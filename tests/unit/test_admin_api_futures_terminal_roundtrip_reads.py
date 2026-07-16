from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
from threading import Event, Lock
import time
from typing import Any

import pytest

from application.admin_api.futures_terminal_roundtrip import Slice3ReadSlot
from application.admin_api.futures_terminal_roundtrip_reads import (
    SLICE3_MARGIN_FACADE_SOURCE_VECTOR,
    FileSlice3ReadJournal,
    Slice3ReadConsumedError,
    Slice3ReadDelegateError,
    Slice3ReadJournalError,
    Slice3ReadOutcome,
    Slice3ReadRecordEvent,
    configured_slice3_read_journal_path,
    slice3_read_declaration,
)


PLAN_SHA256 = "a" * 64
EVIDENCE_SHA256 = "b" * 64
PRIVATE_IDENTIFIER = "PRIVATE-CLIENT-ORDER-ID-READ-JOURNAL"
PRIVATE_RESPONSE = "PRIVATE-RAW-COINBASE-READ-RESPONSE"
PRIVATE_EXCEPTION = "PRIVATE-DELEGATE-EXCEPTION-TEXT"


@dataclass(frozen=True)
class _SyntheticEvidence:
    private_identifier: str = PRIVATE_IDENTIFIER
    private_response: str = PRIVATE_RESPONSE

    def sanitized_evidence(self) -> dict[str, object]:
        return {
            "schema_version": "synthetic-sanitized-evidence-v1",
            "private_identifier_sha256": hashlib.sha256(
                self.private_identifier.encode("utf-8")
            ).hexdigest(),
            "private_response_sha256": hashlib.sha256(
                self.private_response.encode("utf-8")
            ).hexdigest(),
            "raw_response_included": False,
            "identifier_values_included": False,
        }


def _journal(tmp_path: Path) -> FileSlice3ReadJournal:
    return FileSlice3ReadJournal(tmp_path / "slice3-read-journal.jsonl")


def _reserve_from_process(
    path: str,
    start: Any,
    results: Any,
) -> None:
    class _SlowAppendJournal(FileSlice3ReadJournal):
        def _append_locked(self, descriptor: int, record: Any) -> None:
            time.sleep(0.2)
            super()._append_locked(descriptor, record)

    assert start.wait(timeout=5)
    journal = _SlowAppendJournal(path)
    try:
        journal.reserve(
            plan_sha256=PLAN_SHA256,
            slot=Slice3ReadSlot.PRE_CREATE_POSITION,
            declaration=slice3_read_declaration(Slice3ReadSlot.PRE_CREATE_POSITION),
        )
    except Slice3ReadConsumedError:
        results.put("consumed")
    else:
        results.put("reserved")


def test_fixed_read_declarations_bind_subreads_and_margin_facade_vector() -> None:
    pre_open = slice3_read_declaration(Slice3ReadSlot.PRE_CREATE_OPEN_ORDERS)
    final_open = slice3_read_declaration(Slice3ReadSlot.FINAL_OPEN_ORDERS)
    pre_create_margin = slice3_read_declaration(Slice3ReadSlot.PRE_CREATE_MARGIN)
    margin = slice3_read_declaration(Slice3ReadSlot.FINAL_MARGIN)

    assert pre_open.slot_attempt_count == 1
    assert pre_open.subread_count == 1
    assert pre_open.source_vector == (("list_orders_active_transitional", 1),)
    assert final_open.subread_count == 1
    assert final_open.source_vector == pre_open.source_vector
    assert pre_create_margin.slot_attempt_count == 1
    assert pre_create_margin.subread_count == 5
    assert pre_create_margin.source_vector == (SLICE3_MARGIN_FACADE_SOURCE_VECTOR)
    assert margin.slot_attempt_count == 1
    assert margin.subread_count == 5
    assert margin.source_vector == SLICE3_MARGIN_FACADE_SOURCE_VECTOR
    assert margin.source_vector == (
        ("get_futures_balance_summary", 1),
        ("get_intraday_margin_setting", 1),
        ("get_current_margin_window", 2),
        ("list_futures_sweeps", 1),
    )
    assert {slice3_read_declaration(slot).slot for slot in Slice3ReadSlot} == set(
        Slice3ReadSlot
    )


