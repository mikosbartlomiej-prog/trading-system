#!/bin/bash
# Acceptance verification script for 2026-05-18 audit fixes
# Run this AFTER 2026-05-19 04:00 UTC daily-learning to see if fixes worked.
#
# Usage: cd ~/Documents/Git/trading-system && bash journal/audit-baselines/2026-05-19_verify.sh

set +e   # don't bail on individual check failures
cd "$(dirname "$0")/../.."

echo "=================================================="
echo "  Audit fix verification — 2026-05-18 → 2026-05-19"
echo "=================================================="
echo ""

# Pull latest
echo "→ Pulling latest from origin/main..."
git fetch origin main 2>&1 | tail -1
git pull --ff-only origin main 2>&1 | tail -1
echo ""

TODAY=$(date -u +%Y-%m-%d)
HISTORY="learning-loop/history/${TODAY}.md"

# ──── Check 1: Senior PM 3-round dialog ─────────────────
echo "─── CHECK 1: Senior PM 3-round dialog (P0 #2 fix) ───"
if [ -f "$HISTORY" ]; then
    if grep -q "LLM\[high\]" "$HISTORY"; then
        echo "  ✅ PASS  LLM[high] tag present in history"
    elif grep -q "LLM\[low\]" "$HISTORY"; then
        echo "  ❌ FAIL  Still LLM[low] — Challenger/Revise rounds did not fire"
        echo "       inspect: cat $HISTORY | grep '^- 2026'"
    else
        echo "  ⚠️  PARTIAL  No LLM tag found — Senior PM may not have run at all"
    fi

    if grep -qE "Challenger|critique|SURVIVED|MODIFIED|REJECTED" "$HISTORY"; then
        echo "  ✅ PASS  Challenger output detected"
    else
        echo "  ❌ FAIL  No Challenger section in history"
    fi

    if grep -qE "revision_log|DEFENDED|ACCEPTED|MODIFIED|ADDED" "$HISTORY"; then
        echo "  ✅ PASS  revision_log entries detected"
    else
        echo "  ❌ FAIL  No revision_log — Senior PM round 3 revise did not fire"
    fi
else
    echo "  ⚠️  History file missing — daily-learning may not have run"
fi
echo ""

# ──── Check 2: routine_budget records all 3 rounds ──────
echo "─── CHECK 2: Routine budget tracking (P0 #2 fix) ────"
python3 - <<'PYEOF'
import json
try:
    s = json.load(open('learning-loop/runtime_state.json'))
    rb = s.get('routine_budget', {})
    print(f"  date:       {rb.get('date')}")
    print(f"  total:      {rb.get('total', 0)}")
    print(f"  by_routine: {json.dumps(rb.get('by_routine', {}))}")
    print(f"  by_tier:    {json.dumps(rb.get('by_tier', {}))}")
    pm   = rb.get('by_routine', {}).get('daily-learning-pm', 0)
    chal = rb.get('by_routine', {}).get('daily-learning-challenger', 0)
    rev  = rb.get('by_routine', {}).get('daily-learning-revise', 0)
    p2   = rb.get('by_tier', {}).get('P2_optional', 0)
    print()
    if pm >= 2:
        print(f"  ✅ PASS  daily-learning-pm: {pm} (≥2 — round 1 + round 3 revise)")
    else:
        print(f"  ❌ FAIL  daily-learning-pm: {pm} (expected ≥2)")
    if chal >= 1:
        print(f"  ✅ PASS  daily-learning-challenger: {chal} (round 2 ran!)")
    else:
        print(f"  ❌ FAIL  daily-learning-challenger: {chal} (expected ≥1)")
    if rev >= 1:
        print(f"  ✅ PASS  daily-learning-revise: {rev}")
    elif pm >= 2:
        print(f"  ⚠️  PARTIAL  revise possibly counted under daily-learning-pm")
    else:
        print(f"  ❌ FAIL  daily-learning-revise: {rev}")
    if p2 <= 4:
        print(f"  ✅ PASS  P2_optional: {p2}/4 cap enforced")
    else:
        print(f"  ❌ FAIL  P2_optional: {p2} > cap of 4 — curator state not persisted?")
