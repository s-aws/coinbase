"""Generate the Admin API OpenAPI schema artifact."""

from __future__ import annotations

import argparse
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


def build_openapi_schema() -> dict:
    """Build the backend-owned Admin API OpenAPI schema."""

    app = create_app()
    return app.openapi()


def serialize_openapi_schema(schema: dict) -> str:
    """Return the canonical YAML representation of an OpenAPI schema."""

    return yaml.safe_dump(schema, sort_keys=False, allow_unicode=False)


def generate_openapi_schema(path: Path = OPENAPI_PATH) -> dict:
    """Generate and write the backend-owned Admin API OpenAPI schema."""

    schema = build_openapi_schema()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_openapi_schema(schema), encoding="utf-8")
    return schema


def openapi_schema_file_is_current(path: Path = OPENAPI_PATH) -> bool:
    """Return whether the checked-in OpenAPI schema matches generated output."""

    if not path.exists():
        return False
    expected = serialize_openapi_schema(build_openapi_schema())
    actual = path.read_text(encoding="utf-8")
    return actual == expected


def build_parser() -> argparse.ArgumentParser:
    """Build the Admin API OpenAPI generator CLI parser."""

    parser = argparse.ArgumentParser(
        description="Generate or check the backend-owned Admin API OpenAPI schema.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the checked-in OpenAPI schema is stale.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        if openapi_schema_file_is_current():
            print(f"Admin API OpenAPI schema is current: {OPENAPI_PATH}")
            return 0
        print(
            "Admin API OpenAPI schema is stale; run "
            "python tools/generate_admin_api_openapi.py",
            file=sys.stderr,
        )
        return 1

    generate_openapi_schema()
    print(f"Wrote {OPENAPI_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