def test_recovery_read_set_is_separate_finite_and_at_most_once() -> None:
    normal_slots = {
        Slice3ReadSlot.PRE_CREATE_OPEN_ORDERS,
        Slice3ReadSlot.PRE_CREATE_POSITION,
        Slice3ReadSlot.PRE_CREATE_MARGIN,
        Slice3ReadSlot.POST_CREATE_ORDER,
        Slice3ReadSlot.POST_CREATE_POSITION,
        Slice3ReadSlot.POST_CANCEL_TERMINAL_ORDER,
        Slice3ReadSlot.PRE_CLOSE_POSITION,
        Slice3ReadSlot.PRE_CLOSE_MARKET,
        Slice3ReadSlot.PRE_CLOSE_OPEN_ORDERS,
        Slice3ReadSlot.POST_CLOSE_ORDER,
        Slice3ReadSlot.FINAL_POSITION,
        Slice3ReadSlot.FINAL_OPEN_ORDERS,
        Slice3ReadSlot.FINAL_MARGIN,
    }
    recovery_slots = {
        Slice3ReadSlot.RECOVERY_OPENING_ORDER_BY_CLIENT_ID,
        Slice3ReadSlot.RECOVERY_POSITION,
        Slice3ReadSlot.RECOVERY_POST_CANCEL_TERMINAL_ORDER,
        Slice3ReadSlot.RECOVERY_POST_CANCEL_POSITION,
        Slice3ReadSlot.RECOVERY_MARKET,
        Slice3ReadSlot.RECOVERY_PRE_CLOSE_OPEN_ORDERS,
        Slice3ReadSlot.RECOVERY_CLOSE_ORDER_BY_CLIENT_ID,
        Slice3ReadSlot.RECOVERY_FINAL_POSITION,
        Slice3ReadSlot.RECOVERY_FINAL_OPEN_ORDERS,
        Slice3ReadSlot.RECOVERY_FINAL_MARGIN,
    }

    assert normal_slots.isdisjoint(recovery_slots)
    assert normal_slots | recovery_slots == set(Slice3ReadSlot)
    assert (
        sum(slice3_read_declaration(slot).subread_count for slot in normal_slots) == 21
    )
    assert (
        sum(slice3_read_declaration(slot).subread_count for slot in recovery_slots)
        == 14
    )
    assert (
        sum(slice3_read_declaration(slot).subread_count for slot in Slice3ReadSlot)
        == 35
    )
    assert all(
        slice3_read_declaration(slot).slot_attempt_count == 1 for slot in recovery_slots
    )


def test_configured_fixed_path_is_lazy_and_overrideable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = tmp_path / "fixed" / "slice3-reads.jsonl"
    monkeypatch.setenv("COINBASE_SLICE3_READ_JOURNAL_PATH", str(configured))

    assert configured_slice3_read_journal_path() == configured
    journal = FileSlice3ReadJournal()
    assert journal.path == configured
    assert not configured.exists()


