"""System discovery — walks the repo and reports modules / tests / workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .coverage_model import CAPABILITIES, Capability


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@dataclass
class DiscoveryResult:
    monitors:       list[str]
    shared_modules: list[str]
    learning_loop:  list[str]
    scripts:        list[str]
    workflows:      list[str]
    tests:          list[str]
    capability_status: dict[str, dict]    # id → {module_exists, tests_present, ...}


def discover(root: Path | None = None) -> DiscoveryResult:
    r = root or repo_root()

    monitors = []
    for d in r.iterdir():
        if d.is_dir() and d.name.endswith("-monitor") and (d / "monitor.py").exists():
            monitors.append(d.name)
    monitors = sorted(monitors)

    shared_modules = sorted(p.name for p in (r / "shared").glob("*.py")
                             if p.name != "__init__.py")
    learning_loop = sorted(p.name for p in (r / "learning-loop").glob("*.py")
                            if p.name != "__init__.py")
    scripts = sorted(p.name for p in (r / "scripts").glob("*.py")
                      if p.name != "__init__.py")
    workflows = sorted(p.name for p in (r / ".github" / "workflows").glob("*.yml"))

    tests = []
    for tests_dir in [r / "tests", r / "learning-loop"]:
        if tests_dir.exists():
            for p in tests_dir.rglob("test_*.py"):
                tests.append(str(p.relative_to(r)))
    tests = sorted(set(tests))

    capability_status = {}
    for c in CAPABILITIES:
        module_exists = True
        if c.module_path:
            mp = r / c.module_path
            module_exists = mp.exists()
        tests_present = []
        for glob in c.expected_tests:
            for path in tests:
                if path == glob or path.endswith("/" + glob.split("/")[-1]) or path == glob.lstrip("./"):
                    tests_present.append(path)
        # also check explicit file existence
        for glob in c.expected_tests:
            if (r / glob).exists() and glob not in tests_present:
                tests_present.append(glob)
        capability_status[c.id] = {
            "area":            c.area,
            "module_path":     c.module_path,
            "module_exists":   module_exists,
            "expected_tests":  list(c.expected_tests),
            "tests_present":   sorted(set(tests_present)),
            "tests_missing":   [g for g in c.expected_tests
                                 if not (r / g).exists()],
            "description":     c.description,
        }

    return DiscoveryResult(
        monitors=monitors,
        shared_modules=shared_modules,
        learning_loop=learning_loop,
        scripts=scripts,
        workflows=workflows,
        tests=tests,
        capability_status=capability_status,
    )
