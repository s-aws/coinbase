# Test Files Index

Generated from the current tracked checkout on 2026-10-09. Module summaries
describe test intent, not measured coverage. Case counts vary with parametrization.
Run the complete gate from [README.md](README.md); focused selections require
an explicit user request.

## tests/ root (2 files)

| File | Defined test functions | Module intent |
| --- | ---: | --- |
| [test_exceptions.py](test_exceptions.py) | 33 | Comprehensive tests for custom exception system. |
| [test_lot_tracking_integration.py](test_lot_tracking_integration.py) | 9 | Integration tests for lot-based profit-aware execution system. |

## tests/unit (38 files)

| File | Defined test functions | Module intent |
| --- | ---: | --- |
| [test_codex_repo_graph_evidence.py](unit/test_codex_repo_graph_evidence.py) | 15 | See test names in source. |
| [test_codex_repo_graph_lifecycle.py](unit/test_codex_repo_graph_lifecycle.py) | 3 | See test names in source. |
| [test_coinbase_api.py](unit/test_coinbase_api.py) | 16 | Unit tests for Coinbase API integration. |
| [test_condition_evaluators.py](unit/test_condition_evaluators.py) | 22 | Unit tests for condition evaluators. |
| [test_cross_venue_aggregator.py](unit/test_cross_venue_aggregator.py) | 14 | Unit tests for market_intel.cross_venue_aggregator. |
| [test_database.py](unit/test_database.py) | 21 | Unit tests for database operations and repositories. |
| [test_engine_console.py](unit/test_engine_console.py) | 12 | Unit tests for engine_console filter and rendering logic. |
| [test_fee_regime_adaptation.py](unit/test_fee_regime_adaptation.py) | 7 | Unit tests for adaptive fee and target-movement regime integration. |
| [test_fill_ledger_append_derived.py](unit/test_fill_ledger_append_derived.py) | 5 | Unit tests for FillLedgerRepository.append_derived_fill. |
| [test_fill_reconciler.py](unit/test_fill_reconciler.py) | 8 | Unit tests for FillReconciler — Step 5 of the WS-derived-fill design plan. |
| [test_filled_followup_dedup.py](unit/test_filled_followup_dedup.py) | 1 | Unit test proving duplicate FILLED events do not create duplicate follow-up orders. |
| [test_filled_followup_partial_size_adjustment.py](unit/test_filled_followup_partial_size_adjustment.py) | 2 | Unit tests for FILLED follow-up sizing when partial follow-ups already exist. |
| [test_generate_order_ladder_random.py](unit/test_generate_order_ladder_random.py) | 15 | Unit tests for genai_tools.generate_order_ladder random expansion. |
| [test_models.py](unit/test_models.py) | 19 | Unit tests for data models and state management. |
| [test_order_calculator.py](unit/test_order_calculator.py) | 19 | Unit tests for OrderCalculator business logic. |
| [test_order_engine_ticker_ingress.py](unit/test_order_engine_ticker_ingress.py) | 8 | Focused contracts for OrderEngine's bounded ticker-ingress lane. |
| [test_order_event_stream.py](unit/test_order_event_stream.py) | 8 | Focused tests for OrderEventStreamPublisher stealth lifecycle auditing. |
| [test_order_helpers.py](unit/test_order_helpers.py) | 21 | Test the resolve_order_size and resolve_order_side helper functions. |
| [test_order_id_and_followup_rules.py](unit/test_order_id_and_followup_rules.py) | 3 | Unit tests for order ID contracts and stealth follow-up invariants. |
| [test_order_inventory.py](unit/test_order_inventory.py) | 62 | Unit tests for the Order Inventory feature. |
| [test_order_moves.py](unit/test_order_moves.py) | 25 | Tests for the order move mechanism. |
| [test_order_progress_tracker.py](unit/test_order_progress_tracker.py) | 11 | Unit tests for business.order_progress.OrderProgressTracker. |
| [test_orderbook_v2.py](unit/test_orderbook_v2.py) | 56 | Unit tests for the v2 :mod:core.orderbook module. |
| [test_parent_order_race_condition.py](unit/test_parent_order_race_condition.py) | 3 | Test for duplicate parent order insertion race condition fix. |
| [test_partial_fill_followups.py](unit/test_partial_fill_followups.py) | 13 | Unit tests for the OrderEngine WS-derived progress pipeline. |
| [test_placement_response.py](unit/test_placement_response.py) | 14 | Unit tests for the pure exchange-placement response classifier. |
| [test_product_type_profitability_fix.py](unit/test_product_type_profitability_fix.py) | 8 | Regression tests for product-type-aware profitability validation (Option A). |
| [test_profit_validator.py](unit/test_profit_validator.py) | 5 | Unit tests for ProfitValidator shared target-to-price helpers. |
| [test_stealth_condition_deadline_helpers.py](unit/test_stealth_condition_deadline_helpers.py) | 17 | Deterministic tests for production stealth-condition schedule helpers. |
| [test_stealth_condition_transition_persistence.py](unit/test_stealth_condition_transition_persistence.py) | 3 | Fail-closed persistence contracts for stealth condition transitions. |
| [test_stealth_continuous_hold_semantics.py](unit/test_stealth_continuous_hold_semantics.py) | 17 | Behavioral contracts for continuous price/spread reveal holds. |
| [test_stealth_event_deadline_scheduler.py](unit/test_stealth_event_deadline_scheduler.py) | 20 | Focused tests for the manager/DB/REST-independent scheduler primitive. |
| [test_stealth_hydration_completion.py](unit/test_stealth_hydration_completion.py) | 3 | Startup must distinguish an empty stealth table from failed hydration. |
| [test_stealth_order_bridge_scheduler_contract.py](unit/test_stealth_order_bridge_scheduler_contract.py) | 79 | Focused contract tests for the event-driven stealth-order bridge. |
| [test_stealth_order_load_all_statuses.py](unit/test_stealth_order_load_all_statuses.py) | 4 | Test for verifying EXECUTED orders are loaded after engine restart. |
| [test_stealth_order_manager.py](unit/test_stealth_order_manager.py) | 25 | Unit tests for StealthOrderManager. |
| [test_stealth_reveal_strategy.py](unit/test_stealth_reveal_strategy.py) | 20 | Unit tests for the RevealStrategy interface and concrete strategies. |
| [test_stealth_target_movement_fix.py](unit/test_stealth_target_movement_fix.py) | 3 | Test to verify that stealth orders preserve their target_movement when revealed and filled. |

