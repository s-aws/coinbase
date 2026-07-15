"""Prepare or consume the single separately authorized Slice 2R6 Preview.

The preparation mode validates the exact immutable R5 chain without creating
an R6 artifact or constructing a Coinbase client.  The confirmation mode is a
separate future operator gate and remains a fixed one-use Preview-only path.
"""

from __future__ import annotations

import argparse
import json
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
    """Build the deliberately option-minimal R6 producer CLI."""

    parser = argparse.ArgumentParser(
        description=(
            "Prepare or run exactly one fixed Default-profile AVAX Futures "
            "Preview; no exchange mutation is possible."
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
        help=(
            "Consume the separately authorized one-use Slice 2R6 Preview "
            "attempt."
        ),
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
    """Prepare R6 or consume its future exact authorization once."""

    parser = build_parser()
    args = parser.parse_args(argv)
    path = production_artifact_path()
    if path.exists() or path.is_symlink():
        print(
            json.dumps(
                _summary_before_attempt(
                    status="blocked",
                    blocker="futures_preview_attempt_already_consumed",
                    path=path,
                    artifact_created=False,
                ),
                sort_keys=True,
            ),
            file=sys.stderr if not args.preflight else sys.stdout,
        )
        return 2
    if args.preflight:
        try:
            predecessor_binding = validate_production_predecessor()
        except FuturesOrderPreviewArtifactError as exc:
            print(
                json.dumps(
                    _summary_before_attempt(
                        status="blocked",
                        blocker=str(exc),
                        path=path,
                        artifact_created=False,
                    ),
                    sort_keys=True,
                )
            )
            return 2
        summary = _summary_before_attempt(
            status="ready",
            blocker=None,
            path=path,
            artifact_created=False,
        )
        summary["predecessor_binding"] = predecessor_binding
        print(json.dumps(summary, sort_keys=True))
        return 0

    store = FuturesOrderPreviewArtifactStore(path)
    producer = FuturesOrderPreviewProducer(
        rest_client=DeferredR6PreviewRestClient(),
        store=store,
        predecessor_binding=dict(FUTURES_PREVIEW_R5_TERMINAL_BINDING),
        predecessor_validator=validate_production_predecessor,
        artifact_type=FUTURES_PREVIEW_R6_ARTIFACT_TYPE,
    )
    try:
        with _suppress_coinbase_sdk_logging():
            evidence = producer.run()
    except FuturesOrderPreviewArtifactError as exc:
        try:
            terminal = store.read_completed()
        except FuturesOrderPreviewArtifactError:
            terminal = None
        if terminal is not None:
            summary = {
                "status": terminal["status"],
                "outcome": terminal["outcome"],
                "blocker": terminal.get("blocker"),
                "artifact_path": str(path),
                "artifact_created": True,
                "attempt_counters": terminal["attempt_counters"],
                "exchange_submission_attempt_count": terminal[
                    "exchange_submission_attempt_count"
                ],
                "live_execution": terminal["live_execution"],
                "submitted_notional_usdc": terminal[
                    "submitted_notional_usdc"
                ],
                "executed_notional_usdc": terminal[
                    "executed_notional_usdc"
                ],
            }
        else:
            summary = {
                "status": "unknown",
                "outcome": "unknown",
                "blocker": (
                    "futures_preview_attempt_consumed_without_terminal_result:"
                    f"{type(exc).__name__}"
                ),
                "artifact_path": str(path),
                "artifact_created": path.exists(),
                "attempt_counters": None,
                "exchange_submission_attempt_count": 0,
                "live_execution": "not_run",
                "submitted_notional_usdc": "0",
                "executed_notional_usdc": "0",
            }
        print(json.dumps(summary, sort_keys=True), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "status": evidence["status"],
                "artifact_path": str(path),
                "product_id": evidence["product_id"],
                "preview_id": evidence["preview_response"]["preview_id"],
                "seal_ready_plan_sha256": evidence[
                    "seal_ready_plan_sha256"
                ],
                "evidence_sha256": evidence["evidence_sha256"],
                "attempt_counters": evidence["attempt_counters"],
                "live_execution": "not_run",
                "submitted_notional_usdc": "0",
                "executed_notional_usdc": "0",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
