"""Historical Slice 2R6 Coinbase Preview helpers.

The installed command-line entrypoint is source-disabled before artifact,
credential, client, or Coinbase access. Builders remain importable for
synthetic compatibility tests; they grant no current Preview authority.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application.admin_api.futures_order_preview import (  # noqa: E402
    FUTURES_PREVIEW_R5_TERMINAL_BINDING,
    FUTURES_PREVIEW_R6_ARTIFACT_PATH,
    FUTURES_PREVIEW_R6_ARTIFACT_TYPE,
    FuturesOrderPreviewArtifactError,
    FuturesOrderPreviewArtifactStore,
    FuturesOrderPreviewProducer,
    validate_production_futures_order_preview_r5_terminal,
)
from core.coinbase_execution_authority import (  # noqa: E402
    SOURCE_DISABLED_COINBASE_EXECUTION_ERROR,
)
from tools import run_admin_api_futures_no_live_preview_r5 as r5_tool  # noqa: E402


FuturesPreviewOnlyRestClient = r5_tool.FuturesPreviewOnlyRestClient
_suppress_coinbase_sdk_logging = r5_tool._suppress_coinbase_sdk_logging


class DeferredR6PreviewRestClient:
    """Hydrate the fixed Preview-only client only after R6 is claimed."""

    __slots__ = ("__client",)

    def __init__(self) -> None:
        self.__client: FuturesPreviewOnlyRestClient | None = None

    def _get(self) -> FuturesPreviewOnlyRestClient:
        if self.__client is None:
            with _suppress_coinbase_sdk_logging():
                self.__client = build_rest_client()
        return self.__client

    def get_api_key_permissions(self):
        return self._get().get_api_key_permissions()

    def list_portfolios(self):
        return self._get().list_portfolios()

    def get_product_dict(self, product_id: str):
        return self._get().get_product_dict(product_id)

    def get_best_bid_ask(self, *, product_ids: list[str]):
        return self._get().get_best_bid_ask(product_ids=product_ids)

    def get_futures_positions(self):
        return self._get().get_futures_positions()

    def get_futures_margin_collateral_snapshot(self):
        return self._get().get_futures_margin_collateral_snapshot()

    def preview_order(self, **kwargs):
        return self._get().preview_order(**kwargs)


def production_artifact_path() -> Path:
    """Return the fixed R6 path; configuration cannot redirect it."""

    return FUTURES_PREVIEW_R6_ARTIFACT_PATH


def validate_production_predecessor() -> dict[str, object]:
    """Validate exact immutable R5 plus its complete predecessor chain."""

    return validate_production_futures_order_preview_r5_terminal()


def build_parser() -> argparse.ArgumentParser:
    """Build the historical, source-disabled compatibility CLI."""

    parser = argparse.ArgumentParser(
        description=(
            "Historical Slice 2R6 Futures Preview compatibility parser. "
            "The installed command is source-disabled."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "Validate fixed R5 ancestry and report R6 readiness without "
            "credentials, artifact creation, or Coinbase calls."
        ),
    )
    mode.add_argument(
        "--confirm-one-r6-preview",
        action="store_true",
        help="Historical compatibility flag; grants no Preview authority.",
    )
    return parser


def build_rest_client() -> FuturesPreviewOnlyRestClient:
    """Reuse the fixed no-retry, no-redirect Preview-only R5 facade."""

    return r5_tool.build_rest_client()


def _summary_before_attempt(
    *,
    status: str,
    blocker: str | None,
    path: Path,
    artifact_created: bool,
) -> dict[str, object]:
    return {
        "status": status,
        "blocker": blocker,
        "artifact_path": str(path),
        "artifact_created": artifact_created,
        "coinbase_read_ran": False,
        "preview_order_attempt_count": 0,
        "exchange_submission_attempt_count": 0,
        "live_coinbase_execution": "not_run",
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Fail closed before artifact, credential, client, or Coinbase access."""

    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments in (["-h"], ["--help"]):
        parser.parse_args(arguments)
    print(SOURCE_DISABLED_COINBASE_EXECUTION_ERROR, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
