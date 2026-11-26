#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${VENV_DIR:-${project_root}/.venv}/bin/python3.14"

usage() {
    cat <<'EOF'
Usage:
  ./scripts/validate_release.sh

Runs the complete local non-external suite, repository-graph check, and final
Git cleanliness checks. It does not access Coinbase, mutate the runtime
database, push Git commits, or deploy the engine.
EOF
}

fail() {
    printf 'release validation: %s\n' "$*" >&2
    exit 1
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

[[ "$#" -eq 0 ]] || {
    usage >&2
    fail "this command does not accept arguments"
}

[[ -x "${python_bin}" ]] || {
    fail "Python 3.14 environment not found; run ./setup.sh first"
}
"${python_bin}" -c \
    'import sys; raise SystemExit(sys.version_info[:2] != (3, 14))' || {
    fail "${python_bin} must use Python 3.14"
}

cd "${project_root}"

initial_status="$(git status --porcelain=v1 --untracked-files=all)"
[[ -z "${initial_status}" ]] || {
    printf '%s\n' "${initial_status}" >&2
    fail "the release worktree must be clean before validation"
}

branch="$(git symbolic-ref --quiet --short HEAD || printf 'DETACHED')"
head_commit="$(git rev-parse HEAD)"
upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"

printf 'Release branch: %s\n' "${branch}"
printf 'Release commit: %s\n' "${head_commit}"
if [[ -n "${upstream}" ]]; then
    read -r behind ahead < <(
        git rev-list --left-right --count "${upstream}...HEAD"
    )
    printf 'Tracked upstream: %s (ahead=%s behind=%s)\n' \
        "${upstream}" "${ahead}" "${behind}"
else
    printf 'Tracked upstream: none\n'
fi

printf 'Running complete local non-external suite...\n'
"${project_root}/scripts/run_tests.sh"

printf 'Checking repository graph...\n'
"${python_bin}" "${project_root}/codex_repo_graph/build_graph.py" --check

printf 'Checking final diff and worktree...\n'
git diff --check
final_status="$(git status --porcelain=v1 --untracked-files=all)"
[[ -z "${final_status}" ]] || {
    printf '%s\n' "${final_status}" >&2
    fail "validation changed the worktree or found new artifacts"
}

printf 'Release validation passed for %s.\n' "${head_commit}"
