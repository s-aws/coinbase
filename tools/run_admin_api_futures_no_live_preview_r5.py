"""Historical Slice 2R5 Coinbase Preview helpers.

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
    FUTURES_PREVIEW_R5_ARTIFACT_PATH,
    FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
    FUTURES_PREVIEW_R4_PREDECESSOR_BINDING,
    FuturesOrderPreviewArtifactError,
    FuturesOrderPreviewArtifactStore,
    FuturesOrderPreviewProducer,
    validate_production_futures_order_preview_r4_predecessor,
)
from core.coinbase_execution_authority import (  # noqa: E402
    SOURCE_DISABLED_COINBASE_EXECUTION_ERROR,
)
from tools import run_admin_api_futures_no_live_preview as r4_tool  # noqa: E402


FuturesPreviewOnlyRestClient = r4_tool.FuturesPreviewOnlyRestClient
_suppress_coinbase_sdk_logging = r4_tool._suppress_coinbase_sdk_logging


class DeferredR5PreviewRestClient:
    """Hydrate the fixed client only after the producer has claimed R5."""

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
    """Return the fixed R5 one-attempt path; environment cannot redirect it."""

    return FUTURES_PREVIEW_R5_ARTIFACT_PATH


def validate_production_predecessor() -> dict[str, object]:
    """Validate immutable R4 plus its complete predecessor chain."""

    return validate_production_futures_order_preview_r4_predecessor()


def build_parser() -> argparse.ArgumentParser:
    """Build the historical, source-disabled compatibility CLI."""

    parser = argparse.ArgumentParser(
        description=(
            "Historical Slice 2R5 Futures Preview compatibility parser. "
            "The installed command is source-disabled."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "Report fixed-path consumption state without credentials or "
            "Coinbase calls."
        ),
    )
    mode.add_argument(
        "--confirm-one-r5-preview",
        action="store_true",
        help="Historical compatibility flag; grants no Preview authority.",
    )
    return parser


def build_rest_client() -> FuturesPreviewOnlyRestClient:
    """Build the fixed Default client and reject SDK method fallback."""

    client = r4_tool.build_rest_client()
    delegate = getattr(
        client,
        "_FuturesPreviewOnlyRestClient__delegate",
        None,
    )
    sdk_client = getattr(delegate, "_client", None)
    required_sdk_methods = {
        "get_api_key_permissions",
        "get_portfolios",
        "get_product",
        "get_best_bid_ask",
        "list_futures_positions",
        "get_futures_balance_summary",
        "get_intraday_margin_setting",
        "get_current_margin_window",
        "list_futures_sweeps",
        "preview_order",
    }
    if sdk_client is None or any(
        not callable(getattr(sdk_client, method, None))
        for method in required_sdk_methods
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview fixed SDK read surface is unavailable"
        )
    session = getattr(sdk_client, "session", None)
    adapters = getattr(session, "adapters", None)
    if not isinstance(adapters, dict) or not adapters:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R5 transport policy is unavailable"
        )
    for adapter in adapters.values():
        policy = getattr(adapter, "max_retries", None)
        if (
            getattr(policy, "total", None) != 0
            or any(
                getattr(policy, dimension, None) not in {None, 0, False}
                for dimension in (
                    "connect",
                    "read",
                    "redirect",
                    "status",
                    "other",
                )
            )
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R5 transport retry policy is not zero"
            )
    if getattr(session, "max_redirects", None) != 0:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R5 transport redirect policy is not zero"
        )
    return client


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
