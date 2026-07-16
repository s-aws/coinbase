"""One-shot, no-live Futures order Preview evidence.

The producer is a backend-only boundary.  It reserves one append-only JSONL
artifact before any Coinbase SDK read, performs fixed Default-profile AVAX CFM
preflight reads, and may make at most one ``Preview Order`` call.  The repeated
Admin API GET reads only the completed artifact and never receives a REST
client.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import fcntl
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4

from application.admin_api.futures_portfolio_binding import (
    evaluate_futures_default_portfolio_binding,
)


FUTURES_PREVIEW_PRODUCT_ID = "AVP-20DEC30-CDE"
FUTURES_PREVIEW_ACTOR_ID = "operator-controlled-futures-proof"
FUTURES_PREVIEW_ROLE = "trader"
FUTURES_PREVIEW_CONTRACT_COUNT = Decimal("1")
FUTURES_PREVIEW_OPENING_CAP_USDC = Decimal("100")
FUTURES_PREVIEW_EXPOSURE_CAP_USDC = Decimal("150")
FUTURES_PREVIEW_TURNOVER_CAP_USDC = Decimal("300")
FUTURES_PREVIEW_CLOSE_BUFFER = Decimal("1.20")
FUTURES_PREVIEW_ARTIFACT_ENV = (
    "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_PATH"
)
FUTURES_PREVIEW_ARTIFACT_ROOT_ENV = (
    "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_ROOT"
)


def _resolve_futures_preview_artifact_root(
    env: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the persistent immutable-artifact root for source or deployment."""

    values = os.environ if env is None else env
    configured = values.get(FUTURES_PREVIEW_ARTIFACT_ROOT_ENV, "").strip()
    if not configured:
        return Path(__file__).resolve().parents[2] / "artifacts"
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        raise ValueError(
            f"{FUTURES_PREVIEW_ARTIFACT_ROOT_ENV} must be an absolute path"
        )
    return candidate


FUTURES_PREVIEW_ARTIFACT_ROOT = _resolve_futures_preview_artifact_root()
FUTURES_PREVIEW_ORIGINAL_ARTIFACT_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2.jsonl"
)
FUTURES_PREVIEW_R1_ARTIFACT_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2r1.jsonl"
)
FUTURES_PREVIEW_PREDECESSOR_ARTIFACT_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2r2.jsonl"
)
FUTURES_PREVIEW_R3_ARTIFACT_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2r3.jsonl"
)
FUTURES_PREVIEW_R4_ARTIFACT_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2r4.jsonl"
)
FUTURES_PREVIEW_R5_ARTIFACT_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2r5.jsonl"
)
FUTURES_PREVIEW_R6_ARTIFACT_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2r6.jsonl"
)
FUTURES_PREVIEW_R7_ARTIFACT_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2r7.jsonl"
)
_PRODUCTION_FUTURES_PREVIEW_R8_ARTIFACT_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2r8.jsonl"
)
FUTURES_PREVIEW_R8_ARTIFACT_PATH = (
    _PRODUCTION_FUTURES_PREVIEW_R8_ARTIFACT_PATH
)
_PRODUCTION_FUTURES_PREVIEW_R9_ARTIFACT_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2r9.jsonl"
)
FUTURES_PREVIEW_R9_ARTIFACT_PATH = (
    _PRODUCTION_FUTURES_PREVIEW_R9_ARTIFACT_PATH
)
_PRODUCTION_FUTURES_PREVIEW_R10_ARTIFACT_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2r10.jsonl"
)
FUTURES_PREVIEW_R10_ARTIFACT_PATH = (
    _PRODUCTION_FUTURES_PREVIEW_R10_ARTIFACT_PATH
)
_PRODUCTION_FUTURES_PREVIEW_R11_ARTIFACT_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2r11.jsonl"
)
FUTURES_PREVIEW_R11_ARTIFACT_PATH = (
    _PRODUCTION_FUTURES_PREVIEW_R11_ARTIFACT_PATH
)
_PRODUCTION_FUTURES_PREVIEW_R8_LOCK_PATH = (
    Path(__file__).resolve().parents[2]
    / "runtime_state"
    / "futures_preview_r8_selector.lock"
)
DEFAULT_FUTURES_PREVIEW_ARTIFACT_PATH = FUTURES_PREVIEW_R4_ARTIFACT_PATH
FUTURES_PREVIEW_R1_FILE_SHA256 = (
    "55c09c6d4819f2d03dd679ae4c952e203cf540d1a141e13035459821f1b680d7"
)
FUTURES_PREVIEW_R1_EVIDENCE_SHA256 = (
    "a1b7820aa217b7119a6353a8f4fbffa5227ebfe5e4c8d8a1cde5449d370fc6f0"
)
FUTURES_PREVIEW_R1_DEVICE = 2096
FUTURES_PREVIEW_R1_INODE = 400173
FUTURES_PREVIEW_R1_SIZE = 4197
FUTURES_PREVIEW_R1_MODE = 0o400
FUTURES_PREVIEW_R1_MTIME_NS = 1783980960753782357
FUTURES_PREVIEW_PREDECESSOR_FILE_SHA256 = (
    "1831b2feaac69b9d3d64377123833831c1b1c1f26c1c0445ed17f334746b4053"
)
FUTURES_PREVIEW_PREDECESSOR_EVIDENCE_SHA256 = (
    "afebf81c4d95c0abd7635fd700f6618e92191423173df3e2db0f875102b6f1c9"
)
FUTURES_PREVIEW_PREDECESSOR_DEVICE = 2096
FUTURES_PREVIEW_PREDECESSOR_INODE = 400174
FUTURES_PREVIEW_PREDECESSOR_SIZE = 6002
FUTURES_PREVIEW_PREDECESSOR_MODE = 0o400
FUTURES_PREVIEW_PREDECESSOR_MTIME_NS = 1783991637010957407
FUTURES_PREVIEW_R3_FILE_SHA256 = (
    "7ccd5411878842f883b78a99a4103b9b7b1f9aa000ebdde29cdecf2ac894b61c"
)
FUTURES_PREVIEW_R3_EVIDENCE_SHA256 = (
    "e79beb3d9f1324cf8f90ba78cd45869fec5b7963afe3745bd6e26617313718e8"
)
FUTURES_PREVIEW_R3_DEVICE = 2096
FUTURES_PREVIEW_R3_INODE = 400175
FUTURES_PREVIEW_R3_SIZE = 7616
FUTURES_PREVIEW_R3_MODE = 0o400
FUTURES_PREVIEW_R3_MTIME_NS = 1784054457360155278
FUTURES_PREVIEW_R4_FILE_SHA256 = (
    "90691e5b24c17fca5f3d1a67f942ea0b4b067e262435bcdf37e516f79ebb66cf"
)
FUTURES_PREVIEW_R4_EVIDENCE_SHA256 = (
    "0edeffdb0702ba119a7d9c3e32874b75e295ee596538432df5f7be0a67a4af3e"
)
FUTURES_PREVIEW_R4_DEVICE = 2096
FUTURES_PREVIEW_R4_INODE = 400176
FUTURES_PREVIEW_R4_SIZE = 9508
FUTURES_PREVIEW_R4_MODE = 0o400
FUTURES_PREVIEW_R4_MTIME_NS = 1784087822854381595
FUTURES_PREVIEW_R5_FILE_SHA256 = (
    "4988e23886d218d25be518203676bec4f27a2199a0ed2e7f36d0d7e1d8e6bbf7"
)
FUTURES_PREVIEW_R5_EVIDENCE_SHA256 = (
    "194cdd842944f8a453408051c04ff8e117b6b2b3ab6dcd7b1e78f44f4a5a467f"
)
FUTURES_PREVIEW_R5_DEVICE = 2096
FUTURES_PREVIEW_R5_INODE = 400177
FUTURES_PREVIEW_R5_SIZE = 11647
FUTURES_PREVIEW_R5_MODE = 0o400
FUTURES_PREVIEW_R5_MTIME_NS = 1784111957686383208
FUTURES_PREVIEW_R6_FILE_SHA256 = (
    "df5959e95ed4a6027e6c0a6980045fc685e7dd201158b39ff5fcc9577bf73904"
)
FUTURES_PREVIEW_R6_EVIDENCE_SHA256 = (
    "bf26fa6b0f67499dea02f337517c1ebd42ae9a20c88fbb5cfbe45e3f30f9e4f9"
)
FUTURES_PREVIEW_R6_DEVICE = 2096
FUTURES_PREVIEW_R6_INODE = 400333
FUTURES_PREVIEW_R6_SIZE = 18567
FUTURES_PREVIEW_R6_MODE = 0o400
FUTURES_PREVIEW_R6_MTIME_NS = 1784122432722849234
FUTURES_PREVIEW_R7_FILE_SHA256 = (
    "8e7bdf1a1efa67df9b1081cc8270dc9607e0b8c7285053d06985dcab195115e4"
)
FUTURES_PREVIEW_R7_EVIDENCE_SHA256 = (
    "65791ec5aae8bd9db7c623042e3238f80a54067209aeeb1916801ca1d02369c3"
)
FUTURES_PREVIEW_R7_DEVICE = 2096
FUTURES_PREVIEW_R7_INODE = 400397
FUTURES_PREVIEW_R7_SIZE = 20548
FUTURES_PREVIEW_R7_MODE = 0o400
FUTURES_PREVIEW_R7_MTIME_NS = 1784133682760886913
FUTURES_PREVIEW_R8_FILE_SHA256 = (
    "b32aba4868f08ee7a44f19ceacbcf42cb7e4d70da1552f2d8b333ef59ddc8696"
)
FUTURES_PREVIEW_R8_DEVICE = 2096
FUTURES_PREVIEW_R8_INODE = 400341
FUTURES_PREVIEW_R8_SIZE = 14921
FUTURES_PREVIEW_R8_MODE = 0o400
FUTURES_PREVIEW_R8_MTIME_NS = 1784160315297279427
FUTURES_PREVIEW_R9_FILE_SHA256 = (
    "5c7dd3f27605b623edc910a87dcc4b6c9ea6621aa9ee63dbfcc4b2994990dacf"
)
FUTURES_PREVIEW_R9_EVIDENCE_SHA256 = (
    "2fd73aa0059da49dfe6c836f6dea29b12158fb3dfbe8abdd6d8f4f0f7d702464"
)
FUTURES_PREVIEW_R9_DEVICE = 2096
FUTURES_PREVIEW_R9_INODE = 401766
FUTURES_PREVIEW_R9_SIZE = 24406
FUTURES_PREVIEW_R9_MODE = 0o400
FUTURES_PREVIEW_R9_MTIME_NS = 1784173141720439487
FUTURES_PREVIEW_R9_NLINK = 1
FUTURES_PREVIEW_R10_FILE_SHA256 = (
    "5dd010a706c61e78454caeec478e05cafb1a50761e9e5a9a3d485051c4efee64"
)
FUTURES_PREVIEW_R10_EVIDENCE_SHA256 = (
    "5121e980ec9da81f44d9a3b14b9bbcaa7bdaf41c99189cd9234cedc08d652005"
)
FUTURES_PREVIEW_R10_DEVICE = 2096
FUTURES_PREVIEW_R10_INODE = 221388
FUTURES_PREVIEW_R10_SIZE = 26144
FUTURES_PREVIEW_R10_MODE = 0o400
FUTURES_PREVIEW_R10_MTIME_NS = 1784179469052389092
FUTURES_PREVIEW_R10_NLINK = 1
FUTURES_PREVIEW_ORIGINAL_FILE_SHA256 = (
    "9b15da86c172eca46d4b3dc0fc2b81e9b325df9a1e2f75fef79362f538e2d5ff"
)
FUTURES_PREVIEW_ORIGINAL_EVIDENCE_SHA256 = (
    "3b09cb9dfe02991dc886a1c6f041330d417ff11a0f1d45e3734bdc59bfb219b8"
)
FUTURES_PREVIEW_ORIGINAL_DEVICE = 2096
FUTURES_PREVIEW_ORIGINAL_INODE = 400172
FUTURES_PREVIEW_ORIGINAL_SIZE = 3043
FUTURES_PREVIEW_ORIGINAL_MODE = 0o400
FUTURES_PREVIEW_ORIGINAL_MTIME_NS = 1783968539951853688
_FUTURES_PREVIEW_EC2_IDENTITIES = {
    "original": (66305, 42312964),
    "r1": (66305, 42312970),
    "r2": (66305, 42312480),
    "r3": (66305, 42312497),
    "r4": (66305, 42321812),
    "r5": (66305, 41943457),
}
_SCHEMA_VERSION = "1"
_ARTIFACT_TYPE = "futures_exact_no_live_preview_slice_2r3"
FUTURES_PREVIEW_R4_ARTIFACT_TYPE = (
    "futures_exact_no_live_preview_slice_2r4"
)
_R4_ARTIFACT_TYPE = FUTURES_PREVIEW_R4_ARTIFACT_TYPE
FUTURES_PREVIEW_R5_ARTIFACT_TYPE = (
    "futures_exact_no_live_preview_slice_2r5"
)
_R5_ARTIFACT_TYPE = FUTURES_PREVIEW_R5_ARTIFACT_TYPE
FUTURES_PREVIEW_R6_ARTIFACT_TYPE = (
    "futures_exact_no_live_preview_slice_2r6"
)
_R6_ARTIFACT_TYPE = FUTURES_PREVIEW_R6_ARTIFACT_TYPE
FUTURES_PREVIEW_R7_ARTIFACT_TYPE = (
    "futures_exact_no_live_preview_slice_2r7"
)
_R7_ARTIFACT_TYPE = FUTURES_PREVIEW_R7_ARTIFACT_TYPE
FUTURES_PREVIEW_R8_ARTIFACT_TYPE = (
    "futures_exact_no_live_preview_slice_2r8"
)
_R8_ARTIFACT_TYPE = FUTURES_PREVIEW_R8_ARTIFACT_TYPE
FUTURES_PREVIEW_R9_ARTIFACT_TYPE = (
    "futures_exact_no_live_preview_slice_2r9"
)
_R9_ARTIFACT_TYPE = FUTURES_PREVIEW_R9_ARTIFACT_TYPE
FUTURES_PREVIEW_R10_ARTIFACT_TYPE = (
    "futures_exact_no_live_preview_slice_2r10"
)
_R10_ARTIFACT_TYPE = FUTURES_PREVIEW_R10_ARTIFACT_TYPE
FUTURES_PREVIEW_R11_ARTIFACT_TYPE = (
    "futures_exact_no_live_preview_slice_2r11"
)
_R11_ARTIFACT_TYPE = FUTURES_PREVIEW_R11_ARTIFACT_TYPE
_SANITIZED_PREVIEW_ARTIFACT_TYPES = frozenset(
    {
        _R5_ARTIFACT_TYPE,
        _R6_ARTIFACT_TYPE,
        _R7_ARTIFACT_TYPE,
        _R8_ARTIFACT_TYPE,
        _R9_ARTIFACT_TYPE,
        _R10_ARTIFACT_TYPE,
        _R11_ARTIFACT_TYPE,
    }
)
_V3_MARGIN_WINDOW_ARTIFACT_TYPES = frozenset(
    {
        _R6_ARTIFACT_TYPE,
        _R7_ARTIFACT_TYPE,
        _R8_ARTIFACT_TYPE,
        _R9_ARTIFACT_TYPE,
        _R10_ARTIFACT_TYPE,
        _R11_ARTIFACT_TYPE,
    }
)
_CORRECTED_RESPONSE_SCHEMA_ARTIFACT_TYPES = frozenset(
    {
        _R7_ARTIFACT_TYPE,
        _R8_ARTIFACT_TYPE,
        _R9_ARTIFACT_TYPE,
        _R10_ARTIFACT_TYPE,
        _R11_ARTIFACT_TYPE,
    }
)
_POST_PREVIEW_DIAGNOSTIC_ARTIFACT_TYPES = frozenset(
    {
        _R8_ARTIFACT_TYPE,
        _R9_ARTIFACT_TYPE,
        _R10_ARTIFACT_TYPE,
        _R11_ARTIFACT_TYPE,
    }
)
_ACCEPTED_HANDOFF_ARTIFACT_TYPES = frozenset(
    {_R8_ARTIFACT_TYPE, _R9_ARTIFACT_TYPE, _R10_ARTIFACT_TYPE}
)
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
FUTURES_PREVIEW_DOCUMENTED_MARGIN_SETTINGS = frozenset(
    {
        "INTRADAY_MARGIN_SETTING_UNSPECIFIED",
        "INTRADAY_MARGIN_SETTING_STANDARD",
        "INTRADAY_MARGIN_SETTING_INTRADAY",
    }
)
FUTURES_PREVIEW_OPERATIONAL_MARGIN_SETTINGS = frozenset(
    {
        "INTRADAY_MARGIN_SETTING_STANDARD",
        "INTRADAY_MARGIN_SETTING_INTRADAY",
    }
)
FUTURES_PREVIEW_OPERATIONAL_FCM_MARGIN_WINDOW_TYPES = frozenset(
    {
        "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT",
        "FCM_MARGIN_WINDOW_TYPE_WEEKEND",
        "FCM_MARGIN_WINDOW_TYPE_INTRADAY",
        "FCM_MARGIN_WINDOW_TYPE_TRANSITION",
    }
)
FUTURES_PREVIEW_OPERATIONAL_CURRENT_MARGIN_WINDOW_TYPES = frozenset(
    {"MARGIN_WINDOW_TYPE_INTRADAY"}
)
FUTURES_PREVIEW_DOCUMENTED_CURRENT_MARGIN_WINDOW_TYPES = frozenset(
    {
        "MARGIN_WINDOW_TYPE_UNSPECIFIED",
        "MARGIN_WINDOW_TYPE_OVERNIGHT",
        "MARGIN_WINDOW_TYPE_WEEKEND",
        "MARGIN_WINDOW_TYPE_INTRADAY",
        "MARGIN_WINDOW_TYPE_TRANSITION",
    }
)
_FUTURES_PREVIEW_SLICE2_OPERATOR_ACCEPTED_MARGIN_WINDOW_TYPES = frozenset(
    {
        "MARGIN_WINDOW_TYPE_OVERNIGHT",
        "MARGIN_WINDOW_TYPE_WEEKEND",
        "MARGIN_WINDOW_TYPE_INTRADAY",
        "MARGIN_WINDOW_TYPE_TRANSITION",
    }
)
FUTURES_PREVIEW_SLICE2_OPERATOR_MARGIN_WINDOW_POLICY = MappingProxyType(
    {
        "MARGIN_PROFILE_TYPE_RETAIL_REGULAR": (
            _FUTURES_PREVIEW_SLICE2_OPERATOR_ACCEPTED_MARGIN_WINDOW_TYPES
        ),
        "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1": (
            _FUTURES_PREVIEW_SLICE2_OPERATOR_ACCEPTED_MARGIN_WINDOW_TYPES
        ),
    }
)
FUTURES_PREVIEW_SLICE2_R6_OPERATOR_MARGIN_WINDOW_POLICY = MappingProxyType(
    {
        "MARGIN_PROFILE_TYPE_RETAIL_REGULAR": frozenset(
            {"MARGIN_WINDOW_TYPE_UNSPECIFIED"}
        ),
        "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1": frozenset(
            {"MARGIN_WINDOW_TYPE_INTRADAY"}
        ),
    }
)
_FUTURES_PREVIEW_SLICE2_MARGIN_PROFILE_POLICY_INDEX = MappingProxyType(
    {
        profile: index
        for index, profile in enumerate(
            FUTURES_PREVIEW_SLICE2_OPERATOR_MARGIN_WINDOW_POLICY
        )
    }
)
FUTURES_PREVIEW_EXPECTED_MARGIN_PROFILES = {
    "MARGIN_PROFILE_TYPE_RETAIL_REGULAR": "retail_regular",
    "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1": (
        "retail_intraday_margin_1"
    ),
}
FUTURES_PREVIEW_EXPECTED_MARGIN_SOURCE_READS = {
    "get_futures_balance_summary": 1,
    "get_intraday_margin_setting": 1,
    "get_current_margin_window": 2,
    "list_futures_sweeps": 1,
}
FUTURES_PREVIEW_ORIGINAL_PREDECESSOR_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2.jsonl",
    "file_sha256": FUTURES_PREVIEW_ORIGINAL_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_ORIGINAL_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_ORIGINAL_DEVICE),
    "inode": str(FUTURES_PREVIEW_ORIGINAL_INODE),
    "size_bytes": 3043,
    "mode": "0400",
    "mtime_ns": "1783968539951853688",
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
}
FUTURES_PREVIEW_R1_PREDECESSOR_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r1.jsonl",
    "file_sha256": FUTURES_PREVIEW_R1_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_R1_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_R1_DEVICE),
    "inode": str(FUTURES_PREVIEW_R1_INODE),
    "size_bytes": FUTURES_PREVIEW_R1_SIZE,
    "mode": f"{FUTURES_PREVIEW_R1_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_R1_MTIME_NS),
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": (
        FUTURES_PREVIEW_ORIGINAL_PREDECESSOR_BINDING
    ),
}
FUTURES_PREVIEW_PREDECESSOR_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r2.jsonl",
    "file_sha256": FUTURES_PREVIEW_PREDECESSOR_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_PREDECESSOR_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_PREDECESSOR_DEVICE),
    "inode": str(FUTURES_PREVIEW_PREDECESSOR_INODE),
    "size_bytes": FUTURES_PREVIEW_PREDECESSOR_SIZE,
    "mode": f"{FUTURES_PREVIEW_PREDECESSOR_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_PREDECESSOR_MTIME_NS),
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": FUTURES_PREVIEW_R1_PREDECESSOR_BINDING,
}
FUTURES_PREVIEW_R3_PREDECESSOR_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r3.jsonl",
    "file_sha256": FUTURES_PREVIEW_R3_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_R3_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_R3_DEVICE),
    "inode": str(FUTURES_PREVIEW_R3_INODE),
    "size_bytes": FUTURES_PREVIEW_R3_SIZE,
    "mode": f"{FUTURES_PREVIEW_R3_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_R3_MTIME_NS),
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": FUTURES_PREVIEW_PREDECESSOR_BINDING,
}
FUTURES_PREVIEW_R4_PREDECESSOR_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r4.jsonl",
    "file_sha256": FUTURES_PREVIEW_R4_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_R4_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_R4_DEVICE),
    "inode": str(FUTURES_PREVIEW_R4_INODE),
    "size_bytes": FUTURES_PREVIEW_R4_SIZE,
    "mode": f"{FUTURES_PREVIEW_R4_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_R4_MTIME_NS),
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": FUTURES_PREVIEW_R3_PREDECESSOR_BINDING,
}
FUTURES_PREVIEW_R5_TERMINAL_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r5.jsonl",
    "file_sha256": FUTURES_PREVIEW_R5_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_R5_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_R5_DEVICE),
    "inode": str(FUTURES_PREVIEW_R5_INODE),
    "size_bytes": FUTURES_PREVIEW_R5_SIZE,
    "mode": f"{FUTURES_PREVIEW_R5_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_R5_MTIME_NS),
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": FUTURES_PREVIEW_R4_PREDECESSOR_BINDING,
}
FUTURES_PREVIEW_R6_TERMINAL_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r6.jsonl",
    "file_sha256": FUTURES_PREVIEW_R6_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_R6_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_R6_DEVICE),
    "inode": str(FUTURES_PREVIEW_R6_INODE),
    "size_bytes": FUTURES_PREVIEW_R6_SIZE,
    "mode": f"{FUTURES_PREVIEW_R6_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_R6_MTIME_NS),
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 1,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": FUTURES_PREVIEW_R5_TERMINAL_BINDING,
}
FUTURES_PREVIEW_R7_TERMINAL_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r7.jsonl",
    "file_sha256": FUTURES_PREVIEW_R7_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_R7_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_R7_DEVICE),
    "inode": str(FUTURES_PREVIEW_R7_INODE),
    "size_bytes": FUTURES_PREVIEW_R7_SIZE,
    "mode": f"{FUTURES_PREVIEW_R7_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_R7_MTIME_NS),
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 1,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": FUTURES_PREVIEW_R6_TERMINAL_BINDING,
}
FUTURES_PREVIEW_R8_TERMINAL_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r8.jsonl",
    "file_sha256": FUTURES_PREVIEW_R8_FILE_SHA256,
    "device": str(FUTURES_PREVIEW_R8_DEVICE),
    "inode": str(FUTURES_PREVIEW_R8_INODE),
    "size_bytes": FUTURES_PREVIEW_R8_SIZE,
    "mode": f"{FUTURES_PREVIEW_R8_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_R8_MTIME_NS),
    "nlink": 1,
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "opaque_hash_stat_binding": True,
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": FUTURES_PREVIEW_R7_TERMINAL_BINDING,
}
FUTURES_PREVIEW_R9_TERMINAL_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r9.jsonl",
    "file_sha256": FUTURES_PREVIEW_R9_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_R9_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_R9_DEVICE),
    "inode": str(FUTURES_PREVIEW_R9_INODE),
    "size_bytes": FUTURES_PREVIEW_R9_SIZE,
    "mode": f"{FUTURES_PREVIEW_R9_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_R9_MTIME_NS),
    "nlink": FUTURES_PREVIEW_R9_NLINK,
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 1,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": FUTURES_PREVIEW_R8_TERMINAL_BINDING,
}
FUTURES_PREVIEW_R10_TERMINAL_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r10.jsonl",
    "file_sha256": FUTURES_PREVIEW_R10_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_R10_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_R10_DEVICE),
    "inode": str(FUTURES_PREVIEW_R10_INODE),
    "size_bytes": FUTURES_PREVIEW_R10_SIZE,
    "mode": f"{FUTURES_PREVIEW_R10_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_R10_MTIME_NS),
    "nlink": FUTURES_PREVIEW_R10_NLINK,
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 1,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": FUTURES_PREVIEW_R9_TERMINAL_BINDING,
}


def _rebind_preview_filesystem_identity(
    binding: Mapping[str, Any],
    *,
    identity: tuple[int, int],
    predecessor_binding: Mapping[str, Any] | None,
) -> dict[str, Any]:
    rebound = dict(binding)
    rebound["device"] = str(identity[0])
    rebound["inode"] = str(identity[1])
    if predecessor_binding is None:
        rebound.pop("original_predecessor_binding", None)
    else:
        rebound["original_predecessor_binding"] = dict(predecessor_binding)
    return rebound


_FUTURES_PREVIEW_EC2_ORIGINAL_BINDING = _rebind_preview_filesystem_identity(
    FUTURES_PREVIEW_ORIGINAL_PREDECESSOR_BINDING,
    identity=_FUTURES_PREVIEW_EC2_IDENTITIES["original"],
    predecessor_binding=None,
)
_FUTURES_PREVIEW_EC2_R1_BINDING = _rebind_preview_filesystem_identity(
    FUTURES_PREVIEW_R1_PREDECESSOR_BINDING,
    identity=_FUTURES_PREVIEW_EC2_IDENTITIES["r1"],
    predecessor_binding=_FUTURES_PREVIEW_EC2_ORIGINAL_BINDING,
)
_FUTURES_PREVIEW_EC2_R2_BINDING = _rebind_preview_filesystem_identity(
    FUTURES_PREVIEW_PREDECESSOR_BINDING,
    identity=_FUTURES_PREVIEW_EC2_IDENTITIES["r2"],
    predecessor_binding=_FUTURES_PREVIEW_EC2_R1_BINDING,
)
_FUTURES_PREVIEW_EC2_R3_BINDING = _rebind_preview_filesystem_identity(
    FUTURES_PREVIEW_R3_PREDECESSOR_BINDING,
    identity=_FUTURES_PREVIEW_EC2_IDENTITIES["r3"],
    predecessor_binding=_FUTURES_PREVIEW_EC2_R2_BINDING,
)
_FUTURES_PREVIEW_EC2_R4_BINDING = _rebind_preview_filesystem_identity(
    FUTURES_PREVIEW_R4_PREDECESSOR_BINDING,
    identity=_FUTURES_PREVIEW_EC2_IDENTITIES["r4"],
    predecessor_binding=_FUTURES_PREVIEW_EC2_R3_BINDING,
)
_CONSUMED_PREVIEW_IDENTIFIER_SHA256 = frozenset(
    {
        "4f4d5fc1c11bf9d1d974f91dbd9977e74be88f64a63f93ab206e4e744dd264c0",
        "a6165a6c75e29dce7c080d989272ee78abd0c04ca5db60659067487dc6b08f96",
        "973555423899d7e9156fcee19aa09eba05b05a1402d9a4665894a161bedddda3",
        "a0ab3501ea96ee35fcd5594000df704b191e5d2daf2a014bebd7781a0819e876",
        "8821931a9ff34ee20cefb29b9e92d4cccf7fc638ea5e19d720417359ebd7c210",
        "8b5153010623f913c4e56434db957fe6a8772809827eb6f0519e43d80fd10d9a",
        "760776f0a189825f6151c8d4ebe232e22f2fddd05939308377586eaab7a92e10",
        "87432ff9181eca9605ade3ac21ce4995370afbf359f7d00055339d5035004d41",
        "560704840dfb2fe08cc2fb1cf3d91286f19162d3d16d037f285213db0d8b8790",
        "e5ff88abcc817355117e563d7164cfa89bb6a9358da405d0681d13effe5c6476",
    }
)
_R6_CONSUMED_PREVIEW_IDENTIFIER_SHA256 = _CONSUMED_PREVIEW_IDENTIFIER_SHA256 | {
    "713661e32ef51bafdb3039fdfd70d5d6ffb672b58ff75e64de1aaa637c89a70c",
    "5d2fe0644770aef26a3fd1c4cab138c589138aba671b249dfbeedf13ea71e1ad",
}
_R7_CONSUMED_PREVIEW_IDENTIFIER_SHA256 = (
    _R6_CONSUMED_PREVIEW_IDENTIFIER_SHA256
    | frozenset({
        "525928d556e0ad5461b4dee7424a4bb5040d9c3d224da5e91746a6587bed4115",
        "b9177e87cec7b31c35e66a1281aaa5e36c404efa8cc52558388cc0aaa37938d9",
    })
)
_R10_CONSUMED_PREVIEW_IDENTIFIER_SHA256 = (
    _R7_CONSUMED_PREVIEW_IDENTIFIER_SHA256
    | frozenset(
        {
            "2e6e0a5fe74403d8c76cebb61a38d8a1c13f4a95af697cacd87cb6e2a49d399d",
            "ec860afe967dd58e25b32c45c9dfd215ad858e1e8e65f0d459865a0631b5f38d",
        }
    )
)
_R11_CONSUMED_PREVIEW_IDENTIFIER_SHA256 = (
    _R10_CONSUMED_PREVIEW_IDENTIFIER_SHA256
)


