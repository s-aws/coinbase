# Test Coverage Navigation

Reconciled on 2026-10-09. This is a source inventory, not a measured coverage
report. The repository does not publish a current coverage percentage here.
Run policy and environment are in [README.md](README.md); exact file counts
and module summaries are in [TEST_FILES_INDEX.md](TEST_FILES_INDEX.md).

| Domain | Representative checked-in tests |
| --- | --- |
| Runtime readiness/admission/drain | `regression/test_runtime_controller.py`, `regression/test_main_startup_gate.py`, `regression/test_dashboard_startup_admission.py` |
| Private stream sequencing/bootstrap/FIFO | `regression/test_user_channel_patch_dispatch.py`, `e2e/test_user_message_order_flow.py` |
| Public ticker dedup/continuity | `regression/test_redundant_public_ticker_fanout.py`, `unit/test_order_engine_ticker_ingress.py` |
| Conditions/deadlines/durability | `unit/test_stealth_continuous_hold_semantics.py`, `unit/test_stealth_order_bridge_scheduler_contract.py`, `regression/test_triggered_snapshot_commit.py` |
| Reveal acceptance/pricing | `regression/test_stealth_placement_truth.py`, `regression/test_reveal_pricing_policy_post_only.py` |
| Confirmed rearm and Rehide | `regression/test_anchor_reprice_phantom_parent.py`, `regression/test_anchor_rearm_tombstone_replay.py`, `regression/test_manual_stealth_rehide.py`, `regression/test_dashboard_rehide.py` |
| Operator stop/withdrawal/recovery | `regression/test_operator_cancel_lifecycle.py`, `regression/test_operator_cancel_followups.py`, `regression/test_operator_cancel_deletion_guards.py`, `regression/test_operator_cancel_dashboard.py` |
| Threshold offsets/composite edits | `regression/test_reveal_condition_price_tracking.py` |
| Flat hierarchy/follow-up claims/caps | `regression/test_flat_hierarchy_stealth_placement.py`, `regression/test_replacement_slot_atomic_claim.py`, `regression/test_partial_fill_follow_up_atomic_claim.py` |
| Fills/ownership/reconciliation | `regression/test_cross_source_reconciliation.py`, `unit/test_fill_reconciler.py`, `unit/test_fill_ledger_append_derived.py` |
| Price/size/fee boundaries | `regression/test_price_normalization.py`, `regression/test_size_validation.py`, `regression/test_two_sided_fee_accounting.py`, `regression/test_filtered_fee_schedules.py` |
| Product classification | `regression/test_inventory_product_type.py`, `unit/test_product_type_profitability_fix.py` |
| UI visibility/span repricing | `regression/test_stealth_order_visibility_ui.py`, `regression/test_span_builder_anchor_repricing_ui.py` |
| Graph freshness/review fingerprints | `unit/test_codex_repo_graph_lifecycle.py`, `unit/test_codex_repo_graph_evidence.py` |

External tests live in `external/test_coinbase_api.py` and are opt-in. They are
not part of the local pass. File presence and static graph call candidates do
not establish complete branch coverage or live exchange correctness.
