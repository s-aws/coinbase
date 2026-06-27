"""Generate the Admin API OpenAPI schema artifact."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "openapi" / "coinbase-admin-api.yaml"

ROOT_STR = str(ROOT)
if ROOT_STR in sys.path:
    sys.path.remove(ROOT_STR)
sys.path.insert(0, ROOT_STR)

import yaml

from api.v1.app import create_app


def generate_openapi_schema(path: Path = OPENAPI_PATH) -> dict:
    """Generate and write the backend-owned Admin API OpenAPI schema."""

    app = create_app()
    schema = app.openapi()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(schema, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    return schema


def main() -> int:
    generate_openapi_schema()
    print(f"Wrote {OPENAPI_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
