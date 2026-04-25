"""
Configuration for external Coinbase API tests.

These tests require valid credentials and should be run separately from other tests.
"""

import pytest
import os
from typing import Optional
from pathlib import Path

from coinbase.rest import RESTClient

from external import CoinbaseRestClient


# ===================== CREDENTIALS =====================

def get_api_key() -> Optional[str]:
    """Get Coinbase API key from environment."""
    return os.environ.get("COINBASE_API_KEY")


def get_api_secret() -> Optional[str]:
    """Get Coinbase API secret from environment."""
    return os.environ.get("COINBASE_API_SECRET")


def get_sandbox_url() -> str:
    """Get Coinbase sandbox URL."""
    return os.environ.get("COINBASE_SANDBOX_URL", "https://api-sandbox.coinbase.com")


# ===================== FIXTURES =====================

@pytest.fixture
def coinbase_credentials():
    """Coinbase API credentials from environment."""
    api_key = get_api_key()
    api_secret = get_api_secret()
    
    if not api_key or not api_secret:
        pytest.skip("Coinbase API credentials not set. Set COINBASE_API_KEY and COINBASE_API_SECRET")
    
    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "sandbox_url": get_sandbox_url()
    }


@pytest.fixture
def coinbase_sandbox_mode() -> bool:
    """Whether to use Coinbase sandbox (test mode)."""
    return os.environ.get("COINBASE_USE_SANDBOX", "true").lower() == "true"


@pytest.fixture
def coinbase_websocket_external_enabled() -> bool:
    """Whether live external websocket tests are explicitly enabled."""
    return os.environ.get("COINBASE_ENABLE_WEBSOCKET_EXTERNAL", "false").lower() == "true"


@pytest.fixture
def coinbase_rest_client(coinbase_credentials, coinbase_sandbox_mode):
    """Authenticated Coinbase REST wrapper for external contract tests."""
    if not coinbase_sandbox_mode:
        pytest.skip("External tests require COINBASE_USE_SANDBOX=true")

    sdk_client = RESTClient(
        api_key=coinbase_credentials["api_key"],
        api_secret=coinbase_credentials["api_secret"],
        rate_limit_headers=True,
    )
    return CoinbaseRestClient(sdk_client)


@pytest.fixture
def api_reference_root(project_root):
    """Path to API contract reference files."""
    return Path(project_root) / "api_reference"


# ===================== MARKERS =====================

def pytest_configure(config):
    """Register Coinbase-specific markers."""
    config.addinivalue_line(
        "markers", "coinbase: Coinbase API tests"
    )
    config.addinivalue_line(
        "markers", "rest_api: Coinbase REST API tests"
    )
    config.addinivalue_line(
        "markers", "websocket: Coinbase WebSocket tests"
    )


# ===================== COLLECTION HOOKS =====================

def pytest_collection_modifyitems(config, items):
    """Add external marker to all tests in this directory."""
    for item in items:
        if "external" in str(item.fspath):
            item.add_marker(pytest.mark.external)
