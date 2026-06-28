from __future__ import annotations

from tools import run_autonomous_work_queue_check as checker


def _queue_body() -> str:
    return checker.QUEUE_DOC.read_text(encoding="utf-8")


def test_release_0_1_phase_titles_match_approved_product_pivot() -> None:
    result = checker._check_release_phase_titles(_queue_body())

    assert result.passed
    assert result.evidence["missing_phase_titles"] == []
    assert result.evidence["mismatched_phase_titles"] == {}
    assert result.evidence["proof_only_active_phase_titles"] == {}


def test_release_0_1_phase_titles_reject_proof_summary_drift() -> None:
    body = _queue_body().replace(
        "### Phase 7996 - Autonomous Validator Pivot",
        "### Phase 7996 - Futures/Perpetuals Proof Summary Expansion",
    )

    result = checker._check_release_phase_titles(body)

    assert not result.passed
    assert result.evidence["mismatched_phase_titles"][7996] == {
        "expected": "Autonomous Validator Pivot",
        "actual": "Futures/Perpetuals Proof Summary Expansion",
    }
    assert result.evidence["proof_only_active_phase_titles"][7996] == (
        "Futures/Perpetuals Proof Summary Expansion"
    )


def test_release_0_1_phase_titles_reject_unapproved_active_phase() -> None:
    body = _queue_body().replace(
        "### Phase 7996 - Autonomous Validator Pivot",
        (
            "### Phase 8001 - Futures/Perpetuals Request Payload Evidence\n\n"
            "- This would reopen proof-only drift.\n\n"
            "### Phase 7996 - Autonomous Validator Pivot"
        ),
    )

    result = checker._check_release_phase_titles(body)

    assert not result.passed
    assert 8001 in result.evidence["unexpected_active_phase_ids"]
    assert result.evidence["proof_only_active_phase_titles"][8001] == (
        "Futures/Perpetuals Request Payload Evidence"
    )