def test_success_reserves_before_delegate_and_persists_hashes_only(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    slot = Slice3ReadSlot.PRE_CREATE_POSITION
    observed: list[str] = []

    def delegate() -> _SyntheticEvidence:
        record = journal.inspect(plan_sha256=PLAN_SHA256, slot=slot)
        assert record is not None
        assert record.event is Slice3ReadRecordEvent.BOUNDARY_RESERVED
        observed.append("delegate")
        return _SyntheticEvidence()

    result = journal.execute(
        plan_sha256=PLAN_SHA256,
        slot=slot,
        declaration=slice3_read_declaration(slot),
        delegate=delegate,
    )

    assert isinstance(result, _SyntheticEvidence)
    assert observed == ["delegate"]
    records = journal.read_all()
    assert [record.event for record in records] == [
        Slice3ReadRecordEvent.BOUNDARY_RESERVED,
        Slice3ReadRecordEvent.CONSUMED,
    ]
    assert records[1].outcome is Slice3ReadOutcome.SUCCEEDED
    assert records[1].reason_code == "read_succeeded"
    assert records[1].evidence_sha256 is not None
    assert records[0].previous_record_sha256 == "0" * 64
    assert records[1].previous_record_sha256 == records[0].record_sha256
    raw = journal.path.read_text(encoding="utf-8")
    assert PRIVATE_IDENTIFIER not in raw
    assert PRIVATE_RESPONSE not in raw
    assert "client_order_id" not in raw
    assert "preview_id" not in raw
    assert "raw_response" not in raw


def test_delegate_exception_consumes_slot_without_exception_text(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    slot = Slice3ReadSlot.POST_CREATE_ORDER
    calls = 0

    def delegate() -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError(PRIVATE_EXCEPTION)

    with pytest.raises(
        Slice3ReadDelegateError,
        match="^slice3_read_delegate_failed$",
    ) as captured:
        journal.execute(
            plan_sha256=PLAN_SHA256,
            slot=slot,
            declaration=slice3_read_declaration(slot),
            delegate=delegate,
        )

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert calls == 1
    terminal = journal.read_all()[-1]
    assert terminal.event is Slice3ReadRecordEvent.CONSUMED
    assert terminal.outcome is Slice3ReadOutcome.FAILED
    assert terminal.reason_code == "read_delegate_exception"
    assert terminal.evidence_sha256 is None
    raw = journal.path.read_text(encoding="utf-8")
    assert PRIVATE_EXCEPTION not in raw
    assert "RuntimeError" not in raw
    with pytest.raises(Slice3ReadConsumedError, match="slot_consumed"):
        journal.execute(
            plan_sha256=PLAN_SHA256,
            slot=slot,
            declaration=slice3_read_declaration(slot),
            delegate=delegate,
        )
    assert calls == 1


def test_invalid_evidence_hashing_consumes_without_persisting_value(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    slot = Slice3ReadSlot.POST_CREATE_POSITION
    private_result = {"raw": PRIVATE_RESPONSE}

    with pytest.raises(
        Slice3ReadDelegateError,
        match="^slice3_read_evidence_invalid$",
    ):
        journal.execute(
            plan_sha256=PLAN_SHA256,
            slot=slot,
            declaration=slice3_read_declaration(slot),
            delegate=lambda: private_result,
        )

    terminal = journal.read_all()[-1]
    assert terminal.outcome is Slice3ReadOutcome.FAILED
    assert terminal.reason_code == "read_evidence_invalid"
    assert PRIVATE_RESPONSE not in journal.path.read_text(encoding="utf-8")


def test_sanitizer_exception_is_discarded_before_fixed_terminal_error(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    slot = Slice3ReadSlot.PRE_CLOSE_POSITION

    class _BrokenEvidence:
        def sanitized_evidence(self) -> dict[str, object]:
            raise RuntimeError(PRIVATE_EXCEPTION)

    with pytest.raises(
        Slice3ReadDelegateError,
        match="^slice3_read_evidence_invalid$",
    ) as captured:
        journal.execute(
            plan_sha256=PLAN_SHA256,
            slot=slot,
            declaration=slice3_read_declaration(slot),
            delegate=_BrokenEvidence,
        )

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    terminal = journal.read_all()[-1]
    assert terminal.reason_code == "read_evidence_invalid"
    raw = journal.path.read_text(encoding="utf-8")
    assert PRIVATE_EXCEPTION not in raw
    assert "RuntimeError" not in raw


def test_crash_after_boundary_rejects_resume_and_never_calls_delegate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "slice3-read-journal.jsonl"
    slot = Slice3ReadSlot.POST_CANCEL_TERMINAL_ORDER
    first = FileSlice3ReadJournal(path)
    first.reserve(
        plan_sha256=PLAN_SHA256,
        slot=slot,
        declaration=slice3_read_declaration(slot),
    )
    resumed = FileSlice3ReadJournal(path)
    calls = 0

    def delegate() -> _SyntheticEvidence:
        nonlocal calls
        calls += 1
        return _SyntheticEvidence()

    with pytest.raises(Slice3ReadConsumedError, match="slot_consumed"):
        resumed.execute(
            plan_sha256=PLAN_SHA256,
            slot=slot,
            declaration=slice3_read_declaration(slot),
            delegate=delegate,
        )

    assert calls == 0
    records = resumed.read_all()
    assert len(records) == 1
    assert records[0].event is Slice3ReadRecordEvent.BOUNDARY_RESERVED

    recovered = resumed.recover_reserved_as_failed(
        plan_sha256=PLAN_SHA256,
        slot=slot,
        declaration=slice3_read_declaration(slot),
    )
    assert recovered.event is Slice3ReadRecordEvent.CONSUMED
    assert recovered.outcome is Slice3ReadOutcome.FAILED
    assert recovered.reason_code == "read_process_interrupted"
    assert recovered.evidence_sha256 is None
    repeated = resumed.recover_reserved_as_failed(
        plan_sha256=PLAN_SHA256,
        slot=slot,
        declaration=slice3_read_declaration(slot),
    )
    assert repeated == recovered
    assert len(resumed.read_all()) == 2


def test_concurrent_same_slot_executes_delegate_exactly_once(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    slot = Slice3ReadSlot.PRE_CLOSE_MARKET
    started = Event()
    release = Event()
    calls_lock = Lock()
    calls = 0

    def delegate() -> _SyntheticEvidence:
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        assert release.wait(timeout=5)
        return _SyntheticEvidence()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            journal.execute,
            plan_sha256=PLAN_SHA256,
            slot=slot,
            declaration=slice3_read_declaration(slot),
            delegate=delegate,
        )
        assert started.wait(timeout=5)
        second = executor.submit(
            journal.execute,
            plan_sha256=PLAN_SHA256,
            slot=slot,
            declaration=slice3_read_declaration(slot),
            delegate=delegate,
        )
        with pytest.raises(Slice3ReadConsumedError, match="slot_consumed"):
            second.result(timeout=5)
        release.set()
        assert isinstance(first.result(timeout=5), _SyntheticEvidence)

    assert calls == 1
    assert len(journal.read_all()) == 2


def test_processes_cannot_both_reserve_the_same_slot(tmp_path: Path) -> None:
    context = multiprocessing.get_context("fork")
    start = context.Event()
    results = context.Queue()
    path = str(tmp_path / "slice3-read-journal.jsonl")
    processes = [
        context.Process(
            target=_reserve_from_process,
            args=(path, start, results),
        )
        for _ in range(2)
    ]

    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=10)

    assert [process.exitcode for process in processes] == [0, 0]
    assert sorted(results.get(timeout=5) for _ in processes) == [
        "consumed",
        "reserved",
    ]
    records = FileSlice3ReadJournal(path).read_all()
    assert len(records) == 1
    assert records[0].event is Slice3ReadRecordEvent.BOUNDARY_RESERVED


def test_tampered_hash_chain_fails_closed(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    slot = Slice3ReadSlot.FINAL_POSITION
    journal.execute(
        plan_sha256=PLAN_SHA256,
        slot=slot,
        declaration=slice3_read_declaration(slot),
        delegate=_SyntheticEvidence,
    )
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["reason_code"] = "read_succeeded"
    lines[0] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    journal.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    journal.path.chmod(0o600)

    with pytest.raises(Slice3ReadJournalError, match="hash_chain_invalid"):
        journal.read_all()


def test_truncated_record_fails_closed(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    slot = Slice3ReadSlot.FINAL_OPEN_ORDERS
    journal.reserve(
        plan_sha256=PLAN_SHA256,
        slot=slot,
        declaration=slice3_read_declaration(slot),
    )
    with journal.path.open("ab") as stream:
        stream.write(b'{"partial":')
    journal.path.chmod(0o600)

    with pytest.raises(Slice3ReadJournalError, match="truncated"):
        journal.read_all()


def test_symlink_path_is_rejected_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target.jsonl"
    target.write_text(PRIVATE_RESPONSE, encoding="utf-8")
    target.chmod(0o600)
    path = tmp_path / "slice3-read-journal.jsonl"
    path.symlink_to(target)
    journal = FileSlice3ReadJournal(path)

    with pytest.raises(Slice3ReadJournalError, match="unsafe"):
        journal.reserve(
            plan_sha256=PLAN_SHA256,
            slot=Slice3ReadSlot.FINAL_MARGIN,
            declaration=slice3_read_declaration(Slice3ReadSlot.FINAL_MARGIN),
        )

    assert target.read_text(encoding="utf-8") == PRIVATE_RESPONSE


def test_hardlink_path_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    source.write_bytes(b"")
    source.chmod(0o600)
    path = tmp_path / "slice3-read-journal.jsonl"
    os.link(source, path)
    journal = FileSlice3ReadJournal(path)

    with pytest.raises(Slice3ReadJournalError, match="unsafe"):
        journal.reserve(
            plan_sha256=PLAN_SHA256,
            slot=Slice3ReadSlot.FINAL_MARGIN,
            declaration=slice3_read_declaration(Slice3ReadSlot.FINAL_MARGIN),
        )

    assert source.stat().st_nlink == 2
    assert source.read_bytes() == b""


def test_non_owner_only_mode_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "slice3-read-journal.jsonl"
    path.write_bytes(b"")
    path.chmod(0o644)

    with pytest.raises(Slice3ReadJournalError, match="unsafe"):
        FileSlice3ReadJournal(path).read_all()


def test_declaration_drift_is_rejected_before_file_or_delegate(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    slot = Slice3ReadSlot.PRE_CREATE_OPEN_ORDERS
    drifted = replace(slice3_read_declaration(slot), subread_count=2)
    calls = 0

    def delegate() -> _SyntheticEvidence:
        nonlocal calls
        calls += 1
        return _SyntheticEvidence()

    with pytest.raises(Slice3ReadJournalError, match="declaration_invalid"):
        journal.execute(
            plan_sha256=PLAN_SHA256,
            slot=slot,
            declaration=drifted,
            delegate=delegate,
        )

    assert calls == 0
    assert not journal.path.exists()


def test_explicit_evidence_sha256_must_be_exact_and_never_stores_metadata(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    slot = Slice3ReadSlot.PRE_CLOSE_POSITION
    reservation = journal.reserve(
        plan_sha256=PLAN_SHA256,
        slot=slot,
        declaration=slice3_read_declaration(slot),
    )
    journal.consume_success(
        reservation,
        evidence_sha256=EVIDENCE_SHA256,
    )

    terminal = journal.read_all()[-1]
    assert terminal.evidence_sha256 == EVIDENCE_SHA256
    raw = journal.path.read_text(encoding="utf-8")
    assert set(json.loads(raw.splitlines()[-1])) == {
        "schema_version",
        "event",
        "recorded_at",
        "semantic_key",
        "plan_sha256",
        "slot",
        "declaration",
        "outcome",
        "reason_code",
        "evidence_sha256",
        "previous_record_sha256",
        "record_sha256",
    }
