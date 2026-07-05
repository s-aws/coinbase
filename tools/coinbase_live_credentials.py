"""Backend-only Coinbase live credential resolution.

Credentials are consumed only by backend/admin smoke tools. This helper can
hydrate the current process from AWS Secrets Manager without printing or
persisting secret values.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_COINBASE_CREDENTIAL_ENV = ("COINBASE_API_KEY", "COINBASE_API_SECRET")
SECRET_ID_ENV_NAMES = (
    "COINBASE_SECRETS_MANAGER_SECRET_ID",
    "COINBASE_API_CREDENTIALS_SECRET_ID",
    "COINBASE_LIVE_CREDENTIALS_SECRET_ID",
)
SECRET_REGION_ENV_NAMES = (
    "COINBASE_SECRETS_MANAGER_REGION",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
)
KEY_ALIASES = (
    "COINBASE_API_KEY",
    "coinbase_api_key",
    "api_key",
    "key",
)
SECRET_ALIASES = (
    "COINBASE_API_SECRET",
    "coinbase_api_secret",
    "api_secret",
    "secret",
    "private_key",
)
SecretLookup = Callable[[str, str | None], str]


@dataclass(frozen=True)
class CoinbaseCredentialResolution:
    """Redacted credential resolution metadata plus in-memory values."""

    source: str
    credentials: dict[str, str]
    missing: tuple[str, ...] = ()
    secret_id_env: str | None = None


def ensure_live_coinbase_credentials(
    environ: MutableMapping[str, str] | None = None,
    *,
    run_secret_lookup: SecretLookup | None = None,
) -> CoinbaseCredentialResolution:
    """Ensure live Coinbase credentials exist in the supplied environment."""

    target = environ if environ is not None else os.environ
    resolved = resolve_live_coinbase_credentials(
        target,
        run_secret_lookup=run_secret_lookup,
    )
    if resolved.missing:
        raise RuntimeError(
            f"Live Coinbase credentials require {', '.join(LIVE_COINBASE_CREDENTIAL_ENV)} "
            f"in the environment or one of {', '.join(SECRET_ID_ENV_NAMES)} "
            "pointing at an AWS Secrets Manager secret."
        )

    for key, value in resolved.credentials.items():
        target[key] = value
    return resolved


def resolve_live_coinbase_credentials(
    environ: Mapping[str, str],
    *,
    run_secret_lookup: SecretLookup | None = None,
) -> CoinbaseCredentialResolution:
    """Resolve credentials from env first, then from an explicit secret id."""

    current = {
        "COINBASE_API_KEY": _string_value(environ.get("COINBASE_API_KEY")),
        "COINBASE_API_SECRET": _string_value(environ.get("COINBASE_API_SECRET")),
    }
    if _credentials_complete(current):
        return CoinbaseCredentialResolution(source="environment", credentials=current)

    secret_id_env, secret_id = _first_env_value(environ, SECRET_ID_ENV_NAMES)
    if not secret_id_env or not secret_id:
        return CoinbaseCredentialResolution(
            source="missing",
            credentials={},
            missing=_missing_credentials(current),
        )

    _, region = _first_env_value(environ, SECRET_REGION_ENV_NAMES)
    lookup = run_secret_lookup or _lookup_secret_with_aws_cli
    credentials = parse_coinbase_credentials_secret(lookup(secret_id, region))
    if not _credentials_complete(credentials):
        raise RuntimeError(
            "Coinbase Secrets Manager payload must contain "
            f"{', '.join(LIVE_COINBASE_CREDENTIAL_ENV)} values or supported aliases."
        )

    return CoinbaseCredentialResolution(
        source="secrets_manager",
        credentials=credentials,
        secret_id_env=secret_id_env,
    )


def parse_coinbase_credentials_secret(secret_value: str) -> dict[str, str]:
    """Parse AWS, JSON, or dotenv-shaped Coinbase credential payloads."""

    payload = str(secret_value or "").strip()
    if not payload:
        return {}

    parsed = _json_object(payload)
    if parsed is not None:
        secret_string = _string_value(parsed.get("SecretString"))
        if secret_string:
            return parse_coinbase_credentials_secret(secret_string)

        secret_binary = _string_value(parsed.get("SecretBinary"))
        if secret_binary:
            decoded = base64.b64decode(secret_binary).decode("utf-8")
            return parse_coinbase_credentials_secret(decoded)

        return _credentials_from_mapping(parsed)

    return _credentials_from_mapping(_parse_dotenv(payload))


def _lookup_secret_with_aws_cli(secret_id: str, region: str | None) -> str:
    args = [
        "secretsmanager",
        "get-secret-value",
        "--secret-id",
        secret_id,
        "--output",
        "json",
    ]
    if region:
        args.extend(["--region", region])

    try:
        completed = subprocess.run(
            ["aws", *args],
            cwd=REPO_ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "AWS CLI is required to load Coinbase credentials from Secrets Manager."
        ) from exc

    if completed.returncode != 0:
        raise RuntimeError(
            "AWS Secrets Manager Coinbase credential lookup failed. Verify the "
            "configured secret id, IAM access, and AWS region."
        )
    return completed.stdout


def _credentials_from_mapping(mapping: Mapping[str, Any]) -> dict[str, str]:
    api_key = _first_mapping_value(mapping, KEY_ALIASES)
    api_secret = _first_mapping_value(mapping, SECRET_ALIASES)
    credentials: dict[str, str] = {}
    if api_key:
        credentials["COINBASE_API_KEY"] = api_key
    if api_secret:
        credentials["COINBASE_API_SECRET"] = api_secret
    return credentials


def _parse_dotenv(payload: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in payload.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        parsed[key.strip()] = _unquote(raw_value.strip())
    return parsed


def _json_object(payload: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _first_mapping_value(mapping: Mapping[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        value = _string_value(mapping.get(name))
        if value:
            return value
    return ""


def _first_env_value(
    environ: Mapping[str, str],
    names: tuple[str, ...],
) -> tuple[str | None, str]:
    for name in names:
        value = _string_value(environ.get(name))
        if value:
            return name, value
    return None, ""


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _credentials_complete(credentials: Mapping[str, str]) -> bool:
    return all(_string_value(credentials.get(key)) for key in LIVE_COINBASE_CREDENTIAL_ENV)


def _missing_credentials(credentials: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        key
        for key in LIVE_COINBASE_CREDENTIAL_ENV
        if not _string_value(credentials.get(key))
    )


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check backend Coinbase live credential availability without printing secrets."
    )
    parser.add_argument("--check", action="store_true", help="Report redacted presence.")
    args = parser.parse_args()
    if not args.check:
        parser.error("only --check is supported")

    resolved = ensure_live_coinbase_credentials(os.environ)
    print(f"Coinbase live credential source: {resolved.source}")
    for key in LIVE_COINBASE_CREDENTIAL_ENV:
        print(f"{key}=present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