def _preview_identifier_was_consumed(
    identifier: Any,
    *,
    artifact_type: str,
) -> bool:
    """Reject predecessor UUID reuse without exposing the latest raw IDs."""

    if not isinstance(identifier, str):
        return False
    identifier_sha256 = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    consumed_sha256 = {
        _R6_ARTIFACT_TYPE: _R6_CONSUMED_PREVIEW_IDENTIFIER_SHA256,
        _R7_ARTIFACT_TYPE: _R7_CONSUMED_PREVIEW_IDENTIFIER_SHA256,
        _R8_ARTIFACT_TYPE: _R7_CONSUMED_PREVIEW_IDENTIFIER_SHA256,
        _R9_ARTIFACT_TYPE: _R7_CONSUMED_PREVIEW_IDENTIFIER_SHA256,
        _R10_ARTIFACT_TYPE: _R10_CONSUMED_PREVIEW_IDENTIFIER_SHA256,
        _R11_ARTIFACT_TYPE: _R11_CONSUMED_PREVIEW_IDENTIFIER_SHA256,
    }.get(artifact_type, _CONSUMED_PREVIEW_IDENTIFIER_SHA256)
    return identifier_sha256 in consumed_sha256


FUTURES_PREVIEW_R6_MARGIN_WINDOW_POLICY_BINDING = {
    "schema_version": "3",
    "policy_id": "slice2_preview_margin_window_exact_pair_policy_v3",
    "pair_policy_mode": "exact_profile_state_pair",
    "profile_state_pairs": [
        {
            "policy_row_index": 0,
            "profile": "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
            "margin_window_type": "MARGIN_WINDOW_TYPE_UNSPECIFIED",
        },
        {
            "policy_row_index": 1,
            "profile": "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
            "margin_window_type": "MARGIN_WINDOW_TYPE_INTRADAY",
        },
    ],
    "enum_authority": "official_coinbase_advanced_trade_api_docs",
    "profile_state_policy_authority": (
        "operator_defined_slice_2_preview_only_not_coinbase_documented"
    ),
    "profile_state_mapping_documented_by_coinbase": False,
    "eligibility_scope": "slice_2_preview_only",
    "r6_attempt_authority_granted": False,
    "execution_allowed": False,
    "create_order_eligibility_granted": False,
    "later_live_eligibility_granted": False,
}
FUTURES_PREVIEW_R7_RESPONSE_SCHEMA_BINDING = {
    "schema_version": "1",
    "policy_id": "slice2_preview_liquidation_evidence_schema_v1",
    "schema_authority": "official_coinbase_advanced_trade_api_docs",
    "margin_ratio_data_replaces_legacy_liquidation_buffers": True,
    "predicted_liquidation_price_required": False,
    "present_predicted_liquidation_price_policy": "finite_and_positive",
    "persisted_response_policy": "sanitized_allowlist_only",
}
FUTURES_PREVIEW_R10_RESPONSE_SCHEMA_BINDING = {
    "schema_version": "2",
    "policy_id": "slice2_preview_liquidation_evidence_schema_v2",
    "schema_authority": "official_coinbase_advanced_trade_api_docs",
    "margin_ratio_data_replaces_legacy_liquidation_buffers": True,
    "documented_legacy_and_replacement_key_coexistence": True,
    "legacy_liquidation_values_policy": "ignored_never_parsed_or_persisted",
    "margin_ratio_data_policy": "required_authoritative_liquidation_evidence",
    "predicted_liquidation_price_required": False,
    "present_predicted_liquidation_price_policy": "finite_and_positive",
    "persisted_response_policy": "sanitized_allowlist_only",
}
FUTURES_PREVIEW_POST_R10_COMPATIBILITY_BINDING = {
    "schema_version": "3",
    "policy_id": "post_r10_preview_wire_schema_and_acceptance_policy_v3",
    "schema_authority": "official_coinbase_advanced_trade_api_docs",
    "official_spec_url": (
        "https://docs.cdp.coinbase.com/api-reference/"
        "advanced-trade-api/rest-api/advanced-trade-spec.yaml"
    ),
    "official_spec_sha256": (
        "7115b6b13132565a0a65371aadc9a0e09c725860ae5119655d8cd4d8c226a6b7"
    ),
    "official_spec_retrieved_at": "2026-07-16",
    "wire_schema_and_project_acceptance_separated": True,
    "official_required_response_fields": [
        "order_total",
        "commission_total",
        "errs",
        "warning",
        "quote_size",
        "base_size",
        "best_bid",
        "best_ask",
        "is_max",
    ],
    "official_optional_project_required_fields": [
        "preview_id",
        "order_margin_total",
        "margin_ratio_data",
    ],
    "official_required_margin_ratio_child_fields": [],
    "policy_relevant_optional_field_types_enforced_when_present": True,
    "other_optional_fields_policy": (
        "ignored_uninspected_no_project_policy_relevance"
    ),
    "project_required_margin_ratio_child_fields": [
        "current_margin_ratio",
        "projected_margin_ratio",
    ],
    "is_max_project_policy": "must_be_false_for_exact_one_contract",
    "decimal_token_policy": "plain_bounded_non_exponent_string",
    "negative_zero_policy": "canonicalize_to_zero",
    "official_sdk_version_verified": "1.8.4",
    "sdk_response_mapping_policy": (
        "mapping_or_shallow_attributes_before_validation_"
        "never_recursive_plain"
    ),
    "preview_id_handling_policy": (
        "ephemeral_restricted_hash_or_withhold_before_"
        "persistence_or_readback"
    ),
    "runner_integration_status": "not_wired",
    "project_acceptance_policy": "fail_closed_no_fallback",
    "persisted_diagnostic_policy": "fixed_value_blind_category_only",
    "r11_attempt_authority_granted": False,
    "coinbase_call_authority_granted": False,
    "exchange_mutation_authority_granted": False,
}
FUTURES_PREVIEW_R11_RESPONSE_SCHEMA_BINDING = {
    **deepcopy(FUTURES_PREVIEW_POST_R10_COMPATIBILITY_BINDING),
    "runner_integration_status": (
        "wired_r11_shallow_raw_before_recursive_plain"
    ),
    "r11_attempt_authority_granted": True,
    "coinbase_call_authority_granted": True,
    "preview_call_limit": 1,
    "retry_call_limit": 0,
    "exchange_mutation_authority_granted": False,
}
_POST_R10_OFFICIAL_REQUIRED_STRING_FIELDS = (
    "order_total",
    "commission_total",
    "quote_size",
    "base_size",
    "best_bid",
    "best_ask",
)
_POST_R10_OFFICIAL_REQUIRED_LIST_FIELDS = ("errs", "warning")
_POST_R10_OFFICIAL_OPTIONAL_PROJECT_FIELDS = (
    "preview_id",
    "order_margin_total",
    "margin_ratio_data",
)
_POST_R10_OFFICIAL_SCHEMA_INTERNAL_REASONS = frozenset(
    {
        "futures_preview_response_official_response_missing",
        "futures_preview_response_official_is_max_missing",
        "futures_preview_response_official_is_max_type_invalid",
        *(
            reason
            for field in _POST_R10_OFFICIAL_REQUIRED_STRING_FIELDS
            for reason in (
                f"futures_preview_response_official_{field}_missing",
                f"futures_preview_response_official_{field}_type_invalid",
            )
        ),
        *(
            reason
            for field in _POST_R10_OFFICIAL_REQUIRED_LIST_FIELDS
            for reason in (
                f"futures_preview_response_official_{field}_missing",
                f"futures_preview_response_official_{field}_type_invalid",
            )
        ),
        *(
            f"futures_preview_response_official_{field}_item_type_invalid"
            for field in _POST_R10_OFFICIAL_REQUIRED_LIST_FIELDS
        ),
        *(
            f"futures_preview_response_official_{field}_type_invalid"
            for field in (
                "preview_id",
                "order_margin_total",
                "margin_ratio_data",
                "current_margin_ratio",
                "projected_margin_ratio",
                "predicted_liquidation_price",
            )
        ),
    }
)
_POST_R10_CORE_ECONOMICS_INTERNAL_REASONS = frozenset(
    {
        *(
            f"futures_preview_response_{field}_invalid"
            for field in _POST_R10_OFFICIAL_REQUIRED_STRING_FIELDS
        ),
        *(
            f"futures_preview_response_{field}_not_positive"
            for field in _POST_R10_OFFICIAL_REQUIRED_STRING_FIELDS
            if field != "commission_total"
        ),
        "futures_preview_response_commission_total_negative",
    }
)
_POST_R10_PROJECT_IDENTIFIER_INTERNAL_REASONS = frozenset(
    {
        "futures_preview_response_project_preview_id_missing",
        "futures_preview_response_project_preview_id_invalid",
    }
)
_POST_R10_PROJECT_MARGIN_INTERNAL_REASONS = frozenset(
    {
        "futures_preview_response_project_order_margin_total_missing",
        "futures_preview_response_project_order_margin_total_invalid",
        "futures_preview_response_project_order_margin_total_not_finite_or_positive",
    }
)
_POST_R10_LIQUIDATION_INVALID_INTERNAL_REASONS = frozenset(
    {
        "futures_preview_response_liquidation_replacement_invalid",
        "futures_preview_response_project_current_margin_ratio_missing",
        "futures_preview_response_project_projected_margin_ratio_missing",
        "futures_preview_response_project_current_margin_ratio_invalid",
        "futures_preview_response_project_projected_margin_ratio_invalid",
        "futures_preview_response_project_current_margin_ratio_not_finite_or_negative",
        "futures_preview_response_project_projected_margin_ratio_not_finite_or_negative",
        "futures_preview_response_project_predicted_liquidation_price_invalid",
        "futures_preview_response_project_predicted_liquidation_price_not_finite_or_positive",
    }
)
_POST_R10_PREVIEW_RESPONSE_REJECTION_REASONS = frozenset(
    {
        *_POST_R10_OFFICIAL_SCHEMA_INTERNAL_REASONS,
        *_POST_R10_CORE_ECONOMICS_INTERNAL_REASONS,
        *_POST_R10_PROJECT_IDENTIFIER_INTERNAL_REASONS,
        *_POST_R10_PROJECT_MARGIN_INTERNAL_REASONS,
        *_POST_R10_LIQUIDATION_INVALID_INTERNAL_REASONS,
        "futures_preview_response_exchange_errors_present",
        "futures_preview_response_exchange_warnings_present",
        "futures_preview_response_project_is_max_true",
        "futures_preview_response_liquidation_replacement_missing",
    }
)
_POST_R10_DECIMAL_TOKEN = re.compile(r"-?[0-9]+(?:\.[0-9]+)?\Z")
_POST_R10_MAX_DECIMAL_TOKEN_LENGTH = 128
_POST_PREVIEW_STAGE_ORDER = (
    "preview_response_validation",
    "candidate_cap_binding",
    "available_margin_validation",
    "seal_ready_plan_construction",
    "accepted_evidence_construction",
    "terminal_predecessor_validation",
)
_POST_PREVIEW_STAGE_FALLBACK_REASONS = {
    "preview_response_validation": (
        "futures_preview_response_validation_unclassified"
    ),
    "candidate_cap_binding": (
        "futures_preview_candidate_cap_binding_unclassified"
    ),
    "available_margin_validation": (
        "futures_preview_available_margin_validation_unclassified"
    ),
    "seal_ready_plan_construction": (
        "futures_preview_seal_ready_plan_construction_unclassified"
    ),
    "accepted_evidence_construction": (
        "futures_preview_accepted_evidence_construction_unclassified"
    ),
    "terminal_predecessor_validation": (
        "futures_preview_terminal_predecessor_validation_unclassified"
    ),
}
_R10_PREVIEW_RESPONSE_DIAGNOSTIC_REASONS = frozenset(
    {
        "futures_preview_response_envelope_invalid",
        "futures_preview_response_exchange_errors_present",
        "futures_preview_response_exchange_warnings_present",
        "futures_preview_response_economics_invalid",
        "futures_preview_response_liquidation_replacement_missing",
        "futures_preview_response_liquidation_replacement_invalid",
        "futures_preview_response_normalization_invariant_invalid",
    }
)
_POST_PREVIEW_STAGE_ALLOWLISTED_REASONS = {
    "preview_response_validation": frozenset(),
    "candidate_cap_binding": frozenset(
        {
            "futures_preview_base_size_candidate_mismatch",
            "futures_preview_response_book_ambiguous",
            "futures_preview_response_opening_cap_blocked",
            "futures_preview_response_exposure_cap_blocked",
            "futures_preview_response_buffered_close_cap_blocked",
            "futures_preview_response_turnover_cap_blocked",
        }
    ),
    "available_margin_validation": frozenset(
        {"futures_preview_available_margin_insufficient"}
    ),
    "seal_ready_plan_construction": frozenset(),
    "accepted_evidence_construction": frozenset(),
    "terminal_predecessor_validation": frozenset(
        {"futures_preview_predecessor_terminal_binding_changed"}
    ),
}
_R10_POST_PREVIEW_STAGE_ALLOWLISTED_REASONS = {
    **_POST_PREVIEW_STAGE_ALLOWLISTED_REASONS,
    "preview_response_validation": _R10_PREVIEW_RESPONSE_DIAGNOSTIC_REASONS,
}
_R11_POST_PREVIEW_STAGE_ALLOWLISTED_REASONS = {
    **_POST_PREVIEW_STAGE_ALLOWLISTED_REASONS,
    "preview_response_validation": _POST_R10_PREVIEW_RESPONSE_REJECTION_REASONS,
}
FUTURES_PREVIEW_R8_POST_PREVIEW_DIAGNOSTIC_BINDING = {
    "schema_version": "1",
    "policy_id": "slice2_preview_post_return_stage_diagnostic_v1",
    "stage_order": list(_POST_PREVIEW_STAGE_ORDER),
    "persisted_evidence": "ordered_sanitized_stage_prefix_only",
    "raw_response_included": False,
    "external_exception_text_included": False,
    "identifier_values_included": False,
}
FUTURES_PREVIEW_R10_POST_PREVIEW_DIAGNOSTIC_BINDING = {
    "schema_version": "2",
    "policy_id": "slice2_preview_post_return_stage_diagnostic_v2",
    "stage_order": list(_POST_PREVIEW_STAGE_ORDER),
    "persisted_evidence": "ordered_sanitized_stage_prefix_only",
    "response_validation_reason_policy": (
        "fixed_internal_category_allowlist_only"
    ),
    "raw_response_included": False,
    "external_exception_text_included": False,
    "identifier_values_included": False,
}
FUTURES_PREVIEW_R11_POST_PREVIEW_DIAGNOSTIC_BINDING = {
    "schema_version": "3",
    "policy_id": "slice2_preview_post_return_stage_diagnostic_v3",
    "stage_order": list(_POST_PREVIEW_STAGE_ORDER),
    "persisted_evidence": "ordered_sanitized_stage_prefix_only",
    "response_validation_reason_policy": (
        "fixed_post_r10_value_blind_reason_allowlist_only"
    ),
    "unknown_preview_reason_policy": "fixed_value_blind_constant_only",
    "raw_response_included": False,
    "external_exception_text_included": False,
    "identifier_values_included": False,
}
_SAFE_MARGIN_SETTING_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SAFE_MARGIN_WINDOW_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_SDK_MARGIN_SETTING_FIELDS = {
    "setting",
    "rate_limit_remaining",
    "rate_limit_reset",
    "rate_limit_limit",
}
_PRE_PREVIEW_STAGE_ORDER = (
    "remaining_margin_validation",
    "candidate_construction",
    "preview_request_construction",
    "terminal_context_sanitization",
)
_PRE_PREVIEW_STAGE_FALLBACK_REASONS = {
    "remaining_margin_validation": (
        "futures_preview_remaining_margin_validation_unclassified"
    ),
    "candidate_construction": (
        "futures_preview_candidate_construction_unclassified"
    ),
    "preview_request_construction": (
        "futures_preview_request_construction_unclassified"
    ),
    "terminal_context_sanitization": (
        "futures_preview_terminal_context_sanitization_unclassified"
    ),
}
_PRE_PREVIEW_STAGE_ALLOWLISTED_REASONS = {
    "remaining_margin_validation": frozenset(
        {
            "futures_preview_margin_collateral_ambiguous",
            "futures_preview_margin_source_reads_ambiguous",
            "futures_preview_available_margin_currency_invalid",
            "futures_preview_available_margin_invalid",
            "futures_preview_total_usd_balance_currency_invalid",
            "futures_preview_total_usd_balance_invalid",
            "futures_preview_cfm_usd_balance_currency_invalid",
            "futures_preview_cfm_usd_balance_invalid",
            "futures_preview_futures_buying_power_currency_invalid",
            "futures_preview_futures_buying_power_invalid",
            "futures_preview_initial_margin_currency_invalid",
            "futures_preview_initial_margin_invalid",
            "futures_preview_liquidation_threshold_currency_invalid",
            "futures_preview_liquidation_threshold_invalid",
            "futures_preview_margin_window_measure_ambiguous",
            "futures_preview_maintenance_margin_invalid",
            "futures_preview_liquidation_buffer_invalid",
            "futures_preview_margin_maintenance_margin_invalid",
            "futures_preview_margin_liquidation_buffer_invalid",
            "futures_preview_margin_setting_ambiguous",
            "futures_preview_margin_setting_unspecified",
            "futures_preview_margin_windows_ambiguous",
            "futures_preview_margin_killswitch_ambiguous",
            "futures_preview_margin_killswitch_enabled",
            "futures_preview_margin_sweeps_ambiguous",
            "futures_preview_available_margin_not_positive",
        }
    ),
    "candidate_construction": frozenset(
        {
            "futures_preview_product_identity_blocked",
            "futures_preview_avp_display_name_blocked",
            "futures_preview_product_type_blocked",
            "futures_preview_product_status_blocked",
            "futures_preview_product_trading_blocked",
            "futures_preview_avp_perp_style_identity_blocked",
            "futures_preview_contract_size_invalid",
            "futures_preview_avp_contract_size_blocked",
            "futures_preview_product_price_invalid",
            "futures_preview_price_increment_invalid",
            "futures_preview_base_increment_invalid",
            "futures_preview_base_min_size_invalid",
            "futures_preview_one_contract_rule_blocked",
            "futures_preview_pricebook_missing",
            "futures_preview_pricebook_ambiguous",
            "futures_preview_market_time_missing",
            "futures_preview_market_time_invalid",
            "futures_preview_market_time_unzoned",
            "futures_preview_market_stale",
            "futures_preview_bids_missing",
            "futures_preview_bids_price_invalid",
            "futures_preview_asks_missing",
            "futures_preview_asks_price_invalid",
            "futures_preview_crossed_or_ambiguous_book",
            "futures_preview_best_bid_tick_misaligned",
            "futures_preview_limit_tick_blocked",
            "futures_preview_positions_ambiguous",
            "futures_preview_position_contracts_invalid",
            "futures_preview_existing_product_exposure_blocked",
            "futures_preview_opening_cap_blocked",
            "futures_preview_exposure_cap_blocked",
            "futures_preview_buffered_close_cap_blocked",
            "futures_preview_turnover_cap_blocked",
        }
    ),
    "preview_request_construction": frozenset(),
    "terminal_context_sanitization": frozenset(),
}
_TERMINAL_FAILURE_CONTEXT_ALLOWED_KEYS = frozenset(
    {
        "portfolio_id",
        "portfolio_binding",
        "permission_evidence",
        "permission_evidence_sha256",
        "portfolio_catalog_evidence",
        "portfolio_catalog_sha256",
        "product_evidence",
        "product_evidence_sha256",
        "market_evidence",
        "market_evidence_sha256",
        "position_evidence",
        "position_evidence_sha256",
        "margin_collateral_evidence",
        "margin_collateral_evidence_sha256",
        "margin_setting_evidence",
        "margin_setting_evidence_sha256",
        "margin_windows_evidence",
        "margin_windows_evidence_sha256",
        "margin_windows_policy_evidence",
        "margin_windows_policy_evidence_sha256",
        "candidate",
        "candidate_sha256",
        "preview_request",
        "preview_request_sha256",
        "preview_response",
        "preview_response_sha256",
        "post_preview_stage_evidence",
        "post_preview_stage_evidence_sha256",
    }
)


class FuturesOrderPreviewArtifactError(RuntimeError):
    """Raised when one-shot Preview evidence is unavailable or unsafe."""


class FuturesOrderPreviewAcceptedHandoffError(
    FuturesOrderPreviewArtifactError
):
    """Accepted evidence persisted, but the ephemeral handoff did not finish."""


class _FuturesOrderPreviewTerminalPersistenceError(
    FuturesOrderPreviewArtifactError
):
    """The one-use claim exists but terminal evidence could not be appended."""


_R10_RESPONSE_ENVELOPE_INTERNAL_REASONS = frozenset(
    {
        "futures_preview_response_missing",
        "futures_preview_response_errors_ambiguous",
        "futures_preview_response_warning_ambiguous",
        "futures_preview_response_preview_id_missing",
        "futures_preview_response_preview_id_invalid",
    }
)
_R10_RESPONSE_ECONOMICS_FIELDS = (
    "order_total",
    "commission_total",
    "quote_size",
    "base_size",
    "best_bid",
    "best_ask",
    "order_margin_total",
)
_R10_RESPONSE_ECONOMICS_INTERNAL_REASONS = frozenset(
    {
        reason
        for field in _R10_RESPONSE_ECONOMICS_FIELDS
        for reason in (
            f"futures_preview_response_{field}_missing",
            f"futures_preview_{field}_invalid",
            f"futures_preview_response_{field}_not_finite",
            f"futures_preview_response_{field}_negative",
            f"futures_preview_response_{field}_not_positive",
        )
    }
)
_R10_RESPONSE_LIQUIDATION_INVALID_INTERNAL_REASONS = frozenset(
    {
        "futures_preview_current_margin_ratio_invalid",
        "futures_preview_projected_margin_ratio_invalid",
        "futures_preview_margin_ratio_current_margin_ratio_not_finite_or_negative",
        "futures_preview_margin_ratio_projected_margin_ratio_not_finite_or_negative",
        "futures_preview_predicted_liquidation_price_invalid",
        "futures_preview_predicted_liquidation_price_not_finite_or_positive",
    }
)


def _classify_r10_preview_response_validation_reason(
    exc: Exception,
) -> str | None:
    """Map only exact internal ValueError codes to value-blind categories."""

    if (
        type(exc) is not ValueError
        or len(exc.args) != 1
        or not isinstance(exc.args[0], str)
    ):
        return None
    reason = exc.args[0]
    if reason in _R10_RESPONSE_ENVELOPE_INTERNAL_REASONS:
        return "futures_preview_response_envelope_invalid"
    if reason == "futures_preview_response_errors_present":
        return "futures_preview_response_exchange_errors_present"
    if reason == "futures_preview_response_warning_present":
        return "futures_preview_response_exchange_warnings_present"
    if reason in _R10_RESPONSE_ECONOMICS_INTERNAL_REASONS:
        return "futures_preview_response_economics_invalid"
    if reason == (
        "futures_preview_r10_response_schema_liquidation_replacement_missing"
    ):
        return "futures_preview_response_liquidation_replacement_missing"
    if reason in _R10_RESPONSE_LIQUIDATION_INVALID_INTERNAL_REASONS:
        return "futures_preview_response_liquidation_replacement_invalid"
    if reason == (
        "futures_preview_r10_response_schema_liquidation_evidence_invalid"
    ):
        return "futures_preview_response_normalization_invariant_invalid"
    return None


def _redacted_preflight_blocker(exc: Exception) -> str:
    """Return only an exception type label, never response text."""

    return f"preflight_or_preview_blocked:{type(exc).__name__}"


def _pre_preview_stage_failure_context(
    *,
    passed_stages: Sequence[str],
    blocked_stage: str,
    exc: Exception,
) -> dict[str, Any]:
    """Return fixed, sanitized stage evidence without inspecting exception text."""

    reason = _PRE_PREVIEW_STAGE_FALLBACK_REASONS[blocked_stage]
    if (
        type(exc) is ValueError
        and len(exc.args) == 1
        and isinstance(exc.args[0], str)
        and exc.args[0]
        in _PRE_PREVIEW_STAGE_ALLOWLISTED_REASONS[blocked_stage]
    ):
        reason = exc.args[0]
    stages = [
        {"stage": stage, "status": "passed", "reason_code": None}
        for stage in passed_stages
    ]
    stages.append(
        {
            "stage": blocked_stage,
            "status": "blocked",
            "reason_code": reason,
        }
    )
    diagnostic = {
        "schema_version": "1",
        "source": "backend_futures_preview_producer",
        "stages": stages,
        "sanitized": True,
        "raw_response_included": False,
        "external_exception_text_included": False,
        "identifier_values_included": False,
    }
    return {
        "pre_preview_stage_evidence": diagnostic,
        "pre_preview_stage_evidence_sha256": canonical_sha256(diagnostic),
    }


