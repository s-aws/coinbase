# Ops and Diagnostics Agent

## Owns

- `genai_tools/*`
- `docs/archive/*`
- `tools/diagnostics/*`
- root `check_*.py`, `audit_*.py`, `verify_tables.py`, `debug_*.py`
- destructive operational scripts
- historical root-level incident notes until archived or promoted into canonical
  docs

## Canonical Path

Diagnostics gather evidence. Production behavior is extracted into the proper
specialist-owned module only after the canonical path is identified.

## Must Not Do

- Do not productionize `genai_tools/` directly.
- Do not run destructive scripts without explicit approval.
- Do not treat historical notes as current architecture unless they are updated
  into tracked public docs.
