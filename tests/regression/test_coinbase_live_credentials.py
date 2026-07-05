from __future__ import annotations

import json
import os
import subprocess

import pytest

from tools import coinbase_live_credentials as credentials


def test_parses_json_and_dotenv_secret_payloads() -> None:
    json_payload = json.dumps(
        {
            "coinbase_api_key": "json-key",
            "coinbase_api_secret": "json-secret",
        }
    )
    dotenv_payload = (
        "COINBASE_API_KEY=dotenv-key\n"
        "COINBASE_API_SECRET='dotenv-secret'\n"
    )

    assert credentials.parse_coinbase_credentials_secret(json_payload) == {
        "COINBASE_API_KEY": "json-key",
        "COINBASE_API_SECRET": "json-secret",
    }
    assert credentials.parse_coinbase_credentials_secret(dotenv_payload) == {
        "COINBASE_API_KEY": "dotenv-key",
        "COINBASE_API_SECRET": "dotenv-secret",
    }


def test_prefers_existing_environment_before_secrets_manager() -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    resolved = credentials.resolve_live_coinbase_credentials(
        {
            "COINBASE_API_KEY": "env-key",
            "COINBASE_API_SECRET": "env-secret",
            "COINBASE_SECRETS_MANAGER_SECRET_ID": "coinbase/live",
        },
        run_secret_lookup=lambda secret_id, region: calls.append((secret_id, ()))
        or "",
    )

    assert resolved.source == "environment"
    assert resolved.credentials["COINBASE_API_KEY"] == "env-key"
    assert resolved.credentials["COINBASE_API_SECRET"] == "env-secret"
    assert calls == []


def test_resolves_credentials_from_explicit_secrets_manager_secret_id() -> None:
    def fake_lookup(secret_id: str, region: str | None) -> str:
        assert secret_id == "coinbase/live"
        assert region == "us-east-1"
        return json.dumps(
            {
                "SecretString": json.dumps(
                    {
                        "COINBASE_API_KEY": "aws-key",
                        "COINBASE_API_SECRET": "aws-secret",
                    }
                )
            }
        )

    resolved = credentials.resolve_live_coinbase_credentials(
        {
            "COINBASE_SECRETS_MANAGER_SECRET_ID": "coinbase/live",
            "COINBASE_SECRETS_MANAGER_REGION": "us-east-1",
        },
        run_secret_lookup=fake_lookup,
    )

    assert resolved.source == "secrets_manager"
    assert resolved.credentials == {
        "COINBASE_API_KEY": "aws-key",
        "COINBASE_API_SECRET": "aws-secret",
    }
    assert resolved.secret_id_env == "COINBASE_SECRETS_MANAGER_SECRET_ID"


def test_ensure_credentials_updates_process_environment_from_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COINBASE_API_KEY", raising=False)
    monkeypatch.delenv("COINBASE_API_SECRET", raising=False)
    monkeypatch.setenv("COINBASE_API_CREDENTIALS_SECRET_ID", "coinbase/live")

    resolved = credentials.ensure_live_coinbase_credentials(
        os.environ,
        run_secret_lookup=lambda secret_id, region: json.dumps(
            {
                "SecretString": json.dumps(
                    {
                        "api_key": "aws-key",
                        "api_secret": "aws-secret",
                    }
                )
            }
        ),
    )

    assert resolved.source == "secrets_manager"
    assert os.environ["COINBASE_API_KEY"] == "aws-key"
    assert os.environ["COINBASE_API_SECRET"] == "aws-secret"


def test_ensure_credentials_fails_closed_without_env_or_secret_id() -> None:
    with pytest.raises(RuntimeError, match="COINBASE_API_KEY, COINBASE_API_SECRET"):
        credentials.ensure_live_coinbase_credentials({})


def test_check_command_reports_redacted_presence_only() -> None:
    result = subprocess.run(
        [
            os.sys.executable,
            "tools/coinbase_live_credentials.py",
            "--check",
        ],
        cwd=credentials.REPO_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "COINBASE_API_KEY": "cli-key-must-not-print",
            "COINBASE_API_SECRET": "cli-secret-must-not-print",
        },
    )

    assert result.returncode == 0
    assert "Coinbase live credential source: environment" in result.stdout
    assert "COINBASE_API_KEY=present" in result.stdout
    assert "COINBASE_API_SECRET=present" in result.stdout
    assert "cli-key-must-not-print" not in result.stdout
    assert "cli-secret-must-not-print" not in result.stdout
