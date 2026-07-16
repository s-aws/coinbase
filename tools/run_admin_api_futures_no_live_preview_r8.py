"""Fixed one-use Slice 2R8 Preview producer, dormant until workflow sealing.

The operator has authorized one R8 Preview attempt, but the confirmation path
remains independently gated until the conditional Slice 3 workflow and audits
are complete. Preflight never hydrates credentials or constructs a REST client.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
import stat
import sys
from typing import Any, Sequence
from uuid import UUID, uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application.admin_api.futures_order_preview import (  # noqa: E402
    FUTURES_PREVIEW_R7_RESPONSE_SCHEMA_BINDING,
    FUTURES_PREVIEW_R7_TERMINAL_BINDING,
    FUTURES_PREVIEW_R8_ARTIFACT_PATH,
    FUTURES_PREVIEW_R8_ARTIFACT_TYPE,
    FUTURES_PREVIEW_R8_POST_PREVIEW_DIAGNOSTIC_BINDING,
    FuturesOrderPreviewArtifactError,
    FuturesOrderPreviewArtifactStore,
    FuturesOrderPreviewProducer,
    _withhold_r8_private_accepted_evidence,
    _validate_r8_ephemeral_claim_record,
    _validate_r8_claim_record,
    canonical_sha256,
    validate_production_futures_order_preview_r7_opaque_chain,
)
from application.admin_api.futures_portfolio_binding import (  # noqa: E402
    evaluate_futures_default_portfolio_binding,
)
from application.admin_api.futures_terminal_roundtrip_coinbase import (  # noqa: E402
    Slice3CoinbaseAccountBinding,
)
from tools import run_admin_api_futures_no_live_preview_r7 as r7_tool  # noqa: E402
from tools import run_admin_api_futures_no_live_preview as base_tool  # noqa: E402


FuturesPreviewOnlyRestClient = r7_tool.FuturesPreviewOnlyRestClient
_suppress_coinbase_sdk_logging = r7_tool._suppress_coinbase_sdk_logging
R8_PREVIEW_CALL_AUTHORITY_ACTIVE = False
R8_END_TO_END_WORKFLOW_READY = False

_R8_EXACT_READ_COUNTERS = {
    "api_key_permissions": 1,
    "portfolio_catalog": 1,
    "product": 1,
    "best_bid_ask": 1,
    "futures_positions": 1,
    "futures_margin_collateral": 1,
}
_R8_EXACT_ATTEMPT_COUNTERS = {
    "preview_order": 1,
    "retry": 0,
    "fallback": 0,
    "create_order": 0,
    "cancel_order": 0,
    "close_position": 0,
    "reduce_position": 0,
}
_R8_DEFERRED_CALLS = (
    "api_key_permissions",
    "portfolio_catalog",
    "product",
    "best_bid_ask",
    "futures_positions",
    "futures_margin_collateral",
    "preview_order",
)


@dataclass(frozen=True, slots=True, repr=False)
class _R8CanonicalPreviewSession:
    """Private pair of one canonical delegate and its Preview-only facade."""

    delegate: object = field(repr=False)
    preview_client: FuturesPreviewOnlyRestClient = field(init=False, repr=False)
    session_binding_token: str = field(init=False, repr=False)
    _delegate_identity: int = field(init=False, repr=False)
    _preview_client_identity: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.delegate is None:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R8 canonical session is invalid"
            )
        preview_client = FuturesPreviewOnlyRestClient(self.delegate)
        object.__setattr__(self, "preview_client", preview_client)
        object.__setattr__(self, "session_binding_token", str(uuid4()))
        object.__setattr__(self, "_delegate_identity", id(self.delegate))
        object.__setattr__(
            self,
            "_preview_client_identity",
            id(preview_client),
        )
        self.validate()

    def __repr__(self) -> str:
        return "<_R8CanonicalPreviewSession private>"

    def validate(self) -> None:
        try:
            parsed = UUID(self.session_binding_token)
        except (AttributeError, TypeError, ValueError):
            parsed = None
        if (
            parsed is None
            or parsed.version != 4
            or str(parsed) != self.session_binding_token
            or id(self.delegate) != self._delegate_identity
            or id(self.preview_client) != self._preview_client_identity
            or not self.preview_client._uses_exact_delegate(self.delegate)
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R8 canonical session is invalid"
            )


@dataclass(frozen=True, slots=True)
class R8AcceptedSessionHandoff:
    """One-use in-memory release of the exact R8 Coinbase session."""

    delegate: object = field(repr=False)
    account_binding: Slice3CoinbaseAccountBinding = field(repr=False)

    def __repr__(self) -> str:
        return "<R8AcceptedSessionHandoff validated same-session binding>"


def _build_r8_canonical_preview_session(
    *,
    run_secret_lookup: Callable[[str, str | None], str] | None = None,
) -> _R8CanonicalPreviewSession:
    """Build exactly one canonical Default client and its R8-only facade."""

    kwargs = (
        {}
        if run_secret_lookup is None
        else {"run_secret_lookup": run_secret_lookup}
    )
    return _R8CanonicalPreviewSession(
        base_tool._build_canonical_default_rest_client(**kwargs)
    )


class DeferredR8PreviewRestClient:
    """Hold one fixed session and release it only after exact acceptance.

    The sealed production composition root injects a locally constructed
    session before reserving R8 so credential or SDK-construction failures do
    not consume the one-use claim. The factory path remains for synthetic and
    dormant compatibility checks and cannot hydrate before a claim exists.
    """

    __slots__ = (
        "__accepted_session_consumed",
        "__call_attempts",
        "__claim_asserted",
        "__hydration_attempted",
        "__permission_response",
        "__portfolio_response",
        "__session",
        "__session_factory",
        "__store",
    )

    def __init__(
        self,
        *,
        store: FuturesOrderPreviewArtifactStore,
        session_factory: Callable[[], _R8CanonicalPreviewSession] | None = None,
        prepared_session: _R8CanonicalPreviewSession | None = None,
    ) -> None:
        if not isinstance(store, FuturesOrderPreviewArtifactStore):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R8 artifact store is invalid"
            )
        if prepared_session is not None and session_factory is not None:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R8 canonical session source is invalid"
            )
        if prepared_session is not None:
            if type(prepared_session) is not _R8CanonicalPreviewSession:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R8 canonical session source is invalid"
                )
            prepared_session.validate()
            factory: Callable[[], _R8CanonicalPreviewSession] | None = None
        else:
            factory = session_factory or _build_r8_canonical_preview_session
        if factory is not None and not callable(factory):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R8 canonical session factory is invalid"
            )
        self.__store = store
        self.__session_factory = factory
        self.__session = prepared_session
        self.__hydration_attempted = prepared_session is not None
        self.__claim_asserted = False
        self.__accepted_session_consumed = False
        self.__call_attempts = {name: 0 for name in _R8_DEFERRED_CALLS}
        self.__permission_response: object | None = None
        self.__portfolio_response: object | None = None

    def _get(self) -> FuturesPreviewOnlyRestClient:
        if not self.__claim_asserted:
            self._assert_r8_claimed()
            self.__claim_asserted = True
        if self.__session is None:
            if self.__hydration_attempted:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R8 canonical session is unavailable"
                )
            self.__hydration_attempted = True
            factory = self.__session_factory
            if factory is None:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R8 canonical session is unavailable"
                )
            with _suppress_coinbase_sdk_logging():
                session = factory()
            if not isinstance(session, _R8CanonicalPreviewSession):
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R8 canonical session is invalid"
                )
            session.validate()
            self.__session = session
        self.__session.validate()
        return self.__session.preview_client

    def _assert_r8_claimed(self) -> None:
        try:
            rows = self.__store._read_rows()  # noqa: SLF001
            artifact_stat = self.__store.path.lstat()
            claim = rows[0].get("record") if len(rows) == 1 else None
            if (
                len(rows) != 1
                or rows[0].get("record_type") != "claim"
                or not isinstance(claim, Mapping)
                or stat.S_IMODE(artifact_stat.st_mode) != 0o600
                or artifact_stat.st_nlink != 1
            ):
                raise ValueError("claim_not_exclusive")
            _validate_r8_claim_record(claim)
        except Exception:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R8 claim is unavailable"
            ) from None

    def _consume_call(self, name: str) -> None:
        if name not in self.__call_attempts or self.__call_attempts[name] != 0:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R8 call was already attempted"
            )
        self.__call_attempts[name] = 1

    def get_api_key_permissions(self):
        self._consume_call("api_key_permissions")
        result = self._get().get_api_key_permissions()
        self.__permission_response = deepcopy(result)
        return result

    def list_portfolios(self):
        self._consume_call("portfolio_catalog")
        result = self._get().list_portfolios()
        self.__portfolio_response = deepcopy(result)
        return result

    def get_product_dict(self, product_id: str):
        self._consume_call("product")
        return self._get().get_product_dict(product_id)

    def get_best_bid_ask(self, *, product_ids: list[str]):
        self._consume_call("best_bid_ask")
        return self._get().get_best_bid_ask(product_ids=product_ids)

    def get_futures_positions(self):
        self._consume_call("futures_positions")
        return self._get().get_futures_positions()

    def get_futures_margin_collateral_snapshot(self):
        self._consume_call("futures_margin_collateral")
        return self._get().get_futures_margin_collateral_snapshot()

    def preview_order(self, **kwargs):
        self._consume_call("preview_order")
        return self._get().preview_order(**kwargs)

    def take_accepted_session(
        self,
        ephemeral_evidence: Mapping[str, Any],
        persisted_terminal: Mapping[str, Any],
    ) -> R8AcceptedSessionHandoff:
        """Release the already-used delegate exactly once after exact acceptance."""

        if self.__accepted_session_consumed:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R8 accepted session was already released"
            )
        self.__accepted_session_consumed = True
        session = self.__session
        if session is None:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R8 accepted session is unavailable"
            )
        try:
            session.validate()
            ephemeral = _require_mapping(ephemeral_evidence)
            persisted = _require_mapping(persisted_terminal)
            _validate_exact_accepted_pair(
                ephemeral=ephemeral,
                persisted=persisted,
                stored_terminal=self.__store.read_completed(),
                permissions=self.__permission_response,
                portfolios=self.__portfolio_response,
                call_attempts=self.__call_attempts,
            )
            account_binding = Slice3CoinbaseAccountBinding.build(
                portfolio_id=str(ephemeral["portfolio_id"]),
                session_binding_token=session.session_binding_token,
                permission_evidence_sha256=str(ephemeral["permission_evidence_sha256"]),
                portfolio_catalog_sha256=str(ephemeral["portfolio_catalog_sha256"]),
            )
            account_binding.validate()
        except FuturesOrderPreviewArtifactError:
            raise
        except Exception:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R8 accepted session binding is invalid"
            ) from None
        return R8AcceptedSessionHandoff(
            delegate=session.delegate,
            account_binding=account_binding,
        )


def _require_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 accepted session binding is invalid"
        )
    return dict(value)


def _validate_self_hash(evidence: Mapping[str, Any]) -> None:
    if evidence.get("evidence_sha256") != canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 accepted session binding is invalid"
        )


def _validate_exact_accepted_pair(
    *,
    ephemeral: Mapping[str, Any],
    persisted: Mapping[str, Any],
    stored_terminal: Mapping[str, Any],
    permissions: object,
    portfolios: object,
    call_attempts: Mapping[str, int],
) -> None:
    """Prove the accepted pair and same read-session portfolio evidence."""

    _validate_self_hash(ephemeral)
    _validate_self_hash(persisted)
    if (
        ephemeral.get("artifact_type") != FUTURES_PREVIEW_R8_ARTIFACT_TYPE
        or ephemeral.get("status") != "accepted"
        or ephemeral.get("outcome") != "accepted"
        or persisted.get("artifact_type") != FUTURES_PREVIEW_R8_ARTIFACT_TYPE
        or persisted.get("status") != "accepted"
        or persisted.get("outcome") != "accepted"
        or dict(stored_terminal) != dict(persisted)
        or ephemeral.get("read_counters") != _R8_EXACT_READ_COUNTERS
        or ephemeral.get("attempt_counters") != _R8_EXACT_ATTEMPT_COUNTERS
        or persisted.get("read_counters") != _R8_EXACT_READ_COUNTERS
        or persisted.get("attempt_counters") != _R8_EXACT_ATTEMPT_COUNTERS
        or dict(call_attempts) != {name: 1 for name in _R8_DEFERRED_CALLS}
        or ephemeral.get("exchange_submission_attempt_count") != 0
        or ephemeral.get("submitted_notional_usdc") != "0"
        or ephemeral.get("executed_notional_usdc") != "0"
        or ephemeral.get("live_execution") != "not_run"
        or ephemeral.get("live_coinbase_execution") != "not_run"
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 accepted session binding is invalid"
        )
    try:
        expected_persisted = _withhold_r8_private_accepted_evidence(ephemeral)
    except Exception:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 accepted session binding is invalid"
        ) from None
    if expected_persisted != dict(persisted):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 accepted session binding is invalid"
        )

    portfolio_id = ephemeral.get("portfolio_id")
    portfolio_binding = _require_mapping(ephemeral.get("portfolio_binding"))
    if (
        not isinstance(portfolio_id, str)
        or not portfolio_id
        or portfolio_id == "withheld"
        or permissions is None
        or portfolios is None
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 accepted session binding is invalid"
        )
    evaluated = evaluate_futures_default_portfolio_binding(
        permissions=permissions,
        portfolios=portfolios,
        observed_at=str(portfolio_binding.get("observed_at") or ""),
        permissions_read=True,
        portfolio_catalog_read=True,
    ).to_dict()
    permission_evidence = {
        "portfolio_id": portfolio_id,
        "portfolio_type": "DEFAULT",
        "can_view": True,
        "can_trade": True,
        "selection_authority": "cdp_api_key_permissioned_portfolio",
        "sanitized": True,
        "raw_response_included": False,
    }
    portfolio_evidence = {
        "selected_portfolio_id": portfolio_id,
        "selected_portfolio_label": "Default",
        "selected_portfolio_type": "DEFAULT",
        "exact_match_count": 1,
        "sanitized": True,
        "raw_response_included": False,
    }
    if (
        evaluated != portfolio_binding
        or ephemeral.get("permission_evidence") != permission_evidence
        or ephemeral.get("permission_evidence_sha256")
        != canonical_sha256(permission_evidence)
        or ephemeral.get("portfolio_catalog_evidence") != portfolio_evidence
        or ephemeral.get("portfolio_catalog_sha256")
        != canonical_sha256(portfolio_evidence)
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 accepted session binding is invalid"
        )


def production_artifact_path() -> Path:
    """Return the fixed R8 path; configuration cannot redirect it."""

    return FUTURES_PREVIEW_R8_ARTIFACT_PATH


def validate_production_predecessor() -> dict[str, object]:
    """Opaque-hash-bind consumed R7 and every immutable predecessor."""

    return validate_production_futures_order_preview_r7_opaque_chain()


def build_parser() -> argparse.ArgumentParser:
    """Build the deliberately option-minimal R8 producer CLI."""

    parser = argparse.ArgumentParser(
        description=(
            "Fixed Default-profile AVAX Futures R8 Preview-only producer. "
            "No retry, redirect, Create, Cancel, Close, or Reduce exists."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preflight",
        action="store_true",
        help="Validate the fixed claim without credentials or Coinbase access.",
    )
    mode.add_argument(
        "--confirm-one-r8-preview",
        action="store_true",
        help="Consume the one-use R8 Preview authority after workflow sealing.",
    )
    return parser


def build_rest_client() -> FuturesPreviewOnlyRestClient:
    """Retain the public mutation-incapable Preview-only builder."""

    return r7_tool.build_rest_client()


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
    """Validate a disposable R8 claim in memory without reserving it."""

    producer = FuturesOrderPreviewProducer(
        rest_client=None,
        store=FuturesOrderPreviewArtifactStore(path),
        predecessor_binding=dict(FUTURES_PREVIEW_R7_TERMINAL_BINDING),
        predecessor_validator=validate_production_predecessor,
        artifact_type=FUTURES_PREVIEW_R8_ARTIFACT_TYPE,
    )
    _validate_r8_ephemeral_claim_record(producer.build_claim())


def _fixed_blocked_summary(blocker: str) -> dict[str, object]:
    return _summary_before_attempt(
        status="blocked",
        blocker=blocker,
        path=FUTURES_PREVIEW_R8_ARTIFACT_PATH,
        artifact_created=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Preflight safely or consume the exact one-use R8 Preview claim."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if not R8_PREVIEW_CALL_AUTHORITY_ACTIVE:
        print(
            json.dumps(
                _fixed_blocked_summary("futures_preview_r8_call_authority_consumed"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    if args.confirm_one_r8_preview and not R8_END_TO_END_WORKFLOW_READY:
        print(
            json.dumps(
                _fixed_blocked_summary("futures_preview_r8_workflow_not_ready"),
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
            if predecessor_binding != FUTURES_PREVIEW_R7_TERMINAL_BINDING:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R7 terminal binding changed"
                )
            _validate_fresh_claim_contract(path)
        except Exception:
            print(
                json.dumps(
                    _fixed_blocked_summary(
                        "futures_preview_r8_preflight_validation_blocked"
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
                "post_preview_diagnostic_binding": (
                    FUTURES_PREVIEW_R8_POST_PREVIEW_DIAGNOSTIC_BINDING
                ),
                "claim_contract_ready": True,
                "end_to_end_workflow_ready": R8_END_TO_END_WORKFLOW_READY,
            }
        )
        print(json.dumps(summary, sort_keys=True))
        return 0

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
                ),
                file=sys.stderr,
            )
            return 2
        predecessor_binding = validate_production_predecessor()
        if predecessor_binding != FUTURES_PREVIEW_R7_TERMINAL_BINDING:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R7 terminal binding changed"
            )
    except Exception:
        print(
            json.dumps(
                _fixed_blocked_summary(
                    "futures_preview_r8_preflight_validation_blocked"
                ),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    store = FuturesOrderPreviewArtifactStore(path)
    producer = FuturesOrderPreviewProducer(
        rest_client=DeferredR8PreviewRestClient(store=store),
        store=store,
        predecessor_binding=dict(FUTURES_PREVIEW_R7_TERMINAL_BINDING),
        predecessor_validator=validate_production_predecessor,
        artifact_type=FUTURES_PREVIEW_R8_ARTIFACT_TYPE,
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
