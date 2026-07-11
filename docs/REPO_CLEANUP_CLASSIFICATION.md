# Repo Cleanup Classification

This document defines the cleanup categories for the public repository and
records completed cleanup batches. Do not move, delete, or archive additional
files until the relevant owner accepts the batch and required tests are
identified.

Use the classifier to refresh the current map:

```powershell
python3.13 tools/classify_repo_files.py --format markdown
```

## Current Classification Snapshot

As of 2026-05-17, the major cleanup pressure is in the repository root:

| Category | Count | Default action |
| --- | ---: | --- |
| `root_runtime_entrypoint` | 7 | Keep until a real package-layout refactor |
| `root_ui_candidate` | 11 | Review with Dashboard Contract Agent before moving |
| `root_config` | 5 | Keep in place |
| `public_archive` | 28 | Keep in `docs/archive/v2/` |
| `public_diagnostic_tool` | 24 | Keep in `tools/diagnostics/` |

The clean core is mostly intact:

| Category | Count | Default action |
| --- | ---: | --- |
| `package_code` | 74 | Keep in place |
| `public_tests` | 113 | Keep in place |
| `public_reference_payloads` | 50 | Keep in place |
| `public_docs` | 5 | Keep in `docs/` |
| `public_agent_contract` | 28 | Keep tracked |
| `public_ci_metadata` | 1 | Keep tracked |

## Completed Batches

- 2026-05-17: moved 11 root historical markdown notes into
  `docs/archive/v2/` after reference checks.
- 2026-05-17: moved 12 root diagnostic scripts into `tools/diagnostics/`
  and added a shared repo-root bootstrap for standalone execution.
- 2026-05-17: renamed 11 root `test_*.py` manual/demo scripts into
  `tools/diagnostics/manual_*.py` so they are not accidental pytest inputs.
- 2026-05-17: moved 11 unreferenced experimental UI HTML files into
  `docs/archive/v2/ui-experiments/`.
- 2026-05-17: moved `startup_output.txt` into
  `docs/archive/v2/runtime-output/`.
- 2026-05-17: moved 5 unreferenced `ui_order_span/` JSON exports into
  `docs/archive/v2/ui-order-span/`.
- 2026-05-17: deleted 8 zero-byte root UI placeholders after reference checks
  and explicit approval.
- 2026-05-17: added CI enforcement that rejects new root historical notes,
  diagnostic scripts, root tests, experimental UI files, UI export fixtures,
  empty placeholder artifacts, and runtime output.

## Category Rules

### Keep In Place

- `package_code`: importable runtime packages such as `core/`, `business/`,
  `database/`, `external/`, and `integration/`.
- `public_tests`: test suite under `tests/`.
- `public_reference_payloads`: `api_reference/` and `websocket_reference/`.
- `root_runtime_entrypoint`: active root files such as `main.py`,
  `dashboard_server.py`, `configuration.py`, `order.py`, and `logging_service.py`.

Do not move these as cleanup. Moving them is a package-layout refactor and needs
a separate plan.

### Archive Or Move In Batches

- `root_historical_note`: root-level incident or implementation notes. Move to
  `docs/archive/` only after checking references.
- `public_archive`: historical notes and UI artifacts already moved under
  `docs/archive/`.
- `root_diagnostic_tool`: root-level debug/audit scripts. Move to
  `tools/diagnostics/` or leave local-only in `genai_tools/`.
- `public_diagnostic_tool`: debug/audit scripts already moved under
  `tools/diagnostics/`.
- `root_test_candidate`: root-level `test_*.py`. Either promote to the relevant
  `tests/` layer or archive if duplicate coverage exists.
- `experimental_ui_candidate`: one-off dashboard experiments. Move to a web/docs
  archive after confirming they are not active operator surfaces.

### Delete Only After Confirmation

- `empty_artifact_candidate`: zero-byte UI artifacts. Delete only after checking
  no imports, script tags, or docs reference them.
- `root_runtime_output`: logs or captured output. Stop tracking if currently
  tracked, then keep ignored.

### Review Before Action

- `root_ui_candidate`: active-looking UI files. Dashboard Contract Agent owns
  the decision.
- `ui_fixture_or_export_candidate`: UI input/output JSON artifacts. Decide
  whether they are fixtures, local exports, or archive material.
- `root_hidden_config`: editor/tool config not already classified as approved
  project config. Keep only if it is intentionally public and non-sensitive.
- `unclassified_review`: add a classifier rule before moving.

## Recommended Cleanup Sequence

1. **Archive historical notes - completed 2026-05-17**  
   Move root historical markdown into `docs/archive/` or `docs/archive/v2/`.
   This should not affect runtime imports.

2. **Move diagnostics - completed 2026-05-17**  
   Move root `check_*.py`, `audit_*.py`, `debug_*.py`, and similar scripts into
   `tools/diagnostics/`. Update any docs that reference their old paths.

3. **Triage root tests - completed 2026-05-17**  
   For each root `test_*.py`, decide whether it is obsolete, duplicated by
   regression tests, or should be promoted into `tests/unit`,
   `tests/integration`, or `tests/regression`.

4. **Review UI artifacts - partially completed 2026-05-17**  
   Split active operator UIs from one-off demos. Move experiments to archive.
   Do not move active `ui_*.html` files until dashboard route assumptions are
   checked.

5. **Delete empty artifacts - completed 2026-05-17**  
   Delete zero-byte JS/CSS files only after reference checks.

6. **Add root clutter guard - completed 2026-05-17**  
   After the first cleanup batches, add a CI check that rejects new root-level
   `test_*.py`, `*_FIX.md`, `*_COMPLETE.md`, `debug_*.py`, and runtime output
   files unless explicitly owned.

## Validation Rules

- Documentation-only archive moves may use ownership checks plus link/reference
  checks.
- Moving Python scripts requires at least:

```powershell
python -m py_compile tools/classify_repo_files.py
python3.13 tools/check_ownership.py
python3.13 tools/classify_repo_files.py --quiet --fail-category empty_artifact_candidate --fail-category root_historical_note --fail-category root_diagnostic_tool --fail-category root_test_candidate --fail-category experimental_ui_candidate --fail-category ui_fixture_or_export_candidate --fail-category root_runtime_output
```

- Moving tests or runtime-facing files requires focused coverage for the moved
  behavior. If the move is broad, cross-boundary, or part of durable milestone
  closeout, run the full regression gate:

```powershell
python3.13 tools/run_parallel_regression.py --workers 4
```

Use `pytest tests/regression/ -v --tb=short` only as an intentional sequential
fallback when `pytest-xdist` is unavailable.

- Any active UI move requires a Dashboard Contract Agent review and focused UI
  regression tests where available.