except Exception as e:
    print(f"  ⚠️  Could not read runtime_state.json: {e}")
PYEOF
echo ""

# ──── Check 3: fill_rate diagnostics surfaced ───────────
echo "─── CHECK 3: fill_rate.unknown diagnostics (P2 #1) ──"
if [ -f "$HISTORY" ]; then
    if grep -q "sample_open_ids\|sample_open_symbols" "$HISTORY"; then
        echo "  ✅ PASS  sample_open_ids/symbols surfaced in history"
    else
        if grep -q "fill_rate.unknown\|fill rate 0%" "$HISTORY"; then
            echo "  ⚠️  PARTIAL  unknown bucket still showing, but no sample data — possibly Senior PM didn't render it"
        else
            echo "  ✅ PASS  No fill_rate.unknown alert (problem resolved)"
        fi
    fi
fi
echo ""

# ──── Check 4: Allocator idempotency ─────────────────────
echo "─── CHECK 4: Allocator idempotency guard (P0 #1) ────"
EXEC_FILE="learning-loop/allocations/${TODAY}.execution.json"
if [ -f "$EXEC_FILE" ]; then
    python3 - <<PYEOF
import json
try:
    d = json.load(open("$EXEC_FILE"))
    print(f"  executed_at: {d.get('executed_at')}")
    print(f"  n_placed: {d.get('n_placed')}  n_failed: {d.get('n_failed')}")
    syms = [r['symbol'] for r in d.get('results', [])]
    dupes = [s for s in set(syms) if syms.count(s) > 1]
    if dupes:
        print(f"  ❌ FAIL  Duplicate symbol orders in execution.json: {dupes}")
    else:
        print(f"  ✅ PASS  No duplicate symbol orders")
except Exception as e:
    print(f"  ⚠️  Could not parse: {e}")
PYEOF

    LOG_FILE="learning-loop/allocations/${TODAY}.log"
    if [ -f "$LOG_FILE" ] && grep -q "IDEMPOTENCY GUARD" "$LOG_FILE"; then
        echo "  ✅ INFO  Idempotency guard triggered at least once (good — duplicate calls handled)"
    fi
fi
echo ""

# ──── Check 5: Alpaca rejection skip-if-open-order ──────
echo "─── CHECK 5: BUY skip-if-open-order (P1 fix) ────────"
if [ -f "$EXEC_FILE" ]; then
    if grep -q "BUY skipped.*existing open" "$EXEC_FILE" 2>/dev/null; then
        echo "  ✅ INFO  Skip-if-open-order fired (correctly prevented duplicate BUY)"
    fi
    if grep -q "Alpaca rejected" "$EXEC_FILE" 2>/dev/null; then
        echo "  ⚠️  Alpaca rejection still happened — may be different cause"
    fi
fi
echo ""

# ──── Check 6: weekly-retro fail-soft (next Sunday) ─────
echo "─── CHECK 6: weekly-retro fail-soft (P2 #2) ─────────"
NEXT_SUNDAY_FILE=$(ls -t learning-loop/weekly-retros/*.md 2>/dev/null | head -1)
if [ -n "$NEXT_SUNDAY_FILE" ]; then
    echo "  Latest retro: $(basename $NEXT_SUNDAY_FILE) ($(stat -c %y $NEXT_SUNDAY_FILE 2>/dev/null || stat -f '%Sm' $NEXT_SUNDAY_FILE))"
    echo "  (Verify after next Sunday 22:00 UTC cron — fix only matters there)"
fi
echo ""

# ──── Summary ─────────────────────────────────────────────
echo "=================================================="
echo "  Compare with baseline:"
echo "  journal/audit-baselines/2026-05-18_pre-fix-baseline.md"
echo "=================================================="
