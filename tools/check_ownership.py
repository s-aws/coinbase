"""Check changed files against the public ownership manifest.

The parser intentionally supports only the small YAML subset used by
``.agents/ownership.yaml`` so the tool has no third-party dependency.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".agents" / "ownership.yaml"


def _run_git(args: List[str]) -> List[str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return []
    if proc.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def _changed_files(base: Optional[str]) -> List[str]:
    seen = set()
    files: List[str] = []

    commands: List[List[str]]
    if base:
        commands = [["diff", "--name-only", base, "--"]]
    else:
        commands = [
            ["diff", "--name-only", "--cached", "--"],
            ["diff", "--name-only", "--"],
            ["ls-files", "--others", "--exclude-standard"],
        ]

    for cmd in commands:
        for path in _run_git(cmd):
            if path not in seen:
                seen.add(path)
                files.append(path)
    return files


def _parse_manifest(path: Path) -> Dict[str, Dict[str, List[str] | str | bool]]:
    owners: Dict[str, Dict[str, List[str] | str | bool]] = {}
    current_owner: Optional[str] = None
    current_list: Optional[str] = None
    in_owners = False

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line:
            continue
        stripped = line.strip()

        if stripped == "owners:":
            in_owners = True
            continue
        if not in_owners:
            continue

        if raw.startswith("  ") and not raw.startswith("    ") and stripped.endswith(":"):
            current_owner = stripped[:-1]
            owners[current_owner] = {"owns": [], "tests": []}
            current_list = None
            continue

        if current_owner is None:
            continue

        if raw.startswith("    ") and not raw.startswith("      "):
            if stripped.endswith(":"):
                key = stripped[:-1]
                current_list = key
                if key not in owners[current_owner]:
                    owners[current_owner][key] = []
            elif ":" in stripped:
                key, value = stripped.split(":", 1)
                value = value.strip().strip('"').strip("'")
                if value.lower() == "true":
                    owners[current_owner][key] = True
                elif value.lower() == "false":
                    owners[current_owner][key] = False
                else:
                    owners[current_owner][key] = value
                current_list = None
            continue

        if raw.startswith("      - ") and current_list:
            item = stripped[2:].strip().strip('"').strip("'")
            owners[current_owner].setdefault(current_list, [])
            values = owners[current_owner][current_list]
            if isinstance(values, list):
                values.append(item)

    return owners


def _matches(path: str, pattern: str) -> bool:
    normalized = path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    return fnmatch.fnmatchcase(normalized, pattern)


def owners_for_file(path: str, owners: Dict[str, Dict[str, List[str] | str | bool]]) -> List[str]:
    matches: List[str] = []
    for owner, config in owners.items():
        patterns = []
        owns = config.get("owns", [])
        test_owns = config.get("test_owns", [])
        if isinstance(owns, list):
            patterns.extend(owns)
        if isinstance(test_owns, list):
            patterns.extend(test_owns)
        if any(_matches(path, pattern) for pattern in patterns):
            matches.append(owner)
    return matches


def _print_owner_summary(owner: str, config: Dict[str, List[str] | str | bool]) -> None:
    context = config.get("context", "")
    tests = config.get("tests", [])
    regression = config.get("requires_regression", True)
    print(f"{owner}")
    if context:
        print(f"  context: {context}")
    print(f"  requires_regression: {str(regression).lower()}")
    if isinstance(tests, list) and tests:
        print("  tests:")
        for test in tests:
            print(f"    - {test}")


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", help="Require all changed files to belong to this owner")
    parser.add_argument("--base", help="Compare changed files against a git ref")
    parser.add_argument("--list", action="store_true", help="List owners and focused tests")
    parser.add_argument("files", nargs="*", help="Explicit files to check")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not MANIFEST.exists():
        print(f"missing ownership manifest: {MANIFEST}", file=sys.stderr)
        return 2

    owners = _parse_manifest(MANIFEST)

    if args.list:
        for owner in sorted(owners):
            _print_owner_summary(owner, owners[owner])
        return 0

    files = [p.replace("\\", "/") for p in args.files] if args.files else _changed_files(args.base)
    if not files:
        print("No changed files found.")
        return 0

    failures = 0
    for path in files:
        matched = owners_for_file(path, owners)
        if not matched:
            print(f"UNOWNED {path}")
            failures += 1
            continue
        if args.owner and args.owner not in matched:
            print(f"WRONG_OWNER {path} expected={args.owner} actual={','.join(matched)}")
            failures += 1
            continue
        label = ",".join(matched)
        print(f"OK {path} owner={label}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
