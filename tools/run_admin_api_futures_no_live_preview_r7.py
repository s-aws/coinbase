"""Retain the historical Slice 2R7 producer in a terminally disabled state.

R7 consumed its sole Preview-call authority. Both CLI modes now fail closed
before claim construction, credential hydration, client construction, or any
Coinbase call. Historical preparation and producer paths remain testable only
through an explicit in-process test override.
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
    FUTURES_PREVIEW_R6_TERMINAL_BINDING,
    FUTURES_PREVIEW_R7_ARTIFACT_PATH,
    FUTURES_PREVIEW_R7_ARTIFACT_TYPE,
    FUTURES_PREVIEW_R7_RESPONSE_SCHEMA_BINDING,
    FuturesOrderPreviewArtifactError,
    FuturesOrderPreviewArtifactStore,
    FuturesOrderPreviewProducer,
    _validate_r7_claim_record,
    validate_production_futures_order_preview_r6_terminal,
)
from tools import run_admin_api_futures_no_live_preview_r6 as r6_tool  # noqa: E402


FuturesPreviewOnlyRestClient = r6_tool.FuturesPreviewOnlyRestClient
_suppress_coinbase_sdk_logging = r6_tool._suppress_coinbase_sdk_logging
R7_PREVIEW_CALL_AUTHORITY_ACTIVE = False


class DeferredR7PreviewRestClient:
    """Hydrate the fixed Preview-only client only after R7 is claimed."""

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
    """Return the fixed R7 path; configuration cannot redirect it."""

    return FUTURES_PREVIEW_R7_ARTIFACT_PATH


def validate_production_predecessor() -> dict[str, object]:
    """Validate consumed R6 plus its complete immutable predecessor chain."""

    return validate_production_futures_order_preview_r6_terminal()


def build_parser() -> argparse.ArgumentParser:
    """Build the deliberately option-minimal R7 producer CLI."""

    parser = argparse.ArgumentParser(
        description=(
            "Historical fixed Default-profile AVAX Futures R7 producer. "
            "R7 is consumed and all modes fail closed without Coinbase access."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "Report the consumed R7 authority without credentials, artifact "
            "creation, or Coinbase calls."
        ),
    )
    mode.add_argument(
        "--confirm-one-r7-preview",
        action="store_true",
        help="Report that the one-use Slice 2R7 Preview authority is consumed.",
    )
    return parser


def build_rest_client() -> FuturesPreviewOnlyRestClient:
    """Reuse the fixed no-retry, no-redirect Preview-only facade."""

    return r6_tool.build_rest_client()


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


def _validate_fresh_claim_contract(path: Path) -> None:
    """Validate a disposable claim in memory without reserving R7."""

    producer = FuturesOrderPreviewProducer(
        rest_client=None,
        store=FuturesOrderPreviewArtifactStore(path),
        predecessor_binding=dict(FUTURES_PREVIEW_R6_TERMINAL_BINDING),
        predecessor_validator=validate_production_predecessor,
        artifact_type=FUTURES_PREVIEW_R7_ARTIFACT_TYPE,
    )
    _validate_r7_claim_record(producer.build_claim())


def main(argv: Sequence[str] | None = None) -> int:
    """Fail closed because the exact one-use R7 authority is consumed."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if not R7_PREVIEW_CALL_AUTHORITY_ACTIVE:
        print(
            json.dumps(
                _summary_before_attempt(
                    status="blocked",
                    blocker="futures_preview_r7_call_authority_consumed",
                    path=production_artifact_path(),
                    artifact_created=False,
                ),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    if args.preflight:
        try:
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
                    )
                )
                return 2
            predecessor_binding = validate_production_predecessor()
            _validate_fresh_claim_contract(path)
        except Exception:
            print(
                json.dumps(
                    _summary_before_attempt(
                        status="blocked",
                        blocker=(
                            "futures_preview_r7_preflight_validation_blocked"
                        ),
                        path=FUTURES_PREVIEW_R7_ARTIFACT_PATH,
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
        summary.update(
            {
                "predecessor_binding": predecessor_binding,
                "preview_response_schema_binding": (
                    FUTURES_PREVIEW_R7_RESPONSE_SCHEMA_BINDING
                ),
                "claim_contract_ready": True,
            }
        )
        print(json.dumps(summary, sort_keys=True))
        return 0

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
            file=sys.stderr,
        )
        return 2

    store = FuturesOrderPreviewArtifactStore(path)
    producer = FuturesOrderPreviewProducer(
        rest_client=DeferredR7PreviewRestClient(),
        store=store,
        predecessor_binding=dict(FUTURES_PREVIEW_R6_TERMINAL_BINDING),
        predecessor_validator=validate_production_predecessor,
        artifact_type=FUTURES_PREVIEW_R7_ARTIFACT_TYPE,
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
                "submitted_notional_usdc": terminal["submitted_notional_usdc"],
                "executed_notional_usdc": terminal["executed_notional_usdc"],
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
                "seal_ready_plan_sha256": evidence["seal_ready_plan_sha256"],
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