def _post_preview_stage_failure_context(
    *,
    passed_stages: Sequence[str],
    blocked_stage: str,
    exc: Exception,
    artifact_type: str | None = None,
) -> dict[str, Any]:
    """Return a strict stage prefix without response or exception content."""

    reason = _POST_PREVIEW_STAGE_FALLBACK_REASONS[blocked_stage]
    if (
        artifact_type == _R11_ARTIFACT_TYPE
        and blocked_stage == "preview_response_validation"
    ):
        classified_reason = classify_post_r10_preview_response_rejection(exc)
        if classified_reason is not None:
            reason = classified_reason
    elif (
        artifact_type == _R10_ARTIFACT_TYPE
        and blocked_stage == "preview_response_validation"
    ):
        classified_reason = (
            _classify_r10_preview_response_validation_reason(exc)
        )
        if classified_reason is not None:
            reason = classified_reason
    elif (
        type(exc) is ValueError
        and len(exc.args) == 1
        and isinstance(exc.args[0], str)
        and exc.args[0]
        in _POST_PREVIEW_STAGE_ALLOWLISTED_REASONS[blocked_stage]
    ):
        reason = exc.args[0]
    stages = [
        {"stage": stage, "status": "passed", "reason_code": None}
        for stage in passed_stages
    ]
    stages.append(
        {
            "stage": blocked_stage,
            "status": "blocked",
            "reason_code": reason,
        }
    )
    diagnostic = {
        "schema_version": "1",
        "source": "backend_futures_preview_producer",
        "stages": stages,
        "sanitized": True,
        "raw_response_included": False,
        "external_exception_text_included": False,
        "identifier_values_included": False,
    }
    return {
        "post_preview_stage_evidence": diagnostic,
        "post_preview_stage_evidence_sha256": canonical_sha256(diagnostic),
    }


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_plain(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _timestamp(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        return _plain(converter())
    if hasattr(value, "__dict__"):
        return _plain(vars(value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def canonical_json(value: Any) -> str:
    """Return deterministic compact UTF-8 JSON text."""

    return json.dumps(
        _plain(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    """Return SHA-256 for the canonical JSON representation."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _same_artifact_path(left: Path, right: Path) -> bool:
    """Compare paths lexically without following an artifact symlink."""

    return os.path.abspath(os.fspath(left)) == os.path.abspath(os.fspath(right))


def _futures_preview_r8_lock_path(artifact_path: Path) -> Path:
    """Keep the production lock in runtime state and test locks beside fixtures."""

    if _same_artifact_path(
        artifact_path,
        _PRODUCTION_FUTURES_PREVIEW_R8_ARTIFACT_PATH,
    ):
        return _PRODUCTION_FUTURES_PREVIEW_R8_LOCK_PATH
    return artifact_path.with_name(f".{artifact_path.name}.selector.lock")


@contextmanager
def _futures_preview_r8_advisory_lock(
    artifact_path: Path,
    *,
    exclusive: bool,
    nonblocking: bool = False,
) -> Iterator[None]:
    """Hold the shared selector/read or exclusive R8-R10 reservation lock."""

    lock_path = _futures_preview_r8_lock_path(Path(artifact_path))
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        parent = lock_path.parent.lstat()
    except OSError:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview successor selector lock is invalid"
        ) from None
    if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview successor selector lock is invalid"
        )
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | _NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview successor selector lock is invalid"
        ) from None
    try:
        opened = os.fstat(descriptor)
        current = lock_path.lstat()
        if not (
            stat.S_ISREG(opened.st_mode)
            and opened.st_uid == os.getuid()
            and stat.S_IMODE(opened.st_mode) == 0o600
            and opened.st_size == 0
            and (opened.st_dev, opened.st_ino)
            == (current.st_dev, current.st_ino)
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview successor selector lock is invalid"
            )
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if nonblocking:
            operation |= fcntl.LOCK_NB
        fcntl.flock(descriptor, operation)
        yield
    except OSError:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview successor selector lock is invalid"
        ) from None
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _configured_futures_order_preview_r8_artifact_path() -> Path | None:
    """Return a validated R8 terminal, or ``None`` only when it is absent."""

    try:
        FUTURES_PREVIEW_R8_ARTIFACT_PATH.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 terminal readback is invalid"
        ) from None
    else:
        if _same_artifact_path(
            FUTURES_PREVIEW_R8_ARTIFACT_PATH,
            _PRODUCTION_FUTURES_PREVIEW_R8_ARTIFACT_PATH,
        ):
            try:
                observed = (
                    validate_production_futures_order_preview_r8_opaque_chain()
                )
                if observed != FUTURES_PREVIEW_R8_TERMINAL_BINDING:
                    raise FuturesOrderPreviewArtifactError(
                        "futures Preview R8 forensic binding changed"
                    )
            except Exception:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R8 terminal readback is invalid"
                ) from None
            return FUTURES_PREVIEW_R8_ARTIFACT_PATH
        try:
            payload = FuturesOrderPreviewArtifactStore(
                FUTURES_PREVIEW_R8_ARTIFACT_PATH
            ).read_completed()
            if payload.get("artifact_type") != _R8_ARTIFACT_TYPE:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R8 terminal generation is invalid"
                )
            if (
                payload.get("predecessor_binding")
                != FUTURES_PREVIEW_R7_TERMINAL_BINDING
            ):
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R8 predecessor binding changed"
                )
            from application.admin_api.models import (
                AdminFuturesOrderPreviewResponse,
            )

            AdminFuturesOrderPreviewResponse.model_validate(payload)
        except Exception:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R8 terminal readback is invalid"
            ) from None
        return FUTURES_PREVIEW_R8_ARTIFACT_PATH


def _configured_futures_order_preview_r9_artifact_path() -> Path | None:
    """Return a validated R9 terminal, or ``None`` only when it is absent."""

    try:
        FUTURES_PREVIEW_R9_ARTIFACT_PATH.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R9 terminal readback is invalid"
        ) from None
    if _same_artifact_path(
        FUTURES_PREVIEW_R9_ARTIFACT_PATH,
        _PRODUCTION_FUTURES_PREVIEW_R9_ARTIFACT_PATH,
    ):
        try:
            observed = validate_production_futures_order_preview_r9_terminal()
            if observed != FUTURES_PREVIEW_R9_TERMINAL_BINDING:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R9 forensic binding changed"
                )
        except Exception:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R9 terminal readback is invalid"
            ) from None
        return FUTURES_PREVIEW_R9_ARTIFACT_PATH
    try:
        payload = FuturesOrderPreviewArtifactStore(
            FUTURES_PREVIEW_R9_ARTIFACT_PATH
        ).read_completed()
        if (
            payload.get("artifact_type") != _R9_ARTIFACT_TYPE
            or payload.get("predecessor_binding")
            != FUTURES_PREVIEW_R8_TERMINAL_BINDING
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R9 terminal generation is invalid"
            )
        from application.admin_api.models import (
            AdminFuturesOrderPreviewResponse,
        )

        AdminFuturesOrderPreviewResponse.model_validate(payload)
    except Exception:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R9 terminal readback is invalid"
        ) from None
    return FUTURES_PREVIEW_R9_ARTIFACT_PATH


def _configured_futures_order_preview_r10_artifact_path() -> Path | None:
    """Return a validated R10 terminal or an absent nonproduction override."""

    try:
        FUTURES_PREVIEW_R10_ARTIFACT_PATH.lstat()
    except FileNotFoundError:
        if _same_artifact_path(
            FUTURES_PREVIEW_R10_ARTIFACT_PATH,
            _PRODUCTION_FUTURES_PREVIEW_R10_ARTIFACT_PATH,
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R10 terminal readback is missing"
            ) from None
        return None
    except OSError:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R10 terminal readback is invalid"
        ) from None
    if _same_artifact_path(
        FUTURES_PREVIEW_R10_ARTIFACT_PATH,
        _PRODUCTION_FUTURES_PREVIEW_R10_ARTIFACT_PATH,
    ):
        try:
            observed = validate_production_futures_order_preview_r10_terminal()
            if observed != FUTURES_PREVIEW_R10_TERMINAL_BINDING:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R10 terminal binding changed"
                )
        except Exception:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R10 terminal readback is invalid"
            ) from None
        return FUTURES_PREVIEW_R10_ARTIFACT_PATH
    try:
        payload = FuturesOrderPreviewArtifactStore(
            FUTURES_PREVIEW_R10_ARTIFACT_PATH
        ).read_completed()
        if (
            payload.get("artifact_type") != _R10_ARTIFACT_TYPE
            or payload.get("predecessor_binding")
            != FUTURES_PREVIEW_R9_TERMINAL_BINDING
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R10 terminal generation is invalid"
            )
        from application.admin_api.models import (
            AdminFuturesOrderPreviewResponse,
        )

        AdminFuturesOrderPreviewResponse.model_validate(payload)
    except Exception:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R10 terminal readback is invalid"
        ) from None
    return FUTURES_PREVIEW_R10_ARTIFACT_PATH


def _configured_futures_order_preview_r11_artifact_path() -> Path | None:
    """Return a completed valid R11 terminal, or ``None`` only if absent."""

    try:
        FUTURES_PREVIEW_R11_ARTIFACT_PATH.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 terminal readback is invalid"
        ) from None
    try:
        payload = FuturesOrderPreviewArtifactStore(
            FUTURES_PREVIEW_R11_ARTIFACT_PATH
        ).read_completed()
        if (
            payload.get("artifact_type") != _R11_ARTIFACT_TYPE
            or payload.get("predecessor_binding")
            != FUTURES_PREVIEW_R10_TERMINAL_BINDING
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R11 terminal generation is invalid"
            )
        from application.admin_api.models import (
            AdminFuturesOrderPreviewResponse,
        )

        AdminFuturesOrderPreviewResponse.model_validate(payload)
    except Exception:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 terminal readback is invalid"
        ) from None
    return FUTURES_PREVIEW_R11_ARTIFACT_PATH


def _configured_futures_order_preview_artifact_path_unlocked() -> Path:
    """Select the latest terminal while the shared successor lock is held."""

    r11_path = _configured_futures_order_preview_r11_artifact_path()
    if r11_path is not None:
        return r11_path

    r10_path = _configured_futures_order_preview_r10_artifact_path()
    if r10_path is not None:
        return r10_path
    r9_path = _configured_futures_order_preview_r9_artifact_path()
    if r9_path is not None:
        return r9_path
    r8_path = _configured_futures_order_preview_r8_artifact_path()
    if r8_path is not None:
        return r8_path
    configured = os.environ.get(FUTURES_PREVIEW_ARTIFACT_ENV, "").strip()
    if configured:
        return Path(configured)
    try:
        FUTURES_PREVIEW_R7_ARTIFACT_PATH.lstat()
    except FileNotFoundError:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R7 terminal readback is missing"
        ) from None
    except OSError:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R7 terminal readback is invalid"
        ) from None
    else:
        try:
            terminal_binding = (
                validate_production_futures_order_preview_r7_terminal()
            )
            if terminal_binding != FUTURES_PREVIEW_R7_TERMINAL_BINDING:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R7 terminal binding changed"
                )
            payload = FuturesOrderPreviewArtifactStore(
                FUTURES_PREVIEW_R7_ARTIFACT_PATH
            ).read_completed()
            if payload.get("artifact_type") != _R7_ARTIFACT_TYPE:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R7 terminal generation is invalid"
                )
            from application.admin_api.models import (
                AdminFuturesOrderPreviewResponse,
            )

            AdminFuturesOrderPreviewResponse.model_validate(payload)
        except Exception:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R7 terminal readback is invalid"
            ) from None
        return FUTURES_PREVIEW_R7_ARTIFACT_PATH


def configured_futures_order_preview_artifact_path() -> Path:
    """Fail-closed select R11 through R7 without constructing a client."""

    with _futures_preview_r8_advisory_lock(
        FUTURES_PREVIEW_R8_ARTIFACT_PATH,
        exclusive=False,
    ):
        return _configured_futures_order_preview_artifact_path_unlocked()


class FuturesOrderPreviewArtifactStore:
    """One-file append-only claim/result store with fail-closed reads."""

    def __init__(
        self,
        path: Path,
        *,
        enforce_latest_selection: bool = False,
        reservation_lock_nonblocking: bool = False,
    ) -> None:
        self.path = Path(path)
        self.enforce_latest_selection = enforce_latest_selection
        self.reservation_lock_nonblocking = reservation_lock_nonblocking

    def reserve(self, claim: Mapping[str, Any]) -> str:
        """Exclusively create and fsync the one-use attempt claim."""

        artifact_type = claim.get("artifact_type")
        if artifact_type in {
            _R8_ARTIFACT_TYPE,
            _R9_ARTIFACT_TYPE,
            _R10_ARTIFACT_TYPE,
            _R11_ARTIFACT_TYPE,
        }:
            selector_artifact_path = (
                FUTURES_PREVIEW_R8_ARTIFACT_PATH
                if artifact_type in {_R9_ARTIFACT_TYPE, _R10_ARTIFACT_TYPE}
                or artifact_type == _R11_ARTIFACT_TYPE
                else self.path
            )
            with _futures_preview_r8_advisory_lock(
                selector_artifact_path,
                exclusive=True,
                nonblocking=self.reservation_lock_nonblocking,
            ):
                return self._reserve_unlocked(claim)
        return self._reserve_unlocked(claim)

    def _reserve_unlocked(self, claim: Mapping[str, Any]) -> str:
        """Create the claim after any required generation lock is held."""

        self._prepare_parent()
        try:
            current = self.path.lstat()
        except FileNotFoundError:
            current = None
        if current is not None:
            if stat.S_ISLNK(current.st_mode):
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview artifact path is a symlink"
                )
            raise FuturesOrderPreviewArtifactError(
                "futures Preview attempt is already consumed"
            )

        wrapped = self._record("claim", claim)
        payload = (canonical_json(wrapped) + "\n").encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW
        try:
            fd = os.open(self.path, flags, 0o600)
        except FileExistsError as exc:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview attempt is already consumed"
            ) from exc
        except OSError as exc:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact reservation failed"
            ) from exc
        try:
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_directory(self.path.parent)
        return str(wrapped["record_sha256"])

    def append_result(self, result: Mapping[str, Any]) -> str:
        """Append exactly one terminal result after a valid claim."""

        rows = self._read_rows()
        if len(rows) != 1 or rows[0].get("record_type") != "claim":
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact result cannot be appended"
            )
        claim_sha256 = str(rows[0]["record_sha256"])
        wrapped = self._record(
            "result",
            result,
            previous_record_sha256=claim_sha256,
        )
        if "outcome" in result:
            wrapped["outcome"] = str(result["outcome"])
            wrapped["record_sha256"] = _record_sha256(wrapped)
        payload = (canonical_json(wrapped) + "\n").encode("utf-8")

        before = self._safe_regular_lstat()
        flags = os.O_WRONLY | os.O_APPEND | _NOFOLLOW
        try:
            fd = os.open(self.path, flags)
        except OSError as exc:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact result append failed"
            ) from exc
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview artifact identity changed"
                )
            _write_all(fd, payload)
            os.fsync(fd)
            os.fchmod(fd, 0o400)
        finally:
            os.close(fd)
        _fsync_directory(self.path.parent)
        return str(wrapped["record_sha256"])

    def read_completed(self) -> dict[str, Any]:
        """Return a valid terminal accepted, blocked, or unknown record."""

        if self.enforce_latest_selection:
            with _futures_preview_r8_advisory_lock(
                FUTURES_PREVIEW_R8_ARTIFACT_PATH,
                exclusive=False,
            ):
                selected = (
                    _configured_futures_order_preview_artifact_path_unlocked()
                )
                if not _same_artifact_path(self.path, selected):
                    raise FuturesOrderPreviewArtifactError(
                        "futures Preview latest selection changed"
                    )
                return self._read_completed_unlocked()
        return self._read_completed_unlocked()

    def _read_completed_unlocked(self) -> dict[str, Any]:
        """Read one terminal after the caller has established lock context."""

        rows = self._read_rows()
        if len(rows) != 2:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact is not completed"
            )
        terminal = self._safe_regular_lstat()
        if stat.S_IMODE(terminal.st_mode) != 0o400:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview completed artifact mode is invalid"
            )
        claim, result = rows
        if (
            claim.get("record_type") != "claim"
            or result.get("record_type") != "result"
            or result.get("previous_record_sha256") != claim.get("record_sha256")
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact chain is tampered"
            )
        record = result.get("record")
        if result.get("outcome") not in {"accepted", "blocked", "unknown"} or not isinstance(record, Mapping):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact terminal outcome is invalid"
            )
        if (
            result.get("outcome") != record.get("outcome")
            or record.get("status") != record.get("outcome")
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact outcome is contradictory"
            )
        if record.get("claim_sha256") != claim.get("record_sha256"):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact claim binding is invalid"
            )
        claim_record = claim.get("record")
        if (
            isinstance(claim_record, Mapping)
            and claim_record.get("artifact_type") == _R5_ARTIFACT_TYPE
        ):
            _validate_r5_claim_record(claim_record)
        elif (
            isinstance(claim_record, Mapping)
            and claim_record.get("artifact_type") == _R6_ARTIFACT_TYPE
        ):
            _validate_r6_claim_record(claim_record)
        elif (
            isinstance(claim_record, Mapping)
            and claim_record.get("artifact_type") == _R7_ARTIFACT_TYPE
        ):
            _validate_r7_claim_record(claim_record)
        elif (
            isinstance(claim_record, Mapping)
            and claim_record.get("artifact_type") == _R8_ARTIFACT_TYPE
        ):
            _validate_r8_claim_record(claim_record)
        elif (
            isinstance(claim_record, Mapping)
            and claim_record.get("artifact_type") == _R9_ARTIFACT_TYPE
        ):
            _validate_r9_claim_record(claim_record)
        elif (
            isinstance(claim_record, Mapping)
            and claim_record.get("artifact_type") == _R10_ARTIFACT_TYPE
        ):
            _validate_r10_claim_record(claim_record)
        elif (
            isinstance(claim_record, Mapping)
            and claim_record.get("artifact_type") == _R11_ARTIFACT_TYPE
        ):
            _validate_r11_claim_record(claim_record)
        if not isinstance(claim_record, Mapping) or any(
            record.get(key) != claim_record.get(key)
            for key in (
                "artifact_type",
                "predecessor_binding",
                "reserved_at",
                "actor_id",
                "roles",
                "correlation_id",
                "correlation_id_sha256",
                "idempotency_key",
                "idempotency_key_sha256",
                "profile_label",
                "portfolio_type",
                "product_id",
            )
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact claim identity is invalid"
            )
        evidence = dict(record)
        expected_hash = str(evidence.get("evidence_sha256") or "")
        payload = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
        if not expected_hash or canonical_sha256(payload) != expected_hash:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview completed evidence is tampered"
            )
        return evidence

    def _prepare_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        parent = self.path.parent.lstat()
        if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact parent is unsafe"
            )

    def _safe_regular_lstat(self) -> os.stat_result:
        try:
            result = self.path.lstat()
        except FileNotFoundError as exc:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact is missing"
            ) from exc
        if stat.S_ISLNK(result.st_mode):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact path is a symlink"
            )
        if not stat.S_ISREG(result.st_mode):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact is not a regular file"
            )
        return result

    def _read_rows(self) -> list[dict[str, Any]]:
        before = self._safe_regular_lstat()
        if before.st_size <= 0 or before.st_size > _MAX_ARTIFACT_BYTES:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact size is invalid"
            )
        try:
            fd = os.open(self.path, os.O_RDONLY | _NOFOLLOW)
        except OSError as exc:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact cannot be read"
            ) from exc
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview artifact identity changed"
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_ARTIFACT_BYTES:
                    raise FuturesOrderPreviewArtifactError(
                        "futures Preview artifact is too large"
                    )
                chunks.append(chunk)
        finally:
            os.close(fd)
        raw = b"".join(chunks)
        if not raw.endswith(b"\n"):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact has an incomplete record"
            )
        try:
            rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact is tampered"
            ) from exc
        if not rows or len(rows) > 2 or any(not isinstance(row, dict) for row in rows):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact record count is invalid"
            )
        for row in rows:
            if row.get("schema_version") != _SCHEMA_VERSION:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview artifact schema is invalid"
                )
            if row.get("record_sha256") != _record_sha256(row):
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview artifact is tampered"
                )
        return rows

    @staticmethod
    def _record(
        record_type: str,
        record: Mapping[str, Any],
        *,
        previous_record_sha256: str | None = None,
    ) -> dict[str, Any]:
        wrapped: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "record_type": record_type,
            "previous_record_sha256": previous_record_sha256,
            "record": _plain(record),
        }
        wrapped["record_sha256"] = _record_sha256(wrapped)
        return wrapped


def validate_futures_order_preview_predecessor(
    path: Path,
    *,
    expected_file_sha256: str,
    expected_evidence_sha256: str,
    expected_device: int | None = None,
    expected_inode: int | None = None,
    expected_size: int | None = None,
    expected_mode: int = 0o400,
    expected_mtime_ns: int | None = None,
    expected_nlink: int | None = None,
    expected_artifact_type: str = "futures_exact_no_live_preview_slice_2r1",
    expected_blocker: str = (
        "preflight_or_preview_blocked:ValueError:"
        "futures_preview_margin_setting_ambiguous"
    ),
    expected_predecessor_binding: Mapping[str, Any] | None = (
        FUTURES_PREVIEW_ORIGINAL_PREDECESSOR_BINDING
    ),
    expected_evidence_predecessor_binding: Mapping[str, Any] | None = None,
    expected_preview_order_attempt_count: int = 0,
) -> dict[str, Any]:
    """Read and bind one exact immutable terminal Preview predecessor."""

    predecessor = Path(path)
    try:
        before = predecessor.lstat()
    except FileNotFoundError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor is missing"
        ) from exc
    mode = stat.S_IMODE(before.st_mode)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor is not a safe regular file"
        )
    if expected_device is not None and before.st_dev != expected_device:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor device changed"
        )
    if expected_inode is not None and before.st_ino != expected_inode:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor inode changed"
        )
    if expected_size is not None and before.st_size != expected_size:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor size changed"
        )
    if mode != expected_mode:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor mode changed"
        )
    if expected_mtime_ns is not None and before.st_mtime_ns != expected_mtime_ns:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor mtime changed"
        )
    if expected_nlink is not None and before.st_nlink != expected_nlink:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor link count changed"
        )
    if before.st_size <= 0 or before.st_size > _MAX_ARTIFACT_BYTES:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor size is invalid"
        )

    digest = hashlib.sha256()
    try:
        fd = os.open(predecessor, os.O_RDONLY | _NOFOLLOW)
    except OSError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor cannot be read"
        ) from exc
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview predecessor identity changed"
            )
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_ARTIFACT_BYTES:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview predecessor is too large"
                )
            digest.update(chunk)
    finally:
        os.close(fd)
    file_sha256 = digest.hexdigest()
    if not hmac.compare_digest(file_sha256, expected_file_sha256):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor file hash changed"
        )

    try:
        evidence = FuturesOrderPreviewArtifactStore(predecessor).read_completed()
    except FuturesOrderPreviewArtifactError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor terminal evidence is invalid"
        ) from exc
    evidence_sha256 = str(evidence.get("evidence_sha256") or "")
    attempts = _mapping(evidence.get("attempt_counters"))
    reads = _mapping(evidence.get("read_counters"))
    artifacts = _mapping(evidence.get("artifacts"))
    expected_zero_attempts = {
        "preview_order": expected_preview_order_attempt_count,
        "retry": 0,
        "fallback": 0,
        "create_order": 0,
        "cancel_order": 0,
        "close_position": 0,
        "reduce_position": 0,
    }
    expected_reads = {
        "api_key_permissions": 1,
        "portfolio_catalog": 1,
        "product": 1,
        "best_bid_ask": 1,
        "futures_positions": 1,
        "futures_margin_collateral": 1,
    }
    if (
        not hmac.compare_digest(evidence_sha256, expected_evidence_sha256)
        or evidence.get("artifact_type") != expected_artifact_type
        or evidence.get("status") != "blocked"
        or evidence.get("outcome") != "blocked"
        or evidence.get("blocker") != expected_blocker
        or attempts != expected_zero_attempts
        or reads != expected_reads
        or (
            expected_predecessor_binding is not None
            and evidence.get("predecessor_binding")
            != dict(
                expected_evidence_predecessor_binding
                or expected_predecessor_binding
            )
        )
        or evidence.get("exchange_submission_attempt_count") != 0
        or evidence.get("submitted_notional_usdc") != "0"
        or evidence.get("executed_notional_usdc") != "0"
        or artifacts
        != {
            "execution_marker_created": False,
            "attempt_ledger_created": False,
            "runtime_created": False,
        }
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor terminal evidence is invalid"
        )

    after = predecessor.lstat()
    if (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mode,
        after.st_mtime_ns,
    ) != (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mode,
        before.st_mtime_ns,
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor changed during validation"
        )

    binding = {
        "artifact_name": predecessor.name,
        "file_sha256": file_sha256,
        "evidence_sha256": evidence_sha256,
        "device": str(before.st_dev),
        "inode": str(before.st_ino),
        "size_bytes": before.st_size,
        "mode": f"{mode:04o}",
        "mtime_ns": str(before.st_mtime_ns),
        "status": "blocked",
        "outcome": "blocked",
        "preview_order_attempt_count": expected_preview_order_attempt_count,
        "exchange_submission_attempt_count": 0,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "preservation": "immutable_no_modify_delete_or_reuse",
    }
    if expected_predecessor_binding is not None:
        binding["original_predecessor_binding"] = dict(
            expected_predecessor_binding
        )
    if expected_nlink is not None:
        binding["nlink"] = expected_nlink
    return binding


def _validate_opaque_preview_artifact(
    path: Path,
    *,
    expected_file_sha256: str,
    expected_device: int,
    expected_inode: int,
    expected_size: int,
    expected_mode: int,
    expected_mtime_ns: int,
) -> None:
    """Bind immutable bytes and metadata without parsing prior JSON records."""

    artifact = Path(path)
    try:
        before = artifact.lstat()
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or before.st_dev != expected_device
            or before.st_ino != expected_inode
            or before.st_size != expected_size
            or stat.S_IMODE(before.st_mode) != expected_mode
            or before.st_mtime_ns != expected_mtime_ns
            or before.st_size <= 0
            or before.st_size > _MAX_ARTIFACT_BYTES
        ):
            raise ValueError("metadata")
        descriptor = os.open(artifact, os.O_RDONLY | _NOFOLLOW)
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError("identity")
            digest = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    raise ValueError("truncated")
                digest.update(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise ValueError("grew")
        finally:
            os.close(descriptor)
        after = artifact.lstat()
        if (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mode,
            after.st_uid,
            after.st_nlink,
            after.st_mtime_ns,
        ) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mode,
            before.st_uid,
            before.st_nlink,
            before.st_mtime_ns,
        ) or not hmac.compare_digest(
            digest.hexdigest(),
            expected_file_sha256,
        ):
            raise ValueError("binding")
    except Exception:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview opaque predecessor binding is invalid"
        ) from None


def _validate_opaque_preview_artifact_metadata_only(
    path: Path,
    *,
    expected_device: int,
    expected_inode: int,
    expected_size: int,
    expected_mode: int,
    expected_mtime_ns: int,
) -> None:
    """Validate fixed metadata without opening an opaque artifact."""

    artifact = Path(path)
    try:
        before = artifact.lstat()
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or before.st_dev != expected_device
            or before.st_ino != expected_inode
            or before.st_size != expected_size
            or stat.S_IMODE(before.st_mode) != expected_mode
            or before.st_mtime_ns != expected_mtime_ns
            or before.st_size <= 0
            or before.st_size > _MAX_ARTIFACT_BYTES
        ):
            raise ValueError("metadata")
        before_tuple = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after = artifact.lstat()
        after_tuple = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if before_tuple != after_tuple:
            raise ValueError("metadata changed")
    except Exception:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview opaque predecessor metadata is invalid"
        ) from None


def validate_production_futures_order_preview_r7_opaque_chain() -> dict[str, Any]:
    """Hash-bind original through R7 without deserializing prior evidence."""

    for values in (
        (
            FUTURES_PREVIEW_ORIGINAL_ARTIFACT_PATH,
            FUTURES_PREVIEW_ORIGINAL_FILE_SHA256,
            FUTURES_PREVIEW_ORIGINAL_DEVICE,
            FUTURES_PREVIEW_ORIGINAL_INODE,
            FUTURES_PREVIEW_ORIGINAL_SIZE,
            FUTURES_PREVIEW_ORIGINAL_MODE,
            FUTURES_PREVIEW_ORIGINAL_MTIME_NS,
        ),
        (
            FUTURES_PREVIEW_R1_ARTIFACT_PATH,
            FUTURES_PREVIEW_R1_FILE_SHA256,
            FUTURES_PREVIEW_R1_DEVICE,
            FUTURES_PREVIEW_R1_INODE,
            FUTURES_PREVIEW_R1_SIZE,
            FUTURES_PREVIEW_R1_MODE,
            FUTURES_PREVIEW_R1_MTIME_NS,
        ),
        (
            FUTURES_PREVIEW_PREDECESSOR_ARTIFACT_PATH,
            FUTURES_PREVIEW_PREDECESSOR_FILE_SHA256,
            FUTURES_PREVIEW_PREDECESSOR_DEVICE,
            FUTURES_PREVIEW_PREDECESSOR_INODE,
            FUTURES_PREVIEW_PREDECESSOR_SIZE,
            FUTURES_PREVIEW_PREDECESSOR_MODE,
            FUTURES_PREVIEW_PREDECESSOR_MTIME_NS,
        ),
        (
            FUTURES_PREVIEW_R3_ARTIFACT_PATH,
            FUTURES_PREVIEW_R3_FILE_SHA256,
            FUTURES_PREVIEW_R3_DEVICE,
            FUTURES_PREVIEW_R3_INODE,
            FUTURES_PREVIEW_R3_SIZE,
            FUTURES_PREVIEW_R3_MODE,
            FUTURES_PREVIEW_R3_MTIME_NS,
        ),
        (
            FUTURES_PREVIEW_R4_ARTIFACT_PATH,
            FUTURES_PREVIEW_R4_FILE_SHA256,
            FUTURES_PREVIEW_R4_DEVICE,
            FUTURES_PREVIEW_R4_INODE,
            FUTURES_PREVIEW_R4_SIZE,
            FUTURES_PREVIEW_R4_MODE,
            FUTURES_PREVIEW_R4_MTIME_NS,
        ),
        (
            FUTURES_PREVIEW_R5_ARTIFACT_PATH,
            FUTURES_PREVIEW_R5_FILE_SHA256,
            FUTURES_PREVIEW_R5_DEVICE,
            FUTURES_PREVIEW_R5_INODE,
            FUTURES_PREVIEW_R5_SIZE,
            FUTURES_PREVIEW_R5_MODE,
            FUTURES_PREVIEW_R5_MTIME_NS,
        ),
        (
            FUTURES_PREVIEW_R6_ARTIFACT_PATH,
            FUTURES_PREVIEW_R6_FILE_SHA256,
            FUTURES_PREVIEW_R6_DEVICE,
            FUTURES_PREVIEW_R6_INODE,
            FUTURES_PREVIEW_R6_SIZE,
            FUTURES_PREVIEW_R6_MODE,
            FUTURES_PREVIEW_R6_MTIME_NS,
        ),
        (
            FUTURES_PREVIEW_R7_ARTIFACT_PATH,
            FUTURES_PREVIEW_R7_FILE_SHA256,
            FUTURES_PREVIEW_R7_DEVICE,
            FUTURES_PREVIEW_R7_INODE,
            FUTURES_PREVIEW_R7_SIZE,
            FUTURES_PREVIEW_R7_MODE,
            FUTURES_PREVIEW_R7_MTIME_NS,
        ),
    ):
        (
            artifact_path,
            file_sha256,
            device,
            inode,
            size,
            mode,
            mtime_ns,
        ) = values
        _validate_opaque_preview_artifact(
            artifact_path,
            expected_file_sha256=file_sha256,
            expected_device=device,
            expected_inode=inode,
            expected_size=size,
            expected_mode=mode,
            expected_mtime_ns=mtime_ns,
        )
    return dict(FUTURES_PREVIEW_R7_TERMINAL_BINDING)


def validate_production_futures_order_preview_r8_opaque_chain() -> dict[str, Any]:
    """Hash-bind through R7 and stat-bind R8 without opening R8."""

    r7_binding = validate_production_futures_order_preview_r7_opaque_chain()
    if r7_binding != FUTURES_PREVIEW_R7_TERMINAL_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R7 opaque predecessor binding changed"
        )
    _validate_opaque_preview_artifact_metadata_only(
        FUTURES_PREVIEW_R8_ARTIFACT_PATH,
        expected_device=FUTURES_PREVIEW_R8_DEVICE,
        expected_inode=FUTURES_PREVIEW_R8_INODE,
        expected_size=FUTURES_PREVIEW_R8_SIZE,
        expected_mode=FUTURES_PREVIEW_R8_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_R8_MTIME_NS,
    )
    return dict(FUTURES_PREVIEW_R8_TERMINAL_BINDING)


def validate_production_futures_order_preview_r9_terminal() -> dict[str, Any]:
    """Model/hash/stat-bind sanitized consumed R9 plus its immutable chain."""

    r8_binding = validate_production_futures_order_preview_r8_opaque_chain()
    if r8_binding != FUTURES_PREVIEW_R8_TERMINAL_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 predecessor binding changed"
        )
    r9_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_R9_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_R9_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_R9_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_R9_DEVICE,
        expected_inode=FUTURES_PREVIEW_R9_INODE,
        expected_size=FUTURES_PREVIEW_R9_SIZE,
        expected_mode=FUTURES_PREVIEW_R9_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_R9_MTIME_NS,
        expected_nlink=FUTURES_PREVIEW_R9_NLINK,
        expected_artifact_type=FUTURES_PREVIEW_R9_ARTIFACT_TYPE,
        expected_blocker="post_preview_stage_blocked",
        expected_predecessor_binding=r8_binding,
        expected_preview_order_attempt_count=1,
    )
    try:
        from application.admin_api.models import (
            AdminFuturesOrderPreviewResponse,
        )

        AdminFuturesOrderPreviewResponse.model_validate(
            FuturesOrderPreviewArtifactStore(
                FUTURES_PREVIEW_R9_ARTIFACT_PATH
            ).read_completed()
        )
        _validate_opaque_preview_artifact(
            FUTURES_PREVIEW_R9_ARTIFACT_PATH,
            expected_file_sha256=FUTURES_PREVIEW_R9_FILE_SHA256,
            expected_device=FUTURES_PREVIEW_R9_DEVICE,
            expected_inode=FUTURES_PREVIEW_R9_INODE,
            expected_size=FUTURES_PREVIEW_R9_SIZE,
            expected_mode=FUTURES_PREVIEW_R9_MODE,
            expected_mtime_ns=FUTURES_PREVIEW_R9_MTIME_NS,
        )
    except Exception:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R9 terminal model validation failed"
        ) from None
    if r9_binding != FUTURES_PREVIEW_R9_TERMINAL_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R9 terminal binding changed"
        )
    return dict(FUTURES_PREVIEW_R9_TERMINAL_BINDING)


def validate_production_futures_order_preview_r10_terminal() -> dict[str, Any]:
    """Model/hash/stat-bind consumed R10 and its immutable predecessor chain."""

    r9_binding = validate_production_futures_order_preview_r9_terminal()
    if r9_binding != FUTURES_PREVIEW_R9_TERMINAL_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R9 predecessor binding changed"
        )
    r10_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_R10_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_R10_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_R10_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_R10_DEVICE,
        expected_inode=FUTURES_PREVIEW_R10_INODE,
        expected_size=FUTURES_PREVIEW_R10_SIZE,
        expected_mode=FUTURES_PREVIEW_R10_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_R10_MTIME_NS,
        expected_nlink=FUTURES_PREVIEW_R10_NLINK,
        expected_artifact_type=FUTURES_PREVIEW_R10_ARTIFACT_TYPE,
        expected_blocker="post_preview_stage_blocked",
        expected_predecessor_binding=r9_binding,
        expected_preview_order_attempt_count=1,
    )
    try:
        from application.admin_api.models import (
            AdminFuturesOrderPreviewResponse,
        )

        payload = FuturesOrderPreviewArtifactStore(
            FUTURES_PREVIEW_R10_ARTIFACT_PATH
        ).read_completed()
        validated = AdminFuturesOrderPreviewResponse.model_validate(payload)
        post_preview = validated.post_preview_stage_evidence
        if (
            post_preview is None
            or post_preview.model_dump(mode="json")
            != {
                "schema_version": "1",
                "source": "backend_futures_preview_producer",
                "stages": [
                    {
                        "stage": "preview_response_validation",
                        "status": "blocked",
                        "reason_code": (
                            "futures_preview_response_economics_invalid"
                        ),
                    }
                ],
                "sanitized": True,
                "raw_response_included": False,
                "external_exception_text_included": False,
                "identifier_values_included": False,
            }
            or validated.preview_response is not None
            or validated.preview_id_sha256 is not None
            or validated.seal_ready_plan is not None
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R10 terminal diagnosis changed"
            )
        _validate_opaque_preview_artifact(
            FUTURES_PREVIEW_R10_ARTIFACT_PATH,
            expected_file_sha256=FUTURES_PREVIEW_R10_FILE_SHA256,
            expected_device=FUTURES_PREVIEW_R10_DEVICE,
            expected_inode=FUTURES_PREVIEW_R10_INODE,
            expected_size=FUTURES_PREVIEW_R10_SIZE,
            expected_mode=FUTURES_PREVIEW_R10_MODE,
            expected_mtime_ns=FUTURES_PREVIEW_R10_MTIME_NS,
        )
    except Exception:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R10 terminal model validation failed"
        ) from None
    if r10_binding != FUTURES_PREVIEW_R10_TERMINAL_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R10 terminal binding changed"
        )
    return dict(FUTURES_PREVIEW_R10_TERMINAL_BINDING)


def validate_production_futures_order_preview_predecessor() -> dict[str, Any]:
    """Validate the exact R2 -> R1 -> original Slice 2 predecessor chain."""

    original_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_ORIGINAL_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_ORIGINAL_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_ORIGINAL_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_ORIGINAL_DEVICE,
        expected_inode=FUTURES_PREVIEW_ORIGINAL_INODE,
        expected_size=FUTURES_PREVIEW_ORIGINAL_SIZE,
        expected_mode=FUTURES_PREVIEW_ORIGINAL_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_ORIGINAL_MTIME_NS,
        expected_artifact_type="futures_exact_no_live_preview_slice_2",
        expected_blocker=(
            "preflight_or_preview_blocked:ValueError:"
            "futures_preview_product_status_blocked"
        ),
        expected_predecessor_binding=None,
    )
    if original_binding != FUTURES_PREVIEW_ORIGINAL_PREDECESSOR_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview original predecessor binding changed"
        )

    r1_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_R1_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_R1_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_R1_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_R1_DEVICE,
        expected_inode=FUTURES_PREVIEW_R1_INODE,
        expected_size=FUTURES_PREVIEW_R1_SIZE,
        expected_mode=FUTURES_PREVIEW_R1_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_R1_MTIME_NS,
        expected_predecessor_binding=original_binding,
        expected_evidence_predecessor_binding=(
            _FUTURES_PREVIEW_EC2_ORIGINAL_BINDING
        ),
    )
    if r1_binding != FUTURES_PREVIEW_R1_PREDECESSOR_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R1 predecessor binding changed"
        )

    r2_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_PREDECESSOR_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_PREDECESSOR_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_PREDECESSOR_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_PREDECESSOR_DEVICE,
        expected_inode=FUTURES_PREVIEW_PREDECESSOR_INODE,
        expected_size=FUTURES_PREVIEW_PREDECESSOR_SIZE,
        expected_mode=FUTURES_PREVIEW_PREDECESSOR_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_PREDECESSOR_MTIME_NS,
        expected_artifact_type="futures_exact_no_live_preview_slice_2r2",
        expected_blocker="preflight_or_preview_blocked:ValueError",
        expected_predecessor_binding=r1_binding,
        expected_evidence_predecessor_binding=_FUTURES_PREVIEW_EC2_R1_BINDING,
    )
    if r2_binding != FUTURES_PREVIEW_PREDECESSOR_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R2 predecessor binding changed"
        )
    return r2_binding


def validate_production_futures_order_preview_r3_predecessor() -> dict[str, Any]:
    """Validate immutable R3 plus its complete R2/R1/original chain."""

    r2_binding = validate_production_futures_order_preview_predecessor()
    r3_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_R3_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_R3_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_R3_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_R3_DEVICE,
        expected_inode=FUTURES_PREVIEW_R3_INODE,
        expected_size=FUTURES_PREVIEW_R3_SIZE,
        expected_mode=FUTURES_PREVIEW_R3_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_R3_MTIME_NS,
        expected_artifact_type=_ARTIFACT_TYPE,
        expected_blocker="preflight_or_preview_stage_blocked",
        expected_predecessor_binding=r2_binding,
        expected_evidence_predecessor_binding=_FUTURES_PREVIEW_EC2_R2_BINDING,
    )
    if r3_binding != FUTURES_PREVIEW_R3_PREDECESSOR_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R3 predecessor binding changed"
        )
    return r3_binding


def validate_production_futures_order_preview_r4_predecessor() -> dict[str, Any]:
    """Validate immutable R4 plus its complete R3/R2/R1/original chain."""

    r3_binding = validate_production_futures_order_preview_r3_predecessor()
    r4_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_R4_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_R4_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_R4_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_R4_DEVICE,
        expected_inode=FUTURES_PREVIEW_R4_INODE,
        expected_size=FUTURES_PREVIEW_R4_SIZE,
        expected_mode=FUTURES_PREVIEW_R4_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_R4_MTIME_NS,
        expected_artifact_type=_R4_ARTIFACT_TYPE,
        expected_blocker="preflight_or_preview_stage_blocked",
        expected_predecessor_binding=r3_binding,
        expected_evidence_predecessor_binding=_FUTURES_PREVIEW_EC2_R3_BINDING,
    )
    if r4_binding != FUTURES_PREVIEW_R4_PREDECESSOR_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R4 predecessor binding changed"
        )
    return r4_binding


def validate_production_futures_order_preview_r5_terminal() -> dict[str, Any]:
    """Validate immutable terminal R5 plus its complete predecessor chain."""

    r4_binding = validate_production_futures_order_preview_r4_predecessor()
    r5_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_R5_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_R5_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_R5_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_R5_DEVICE,
        expected_inode=FUTURES_PREVIEW_R5_INODE,
        expected_size=FUTURES_PREVIEW_R5_SIZE,
        expected_mode=FUTURES_PREVIEW_R5_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_R5_MTIME_NS,
        expected_artifact_type=_R5_ARTIFACT_TYPE,
        expected_blocker="preflight_or_preview_stage_blocked",
        expected_predecessor_binding=r4_binding,
        expected_evidence_predecessor_binding=_FUTURES_PREVIEW_EC2_R4_BINDING,
    )
    if r5_binding != FUTURES_PREVIEW_R5_TERMINAL_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R5 terminal binding changed"
        )
    from application.admin_api.models import AdminFuturesOrderPreviewResponse

    evidence = FuturesOrderPreviewArtifactStore(
        FUTURES_PREVIEW_R5_ARTIFACT_PATH
    ).read_completed()
    AdminFuturesOrderPreviewResponse.model_validate(evidence)
    return r5_binding


def validate_production_futures_order_preview_r6_terminal() -> dict[str, Any]:
    """Validate immutable terminal R6 plus its complete restored chain."""

    r5_binding = validate_production_futures_order_preview_r5_terminal()
    r6_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_R6_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_R6_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_R6_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_R6_DEVICE,
        expected_inode=FUTURES_PREVIEW_R6_INODE,
        expected_size=FUTURES_PREVIEW_R6_SIZE,
        expected_mode=FUTURES_PREVIEW_R6_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_R6_MTIME_NS,
        expected_artifact_type=_R6_ARTIFACT_TYPE,
        expected_blocker="preflight_or_preview_blocked:ValueError",
        expected_predecessor_binding=r5_binding,
        expected_preview_order_attempt_count=1,
    )
    if r6_binding != FUTURES_PREVIEW_R6_TERMINAL_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R6 terminal binding changed"
        )
    from application.admin_api.models import AdminFuturesOrderPreviewResponse

    evidence = FuturesOrderPreviewArtifactStore(
        FUTURES_PREVIEW_R6_ARTIFACT_PATH
    ).read_completed()
    AdminFuturesOrderPreviewResponse.model_validate(evidence)
    return r6_binding


def validate_production_futures_order_preview_r7_terminal() -> dict[str, Any]:
    """Validate immutable terminal R7 plus its complete restored chain."""

    r6_binding = validate_production_futures_order_preview_r6_terminal()
    r7_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_R7_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_R7_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_R7_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_R7_DEVICE,
        expected_inode=FUTURES_PREVIEW_R7_INODE,
        expected_size=FUTURES_PREVIEW_R7_SIZE,
        expected_mode=FUTURES_PREVIEW_R7_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_R7_MTIME_NS,
        expected_artifact_type=_R7_ARTIFACT_TYPE,
        expected_blocker="preflight_or_preview_blocked:ValueError",
        expected_predecessor_binding=r6_binding,
        expected_preview_order_attempt_count=1,
    )
    if r7_binding != FUTURES_PREVIEW_R7_TERMINAL_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R7 terminal binding changed"
        )
    from application.admin_api.models import AdminFuturesOrderPreviewResponse

    evidence = FuturesOrderPreviewArtifactStore(
        FUTURES_PREVIEW_R7_ARTIFACT_PATH
    ).read_completed()
    AdminFuturesOrderPreviewResponse.model_validate(evidence)
    return r7_binding


class FuturesOrderPreviewProducer:
    """Consume one fixed authorization to produce Preview-only evidence."""

    def __init__(
        self,
        *,
        rest_client: Any,
        store: FuturesOrderPreviewArtifactStore,
        predecessor_binding: Mapping[str, Any],
        predecessor_validator: Callable[[], Mapping[str, Any]],
        artifact_type: str = _ARTIFACT_TYPE,
        now: Callable[[], datetime] | None = None,
        correlation_id_factory: Callable[[], str] | None = None,
        idempotency_key_factory: Callable[[], str] | None = None,
    ) -> None:
        if artifact_type not in {
            _ARTIFACT_TYPE,
            _R4_ARTIFACT_TYPE,
            _R5_ARTIFACT_TYPE,
            _R6_ARTIFACT_TYPE,
            _R7_ARTIFACT_TYPE,
            _R8_ARTIFACT_TYPE,
            _R9_ARTIFACT_TYPE,
            _R10_ARTIFACT_TYPE,
            _R11_ARTIFACT_TYPE,
        }:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact generation is invalid"
            )
        expected_predecessor_name = {
            _ARTIFACT_TYPE: "futures_exact_no_live_preview_slice_2r2.jsonl",
            _R4_ARTIFACT_TYPE: "futures_exact_no_live_preview_slice_2r3.jsonl",
            _R5_ARTIFACT_TYPE: "futures_exact_no_live_preview_slice_2r4.jsonl",
            _R6_ARTIFACT_TYPE: "futures_exact_no_live_preview_slice_2r5.jsonl",
            _R7_ARTIFACT_TYPE: "futures_exact_no_live_preview_slice_2r6.jsonl",
            _R8_ARTIFACT_TYPE: "futures_exact_no_live_preview_slice_2r7.jsonl",
            _R9_ARTIFACT_TYPE: "futures_exact_no_live_preview_slice_2r8.jsonl",
            _R10_ARTIFACT_TYPE: "futures_exact_no_live_preview_slice_2r9.jsonl",
            _R11_ARTIFACT_TYPE: "futures_exact_no_live_preview_slice_2r10.jsonl",
        }[artifact_type]
        if predecessor_binding.get("artifact_name") != expected_predecessor_name:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview predecessor generation is invalid"
            )
        self.rest_client = rest_client
        self.store = store
        self.artifact_type = artifact_type
        self.predecessor_binding = dict(predecessor_binding)
        self.predecessor_validator = predecessor_validator
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.correlation_id_factory = correlation_id_factory or (lambda: str(uuid4()))
        self.idempotency_key_factory = idempotency_key_factory or (lambda: str(uuid4()))

    def build_claim(self) -> dict[str, Any]:
        """Build the fixed claim without calling Coinbase."""

        correlation_id = self.correlation_id_factory()
        idempotency_key = self.idempotency_key_factory()
        try:
            parsed_correlation_id = UUID(correlation_id)
            parsed_idempotency_key = UUID(idempotency_key)
        except (AttributeError, TypeError, ValueError) as exc:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview identifiers are not canonical UUIDv4"
            ) from exc
        if (
            parsed_correlation_id.version != 4
            or parsed_idempotency_key.version != 4
            or str(parsed_correlation_id) != correlation_id
            or str(parsed_idempotency_key) != idempotency_key
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview identifiers are not canonical UUIDv4"
            )
        if (
            _preview_identifier_was_consumed(
                correlation_id,
                artifact_type=self.artifact_type,
            )
            or _preview_identifier_was_consumed(
                idempotency_key,
                artifact_type=self.artifact_type,
            )
            or correlation_id == idempotency_key
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview identifiers are not fresh"
            )
        claim = {
            "artifact_type": self.artifact_type,
            "claim_status": "reserved",
            "predecessor_binding": dict(self.predecessor_binding),
            "reserved_at": _timestamp(self.now()),
            "actor_id": FUTURES_PREVIEW_ACTOR_ID,
            "roles": [FUTURES_PREVIEW_ROLE],
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "profile_label": "Default",
            "portfolio_type": "DEFAULT",
            "product_id": FUTURES_PREVIEW_PRODUCT_ID,
            "contract_count": "1",
            "caps": {
                "opening_reference_notional_usdc": "100",
                "concurrent_exposure_usdc": "150",
                "buffered_close_reference_notional_usdc": "150",
                "branch_turnover_reference_notional_usdc": "300",
                "close_buffer_multiplier": "1.20",
                "comparison": "strictly_less_than",
            },
            "allowed_coinbase_methods": [
                "get_api_key_permissions",
                "list_portfolios",
                "get_product_dict",
                "get_best_bid_ask",
                "get_futures_positions",
                "get_futures_margin_collateral_snapshot",
                "preview_order",
            ],
            "preview_order_attempt_max": 1,
            "retry_attempt_max": 0,
            "fallback_attempt_max": 0,
            "create_order_attempt_max": 0,
            "cancel_order_attempt_max": 0,
            "close_position_attempt_max": 0,
            "reduce_position_attempt_max": 0,
            "marker_created": False,
            "ledger_created": False,
            "runtime_created": False,
        }
        if self.artifact_type in _V3_MARGIN_WINDOW_ARTIFACT_TYPES:
            claim["margin_window_policy_binding"] = deepcopy(
                FUTURES_PREVIEW_R6_MARGIN_WINDOW_POLICY_BINDING
            )
        if self.artifact_type in _CORRECTED_RESPONSE_SCHEMA_ARTIFACT_TYPES:
            claim["preview_response_schema_binding"] = deepcopy(
                FUTURES_PREVIEW_R11_RESPONSE_SCHEMA_BINDING
                if self.artifact_type == _R11_ARTIFACT_TYPE
                else (
                    FUTURES_PREVIEW_R10_RESPONSE_SCHEMA_BINDING
                    if self.artifact_type == _R10_ARTIFACT_TYPE
                    else FUTURES_PREVIEW_R7_RESPONSE_SCHEMA_BINDING
                )
            )
        if self.artifact_type in _POST_PREVIEW_DIAGNOSTIC_ARTIFACT_TYPES:
            claim["post_preview_diagnostic_binding"] = deepcopy(
                FUTURES_PREVIEW_R11_POST_PREVIEW_DIAGNOSTIC_BINDING
                if self.artifact_type == _R11_ARTIFACT_TYPE
                else (
                    FUTURES_PREVIEW_R10_POST_PREVIEW_DIAGNOSTIC_BINDING
                    if self.artifact_type == _R10_ARTIFACT_TYPE
                    else FUTURES_PREVIEW_R8_POST_PREVIEW_DIAGNOSTIC_BINDING
                )
            )
        return claim

    def run(
        self,
        *,
        accepted_callback: Callable[
            [dict[str, Any], dict[str, Any]],
            None,
        ]
        | None = None,
    ) -> dict[str, Any]:
        """Reserve once, preflight, and make at most one Preview call."""

        if (
            accepted_callback is not None
            and self.artifact_type not in _ACCEPTED_HANDOFF_ARTIFACT_TYPES
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview accepted handoff is not enabled"
            )

        if self.artifact_type in _SANITIZED_PREVIEW_ARTIFACT_TYPES:
            claim = self.build_claim()
            reservation_claim = (
                _withhold_r8_private_claim(claim)
                if self.artifact_type
                in {
                    _R8_ARTIFACT_TYPE,
                    _R9_ARTIFACT_TYPE,
                    _R10_ARTIFACT_TYPE,
                    _R11_ARTIFACT_TYPE,
                }
                else claim
            )
            claim_sha256 = self._reserve_claim(reservation_claim)
        else:
            observed_predecessor = dict(self.predecessor_validator())
            if observed_predecessor != self.predecessor_binding:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview predecessor binding changed"
                )
            claim = self.build_claim()
            claim_sha256 = self._reserve_claim(claim)
        counters = _zero_attempt_counters()
        read_counters = _zero_read_counters()
        terminal_context: dict[str, Any] = {}
        passed_pre_preview_stages: list[str] = []
        passed_post_preview_stages: list[str] = []
        try:
            if self.artifact_type in _SANITIZED_PREVIEW_ARTIFACT_TYPES:
                try:
                    observed_predecessor = dict(self.predecessor_validator())
                except FuturesOrderPreviewArtifactError as exc:
                    raise ValueError(
                        "futures_preview_predecessor_validation_blocked"
                    ) from exc
                if observed_predecessor != self.predecessor_binding:
                    raise ValueError(
                        "futures_preview_predecessor_binding_changed_after_claim"
                    )
            try:
                revalidated_predecessor = dict(self.predecessor_validator())
            except FuturesOrderPreviewArtifactError as exc:
                raise ValueError(
                    f"futures_preview_predecessor_validation_blocked:{exc}"
                ) from exc
            if revalidated_predecessor != self.predecessor_binding:
                raise ValueError(
                    "futures_preview_predecessor_binding_changed_after_claim"
                )
            read_counters["api_key_permissions"] = 1
            permissions = _plain(self.rest_client.get_api_key_permissions())
            read_counters["portfolio_catalog"] = 1
            portfolios = _plain(self.rest_client.list_portfolios())
            binding = evaluate_futures_default_portfolio_binding(
                permissions=permissions,
                portfolios=portfolios,
                observed_at=_timestamp(self.now()),
                permissions_read=True,
                portfolio_catalog_read=True,
            )
            if (
                not binding.read_ready
                or binding.can_view is not True
                or binding.can_trade is not True
            ):
                raise ValueError(
                    binding.blocker
                    or "futures_default_portfolio_trade_permission_missing"
                )
            read_counters["product"] = 1
            product = _plain(
                self.rest_client.get_product_dict(FUTURES_PREVIEW_PRODUCT_ID)
            )
            read_counters["best_bid_ask"] = 1
            book = _plain(
                self.rest_client.get_best_bid_ask(
                    product_ids=[FUTURES_PREVIEW_PRODUCT_ID]
                )
            )
            read_counters["futures_positions"] = 1
            positions = _plain(self.rest_client.get_futures_positions())
            read_counters["futures_margin_collateral"] = 1
            margin_collateral_observed = False
            margin_collateral: Any = {}
            try:
                raw_margin_collateral = (
                    self.rest_client.get_futures_margin_collateral_snapshot()
                )
                margin_collateral_observed = True
                margin_collateral = _plain(raw_margin_collateral)
                if self.artifact_type == _R5_ARTIFACT_TYPE:
                    terminal_context.update(
                        slice2_preview_margin_windows_policy_context(
                            margin_collateral
                        )
                    )
                elif self.artifact_type in _V3_MARGIN_WINDOW_ARTIFACT_TYPES:
                    terminal_context.update(
                        slice2_preview_margin_windows_pair_policy_context(
                            margin_collateral
                        )
                    )
                terminal_context.update(
                    _margin_setting_terminal_context(margin_collateral)
                )
                if self.artifact_type == _R5_ARTIFACT_TYPE:
                    available_margin = (
                        validate_slice2_preview_margin_collateral_evidence(
                            margin_collateral
                        )
                    )
                elif self.artifact_type in _V3_MARGIN_WINDOW_ARTIFACT_TYPES:
                    available_margin = (
                        validate_slice2_preview_r6_margin_collateral_evidence(
                            margin_collateral
                        )
                    )
                else:
                    available_margin = validate_margin_collateral_evidence(
                        margin_collateral
                    )
            except Exception as exc:
                if (
                    self.artifact_type == _R4_ARTIFACT_TYPE
                    and margin_collateral_observed
                    and type(exc) is ValueError
                    and exc.args
                    == ("futures_preview_margin_windows_ambiguous",)
                ):
                    terminal_context.update(
                        _margin_windows_terminal_context(margin_collateral)
                    )
                elif (
                    self.artifact_type in _SANITIZED_PREVIEW_ARTIFACT_TYPES
                    and "margin_windows_policy_evidence"
                    not in terminal_context
                ):
                    policy_context = (
                        slice2_preview_margin_windows_pair_policy_context
                        if self.artifact_type in _V3_MARGIN_WINDOW_ARTIFACT_TYPES
                        else slice2_preview_margin_windows_policy_context
                    )
                    terminal_context.update(policy_context(margin_collateral))
                terminal_context.update(
                    _pre_preview_stage_failure_context(
                        passed_stages=passed_pre_preview_stages,
                        blocked_stage="remaining_margin_validation",
                        exc=exc,
                    )
                )
                raise
            passed_pre_preview_stages.append("remaining_margin_validation")
            try:
                observed_at = self.now()
                candidate = build_futures_order_preview_candidate(
                    product=product,
                    book=book,
                    positions=positions,
                    observed_at=observed_at,
                )
            except Exception as exc:
                terminal_context.update(
                    _pre_preview_stage_failure_context(
                        passed_stages=passed_pre_preview_stages,
                        blocked_stage="candidate_construction",
                        exc=exc,
                    )
                )
                raise
            passed_pre_preview_stages.append("candidate_construction")
            try:
                preview_request = _preview_request(candidate)
            except Exception as exc:
                terminal_context.update(
                    _pre_preview_stage_failure_context(
                        passed_stages=passed_pre_preview_stages,
                        blocked_stage="preview_request_construction",
                        exc=exc,
                    )
                )
                raise
            passed_pre_preview_stages.append("preview_request_construction")
            try:
                attempt_context = _terminal_attempt_context(
                    artifact_type=self.artifact_type,
                    binding=binding.to_dict(),
                    permissions=permissions,
                    portfolios=portfolios,
                    product=product,
                    book=book,
                    positions=positions,
                    margin_collateral=margin_collateral,
                    candidate=candidate,
                    preview_request=preview_request,
                )
                try:
                    pre_preview_predecessor = dict(
                        self.predecessor_validator()
                    )
                except FuturesOrderPreviewArtifactError as exc:
                    raise ValueError(
                        "futures_preview_predecessor_pre_preview_blocked"
                    ) from exc
                if pre_preview_predecessor != self.predecessor_binding:
                    raise ValueError(
                        "futures_preview_predecessor_binding_changed_pre_preview"
                    )
            except Exception as exc:
                terminal_context.update(
                    _pre_preview_stage_failure_context(
                        passed_stages=passed_pre_preview_stages,
                        blocked_stage="terminal_context_sanitization",
                        exc=exc,
                    )
                )
                raise
            terminal_context = attempt_context
            passed_pre_preview_stages.append("terminal_context_sanitization")
            counters["preview_order"] = 1
            try:
                raw_preview_response = self.rest_client.preview_order(
                    **preview_request
                )
            except Exception as exc:
                transition_blocker = self._terminal_predecessor_blocker()
                blocker = (
                    "preview_order_unknown_consumed"
                    if self.artifact_type == _R11_ARTIFACT_TYPE
                    else f"preview_order_unknown:{type(exc).__name__}"
                )
                if transition_blocker is not None:
                    blocker = f"{blocker};{transition_blocker}"
                result = _terminal_failure_record(
                    claim=claim,
                    claim_sha256=claim_sha256,
                    counters=counters,
                    read_counters=read_counters,
                    outcome="unknown",
                    blocker=blocker,
                    context=terminal_context,
                )
                result = _withhold_r8_private_accepted_evidence(result)
                self._append_terminal_result(result)
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview outcome is unknown; attempt consumed"
                ) from exc
            try:
                if self.artifact_type == _R11_ARTIFACT_TYPE:
                    normalized_preview = (
                        validate_post_r10_preview_response_acceptance(
                            raw_preview_response
                        )
                    )
                else:
                    preview_response = _plain(raw_preview_response)
                    if self.artifact_type == _R10_ARTIFACT_TYPE:
                        normalized_preview = (
                            validate_r10_preview_response_schema(
                                preview_response
                            )
                        )
                    elif (
                        self.artifact_type
                        in _CORRECTED_RESPONSE_SCHEMA_ARTIFACT_TYPES
                    ):
                        normalized_preview = (
                            validate_r7_preview_response_schema(
                                preview_response
                            )
                        )
                    else:
                        normalized_preview = validate_preview_response(
                            preview_response
                        )
            except Exception as exc:
                if (
                    self.artifact_type
                    in _POST_PREVIEW_DIAGNOSTIC_ARTIFACT_TYPES
                ):
                    terminal_context.update(
                        _post_preview_stage_failure_context(
                            passed_stages=passed_post_preview_stages,
                            blocked_stage="preview_response_validation",
                            exc=exc,
                            artifact_type=self.artifact_type,
                        )
                    )
                raise
            passed_post_preview_stages.append("preview_response_validation")
            terminal_context["preview_response"] = normalized_preview
            terminal_context["preview_response_sha256"] = canonical_sha256(
                normalized_preview
            )
            try:
                normalized_preview = validate_preview_against_candidate(
                    normalized_preview,
                    candidate,
                )
            except Exception as exc:
                if (
                    self.artifact_type
                    in _POST_PREVIEW_DIAGNOSTIC_ARTIFACT_TYPES
                ):
                    terminal_context.update(
                        _post_preview_stage_failure_context(
                            passed_stages=passed_post_preview_stages,
                            blocked_stage="candidate_cap_binding",
                            exc=exc,
                            artifact_type=self.artifact_type,
                        )
                    )
                raise
            passed_post_preview_stages.append("candidate_cap_binding")
            terminal_context["preview_response"] = normalized_preview
            terminal_context["preview_response_sha256"] = canonical_sha256(
                normalized_preview
            )
            try:
                preview_margin = _decimal(
                    normalized_preview["order_margin_total"],
                    "order_margin_total",
                )
                if preview_margin > available_margin:
                    raise ValueError(
                        "futures_preview_available_margin_insufficient"
                    )
            except Exception as exc:
                if (
                    self.artifact_type
                    in _POST_PREVIEW_DIAGNOSTIC_ARTIFACT_TYPES
                ):
                    terminal_context.update(
                        _post_preview_stage_failure_context(
                            passed_stages=passed_post_preview_stages,
                            blocked_stage="available_margin_validation",
                            exc=exc,
                            artifact_type=self.artifact_type,
                        )
                    )
                raise
            passed_post_preview_stages.append("available_margin_validation")
            try:
                seal_ready_plan = _seal_ready_plan(
                    claim=claim,
                    binding=binding.to_dict(),
                    candidate=candidate,
                    preview_request=preview_request,
                    preview_response=normalized_preview,
                    permissions=permissions,
                    portfolios=portfolios,
                    product=product,
                    book=book,
                    positions=positions,
                    margin_collateral=margin_collateral,
                )
            except Exception as exc:
                if (
                    self.artifact_type
                    in _POST_PREVIEW_DIAGNOSTIC_ARTIFACT_TYPES
                ):
                    terminal_context.update(
                        _post_preview_stage_failure_context(
                            passed_stages=passed_post_preview_stages,
                            blocked_stage="seal_ready_plan_construction",
                            exc=exc,
                            artifact_type=self.artifact_type,
                        )
                    )
                raise
            passed_post_preview_stages.append("seal_ready_plan_construction")
            try:
                evidence = _accepted_evidence(
                    claim=claim,
                    claim_sha256=claim_sha256,
                    counters=counters,
                    read_counters=read_counters,
                    binding=binding.to_dict(),
                    permissions=permissions,
                    portfolios=portfolios,
                    product=product,
                    book=book,
                    positions=positions,
                    margin_collateral=margin_collateral,
                    candidate=candidate,
                    preview_request=preview_request,
                    preview_response=normalized_preview,
                    seal_ready_plan=seal_ready_plan,
                    completed_at=self.now(),
                )
            except Exception as exc:
                if (
                    self.artifact_type
                    in _POST_PREVIEW_DIAGNOSTIC_ARTIFACT_TYPES
                ):
                    terminal_context.update(
                        _post_preview_stage_failure_context(
                            passed_stages=passed_post_preview_stages,
                            blocked_stage="accepted_evidence_construction",
                            exc=exc,
                            artifact_type=self.artifact_type,
                        )
                    )
                raise
            passed_post_preview_stages.append("accepted_evidence_construction")
            try:
                transition_blocker = self._terminal_predecessor_blocker()
                if transition_blocker is not None:
                    raise ValueError(transition_blocker)
            except Exception as exc:
                if (
                    self.artifact_type
                    in _POST_PREVIEW_DIAGNOSTIC_ARTIFACT_TYPES
                ):
                    terminal_context.update(
                        _post_preview_stage_failure_context(
                            passed_stages=passed_post_preview_stages,
                            blocked_stage="terminal_predecessor_validation",
                            exc=exc,
                            artifact_type=self.artifact_type,
                        )
                    )
                raise
            passed_post_preview_stages.append(
                "terminal_predecessor_validation"
            )
            persisted_evidence = _withhold_r8_private_accepted_evidence(
                evidence
            )
            self._append_terminal_result(persisted_evidence)
            terminal = self.store.read_completed()
            if accepted_callback is not None:
                handoff_failed = False
                try:
                    accepted_callback(
                        deepcopy(evidence),
                        deepcopy(terminal),
                    )
                except Exception:
                    handoff_failed = True
                if handoff_failed:
                    raise FuturesOrderPreviewAcceptedHandoffError(
                        "futures Preview accepted handoff did not complete"
                    ) from None
            return terminal
        except Exception as exc:
            if isinstance(
                exc,
                _FuturesOrderPreviewTerminalPersistenceError,
            ):
                raise
            if isinstance(exc, FuturesOrderPreviewAcceptedHandoffError):
                raise
            if isinstance(exc, FuturesOrderPreviewArtifactError):
                if self.artifact_type not in _SANITIZED_PREVIEW_ARTIFACT_TYPES:
                    raise
                try:
                    self.store.read_completed()
                except FuturesOrderPreviewArtifactError:
                    pass
                else:
                    raise
            transition_blocker = self._terminal_predecessor_blocker()
            pre_stage_failure = (
                "pre_preview_stage_evidence" in terminal_context
            )
            post_stage_failure = (
                "post_preview_stage_evidence" in terminal_context
            )
            blocker = (
                "preflight_or_preview_stage_blocked"
                if pre_stage_failure
                else (
                    "post_preview_stage_blocked"
                    if post_stage_failure
                    else (
                        "preflight_or_preview_blocked"
                        if self.artifact_type == _R11_ARTIFACT_TYPE
                        else _redacted_preflight_blocker(exc)
                    )
                )
            )
            if (
                transition_blocker is not None
                and not pre_stage_failure
                and not post_stage_failure
                and transition_blocker not in blocker
            ):
                blocker = f"{blocker};{transition_blocker}"
            if self.artifact_type in _SANITIZED_PREVIEW_ARTIFACT_TYPES:
                terminal_context.pop("preview_response", None)
                terminal_context.pop("preview_response_sha256", None)
            result = _terminal_failure_record(
                claim=claim,
                claim_sha256=claim_sha256,
                counters=counters,
                read_counters=read_counters,
                outcome="blocked",
                blocker=blocker,
                context=terminal_context,
            )
            result = _withhold_r8_private_accepted_evidence(result)
            self._append_terminal_result(result)
            raise FuturesOrderPreviewArtifactError(
                "futures Preview preflight blocked; attempt consumed"
            ) from exc

    def _reserve_claim(self, claim: Mapping[str, Any]) -> str:
        """Reserve R11 value-blindly; persistence ambiguity consumes it."""

        if self.artifact_type != _R11_ARTIFACT_TYPE:
            return self.store.reserve(claim)
        try:
            return self.store.reserve(claim)
        except FuturesOrderPreviewArtifactError:
            raise
        except Exception:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview claim persistence unavailable; "
                "attempt consumed"
            ) from None

    def _append_terminal_result(self, result: Mapping[str, Any]) -> None:
        """Append once; R11 persistence ambiguity consumes without retry."""

        if self.artifact_type != _R11_ARTIFACT_TYPE:
            self.store.append_result(result)
            return
        try:
            self.store.append_result(result)
        except Exception:
            raise _FuturesOrderPreviewTerminalPersistenceError(
                "futures Preview terminal persistence unavailable; "
                "attempt consumed"
            ) from None

    def _terminal_predecessor_blocker(self) -> str | None:
        """Return a redacted transition blocker immediately before append."""

        try:
            observed = dict(self.predecessor_validator())
        except Exception as exc:
            if self.artifact_type == _R11_ARTIFACT_TYPE:
                return (
                    "futures_preview_predecessor_terminal_validation_blocked"
                )
            return (
                "futures_preview_predecessor_terminal_validation_blocked:"
                f"{type(exc).__name__}"
            )
        if observed != self.predecessor_binding:
            return "futures_preview_predecessor_terminal_binding_changed"
        return None


def build_futures_order_preview_candidate(
    *,
    product: Mapping[str, Any],
    book: Mapping[str, Any],
    positions: Any,
    observed_at: datetime,
) -> dict[str, str]:
    """Build the fixed one-contract resting AVAX candidate or fail closed."""

    if str(product.get("product_id") or "") != FUTURES_PREVIEW_PRODUCT_ID:
        raise ValueError("futures_preview_product_identity_blocked")
    if str(product.get("display_name") or "").strip() != "AVAX PERP":
        raise ValueError("futures_preview_avp_display_name_blocked")
    if str(product.get("product_type") or "").upper() != "FUTURE":
        raise ValueError("futures_preview_product_type_blocked")
    if "status" not in product or product.get("status") != "":
        raise ValueError("futures_preview_product_status_blocked")
    if any(
        product.get(field) is not False
        for field in ("trading_disabled", "view_only", "cancel_only")
    ):
        raise ValueError("futures_preview_product_trading_blocked")

    details = _mapping(product.get("future_product_details"))
    exact_perp_style_identity = {
        "contract_code": "AVP",
        "group_description": "Avalanche Perp Futures",
        "group_short_description": "Avalanche Perp",
        "venue": "cde",
        "risk_managed_by": "MANAGED_BY_FCM",
        "contract_expiry": "2030-12-20T16:00:00Z",
        "contract_expiry_type": "EXPIRING",
    }
    if any(
        details.get(field) != expected
        for field, expected in exact_perp_style_identity.items()
    ):
        raise ValueError("futures_preview_avp_perp_style_identity_blocked")
    contract_expiry_type = str(
        details.get("contract_expiry_type") or ""
    ).strip().upper()
    contract_size = _positive_decimal(details.get("contract_size"), "contract_size")
    if contract_size != Decimal("10"):
        raise ValueError("futures_preview_avp_contract_size_blocked")
    product_price = _positive_decimal(product.get("price"), "product_price")
    price_increment = _positive_decimal(product.get("price_increment"), "price_increment")
    base_increment = _positive_decimal(product.get("base_increment"), "base_increment")
    base_min_size = _positive_decimal(product.get("base_min_size"), "base_min_size")
    if (
        FUTURES_PREVIEW_CONTRACT_COUNT < base_min_size
        or FUTURES_PREVIEW_CONTRACT_COUNT % base_increment != 0
    ):
        raise ValueError("futures_preview_one_contract_rule_blocked")

    pricebook = _exact_pricebook(book)
    _validate_market_freshness(pricebook, observed_at)
    best_bid = _top_price(pricebook, "bids")
    best_ask = _top_price(pricebook, "asks")
    if best_bid >= best_ask:
        raise ValueError("futures_preview_crossed_or_ambiguous_book")
    if best_bid % price_increment != 0:
        raise ValueError("futures_preview_best_bid_tick_misaligned")
    limit_price = best_bid - price_increment
    if limit_price <= 0 or limit_price % price_increment != 0:
        raise ValueError("futures_preview_limit_tick_blocked")
    if _position_contracts(positions, FUTURES_PREVIEW_PRODUCT_ID) != 0:
        raise ValueError("futures_preview_existing_product_exposure_blocked")

    reference_price = max(product_price, best_ask)
    opening = reference_price * contract_size * FUTURES_PREVIEW_CONTRACT_COUNT
    exposure = opening
    buffered_close = exposure * FUTURES_PREVIEW_CLOSE_BUFFER
    turnover = opening + buffered_close
    if opening >= FUTURES_PREVIEW_OPENING_CAP_USDC:
        raise ValueError("futures_preview_opening_cap_blocked")
    if exposure >= FUTURES_PREVIEW_EXPOSURE_CAP_USDC:
        raise ValueError("futures_preview_exposure_cap_blocked")
    if buffered_close >= FUTURES_PREVIEW_EXPOSURE_CAP_USDC:
        raise ValueError("futures_preview_buffered_close_cap_blocked")
    if turnover >= FUTURES_PREVIEW_TURNOVER_CAP_USDC:
        raise ValueError("futures_preview_turnover_cap_blocked")

    return {
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "side": "BUY",
        "order_type": "LIMIT_GTC",
        "post_only": "true",
        "contract_count": "1",
        "product_classification": "PERP_STYLE_FUTURE",
        "contract_code": "AVP",
        "contract_expiry": "2030-12-20T16:00:00Z",
        "contract_expiry_type": contract_expiry_type,
        "venue": "cde",
        "risk_managed_by": "MANAGED_BY_FCM",
        "contract_size": _decimal_text(contract_size),
        "product_price": _decimal_text(product_price),
        "reference_price": _decimal_text(reference_price),
        "reference_price_source": "max_product_price_and_fresh_best_ask",
        "price_increment": _decimal_text(price_increment),
        "best_bid": _decimal_text(best_bid),
        "best_ask": _decimal_text(best_ask),
        "limit_price": _decimal_text(limit_price),
        "opening_reference_notional_usdc": _notional_text(opening),
        "maximum_exposure_reference_notional_usdc": _notional_text(exposure),
        "observed_concurrent_exposure_usdc": _notional_text(exposure),
        "buffered_close_reference_notional_usdc": _notional_text(buffered_close),
        "branch_turnover_reference_notional_usdc": _notional_text(turnover),
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "close_buffer_multiplier": "1.20",
        "observed_at": _timestamp(observed_at),
    }


def validate_preview_response(value: Any) -> dict[str, Any]:
    """Return exact allowlisted fee, margin, and liquidation evidence."""

    response = _mapping(value)
    if not response:
        raise ValueError("futures_preview_response_missing")
    if not isinstance(response.get("errs"), list):
        raise ValueError("futures_preview_response_errors_ambiguous")
    if response["errs"]:
        raise ValueError("futures_preview_response_errors_present")
    if not isinstance(response.get("warning"), list):
        raise ValueError("futures_preview_response_warning_ambiguous")
    if response["warning"]:
        raise ValueError("futures_preview_response_warning_present")
    for field in (
        "preview_id",
        "order_total",
        "commission_total",
        "quote_size",
        "base_size",
        "best_bid",
        "best_ask",
        "order_margin_total",
    ):
        if not _nonempty(response.get(field)):
            raise ValueError(f"futures_preview_response_{field}_missing")
    preview_id = response["preview_id"]
    if (
        not isinstance(preview_id, str)
        or preview_id != preview_id.strip()
        or not preview_id.isprintable()
        or len(preview_id) > 256
    ):
        raise ValueError("futures_preview_response_preview_id_invalid")
    decimals: dict[str, Decimal] = {}
    for field in (
        "order_total",
        "commission_total",
        "quote_size",
        "base_size",
        "best_bid",
        "best_ask",
        "order_margin_total",
    ):
        decimal = _decimal(response[field], field)
        decimals[field] = decimal
        if not decimal.is_finite():
            raise ValueError(f"futures_preview_response_{field}_not_finite")
        if field == "commission_total":
            if decimal < 0:
                raise ValueError(f"futures_preview_response_{field}_negative")
        elif decimal <= 0:
            raise ValueError(f"futures_preview_response_{field}_not_positive")
    legacy_liquidation_ready = all(
        _nonempty(response.get(field))
        for field in (
            "current_liquidation_buffer",
            "projected_liquidation_buffer",
        )
    )
    replacement_liquidation_ready = bool(
        _mapping(response.get("margin_ratio_data"))
    )
    sanitized: dict[str, Any] = {
        "preview_id": preview_id,
        "errs": [],
        "warning": [],
        **{
            field: _decimal_text(decimals[field])
            for field in (
                "order_total",
                "commission_total",
                "quote_size",
                "base_size",
                "best_bid",
                "best_ask",
                "order_margin_total",
            )
        },
    }
    if legacy_liquidation_ready:
        for field in (
            "current_liquidation_buffer",
            "projected_liquidation_buffer",
        ):
            decimal = _decimal(response[field], field)
            if not decimal.is_finite() or decimal < 0:
                raise ValueError(
                    f"futures_preview_liquidation_{field}_not_finite_or_negative"
                )
            sanitized[field] = _decimal_text(decimal)
        sanitized["liquidation_evidence_source"] = (
            "current_and_projected_liquidation_buffer"
        )
    elif replacement_liquidation_ready:
        margin_ratio_data = _mapping(response["margin_ratio_data"])
        sanitized_margin_ratio: dict[str, str] = {}
        for field in ("current_margin_ratio", "projected_margin_ratio"):
            decimal = _decimal(margin_ratio_data.get(field), field)
            if not decimal.is_finite() or decimal < 0:
                raise ValueError(
                    f"futures_preview_margin_ratio_{field}_not_finite_or_negative"
                )
            sanitized_margin_ratio[field] = _decimal_text(decimal)
        sanitized["margin_ratio_data"] = sanitized_margin_ratio
        if "predicted_liquidation_price" in response:
            predicted_liquidation_price = _decimal(
                response["predicted_liquidation_price"],
                "predicted_liquidation_price",
            )
            if (
                not predicted_liquidation_price.is_finite()
                or predicted_liquidation_price <= 0
            ):
                raise ValueError(
                    "futures_preview_predicted_liquidation_price_not_finite_or_positive"
                )
            sanitized["predicted_liquidation_price"] = _decimal_text(
                predicted_liquidation_price
            )
            sanitized["liquidation_evidence_source"] = (
                "margin_ratio_data_and_predicted_liquidation_price"
            )
        else:
            sanitized["liquidation_evidence_source"] = "margin_ratio_data"
    else:
        raise ValueError("futures_preview_response_liquidation_evidence_incomplete")
    return sanitized


def validate_r7_preview_response_schema(
    value: Any,
) -> dict[str, Any]:
    """Validate raw R7 evidence before shared normalization can drop fields."""

    response = _mapping(value)
    if any(
        field in response
        for field in (
            "current_liquidation_buffer",
            "projected_liquidation_buffer",
        )
    ):
        raise ValueError(
            "futures_preview_r7_response_schema_liquidation_evidence_invalid"
        )
    normalized = validate_preview_response(response)
    liquidation_source = normalized.get("liquidation_evidence_source")
    if liquidation_source not in {
        "margin_ratio_data",
        "margin_ratio_data_and_predicted_liquidation_price",
    }:
        raise ValueError(
            "futures_preview_r7_response_schema_liquidation_evidence_invalid"
        )
    margin_ratio_data = normalized.get("margin_ratio_data")
    if not isinstance(margin_ratio_data, Mapping) or set(margin_ratio_data) != {
        "current_margin_ratio",
        "projected_margin_ratio",
    }:
        raise ValueError(
            "futures_preview_r7_response_schema_liquidation_evidence_invalid"
        )
    if (
        liquidation_source == "margin_ratio_data"
        and "predicted_liquidation_price" in normalized
    ) or (
        liquidation_source == "margin_ratio_data_and_predicted_liquidation_price"
        and "predicted_liquidation_price" not in normalized
    ):
        raise ValueError(
            "futures_preview_r7_response_schema_liquidation_evidence_invalid"
        )
    return normalized


def validate_r10_preview_response_schema(
    value: Any,
) -> dict[str, Any]:
    """Use documented margin ratios even when legacy response keys coexist.

    Coinbase's current Preview schema lists both legacy liquidation-buffer
    keys and ``margin_ratio_data`` in the same response object while describing
    the ratio object as their replacement.  R10 therefore requires the ratio
    object, treats it as authoritative, and removes legacy keys before shared
    normalization.  Legacy values are neither parsed nor persisted and can
    never serve as fallback liquidation evidence.
    """

    response = _mapping(value)
    if not _mapping(response.get("margin_ratio_data")):
        raise ValueError(
            "futures_preview_r10_response_schema_liquidation_replacement_missing"
        )
    authoritative_response = {
        field: field_value
        for field, field_value in response.items()
        if field
        not in {
            "current_liquidation_buffer",
            "projected_liquidation_buffer",
        }
    }
    normalized = validate_preview_response(authoritative_response)
    liquidation_source = normalized.get("liquidation_evidence_source")
    if liquidation_source not in {
        "margin_ratio_data",
        "margin_ratio_data_and_predicted_liquidation_price",
    }:
        raise ValueError(
            "futures_preview_r10_response_schema_liquidation_evidence_invalid"
        )
    margin_ratio_data = normalized.get("margin_ratio_data")
    if not isinstance(margin_ratio_data, Mapping) or set(margin_ratio_data) != {
        "current_margin_ratio",
        "projected_margin_ratio",
    }:
        raise ValueError(
            "futures_preview_r10_response_schema_liquidation_evidence_invalid"
        )
    if (
        liquidation_source == "margin_ratio_data"
        and "predicted_liquidation_price" in normalized
    ) or (
        liquidation_source == "margin_ratio_data_and_predicted_liquidation_price"
        and "predicted_liquidation_price" not in normalized
    ):
        raise ValueError(
            "futures_preview_r10_response_schema_liquidation_evidence_invalid"
        )
    return normalized


def _post_r10_shallow_mapping(value: Any) -> dict[Any, Any] | None:
    """Copy one response object without traversing unknown field values."""

    try:
        if isinstance(value, Mapping):
            return dict(value)
        attributes = getattr(value, "__dict__", None)
        if isinstance(attributes, Mapping):
            return dict(attributes)
    except Exception:
        return None
    return None


def validate_post_r10_official_preview_response_schema(
    value: Any,
) -> dict[str, Any]:
    """Validate only Coinbase's documented Preview response wire shape.

    This prospective compatibility boundary intentionally does not apply the
    project's stricter one-contract acceptance rules.  It returns shape-only,
    value-blind evidence and never includes response values.
    """

    response = _post_r10_shallow_mapping(value)
    if not response:
        raise ValueError("futures_preview_response_official_response_missing")
    for field in _POST_R10_OFFICIAL_REQUIRED_STRING_FIELDS:
        if field not in response:
            raise ValueError(
                f"futures_preview_response_official_{field}_missing"
            )
        if type(response[field]) is not str:
            raise ValueError(
                f"futures_preview_response_official_{field}_type_invalid"
            )
    for field in _POST_R10_OFFICIAL_REQUIRED_LIST_FIELDS:
        if field not in response:
            raise ValueError(
                f"futures_preview_response_official_{field}_missing"
            )
        if type(response[field]) is not list:
            raise ValueError(
                f"futures_preview_response_official_{field}_type_invalid"
            )
        if any(type(item) is not str for item in response[field]):
            raise ValueError(
                f"futures_preview_response_official_{field}_item_type_invalid"
            )
    if "is_max" not in response:
        raise ValueError("futures_preview_response_official_is_max_missing")
    if type(response["is_max"]) is not bool:
        raise ValueError(
            "futures_preview_response_official_is_max_type_invalid"
        )
    for field in (
        "preview_id",
        "order_margin_total",
        "predicted_liquidation_price",
    ):
        if field in response and type(response[field]) is not str:
            raise ValueError(
                f"futures_preview_response_official_{field}_type_invalid"
            )
    if "margin_ratio_data" in response:
        margin_ratio_data = _post_r10_shallow_mapping(
            response["margin_ratio_data"]
        )
        if margin_ratio_data is None:
            raise ValueError(
                "futures_preview_response_official_margin_ratio_data_"
                "type_invalid"
            )
        for field in ("current_margin_ratio", "projected_margin_ratio"):
            if field in margin_ratio_data and type(
                margin_ratio_data[field]
            ) is not str:
                raise ValueError(
                    f"futures_preview_response_official_{field}_type_invalid"
                )
    return {
        "schema_status": "official_required_shape_valid",
        "official_required_fields_present": True,
        "official_optional_project_fields_present": {
            field: field in response
            for field in _POST_R10_OFFICIAL_OPTIONAL_PROJECT_FIELDS
        },
        "unknown_fields_ignored": True,
        "raw_response_included": False,
    }


def _post_r10_decimal(value: Any, invalid_reason: str) -> Decimal:
    """Parse one bounded plain decimal string without echoing its value."""

    if (
        type(value) is not str
        or not value
        or len(value) > _POST_R10_MAX_DECIMAL_TOKEN_LENGTH
        or _POST_R10_DECIMAL_TOKEN.fullmatch(value) is None
    ):
        raise ValueError(invalid_reason)
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError(invalid_reason) from None


def _post_r10_decimal_text(value: Decimal) -> str:
    """Canonicalize permitted signed zero before sanitized persistence."""

    return "0" if value == 0 else _decimal_text(value)


def validate_post_r10_preview_response_acceptance(
    value: Any,
) -> dict[str, Any]:
    """Apply prospective fixed-scope acceptance after wire validation.

    Coinbase-optional fields can remain mandatory for this project's exact
    one-contract safety policy.  Legacy liquidation fields and unknown keys
    are ignored and never parsed, returned, or used as fallback evidence.
    """

    response = _post_r10_shallow_mapping(value)
    if response is None:
        raise ValueError("futures_preview_response_official_response_missing")
    validate_post_r10_official_preview_response_schema(response)
    if response["errs"]:
        raise ValueError("futures_preview_response_exchange_errors_present")
    if response["warning"]:
        raise ValueError("futures_preview_response_exchange_warnings_present")
    if response["is_max"] is not False:
        raise ValueError("futures_preview_response_project_is_max_true")

    if (
        "preview_id" not in response
        or response["preview_id"] is None
        or response["preview_id"] == ""
    ):
        raise ValueError(
            "futures_preview_response_project_preview_id_missing"
        )
    preview_id = response["preview_id"]
    if (
        type(preview_id) is not str
        or preview_id != preview_id.strip()
        or not preview_id.isprintable()
        or len(preview_id) > 256
    ):
        raise ValueError(
            "futures_preview_response_project_preview_id_invalid"
        )

    decimals: dict[str, Decimal] = {}
    for field in _POST_R10_OFFICIAL_REQUIRED_STRING_FIELDS:
        decimal = _post_r10_decimal(
            response[field],
            f"futures_preview_response_{field}_invalid",
        )
        decimals[field] = decimal
        if not decimal.is_finite():
            raise ValueError(f"futures_preview_response_{field}_invalid")
        if field == "commission_total":
            if decimal < 0:
                raise ValueError(
                    "futures_preview_response_commission_total_negative"
                )
        elif decimal <= 0:
            raise ValueError(
                f"futures_preview_response_{field}_not_positive"
            )

    if (
        "order_margin_total" not in response
        or response["order_margin_total"] is None
        or response["order_margin_total"] == ""
    ):
        raise ValueError(
            "futures_preview_response_project_order_margin_total_missing"
        )
    order_margin_total = _post_r10_decimal(
        response["order_margin_total"],
        "futures_preview_response_project_order_margin_total_invalid",
    )
    if not order_margin_total.is_finite() or order_margin_total <= 0:
        raise ValueError(
            "futures_preview_response_project_order_margin_total_"
            "not_finite_or_positive"
        )

    if "margin_ratio_data" not in response:
        raise ValueError(
            "futures_preview_response_liquidation_replacement_missing"
        )
    margin_ratio_value = _post_r10_shallow_mapping(
        response["margin_ratio_data"]
    )
    if margin_ratio_value is None:
        raise ValueError(
            "futures_preview_response_liquidation_replacement_invalid"
        )
    margin_ratio_data = margin_ratio_value
    sanitized_margin_ratio: dict[str, str] = {}
    for field in ("current_margin_ratio", "projected_margin_ratio"):
        if (
            field not in margin_ratio_data
            or margin_ratio_data[field] is None
            or margin_ratio_data[field] == ""
        ):
            raise ValueError(
                f"futures_preview_response_project_{field}_missing"
            )
        decimal = _post_r10_decimal(
            margin_ratio_data[field],
            f"futures_preview_response_project_{field}_invalid",
        )
        if not decimal.is_finite() or decimal < 0:
            raise ValueError(
                f"futures_preview_response_project_{field}_"
                "not_finite_or_negative"
            )
        sanitized_margin_ratio[field] = _post_r10_decimal_text(decimal)

    sanitized: dict[str, Any] = {
        "preview_id": preview_id,
        "errs": [],
        "warning": [],
        "is_max": False,
        **{
            field: _post_r10_decimal_text(decimals[field])
            for field in _POST_R10_OFFICIAL_REQUIRED_STRING_FIELDS
        },
        "order_margin_total": _post_r10_decimal_text(order_margin_total),
        "margin_ratio_data": sanitized_margin_ratio,
        "liquidation_evidence_source": "margin_ratio_data",
    }
    if "predicted_liquidation_price" in response:
        predicted_liquidation_price = _post_r10_decimal(
            response["predicted_liquidation_price"],
            "futures_preview_response_project_predicted_liquidation_price_"
            "invalid",
        )
        if (
            not predicted_liquidation_price.is_finite()
            or predicted_liquidation_price <= 0
        ):
            raise ValueError(
                "futures_preview_response_project_predicted_liquidation_"
                "price_not_finite_or_positive"
            )
        sanitized["predicted_liquidation_price"] = _decimal_text(
            predicted_liquidation_price
        )
        sanitized["liquidation_evidence_source"] = (
            "margin_ratio_data_and_predicted_liquidation_price"
        )
    return sanitized


def classify_post_r10_preview_response_rejection(
    exc: BaseException,
) -> str | None:
    """Return only an exact prospective value-blind rejection category."""

    if (
        type(exc) is not ValueError
        or len(exc.args) != 1
        or type(exc.args[0]) is not str
        or exc.args[0] not in _POST_R10_PREVIEW_RESPONSE_REJECTION_REASONS
    ):
        return None
    return exc.args[0]


def validate_margin_collateral_evidence(value: Any) -> Decimal:
    """Return authoritative available US CFM margin or fail closed."""

    return _validate_margin_collateral_evidence(value, policy_version="v1")


def validate_slice2_preview_margin_collateral_evidence(value: Any) -> Decimal:
    """Validate R5 margin evidence under the operator's Preview-only policy."""

    return _validate_margin_collateral_evidence(value, policy_version="v2")


def validate_slice2_preview_r6_margin_collateral_evidence(
    value: Any,
) -> Decimal:
    """Validate R6 margin evidence under the exact-pair Preview-only policy."""

    return _validate_margin_collateral_evidence(value, policy_version="v3")


def _validate_margin_collateral_evidence(
    value: Any,
    *,
    policy_version: str,
) -> Decimal:
    """Apply common US CFM risk gates with one explicit window policy."""

    if policy_version not in {"v1", "v2", "v3"}:
        raise ValueError("futures_preview_margin_window_policy_invalid")

    evidence = _mapping(value)
    if (
        evidence.get("status") != "ready"
        or evidence.get("account_family") != "coinbase_futures_us_cfm"
        or evidence.get("source") != "backend_rest_client"
        or evidence.get("intx_applicability") != "not_applicable_us_account"
        or not isinstance(evidence.get("errors"), list)
        or bool(evidence["errors"])
    ):
        raise ValueError("futures_preview_margin_collateral_ambiguous")
    summary = _mapping(evidence.get("balance_summary"))
    if _mapping(evidence.get("source_read_attempts")) != (
        FUTURES_PREVIEW_EXPECTED_MARGIN_SOURCE_READS
    ):
        raise ValueError("futures_preview_margin_source_reads_ambiguous")
    available = _usd_money_value(
        summary.get("available_margin"),
        "available_margin",
    )
    _usd_money_value(summary.get("total_usd_balance"), "total_usd_balance")
    _usd_money_value(summary.get("cfm_usd_balance"), "cfm_usd_balance")
    _usd_money_value(summary.get("futures_buying_power"), "futures_buying_power")
    _usd_money_value(summary.get("initial_margin"), "initial_margin")
    _usd_money_value(
        summary.get("liquidation_threshold"),
        "liquidation_threshold",
    )
    measure = _mapping(summary.get("intraday_margin_window_measure"))
    if (
        measure.get("margin_window_type")
        not in FUTURES_PREVIEW_OPERATIONAL_FCM_MARGIN_WINDOW_TYPES
    ):
        raise ValueError("futures_preview_margin_window_measure_ambiguous")
    for field in ("maintenance_margin", "liquidation_buffer"):
        amount = _decimal(measure.get(field), field)
        if not amount.is_finite() or amount < 0:
            raise ValueError(f"futures_preview_margin_{field}_invalid")

    setting_evidence = _mapping(evidence.get("intraday_margin_setting"))
    setting = setting_evidence.get("setting")
    if (
        not isinstance(setting, str)
        or setting not in FUTURES_PREVIEW_DOCUMENTED_MARGIN_SETTINGS
        or bool(set(setting_evidence) - _SDK_MARGIN_SETTING_FIELDS)
    ):
        raise ValueError("futures_preview_margin_setting_ambiguous")
    if setting not in FUTURES_PREVIEW_OPERATIONAL_MARGIN_SETTINGS:
        raise ValueError("futures_preview_margin_setting_unspecified")
    if policy_version == "v1":
        margin_windows_diagnostic = _classify_margin_windows(evidence)
        failing_row_index = margin_windows_diagnostic["failing_row_index"]
        if (
            margin_windows_diagnostic["classification"] != "ready"
            and failing_row_index is None
            and margin_windows_diagnostic["classification"]
            != "expected_profile_set_incomplete"
        ):
            raise ValueError("futures_preview_margin_windows_ambiguous")
    elif policy_version == "v2":
        margin_windows_diagnostic = (
            _classify_slice2_preview_margin_windows_policy(evidence)
        )
        failing_row_index = None
        if not margin_windows_diagnostic["margin_window_policy_satisfied"]:
            raise ValueError("futures_preview_margin_windows_ambiguous")
    else:
        margin_windows_diagnostic = (
            _classify_slice2_preview_margin_windows_policy(
                evidence,
                policy_version="v3",
            )
        )
        failing_row_index = None
        if not margin_windows_diagnostic["margin_window_policy_satisfied"]:
            raise ValueError("futures_preview_margin_windows_ambiguous")
    windows = evidence.get("current_margin_windows", [])
    for index, item in enumerate(windows):
        if failing_row_index == index:
            raise ValueError("futures_preview_margin_windows_ambiguous")
        window = _mapping(item)
        for killswitch_field in (
            "is_intraday_margin_killswitch_enabled",
            "is_intraday_margin_enrollment_killswitch_enabled",
        ):
            killswitch = window.get(killswitch_field)
            if not isinstance(killswitch, bool):
                raise ValueError("futures_preview_margin_killswitch_ambiguous")
            if killswitch:
                raise ValueError("futures_preview_margin_killswitch_enabled")
    if margin_windows_diagnostic["classification"] != "ready":
        raise ValueError("futures_preview_margin_windows_ambiguous")
    if (
        not isinstance(evidence.get("futures_sweeps"), list)
        or bool(evidence["futures_sweeps"])
    ):
        raise ValueError("futures_preview_margin_sweeps_ambiguous")
    if available <= 0:
        raise ValueError("futures_preview_available_margin_not_positive")
    return available


def validate_preview_against_candidate(
    preview: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind authoritative Preview size/notional back to the fixed caps."""

    response = dict(preview)
    base_size = _positive_decimal(response.get("base_size"), "preview_base_size")
    if base_size != FUTURES_PREVIEW_CONTRACT_COUNT:
        raise ValueError("futures_preview_base_size_candidate_mismatch")
    order_total = _positive_decimal(
        response.get("order_total"),
        "preview_order_total",
    )
    quote_size = _positive_decimal(
        response.get("quote_size"),
        "preview_quote_size",
    )
    commission = _decimal(
        response.get("commission_total"),
        "preview_commission_total",
    )
    if not commission.is_finite() or commission < 0:
        raise ValueError("futures_preview_commission_total_invalid")
    preview_bid = _positive_decimal(response.get("best_bid"), "preview_best_bid")
    preview_ask = _positive_decimal(response.get("best_ask"), "preview_best_ask")
    if preview_bid >= preview_ask:
        raise ValueError("futures_preview_response_book_ambiguous")

    contract_size = _positive_decimal(
        candidate.get("contract_size"),
        "candidate_contract_size",
    )
    preview_market_reference = (
        preview_ask * contract_size * FUTURES_PREVIEW_CONTRACT_COUNT
    )
    candidate_opening = _positive_decimal(
        candidate.get("opening_reference_notional_usdc"),
        "candidate_opening_reference_notional",
    )
    authoritative_opening = max(
        candidate_opening,
        preview_market_reference,
        order_total + commission,
        quote_size + commission,
    )
    maximum_exposure = authoritative_opening
    buffered_close = maximum_exposure * FUTURES_PREVIEW_CLOSE_BUFFER
    turnover = authoritative_opening + buffered_close
    if authoritative_opening >= FUTURES_PREVIEW_OPENING_CAP_USDC:
        raise ValueError("futures_preview_response_opening_cap_blocked")
    if maximum_exposure >= FUTURES_PREVIEW_EXPOSURE_CAP_USDC:
        raise ValueError("futures_preview_response_exposure_cap_blocked")
    if buffered_close >= FUTURES_PREVIEW_EXPOSURE_CAP_USDC:
        raise ValueError("futures_preview_response_buffered_close_cap_blocked")
    if turnover >= FUTURES_PREVIEW_TURNOVER_CAP_USDC:
        raise ValueError("futures_preview_response_turnover_cap_blocked")
    response["candidate_binding"] = {
        "status": "matched",
        "contract_count": "1",
        "authoritative_opening_reference_notional_usdc": _notional_text(
            authoritative_opening
        ),
        "maximum_exposure_reference_notional_usdc": _notional_text(
            maximum_exposure
        ),
        "buffered_close_reference_notional_usdc": _notional_text(
            buffered_close
        ),
        "branch_turnover_reference_notional_usdc": _notional_text(turnover),
        "reference_rule": (
            "max_candidate_reference_preview_ask_contract_notional_"
            "order_total_plus_fee_quote_size_plus_fee"
        ),
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "comparison": "strictly_less_than",
    }
    return response


def _accepted_evidence(
    *,
    claim: Mapping[str, Any],
    claim_sha256: str,
    counters: Mapping[str, int],
    read_counters: Mapping[str, int],
    binding: Mapping[str, Any],
    permissions: Any,
    portfolios: Any,
    product: Mapping[str, Any],
    book: Mapping[str, Any],
    positions: Any,
    margin_collateral: Mapping[str, Any],
    candidate: Mapping[str, Any],
    preview_request: Mapping[str, Any],
    preview_response: Mapping[str, Any],
    seal_ready_plan: Mapping[str, Any],
    completed_at: datetime,
) -> dict[str, Any]:
    sanitized_permissions = _sanitized_permission_evidence(binding)
    sanitized_portfolio = _sanitized_portfolio_catalog_evidence(binding)
    sanitized_positions = _sanitized_position_evidence(positions)
    sanitized_margin = _sanitized_margin_collateral_evidence(margin_collateral)
    product_evidence = (
        _sanitized_product_evidence(product)
        if claim["artifact_type"] in _SANITIZED_PREVIEW_ARTIFACT_TYPES
        else _plain(product)
    )
    market_evidence = (
        _sanitized_market_evidence(book)
        if claim["artifact_type"] in _SANITIZED_PREVIEW_ARTIFACT_TYPES
        else _plain(book)
    )
    evidence: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "type": "admin_futures_order_preview",
        "artifact_type": claim["artifact_type"],
        "status": "accepted",
        "outcome": "accepted",
        "predecessor_binding": dict(claim["predecessor_binding"]),
        "reserved_at": claim["reserved_at"],
        "completed_at": _timestamp(completed_at),
        "claim_sha256": claim_sha256,
        "actor_id": claim["actor_id"],
        "roles": list(claim["roles"]),
        "correlation_id": claim["correlation_id"],
        "idempotency_key": claim["idempotency_key"],
        "profile_label": "Default",
        "portfolio_type": "DEFAULT",
        "portfolio_id": binding.get("observed_portfolio_id"),
        "portfolio_binding": dict(binding),
        "permission_evidence": sanitized_permissions,
        "permission_evidence_sha256": canonical_sha256(sanitized_permissions),
        "portfolio_catalog_evidence": sanitized_portfolio,
        "portfolio_catalog_sha256": canonical_sha256(sanitized_portfolio),
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "product_evidence": product_evidence,
        "product_evidence_sha256": canonical_sha256(product_evidence),
        "market_evidence": market_evidence,
        "market_evidence_sha256": canonical_sha256(market_evidence),
        "position_evidence": sanitized_positions,
        "position_evidence_sha256": canonical_sha256(sanitized_positions),
        "margin_collateral_evidence": sanitized_margin,
        "margin_collateral_evidence_sha256": canonical_sha256(sanitized_margin),
        **_margin_setting_terminal_context(margin_collateral),
        "candidate": dict(candidate),
        "candidate_sha256": canonical_sha256(candidate),
        "preview_request": dict(preview_request),
        "preview_request_sha256": canonical_sha256(preview_request),
        "preview_response": dict(preview_response),
        "preview_response_sha256": canonical_sha256(preview_response),
        "seal_ready_plan": dict(seal_ready_plan),
        "seal_ready_plan_sha256": canonical_sha256(seal_ready_plan),
        "attempt_counters": dict(counters),
        "read_counters": dict(read_counters),
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "live_execution": "not_run",
        "live_coinbase_execution": "not_run",
        "live_coinbase_read_ran": True,
        "exchange_submission_attempt_count": 0,
        "read_only": True,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "artifacts": {
            "execution_marker_created": False,
            "attempt_ledger_created": False,
            "runtime_created": False,
        },
        "canonicalization": "sorted_keys_compact_utf8_json",
        "hash_algorithm": "sha256",
    }
    if claim["artifact_type"] == _R5_ARTIFACT_TYPE:
        evidence.update(
            slice2_preview_margin_windows_policy_context(margin_collateral)
        )
    elif claim["artifact_type"] in _V3_MARGIN_WINDOW_ARTIFACT_TYPES:
        evidence.update(
            slice2_preview_margin_windows_pair_policy_context(
                margin_collateral
            )
        )
    if claim["artifact_type"] in _CORRECTED_RESPONSE_SCHEMA_ARTIFACT_TYPES:
        evidence["preview_response_schema_binding"] = deepcopy(
            claim["preview_response_schema_binding"]
        )
    if claim["artifact_type"] in _POST_PREVIEW_DIAGNOSTIC_ARTIFACT_TYPES:
        evidence["post_preview_diagnostic_binding"] = deepcopy(
            claim["post_preview_diagnostic_binding"]
        )
        evidence["post_preview_stage_evidence"] = None
        evidence["post_preview_stage_evidence_sha256"] = None
    evidence["evidence_sha256"] = canonical_sha256(evidence)
    return evidence


def _withhold_r8_private_claim(
    claim: Mapping[str, Any],
) -> dict[str, Any]:
    """Return an R8+ reservation claim with trace values hash-only."""

    result = deepcopy(dict(claim))
    artifact_type = result.get("artifact_type")
    if artifact_type not in {
        FUTURES_PREVIEW_R8_ARTIFACT_TYPE,
        FUTURES_PREVIEW_R9_ARTIFACT_TYPE,
        FUTURES_PREVIEW_R10_ARTIFACT_TYPE,
        FUTURES_PREVIEW_R11_ARTIFACT_TYPE,
    }:
        return result
    claim_validator = {
        FUTURES_PREVIEW_R8_ARTIFACT_TYPE: _validate_r8_ephemeral_claim_record,
        FUTURES_PREVIEW_R9_ARTIFACT_TYPE: _validate_r9_ephemeral_claim_record,
        FUTURES_PREVIEW_R10_ARTIFACT_TYPE: _validate_r10_ephemeral_claim_record,
        FUTURES_PREVIEW_R11_ARTIFACT_TYPE: _validate_r11_ephemeral_claim_record,
    }[artifact_type]
    persisted_validator = {
        FUTURES_PREVIEW_R8_ARTIFACT_TYPE: _validate_r8_claim_record,
        FUTURES_PREVIEW_R9_ARTIFACT_TYPE: _validate_r9_claim_record,
        FUTURES_PREVIEW_R10_ARTIFACT_TYPE: _validate_r10_claim_record,
        FUTURES_PREVIEW_R11_ARTIFACT_TYPE: _validate_r11_claim_record,
    }[artifact_type]
    claim_validator(result)
    for field in ("correlation_id", "idempotency_key"):
        value = result.get(field)
        if not isinstance(value, str) or not value or value == "withheld":
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R8 private trace binding is unavailable"
            )
        result[f"{field}_sha256"] = hashlib.sha256(
            value.encode("utf-8")
        ).hexdigest()
        result[field] = "withheld"
    persisted_validator(result)
    return result


def _withhold_r8_private_accepted_evidence(
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a persistence-safe R8+ terminal with private values withheld."""

    result = deepcopy(dict(evidence))
    if result.get("artifact_type") not in {
        FUTURES_PREVIEW_R8_ARTIFACT_TYPE,
        FUTURES_PREVIEW_R9_ARTIFACT_TYPE,
        FUTURES_PREVIEW_R10_ARTIFACT_TYPE,
        FUTURES_PREVIEW_R11_ARTIFACT_TYPE,
    }:
        return result
    accepted = result.get("outcome") == "accepted"
    preview_present = isinstance(result.get("preview_response"), Mapping)
    preview = _mapping(result.get("preview_response"))
    preview_id = preview.get("preview_id")
    portfolio_id = result.get("portfolio_id")
    for field in ("correlation_id", "idempotency_key"):
        value = result.get(field)
        if isinstance(value, str) and value and value != "withheld":
            result[f"{field}_sha256"] = hashlib.sha256(
                value.encode("utf-8")
            ).hexdigest()
            result[field] = "withheld"
    if accepted and (
        not isinstance(preview_id, str)
        or not preview_id
        or preview_id == "withheld"
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 private Preview binding is unavailable"
        )
    if accepted and (
        not isinstance(portfolio_id, str)
        or not portfolio_id
        or portfolio_id == "withheld"
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 private portfolio binding is unavailable"
        )
    if (
        isinstance(portfolio_id, str)
        and portfolio_id
        and portfolio_id != "withheld"
    ):
        result["portfolio_id_sha256"] = hashlib.sha256(
            portfolio_id.encode("utf-8")
        ).hexdigest()
        result["portfolio_id"] = "withheld"

        if isinstance(result.get("portfolio_binding"), Mapping):
            portfolio_binding = _mapping(result["portfolio_binding"])
            portfolio_binding["observed_portfolio_id"] = "withheld"
            portfolio_binding["portfolio_id"] = "withheld"
            result["portfolio_binding"] = portfolio_binding

        if isinstance(result.get("permission_evidence"), Mapping):
            permission_evidence = _mapping(result["permission_evidence"])
            permission_evidence["portfolio_id"] = "withheld"
            result["permission_evidence"] = permission_evidence
            result["permission_evidence_sha256"] = canonical_sha256(
                permission_evidence
            )

        if isinstance(result.get("portfolio_catalog_evidence"), Mapping):
            portfolio_catalog = _mapping(
                result["portfolio_catalog_evidence"]
            )
            portfolio_catalog["selected_portfolio_id"] = "withheld"
            result["portfolio_catalog_evidence"] = portfolio_catalog
            result["portfolio_catalog_sha256"] = canonical_sha256(
                portfolio_catalog
            )

    if (
        preview_present
        and isinstance(preview_id, str)
        and preview_id
        and preview_id != "withheld"
    ):
        result["preview_id_sha256"] = hashlib.sha256(
            preview_id.encode("utf-8")
        ).hexdigest()
        preview["preview_id"] = "withheld"
        result["preview_response"] = preview
        result["preview_response_sha256"] = canonical_sha256(preview)

    if isinstance(result.get("seal_ready_plan"), Mapping):
        plan = _mapping(result["seal_ready_plan"])
        for field in ("correlation_id", "idempotency_key"):
            value = plan.get(field)
            if isinstance(value, str) and value and value != "withheld":
                plan[f"{field}_sha256"] = hashlib.sha256(
                    value.encode("utf-8")
                ).hexdigest()
                plan[field] = "withheld"
        if isinstance(plan.get("profile_binding"), Mapping):
            profile_binding = _mapping(plan["profile_binding"])
            profile_binding["portfolio_id"] = "withheld"
            plan["profile_binding"] = profile_binding
        if isinstance(plan.get("authoritative_preview"), Mapping):
            authoritative_preview = _mapping(
                plan["authoritative_preview"]
            )
            authoritative_preview["preview_id"] = "withheld"
            authoritative_preview["preview_response"] = deepcopy(preview)
            authoritative_preview["preview_response_sha256"] = (
                canonical_sha256(preview)
            )
            plan["authoritative_preview"] = authoritative_preview
        if isinstance(plan.get("preflight_evidence_hashes"), Mapping):
            preflight_hashes = _mapping(plan["preflight_evidence_hashes"])
            if "permission_evidence_sha256" in result:
                preflight_hashes["permissions"] = result[
                    "permission_evidence_sha256"
                ]
            if "portfolio_catalog_sha256" in result:
                preflight_hashes["portfolio_catalog"] = result[
                    "portfolio_catalog_sha256"
                ]
            plan["preflight_evidence_hashes"] = preflight_hashes
        result["seal_ready_plan"] = plan
        result["seal_ready_plan_sha256"] = canonical_sha256(plan)
    result["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in result.items()
            if key != "evidence_sha256"
        }
    )
    return result


def _terminal_failure_record(
    *,
    claim: Mapping[str, Any],
    claim_sha256: str,
    counters: Mapping[str, int],
    read_counters: Mapping[str, int],
    outcome: str,
    blocker: str,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "type": "admin_futures_order_preview",
        "artifact_type": claim["artifact_type"],
        "status": outcome,
        "outcome": outcome,
        "predecessor_binding": dict(claim["predecessor_binding"]),
        "reserved_at": claim["reserved_at"],
        "completed_at": _timestamp(datetime.now(timezone.utc)),
        "claim_sha256": claim_sha256,
        "actor_id": claim["actor_id"],
        "roles": list(claim["roles"]),
        "correlation_id": claim["correlation_id"],
        "idempotency_key": claim["idempotency_key"],
        "profile_label": "Default",
        "portfolio_type": "DEFAULT",
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "attempt_counters": dict(counters),
        "read_counters": dict(read_counters),
        "blocker": blocker,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "live_execution": "not_run",
        "live_coinbase_execution": "not_run",
        "live_coinbase_read_ran": any(read_counters.values()),
        "exchange_submission_attempt_count": 0,
        "read_only": True,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "artifacts": {
            "execution_marker_created": False,
            "attempt_ledger_created": False,
            "runtime_created": False,
        },
        "canonicalization": "sorted_keys_compact_utf8_json",
        "hash_algorithm": "sha256",
    }
    if context:
        normalized_context = {
            key: _plain(context[key])
            for key in _TERMINAL_FAILURE_CONTEXT_ALLOWED_KEYS
            if key in context
        }
        evidence.update(normalized_context)
        stage_evidence = (
            _plain(context["pre_preview_stage_evidence"])
            if "pre_preview_stage_evidence" in context
            else None
        )
        stage_evidence_sha256 = (
            _plain(context["pre_preview_stage_evidence_sha256"])
            if "pre_preview_stage_evidence_sha256" in context
            else None
        )
        if stage_evidence is not None or stage_evidence_sha256 is not None:
            evidence["pre_preview_stage_evidence"] = stage_evidence
            evidence["pre_preview_stage_evidence_sha256"] = (
                stage_evidence_sha256
            )
    if claim["artifact_type"] in _CORRECTED_RESPONSE_SCHEMA_ARTIFACT_TYPES:
        evidence["preview_response_schema_binding"] = deepcopy(
            claim["preview_response_schema_binding"]
        )
    if claim["artifact_type"] in _POST_PREVIEW_DIAGNOSTIC_ARTIFACT_TYPES:
        evidence["post_preview_diagnostic_binding"] = deepcopy(
            claim["post_preview_diagnostic_binding"]
        )
    evidence["evidence_sha256"] = canonical_sha256(evidence)
    return evidence


def _terminal_attempt_context(
    *,
    artifact_type: str,
    binding: Mapping[str, Any],
    permissions: Any,
    portfolios: Any,
    product: Any,
    book: Any,
    positions: Any,
    margin_collateral: Any,
    candidate: Mapping[str, Any],
    preview_request: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the exact preflight and payload for any post-attempt terminal state."""

    sanitized_permissions = _sanitized_permission_evidence(binding)
    sanitized_portfolio = _sanitized_portfolio_catalog_evidence(binding)
    sanitized_positions = _sanitized_position_evidence(positions)
    sanitized_margin = _sanitized_margin_collateral_evidence(margin_collateral)
    product_evidence = (
        _sanitized_product_evidence(product)
        if artifact_type in _SANITIZED_PREVIEW_ARTIFACT_TYPES
        else _plain(product)
    )
    market_evidence = (
        _sanitized_market_evidence(book)
        if artifact_type in _SANITIZED_PREVIEW_ARTIFACT_TYPES
        else _plain(book)
    )
    context = {
        "portfolio_id": binding.get("observed_portfolio_id"),
        "portfolio_binding": dict(binding),
        "permission_evidence": sanitized_permissions,
        "permission_evidence_sha256": canonical_sha256(sanitized_permissions),
        "portfolio_catalog_evidence": sanitized_portfolio,
        "portfolio_catalog_sha256": canonical_sha256(sanitized_portfolio),
        "product_evidence": product_evidence,
        "product_evidence_sha256": canonical_sha256(product_evidence),
        "market_evidence": market_evidence,
        "market_evidence_sha256": canonical_sha256(market_evidence),
        "position_evidence": sanitized_positions,
        "position_evidence_sha256": canonical_sha256(sanitized_positions),
        "margin_collateral_evidence": sanitized_margin,
        "margin_collateral_evidence_sha256": canonical_sha256(sanitized_margin),
        **_margin_setting_terminal_context(margin_collateral),
        "candidate": dict(candidate),
        "candidate_sha256": canonical_sha256(candidate),
        "preview_request": dict(preview_request),
        "preview_request_sha256": canonical_sha256(preview_request),
    }
    if artifact_type == _R5_ARTIFACT_TYPE:
        context.update(
            slice2_preview_margin_windows_policy_context(margin_collateral)
        )
    elif artifact_type in _V3_MARGIN_WINDOW_ARTIFACT_TYPES:
        context.update(
            slice2_preview_margin_windows_pair_policy_context(
                margin_collateral
            )
        )
    return context


def _sanitized_permission_evidence(
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "portfolio_id": binding.get("observed_portfolio_id"),
        "portfolio_type": binding.get("observed_portfolio_type"),
        "can_view": binding.get("can_view"),
        "can_trade": binding.get("can_trade"),
        "selection_authority": binding.get("selection_authority"),
        "sanitized": True,
        "raw_response_included": False,
    }


def _sanitized_portfolio_catalog_evidence(
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "selected_portfolio_id": binding.get("observed_portfolio_id"),
        "selected_portfolio_label": binding.get("observed_portfolio_label"),
        "selected_portfolio_type": binding.get("observed_portfolio_type"),
        "exact_match_count": 1,
        "sanitized": True,
        "raw_response_included": False,
    }


def _sanitized_position_evidence(positions: Any) -> dict[str, Any]:
    contracts = _position_contracts(positions, FUTURES_PREVIEW_PRODUCT_ID)
    return {
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "observed_contract_count": _decimal_text(contracts),
        "sanitized": True,
        "raw_response_included": False,
    }


def _sanitized_product_evidence(product: Any) -> dict[str, Any]:
    """Return only candidate-relevant R5 product fields."""

    item = _mapping(product)
    details = _mapping(item.get("future_product_details"))
    return {
        "product_id": item.get("product_id"),
        "display_name": item.get("display_name"),
        "product_type": item.get("product_type"),
        "status": item.get("status"),
        "price": item.get("price"),
        "price_increment": item.get("price_increment"),
        "base_increment": item.get("base_increment"),
        "base_min_size": item.get("base_min_size"),
        "trading_disabled": item.get("trading_disabled"),
        "view_only": item.get("view_only"),
        "cancel_only": item.get("cancel_only"),
        "future_product_details": {
            key: details.get(key)
            for key in (
                "contract_size",
                "contract_code",
                "group_description",
                "group_short_description",
                "venue",
                "risk_managed_by",
                "contract_expiry",
                "contract_expiry_type",
            )
        },
        "sanitized": True,
        "raw_response_included": False,
    }


def _sanitized_market_evidence(book: Any) -> dict[str, Any]:
    """Return only the exact fresh top-of-book fields used by R5."""

    pricebook = _exact_pricebook(_mapping(book))
    return {
        "product_id": pricebook.get("product_id"),
        "best_bid": _decimal_text(_top_price(pricebook, "bids")),
        "best_ask": _decimal_text(_top_price(pricebook, "asks")),
        "exchange_observed_at": pricebook.get("time"),
        "sanitized": True,
        "raw_response_included": False,
    }


def _sanitized_margin_collateral_evidence(value: Any) -> dict[str, Any]:
    evidence = _mapping(value)
    summary = _mapping(evidence.get("balance_summary"))
    measure = _mapping(summary.get("intraday_margin_window_measure"))
    setting = _mapping(evidence.get("intraday_margin_setting"))
    windows: list[dict[str, Any]] = []
    for item in evidence.get("current_margin_windows", []):
        window = _mapping(item)
        margin_window = _mapping(window.get("margin_window"))
        windows.append(
            {
                "profile": window.get("profile"),
                "margin_window_type": margin_window.get("margin_window_type"),
                "is_intraday_margin_killswitch_enabled": window.get(
                    "is_intraday_margin_killswitch_enabled"
                ),
                "is_intraday_margin_enrollment_killswitch_enabled": window.get(
                    "is_intraday_margin_enrollment_killswitch_enabled"
                ),
            }
        )
    windows.sort(key=lambda item: str(item["profile"]))
    return {
        "status": evidence.get("status"),
        "account_family": evidence.get("account_family"),
        "source": evidence.get("source"),
        "source_read_attempts": dict(
            _mapping(evidence.get("source_read_attempts"))
        ),
        "available_margin_usdc": _decimal_text(
            _usd_money_value(summary.get("available_margin"), "available_margin")
        ),
        "intraday_margin_window_measure": {
            "margin_window_type": measure.get("margin_window_type"),
            "maintenance_margin_usdc": _decimal_text(
                _decimal(measure.get("maintenance_margin"), "maintenance_margin")
            ),
            "liquidation_buffer_usdc": _decimal_text(
                _decimal(measure.get("liquidation_buffer"), "liquidation_buffer")
            ),
        },
        "intraday_margin_setting": {"setting": setting.get("setting")},
        "current_margin_windows": windows,
        "futures_sweep_count": len(evidence.get("futures_sweeps", [])),
        "sanitized": True,
        "raw_response_included": False,
    }


def _margin_setting_terminal_context(
    margin_collateral: Any,
) -> dict[str, Any]:
    """Return a secret-minimized margin-setting diagnostic."""

    snapshot = _plain(margin_collateral)
    snapshot_mapping = dict(snapshot) if isinstance(snapshot, Mapping) else {}
    container_present = "intraday_margin_setting" in snapshot_mapping
    raw_setting_evidence = snapshot_mapping.get("intraday_margin_setting")
    container_type = _diagnostic_value_type(
        raw_setting_evidence,
        present=container_present,
    )
    setting_evidence = (
        dict(_plain(raw_setting_evidence))
        if isinstance(raw_setting_evidence, Mapping)
        else {}
    )
    setting_present = "setting" in setting_evidence
    setting = setting_evidence.get("setting") if setting_present else None
    value_type = _diagnostic_value_type(setting, present=setting_present)
    token_is_well_formed = (
        isinstance(setting, str)
        and setting == setting.strip()
        and _SAFE_MARGIN_SETTING_TOKEN.fullmatch(setting) is not None
    )
    safe_setting = (
        setting
        if isinstance(setting, str)
        and setting in FUTURES_PREVIEW_DOCUMENTED_MARGIN_SETTINGS
        else None
    )
    allowlist_match = (
        isinstance(setting, str)
        and setting in FUTURES_PREVIEW_DOCUMENTED_MARGIN_SETTINGS
    )
    operationally_resolved = (
        isinstance(setting, str)
        and setting in FUTURES_PREVIEW_OPERATIONAL_MARGIN_SETTINGS
    )
    if token_is_well_formed:
        token_form = "safe_enum_token"
        classification = (
            "recognized_string"
            if allowlist_match
            else "unrecognized_string"
        )
    elif isinstance(setting, str):
        token_form = "malformed_string"
        classification = "malformed_string"
    elif not container_present:
        token_form = "not_applicable"
        classification = "missing_container"
    elif not isinstance(raw_setting_evidence, Mapping):
        token_form = "not_applicable"
        classification = "non_mapping_container"
    elif not setting_present:
        token_form = "not_applicable"
        classification = "missing_field"
    elif setting is None:
        token_form = "not_applicable"
        classification = "null_value"
    else:
        token_form = "not_applicable"
        classification = "non_string_value"
    diagnostic = {
        "source": "backend_rest_client.get_intraday_margin_setting",
        "stage": "margin_collateral_validation",
        "field_path": "intraday_margin_setting.setting",
        "container_present": container_present,
        "container_type": container_type,
        "field_present": setting_present,
        "value_type": value_type,
        "token_form": token_form,
        "observed_token": safe_setting,
        "allowlist_match": allowlist_match,
        "operationally_resolved": operationally_resolved,
        "enum_authority": "official_coinbase_advanced_trade_api_docs",
        "classification": classification,
        "unexpected_field_count": len(
            set(setting_evidence) - _SDK_MARGIN_SETTING_FIELDS
        ),
        "sanitized": True,
        "raw_response_included": False,
    }
    return {
        "margin_setting_evidence": diagnostic,
        "margin_setting_evidence_sha256": canonical_sha256(diagnostic),
    }


def _margin_windows_terminal_context(
    margin_collateral: Any,
) -> dict[str, Any]:
    """Return an exact, identifier-withholding margin-window diagnostic."""

    diagnostic = _classify_margin_windows(margin_collateral)
    return {
        "margin_windows_evidence": diagnostic,
        "margin_windows_evidence_sha256": canonical_sha256(diagnostic),
    }


def _classify_margin_windows(margin_collateral: Any) -> dict[str, Any]:
    """Classify the exact current-window validation boundary without raw values."""

    snapshot = (
        dict(margin_collateral)
        if isinstance(margin_collateral, Mapping)
        else {}
    )
    container_present = "current_margin_windows" in snapshot
    windows = snapshot.get("current_margin_windows")
    container_type = _diagnostic_value_type(
        windows,
        present=container_present,
    )

    def result(
        *,
        row_count_bucket: str,
        classification: str,
        failing_row_index: int | None,
        recognized_profile: str | None,
        failing_field: str | None,
        failing_value_type: str | None,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "source": "backend_rest_client.get_current_margin_window",
            "stage": "margin_collateral_validation",
            "field_path": "current_margin_windows",
            "container_present": container_present,
            "container_type": container_type,
            "row_count_bucket": row_count_bucket,
            "expected_row_count": 2,
            "failing_row_index": failing_row_index,
            "recognized_profile": recognized_profile,
            "failing_field": failing_field,
            "failing_value_type": failing_value_type,
            "classification": classification,
            "sanitized": True,
            "raw_response_included": False,
            "external_exception_text_included": False,
            "unknown_identifier_values_included": False,
        }

    if not container_present:
        return result(
            row_count_bucket="not_applicable",
            classification="missing_container",
            failing_row_index=None,
            recognized_profile=None,
            failing_field="current_margin_windows",
            failing_value_type="missing",
        )
    if not isinstance(windows, list):
        return result(
            row_count_bucket="not_applicable",
            classification="non_list_container",
            failing_row_index=None,
            recognized_profile=None,
            failing_field="current_margin_windows",
            failing_value_type=container_type,
        )
    row_count_bucket = {
        0: "zero",
        1: "one",
        2: "expected_two",
    }.get(len(windows), "more_than_two")
    if len(windows) != 2:
        return result(
            row_count_bucket=row_count_bucket,
            classification="unexpected_row_count",
            failing_row_index=None,
            recognized_profile=None,
            failing_field="current_margin_windows",
            failing_value_type="sequence",
        )

    observed_profiles: set[str] = set()
    for index, item in enumerate(windows):
        if not isinstance(item, Mapping):
            return result(
                row_count_bucket=row_count_bucket,
                classification="non_mapping_row",
                failing_row_index=index,
                recognized_profile=None,
                failing_field="row",
                failing_value_type=_diagnostic_value_type(item, present=True),
            )
        window = dict(item)
        profile_present = "profile" in window
        profile = window.get("profile")
        profile_type = _diagnostic_value_type(
            profile,
            present=profile_present,
        )
        if not profile_present:
            profile_classification = "profile_missing"
        elif profile is None:
            profile_classification = "profile_null"
        elif not isinstance(profile, str):
            profile_classification = "profile_non_string"
        elif (
            profile != profile.strip()
            or _SAFE_MARGIN_WINDOW_TOKEN.fullmatch(profile) is None
        ):
            profile_classification = "profile_malformed_string"
        elif profile not in FUTURES_PREVIEW_EXPECTED_MARGIN_PROFILES:
            profile_classification = "profile_unrecognized_enum_token"
        else:
            profile_classification = "ready"
        if profile_classification != "ready":
            return result(
                row_count_bucket=row_count_bucket,
                classification=profile_classification,
                failing_row_index=index,
                recognized_profile=None,
                failing_field="profile",
                failing_value_type=profile_type,
            )
        recognized_profile = FUTURES_PREVIEW_EXPECTED_MARGIN_PROFILES[profile]
        if profile in observed_profiles:
            return result(
                row_count_bucket=row_count_bucket,
                classification="duplicate_profile",
                failing_row_index=index,
                recognized_profile=recognized_profile,
                failing_field="profile",
                failing_value_type="string",
            )
        observed_profiles.add(profile)

        status_present = "status" in window
        status = window.get("status")
        status_type = _diagnostic_value_type(status, present=status_present)
        if not status_present:
            status_classification = "status_missing"
        elif status is None:
            status_classification = "status_null"
        elif not isinstance(status, str):
            status_classification = "status_non_string"
        elif status != "ready":
            status_classification = "status_not_ready"
        else:
            status_classification = "ready"
        if status_classification != "ready":
            return result(
                row_count_bucket=row_count_bucket,
                classification=status_classification,
                failing_row_index=index,
                recognized_profile=recognized_profile,
                failing_field="status",
                failing_value_type=status_type,
            )

        margin_window_present = "margin_window" in window
        margin_window = window.get("margin_window")
        margin_window_type = _diagnostic_value_type(
            margin_window,
            present=margin_window_present,
        )
        if not margin_window_present:
            container_classification = "margin_window_missing"
        elif margin_window is None:
            container_classification = "margin_window_null"
        elif not isinstance(margin_window, Mapping):
            container_classification = "margin_window_non_mapping"
        else:
            container_classification = "ready"
        if container_classification != "ready":
            return result(
                row_count_bucket=row_count_bucket,
                classification=container_classification,
                failing_row_index=index,
                recognized_profile=recognized_profile,
                failing_field="margin_window",
                failing_value_type=margin_window_type,
            )

        margin_window_mapping = dict(margin_window)
        window_type_present = "margin_window_type" in margin_window_mapping
        window_type = margin_window_mapping.get("margin_window_type")
        window_type_value_type = _diagnostic_value_type(
            window_type,
            present=window_type_present,
        )
        if not window_type_present:
            window_type_classification = "margin_window_type_missing"
        elif window_type is None:
            window_type_classification = "margin_window_type_null"
        elif not isinstance(window_type, str):
            window_type_classification = "margin_window_type_non_string"
        elif (
            window_type != window_type.strip()
            or _SAFE_MARGIN_WINDOW_TOKEN.fullmatch(window_type) is None
        ):
            window_type_classification = (
                "margin_window_type_malformed_string"
            )
        elif (
            window_type
            not in FUTURES_PREVIEW_OPERATIONAL_CURRENT_MARGIN_WINDOW_TYPES
        ):
            window_type_classification = (
                "margin_window_type_not_exact_operational_enum_token"
            )
        else:
            window_type_classification = "ready"
        if window_type_classification != "ready":
            return result(
                row_count_bucket=row_count_bucket,
                classification=window_type_classification,
                failing_row_index=index,
                recognized_profile=recognized_profile,
                failing_field="margin_window_type",
                failing_value_type=window_type_value_type,
            )

    if observed_profiles != set(FUTURES_PREVIEW_EXPECTED_MARGIN_PROFILES):
        return result(
            row_count_bucket=row_count_bucket,
            classification="expected_profile_set_incomplete",
            failing_row_index=None,
            recognized_profile=None,
            failing_field="expected_profile_set",
            failing_value_type=None,
        )
    return result(
        row_count_bucket=row_count_bucket,
        classification="ready",
        failing_row_index=None,
        recognized_profile=None,
        failing_field=None,
        failing_value_type=None,
    )


def slice2_preview_margin_windows_policy_context(
    margin_collateral: Any,
) -> dict[str, Any]:
    """Return a typed, sanitized, non-authorizing Slice 2 policy decision."""

    evidence = _classify_slice2_preview_margin_windows_policy(
        margin_collateral
    )
    return {
        "margin_windows_policy_evidence": evidence,
        "margin_windows_policy_evidence_sha256": canonical_sha256(evidence),
    }


def slice2_preview_margin_windows_pair_policy_context(
    margin_collateral: Any,
) -> dict[str, Any]:
    """Return the sanitized, non-authorizing exact-pair R6 decision."""

    evidence = _classify_slice2_preview_margin_windows_policy(
        margin_collateral,
        policy_version="v3",
    )
    return {
        "margin_windows_policy_evidence": evidence,
        "margin_windows_policy_evidence_sha256": canonical_sha256(evidence),
    }


def _classify_slice2_preview_margin_windows_policy(
    margin_collateral: Any,
    *,
    policy_version: str = "v2",
) -> dict[str, Any]:
    """Evaluate one versioned two-profile Preview-only operator policy."""

    if policy_version == "v2":
        operator_policy = FUTURES_PREVIEW_SLICE2_OPERATOR_MARGIN_WINDOW_POLICY
        schema_version = "2"
        policy_id = "slice2_preview_margin_window_profile_state_policy_v2"
    elif policy_version == "v3":
        operator_policy = (
            FUTURES_PREVIEW_SLICE2_R6_OPERATOR_MARGIN_WINDOW_POLICY
        )
        schema_version = "3"
        policy_id = "slice2_preview_margin_window_exact_pair_policy_v3"
    else:
        raise ValueError("futures_preview_margin_window_policy_invalid")

    snapshot = (
        dict(margin_collateral)
        if isinstance(margin_collateral, Mapping)
        else {}
    )
    container_present = "current_margin_windows" in snapshot
    windows = snapshot.get("current_margin_windows")
    container_type = _diagnostic_value_type(
        windows,
        present=container_present,
    )
    rows: list[dict[str, Any]] = []
    structural_failures: list[dict[str, Any]] = []
    token_failures: list[dict[str, Any]] = []

    def result(
        *,
        row_count_bucket: str,
        classification: str,
        failing_policy_row_index: int | None,
        recognized_profile: str | None,
        failing_field: str | None,
        failing_value_type: str | None,
        include_rows: bool = False,
    ) -> dict[str, Any]:
        authority_fields = (
            {
                "pair_policy_mode": "exact_profile_state_pair",
                "r5_attempt_authority_granted": False,
                "r6_attempt_authority_granted": False,
            }
            if policy_version == "v3"
            else {"r5_attempt_authority_granted": False}
        )
        return {
            "schema_version": schema_version,
            "policy_id": policy_id,
            "source": "backend_rest_client.get_current_margin_window",
            "stage": "margin_collateral_validation",
            "field_path": "current_margin_windows",
            "enum_authority": (
                "official_coinbase_advanced_trade_api_docs"
            ),
            "profile_state_policy_authority": (
                "operator_defined_slice_2_preview_only_not_coinbase_documented"
            ),
            "profile_state_mapping_documented_by_coinbase": False,
            "eligibility_scope": "slice_2_preview_only",
            **authority_fields,
            "execution_allowed": False,
            "create_order_eligibility_granted": False,
            "later_live_eligibility_granted": False,
            "container_present": container_present,
            "container_type": container_type,
            "row_count_bucket": row_count_bucket,
            "expected_row_count": 2,
            "failing_policy_row_index": failing_policy_row_index,
            "recognized_profile": recognized_profile,
            "failing_field": failing_field,
            "failing_value_type": failing_value_type,
            "rows": sorted(
                rows if include_rows else [],
                key=lambda row: int(row["policy_row_index"]),
            ),
            "margin_window_policy_satisfied": classification == "ready",
            "classification": classification,
            "sanitized": True,
            "raw_response_included": False,
            "external_exception_text_included": False,
            "unknown_identifier_values_included": False,
        }

    if not container_present:
        return result(
            row_count_bucket="not_applicable",
            classification="missing_container",
            failing_policy_row_index=None,
            recognized_profile=None,
            failing_field="current_margin_windows",
            failing_value_type="missing",
        )
    if not isinstance(windows, list):
        return result(
            row_count_bucket="not_applicable",
            classification="non_list_container",
            failing_policy_row_index=None,
            recognized_profile=None,
            failing_field="current_margin_windows",
            failing_value_type=container_type,
        )
    row_count_bucket = {
        0: "zero",
        1: "one",
        2: "expected_two",
    }.get(len(windows), "more_than_two")
    if len(windows) != 2:
        return result(
            row_count_bucket=row_count_bucket,
            classification="unexpected_row_count",
            failing_policy_row_index=None,
            recognized_profile=None,
            failing_field="current_margin_windows",
            failing_value_type="sequence",
        )

    observed_profiles: set[str] = set()
    for item in windows:
        if not isinstance(item, Mapping):
            return result(
                row_count_bucket=row_count_bucket,
                classification="non_mapping_row",
                failing_policy_row_index=None,
                recognized_profile=None,
                failing_field="row",
                failing_value_type=_diagnostic_value_type(
                    item,
                    present=True,
                ),
            )
        window = dict(item)
        profile_present = "profile" in window
        profile = window.get("profile")
        profile_type = _diagnostic_value_type(
            profile,
            present=profile_present,
        )
        if not profile_present:
            profile_classification = "profile_missing"
        elif profile is None:
            profile_classification = "profile_null"
        elif not isinstance(profile, str):
            profile_classification = "profile_non_string"
        elif (
            profile != profile.strip()
            or _SAFE_MARGIN_WINDOW_TOKEN.fullmatch(profile) is None
        ):
            profile_classification = "profile_malformed_string"
        elif profile not in operator_policy:
            profile_classification = "profile_unrecognized_enum_token"
        else:
            profile_classification = "ready"
        if profile_classification != "ready":
            return result(
                row_count_bucket=row_count_bucket,
                classification=profile_classification,
                failing_policy_row_index=None,
                recognized_profile=None,
                failing_field="profile",
                failing_value_type=profile_type,
            )
        recognized_profile = FUTURES_PREVIEW_EXPECTED_MARGIN_PROFILES[profile]
        policy_row_index = (
            _FUTURES_PREVIEW_SLICE2_MARGIN_PROFILE_POLICY_INDEX[profile]
        )
        if profile in observed_profiles:
            return result(
                row_count_bucket=row_count_bucket,
                classification="duplicate_profile",
                failing_policy_row_index=policy_row_index,
                recognized_profile=recognized_profile,
                failing_field="profile",
                failing_value_type="string",
            )
        observed_profiles.add(profile)

        status_present = "status" in window
        status = window.get("status")
        status_type = _diagnostic_value_type(status, present=status_present)
        if not status_present:
            status_classification = "status_missing"
        elif status is None:
            status_classification = "status_null"
        elif not isinstance(status, str):
            status_classification = "status_non_string"
        elif status != "ready":
            status_classification = "status_not_ready"
        else:
            status_classification = "ready"
        if status_classification != "ready":
            structural_failures.append(
                {
                    "policy_row_index": policy_row_index,
                    "classification": status_classification,
                    "recognized_profile": recognized_profile,
                    "failing_field": "status",
                    "failing_value_type": status_type,
                }
            )
            continue

        margin_window_present = "margin_window" in window
        margin_window = window.get("margin_window")
        margin_window_type = _diagnostic_value_type(
            margin_window,
            present=margin_window_present,
        )
        if not margin_window_present:
            container_classification = "margin_window_missing"
        elif margin_window is None:
            container_classification = "margin_window_null"
        elif not isinstance(margin_window, Mapping):
            container_classification = "margin_window_non_mapping"
        else:
            container_classification = "ready"
        if container_classification != "ready":
            structural_failures.append(
                {
                    "policy_row_index": policy_row_index,
                    "classification": container_classification,
                    "recognized_profile": recognized_profile,
                    "failing_field": "margin_window",
                    "failing_value_type": margin_window_type,
                }
            )
            continue

        margin_window_mapping = dict(margin_window)
        token_present = "margin_window_type" in margin_window_mapping
        token = margin_window_mapping.get("margin_window_type")
        token_type = _diagnostic_value_type(token, present=token_present)
        token_is_documented = (
            isinstance(token, str)
            and token in FUTURES_PREVIEW_DOCUMENTED_CURRENT_MARGIN_WINDOW_TYPES
        )
        operator_policy_match = (
            token_is_documented
            and token
            in operator_policy[profile]
        )
        observed_token = token if token_is_documented else None
        if not token_present:
            token_classification = "margin_window_type_missing"
        elif token is None:
            token_classification = "margin_window_type_null"
        elif not isinstance(token, str):
            token_classification = "margin_window_type_non_string"
        elif operator_policy_match:
            token_classification = "ready"
        elif token_is_documented:
            token_classification = (
                "margin_window_type_documented_but_operator_rejected"
            )
        else:
            token_classification = (
                "margin_window_type_undocumented_or_malformed"
            )
        if operator_policy_match:
            row_classification = "accepted"
        elif token_is_documented:
            row_classification = "documented_but_operator_rejected"
        else:
            row_classification = "undocumented_or_malformed"
        rows.append(
            {
                "policy_row_index": policy_row_index,
                "recognized_profile": recognized_profile,
                "observed_token": observed_token,
                "documented_allowlist_match": token_is_documented,
                "operator_policy_match": operator_policy_match,
                "classification": row_classification,
            }
        )
        if token_classification != "ready":
            token_failures.append(
                {
                    "policy_row_index": policy_row_index,
                    "classification": token_classification,
                    "recognized_profile": recognized_profile,
                    "failing_value_type": token_type,
                }
            )

    if observed_profiles != set(
        operator_policy
    ):
        return result(
            row_count_bucket=row_count_bucket,
            classification="expected_profile_set_incomplete",
            failing_policy_row_index=None,
            recognized_profile=None,
            failing_field="expected_profile_set",
            failing_value_type=None,
        )
    if structural_failures:
        failure = min(
            structural_failures,
            key=lambda item: int(item["policy_row_index"]),
        )
        return result(
            row_count_bucket=row_count_bucket,
            classification=str(failure["classification"]),
            failing_policy_row_index=int(failure["policy_row_index"]),
            recognized_profile=str(failure["recognized_profile"]),
            failing_field=str(failure["failing_field"]),
            failing_value_type=str(failure["failing_value_type"]),
        )
    if token_failures:
        failure = min(
            token_failures,
            key=lambda item: int(item["policy_row_index"]),
        )
        return result(
            row_count_bucket=row_count_bucket,
            classification=str(failure["classification"]),
            failing_policy_row_index=int(failure["policy_row_index"]),
            recognized_profile=str(failure["recognized_profile"]),
            failing_field="margin_window_type",
            failing_value_type=str(failure["failing_value_type"]),
            include_rows=True,
        )
    return result(
        row_count_bucket=row_count_bucket,
        classification="ready",
        failing_policy_row_index=None,
        recognized_profile=None,
        failing_field=None,
        failing_value_type=None,
        include_rows=True,
    )


def _diagnostic_value_type(value: Any, *, present: bool) -> str:
    if not present:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float, Decimal)):
        return "number"
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return "sequence"
    return "other"


def _preview_request(candidate: Mapping[str, str]) -> dict[str, Any]:
    return {
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "side": "BUY",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": candidate["limit_price"],
                "post_only": True,
            }
        },
    }


def _seal_ready_plan(
    *,
    claim: Mapping[str, Any],
    binding: Mapping[str, Any],
    candidate: Mapping[str, Any],
    preview_request: Mapping[str, Any],
    preview_response: Mapping[str, Any],
    permissions: Any,
    portfolios: Any,
    product: Any,
    book: Any,
    positions: Any,
    margin_collateral: Any,
) -> dict[str, Any]:
    """Build the canonical fixed plan object suitable for later sealing."""

    sanitized_margin = _sanitized_margin_collateral_evidence(margin_collateral)
    product_hash_source = (
        _sanitized_product_evidence(product)
        if claim["artifact_type"] in _SANITIZED_PREVIEW_ARTIFACT_TYPES
        else product
    )
    market_hash_source = (
        _sanitized_market_evidence(book)
        if claim["artifact_type"] in _SANITIZED_PREVIEW_ARTIFACT_TYPES
        else book
    )
    permission_hash_source = (
        _sanitized_permission_evidence(binding)
        if claim["artifact_type"] in _SANITIZED_PREVIEW_ARTIFACT_TYPES
        else permissions
    )
    portfolio_hash_source = (
        _sanitized_portfolio_catalog_evidence(binding)
        if claim["artifact_type"] in _SANITIZED_PREVIEW_ARTIFACT_TYPES
        else portfolios
    )
    position_hash_source = (
        _sanitized_position_evidence(positions)
        if claim["artifact_type"] in _SANITIZED_PREVIEW_ARTIFACT_TYPES
        else positions
    )
    margin_hash_source = (
        sanitized_margin
        if claim["artifact_type"] in _SANITIZED_PREVIEW_ARTIFACT_TYPES
        else margin_collateral
    )
    liquidation_source = str(preview_response["liquidation_evidence_source"])
    if liquidation_source == "current_and_projected_liquidation_buffer":
        liquidation_evidence = {
            "current_liquidation_buffer": preview_response[
                "current_liquidation_buffer"
            ],
            "projected_liquidation_buffer": preview_response[
                "projected_liquidation_buffer"
            ],
        }
    else:
        liquidation_evidence = {
            "margin_ratio_data": _mapping(preview_response["margin_ratio_data"]),
        }
        if "predicted_liquidation_price" in preview_response:
            liquidation_evidence["predicted_liquidation_price"] = (
                preview_response["predicted_liquidation_price"]
            )
    plan = {
        "schema_version": _SCHEMA_VERSION,
        "slice_id": claim["artifact_type"],
        "actor_id": claim["actor_id"],
        "roles": list(claim["roles"]),
        "correlation_id": claim["correlation_id"],
        "idempotency_key": claim["idempotency_key"],
        "predecessor_binding": dict(claim["predecessor_binding"]),
        "profile_binding": {
            "profile_label": "Default",
            "portfolio_type": "DEFAULT",
            "portfolio_id": binding.get("observed_portfolio_id"),
            "selection_authority": "cdp_api_key_permissioned_portfolio",
            "request_portfolio_override_allowed": False,
        },
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "contract_count": "1",
        "candidate": dict(candidate),
        "preview_request": dict(preview_request),
        "preview_request_sha256": canonical_sha256(preview_request),
        "authoritative_preview": {
            "preview_id": preview_response["preview_id"],
            "preview_response": dict(preview_response),
            "preview_response_sha256": canonical_sha256(preview_response),
            "candidate_binding": dict(preview_response["candidate_binding"]),
            "commission_total": preview_response["commission_total"],
            "order_margin_total": preview_response["order_margin_total"],
            "liquidation_evidence_source": liquidation_source,
            "liquidation_evidence": liquidation_evidence,
            "margin_collateral_evidence_sha256": canonical_sha256(
                sanitized_margin
            ),
        },
        "caps": dict(claim["caps"]),
        "attempt_policy": {
            "preview_order": 1,
            "retry": 0,
            "fallback": 0,
            "create_order": 0,
            "cancel_order": 0,
            "close_position": 0,
            "reduce_position": 0,
        },
        "preflight_evidence_hashes": {
            "permissions": canonical_sha256(permission_hash_source),
            "portfolio_catalog": canonical_sha256(portfolio_hash_source),
            "product": canonical_sha256(product_hash_source),
            "market": canonical_sha256(market_hash_source),
            "positions": canonical_sha256(position_hash_source),
            "margin_collateral": canonical_sha256(margin_hash_source),
        },
        "no_live_posture": {
            "order_creation_authorized": False,
            "order_cancellation_authorized": False,
            "position_close_authorized": False,
            "position_reduce_authorized": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "execution_marker_created": False,
            "attempt_ledger_created": False,
            "runtime_created": False,
        },
        "canonicalization": "sorted_keys_compact_utf8_json",
        "hash_algorithm": "sha256",
    }
    if claim["artifact_type"] == _R5_ARTIFACT_TYPE:
        policy_context = slice2_preview_margin_windows_policy_context(
            margin_collateral
        )
        plan["preflight_evidence_hashes"][
            "margin_windows_policy_evidence"
        ] = policy_context["margin_windows_policy_evidence_sha256"]
    elif claim["artifact_type"] in _V3_MARGIN_WINDOW_ARTIFACT_TYPES:
        policy_context = slice2_preview_margin_windows_pair_policy_context(
            margin_collateral
        )
        plan["preflight_evidence_hashes"][
            "margin_windows_policy_evidence"
        ] = policy_context["margin_windows_policy_evidence_sha256"]
        plan["margin_window_policy_binding"] = deepcopy(
            claim["margin_window_policy_binding"]
        )
    if claim["artifact_type"] in _CORRECTED_RESPONSE_SCHEMA_ARTIFACT_TYPES:
        plan["preview_response_schema_binding"] = deepcopy(
            claim["preview_response_schema_binding"]
        )
    if claim["artifact_type"] in _POST_PREVIEW_DIAGNOSTIC_ARTIFACT_TYPES:
        plan["post_preview_diagnostic_binding"] = deepcopy(
            claim["post_preview_diagnostic_binding"]
        )
    return plan


def _zero_attempt_counters() -> dict[str, int]:
    return {
        "preview_order": 0,
        "retry": 0,
        "fallback": 0,
        "create_order": 0,
        "cancel_order": 0,
        "close_position": 0,
        "reduce_position": 0,
    }


def _validate_r5_claim_record(claim: Mapping[str, Any]) -> None:
    """Reject any authority or scope drift in the one-use R5 claim."""

    correlation_id = claim.get("correlation_id")
    idempotency_key = claim.get("idempotency_key")
    try:
        parsed_correlation_id = UUID(correlation_id)
        parsed_idempotency_key = UUID(idempotency_key)
    except (AttributeError, TypeError, ValueError) as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R5 claim identifier is invalid"
        ) from exc
    if (
        parsed_correlation_id.version != 4
        or parsed_idempotency_key.version != 4
        or str(parsed_correlation_id) != correlation_id
        or str(parsed_idempotency_key) != idempotency_key
        or correlation_id == idempotency_key
        or _preview_identifier_was_consumed(
            correlation_id,
            artifact_type=_R5_ARTIFACT_TYPE,
        )
        or _preview_identifier_was_consumed(
            idempotency_key,
            artifact_type=_R5_ARTIFACT_TYPE,
        )
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R5 claim identifier is invalid"
        )
    reserved_at = claim.get("reserved_at")
    try:
        parsed_reserved_at = datetime.fromisoformat(
            str(reserved_at).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R5 claim timestamp is invalid"
        ) from exc
    if (
        not isinstance(reserved_at, str)
        or parsed_reserved_at.tzinfo is None
        or _timestamp(parsed_reserved_at) != reserved_at
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R5 claim timestamp is invalid"
        )

    expected_keys = {
        "artifact_type",
        "claim_status",
        "predecessor_binding",
        "reserved_at",
        "actor_id",
        "roles",
        "correlation_id",
        "idempotency_key",
        "profile_label",
        "portfolio_type",
        "product_id",
        "contract_count",
        "caps",
        "allowed_coinbase_methods",
        "preview_order_attempt_max",
        "retry_attempt_max",
        "fallback_attempt_max",
        "create_order_attempt_max",
        "cancel_order_attempt_max",
        "close_position_attempt_max",
        "reduce_position_attempt_max",
        "marker_created",
        "ledger_created",
        "runtime_created",
    }
    if (
        set(claim) != expected_keys
        or claim.get("artifact_type") != _R5_ARTIFACT_TYPE
        or claim.get("claim_status") != "reserved"
        or claim.get("predecessor_binding")
        not in (
            _FUTURES_PREVIEW_EC2_R4_BINDING,
            FUTURES_PREVIEW_R4_PREDECESSOR_BINDING,
        )
        or claim.get("actor_id") != FUTURES_PREVIEW_ACTOR_ID
        or claim.get("roles") != [FUTURES_PREVIEW_ROLE]
        or claim.get("profile_label") != "Default"
        or claim.get("portfolio_type") != "DEFAULT"
        or claim.get("product_id") != FUTURES_PREVIEW_PRODUCT_ID
        or claim.get("contract_count") != "1"
        or claim.get("caps")
        != {
            "opening_reference_notional_usdc": "100",
            "concurrent_exposure_usdc": "150",
            "buffered_close_reference_notional_usdc": "150",
            "branch_turnover_reference_notional_usdc": "300",
            "close_buffer_multiplier": "1.20",
            "comparison": "strictly_less_than",
        }
        or claim.get("allowed_coinbase_methods")
        != [
            "get_api_key_permissions",
            "list_portfolios",
            "get_product_dict",
            "get_best_bid_ask",
            "get_futures_positions",
            "get_futures_margin_collateral_snapshot",
            "preview_order",
        ]
        or claim.get("preview_order_attempt_max") != 1
        or any(
            claim.get(key) != expected
            for key, expected in {
                "retry_attempt_max": 0,
                "fallback_attempt_max": 0,
                "create_order_attempt_max": 0,
                "cancel_order_attempt_max": 0,
                "close_position_attempt_max": 0,
                "reduce_position_attempt_max": 0,
                "marker_created": False,
                "ledger_created": False,
                "runtime_created": False,
            }.items()
        )
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R5 claim authority is invalid"
        )


def _validate_r6_claim_record(claim: Mapping[str, Any]) -> None:
    """Reject scope, ancestry, policy, or identifier drift in an R6 claim."""

    correlation_id = claim.get("correlation_id")
    idempotency_key = claim.get("idempotency_key")
    try:
        parsed_correlation_id = UUID(correlation_id)
        parsed_idempotency_key = UUID(idempotency_key)
    except (AttributeError, TypeError, ValueError) as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R6 claim identifier is invalid"
        ) from exc
    if (
        parsed_correlation_id.version != 4
        or parsed_idempotency_key.version != 4
        or str(parsed_correlation_id) != correlation_id
        or str(parsed_idempotency_key) != idempotency_key
        or correlation_id == idempotency_key
        or _preview_identifier_was_consumed(
            correlation_id,
            artifact_type=_R6_ARTIFACT_TYPE,
        )
        or _preview_identifier_was_consumed(
            idempotency_key,
            artifact_type=_R6_ARTIFACT_TYPE,
        )
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R6 claim identifier is invalid"
        )
    reserved_at = claim.get("reserved_at")
    try:
        parsed_reserved_at = datetime.fromisoformat(
            str(reserved_at).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R6 claim timestamp is invalid"
        ) from exc
    if (
        not isinstance(reserved_at, str)
        or parsed_reserved_at.tzinfo is None
        or _timestamp(parsed_reserved_at) != reserved_at
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R6 claim timestamp is invalid"
        )

    expected_keys = {
        "artifact_type",
        "claim_status",
        "predecessor_binding",
        "reserved_at",
        "actor_id",
        "roles",
        "correlation_id",
        "idempotency_key",
        "profile_label",
        "portfolio_type",
        "product_id",
        "contract_count",
        "caps",
        "allowed_coinbase_methods",
        "preview_order_attempt_max",
        "retry_attempt_max",
        "fallback_attempt_max",
        "create_order_attempt_max",
        "cancel_order_attempt_max",
        "close_position_attempt_max",
        "reduce_position_attempt_max",
        "marker_created",
        "ledger_created",
        "runtime_created",
        "margin_window_policy_binding",
    }
    if (
        set(claim) != expected_keys
        or claim.get("artifact_type") != _R6_ARTIFACT_TYPE
        or claim.get("claim_status") != "reserved"
        or claim.get("predecessor_binding")
        != FUTURES_PREVIEW_R5_TERMINAL_BINDING
        or claim.get("margin_window_policy_binding")
        != FUTURES_PREVIEW_R6_MARGIN_WINDOW_POLICY_BINDING
        or claim.get("actor_id") != FUTURES_PREVIEW_ACTOR_ID
        or claim.get("roles") != [FUTURES_PREVIEW_ROLE]
        or claim.get("profile_label") != "Default"
        or claim.get("portfolio_type") != "DEFAULT"
        or claim.get("product_id") != FUTURES_PREVIEW_PRODUCT_ID
        or claim.get("contract_count") != "1"
        or claim.get("caps")
        != {
            "opening_reference_notional_usdc": "100",
            "concurrent_exposure_usdc": "150",
            "buffered_close_reference_notional_usdc": "150",
            "branch_turnover_reference_notional_usdc": "300",
            "close_buffer_multiplier": "1.20",
            "comparison": "strictly_less_than",
        }
        or claim.get("allowed_coinbase_methods")
        != [
            "get_api_key_permissions",
            "list_portfolios",
            "get_product_dict",
            "get_best_bid_ask",
            "get_futures_positions",
            "get_futures_margin_collateral_snapshot",
            "preview_order",
        ]
        or claim.get("preview_order_attempt_max") != 1
        or any(
            claim.get(key) != expected
            for key, expected in {
                "retry_attempt_max": 0,
                "fallback_attempt_max": 0,
                "create_order_attempt_max": 0,
                "cancel_order_attempt_max": 0,
                "close_position_attempt_max": 0,
                "reduce_position_attempt_max": 0,
                "marker_created": False,
                "ledger_created": False,
                "runtime_created": False,
            }.items()
        )
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R6 claim authority is invalid"
        )


def _validate_r7_claim_record(claim: Mapping[str, Any]) -> None:
    """Reject any R7 drift while preserving the exact R6 V3 scope."""

    expected_r7_keys = {
        "artifact_type",
        "claim_status",
        "predecessor_binding",
        "reserved_at",
        "actor_id",
        "roles",
        "correlation_id",
        "idempotency_key",
        "profile_label",
        "portfolio_type",
        "product_id",
        "contract_count",
        "caps",
        "allowed_coinbase_methods",
        "preview_order_attempt_max",
        "retry_attempt_max",
        "fallback_attempt_max",
        "create_order_attempt_max",
        "cancel_order_attempt_max",
        "close_position_attempt_max",
        "reduce_position_attempt_max",
        "marker_created",
        "ledger_created",
        "runtime_created",
        "margin_window_policy_binding",
        "preview_response_schema_binding",
    }
    correlation_id = claim.get("correlation_id")
    idempotency_key = claim.get("idempotency_key")
    if (
        set(claim) != expected_r7_keys
        or claim.get("artifact_type") != _R7_ARTIFACT_TYPE
        or claim.get("predecessor_binding")
        != FUTURES_PREVIEW_R6_TERMINAL_BINDING
        or claim.get("margin_window_policy_binding")
        != FUTURES_PREVIEW_R6_MARGIN_WINDOW_POLICY_BINDING
        or claim.get("preview_response_schema_binding")
        != FUTURES_PREVIEW_R7_RESPONSE_SCHEMA_BINDING
        or _preview_identifier_was_consumed(
            correlation_id,
            artifact_type=_R7_ARTIFACT_TYPE,
        )
        or _preview_identifier_was_consumed(
            idempotency_key,
            artifact_type=_R7_ARTIFACT_TYPE,
        )
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R7 claim authority is invalid"
        )

    r6_equivalent = dict(claim)
    r6_equivalent.pop("preview_response_schema_binding")
    r6_equivalent["artifact_type"] = _R6_ARTIFACT_TYPE
    r6_equivalent["predecessor_binding"] = FUTURES_PREVIEW_R5_TERMINAL_BINDING
    try:
        _validate_r6_claim_record(r6_equivalent)
    except FuturesOrderPreviewArtifactError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R7 claim authority is invalid"
        ) from exc


def _validate_r8_ephemeral_claim_record(claim: Mapping[str, Any]) -> None:
    """Reject in-memory R8 drift before private trace identifiers are withheld."""

    expected_r8_keys = {
        "artifact_type",
        "claim_status",
        "predecessor_binding",
        "reserved_at",
        "actor_id",
        "roles",
        "correlation_id",
        "idempotency_key",
        "profile_label",
        "portfolio_type",
        "product_id",
        "contract_count",
        "caps",
        "allowed_coinbase_methods",
        "preview_order_attempt_max",
        "retry_attempt_max",
        "fallback_attempt_max",
        "create_order_attempt_max",
        "cancel_order_attempt_max",
        "close_position_attempt_max",
        "reduce_position_attempt_max",
        "marker_created",
        "ledger_created",
        "runtime_created",
        "margin_window_policy_binding",
        "preview_response_schema_binding",
        "post_preview_diagnostic_binding",
    }
    correlation_id = claim.get("correlation_id")
    idempotency_key = claim.get("idempotency_key")
    if (
        set(claim) != expected_r8_keys
        or claim.get("artifact_type") != _R8_ARTIFACT_TYPE
        or claim.get("predecessor_binding")
        != FUTURES_PREVIEW_R7_TERMINAL_BINDING
        or claim.get("margin_window_policy_binding")
        != FUTURES_PREVIEW_R6_MARGIN_WINDOW_POLICY_BINDING
        or claim.get("preview_response_schema_binding")
        != FUTURES_PREVIEW_R7_RESPONSE_SCHEMA_BINDING
        or claim.get("post_preview_diagnostic_binding")
        != FUTURES_PREVIEW_R8_POST_PREVIEW_DIAGNOSTIC_BINDING
        or _preview_identifier_was_consumed(
            correlation_id,
            artifact_type=_R8_ARTIFACT_TYPE,
        )
        or _preview_identifier_was_consumed(
            idempotency_key,
            artifact_type=_R8_ARTIFACT_TYPE,
        )
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 claim authority is invalid"
        )

    r7_equivalent = dict(claim)
    r7_equivalent.pop("post_preview_diagnostic_binding")
    r7_equivalent["artifact_type"] = _R7_ARTIFACT_TYPE
    r7_equivalent["predecessor_binding"] = FUTURES_PREVIEW_R6_TERMINAL_BINDING
    try:
        _validate_r7_claim_record(r7_equivalent)
    except FuturesOrderPreviewArtifactError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 claim authority is invalid"
        ) from exc


def _validate_r8_claim_record(claim: Mapping[str, Any]) -> None:
    """Validate the persistence-safe R8 claim without raw identifiers."""

    expected_keys = {
        "artifact_type",
        "claim_status",
        "predecessor_binding",
        "reserved_at",
        "actor_id",
        "roles",
        "correlation_id",
        "correlation_id_sha256",
        "idempotency_key",
        "idempotency_key_sha256",
        "profile_label",
        "portfolio_type",
        "product_id",
        "contract_count",
        "caps",
        "allowed_coinbase_methods",
        "preview_order_attempt_max",
        "retry_attempt_max",
        "fallback_attempt_max",
        "create_order_attempt_max",
        "cancel_order_attempt_max",
        "close_position_attempt_max",
        "reduce_position_attempt_max",
        "marker_created",
        "ledger_created",
        "runtime_created",
        "margin_window_policy_binding",
        "preview_response_schema_binding",
        "post_preview_diagnostic_binding",
    }
    correlation_sha256 = claim.get("correlation_id_sha256")
    idempotency_sha256 = claim.get("idempotency_key_sha256")
    if (
        set(claim) != expected_keys
        or claim.get("correlation_id") != "withheld"
        or claim.get("idempotency_key") != "withheld"
        or not isinstance(correlation_sha256, str)
        or not isinstance(idempotency_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", correlation_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", idempotency_sha256) is None
        or correlation_sha256 == idempotency_sha256
        or correlation_sha256 in _R7_CONSUMED_PREVIEW_IDENTIFIER_SHA256
        or idempotency_sha256 in _R7_CONSUMED_PREVIEW_IDENTIFIER_SHA256
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 claim authority is invalid"
        )
    equivalent = dict(claim)
    equivalent.pop("correlation_id_sha256")
    equivalent.pop("idempotency_key_sha256")
    equivalent["correlation_id"] = "00000000-0000-4000-8000-000000000801"
    equivalent["idempotency_key"] = "00000000-0000-4000-8000-000000000802"
    _validate_r8_ephemeral_claim_record(equivalent)


def _validate_r9_ephemeral_claim_record(claim: Mapping[str, Any]) -> None:
    """Reject in-memory R9 drift from the corrected bounded Preview scope."""

    if (
        claim.get("artifact_type") != _R9_ARTIFACT_TYPE
        or claim.get("predecessor_binding")
        != FUTURES_PREVIEW_R8_TERMINAL_BINDING
        or _preview_identifier_was_consumed(
            claim.get("correlation_id"),
            artifact_type=_R9_ARTIFACT_TYPE,
        )
        or _preview_identifier_was_consumed(
            claim.get("idempotency_key"),
            artifact_type=_R9_ARTIFACT_TYPE,
        )
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R9 claim authority is invalid"
        )
    r8_equivalent = dict(claim)
    r8_equivalent["artifact_type"] = _R8_ARTIFACT_TYPE
    r8_equivalent["predecessor_binding"] = FUTURES_PREVIEW_R7_TERMINAL_BINDING
    try:
        _validate_r8_ephemeral_claim_record(r8_equivalent)
    except FuturesOrderPreviewArtifactError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R9 claim authority is invalid"
        ) from exc


def _validate_r9_claim_record(claim: Mapping[str, Any]) -> None:
    """Validate a persistence-safe R9 claim without raw trace identifiers."""

    correlation_sha256 = claim.get("correlation_id_sha256")
    idempotency_sha256 = claim.get("idempotency_key_sha256")
    if (
        claim.get("artifact_type") != _R9_ARTIFACT_TYPE
        or claim.get("predecessor_binding")
        != FUTURES_PREVIEW_R8_TERMINAL_BINDING
        or claim.get("correlation_id") != "withheld"
        or claim.get("idempotency_key") != "withheld"
        or not isinstance(correlation_sha256, str)
        or not isinstance(idempotency_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", correlation_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", idempotency_sha256) is None
        or correlation_sha256 == idempotency_sha256
        or correlation_sha256 in _R7_CONSUMED_PREVIEW_IDENTIFIER_SHA256
        or idempotency_sha256 in _R7_CONSUMED_PREVIEW_IDENTIFIER_SHA256
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R9 claim authority is invalid"
        )
    equivalent = dict(claim)
    equivalent.pop("correlation_id_sha256", None)
    equivalent.pop("idempotency_key_sha256", None)
    equivalent["correlation_id"] = "00000000-0000-4000-8000-000000000901"
    equivalent["idempotency_key"] = "00000000-0000-4000-8000-000000000902"
    _validate_r9_ephemeral_claim_record(equivalent)


def _validate_r10_ephemeral_claim_record(claim: Mapping[str, Any]) -> None:
    """Reject in-memory R10 drift from its immutable R9 predecessor."""

    if (
        claim.get("artifact_type") != _R10_ARTIFACT_TYPE
        or claim.get("predecessor_binding")
        != FUTURES_PREVIEW_R9_TERMINAL_BINDING
        or claim.get("preview_response_schema_binding")
        != FUTURES_PREVIEW_R10_RESPONSE_SCHEMA_BINDING
        or claim.get("post_preview_diagnostic_binding")
        != FUTURES_PREVIEW_R10_POST_PREVIEW_DIAGNOSTIC_BINDING
        or _preview_identifier_was_consumed(
            claim.get("correlation_id"),
            artifact_type=_R10_ARTIFACT_TYPE,
        )
        or _preview_identifier_was_consumed(
            claim.get("idempotency_key"),
            artifact_type=_R10_ARTIFACT_TYPE,
        )
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R10 claim authority is invalid"
        )
    r9_equivalent = dict(claim)
    r9_equivalent["artifact_type"] = _R9_ARTIFACT_TYPE
    r9_equivalent["predecessor_binding"] = FUTURES_PREVIEW_R8_TERMINAL_BINDING
    r9_equivalent["preview_response_schema_binding"] = (
        FUTURES_PREVIEW_R7_RESPONSE_SCHEMA_BINDING
    )
    r9_equivalent["post_preview_diagnostic_binding"] = (
        FUTURES_PREVIEW_R8_POST_PREVIEW_DIAGNOSTIC_BINDING
    )
    try:
        _validate_r9_ephemeral_claim_record(r9_equivalent)
    except FuturesOrderPreviewArtifactError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R10 claim authority is invalid"
        ) from exc


def _validate_r10_claim_record(claim: Mapping[str, Any]) -> None:
    """Validate a persistence-safe R10 claim without raw identifiers."""

    correlation_sha256 = claim.get("correlation_id_sha256")
    idempotency_sha256 = claim.get("idempotency_key_sha256")
    if (
        claim.get("artifact_type") != _R10_ARTIFACT_TYPE
        or claim.get("predecessor_binding")
        != FUTURES_PREVIEW_R9_TERMINAL_BINDING
        or claim.get("correlation_id") != "withheld"
        or claim.get("idempotency_key") != "withheld"
        or not isinstance(correlation_sha256, str)
        or not isinstance(idempotency_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", correlation_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", idempotency_sha256) is None
        or correlation_sha256 == idempotency_sha256
        or correlation_sha256 in _R10_CONSUMED_PREVIEW_IDENTIFIER_SHA256
        or idempotency_sha256 in _R10_CONSUMED_PREVIEW_IDENTIFIER_SHA256
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R10 claim authority is invalid"
        )
    equivalent = dict(claim)
    equivalent.pop("correlation_id_sha256", None)
    equivalent.pop("idempotency_key_sha256", None)
    equivalent["correlation_id"] = "00000000-0000-4000-8000-000000001001"
    equivalent["idempotency_key"] = "00000000-0000-4000-8000-000000001002"
    _validate_r10_ephemeral_claim_record(equivalent)


def _validate_r11_ephemeral_claim_record(claim: Mapping[str, Any]) -> None:
    """Reject in-memory R11 drift from R10 or the audited V3 policy."""

    if (
        claim.get("artifact_type") != _R11_ARTIFACT_TYPE
        or claim.get("predecessor_binding")
        != FUTURES_PREVIEW_R10_TERMINAL_BINDING
        or claim.get("preview_response_schema_binding")
        != FUTURES_PREVIEW_R11_RESPONSE_SCHEMA_BINDING
        or claim.get("post_preview_diagnostic_binding")
        != FUTURES_PREVIEW_R11_POST_PREVIEW_DIAGNOSTIC_BINDING
        or _preview_identifier_was_consumed(
            claim.get("correlation_id"),
            artifact_type=_R11_ARTIFACT_TYPE,
        )
        or _preview_identifier_was_consumed(
            claim.get("idempotency_key"),
            artifact_type=_R11_ARTIFACT_TYPE,
        )
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 claim authority is invalid"
        )
    r10_equivalent = dict(claim)
    r10_equivalent["artifact_type"] = _R10_ARTIFACT_TYPE
    r10_equivalent["predecessor_binding"] = FUTURES_PREVIEW_R9_TERMINAL_BINDING
    r10_equivalent["preview_response_schema_binding"] = (
        FUTURES_PREVIEW_R10_RESPONSE_SCHEMA_BINDING
    )
    r10_equivalent["post_preview_diagnostic_binding"] = (
        FUTURES_PREVIEW_R10_POST_PREVIEW_DIAGNOSTIC_BINDING
    )
    try:
        _validate_r10_ephemeral_claim_record(r10_equivalent)
    except FuturesOrderPreviewArtifactError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 claim authority is invalid"
        ) from exc


def _validate_r11_claim_record(claim: Mapping[str, Any]) -> None:
    """Validate one persistence-safe R11 claim without raw identifiers."""

    correlation_sha256 = claim.get("correlation_id_sha256")
    idempotency_sha256 = claim.get("idempotency_key_sha256")
    if (
        claim.get("artifact_type") != _R11_ARTIFACT_TYPE
        or claim.get("predecessor_binding")
        != FUTURES_PREVIEW_R10_TERMINAL_BINDING
        or claim.get("preview_response_schema_binding")
        != FUTURES_PREVIEW_R11_RESPONSE_SCHEMA_BINDING
        or claim.get("post_preview_diagnostic_binding")
        != FUTURES_PREVIEW_R11_POST_PREVIEW_DIAGNOSTIC_BINDING
        or claim.get("correlation_id") != "withheld"
        or claim.get("idempotency_key") != "withheld"
        or not isinstance(correlation_sha256, str)
        or not isinstance(idempotency_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", correlation_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", idempotency_sha256) is None
        or correlation_sha256 == idempotency_sha256
        or correlation_sha256 in _R11_CONSUMED_PREVIEW_IDENTIFIER_SHA256
        or idempotency_sha256 in _R11_CONSUMED_PREVIEW_IDENTIFIER_SHA256
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 claim authority is invalid"
        )
    equivalent = dict(claim)
    equivalent.pop("correlation_id_sha256", None)
    equivalent.pop("idempotency_key_sha256", None)
    equivalent["correlation_id"] = "00000000-0000-4000-8000-000000001101"
    equivalent["idempotency_key"] = "00000000-0000-4000-8000-000000001102"
    _validate_r11_ephemeral_claim_record(equivalent)


def _zero_read_counters() -> dict[str, int]:
    return {
        "api_key_permissions": 0,
        "portfolio_catalog": 0,
        "product": 0,
        "best_bid_ask": 0,
        "futures_positions": 0,
        "futures_margin_collateral": 0,
    }


def _record_sha256(record: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in record.items() if key != "record_sha256"}
    )


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact write was incomplete"
            )
        view = view[written:]


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview artifact directory sync failed"
        ) from exc
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _mapping(value: Any) -> dict[str, Any]:
    normalized = _plain(value)
    return dict(normalized) if isinstance(normalized, Mapping) else {}


def _decimal(value: Any, name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"futures_preview_{name}_invalid") from exc


def _positive_decimal(value: Any, name: str) -> Decimal:
    result = _decimal(value, name)
    if not result.is_finite() or result <= 0:
        raise ValueError(f"futures_preview_{name}_invalid")
    return result


def _usd_money_value(value: Any, name: str) -> Decimal:
    money = _mapping(value)
    if money.get("currency") != "USD":
        raise ValueError(f"futures_preview_{name}_currency_invalid")
    result = _decimal(money.get("value"), name)
    if not result.is_finite() or result < 0:
        raise ValueError(f"futures_preview_{name}_invalid")
    return result


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _notional_text(value: Decimal) -> str:
    text = format(value, "f")
    whole, separator, fraction = text.partition(".")
    if not separator:
        return f"{whole}.00"
    trimmed_fraction = fraction.rstrip("0")
    if not trimmed_fraction:
        return f"{whole}.00"
    return f"{whole}.{trimmed_fraction.ljust(2, '0')}"


def _exact_pricebook(book: Mapping[str, Any]) -> dict[str, Any]:
    rows = book.get("pricebooks")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("futures_preview_pricebook_missing")
    matches = [
        _mapping(row)
        for row in rows
        if _mapping(row).get("product_id") == FUTURES_PREVIEW_PRODUCT_ID
    ]
    if len(matches) != 1:
        raise ValueError("futures_preview_pricebook_ambiguous")
    return matches[0]


def _top_price(pricebook: Mapping[str, Any], side: str) -> Decimal:
    levels = pricebook.get(side)
    if not isinstance(levels, Sequence) or not levels:
        raise ValueError(f"futures_preview_{side}_missing")
    return _positive_decimal(_mapping(levels[0]).get("price"), f"{side}_price")


def _validate_market_freshness(
    pricebook: Mapping[str, Any],
    observed_at: datetime,
) -> None:
    raw = str(pricebook.get("time") or "").strip()
    if not raw:
        raise ValueError("futures_preview_market_time_missing")
    try:
        market_time = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("futures_preview_market_time_invalid") from exc
    if market_time.tzinfo is None:
        raise ValueError("futures_preview_market_time_unzoned")
    age_seconds = (observed_at.astimezone(timezone.utc) - market_time.astimezone(timezone.utc)).total_seconds()
    if age_seconds < -5 or age_seconds > 30:
        raise ValueError("futures_preview_market_stale")


def _position_contracts(positions: Any, product_id: str) -> Decimal:
    normalized = _plain(positions)
    if isinstance(normalized, Mapping):
        candidate = normalized.get(product_id)
        rows = [candidate] if candidate is not None else []
    elif isinstance(normalized, Sequence) and not isinstance(
        normalized, (str, bytes, bytearray)
    ):
        rows = [
            row
            for row in normalized
            if _mapping(row).get("product_id") == product_id
        ]
    else:
        raise ValueError("futures_preview_positions_ambiguous")
    if len(rows) > 1:
        raise ValueError("futures_preview_positions_ambiguous")
    if not rows:
        return Decimal("0")
    row = _mapping(rows[0])
    return abs(
        _decimal(
            row.get("number_of_contracts", row.get("net_size", "0")),
            "position_contracts",
        )
    )


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping) or (
        isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray))
    ):
        return bool(value)
    return True


def _timestamp(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
