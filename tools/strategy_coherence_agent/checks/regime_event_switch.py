"""Spec §7 — Event Switch / regime-aware strategy.

Required regimes: RISK_ON, INFLATION_SHOCK, RISK_OFF, NEUTRAL. Each must
have allowed_buckets, size_multiplier, fallback / defensive bucket and
options policy. RISK_OFF must shrink sizing WITHOUT silently locking the
system out of full deployment.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Evidence, Finding
from ..utils import read_json, read_text, rel


CATEGORY  = "regime_event_switch"
PRINCIPLE = "REGIME_AWARE_STRATEGY"

REQUIRED_REGIMES = ("RISK_ON", "INFLATION_SHOCK", "RISK_OFF", "NEUTRAL")
REQUIRED_BUCKET_FIELDS = ("allowed_buckets", "size_multiplier")


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    # 1. shared/regime.py exists
    reg_path = root / "shared" / "regime.py"
    if not reg_path.exists():
        out.append(Finding(
            id="REG_MODULE_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="shared/regime.py is missing — strategy has no regime detector.",
            recommendation="Add shared/regime.py with detect_regime().",
        ))
        return out

    text = read_text(reg_path)
    missing_states = [r for r in REQUIRED_REGIMES if r not in text]
    if missing_states:
        out.append(Finding(
            id="REG_STATES_INCOMPLETE",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message=f"shared/regime.py missing states: {', '.join(missing_states)}.",
            expected="All 4: " + ", ".join(REQUIRED_REGIMES),
            observed="missing: " + ", ".join(missing_states),
            recommendation="Define the missing regime states.",
            evidence=[Evidence(file=str(rel(reg_path)))],
        ))
    else:
        out.append(Finding(
            id="REG_STATES_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="All 4 regimes declared.",
        ))

    # 2. Detection mode
    cfg_path = root / "config" / "aggressive_profile.json"
    cfg = read_json(cfg_path) or {}
    rcfg = (cfg.get("regime") or {}) if isinstance(cfg, dict) else {}
    mode = rcfg.get("detection_mode")
    if mode not in ("hybrid", "auto", "manual"):
        out.append(Finding(
            id="REG_DETECTION_MODE_UNSET",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"regime.detection_mode = {mode!r} (expected hybrid/auto/manual).",
            recommendation="Set detection_mode: hybrid in aggressive_profile.json.",
            evidence=[Evidence(file=str(rel(cfg_path)))],
        ))
    else:
        out.append(Finding(
            id="REG_DETECTION_MODE_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message=f"regime.detection_mode = {mode}.",
        ))

    # 3. buckets_per_regime block — every regime declared
    buckets = (cfg.get("buckets_per_regime") or {}) if isinstance(cfg, dict) else {}
    missing_regime_blocks = [r for r in REQUIRED_REGIMES if r not in buckets]
    if missing_regime_blocks:
        out.append(Finding(
            id="REG_BUCKET_BLOCKS_INCOMPLETE",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message=f"buckets_per_regime missing: {', '.join(missing_regime_blocks)}.",
            expected="One block per regime",
            observed=f"present: {sorted(buckets)}",
            recommendation="Add the missing regime blocks with allowed_buckets + size_multiplier.",
            evidence=[Evidence(file=str(rel(cfg_path)))],
        ))
    else:
        out.append(Finding(
            id="REG_BUCKET_BLOCKS_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="buckets_per_regime declares all 4 regimes.",
        ))

    # 4. Each block has allowed_buckets + size_multiplier
    for r in REQUIRED_REGIMES:
        block = buckets.get(r) or {}
        if not block:
            continue
        miss = [f for f in REQUIRED_BUCKET_FIELDS if f not in block]
        if miss:
            out.append(Finding(
                id=f"REG_{r}_FIELDS_INCOMPLETE",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message=f"buckets_per_regime.{r} missing fields: {', '.join(miss)}.",
                recommendation="Add allowed_buckets and size_multiplier.",
                evidence=[Evidence(file=str(rel(cfg_path)))],
            ))

    # 5. RISK_OFF: size_multiplier may shrink, but allowed_buckets must
    # still include a defensive bucket (hedge_metals / hedge_bonds) so
    # idle cash can be deployed to defensives instead of sitting flat.
    ro = buckets.get("RISK_OFF") or {}
    ro_buckets = ro.get("allowed_buckets") or []
    defensive_options = ("hedge_metals", "hedge_bonds", "defensive_fallback",
                         "defense_etf")
    has_defensive = any(b in ro_buckets for b in defensive_options)
    if not has_defensive:
        out.append(Finding(
            id="REG_RISK_OFF_NO_DEFENSIVE_FALLBACK",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message="RISK_OFF has no defensive fallback bucket — system will "
                    "silently sit on idle cash, breaking full-deployment contract.",
            expected="allowed_buckets containing hedge_metals / hedge_bonds / defensive_fallback",
            observed=f"allowed_buckets: {ro_buckets}",
            recommendation="Add hedge_metals + hedge_bonds to RISK_OFF.allowed_buckets.",
            evidence=[Evidence(file=str(rel(cfg_path)))],
        ))
    else:
        out.append(Finding(
            id="REG_RISK_OFF_HAS_FALLBACK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message=f"RISK_OFF fallback buckets present: {[b for b in defensive_options if b in ro_buckets]}",
        ))

    # 6. INFLATION_SHOCK: must include inflation_energy or equivalent
    inf = buckets.get("INFLATION_SHOCK") or {}
    inf_buckets = inf.get("allowed_buckets") or []
    if not any(b in inf_buckets for b in ("inflation_energy", "energy", "hedge_metals")):
        out.append(Finding(
            id="REG_INFLATION_SHOCK_NO_ROTATION",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="INFLATION_SHOCK has no inflation_energy / hedge_metals bucket.",
            recommendation="Add inflation_energy + hedge_metals to INFLATION_SHOCK.",
            evidence=[Evidence(file=str(rel(cfg_path)))],
        ))

    # 7. Wiring: price-monitor / allocator consult regime
    consumers_ok = 0
    for c in ("price-monitor/monitor.py", "shared/allocator.py"):
        p = root / c
        if p.exists() and ("from regime" in read_text(p) or "detect_regime" in read_text(p)):
            consumers_ok += 1
    if consumers_ok == 0:
        out.append(Finding(
            id="REG_NO_CONSUMER_WIRED",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message="No monitor or allocator imports shared.regime — the regime "
                    "module exists but is dead code.",
            recommendation="Wire detect_regime() into price-monitor and allocator.",
        ))
    elif consumers_ok == 1:
        out.append(Finding(
            id="REG_PARTIAL_CONSUMER_WIRING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="Only one consumer wires the regime module (price-monitor or allocator).",
            recommendation="Wire the regime into both price-monitor and allocator.",
        ))
    else:
        out.append(Finding(
            id="REG_CONSUMERS_WIRED",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="Both price-monitor and allocator import shared.regime.",
        ))

    return out