## tests/integration (7 files)

| File | Defined test functions | Module intent |
| --- | ---: | --- |
| [test_adaptive_follow_up_spacing_integration.py](integration/test_adaptive_follow_up_spacing_integration.py) | 1 | Integration test for adaptive follow-up spacing through OrderEngine flow. |
| [test_anchor_repricing_integration.py](integration/test_anchor_repricing_integration.py) | 12 | Integration tests for ticker-driven anchor repricing. |
| [test_anchor_repricing_phase2.py](integration/test_anchor_repricing_phase2.py) | 12 | Phase 2: Adaptive repricing with extended guardrails. |
| [test_bridges.py](integration/test_bridges.py) | 15 | Integration tests for bridge components and orchestration. |
| [test_order_engine_id_workflow.py](integration/test_order_engine_id_workflow.py) | 5 | Integration tests for OrderEngine ID handling and parent-child workflow. |
| [test_order_processing.py](integration/test_order_processing.py) | 13 | Integration tests for complete order processing workflows. |
| [test_stealth_order_workflow.py](integration/test_stealth_order_workflow.py) | 6 | Integration tests for stealth order workflows. |

## tests/regression (78 files)

| File | Defined test functions | Module intent |
| --- | ---: | --- |
| [test_anchor_rearm_tombstone_replay.py](regression/test_anchor_rearm_tombstone_replay.py) | 3 | Regression coverage for stale rows after authenticated anchor rearming. |
| [test_anchor_reprice_phantom_parent.py](regression/test_anchor_reprice_phantom_parent.py) | 23 | Regression coverage for revealed anchor repricing. |
| [test_cancel_followup_stealth_id_passthrough.py](regression/test_cancel_followup_stealth_id_passthrough.py) | 6 | Regression: 2026-05-04 phantom-child / stranded-exposure incident. |
| [test_configuration_cloudflare_fallback.py](regression/test_configuration_cloudflare_fallback.py) | 3 | Regression coverage for transient malformed Coinbase gateway responses. |
| [test_core_functionality.py](regression/test_core_functionality.py) | 10 | Regression tests - Critical path tests that must always pass before deployment. |
| [test_create_limit_order_span_smoke.py](regression/test_create_limit_order_span_smoke.py) | 7 | Smoke tests for order.create_limit_order_span. |
| [test_cross_source_reconciliation.py](regression/test_cross_source_reconciliation.py) | 30 | Regression tests for cross-source reconciliation (Phase 3). |
| [test_cross_venue_monitor.py](regression/test_cross_venue_monitor.py) | 6 | Regression tests for the ui_console CrossVenueMonitor lifecycle. |
| [test_dashboard_move_revealed_handler.py](regression/test_dashboard_move_revealed_handler.py) | 6 | Regression tests for the move_revealed_stealth_order dashboard |
| [test_dashboard_rehide.py](regression/test_dashboard_rehide.py) | 6 | Manual Rehide uses the bridge and reports intent, never inferred exchange truth. |
| [test_dashboard_startup_admission.py](regression/test_dashboard_startup_admission.py) | 9 | Dashboard admission remains fail-closed through runtime startup. |
| [test_db_cursor_thread_safety.py](regression/test_db_cursor_thread_safety.py) | 2 | Regression: PostgresDB.get_cursor() must serialize cursor access across threads. |
| [test_exception_kwargs_signature.py](regression/test_exception_kwargs_signature.py) | 11 | Regression: every exception class accepts the kwargs that real call sites use. |
| [test_fee_manager_lifecycle.py](regression/test_fee_manager_lifecycle.py) | 5 | Fee refresh publication remains stop-dominant during engine startup. |
| [test_fee_multiplier_by_product_type.py](regression/test_fee_multiplier_by_product_type.py) | 6 | Regression: fee schedule and cushion must both be product-type aware. |
| [test_filtered_fee_schedules.py](regression/test_filtered_fee_schedules.py) | 8 | Regression contract for filtered, isolated Coinbase fee schedules. |
| [test_flat_hierarchy_stealth_placement.py](regression/test_flat_hierarchy_stealth_placement.py) | 6 | Regression: flat-hierarchy rule must not be violated by stealth placements. |
| [test_follow_up_claim_api.py](regression/test_follow_up_claim_api.py) | 10 | Regression: follow-up claim API must work after the OrderBook v2 cleanup. |
| [test_follow_up_creation_retreat_wiring.py](regression/test_follow_up_creation_retreat_wiring.py) | 7 | Regression: create_follow_up_stealth_order actually applies the |
| [test_follow_up_retreat.py](regression/test_follow_up_retreat.py) | 14 | Regression: RepricingPolicy.compute_follow_up_price (post-fill |
| [test_hotpoint_decay_sweeper.py](regression/test_hotpoint_decay_sweeper.py) | 8 | Tests for business.hotpoint_decay_sweeper. |
| [test_hotpoint_detector.py](regression/test_hotpoint_detector.py) | 14 | Tests for business.hotpoint_detector. |
| [test_hotpoint_engine_integration.py](regression/test_hotpoint_engine_integration.py) | 14 | Integration: OrderEngine._maybe_dispatch_hotpoint end-to-end with mocks. |
| [test_hotpoint_opt_in_plumbing.py](regression/test_hotpoint_opt_in_plumbing.py) | 3 | Regression: enable_hotpoint_replication is plumbed end-to-end. |
| [test_hotpoint_placer.py](regression/test_hotpoint_placer.py) | 15 | Tests for business.hotpoint_placer. |
| [test_hotpoint_rate_limiter.py](regression/test_hotpoint_rate_limiter.py) | 12 | Tests for business.hotpoint_rate_limiter. |
| [test_inventory_product_type.py](regression/test_inventory_product_type.py) | 6 | Inventory, state, and lifecycle types must not depend on month substrings. |
| [test_list_fills_param_mapping.py](regression/test_list_fills_param_mapping.py) | 3 | Regression: 2026-04-30 list_fills parameter-name mismatch. |
| [test_list_orders_param_mapping.py](regression/test_list_orders_param_mapping.py) | 3 | Regression coverage for paginated startup open-order reconciliation. |
| [test_main_startup_gate.py](regression/test_main_startup_gate.py) | 43 | Fail-closed startup ordering for stealth decision activation. |
| [test_maker_taker_fee_selection.py](regression/test_maker_taker_fee_selection.py) | 5 | Regression: maker/taker selection is schedule-specific and post-only driven. |
| [test_manual_stealth_rehide.py](regression/test_manual_stealth_rehide.py) | 16 | Manual Rehide reuses authenticated rearm without repricing or duplication. |
| [test_market_chart_data.py](regression/test_market_chart_data.py) | 6 | Regression: 1m candle store + chart-history reader. |
| [test_market_metrics_tracker.py](regression/test_market_metrics_tracker.py) | 17 | Regression tests for business.market_metrics.MarketMetricsTracker. |
| [test_market_tick_recorder.py](regression/test_market_tick_recorder.py) | 9 | Regression: market-tick recorder throttle, table creation, and retention. |
| [test_nonmanager_price_boundaries.py](regression/test_nonmanager_price_boundaries.py) | 13 | Regression coverage for exchange-bound prices outside the stealth manager. |
| [test_operator_cancel_dashboard.py](regression/test_operator_cancel_dashboard.py) | 9 | Operator commands retain cancellation truth until exchange confirmation. |
| [test_operator_cancel_deletion_guards.py](regression/test_operator_cancel_deletion_guards.py) | 3 | Destructive cleanup keeps durable cancellation and parent recovery evidence. |
| [test_operator_cancel_followups.py](regression/test_operator_cancel_followups.py) | 9 | An accepted project cancel stops new automation, not exchange accounting. |
| [test_operator_cancel_lifecycle.py](regression/test_operator_cancel_lifecycle.py) | 15 | Intentional stealth cancellation stops automation without losing venue truth. |
| [test_order_id_regression.py](regression/test_order_id_regression.py) | 3 | Regression guards for critical order ID and hierarchy behavior. |
| [test_parent_row_before_ws_delta.py](regression/test_parent_row_before_ws_delta.py) | 4 | Regression: order_parent row must exist BEFORE _process_ws_order_delta. |
| [test_partial_fill_follow_up_atomic_claim.py](regression/test_partial_fill_follow_up_atomic_claim.py) | 4 | Regression: 2026-04-29 duplicate-buy / over-buy incident. |
| [test_per_side_mandatory_fee.py](regression/test_per_side_mandatory_fee.py) | 7 | Regression: Coinbase Derivatives per-side mandatory fee schedule. |
| [test_place_limit_order_returns_dict.py](regression/test_place_limit_order_returns_dict.py) | 7 | Regression: CoinbaseClient.place_limit_order must return the SDK's |
| [test_placement_response_truth.py](regression/test_placement_response_truth.py) | 2 | Regression guards for false-positive REST placement success. |
| [test_post_only_guard_fire_preservation.py](regression/test_post_only_guard_fire_preservation.py) | 4 | Regression: post_only is preserved when the configured-limit guard |
| [test_post_only_propagation.py](regression/test_post_only_propagation.py) | 7 | Regression: post_only propagation across profitability call sites. |
| [test_post_only_retry.py](regression/test_post_only_retry.py) | 16 | Regression: post-only retry loop with 1-tick safer reprice. |
| [test_post_only_retry_no_orphan.py](regression/test_post_only_retry_no_orphan.py) | 5 | Regression: post-only retry must not orphan the placement from |
| [test_price_camouflage.py](regression/test_price_camouflage.py) | 14 | Regression tests for calculation.price_camouflage. |
| [test_price_normalization.py](regression/test_price_normalization.py) | 10 | Regression coverage for the canonical exchange-price grid boundary. |
| [test_process_user_order_per_coid_lock.py](regression/test_process_user_order_per_coid_lock.py) | 4 | Regression: per-COID serialisation in process_user_order. |
| [test_profitability_failure_throttling.py](regression/test_profitability_failure_throttling.py) | 16 | Regression: profitability-validation failures must be log-throttled |
| [test_profitability_fee_quote_consistency.py](regression/test_profitability_fee_quote_consistency.py) | 2 | Regression coverage for atomic profitability fee sampling. |
| [test_quantize_to_increment.py](regression/test_quantize_to_increment.py) | 11 | Regression tests for the canonical quantize_to_increment. |
| [test_reconciler_schema.py](regression/test_reconciler_schema.py) | 6 | Schema smoke test for runtime-reconciler SQL. |
| [test_redundant_public_ticker_fanout.py](regression/test_redundant_public_ticker_fanout.py) | 1 | Regression guard for redundant public websocket ticker fan-out. |
| [test_replacement_slot_atomic_claim.py](regression/test_replacement_slot_atomic_claim.py) | 7 | Regression: replacement-cap atomic claim + partial-fill bypass. |
| [test_repricing_policy.py](regression/test_repricing_policy.py) | 14 | Regression: RepricingPolicy dataclass + static-source guard. |
| [test_reveal_condition_price_tracking.py](regression/test_reveal_condition_price_tracking.py) | 13 | Repricing offsets follow operator edits and identify each composite field. |
| [test_reveal_pricing_policy_post_only.py](regression/test_reveal_pricing_policy_post_only.py) | 7 | Regression: RevealPricingPolicy.implies_post_only is the single |
| [test_reveal_slice_exception_messaging.py](regression/test_reveal_slice_exception_messaging.py) | 4 | Regression: reveal_order_slice must distinguish REST-failure from |
| [test_runtime_controller.py](regression/test_runtime_controller.py) | 43 | Regression tests for the runtime lifecycle controller. |
| [test_seed_child_placement_from_db.py](regression/test_seed_child_placement_from_db.py) | 7 | Regression: stealth reveal-placement persisted as a child must seed correctly. |
| [test_shutdown_followups.py](regression/test_shutdown_followups.py) | 12 | Regression tests for graceful-shutdown follow-up pieces. |
| [test_size_validation.py](regression/test_size_validation.py) | 16 | Regression tests for calculation.size_validation. |
| [test_slide_calibration_summary.py](regression/test_slide_calibration_summary.py) | 12 | Regression: slide-calibration summary aggregates and goal math. |
| [test_span_builder_anchor_repricing_ui.py](regression/test_span_builder_anchor_repricing_ui.py) | 6 | Regression contracts for optional per-rung span repricing policies. |
| [test_stealth_move_revealed.py](regression/test_stealth_move_revealed.py) | 24 | Regression test pinning the v1 contract for "move REVEALED stealth order". |
| [test_stealth_order_visibility_ui.py](regression/test_stealth_order_visibility_ui.py) | 5 | Regression contracts for actionable stealth-order visibility and labels. |
| [test_stealth_placement_truth.py](regression/test_stealth_placement_truth.py) | 31 | Regression coverage for canonical stealth placement truth. |
| [test_stealth_price_hold_ui.py](regression/test_stealth_price_hold_ui.py) | 2 | Regression contracts for configurable zero-second price-condition holds. |
| [test_tranche_iceberg_pacing.py](regression/test_tranche_iceberg_pacing.py) | 9 | Regression: tranche stealth orders must not burst-post slices. |
| [test_transaction_summary_param_mapping.py](regression/test_transaction_summary_param_mapping.py) | 4 | Regression coverage for Coinbase transaction-summary filter forwarding. |
| [test_triggered_snapshot_commit.py](regression/test_triggered_snapshot_commit.py) | 5 | Regression: TRIGGERED stealth orders must commit on the next bridge tick. |
| [test_two_sided_fee_accounting.py](regression/test_two_sided_fee_accounting.py) | 6 | Regression: percentage fees must be charged on BOTH sides. |
| [test_user_channel_patch_dispatch.py](regression/test_user_channel_patch_dispatch.py) | 56 | Regression contracts for Coinbase authenticated user-channel dispatch. |

## tests/e2e (2 files)

| File | Defined test functions | Module intent |
| --- | ---: | --- |
| [test_trading_workflows.py](e2e/test_trading_workflows.py) | 10 | End-to-end tests for complete system workflows. |
| [test_user_message_order_flow.py](e2e/test_user_message_order_flow.py) | 1 | E2E-style tests for user message order flow and ID semantics. |

## tests/external (1 files)

| File | Defined test functions | Module intent |
| --- | ---: | --- |
| [test_coinbase_api.py](external/test_coinbase_api.py) | 11 | External Coinbase API integration tests. |
