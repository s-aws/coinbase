# Admin API Examples

These examples describe the current enterprise Admin API contract. Mutating
HTTP endpoints are authenticated, permission-checked, idempotent, and audited,
then return `not_implemented`; they do not call Coinbase. Read-only spot
operator endpoints are available behind the same fail-closed auth dependency.

The Admin API is the backend contract layer for the enterprise admin platform.
Spot is the first complete product module. Do not use spot wallet, USDC,
cost-basis, or no-shorting rules as generic admin behavior for
futures/perpetuals, stealth orders, repricing, or risk policy modules.

## Current Futures/Perpetuals M57 Evidence

`GET /api/v1/futures/command-suite` currently reports
`"approved_phase_range": "7261-7280"`. Futures/perpetual command-suite reads
expose backend-owned execution-eligibility resolution-plan step review input
store record-validation remediation dependency work-item claim-trace clearance
step evidence while carrying forward execution-eligibility resolution-plan step
review input store record-validation remediation dependency work-item
claim-trace clearance plan evidence,
carrying forward execution-eligibility resolution-plan step
review input store record-validation remediation dependency work-item
claim-trace evidence,
carrying forward execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item evidence,
carrying forward execution-eligibility resolution-plan step review input store
record-validation remediation dependency evidence,
execution-eligibility resolution-plan step review input store record-validation
remediation evidence,
execution-eligibility resolution-plan step review input store record-validation
evidence, execution-eligibility resolution-plan step review input store
record-contract evidence,
execution-eligibility resolution-plan step review input store requirement evidence,
execution-eligibility resolution-plan step review input evidence,
execution-eligibility resolution-plan step review evidence,
execution-eligibility resolution-plan step evidence, execution-eligibility
resolution-plan evidence, execution-eligibility semantic closure evidence,
disabled reconciliation semantics, cancel semantics, order semantics, and
earlier evidence. Active M57 `7261-7280` evidence adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance step
evidence while completed M57 `7241-7260` carries forward futures request
payload validation record execution-eligibility resolution-plan step review
input store record-validation remediation dependency work-item claim-trace
clearance plan evidence, completed M57 `7221-7240` carries forward futures request
payload validation record execution-eligibility resolution-plan step review
input store record-validation remediation dependency work-item claim trace
evidence, completed M57 `7201-7220` carries forward futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item evidence, and completed M57
`7181-7200` carries forward futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency evidence.

Active claim-trace rows expose `execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_contract_ref`,
`record_validation_remediation_dependency_work_item_claim_trace_required=true`,
`record_validation_remediation_dependency_work_item_claim_trace_ready=false`,
`record_validation_remediation_dependency_work_item_claim_trace_created=false`,
`claim_trace_created=false`, `claim_trace_ready=false`,
`claim_allowed=false`, `claim_resolved=false`,
`claim_review_accepted=false`, `contextless_review_passed=false`,
`accepts_evidence=false`, and `writes_evidence=false`.

Active work-item rows expose `execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_contract_ref`,
`record_validation_remediation_dependency_work_item_required=true`,
`record_validation_remediation_dependency_work_item_ready=false`,
`record_validation_remediation_dependency_work_item_created=false`,
`record_validation_remediation_dependency_work_item_claimed=false`,
`claim_ledger_registered=false`, `owner_review_accepted=false`,
`contextless_review_passed=false`, `accepts_evidence=false`, and
`writes_evidence=false`.

Completed M57 `7181-7200` futures/perpetual command-suite reads expose
backend-owned execution-eligibility resolution-plan step review input store
record-validation remediation dependency evidence while carrying forward
execution-eligibility resolution-plan step review input store
record-validation remediation evidence.

Completed M57 `7161-7180` futures/perpetual command-suite reads expose
backend-owned execution-eligibility resolution-plan step review input store
record-validation remediation evidence while carrying forward execution-
eligibility resolution-plan step review input store record-validation evidence.

Completed M57 `7141-7160` futures/perpetual command-suite reads expose
backend-owned execution-eligibility resolution-plan step review input store
record-validation evidence while carrying forward execution-eligibility
resolution-plan step review input store record-contract evidence.

Completed M57 `7121-7140` futures/perpetual command-suite reads
expose backend-owned execution-eligibility resolution-plan step review input
store record-contract evidence while carrying forward
futures request payload validation record execution-eligibility resolution-plan
step review input store requirement evidence.

Completed M57 `7101-7120` futures/perpetual command-suite reads
expose backend-owned execution-eligibility resolution-plan step review input
store requirement evidence while carrying forward execution-eligibility
resolution-plan step review input evidence, execution-eligibility
resolution-plan step review evidence, execution-eligibility resolution-plan
step evidence, execution-eligibility resolution-plan evidence,
execution-eligibility semantic closure evidence, disabled reconciliation semantics,
cancel semantics, order semantics, and
carrying forward earlier semantic artifact runtime evidence binding,
semantic artifact definition review output acceptance,
semantic artifact definition review output, semantic artifact definition
review input, semantic artifact definition review,
semantic artifact definition, semantic artifact, execution-eligibility blocker,
execution-eligibility, and admission-link evidence:
`FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS`,
`iter_futures_request_payload_contracts`,
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS`,
`iter_futures_request_payload_validator_contracts`,
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS`,
`iter_futures_request_payload_validator_input_schemas`,
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS`,
`iter_futures_request_payload_validator_output_schemas`,
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS`,
`iter_futures_request_payload_validator_registrations`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS`,
`iter_futures_request_payload_validation_evidence`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS`,
`iter_futures_request_payload_validation_evidence_records`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS`,
`iter_futures_request_payload_validation_record_schemas`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS`,
`iter_futures_request_payload_validation_record_replay_guards`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_AUDIT_LINK_CONTRACTS`,
`iter_futures_request_payload_validation_record_audit_links`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ADMISSION_LINK_CONTRACTS`,
`iter_futures_request_payload_validation_record_admission_links`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS`,
`iter_futures_request_payload_validation_record_execution_eligibilities`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS`,
`iter_futures_request_payload_validation_record_execution_eligibility_blockers`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS`,
`iter_futures_request_payload_validation_record_semantic_artifacts`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_CONTRACTS`,
`iter_futures_request_payload_validation_record_semantic_artifact_definitions`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_CONTRACTS`,
`iter_futures_request_payload_validation_record_semantic_artifact_definition_reviews`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS`,
`iter_futures_request_payload_validation_record_semantic_artifact_definition_review_inputs`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_CONTRACTS`,
`iter_futures_request_payload_validation_record_semantic_artifact_definition_review_outputs`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_ACCEPTANCE_CONTRACTS`,
`iter_futures_request_payload_validation_record_semantic_artifact_definition_review_output_acceptances`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS`,
`iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidences`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS`,
`iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS`,
`iter_futures_request_payload_validation_record_position_semantics`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS`,
`iter_futures_request_payload_validation_record_margin_semantics`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS`,
`iter_futures_request_payload_validation_record_collateral_semantics`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS`,
`iter_futures_request_payload_validation_record_liquidation_semantics`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS`,
`iter_futures_request_payload_validation_record_reduce_only_semantics`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CLOSE_ONLY_SEMANTIC_CONTRACTS`,
`iter_futures_request_payload_validation_record_close_only_semantics`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_FUNDING_SEMANTIC_CONTRACTS`,
`iter_futures_request_payload_validation_record_funding_semantics`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ORDER_SEMANTIC_CONTRACTS`,
`iter_futures_request_payload_validation_record_order_semantics`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CANCEL_SEMANTIC_CONTRACTS`,
`iter_futures_request_payload_validation_record_cancel_semantics`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_RECONCILIATION_SEMANTIC_CONTRACTS`,
and `iter_futures_request_payload_validation_record_reconciliation_semantics`.

Active execution-eligibility resolution-plan step rows expose
`execution_eligibility_resolution_plan_ref`,
`execution_eligibility_resolution_plan_contract_ref`,
`execution_eligibility_resolution_plan_step_ref`,
`execution_eligibility_resolution_plan_step_contract_ref`,
`execution_eligibility_resolution_plan_step_review_ref`,
`execution_eligibility_resolution_plan_step_review_contract_ref`,
`execution_eligibility_resolution_plan_step_review_input_ref`,
`execution_eligibility_resolution_plan_step_review_input_contract_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_requirement_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_requirement_contract_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_contract_contract_ref`,
`resolution_plan_step_kind`, `resolution_plan_step_ready=false`,
`resolution_plan_step_accepted=false`,
`resolution_plan_step_review_required=true`,
`resolution_plan_step_review_ready=false`,
`resolution_plan_step_reviewed=false`,
`resolution_plan_step_review_accepted=false`, `review_input_kind`,
`review_input_index`, `input_evidence_store`,
`resolution_plan_step_review_input_required=true`,
`resolution_plan_step_review_input_present=false`,
`resolution_plan_step_review_input_accepted=false`,
`resolution_plan_step_review_input_validated=false`,
`resolution_plan_step_review_input_store_requirement_required=true`,
`resolution_plan_step_review_input_store_available=false`,
`resolution_plan_step_review_input_writer_available=false`,
`resolution_plan_step_review_input_record_key_available=false`,
`resolution_plan_step_review_input_validation_gate_ready=false`,
`resolution_plan_step_review_input_replay_gate_ready=false`,
`record_contract_required=true`,
`record_contract_available=false`,
`record_schema_available=false`,
`append_only_log_available=false`,
`idempotency_key_bound=false`,
`payload_schema_validated=false`,
`replay_protected=false`,
`store_available=false`,
`writer_available=false`,
`writer_allowed=false`,
`write_allowed=false`,
`record_present=false`,
`record_accepted=false`,
`record_validated=false`,
`validation_configured=false`,
`replay_protection_configured=false`,
`ordered_resolution_step_ref`,
`ordered_resolution_step_refs`, `ordered_resolution_step_count`,
`resolution_plan_present=true`, `resolution_plan_ready=false`,
`resolution_plan_accepted=false`,
`runtime_evidence_satisfies_semantic_contract=false`,
`validation_record_admission_link_ready=false`, and
`blocker_resolved=false`. Resolution plan step review input store
record-contract presence is not blocker resolution. Resolution plan step review
input store requirement presence is not blocker resolution.

Completed execution-eligibility semantic-closure rows expose
`validation_record_position_semantics_contract_ref`,
`validation_record_margin_semantics_contract_ref`,
`validation_record_collateral_semantics_contract_ref`,
`validation_record_liquidation_semantics_contract_ref`,
`validation_record_reduce_only_semantics_contract_ref`,
`validation_record_close_only_semantics_contract_ref`,
`validation_record_funding_semantics_contract_ref`,
`validation_record_order_semantics_contract_ref`,
`validation_record_cancel_semantics_contract_ref`,
`validation_record_reconciliation_semantics_contract_ref`,
`validation_record_semantic_contract_refs`,
`validation_record_semantic_contract_ref_count`,
`validation_record_semantic_contracts_present=true`,
`validation_record_semantic_contracts_ready=false`,
`semantic_contract_ref`, `semantic_contract_present=true`, and
`semantic_contract_ready=false`.

Completed reconciliation-semantics rows expose
`request_payload_validation_record_reconciliation_semantic_count`,
`blocking_request_payload_validation_record_reconciliation_semantic_count`,
`ready_request_payload_validation_record_reconciliation_semantic_count`,
`runtime_observed_request_payload_validation_record_reconciliation_semantic_count`,
`request_payload_validation_record_reconciliation_semantics`,
`reconciliation_semantics_ref`, `reconciliation_semantics_contract_ref`,
`evidence_routes`, `reconciliation_semantics_contract_available=false`,
`reconciliation_semantics_contract_ready=false`,
`reconciliation_identity_bound=false`,
`reconciliation_position_key_bound=false`,
`reconciliation_plan_bound=false`, `reconciliation_reason_bound=false`,
`post_exchange_reconciliation_bound=false`,
`reconciliation_audit_bound=false`,
`runtime_reconciliation_evidence_observed=false`,
`runtime_evidence_satisfies_reconciliation_semantics=false`, and
`validation_record_reconciliation_semantics_ready=false`.

Completed cancel-semantics rows expose
`request_payload_validation_record_cancel_semantic_count`,
`blocking_request_payload_validation_record_cancel_semantic_count`,
`ready_request_payload_validation_record_cancel_semantic_count`,
`runtime_observed_request_payload_validation_record_cancel_semantic_count`,
`request_payload_validation_record_cancel_semantics`,
`cancel_semantics_ref`, `cancel_semantics_contract_ref`,
`evidence_routes`, `cancel_semantics_contract_available=false`,
`cancel_semantics_contract_ready=false`, `cancel_identity_bound=false`,
`cancel_client_order_id_bound=false`,
`cancel_order_wrapper_bound=false`,
`cancel_active_placement_bound=false`, `cancel_audit_bound=false`,
`runtime_cancel_evidence_observed=false`,
`runtime_evidence_satisfies_cancel_semantics=false`, and
`validation_record_cancel_semantics_ready=false`.

Completed order-semantics rows expose
`request_payload_validation_record_order_semantic_count`,
`blocking_request_payload_validation_record_order_semantic_count`,
`ready_request_payload_validation_record_order_semantic_count`,
`runtime_observed_request_payload_validation_record_order_semantic_count`,
`request_payload_validation_record_order_semantics`,
`order_semantics_ref`, `order_semantics_contract_ref`,
`evidence_routes`, `order_semantics_contract_available=false`,
`order_semantics_contract_ready=false`, `order_identity_bound=false`,
`order_side_bound=false`, `order_size_bound=false`,
`order_price_bound=false`, `order_type_bound=false`,
`runtime_order_evidence_observed=false`,
`runtime_evidence_satisfies_order_semantics=false`, and
`validation_record_order_semantics_ready=false`. Completed
funding-semantics rows expose
`request_payload_validation_record_funding_semantic_count`,
`blocking_request_payload_validation_record_funding_semantic_count`,
`ready_request_payload_validation_record_funding_semantic_count`,
`runtime_observed_request_payload_validation_record_funding_semantic_count`,
`request_payload_validation_record_funding_semantics`,
`funding_semantics_ref`, `funding_semantics_contract_ref`,
`evidence_routes`, `funding_semantics_contract_available=false`,
`funding_semantics_contract_ready=false`, `funding_rate_bound=false`,
`funding_fee_bound=false`, `funding_interval_bound=false`,
`funding_cost_bound=false`, `runtime_funding_evidence_observed=false`,
`runtime_evidence_satisfies_funding_semantics=false`, and
`validation_record_funding_semantics_ready=false`. Completed
close-only-semantics rows expose
`request_payload_validation_record_close_only_semantic_count`,
`blocking_request_payload_validation_record_close_only_semantic_count`,
`ready_request_payload_validation_record_close_only_semantic_count`,
`runtime_observed_request_payload_validation_record_close_only_semantic_count`,
`request_payload_validation_record_close_only_semantics`,
`close_only_semantics_ref`, `close_only_semantics_contract_ref`,
`evidence_routes`, `close_only_semantics_contract_available=false`,
`close_only_semantics_contract_ready=false`,
`close_only_flag_bound=false`, `close_only_position_side_bound=false`,
`close_only_position_size_bound=false`, `close_only_order_side_bound=false`,
`runtime_close_only_evidence_observed=false`,
`runtime_evidence_satisfies_close_only_semantics=false`, and
`validation_record_close_only_semantics_ready=false`. Completed
reduce-only-semantics rows expose
`request_payload_validation_record_reduce_only_semantic_count`,
`blocking_request_payload_validation_record_reduce_only_semantic_count`,
`ready_request_payload_validation_record_reduce_only_semantic_count`,
`runtime_observed_request_payload_validation_record_reduce_only_semantic_count`,
`request_payload_validation_record_reduce_only_semantics`,
`reduce_only_semantics_ref`, `reduce_only_semantics_contract_ref`,
`evidence_routes`, `reduce_only_semantics_contract_available=false`,
`reduce_only_semantics_contract_ready=false`,
`reduce_only_flag_bound=false`, `reduce_only_position_side_bound=false`,
`reduce_only_position_size_bound=false`, `reduce_only_order_side_bound=false`,
`runtime_reduce_only_evidence_observed=false`,
`runtime_evidence_satisfies_reduce_only_semantics=false`, and
`validation_record_reduce_only_semantics_ready=false`. Completed
liquidation-semantics rows expose
`request_payload_validation_record_liquidation_semantic_count`,
`blocking_request_payload_validation_record_liquidation_semantic_count`,
`ready_request_payload_validation_record_liquidation_semantic_count`,
`runtime_observed_request_payload_validation_record_liquidation_semantic_count`,
`request_payload_validation_record_liquidation_semantics`,
`liquidation_semantics_ref`, `liquidation_semantics_contract_ref`,
`evidence_routes`, `liquidation_semantics_contract_available=false`,
`liquidation_semantics_contract_ready=false`,
`liquidation_buffer_bound=false`, `liquidation_price_bound=false`,
`liquidation_distance_bound=false`, `liquidation_threshold_bound=false`,
`runtime_liquidation_evidence_observed=false`,
`runtime_evidence_satisfies_liquidation_semantics=false`, and
`validation_record_liquidation_semantics_ready=false`. Completed
collateral-semantics rows expose
`request_payload_validation_record_collateral_semantic_count`,
`blocking_request_payload_validation_record_collateral_semantic_count`,
`ready_request_payload_validation_record_collateral_semantic_count`,
`runtime_observed_request_payload_validation_record_collateral_semantic_count`,
`request_payload_validation_record_collateral_semantics`,
`collateral_semantics_ref`, `collateral_semantics_contract_ref`,
`evidence_routes`, `collateral_semantics_contract_available=false`,
`collateral_semantics_contract_ready=false`,
`collateral_balance_bound=false`, `collateral_currency_bound=false`,
`collateral_requirement_bound=false`, `collateral_source_bound=false`,
`runtime_collateral_evidence_observed=false`,
`runtime_evidence_satisfies_collateral_semantics=false`, and
`validation_record_collateral_semantics_ready=false`. Completed margin-semantics
rows expose
`request_payload_validation_record_margin_semantic_count`,
`blocking_request_payload_validation_record_margin_semantic_count`,
`ready_request_payload_validation_record_margin_semantic_count`,
`runtime_observed_request_payload_validation_record_margin_semantic_count`,
`request_payload_validation_record_margin_semantics`,
`margin_semantics_ref`, `margin_semantics_contract_ref`,
`evidence_routes`, `margin_semantics_contract_available=false`,
`margin_semantics_contract_ready=false`, `margin_account_bound=false`,
`margin_requirement_bound=false`, `margin_mode_bound=false`,
`margin_buffer_bound=false`, `runtime_margin_evidence_observed=false`,
`runtime_evidence_satisfies_margin_semantics=false`, and
`validation_record_margin_semantics_ready=false`. Completed position-semantics
rows expose
`request_payload_validation_record_position_semantic_count`,
`blocking_request_payload_validation_record_position_semantic_count`,
`ready_request_payload_validation_record_position_semantic_count`,
`runtime_observed_request_payload_validation_record_position_semantic_count`,
`request_payload_validation_record_position_semantics`,
`position_semantics_ref`, `position_semantics_contract_ref`,
`evidence_routes`, `position_semantics_contract_available=false`,
`position_semantics_contract_ready=false`, `position_identity_bound=false`,
`position_scope_bound=false`, `position_side_derivation_bound=false`,
`position_size_bound=false`, `position_notional_bound=false`,
`runtime_position_evidence_observed=false`,
`runtime_evidence_satisfies_position_semantics=false`, and
`validation_record_position_semantics_ready=false`. Completed semantic
artifact runtime evidence acceptance rows expose
`request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count`,
`blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count`,
`ready_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count`,
`runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count`,
`request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances`,
`semantic_artifact_runtime_evidence_acceptance_ref`,
`semantic_artifact_runtime_evidence_acceptance_contract_ref`,
`semantic_artifact_runtime_evidence_acceptance_available=false`, and
`semantic_artifact_runtime_evidence_acceptance_accepted=false`. Completed
semantic artifact runtime evidence rows expose
`request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
`blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
`ready_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
`runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
`request_payload_validation_record_semantic_artifact_runtime_evidences`,
`semantic_artifact_runtime_evidence_ref`,
`semantic_artifact_runtime_evidence_contract_ref`,
`semantic_artifact_runtime_evidence_available=false`,
`semantic_artifact_runtime_evidence_bound=false`, and
`semantic_artifact_runtime_evidence_accepted=false`. Completed semantic
artifact definition review output acceptance rows expose
`request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
`blocking_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
`ready_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
`runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
`request_payload_validation_record_semantic_artifact_definition_review_output_acceptances`,
`semantic_artifact_definition_review_output_acceptance_ref`,
`semantic_artifact_definition_review_output_acceptance_contract_ref`,
`semantic_artifact_definition_review_output_acceptance_available=false`, and
`semantic_artifact_definition_review_output_acceptance_accepted=false`.
Completed semantic artifact definition review output rows expose
`request_payload_validation_record_semantic_artifact_definition_review_output_count`,
`blocking_request_payload_validation_record_semantic_artifact_definition_review_output_count`,
`ready_request_payload_validation_record_semantic_artifact_definition_review_output_count`,
`runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_count`,
`request_payload_validation_record_semantic_artifact_definition_review_outputs`,
`semantic_artifact_definition_review_output_ref`,
`semantic_artifact_definition_review_output_contract_ref`,
`semantic_artifact_definition_review_output_available=false`, and
`semantic_artifact_definition_review_output_accepted=false`. Completed semantic
artifact definition review input rows expose
`request_payload_validation_record_semantic_artifact_definition_review_input_count`,
`blocking_request_payload_validation_record_semantic_artifact_definition_review_input_count`,
`ready_request_payload_validation_record_semantic_artifact_definition_review_input_count`,
`runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_input_count`,
`request_payload_validation_record_semantic_artifact_definition_review_inputs`,
`semantic_artifact_definition_review_input_ref`,
`semantic_artifact_definition_review_input_contract_ref`,
`semantic_artifact_definition_review_input_available=false`, and
`semantic_artifact_definition_review_input_accepted=false`. Completed semantic
artifact definition review rows expose
`request_payload_validation_record_semantic_artifact_definition_review_count`,
`blocking_request_payload_validation_record_semantic_artifact_definition_review_count`,
`ready_request_payload_validation_record_semantic_artifact_definition_review_count`,
`runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_count`,
`request_payload_validation_record_semantic_artifact_definition_reviews`,
`semantic_artifact_definition_review_ref`,
`semantic_artifact_definition_review_contract_ref`,
`semantic_artifact_definition_review_input_ref`,
`semantic_artifact_definition_review_output_ref`,
`contextless_review_required=true`,
`semantic_artifact_definition_available=false`,
`semantic_artifact_definition_review_available=false`,
`semantic_artifact_definition_reviewed=false`,
`semantic_artifact_definition_review_passed=false`, and
`semantic_artifact_runtime_evidence_bound=false`. Completed semantic artifact
definition rows expose
`request_payload_validation_record_semantic_artifact_definition_count`,
`blocking_request_payload_validation_record_semantic_artifact_definition_count`,
`ready_request_payload_validation_record_semantic_artifact_definition_count`,
`runtime_observed_request_payload_validation_record_semantic_artifact_definition_count`,
`request_payload_validation_record_semantic_artifact_definitions`,
`semantic_artifact_definition_ref`, and
`semantic_artifact_definition_contract_ref`. Completed semantic artifact rows expose
`request_payload_validation_record_semantic_artifact_count`,
`blocking_request_payload_validation_record_semantic_artifact_count`,
`ready_request_payload_validation_record_semantic_artifact_count`,
`runtime_observed_request_payload_validation_record_semantic_artifact_count`,
`request_payload_validation_record_semantic_artifacts`,
`semantic_artifact_ref`, and `semantic_artifact_contract_ref`. These rows are
blocked evidence only; they do not define futures semantics, resolve execution
eligibility blockers, validate request payloads, accept liquidation semantics,
bind live account/risk evidence, accept collateral semantics, bind live
account/collateral evidence, accept margin semantics, accept position
semantics, bind live position evidence, accept or bind runtime evidence,
accept runtime-evidence acceptances, admit commands, call Coinbase, execute
reconciliation, mutate futures state, or grant browser/BFF authority.
Exact autonomous phrase: Active M57 `6861-6880` evidence adds disabled futures request payload validation record liquidation semantics while completed M57 `6841-6860` carries forward disabled futures request payload validation record collateral semantics.

Representative no-live response keys include
`"request_field_count"`, `"blocking_request_field_count"`,
`"request_payload_validator_contract_count"`,
`"blocking_request_payload_validator_contract_count"`,
`"ready_request_payload_validator_contract_count"`,
`"registered_request_payload_validator_contract_count"`,
`"request_payload_validator_contracts"`,
`"request_payload_validator_input_schema_count"`,
`"blocking_request_payload_validator_input_schema_count"`,
`"ready_request_payload_validator_input_schema_count"`,
`"registered_request_payload_validator_input_schema_count"`,
`"request_payload_validator_input_schemas"`,
`"request_payload_validator_output_schema_count"`,
`"blocking_request_payload_validator_output_schema_count"`,
`"ready_request_payload_validator_output_schema_count"`,
`"registered_request_payload_validator_output_schema_count"`,
`"request_payload_validator_output_schemas"`,
`"request_payload_validator_registration_count"`,
`"blocking_request_payload_validator_registration_count"`,
`"ready_request_payload_validator_registration_count"`,
`"registered_request_payload_validator_registration_count"`,
`"runtime_observed_request_payload_validator_registration_count"`,
`"request_payload_validator_registrations"`,
`"request_payload_validation_evidence_count"`,
`"blocking_request_payload_validation_evidence_count"`,
`"ready_request_payload_validation_evidence_count"`,
`"recorded_request_payload_validation_evidence_count"`,
`"runtime_observed_request_payload_validation_evidence_count"`,
`"request_payload_validation_evidence"`,
`"request_payload_validation_evidence_record_count"`,
`"blocking_request_payload_validation_evidence_record_count"`,
`"request_payload_validation_record_admission_link_count"`,
`"blocking_request_payload_validation_record_admission_link_count"`,
`"ready_request_payload_validation_record_admission_link_count"`,
`"admission_bound_request_payload_validation_record_count"`,
`"runtime_observed_request_payload_validation_record_admission_link_count"`,
`"request_payload_validation_record_admission_links"`,
`"request_payload_validation_record_execution_eligibility_count"`,
`"blocking_request_payload_validation_record_execution_eligibility_count"`,
`"ready_request_payload_validation_record_execution_eligibility_count"`,
`"execution_eligible_request_payload_validation_record_count"`,
`"runtime_observed_request_payload_validation_record_execution_eligibility_count"`,
`"request_payload_validation_record_execution_eligibilities"`,
`"request_payload_validation_record_audit_link_count"`,
`"blocking_request_payload_validation_record_audit_link_count"`,
`"ready_request_payload_validation_record_audit_link_count"`,
`"audit_bound_request_payload_validation_record_count"`,
`"runtime_observed_request_payload_validation_record_audit_link_count"`,
`"request_payload_validation_record_audit_links"`,
`"ready_request_payload_validation_evidence_record_count"`,
`"stored_request_payload_validation_evidence_record_count"`,
`"runtime_observed_request_payload_validation_evidence_record_count"`,
`"request_payload_validation_evidence_records"`,
`"request_payload_validation_record_schema_count"`,
`"blocking_request_payload_validation_record_schema_count"`,
`"ready_request_payload_validation_record_schema_count"`,
`"registered_request_payload_validation_record_schema_count"`,
`"runtime_observed_request_payload_validation_record_schema_count"`,
`"request_payload_validation_record_schemas"`,
`"request_payload_validation_record_replay_guard_count"`,
`"blocking_request_payload_validation_record_replay_guard_count"`,
`"ready_request_payload_validation_record_replay_guard_count"`,
`"idempotency_bound_request_payload_validation_record_count"`,
`"runtime_observed_request_payload_validation_record_replay_guard_count"`,
`"request_payload_validation_record_replay_guards"`,
`"request_payload_validation_record_audit_link_count"`,
`"blocking_request_payload_validation_record_audit_link_count"`,
`"ready_request_payload_validation_record_audit_link_count"`,
`"audit_bound_request_payload_validation_record_count"`,
`"runtime_observed_request_payload_validation_record_audit_link_count"`, and
`"request_payload_validation_record_audit_links"`.

Machine-check replay guard count keys:
`request_payload_validation_record_replay_guard_count`,
`blocking_request_payload_validation_record_replay_guard_count`,
`ready_request_payload_validation_record_replay_guard_count`,
`idempotency_bound_request_payload_validation_record_count`,
`runtime_observed_request_payload_validation_record_replay_guard_count`,
`request_payload_validation_record_replay_guards`,
`request_payload_validation_record_admission_link_count`,
`blocking_request_payload_validation_record_admission_link_count`,
`ready_request_payload_validation_record_admission_link_count`,
`admission_bound_request_payload_validation_record_count`,
`runtime_observed_request_payload_validation_record_admission_link_count`,
`request_payload_validation_record_admission_links`,
`request_payload_validation_record_execution_eligibility_count`,
`blocking_request_payload_validation_record_execution_eligibility_count`,
`ready_request_payload_validation_record_execution_eligibility_count`,
`execution_eligible_request_payload_validation_record_count`,
`runtime_observed_request_payload_validation_record_execution_eligibility_count`,
`request_payload_validation_record_execution_eligibilities`,
`request_payload_validation_record_audit_link_count`,
`blocking_request_payload_validation_record_audit_link_count`,
`ready_request_payload_validation_record_audit_link_count`,
`audit_bound_request_payload_validation_record_count`,
`runtime_observed_request_payload_validation_record_audit_link_count`,
`request_payload_validation_record_audit_links`.

Row evidence includes `"validation_gate_ref"`, `"validation_evidence_ref"`,
`"validator_contract_ref"`, `"validator_input_schema_ref"`,
`"validator_output_schema_ref"`, `"output_schema_field_refs"`,
`"output_schema_field_count"`, `"validator_registration_ref"`,
`"validator_registration_field_refs"`, `"validator_registration_field_count"`,
`"validation_evidence_contract_ref"`, `"validation_evidence_field_refs"`,
`"validation_evidence_field_count"`, `"validation_record_contract_ref"`,
`"validation_record_store_ref"`, `"validation_record_writer_ref"`,
`"validation_record_replay_guard_ref"`, `"validation_record_field_refs"`,
`"validation_record_field_count"`, `"validation_record_schema_ref"`,
`"validation_record_append_only_log_ref"`,
`"validation_record_replay_guard_contract_ref"`,
`"validation_record_idempotency_contract_ref"`,
`"validation_record_replay_window_ref"`,
`"validation_record_duplicate_policy_ref"`,
`"validation_record_schema_field_refs"`,
`"validation_record_schema_field_count"`,
`"validation_record_replay_guard_field_refs"`,
`"validation_record_replay_guard_field_count"`,
`"validation_record_audit_link_contract_ref"`,
`"validation_record_actor_ref"`,
`"validation_record_operator_intent_ref"`,
`"validation_record_correlation_ref"`,
`"validation_record_admission_audit_ref"`,
`"validation_record_audit_record_ref"`,
`"validation_record_audit_link_field_refs"`,
`"validation_record_audit_link_field_count"`,
`"validation_record_execution_eligibility_contract_ref"`,
`"validation_record_position_semantics_ref"`,
`"validation_record_margin_semantics_ref"`,
`"validation_record_collateral_semantics_ref"`,
`"validation_record_liquidation_semantics_ref"`,
`"validation_record_reduce_only_semantics_ref"`,
`"validation_record_close_only_semantics_ref"`,
`"validation_record_funding_semantics_ref"`,
`"validation_record_order_semantics_ref"`,
`"validation_record_cancel_semantics_ref"`,
`"validation_record_reconciliation_semantics_ref"`, and
`"validation_record_execution_eligibility_field_refs"`.

False authority flags remain `"validation_gate_ready": false`,
`"validation_gate_passed": false`, `"validator_contract_registered": false`,
`"validator_input_schema_registered": false`,
`"validator_output_schema_registered": false`,
`"output_schema_registered": false`, `"validator_registration_ready": false`,
`"runtime_evidence_satisfies_validator_registration": false`,
`"runtime_evidence_satisfies_validation_evidence": false`,
`"validation_evidence_ready": false`, `"validation_evidence_recorded": false`,
`"validation_record_contract_ready": false`,
`"validation_record_store_ready": false`,
`"validation_record_writer_enabled": false`,
`"validation_record_replay_guard_ready": false`,
`"validation_record_schema_ready": false`,
`"validation_record_schema_registered": false`,
`"validation_record_append_only_log_ready": false`,
`"runtime_evidence_satisfies_validation_record_schema": false`,
`"runtime_evidence_satisfies_validation_record_replay_guard": false`,
`"runtime_evidence_satisfies_validation_record_audit_link": false`,
`"validation_record_replay_guard_contract_ready": false`,
`"validation_record_idempotency_contract_ready": false`,
`"validation_record_replay_protected": false`,
`"validation_record_audit_link_contract_ready": false`,
`"validation_record_audit_link_ready": false`,
`"validation_record_actor_bound": false`,
`"validation_record_operator_intent_bound": false`,
`"validation_record_correlation_bound": false`,
`"validation_record_admission_audit_bound": false`,
`"validation_record_audit_recorded": false`,
`"runtime_evidence_satisfies_validation_record_execution_eligibility": false`,
`"validation_record_execution_eligibility_contract_ready": false`,
`"validation_record_execution_eligible": false`,
append_only_validation_record=false,
validation_record_idempotency_bound=false, request_payload_validated=false.
Machine-check evidence: futures request payload contract registry evidence;
futures request payload validation gate evidence; futures request payload
validator contract registry evidence; futures request payload validator
input-schema evidence; futures request payload validator output-schema evidence;
futures request payload validator registration evidence; futures request
payload validation evidence; futures request payload validation evidence record
contract evidence; futures request payload validation record schema evidence;
futures request payload validation record replay guard evidence; futures
request payload validation record audit-link evidence; futures request payload
validation record admission-link evidence; futures request payload validation
record execution-eligibility evidence. The rows keep
route/draft true and execution false flags; they do not validate command
request payloads, register payload validators, register proof routes, create
proof writers, call Coinbase, execute reconciliation, mutate
futures/order/exchange state, or grant spot-rule authority.

## Bootstrap And Session

Start the local backend target for frontend development:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
```

The runner binds `http://127.0.0.1:8787` by default and keeps mutating HTTP
routes live-disabled.

For frontend integration, set CORS to the exact local frontend origin:

```powershell
$env:COINBASE_ADMIN_API_CORS_ORIGINS = "http://127.0.0.1:3000"
```

The CORS contract is origin-allowlisted and permits `X-CSRF-Token` for
cookie/session or BFF bridge deployments. Current bearer-token bootstrap still
fails closed unless `COINBASE_ADMIN_API_BEARER_TOKEN` is configured on the
backend. When `COINBASE_ADMIN_API_CSRF_REQUIRED=true`, mutating `/api/v1/`
requests must include `X-CSRF-Token` matching
`COINBASE_ADMIN_API_CSRF_TOKEN`; read-only `GET` routes do not require it.

Use bootstrap and session reads to render environment, backend association,
live-action posture, and backend RBAC evidence. These routes do not require
idempotency headers and do not run Coinbase orders.
The local bootstrap verifier mode is `bootstrap_bearer`. Production-shaped
OIDC deployments use `COINBASE_ADMIN_API_AUTH_MODE=oidc_jwt`; that mode
verifies RS256 JWTs against configured issuer, audience, and JWKS settings
and derives actor/role evidence from claims.

OIDC/JWT readiness uses these backend environment names:

```powershell
$env:COINBASE_ADMIN_API_AUTH_MODE = "oidc_jwt"
$env:COINBASE_ADMIN_API_OIDC_ISSUER = "https://issuer.example.test"
$env:COINBASE_ADMIN_API_OIDC_AUDIENCE = "coinbase-admin-api"
$env:COINBASE_ADMIN_API_OIDC_JWKS_URL = "https://issuer.example.test/.well-known/jwks.json"
```

Missing values fail closed with `401`. Expected claim mapping is `sub` for
subject, `email` for email, `roles` for roles, `iss` for issuer, and `aud`
for audience. In OIDC mode the backend ignores browser-supplied
`X-Admin-Actor` and `X-Admin-Roles`; those values are derived from verified
JWT claims.

Run the no-live OIDC readiness smoke before treating production OIDC evidence
as available to the frontend release gate:

```powershell
python tools\run_admin_oidc_readiness_smoke.py --summary-only
```

Expected evidence:

- `ADMIN_OIDC_READINESS_SMOKE_SUMMARY` status `passed`
- missing OIDC config blocks
- configured temporary JWKS readiness reports `ready`
- `oidc_jwt` session claims define actor and roles
- live Coinbase execution not run; notional `$0`

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8787/api/v1/admin/bootstrap `
  -Headers @{
    Authorization = "Bearer local-admin-token"
    "X-Admin-Actor" = "viewer-001"
    "X-Admin-Roles" = "viewer"
  }
```

```http
GET /api/v1/admin/bootstrap
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected posture fields:

```json
{
  "type": "admin_bootstrap",
  "backend_repository": "s-aws/coinbase",
  "mutating_routes_live_disabled": true,
  "live_execution_enabled": false,
  "live_coinbase_orders_ran": false
}
```

```http
GET /api/v1/admin/session
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: trader-001
X-Admin-Roles: trader
```

The session response includes `actor`, `roles`, `permissions`, and
`bearer_token_visible_to_browser=false`.

```http
GET /api/v1/admin/csrf
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

This route returns the CSRF header name, whether CSRF is required, and the
token source/rotation policy. It never returns the token value.

```http
GET /api/v1/admin/oidc-readiness
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

This route returns backend OIDC verifier evidence for release checks:
active auth mode, required and missing OIDC settings, claim mapping, JWKS
reachability, and no-live notional posture.

```http
GET /api/v1/admin/capabilities
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Command capability rows are derived from `ADMIN_API_ROUTE_INVENTORY` and
include `action_class`, `permission`, `shared_method`, `idempotency`,
`approval`, `caps`, `audit`, `command_contract`, and `parity_test`. They are
metadata for frontend validation and diagnostics only; they do not enable live
Coinbase execution. `frontend_safe=true` means the row is safe for Admin
frontend/BFF contract exposure under backend authority, not that the command
is safe or approved for live trading.

The checked-in export
`openapi/coinbase-admin-api-route-inventory.json` is generated from the same
inventory and is the artifact consumed by frontend route-coverage checks.
Each route inventory artifact row includes `module_id`; frontend checks use it
to prove route ownership, not to authorize browser-side trading behavior.

```http
GET /api/v1/admin/live-enablement
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected current live-enablement posture:

```json
{
  "type": "admin_live_enablement",
  "status": "live_disabled",
  "approved_phase_range": "6541-6560",
  "default_live_coinbase_execution": "not_run",
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0",
  "quote_currency": "USDC",
  "product_scope": "cheapest Coinbase USDC spot product available to US customers",
  "max_submitted_notional_usdc": "3.10",
  "max_executed_notional_usdc": "1.00",
  "retain_inventory": true,
  "reconciliation_required": true,
  "live_enabled_path_count": 0,
  "live_eligible_path_count": 0,
  "preflight_check_count": 88,
  "blocking_preflight_check_count": 44,
  "passed_preflight_check_count": 44,
  "approval_snapshot_required_count": 11,
  "approval_snapshot_present_count": 0,
  "approval_snapshot_missing_count": 11,
  "approval_snapshot_required_field_count": 165,
  "approval_snapshot_missing_field_count": 165,
  "approval_store_required_count": 11,
  "approval_store_configured_count": 11,
  "approval_store_missing_count": 0,
  "approval_store_requirement_count": 132,
  "approval_store_missing_requirement_count": 0,
  "admission_audit_required_count": 11,
  "admission_audit_configured_count": 0,
  "admission_audit_missing_count": 11,
  "admission_audit_fact_count": 110,
  "admission_audit_missing_fact_count": 99,
  "cap_guard_required_count": 11,
  "cap_guard_configured_count": 0,
  "cap_guard_missing_count": 11,
  "cap_guard_requirement_count": 154,
  "cap_guard_missing_requirement_count": 154,
  "live_execution_adapter_required_count": 11,
  "live_execution_adapter_configured_count": 2,
  "live_execution_adapter_missing_count": 9,
  "readiness_precondition_count": 99,
  "blocking_readiness_precondition_count": 63,
  "passed_readiness_precondition_count": 36,
  "paths": [
    {
      "path_id": "post.api.v1.orders",
      "route": "/api/v1/orders",
      "method": "POST",
      "module_id": "spot_operations",
      "module": "Spot Operations",
      "module_owner": "strategy",
      "identity_key": "client_order_id",
      "action_class": "live_exchange_place",
      "required_permission": "order:create",
      "shared_method": "place_manual_order",
      "live_enabled": false,
      "live_eligible": false,
      "status": "approval_required",
      "governance_status": "blocked",
      "approval_required": true,
      "cap_required": true,
      "guard_required": true,
      "audit_required": true,
      "idempotency_key_required": true,
      "operator_intent_required": true,
      "payload_hash_required": true,
      "request_id_required": true,
      "audit_id_required": true,
      "reconciliation_required": true,
      "preflight_checks": [
        {
          "name": "auth_rbac",
          "category": "authorization",
          "status": "passed",
          "required": true,
          "blocking": false,
          "owner": "admin_api_contract",
          "evidence": "FastAPI route requires authenticated Admin API actor and backend RBAC.",
          "detail": "Live-shaped HTTP routes already fail closed without auth and permission evidence."
        },
        {
          "name": "idempotency_operator_intent",
          "category": "idempotency",
          "status": "passed",
          "required": true,
          "blocking": false,
          "owner": "admin_api_contract",
          "evidence": "Idempotency-Key, X-Operator-Intent, payload hash, and request id are captured before command service delegation.",
          "detail": "Current dry command contracts preserve replay/conflict evidence without placing Coinbase orders."
        },
        {
          "name": "durable_audit",
          "category": "audit",
          "status": "passed",
          "required": true,
          "blocking": false,
          "owner": "admin_api_contract",
          "evidence": "Command audit events are written before live-disabled responses are returned.",
          "detail": "Audit id and correlation id are available as operator evidence for dry-submit review."
        },
        {
          "name": "browser_authority",
          "category": "browser_authority",
          "status": "passed",
          "required": true,
          "blocking": false,
          "owner": "admin_api_contract",
          "evidence": "Frontend authority is display_only and command workflows require backend capability evidence.",
          "detail": "The browser may show preflight evidence but must not approve, place, cancel, or reconcile live orders."
        },
        {
          "name": "approval_snapshot",
          "category": "approval",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "owner": "admin_api_contract",
          "evidence": "No explicit M8 live approval snapshot is attached to this route.",
          "detail": "The route remains live-disabled until approval evidence is durable and route-specific."
        },
        {
          "name": "cap_guard_policy",
          "category": "cap_guard",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "owner": "strategy",
          "evidence": "Live cap and action-condition guard decisions are not yet wired as route-specific admission evidence.",
          "detail": "Guard, cap, wallet, position, and domain risk semantics must remain backend-owned before live enablement."
        },
        {
          "name": "live_execution_service",
          "category": "live_execution_service",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "owner": "strategy",
          "evidence": "place_manual_order is exposed only through the current live-disabled Admin API contract.",
          "detail": "No HTTP command route is admitted to live Coinbase execution in the enterprise Admin API path."
        },
        {
          "name": "post_live_reconciliation",
          "category": "reconciliation",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "owner": "strategy",
          "evidence": "Post-live reconciliation evidence is not wired for this route.",
          "detail": "A live path cannot be enabled until the exact route reports post-submit reconciliation evidence under cap."
        }
      ],
      "blocking_preflight_check_count": 4,
      "passed_preflight_check_count": 4,
      "readiness_precondition_count": 9,
      "blocking_readiness_precondition_count": 5,
      "passed_readiness_precondition_count": 4,
      "readiness_preconditions": [
        {
          "precondition": "approval_snapshot",
          "status": "blocked",
          "required": true,
          "configured": false,
          "blocking": true,
          "backend_owned": true,
          "route_bound": true,
          "source": "not_configured",
          "expected_source": "approval_snapshot",
          "blocker": "approval_snapshot_missing",
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "detail": "POST /api/v1/orders remains live-disabled until a durable route-specific approval snapshot is present."
        },
        {
          "precondition": "execution_intent_envelope",
          "status": "passed",
          "required": true,
          "configured": true,
          "blocking": false,
          "backend_owned": true,
          "route_bound": true,
          "source": "command_admission",
          "expected_source": "AdminApiCommandService.place_manual_order",
          "blocker": null,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "detail": "POST /api/v1/orders command admissions expose backend-owned execution intent evidence, but the intent remains non-executable while live execution is disabled."
        }
      ],
      "approval_snapshot": {
        "status": "blocked",
        "required": true,
        "present": false,
        "durable": false,
        "route_specific": true,
        "backend_owned": true,
        "browser_authority": "display_only",
        "source": "not_configured",
        "required_field_count": 15,
        "missing_required_field_count": 15,
        "required_fields": [
          {
            "field": "route",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "/api/v1/orders",
            "detail": "Approval must bind to the exact Admin API route."
          },
          {
            "field": "method",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "POST",
            "detail": "Approval must bind to the exact HTTP method."
          },
          {
            "field": "module_id",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "spot_operations",
            "detail": "Approval must bind to the backend-owned enterprise module id."
          },
          {
            "field": "identity_key",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "client_order_id",
            "detail": "Approval must bind to the module-specific command identity key."
          },
          {
            "field": "identity_value",
            "status": "blocked",
            "required": true,
            "expected_source": "command_identity",
            "expected_value": null,
            "detail": "Approval must bind to the exact route or request identity value."
          },
          {
            "field": "action_class",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "live_exchange_place",
            "detail": "Approval must bind to the live action class being requested."
          },
          {
            "field": "required_permission",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "order:create",
            "detail": "Approval must name the backend permission required for the route."
          },
          {
            "field": "requested_by_actor_id",
            "status": "blocked",
            "required": true,
            "expected_source": "authenticated_actor",
            "expected_value": null,
            "detail": "Approval must bind to the backend-authenticated requesting actor."
          },
          {
            "field": "operator_intent",
            "status": "blocked",
            "required": true,
            "expected_source": "command_headers",
            "expected_value": null,
            "detail": "Approval must bind to durable operator intent, not browser-only acknowledgement."
          },
          {
            "field": "idempotency_key",
            "status": "blocked",
            "required": true,
            "expected_source": "command_headers",
            "expected_value": null,
            "detail": "Approval must bind to the idempotency key for the submitted command."
          },
          {
            "field": "payload_hash",
            "status": "blocked",
            "required": true,
            "expected_source": "command_service",
            "expected_value": null,
            "detail": "Approval must bind to the command payload hash so payload drift is not approved."
          },
          {
            "field": "approved_by_actor_id",
            "status": "blocked",
            "required": true,
            "expected_source": "approval_store",
            "expected_value": null,
            "detail": "Approval must identify the backend-authenticated approver."
          },
          {
            "field": "expires_at",
            "status": "blocked",
            "required": true,
            "expected_source": "approval_store",
            "expected_value": null,
            "detail": "Approval must expire and must not be treated as an evergreen browser switch."
          },
          {
            "field": "cap_guard_decision_ref",
            "status": "blocked",
            "required": true,
            "expected_source": "guard_risk_policy",
            "expected_value": null,
            "detail": "Approval must bind to backend cap and guard decision evidence."
          },
          {
            "field": "reconciliation_plan_ref",
            "status": "blocked",
            "required": true,
            "expected_source": "reconciliation_policy",
            "expected_value": null,
            "detail": "Approval must bind to post-live reconciliation evidence for the route."
          }
        ],
        "evidence": [
          "No durable route-specific approval snapshot is present.",
          "Approval must be backend-owned, route-specific, expiring, and payload-bound.",
          "Browser acknowledgement is not sufficient live execution approval."
        ],
        "detail": "POST /api/v1/orders remains live-disabled until a durable route-specific approval snapshot is present."
      },
      "approval_store_contract": {
        "status": "passed",
        "required": true,
        "configured": true,
        "durable": true,
        "backend_owned": true,
        "browser_authority": "display_only",
        "source": "admin_api_approval_store",
        "requirement_count": 12,
        "missing_requirement_count": 0,
        "requirements": [
          {
            "requirement": "backend_owned",
            "status": "passed",
            "required": true,
            "expected_source": "admin_api_approval_store",
            "expected_value": null,
            "detail": "Approval storage is owned by the backend approval store."
          },
          {
            "requirement": "route_bound",
            "status": "passed",
            "required": true,
            "expected_source": "admin_api_approval_store",
            "expected_value": "/api/v1/orders",
            "detail": "Approval records bind approval to the exact route."
          },
          {
            "requirement": "payload_hash_bound",
            "status": "passed",
            "required": true,
            "expected_source": "admin_api_approval_store",
            "expected_value": null,
            "detail": "Approval records bind to the submitted command payload hash."
          },
          {
            "requirement": "append_only_audit",
            "status": "passed",
            "required": true,
            "expected_source": "admin_api_approval_store",
            "expected_value": null,
            "detail": "Approval records are stored as append-only JSONL evidence."
          },
          {
            "requirement": "browser_authority_rejected",
            "status": "passed",
            "required": true,
            "expected_source": "frontend_boundary",
            "expected_value": "display_only",
            "detail": "Approval storage must reject browser-only acknowledgement as live authority."
          }
        ],
        "evidence": [
          "Durable backend approval store contract is implemented.",
          "Approval records are backend-owned, route-bound, expiring, payload-bound, and append-only.",
          "No approval mutation endpoint or browser approval authority is exposed by this evidence."
        ],
        "detail": "POST /api/v1/orders has a durable approval store contract, but remains live-disabled until a route-specific approval snapshot, cap/guard decision, full admission audit trail, and reconciliation plan are linked."
      },
      "admission_audit_trail": {
        "status": "blocked",
        "required": true,
        "configured": false,
        "append_only": true,
        "backend_owned": true,
        "browser_authority": "display_only",
        "source": "admin_api_audit_log_partial",
        "fact_count": 10,
        "missing_fact_count": 9,
        "facts": [
          {
            "fact": "route_admission_requested",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "POST /api/v1/orders",
            "detail": "Audit trail must record the exact route admission request."
          },
          {
            "fact": "approval_store_decision_linked",
            "status": "blocked",
            "required": true,
            "expected_source": "approval_store",
            "expected_value": null,
            "detail": "Audit trail must link the backend approval-store decision, approving actor, and requesting actor."
          },
          {
            "fact": "command_admission_decision_recorded",
            "status": "passed",
            "required": true,
            "expected_source": "admin_api_audit_log",
            "expected_value": "spot_operations",
            "detail": "Append-only Admin API audit records now store the backend admission decision before Coinbase submission."
          },
          {
            "fact": "exchange_submission_linked",
            "status": "blocked",
            "required": true,
            "expected_source": "coinbase_adapter",
            "expected_value": null,
            "detail": "Audit trail must link the exchange submission result when live execution is admitted."
          },
          {
            "fact": "browser_authority_rejection_recorded",
            "status": "blocked",
            "required": true,
            "expected_source": "frontend_boundary",
            "expected_value": "display_only",
            "detail": "Audit trail must record that browser acknowledgement is not live authority."
          }
        ],
        "evidence": [
          "Command admission decisions are recorded in the append-only Admin API audit log.",
          "Full live admission remains blocked until approval, cap/guard, exchange submission, and reconciliation facts are linked.",
          "Browser evidence remains display-only and cannot write or satisfy admission audit facts."
        ],
        "detail": "POST /api/v1/orders remains live-disabled until the backend can write and verify the full append-only live-admission audit trail."
      },
      "cap_guard_contract": {
        "status": "blocked",
        "required": true,
        "configured": false,
        "route_specific": true,
        "backend_owned": true,
        "browser_authority": "display_only",
        "source": "not_configured",
        "requirement_count": 14,
        "missing_requirement_count": 14,
        "requirements": [
          {
            "requirement": "backend_owned",
            "status": "blocked",
            "required": true,
            "expected_source": "guard_risk_policy",
            "expected_value": null,
            "detail": "Cap and guard decisions must be owned and enforced by the backend."
          },
          {
            "requirement": "route_bound",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "/api/v1/orders",
            "detail": "Cap and guard decisions must bind to the exact Admin API route."
          },
          {
            "requirement": "notional_cap_bound",
            "status": "blocked",
            "required": true,
            "expected_source": "guard_risk_policy",
            "expected_value": "3.10",
            "detail": "Cap and guard decisions must enforce approved submitted/executed notional caps."
          },
          {
            "requirement": "domain_guard_bound",
            "status": "blocked",
            "required": true,
            "expected_source": "guard_risk_policy",
            "expected_value": null,
            "detail": "Spot order guard must bind notional caps, product capability, wallet budget, no-shorting SELL inventory authority, cost-basis policy, and manual live acknowledgement to the submitted payload."
          },
          {
            "requirement": "browser_authority_rejected",
            "status": "blocked",
            "required": true,
            "expected_source": "frontend_boundary",
            "expected_value": "display_only",
            "detail": "Cap and guard decisions must reject browser-computed authority."
          }
        ],
        "evidence": [
          "No route-specific backend cap/guard decision contract is configured for this route.",
          "Cap/guard decisions must be backend-owned, route-bound, payload-bound, approval-linked, and admission-audit-linked.",
          "Browser-side wallet, margin, profitability, or cap calculations cannot satisfy live admission guards."
        ],
        "detail": "POST /api/v1/orders remains live-disabled until a route-specific backend cap/guard decision contract is implemented and configured."
      },
      "live_execution_adapter": {
        "required": true,
        "configured": true,
        "backend_owned": true,
        "route_bound": true,
        "status": "approval_required",
        "source": "m53_backend_pilot_dry_run",
        "missing_reason": "pilot_dry_run_only",
        "module_id": "spot_operations",
        "route": "/api/v1/orders",
        "method": "POST",
        "service_method": "place_manual_order",
        "adapter_reference": "AdminApiCommandService.place_manual_order",
        "action_class": "live_exchange_place",
        "executable": false,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "forbidden_methods": [
          "create_order",
          "cancel_order",
          "execute",
          "submit",
          "coinbase_client"
        ],
        "evidence": [
          "Live-shaped route is mapped to the shared backend command service.",
          "The M53 pilot adapter is route-bound dry-run evidence only and remains non-executable.",
          "Browser and BFF layers cannot create a route-local execution adapter."
        ],
        "detail": "POST /api/v1/orders is mapped to AdminApiCommandService.place_manual_order through the M53 dry-run pilot adapter, but the Admin API live execution service remains disabled and non-executable."
      },
      "browser_authority": "display_only",
      "capability_source": "GET /api/v1/admin/capabilities",
      "readiness_source": "GET /api/v1/admin/enterprise-readiness",
      "reconciliation_blockers": [
        "post-live reconciliation evidence is not wired for this route",
        "explicit M8 live approval snapshot is not present for this route",
        "backend cap, guard, idempotency, operator-intent, and audit evidence must be enforced before live enablement",
        "spot wallet, inventory, no-shorting, and cost-basis authority must remain backend-owned"
      ],
      "spot_rule_boundary": "Spot-only wallet, USDC, no-shorting, inventory, cost-basis, and average-cost rules apply only to spot command authority.",
      "product_scope": "cheapest Coinbase USDC spot product available to US customers",
      "max_submitted_notional_usdc": "3.10",
      "max_executed_notional_usdc": "1.00",
      "evidence": [
        "M4 guard/risk evidence required",
        "M6 command contract proof required",
        "M8 explicit live approval required",
        "idempotency, operator intent, payload hash, request id, and audit id required",
        "post-live reconciliation required"
      ],
      "notes": "Current Admin API command contract is live-disabled; this read route is governance evidence only and does not grant browser command authority."
    }
  ],
  "checks": [
    {
      "name": "live_execution_default",
      "status": "passed",
      "detail": "Default live Coinbase execution is not_run with submitted/executed notional $0."
    },
    {
      "name": "reconciliation_gate",
      "status": "blocked",
      "detail": "No path is live-enabled until post-live reconciliation evidence is wired for that path."
    }
  ],
  "read_only": true,
  "live_coinbase_orders_ran": false
}
```

This route is evidence only. It lists command paths that could later be
considered for controlled live enablement, but every current path remains
`live_enabled=false` until explicit live approval, cap, guard, audit, and
reconciliation gates pass. M27 governance fields make that fail-closed posture
auditable per route; they do not approve live execution. M29 preflight fields
make passed and blocking prerequisites visible per route; they are not a
browser approval workflow, live switch, command route, Coinbase call, or
reconciliation substitute. M30 approval snapshot fields make the missing
durable, route-specific, backend-owned, expiring, payload-bound approval
record explicit; they are not approval storage or browser approval. M36
approval-store foundation fields make configured durable backend
approval-store infrastructure explicit; they are not approval mutation,
browser approval, command authority, Coinbase execution, or reconciliation proof.
M37 approval snapshot resolver infrastructure is backend-only and can derive
immutable evidence from exact unexpired store records; it is not proof that
command admission may proceed. M38 command admission wiring can report whether
that resolver found a snapshot, but a found snapshot only changes evidence and
does not remove live-disabled, admission-audit, cap/guard, reconciliation, or
browser-authority blockers. M39 command admission audit wiring can report
whether exact append-only admission audit proof was found, but a found audit
proof only changes evidence and does not remove live-disabled, cap/guard,
reconciliation, or browser-authority blockers. M32
admission-audit trail fields make the missing append-only backend admission
audit facts explicit; they are not audit storage, approval storage, browser
approval, command authority, Coinbase execution, or reconciliation proof.
M33 cap/guard contract fields make the missing route-specific backend cap and
guard decision bindings explicit; they are not guard execution, browser wallet
or profitability authority, browser approval, command authority, Coinbase
execution, or reconciliation proof.
M44 live execution adapter contract fields make the route-to-shared-command
service boundary explicit; they are not route-local execution, browser
approval, BFF execution authority, Coinbase calls, or order/exchange-state
mutation.
M45 live execution intent fields make the command-to-live-execution intent
explicit under command admission decisions; they are not an executable
adapter, browser approval, BFF execution authority, Coinbase call, or
order/exchange-state mutation.
M46 live readiness precondition fields normalize the route's existing
approval-store, approval-snapshot, admission-audit, cap/guard,
reconciliation, adapter, intent, browser/BFF, and disabled live-service
evidence into a checklist. They are derived from `GET
/api/v1/admin/live-enablement`; they are not a new endpoint, command
admission call, browser approval workflow, BFF execution authority, live
switch, Coinbase call, or route-local executor.

M34 command admission decision fields appear on live-disabled HTTP command
responses. They bind the command route, module, identity key, actor,
idempotency key, operator intent, and payload hash to the current blockers.
They are not browser approval, command authority, guard execution,
reconciliation authority, or live Coinbase execution.

Example command admission intent fragment:

```json
{
  "admission_decision": {
    "live_execution_intent": {
      "required": true,
      "prepared": false,
      "executable": false,
      "status": "live_disabled",
      "source": "disabled_backend_service",
      "missing_reason": "live_execution_disabled",
      "route": "/api/v1/orders",
      "method": "POST",
      "identity_key": "client_order_id",
      "service_method": "place_manual_order",
      "adapter_reference": "AdminApiCommandService.place_manual_order",
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "live_exchange_submitted": false,
      "blockers": [
        "live_execution_disabled",
        "browser_authority_rejected"
      ]
    }
  }
}
```

M35 persists command admission decisions to the existing append-only Admin API
audit log. M36 adds backend-owned append-only approval-store infrastructure,
so approval-store contract evidence may pass while route-specific approval
snapshots remain absent and live execution remains disabled. M37 adds
backend-only snapshot resolver infrastructure over exact unexpired approval
records. M38 wires live-disabled command admission evidence to that resolver
without adding live admission. M39 wires live-disabled command admission
evidence to backend-owned audit proof without adding audit mutation. M40 wires
live-disabled command admission evidence to backend-owned cap/guard proof
without adding guard mutation, browser guard authority, live admission, or
Coinbase execution. M41 wires live-disabled command admission evidence to
backend-owned reconciliation plan proof without adding reconciliation
execution, browser reconciliation authority, live admission, order-state
mutation, or Coinbase execution. M42 makes the disabled backend live
execution service boundary explicit without adding a live switch, browser
approval, BFF execution authority, or Coinbase execution. M43 introduces a
backend-owned disabled service descriptor without adding create, cancel,
submit, execute, browser, BFF, or Coinbase authority methods. M44 adds
live-enablement adapter evidence without making route-to-service mapping
executable. M45 adds command admission execution-intent evidence without
making command-to-service intent executable. M46 adds normalized
live-readiness checklist evidence without making any prerequisite executable
or admissive. M47 adds a backend-owned functionality inventory and gap ledger
without adding mutation or live authority. None of these
milestones adds an approval endpoint, browser approval, or Coinbase execution
path.

```http
GET /api/v1/admin/enterprise-readiness
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected current enterprise readiness posture:

```json
{
  "type": "admin_enterprise_readiness",
  "candidate": "enterprise_admin_m9",
  "approved_phase_range": "6541-6560",
  "status": "warning",
  "supported_module_count": 7,
  "unsupported_module_count": 1,
  "command_gap_count": 17,
  "module_registry_count": 8,
  "module_action_posture_count": 8,
  "functionality_inventory_count": 25,
  "backend_supported_workflow_count": 25,
  "admin_exposed_workflow_count": 23,
  "command_workflow_count": 17,
  "live_designated_workflow_count": 8,
  "recovery_workflow_count": 1,
  "automation_workflow_count": 1,
  "repair_workflow_count": 1,
  "mutation_taxonomy_count": 44,
  "route_bound_mutation_taxonomy_count": 43,
  "live_disabled_mutation_count": 33,
  "backend_contract_required_mutation_count": 1,
  "compatibility_mutation_count": 3,
  "functionality_inventory": [
    {
      "workflow_id": "spot.order_command_drafts",
      "module_id": "spot_operations",
      "module": "Spot Operations",
      "workflow_type": "command_draft",
      "exposure_status": "admin_draft_live_disabled",
      "support_status": "command_draft_live_disabled",
      "backend_supported": true,
      "admin_api_exposed": true,
      "frontend_exposed": true,
      "command_capable": true,
      "live_designated": true,
      "live_enabled": false,
      "identity_keys": ["client_order_id", "campaign_id", "sweep_config_id"],
      "command_routes": [
        "POST /api/v1/orders",
        "POST /api/v1/orders/{client_order_id}/cancel",
        "POST /api/v1/spot/campaign/executions",
        "POST /api/v1/spot/sweep/automation-runs"
      ],
      "required_next_contract": "Approval, cap/guard, audit, reconciliation, and live adapter admission must all pass before execution.",
      "blockers": [
        "live_execution_disabled",
        "approval_snapshot_missing",
        "cap_guard_missing",
        "reconciliation_plan_missing"
      ],
      "frontend_boundary": "Keep buttons dry-submit/live-disabled unless backend capability and live-enablement evidence explicitly admit execution.",
      "spot_rule_boundary": "Spot commands must preserve no-shorting and inventory authority.",
      "live_coinbase_execution": "not_run",
      "notional_usdc": "0"
    },
    {
      "workflow_id": "admin.live_service_decisions",
      "module_id": "admin_system_health",
      "module": "Admin / System Health",
      "workflow_type": "command_draft",
      "exposure_status": "admin_exposed",
      "support_status": "platform_ready",
      "backend_supported": true,
      "admin_api_exposed": true,
      "frontend_exposed": true,
      "command_capable": true,
      "live_designated": false,
      "live_enabled": false,
      "identity_keys": [
        "decision_id",
        "deployment_ref",
        "runtime_configuration_ref"
      ],
      "read_routes": [
        "GET /api/v1/admin/live-execution/service-decisions",
        "GET /api/v1/admin/live-execution/service-decisions/{decision_id}"
      ],
      "command_routes": [
        "POST /api/v1/admin/live-execution/service-decisions"
      ],
      "required_next_contract": "Controlled live adapter admission must still pass live service, live adapter, verification, and browser-boundary gates.",
      "blockers": [
        "live_execution_disabled",
        "live_service_enablement_missing",
        "live_adapter_construction_missing"
      ],
      "frontend_boundary": "The browser may display and forward disabled live-service decision evidence only; it must not enable service or clear live-readiness blockers.",
      "spot_rule_boundary": "Live-service decision records are platform evidence. Spot wallet, USDC, cost-basis, and no-shorting rules stay in route-specific guard inputs.",
      "live_coinbase_execution": "not_run",
      "notional_usdc": "0"
    },
    {
      "workflow_id": "futures.commands_not_modeled",
      "module_id": "futures_perpetuals",
      "module": "Futures / Perpetuals",
      "workflow_type": "command_draft",
      "exposure_status": "backend_contract_required",
      "support_status": "not_modeled",
      "backend_supported": false,
      "admin_api_exposed": false,
      "frontend_exposed": false,
      "command_capable": true,
      "live_designated": false,
      "live_enabled": false,
      "required_next_contract": "Backend command contracts over position side, margin, leverage, liquidation, reduce-only, close-only, funding, cap, approval, audit, and reconciliation evidence.",
      "blockers": ["backend futures command contract missing"],
      "frontend_boundary": "Do not add futures command drafts from spot order/cancel patterns.",
      "spot_rule_boundary": "Spot rules are forbidden in futures command authority.",
      "live_coinbase_execution": "not_run",
      "notional_usdc": "0"
    }
  ],
  "mutation_taxonomy": [
    {
      "mutation_id": "spot.order_cancel",
      "mutation_family": "spot_order_cancel",
      "workflow_id": "spot.order_command_drafts",
      "module_id": "spot_operations",
      "module": "Spot Operations",
      "exposure_status": "admin_draft_live_disabled",
      "support_status": "command_draft_live_disabled",
      "command_surfaces": [
        "POST /api/v1/orders/{client_order_id}/cancel"
      ],
      "action_classes": ["live_exchange_cancel"],
      "required_permissions": ["order:cancel"],
      "identity_keys": ["client_order_id", "campaign_id", "sweep_config_id"],
      "payload_binding_fields": [
        "endpoint",
        "actor",
        "operator_intent",
        "body",
        "path_params"
      ],
      "idempotency_required": true,
      "operator_intent_required": true,
      "rbac_required": true,
      "approval_required": true,
      "cap_guard_required": true,
      "admission_audit_required": true,
      "reconciliation_required": true,
      "live_adapter_required": true,
      "owning_backend_service": "application/admin_api/command_service.py",
      "shared_command_service_method": "cancel_order_by_client_order_id",
      "browser_authority": "display_only",
      "bff_execution_authority": "forward_only_no_execution",
      "route_local_execution_allowed": false,
      "blockers": [
        "live_execution_disabled",
        "approval_snapshot_missing",
        "cancel reconciliation proof missing"
      ],
      "frontend_boundary": "Do not accept exchange order_id as the internal cancel identity; frontend cancel evidence must stay client_order_id-scoped.",
      "live_coinbase_execution": "not_run",
      "notional_usdc": "0"
    },
    {
      "mutation_id": "admin.live_service_decisions",
      "mutation_family": "admin_live_service_decision",
      "workflow_id": "admin.live_service_decisions",
      "module_id": "admin_system_health",
      "module": "Admin / System Health",
      "exposure_status": "admin_exposed",
      "support_status": "platform_ready",
      "command_surfaces": [
        "POST /api/v1/admin/live-execution/service-decisions"
      ],
      "action_classes": ["local_state_mutation"],
      "required_permissions": ["config:update"],
      "identity_keys": [
        "decision_id",
        "deployment_ref",
        "runtime_configuration_ref"
      ],
      "idempotency_required": true,
      "operator_intent_required": true,
      "rbac_required": true,
      "approval_required": true,
      "cap_guard_required": true,
      "admission_audit_required": true,
      "reconciliation_required": true,
      "live_adapter_required": false,
      "owning_backend_service": "application/admin_api/live_service_decision_service.py",
      "shared_command_service_method": "record_live_service_decision",
      "browser_authority": "display_only",
      "bff_execution_authority": "forward_only_no_execution",
      "route_local_execution_allowed": false,
      "blockers": [
        "live_execution_disabled",
        "live_service_enablement_missing",
        "live_adapter_construction_missing"
      ],
      "frontend_boundary": "The frontend may record and display disabled live-service decision evidence through generated contracts only; it must not enable service, approve Coinbase execution, or clear live-readiness blockers.",
      "live_coinbase_execution": "not_run",
      "notional_usdc": "0"
    },
    {
      "mutation_id": "futures.commands_contract_required",
      "mutation_family": "futures_contract_required",
      "workflow_id": "futures.commands_not_modeled",
      "module_id": "futures_perpetuals",
      "exposure_status": "backend_contract_required",
      "support_status": "not_modeled",
      "command_surfaces": [],
      "identity_keys": ["position_key", "product_id", "portfolio_id"],
      "required_next_contract": "Futures/perpetual command contracts over position side, margin, collateral, liquidation, reduce-only, close-only, funding, order, cancel, and reconciliation semantics.",
      "blockers": ["backend futures command contract missing"],
      "frontend_boundary": "Do not create futures command drafts by copying spot order, wallet, no-shorting, or cost-basis behavior.",
      "spot_rule_boundary": "Spot rules are forbidden in futures/perpetual command authority."
    }
  ],
  "modules": [
    {
      "module_id": "spot_operations",
      "module": "Spot Operations",
      "primary_owner": "strategy",
      "support_status": "command_draft_live_disabled",
      "unsupported_actions": [
        "spot short selling",
        "browser-side wallet or cost-basis authority",
        "frontend live order placement without backend M8 approval"
      ],
      "command_gaps": [
        {
          "action": "spot short selling",
          "status": "unsupported",
          "reason": "Spot accounts cannot sell assets the account does not hold.",
          "required_backend_contract": "No backend contract should enable spot short selling; spot sell authority remains inventory-backed.",
          "frontend_boundary": "Do not model a spot short draft or bypass backend wallet and inventory authority.",
          "live_coinbase_execution": "not_run",
          "notional_usdc": "0"
        }
      ],
      "identity_keys": ["client_order_id"],
      "backend_contract_refs": [
        "business/spot_portfolio_sweep.py",
        "business/spot_inventory_authority.py",
        "application/admin_api/command_service.py",
        "api/v1/routes/spot.py"
      ],
      "frontend_contract_refs": [
        "src/shared/api/contracts/backendApiClient.ts::getSpotReadiness",
        "src/shared/api/contracts/backendApiClient.ts::executeSpotCampaign",
        "src/features/spot-ops/spotBackendAdapters.ts"
      ],
      "documentation_refs": [
        "README.spot-trading.md",
        "README.spot-portfolio-sweep.md",
        "README.spot-campaign.md",
        "docs/examples/admin-api.md"
      ],
      "spot_rule_boundary": "Spot rules apply here only: no short selling, USDC spot scope, inventory authority, cost basis, and average-cost evidence must not be copied into non-spot modules.",
      "action_posture": {
        "module_id": "spot_operations",
        "support_status": "command_draft_live_disabled",
        "read_route_count": 12,
        "command_route_count": 5,
        "live_route_count": 4,
        "evidence_route_count": 12,
        "unsupported_action_count": 3,
        "command_gap_count": 2,
        "route_module_id_status": "passed",
        "route_module_id_detail": "17 route inventory rows are bound to module_id=spot_operations; enterprise readiness route lists are derived from module_id, not path prefixes.",
        "frontend_authority": "backend_contract_only",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0"
      }
    },
    {
      "module_id": "futures_perpetuals",
      "module": "Futures / Perpetuals",
      "primary_owner": "admin_api_contract",
      "support_status": "read_only_ready",
      "unsupported_actions": [
        "frontend futures placement",
        "frontend futures cancel/close/reduce",
        "spot inventory rules in futures workflows"
      ],
      "command_gaps": [
        {
          "action": "frontend futures placement",
          "status": "not_modeled",
          "reason": "Futures/perpetual placement needs backend-owned margin, leverage, liquidation, reduce-only, collateral, and approval contracts before UI drafting.",
          "required_backend_contract": "POST futures/perpetual placement contract with margin, leverage, liquidation, reduce-only, cap, approval, audit, and reconciliation evidence.",
          "frontend_boundary": "Do not add a futures/perpetual placement draft, dry-submit, or BFF route until the backend contract and capability row exist.",
          "live_coinbase_execution": "not_run",
          "notional_usdc": "0"
        }
      ],
      "identity_keys": ["position_key"],
      "backend_contract_refs": [
        "application/admin_api/read_service.py::build_futures_account",
        "application/admin_api/read_service.py::build_futures_positions",
        "api/v1/routes/futures.py"
      ],
      "frontend_contract_refs": [
        "src/shared/api/contracts/backendApiClient.ts::getFuturesAccount",
        "src/shared/api/contracts/backendRuntime.ts::loadFuturesPerpetualsReadSnapshot",
        "src/features/admin-shell/AdminShell.tsx"
      ],
      "documentation_refs": [
        "README.futures-perpetuals.md",
        "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
        "docs/examples/admin-api.md"
      ],
      "spot_rule_boundary": "Spot inventory, USDC, no-shorting, cost-basis, and average-cost rules are forbidden as futures/perpetual authority. Futures require position, margin, leverage, collateral, liquidation, and reduce-only backend contracts.",
      "action_posture": {
        "module_id": "futures_perpetuals",
        "support_status": "read_only_ready",
        "read_route_count": 3,
        "command_route_count": 0,
        "live_route_count": 0,
        "evidence_route_count": 3,
        "unsupported_action_count": 3,
        "command_gap_count": 3,
        "route_module_id_status": "passed",
        "route_module_id_detail": "4 route inventory rows are bound to module_id=futures_perpetuals; enterprise readiness route lists are derived from module_id, not path prefixes.",
        "frontend_authority": "backend_contract_only",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0"
      }
    },
    {
      "module_id": "legacy_dashboard_websocket",
      "module": "Legacy Dashboard WebSocket",
      "primary_owner": "dashboard_contract",
      "support_status": "unsupported",
      "unsupported_actions": [
        "enterprise frontend direct WebSocket command execution",
        "new admin module implementation through dashboard.py"
      ],
      "command_gaps": [
        {
          "action": "enterprise frontend direct WebSocket command execution",
          "status": "unsupported",
          "reason": "The legacy dashboard WebSocket is compatibility-only and is not the enterprise admin command plane.",
          "required_backend_contract": "Backend-owned Admin API route through auth, RBAC, idempotency, approval, caps, audit, and the shared command service.",
          "frontend_boundary": "Do not call dashboard.py or legacy dashboard WebSocket handlers from enterprise frontend product UI.",
          "live_coinbase_execution": "not_run",
          "notional_usdc": "0"
        }
      ],
      "identity_keys": ["client_order_id"],
      "backend_contract_refs": [
        "dashboard_server.py",
        "docs/LIVE_ORDER_SURFACES.md",
        "application/admin_api/command_service.py"
      ],
      "frontend_contract_refs": [
        "src/shared/api/contracts/adminBffProxy.ts",
        "src/shared/api/contracts/mutationContracts.ts",
        "src/features/command-workflows"
      ],
      "documentation_refs": [
        "docs/ADMIN_PLATFORM_ARCHITECTURE.md",
        "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
        "docs/examples/admin-api.md"
      ],
      "spot_rule_boundary": "Legacy dashboard behavior is compatibility-only. Spot rules exposed there are not reusable enterprise frontend authority and must be reintroduced only through Admin API contracts.",
      "action_posture": {
        "module_id": "legacy_dashboard_websocket",
        "support_status": "unsupported",
        "read_route_count": 0,
        "command_route_count": 3,
        "live_route_count": 3,
        "evidence_route_count": 0,
        "unsupported_action_count": 2,
        "command_gap_count": 2,
        "route_module_id_status": "passed",
        "route_module_id_detail": "3 route inventory rows are bound to module_id=legacy_dashboard_websocket; enterprise readiness route lists are derived from module_id, not path prefixes.",
        "frontend_authority": "backend_contract_only",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0"
      }
    }
  ],
  "security_checks": [
    {
      "name": "browser_authority_boundary",
      "status": "passed",
      "detail": "Enterprise admin frontend/Admin HTTP authority is backend_contract_only; this path does not approve, place, cancel, or reconcile Coinbase orders. Legacy browser live surfaces are compatibility-only and documented in docs/LIVE_ORDER_SURFACES.md."
    }
  ],
  "release_checks": [
    {
      "name": "frontend_release_gate",
      "status": "warning",
      "detail": "Run npm run release:gate after frontend/API changes before release."
    }
  ],
  "frontend_authority": "backend_contract_only",
  "live_posture": "live_disabled",
  "default_live_coinbase_execution": "not_run",
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0",
  "read_only": true,
  "live_coinbase_orders_ran": false
}
```

This route is module and release-candidate evidence only. Warning release
checks mean the external gate still has to be run; they are not browser-side
approval or live execution authority.

`GET /api/v1/admin/live-enablement` returns compact adapter evidence for
operator reads. In that read summary, `construction_contract` may be `null`
while `construction_contract_ref` still points at
`backend_live_adapter_construction_contract`; this keeps the live-enablement
read usable without hiding that full construction evidence is still required.

Dedicated adapter-construction evidence may include active M55
record-validation remediation dependency readback. Command responses and
idempotency replays keep `construction_contract` null and expose only the
construction-contract ref. The following JSON is a full construction-contract
excerpt, not the compact command response or live-enablement read shape. The
dependency rows derive from the remediation rows shown here, expose immediate
predecessor/successor links only, and do not perform remediation.

```json
{
  "live_execution_adapter_contract": {
    "construction_contract": {
      "acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_items": [
        {
          "source_ref": "acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validations",
          "status": "blocked",
          "remediation_id": "define_backend_route_contract_step_review_step_implementation_evidence_store_requirement_record_contract_record_validation_remediation",
          "record_validation_id": "define_backend_route_contract_step_review_step_implementation_evidence_store_requirement_record_contract_record_validation",
          "record_contract_id": "define_backend_route_contract_step_review_step_implementation_evidence_store_requirement_record_contract",
          "input_id": "define_backend_route_contract_step_review_step_implementation_evidence",
          "missing_backend_work": [
            "record_contract_available",
            "record_schema_available",
            "append_only_log_available",
            "idempotency_key_bound",
            "payload_schema_validated",
            "replay_protected",
            "store_available",
            "writer_allowed",
            "write_allowed",
            "record_present",
            "record_accepted",
            "record_validated"
          ],
          "remediation_gate": "define_backend_route_contract_step_review_step_implementation_evidence_store_requirement_record_contract_record_validation_remediation_gate",
          "blocker": "define_backend_route_contract_step_review_step_implementation_evidence_store_requirement_record_contract_record_validation_remediation_missing_record_validation_remediation",
          "validation_blocker": "define_backend_route_contract_step_review_step_implementation_evidence_store_requirement_record_contract_record_validation_missing_record_validation_readiness",
          "remediation_ready": false,
          "remediation_performed": false,
          "record_validation_ready": false,
          "write_allowed": false,
          "adapter_constructed": false,
          "live_execution_allowed": false,
          "executed": false,
          "no_live_execution": true,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution"
        }
      ],
      "acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_summary": {
        "status": "blocked",
        "total_remediation_item_count": 1152,
        "missing_remediation_item_count": 1152,
        "ready_remediation_item_count": 0,
        "record_validation_count": 1152,
        "all_remediations_ready": false,
        "remediation_performed": false,
        "construction_allowed": false,
        "adapter_constructed": false,
        "live_execution_allowed": false,
        "execution_allowed": false,
        "executed": false,
        "no_live_execution": true,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution"
      },
      "acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_dependencies": [
        {
          "source_ref": "acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_items",
          "status": "blocked",
          "dependency_id": "define_backend_route_contract_step_review_step_implementation_evidence_store_requirement_record_contract_record_validation_remediation_dependency",
          "remediation_id": "define_backend_route_contract_step_review_step_implementation_evidence_store_requirement_record_contract_record_validation_remediation",
          "record_validation_id": "define_backend_route_contract_step_review_step_implementation_evidence_store_requirement_record_contract_record_validation",
          "dependency_stage": "record_validation_remediation",
          "dependency_order": 1,
          "predecessor_remediation_ids": [],
          "successor_remediation_ids": [
            "define_backend_route_contract_step_review_backend_owner_review_evidence_store_requirement_record_contract_record_validation_remediation"
          ],
          "dependency_ready": false,
          "all_predecessors_ready": false,
          "dependency_graph_ready": false,
          "remediation_ready": false,
          "remediation_performed": false,
          "record_validation_ready": false,
          "construction_allowed": false,
          "adapter_constructed": false,
          "live_execution_allowed": false,
          "executed": false,
          "no_live_execution": true,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution"
        }
      ],
      "acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_dependency_summary": {
        "status": "blocked",
        "total_dependency_count": 1152,
        "blocked_dependency_count": 1152,
        "ready_dependency_count": 0,
        "remediation_item_count": 1152,
        "record_validation_count": 1152,
        "dependency_graph_ready": false,
        "all_dependencies_ready": false,
        "all_predecessors_ready": false,
        "any_action_ready": false,
        "all_remediations_ready": false,
        "remediation_performed": false,
        "record_validation_ready": false,
        "construction_allowed": false,
        "adapter_constructed": false,
        "live_execution_allowed": false,
        "execution_allowed": false,
        "executed": false,
        "no_live_execution": true,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution"
      },
      "acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_dependency_work_items": [
        {
          "source_ref": "acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_dependencies",
          "status": "blocked",
          "work_item_id": "define_backend_route_contract_step_review_step_implementation_evidence_store_requirement_record_contract_record_validation_remediation_dependency_work_item",
          "dependency_id": "define_backend_route_contract_step_review_step_implementation_evidence_store_requirement_record_contract_record_validation_remediation_dependency",
          "remediation_id": "define_backend_route_contract_step_review_step_implementation_evidence_store_requirement_record_contract_record_validation_remediation",
          "record_validation_id": "define_backend_route_contract_step_review_step_implementation_evidence_store_requirement_record_contract_record_validation",
          "work_stage": "record_validation_remediation_dependency",
          "work_queue_order": 1,
          "predecessor_dependency_ids": [],
          "successor_dependency_ids": [
            "define_backend_route_contract_step_review_backend_owner_review_evidence_store_requirement_record_contract_record_validation_remediation_dependency"
          ],
          "required_backend_work": [
            "record_contract_available",
            "record_schema_available",
            "append_only_log_available",
            "idempotency_key_bound",
            "payload_schema_validated",
            "replay_protected",
            "store_available",
            "writer_allowed",
            "write_allowed",
            "record_present",
            "record_accepted",
            "record_validated"
          ],
          "work_item_ready": false,
          "work_queue_ready": false,
          "handoff_ready": false,
          "dependency_ready": false,
          "remediation_performed": false,
          "record_validation_ready": false,
          "construction_allowed": false,
          "adapter_constructed": false,
          "live_execution_allowed": false,
          "executed": false,
          "no_live_execution": true,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution"
        }
      ],
      "acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_dependency_work_queue_summary": {
        "status": "blocked",
        "total_work_item_count": 1152,
        "blocked_work_item_count": 1152,
        "ready_work_item_count": 0,
        "dependency_count": 1152,
        "remediation_item_count": 1152,
        "record_validation_count": 1152,
        "work_queue_ready": false,
        "all_work_items_ready": false,
        "handoff_ready": false,
        "dependency_graph_ready": false,
        "all_dependencies_ready": false,
        "remediation_performed": false,
        "all_record_validations_ready": false,
        "construction_allowed": false,
        "adapter_constructed": false,
        "live_execution_allowed": false,
        "execution_allowed": false,
        "executed": false,
        "no_live_execution": true,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution"
      }
    }
  }
}
```

The same construction contract also exposes blocked claim-trace clearance
plans and ordered clearance steps:

```json
{
  "acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_steps": [
    {
      "status": "blocked",
      "step_order": 1,
      "step_name": "inspect_dependency_work_item_claim_trace",
      "required_ref_kind": "claim_trace_id",
      "depends_on_prior_step_ids": [],
      "blocks_next_step_ids": [
        "claim-trace-001_clearance_plan_define_record_validation_remediation_plan_step"
      ],
      "step_ready": false,
      "step_completed": false,
      "claim_resolved": false,
      "construction_allowed": false,
      "live_execution_allowed": false,
      "execution_allowed": false,
      "executed": false,
      "no_live_execution": true,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution"
    }
  ],
  "acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_summary": {
    "status": "blocked",
    "total_step_count": 9216,
    "blocked_step_count": 9216,
    "ready_step_count": 0,
    "completed_step_count": 0,
    "plan_count": 1152,
    "prerequisite_edge_count": 32256,
    "successor_edge_count": 8064,
    "all_steps_ready": false,
    "all_steps_completed": false,
    "execution_allowed": false,
    "executed": false,
    "no_live_execution": true,
    "browser_authority": "display_only",
    "bff_authority": "forward_only_no_execution"
  }
}
```

The same construction contract also exposes blocked claim-trace clearance-step
review-input store record validations derived from the blocked store record
contracts:

```json
{
  "acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validations": [
    {
      "status": "blocked",
      "record_validation_id": "claim-trace-review-input-store-record-contract-001_record_validation",
      "record_contract_id": "claim-trace-review-input-store-record-contract-001",
      "requirement_id": "claim-trace-review-input-store-requirement-001",
      "input_id": "claim-trace-review-input-001",
      "validation_checks": [
        "record_contract_available",
        "record_schema_available",
        "append_only_log_available",
        "idempotency_key_bound",
        "payload_schema_validated",
        "replay_protected",
        "store_available",
        "writer_allowed",
        "write_allowed",
        "record_present",
        "record_accepted",
        "record_validated"
      ],
      "record_validation_ready": false,
      "record_contract_available": false,
      "payload_schema_validated": false,
      "replay_protected": false,
      "record_accepted": false,
      "record_validated": false,
      "construction_allowed": false,
      "live_execution_allowed": false,
      "execution_allowed": false,
      "executed": false,
      "no_live_execution": true,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution"
    }
  ],
  "acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_summary": {
    "status": "blocked",
    "total_record_validation_count": 36864,
    "materialized_record_validation_count": 768,
    "missing_record_validation_count": 36864,
    "ready_record_validation_count": 0,
    "all_record_validations_ready": false,
    "all_record_contracts_available": false,
    "all_payload_schemas_validated": false,
    "all_replay_protected": false,
    "live_execution_allowed": false,
    "execution_allowed": false,
    "executed": false,
    "no_live_execution": true
  }
}
```

These remediation, dependency, dependency work-queue, clearance-plan, and
clearance-step fields, plus the store record-validation fields above, are
diagnostic readback only. They name and order missing backend work; they do not
complete steps, resolve claims, clear work items or dependencies, perform
remediation, create validators, bind idempotency, validate payloads, protect
replay, write or accept evidence, construct adapters, call Coinbase, or grant
browser/BFF execution authority.

## Cancel By Client Order ID

Current live-disabled command shape:

```http
POST /api/v1/orders/{client_order_id}/cancel
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1082
X-Correlation-Id: corr-20260610-001
X-Operator-Intent: operator_cancel
X-Admin-Actor: operator-001
X-Admin-Roles: trader
X-CSRF-Token: <configured-csrf-token-when-required>
Content-Type: application/json

{"reason":"operator_requested_cancel"}
```

Current backend behavior:

- parse the request through FastAPI/Pydantic
- authenticate actor and authorize `order:cancel`
- evaluate durable idempotency
- call the shared command service with HTTP live execution disabled
- write durable command audit evidence
- return `501` with `status: "not_implemented"`
- never call Coinbase

Future live execution must call the project Coinbase wrapper
`cancel_order(client_order_id)` after rate/cap policy is complete. The wrapper
must parse Coinbase cancel payloads and accept only explicit `success: true`
evidence as a successful exchange cancellation.

## Stealth Cancel By Stealth Order ID

Current live-disabled command shape:

```http
POST /api/v1/stealth/orders/{stealth_order_id}/cancel
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1083
X-Correlation-Id: corr-20260610-002
X-Operator-Intent: operator_stealth_cancel
X-Admin-Actor: operator-001
X-Admin-Roles: trader
X-CSRF-Token: <configured-csrf-token-when-required>
```

Current backend behavior:

- parse the request through FastAPI/Pydantic
- authenticate actor and authorize `order:cancel`
- evaluate durable idempotency
- call the shared command service with HTTP live execution disabled
- write durable command audit evidence with `stealth_order_id`
- return `501` with `status: "not_implemented"`
- never call Coinbase
- never mark a revealed placement hidden/cancelled or mutate stealth lifecycle
  state

This command draft is keyed by `stealth_order_id`. Active placement client ids
and exchange order ids are evidence only. Future live execution must reconcile
the live placement through the existing stealth lifecycle exchange-handling
path before local state can change.

## Stealth Reveal By Stealth Order ID

Current live-disabled command shape:

```http
POST /api/v1/stealth/orders/{stealth_order_id}/reveal
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1084
X-Correlation-Id: corr-20260610-003
X-Operator-Intent: operator_stealth_reveal
X-Admin-Actor: operator-001
X-Admin-Roles: trader
X-CSRF-Token: <configured-csrf-token-when-required>
Content-Type: application/json

{"reason":"trigger_window_open","manual_live_acknowledgement":true}
```

Current backend behavior:

- parse the request through FastAPI/Pydantic
- authenticate actor and authorize `order:create`
- evaluate durable idempotency
- call the shared command service with HTTP live execution disabled
- write durable command audit evidence with `stealth_order_id`
- return `501` with `status: "not_implemented"`
- never call `reveal_order_slice` or `StealthOrderManager`
- never submit Coinbase orders
- never mutate stealth lifecycle state

This command draft is keyed by `stealth_order_id`. Future live execution must
prove trigger evidence, exchange submission adapter behavior, active-placement
audit, approval, cap/guard, and reconciliation proof before the existing reveal
path can place an order or update lifecycle state.

## Stealth Move By Stealth Order ID

Current live-disabled command shape:

```http
POST /api/v1/stealth/orders/{stealth_order_id}/move
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1085
X-Correlation-Id: corr-20260610-004
X-Operator-Intent: operator_stealth_move
X-Admin-Actor: operator-001
X-Admin-Roles: trader
X-CSRF-Token: <configured-csrf-token-when-required>
Content-Type: application/json

{"new_limit_price":"50100.00","reason":"operator_requested_move"}
```

Current backend behavior:

- parse the request through FastAPI/Pydantic
- authenticate actor and authorize `order:cancel`
- evaluate durable idempotency
- call the shared command service with HTTP live execution disabled
- write durable command audit evidence with `stealth_order_id`
- return `501` with `status: "not_implemented"`
- never call `build_stealth_move_plan`, `execute_stealth_move`, or
  `StealthOrderManager`
- never submit or cancel Coinbase orders
- never perform cancel/replace or mutate stealth lifecycle state

This command draft is keyed by `stealth_order_id`. Future live execution must
prove mutation-claim, active-placement cancel/replace, approval, cap/guard,
admission audit, and reconciliation proof before the existing move path can
replace a live placement or update lifecycle state.

## Order Reads

Order reads are local/backend evidence routes. They are keyed by
`client_order_id`; exchange-native ids are exposed only as `exchange_order_id`
evidence.
If durable row-level audit metadata exists, read items may also include
optional `correlation_id` and `audit_id` fields for operator audit navigation.
Those ids are not order identity and must not be used for cancellation.

```http
GET /api/v1/orders?product_id=BTC-USDC&order_status=OPEN&limit=50&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

```http
GET /api/v1/orders/{client_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

The response model does not contain an `order_id` identity field. If exchange
evidence is known, it appears as `exchange_order_id` with
`exchange_order_id_evidence_only=true`. List responses include pagination
metadata: `limit`, `offset`, `returned_count`, `total_matching_count`,
`next_offset`, and `has_more`.

Frontend read-model interactions over these rows are display-only. Local
filtering, sorting, selected detail panels, responsive table scrolling, and
audit anchors must use backend-shaped row data already loaded through the
Admin API. They must not create a second fetch path, use exchange
`order_id` as identity, or infer wallet/guard/execution authority in the
browser.

## Stealth Order Reads

Stealth reads are local/backend lifecycle evidence routes. They are keyed by
`stealth_order_id`. Active placement client ids and exchange order ids are
evidence fields only. The enterprise Admin API exposes list/detail reads,
read-only command-suite readiness, and live-disabled stealth create, reveal,
move, cancel, recovery, and reconciliation command contracts. These command
contracts are modeled as Admin API routes, but they remain live-disabled until
their backend proof chains and live execution services exist.

```http
GET /api/v1/stealth/orders?product_id=BTC-USDC&stealth_status=REVEALED&limit=50&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

```http
GET /api/v1/stealth/orders/{stealth_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

```http
GET /api/v1/stealth/command-suite
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

```http
GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Response rows include lifecycle and policy evidence such as `status`,
`revealed_orders`, `active_placement_client_order_id`,
`active_exchange_order_id`, `cancel_reentry_state`, and
`anchor_repricing_state`. These fields are display evidence for the admin
platform. They must not be used by a frontend to mutate stealth lifecycle
state or cancel a live placement.

The command-suite response reports `exchange_truth_required=true`,
`live_enabled_command_count=0`, `executable_command_count=0`, and
`live_coinbase_orders_ran=false`. It lists live-disabled stealth create,
reveal, move, cancel, recovery, reconciliation, and movement/reprice command
rows plus blocked gap rows for create lifecycle-write, reveal trigger/exchange
placement, cancel exchange handling, move revealed, reprice completion,
recovery, and reconciliation. Active-placement exchange-truth snapshot/proof
writer routes persist local no-live evidence only after backend admission
prerequisites match. These routes do not create stealth orders, reveal orders,
cancel active placements, move/reprice revealed orders, execute
reconciliation, mutate state, read Coinbase, verify exchange truth, or call
Coinbase.

## Movement And Repricing

Movement/repricing reads expose existing durable and runtime-safe evidence.
The read routes do not move parent orders, premark moves, trigger repricing,
cancel Coinbase orders, or replace revealed stealth placements.

```http
GET /api/v1/movement-repricing/evidence?product_id=BTC-USDC&evidence_type=stealth_repricing_state&limit=50&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

```http
GET /api/v1/movement-repricing/orders/{client_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

```http
GET /api/v1/movement-repricing/stealth/{stealth_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Response items may include parent move history from `order_moves`, stealth
move audit rows from `stealth_order_moves`, repricing state from
`stealth_orders.anchor_repricing_state_json`, replacement-slot evidence, and
runtime mutation claim evidence when the existing manager state is observable.
Exchange-native ids are exposed as exchange evidence only.

Movement repricing has one live-disabled command draft:

```http
POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: idem-movement-reprice-001
X-Correlation-Id: corr-movement-reprice-001
X-Operator-Intent: movement_reprice_review
X-Admin-Actor: trader-001
X-Admin-Roles: trader
Content-Type: application/json

{"reason":"operator_requested_reprice"}
```

The request identity is the path `stealth_order_id`. Do not send
`client_order_id` or `order_id` in the body. The current response is HTTP
`501` with `status="not_implemented"`, durable audit/idempotency evidence,
`live_exchange_submitted=false`, and `data.stealth_manager_invoked=false`.
It does not clear repricing cooldowns, invoke the live dashboard repricer,
cancel placements, or call Coinbase.

## Futures/Perpetuals Reads

Futures/perpetual reads expose backend-owned account, risk, and position
evidence. They are not command routes. They do not place, close, reduce,
cancel, or liquidate positions.

Futures/perpetual command-suite reads expose backend-owned M57 contract
evidence for route-bound placement, close/reduce, cancel, and reconciliation
command drafts, including blocked request-field rows, semantic guard rows,
evidence routes, command-level readiness decisions, ordered closure steps, risk
proof requirements, and risk proof acceptance criteria. The route-bound drafts
register Admin API routes, but route/draft flags are true while execution
remains false. Cancel route evidence is keyed by `client_order_id`. The
response does not enable proof writers, accept proof records as readiness,
execute reconciliation, call Coinbase reads or writes, mutate
futures/order/exchange state, or grant browser/BFF execution authority.

```http
GET /api/v1/futures/command-suite
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Expected command-suite posture:

```json
{
  "type": "admin_futures_command_suite",
  "module_id": "futures_perpetuals",
  "approved_phase_range": "6541-6560",
  "status": "blocked",
  "command_count": 4,
  "blocked_command_count": 4,
  "executable_command_count": 0,
  "command_route_count": 4,
  "command_draft_allowed_count": 4,
  "command_enablement_blocker_summary_count": 6,
  "command_enablement_blocker_summary_blocking_count": 6,
  "command_enablement_blocker_summaries": [
    {"blocker": "unresolved_prerequisites", "status": "blocked"},
    {"blocker": "request_payload_contracts", "status": "blocked"},
    {"blocker": "semantic_guard_evidence", "status": "blocked"},
    {"blocker": "risk_proof_acceptance", "status": "blocked"},
    {"blocker": "live_service_adapter", "status": "blocked"},
    {"blocker": "contextless_review_gate", "status": "blocked"}
  ],
  "request_field_count": 22,
  "required_request_field_count": 22,
  "blocking_request_field_count": 22,
  "request_payload_validator_contract_count": 22,
  "blocking_request_payload_validator_contract_count": 22,
  "ready_request_payload_validator_contract_count": 0,
  "registered_request_payload_validator_contract_count": 0,
  "request_payload_validator_input_schema_count": 22,
  "blocking_request_payload_validator_input_schema_count": 22,
  "ready_request_payload_validator_input_schema_count": 0,
  "registered_request_payload_validator_input_schema_count": 0,
  "request_payload_validator_output_schema_count": 22,
  "blocking_request_payload_validator_output_schema_count": 22,
  "ready_request_payload_validator_output_schema_count": 0,
  "registered_request_payload_validator_output_schema_count": 0,
  "request_payload_validator_registration_count": 22,
  "blocking_request_payload_validator_registration_count": 22,
  "ready_request_payload_validator_registration_count": 0,
  "registered_request_payload_validator_registration_count": 0,
  "runtime_observed_request_payload_validator_registration_count": 0,
  "request_payload_validation_evidence_count": 22,
  "blocking_request_payload_validation_evidence_count": 22,
  "ready_request_payload_validation_evidence_count": 0,
  "recorded_request_payload_validation_evidence_count": 0,
  "runtime_observed_request_payload_validation_evidence_count": 0,
  "request_payload_validation_evidence_record_count": 22,
  "blocking_request_payload_validation_evidence_record_count": 22,
  "ready_request_payload_validation_evidence_record_count": 0,
  "stored_request_payload_validation_evidence_record_count": 0,
  "runtime_observed_request_payload_validation_evidence_record_count": 0,
  "request_fields": [
    {
      "field": "client_order_id",
      "request_payload_contract_ref": "application/admin_api/futures_request_payload_contracts.py::futures_cancel_client_order_id_request_payload_contract",
      "validation_gate_ref": "application/admin_api/futures_request_payload_contracts.py::futures_cancel_client_order_id_request_payload_validation_gate",
      "validation_evidence_ref": "futures_cancel_client_order_id_request_payload_validated",
      "validator_contract_ref": "application/admin_api/futures_request_payload_validators.py::futures_cancel_client_order_id_request_payload_validator_contract",
      "validator_registration_ref": "application/admin_api/futures_request_payload_validators.py::futures_cancel_client_order_id_request_payload_validator_registration",
      "validation_gate_ready": false,
      "validation_gate_passed": false,
      "validator_contract_registered": false,
      "validator_registered": false,
      "request_payload_validated": false
    }
  ],
  "request_payload_validation_evidence": [
    {
      "field": "client_order_id",
      "validation_evidence_contract_ref": "application/admin_api/futures_request_payload_validation_evidence.py::futures_cancel_client_order_id_request_payload_validation_evidence",
      "validation_evidence_field_refs": [
        "application/admin_api/futures_request_payload_validation_evidence.py::futures_cancel_client_order_id_request_payload_validation_evidence.status",
        "application/admin_api/futures_request_payload_validation_evidence.py::futures_cancel_client_order_id_request_payload_validation_evidence.source"
      ],
      "validation_evidence_field_count": 6,
      "runtime_evidence_satisfies_validation_evidence": false,
      "validation_evidence_ready": false,
      "validation_evidence_recorded": false,
      "request_payload_validated": false
    }
  ],
  "request_payload_validation_evidence_records": [
    {
      "field": "client_order_id",
      "validation_record_contract_ref": "application/admin_api/futures_request_payload_validation_evidence_records.py::futures_cancel_client_order_id_request_payload_validation_evidence_record",
      "validation_record_store_ref": "application/admin_api/futures_request_payload_validation_evidence_records.py::futures_cancel_client_order_id_request_payload_validation_evidence_record_store",
      "validation_record_writer_ref": "application/admin_api/futures_request_payload_validation_evidence_records.py::futures_cancel_client_order_id_request_payload_validation_evidence_record_writer",
      "validation_record_replay_guard_ref": "application/admin_api/futures_request_payload_validation_evidence_records.py::futures_cancel_client_order_id_request_payload_validation_evidence_record_replay_guard",
      "validation_record_field_refs": [
        "application/admin_api/futures_request_payload_validation_evidence_records.py::futures_cancel_client_order_id_request_payload_validation_evidence_record.validation_evidence_contract_ref",
        "application/admin_api/futures_request_payload_validation_evidence_records.py::futures_cancel_client_order_id_request_payload_validation_evidence_record.validation_record_store_ref"
      ],
      "validation_record_field_count": 8,
      "validation_record_contract_ready": false,
      "validation_record_store_ready": false,
      "validation_record_writer_enabled": false,
      "validation_record_replay_guard_ready": false,
      "validation_recorded": false,
      "append_only_validation_record": false,
      "validation_record_idempotency_bound": false,
      "request_payload_validated": false
    }
  ],
  "semantic_guard_count": 33,
  "blocking_semantic_guard_count": 33,
  "risk_semantic_guard_count": 12,
  "readiness_decision_count": 4,
  "blocked_readiness_decision_count": 4,
  "ready_readiness_decision_count": 0,
  "readiness_closure_step_count": 24,
  "blocking_readiness_closure_step_count": 24,
  "risk_proof_requirement_count": 20,
  "blocking_risk_proof_requirement_count": 20,
  "risk_proof_contract_count": 40,
  "blocking_risk_proof_contract_count": 40,
  "registered_risk_proof_route_count": 0,
  "enabled_risk_proof_writer_count": 0,
  "risk_proof_payload_field_count": 200,
  "blocking_risk_proof_payload_field_count": 200,
  "present_risk_proof_payload_field_count": 0,
  "registered_risk_proof_payload_validation_count": 0,
  "risk_proof_record_contract_count": 120,
  "blocking_risk_proof_record_contract_count": 120,
  "registered_risk_proof_record_store_count": 0,
  "registered_risk_proof_record_validation_count": 0,
  "accepted_risk_proof_record_contract_count": 0,
  "risk_proof_record_validation_count": 120,
  "blocking_risk_proof_record_validation_count": 120,
  "ready_risk_proof_record_validation_count": 0,
  "risk_proof_record_validation_remediation_count": 120,
  "blocking_risk_proof_record_validation_remediation_count": 120,
  "ready_risk_proof_record_validation_remediation_count": 0,
  "risk_proof_record_validation_remediation_dependency_count": 120,
  "blocking_risk_proof_record_validation_remediation_dependency_count": 120,
  "ready_risk_proof_record_validation_remediation_dependency_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_count": 120,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_count": 120,
  "ready_risk_proof_record_validation_remediation_dependency_work_item_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_count": 120,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_count": 120,
  "ready_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_count": 120,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_count": 120,
  "ready_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_count": 720,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_count": 720,
  "ready_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_count": 0,
  "completed_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 720,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 720,
  "ready_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 0,
  "completed_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 1440,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 1440,
  "present_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 0,
  "accepted_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_requirement_count": 1440,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_requirement_count": 1440,
  "available_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_requirement_count": 0,
  "writer_available_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_requirement_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_contract_count": 1440,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_contract_count": 1440,
  "available_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_contract_count": 0,
  "accepted_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_contract_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_count": 1440,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_count": 1440,
  "ready_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_count": 0,
  "configured_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_count": 1440,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_count": 1440,
  "ready_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_count": 0,
  "recorded_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_count": 1440,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_count": 1440,
  "ready_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_count": 0,
  "performed_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_count": 1440,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_count": 1440,
  "ready_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_count": 0,
  "claimed_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_count": 8640,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_count": 8640,
  "ready_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_count": 0,
  "completed_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_count": 0,
  "risk_proof_acceptance_criterion_count": 100,
  "blocking_risk_proof_acceptance_criterion_count": 100,
  "accepted_risk_proof_acceptance_criterion_count": 0,
  "risk_proof_acceptance_blocker_count": 120,
  "proof_record_resolved_but_acceptance_blocked_count": 0,
  "risk_proof_semantic_contract_requirement_count": 34,
  "blocking_risk_proof_semantic_contract_requirement_count": 34,
  "registered_risk_proof_semantic_contract_count": 0,
  "runtime_observed_risk_proof_semantic_contract_requirement_count": 8,
  "risk_proof_semantic_contract_definition_count": 34,
  "blocking_risk_proof_semantic_contract_definition_count": 34,
  "ready_risk_proof_semantic_contract_definition_count": 0,
  "registered_risk_proof_semantic_contract_definition_count": 0,
  "runtime_observed_risk_proof_semantic_contract_definition_count": 8,
  "risk_proof_semantic_contract_validation_gate_count": 34,
  "blocking_risk_proof_semantic_contract_validation_gate_count": 34,
  "ready_risk_proof_semantic_contract_validation_gate_count": 0,
  "registered_risk_proof_semantic_contract_validator_count": 0,
  "runtime_observed_risk_proof_semantic_contract_validation_gate_count": 8,
  "risk_proof_semantic_contract_validator_contract_count": 34,
  "blocking_risk_proof_semantic_contract_validator_contract_count": 34,
  "ready_risk_proof_semantic_contract_validator_contract_count": 0,
  "registered_risk_proof_semantic_contract_validator_contract_count": 0,
  "runtime_observed_risk_proof_semantic_contract_validator_contract_count": 8,
  "risk_proof_semantic_validator_input_schema_count": 34,
  "blocking_risk_proof_semantic_validator_input_schema_count": 34,
  "ready_risk_proof_semantic_validator_input_schema_count": 0,
  "registered_risk_proof_semantic_validator_input_schema_count": 0,
  "runtime_observed_risk_proof_semantic_validator_input_schema_count": 8,
  "risk_proof_semantic_validator_output_schema_count": 34,
  "blocking_risk_proof_semantic_validator_output_schema_count": 34,
  "ready_risk_proof_semantic_validator_output_schema_count": 0,
  "registered_risk_proof_semantic_validator_output_schema_count": 0,
  "runtime_observed_risk_proof_semantic_validator_output_schema_count": 8,
  "risk_proof_semantic_validator_registration_count": 34,
  "blocking_risk_proof_semantic_validator_registration_count": 34,
  "ready_risk_proof_semantic_validator_registration_count": 0,
  "registered_risk_proof_semantic_validator_registration_count": 0,
  "runtime_observed_risk_proof_semantic_validator_registration_count": 8,
  "forbidden_spot_assumptions": [
    "spot_wallet_available",
    "spot_no_shorting",
    "spot_usdc_quote_required",
    "spot_average_cost_basis",
    "spot_inventory_lot_authority"
  ],
  "spot_rule_authority": false,
  "browser_authority": "display_only",
  "bff_authority": "forward_only_no_execution",
  "live_coinbase_orders_ran": false,
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0"
}
```

Command rows include `"readiness_closure_steps"`, an ordered backend-owned plan
for the remaining prerequisite, payload, semantic-guard, command-service,
route, live-adapter, and contextless-review work. They also include
`"risk_proof_requirements"` for product scope, position scope, margin,
collateral, liquidation buffer, funding fee, reduce-only, close-only,
cap-guard, and reconciliation-plan semantics. Each risk proof includes
`"proof_contracts"` for the future backend-owned proof route and proof writer
artifacts that must exist before proof evidence can be accepted. Each proof
also includes
`"payload_fields"` for the future backend-owned proof record payload fields,
payload paths, validation evidence refs, idempotency, correlation, and audit
bindings. Payload rows remain blocked with `payload_field_present=false` and
`validation_registered=false`. Each proof also includes `"record_contracts"`
for the future backend-owned proof record schema, append-only log,
idempotency binding, payload validation gate, replay guard, and audit-link
contracts. Record/store rows remain blocked with `store_registered=false`,
`payload_validation_registered=false`, and `proof_record_accepted=false`.
Each proof also includes `"record_validations"` for the future backend-owned
record contract, schema/log, idempotency, payload-validation, replay, and
audit-link checks. Validation rows remain blocked with
`record_validation_registered=false` and `record_validation_ready=false`.
Each proof also includes `"record_validation_remediations"` for the blocked
backend-owned work needed before a record validator could become ready:
record-contract registration, store-schema creation, append-only log
configuration, idempotency binding, payload validation, replay guard, audit
linking, record-validator registration, and contextless review. Remediation
rows remain blocked with `remediation_work_item_created=false`,
`remediation_ready=false`, and `remediation_performed=false`.
Each store record-validation remediation row also includes
`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependencies"`
for blocked backend-owned dependency order, dependency graph,
predecessor/successor dependency refs, dependency gate, required dependency
work, inherited validation/remediation blockers, and missing evidence required
before validation-remediation work could be safely sequenced. Those dependency
rows remain blocked with
`record_validation_remediation_dependency_required=true`,
`record_validation_remediation_dependency_ready=false`,
`record_validation_remediation_dependency_resolved=false`,
`record_validation_remediation_dependency_performed=false`,
`dependency_ready=false`, `dependency_resolved=false`, and
`dependency_performed=false`. The matching aggregate field is
`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_count"`.
Each nested record-validation remediation dependency work item also exposes
blocked nested dependency work-item claim-trace clearance-step rows through
`"remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_steps"`.
The matching aggregate field is
`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_count"`.
Those rows remain blocked with `prior_clearance_step_complete=false`,
`next_clearance_step_enabled=false`, `clearance_step_ready=false`,
`clearance_step_complete=false`, `accepts_evidence=false`,
`writes_evidence=false`, and `execution_allowed=false`.
Each proof also includes
`"record_validation_remediation_dependencies"` for the blocked backend-owned
dependency work that orders each remediation row against its immediate
predecessor and successor remediation rows. Dependency rows name dependency
gates, required backend contracts, required evidence refs, dependency
actions, and dependency blockers. They remain blocked with
`dependency_work_item_created=false`, `dependency_ready=false`,
`dependency_resolved=false`, and `dependency_performed=false`.
Each proof also includes
`"record_validation_remediation_dependency_work_items"` for the blocked
backend-owned work-item contract that would be required before a remediation
dependency could be queued or claimed. Work-item rows name work-item store
refs, claim-ledger blockers, predecessor/successor work-item refs, required
backend contracts, actions, and blockers. They remain blocked with
`work_item_created=false`, `work_item_claimed=false`,
`claim_ledger_registered=false`, and `dependency_ready=false`.
Each proof also includes
`"record_validation_remediation_dependency_work_item_claim_traces"` for the
blocked backend-owned claim-trace contract that would be required before a
dependency work item could be claimed or used as dependency-clearance
evidence. Claim-trace rows name claim-trace store refs, claim-ledger blockers,
claim-review blockers, predecessor/successor claim-trace refs, required
backend contracts, claim targets, and blockers. They remain blocked with
`claim_trace_created=false`, `claim_allowed=false`,
`claim_resolved=false`, and `work_item_claimed=false`.
Each proof also includes
`"record_validation_remediation_dependency_work_item_claim_trace_clearance_plans"`
for the blocked backend-owned clearance-plan contract that would be required
before a claim trace could ever be cleared. Clearance-plan rows name
clearance-plan store refs, upstream claim-trace refs, predecessor/successor
claim-trace refs, predecessor/successor clearance-plan refs, claim targets,
required backend contracts, required plan steps, and blockers. They remain
blocked with `clearance_plan_created=false`,
`clearance_plan_ready=false`, `clearance_sequence_ready=false`,
`claim_trace_ready=false`, and `claim_resolved=false`.
Each clearance plan also includes
`"record_validation_remediation_dependency_work_item_claim_trace_clearance_steps"`
for the blocked backend-owned clearance-step rows that would be required
before the plan could ever be reviewed or executed. Clearance-step rows name
step refs, predecessor/successor step refs, missing backend step contracts,
missing step-review refs, missing contextless-review refs, and blockers. They
remain blocked with `clearance_step_ready=false`,
`clearance_step_complete=false`, `clearance_plan_ready=false`,
`claim_trace_ready=false`, and `claim_resolved=false`.
Each clearance step also includes
`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_reviews"`
for the blocked backend-owned clearance-step review rows that would be required
before the step could ever be accepted as reviewed. Clearance-step review rows
name review refs, source step refs, predecessor/successor review refs,
required owner/contextless review inputs, missing backend review contracts,
missing review-gate refs, and blockers. They remain blocked with
`clearance_step_review_ready=false`,
`clearance_step_review_complete=false`,
`clearance_step_review_inputs_present=false`,
`clearance_step_review_gates_passed=false`, `accepts_evidence=false`,
`writes_evidence=false`, `clearance_step_ready=false`, and
`claim_resolved=false`.
Each clearance-step review also includes
`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_inputs"`
for the blocked backend-owned owner/contextless input rows that would be
required before a review could ever accept evidence. Clearance-step review
input rows name input refs, source review refs, required input store refs,
input gates, inherited review/step blockers, and missing evidence refs. They
remain blocked with `clearance_step_review_input_present=false`,
`clearance_step_review_input_accepted=false`,
`clearance_step_review_input_validated=false`,
`clearance_step_review_input_gate_passed=false`,
`clearance_step_review_inputs_present=false`, `claim_trace_created=false`,
`claim_allowed=false`, `claim_resolved=false`, `accepts_evidence=false`,
`writes_evidence=false`, and `execution_allowed=false`.
Each clearance-step review input also includes
`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_requirements"`
for the blocked backend-owned input store, writer, record-key, validation-gate,
and replay-gate requirements that would be required before input evidence
could ever be accepted. Those rows remain blocked with `store_required=true`,
`store_available=false`, `writer_available=false`,
`record_key_registered=false`, `validation_gate_passed=false`,
`replay_gate_passed=false`, `accepts_evidence=false`,
`writes_evidence=false`, and `execution_allowed=false`.
Each clearance-step review input store requirement also includes
`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_contracts"`
for the blocked backend-owned record contract, schema, append-only log,
idempotency key, payload fields, validation gate, and replay protection that
would be required before input evidence could ever be recorded. Those rows
remain blocked with `record_contract_required=true`,
`record_contract_available=false`, `record_schema_available=false`,
`append_only_log_available=false`, `idempotency_key_bound=false`,
`payload_schema_validated=false`, `replay_protected=false`,
`record_present=false`, `record_accepted=false`,
`record_validated=false`, `accepts_evidence=false`,
`writes_evidence=false`, and `execution_allowed=false`.
Each store record contract also includes
`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validations"`
for the blocked backend-owned validation checks and record-validation gate
that would be required before input evidence could ever be accepted. Those
rows remain blocked with `record_validation_required=true`,
`record_validation_ready=false`, `validation_checks_passed=false`,
`validation_configured=false`, `record_present=false`,
`record_accepted=false`, `record_validated=false`,
`accepts_evidence=false`, `writes_evidence=false`, and
`execution_allowed=false`.
Each store record-validation row also includes
`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediations"`
for the blocked backend-owned remediation work and evidence attachment that
would be required before a validation row could ever be remediated or
recorded:

```json
{
  "record_validation_remediation_required": true,
  "record_validation_remediation_ready": false,
  "record_validation_remediation_performed": false,
  "record_validation_remediation_recorded": false,
  "accepts_evidence": false,
  "writes_evidence": false,
  "execution_allowed": false
}
```

Each proof also includes
`"acceptance_criteria"` for required evidence, proof route registration,
proof-writer review, spot-rule boundary review, and browser/BFF authority
review. Completed 5821-5840 rows also expose `"proof_acceptance_blockers"` and
`"proof_record_resolves_acceptance"` so a resolved safe proof record remains
display evidence only. Completed 5841-5860 rows add
`"semantic_contract_requirements"` plus semantic-contract aggregate counters
so the exact missing futures semantic contract refs are visible. Completed
5861-5880 rows add `"semantic_contract_definitions"`,
`"risk_proof_semantic_contract_definition_count"`,
`"semantic_contract_definition_ref"`, `"definition_ready": false`,
`"validation_ready": false`, and
`"runtime_evidence_satisfies_definition": false` so the missing backend
definition contract, validation gate, and acceptance gate are explicit.
Completed 5881-5900 rows add `"semantic_contract_validation_gates"`,
`"risk_proof_semantic_contract_validation_gate_count"`,
`"validation_contract_ref"`, `"validator_registered": false`, and
`"runtime_evidence_satisfies_validation": false` so the missing backend
validator contract, validation input refs, and required validation evidence
are explicit. Completed 5901-5920 rows add
`"semantic_contract_validator_contracts"`,
`"risk_proof_semantic_contract_validator_contract_count"`,
`"validator_contract_ref"`, `"validator_input_schema_ref"`,
`"validator_output_schema_ref"`, `"validator_registration_ref"`,
`"validator_contract_registered": false`, and
`"runtime_evidence_satisfies_validator_contract": false` so the missing backend
validator contract, input schema, output schema, registration, and
contextless-review evidence are explicit. Completed 5921-5940 rows add
`"semantic_validator_input_schemas"`,
`"risk_proof_semantic_validator_input_schema_count"`,
`"input_schema_field_refs"`, `"input_schema_registered": false`, and
`"runtime_evidence_satisfies_input_schema": false` so the missing backend input
schema contract, input fields, schema registration, and contextless-review
evidence are explicit. Completed 5941-5960 rows add
`"semantic_validator_output_schemas"`,
`"risk_proof_semantic_validator_output_schema_count"`,
`"output_schema_field_refs"`, `"output_schema_registered": false`, and
`"runtime_evidence_satisfies_output_schema": false` so the missing backend
output schema contract, output fields, schema registration, and
contextless-review evidence are explicit. Completed 5961-5980 rows add
`"semantic_validator_registrations"`,
`"risk_proof_semantic_validator_registration_count"`,
`"validator_registration_field_refs"`,
`"validator_registration_ready": false`, and
`"runtime_evidence_satisfies_validator_registration": false` so the missing
backend validator registration contract, registry record, input/output schema
bindings, and contextless-review evidence are explicit. These rows are blocked
evidence only. Completed 5981-6000 rows add disabled futures command-service
contract evidence: `place_futures_order`,
`close_or_reduce_futures_position`, and `cancel_futures_order` are named
disabled backend service methods. Their service contracts remain required, but
the command-suite no longer reports them as missing. Completed 6001-6020 rows
add disabled futures risk-guard contract evidence:
`evaluate_futures_margin_collateral_liquidation` is a named disabled backend
risk-guard method. The risk-guard contract remains required, but the
command-suite no longer reports it as missing. Completed 6021-6040 rows add
disabled futures reconciliation evidence:
`record_futures_reconciliation_plan` is required/present disabled backend
evidence and is no longer missing. Completed 6041-6060 rows add disabled
futures route-registration contract metadata only:
`api/v1/routes/futures.py::*_route_contract` refs are required/present disabled
evidence and are no longer missing. Completed 6061-6080 rows add disabled
futures live-adapter contract metadata only:
`application/admin_api/live_execution.py::*_adapter_contract` refs are
required/present disabled evidence and are no longer missing. Completed
6081-6100 work adds disabled adapter-construction metadata only:
`application/admin_api/live_execution.py::*_adapter_construction_contract`
refs are required/present disabled evidence and are no longer missing.
Completed 6101-6120 work adds disabled adapter-decision metadata only:
`application/admin_api/live_execution.py::*_adapter_decision_contract` refs
are required/present disabled evidence and are no longer missing. Completed
6121-6140 work adds disabled adapter-decision-record metadata only:
`application/admin_api/live_execution.py::*_adapter_decision_record_contract`
refs are required/present disabled evidence and are no longer missing. Completed
6141-6160 work adds disabled adapter-invocation metadata only:
`application/admin_api/live_execution.py::*_adapter_invocation_contract`
refs are required/present disabled evidence and are no longer missing. Completed
6161-6180 work adds disabled adapter-execution metadata only:
`application/admin_api/live_execution.py::*_adapter_execution_contract`
refs are required/present disabled evidence and are no longer missing. Completed
6181-6200 work adds disabled Coinbase exchange-submission metadata only:
`application/admin_api/live_execution.py::*_coinbase_exchange_submission_contract`
refs are required/present disabled evidence, while
`application/admin_api/live_execution.py::*_post_exchange_submission_reconciliation_contract`
refs remained missing backend contract gaps. Completed 6201-6220 work adds
disabled post-exchange-submission reconciliation metadata only:
`application/admin_api/live_execution.py::*_post_exchange_submission_reconciliation_contract`
refs are required/present disabled evidence and are no longer listed in
`missing_backend_contracts`. Completed 6221-6240 work adds aggregate command
enablement blocker summaries for unresolved prerequisites, request payload
contracts, semantic guard evidence, risk proof acceptance, live service
adapters, and contextless review. Completed 6241-6260 work adds
backend-owned `command_enablement_sequence_steps`,
`command_enablement_sequence_step_count`, and
`command_enablement_sequence_step_blocking_count` derived from
`readiness_closure_steps` for `resolve_prerequisite_contracts`,
`define_request_payload_contract`, `bind_semantic_guard_evidence`,
`bind_live_service_adapter`, and `run_contextless_review_gate`. These rows do
not configure or construct adapters, invoke adapters, execute adapters, submit
Coinbase orders, validate
payloads, write proofs, enable writers, resolve dependencies, create
remediation or dependency work items, claim work items, create or resolve claim
traces, create or execute clearance plans, execute clearance steps, complete
clearance-step reviews, clear claim traces, accept review inputs, register
claim ledgers, perform remediation, execute post-exchange reconciliation, or
grant browser/BFF authority.

Current sequence field examples: `"command_enablement_sequence_steps"`,
`"command_enablement_sequence_step_count"`, and
`"command_enablement_sequence_step_blocking_count"`.
Completed 6261-6280 work added backend-owned
`"command_enablement_sequence_command_traces"`,
`"command_enablement_sequence_command_trace_count"`, and
`"command_enablement_sequence_command_trace_blocking_count"` so each aggregate
sequence step traces to exact per-command closure evidence. Trace rows include
`"trace_id"`, `"command_step_sequence"`,
`"reconciliation_execution_allowed": false`, and
`"futures_state_mutation_allowed": false`; they do not register routes, create
drafts, call Coinbase, execute reconciliation, mutate futures state, or grant
browser/BFF authority.

Completed 6281-6300 work reports `"service_method": "reconcile_futures_position"`
for the `futures_reconcile` row and includes
`"application/admin_api/futures_command_service.py::reconcile_futures_position"`
alongside
`"application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan"`
in `required_backend_contracts`. This is a disabled command-service bridge
plus a separate required reconciliation-plan contract; it does not register
routes, create drafts, call Coinbase, execute reconciliation, mutate futures
state, or grant browser/BFF authority.

Completed 6301-6320 work reports futures proof route/writer contract registry
evidence in `risk_proof_requirements[*].proof_contracts`, including
`"application/admin_api/futures_proof_routes.py::post_futures_place_margin_collateral_proof"`
and
`"application/admin_api/futures_proof_writer.py::write_futures_place_margin_collateral_proof"`.
The current response keeps `"registered_proof_route_count": 0` and
`"enabled_proof_writer_count": 0`; these rows do not register proof routes,
create proof writers, accept proof records, satisfy risk proofs, call
Coinbase, execute reconciliation, mutate futures state, or grant browser/BFF
authority.

Completed 6321-6340 work reports futures proof payload-field contract registry
evidence in `risk_proof_requirements[*].payload_fields`, including
`"proof_payload.command"`, `"proof_payload.validation.status"`,
`"futures_place_margin_collateral_payload_command_validated"`,
`"payload_field_present": false`, and `"validation_registered": false`.
These rows do not validate submitted proof payloads, register validators,
accept proof records, create proof writers, make route-bound command drafts
executable, call Coinbase, execute reconciliation, mutate futures state, or
grant browser/BFF authority.

Completed 6341-6360 work reports futures route-bound command draft evidence
for `POST /api/v1/futures/orders`,
`POST /api/v1/futures/positions/{position_key}/close-reduce`,
`POST /api/v1/futures/orders/{client_order_id}/cancel`, and
`POST /api/v1/futures/positions/{position_key}/reconciliation`.
Machine-check evidence: route/draft flags remain true while execution remains
false; cancel uses
`client_order_id`.

Completed 6361-6380 work reports futures request payload contract registry
evidence through `FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS` and
`iter_futures_request_payload_contracts`. The command-suite response exposes
`"request_field_count"`, `"blocking_request_field_count"`, and request-field
`required_backend_contracts`, including
`"application/admin_api/futures_request_payload_contracts.py::futures_cancel_client_order_id_request_payload_contract"`.
Completed 6381-6400 work reports futures request payload validation gate
evidence on those same request-field rows: `"validation_gate_ref"`,
`"validation_evidence_ref"`, `"validator_contract_ref"`,
`"validator_registration_ref"`, `"validation_gate_ready": false`,
`"validation_gate_passed": false`, and `"request_payload_validated": false`.
Completed 6401-6420 work reports futures request payload validator contract
registry evidence through `FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS` and
`iter_futures_request_payload_validator_contracts`, with
`"request_payload_validator_contract_count"`,
`"blocking_request_payload_validator_contract_count"`,
`"ready_request_payload_validator_contract_count"`,
`"registered_request_payload_validator_contract_count"`,
`"request_payload_validator_contracts"`, `"validator_input_schema_ref"`,
`"validator_output_schema_ref"`,
`"validator_input_schema_registered": false`, and
`"validator_output_schema_registered": false`.
Completed 6421-6440 work reports futures request payload validator input-schema
evidence through `FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS`
and `iter_futures_request_payload_validator_input_schemas`, with
`"request_payload_validator_input_schema_count": 22`,
`"blocking_request_payload_validator_input_schema_count": 22`,
`"ready_request_payload_validator_input_schema_count": 0`,
`"registered_request_payload_validator_input_schema_count": 0`,
`"request_payload_validator_input_schemas"`, `"input_schema_field_refs"`,
`"input_schema_field_count": 5`, and `"input_schema_registered": false`.
Machine-check evidence: futures request payload validator input-schema evidence.
Completed 6441-6460 work reports futures request payload validator
output-schema evidence through
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS` and
`iter_futures_request_payload_validator_output_schemas`, with
`"request_payload_validator_output_schema_count": 22`,
`"blocking_request_payload_validator_output_schema_count": 22`,
`"request_payload_validator_output_schemas"`, `"output_schema_field_refs"`,
`"output_schema_field_count": 5`, and `"output_schema_registered": false`.
Machine-check evidence: futures request payload validator output-schema evidence.
Completed 6461-6480 work reports futures request payload validator
registration evidence through
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS` and
`iter_futures_request_payload_validator_registrations`, with
`"request_payload_validator_registration_count": 22`,
`"blocking_request_payload_validator_registration_count": 22`,
`"request_payload_validator_registrations"`,
`"validator_registration_field_refs"`,
`"validator_registration_field_count": 6`,
`"validator_registration_ready": false`, and
`"runtime_evidence_satisfies_validator_registration": false`.
Machine-check evidence: futures request payload validator registration evidence.
Completed 6481-6500 work reports futures request payload validation evidence
through `FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS` and
`iter_futures_request_payload_validation_evidence`, with
`"request_payload_validation_evidence_count": 22`,
`"blocking_request_payload_validation_evidence_count": 22`,
`"ready_request_payload_validation_evidence_count": 0`,
`"recorded_request_payload_validation_evidence_count": 0`,
`"runtime_observed_request_payload_validation_evidence_count": 0`,
`"request_payload_validation_evidence"`,
`"validation_evidence_contract_ref"`,
`"validation_evidence_field_refs"`,
`"validation_evidence_field_count": 6`,
`"runtime_evidence_satisfies_validation_evidence": false`,
`"validation_evidence_ready": false`, and
`"validation_evidence_recorded": false`.
Machine-check evidence: futures request payload validation evidence.
The completed 6521-6540 range reports futures request payload validation evidence
record contract evidence through
`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS` and
`iter_futures_request_payload_validation_evidence_records`, with
`"approved_phase_range": "6541-6560"`,
`"request_payload_validation_evidence_record_count": 22`,
`"blocking_request_payload_validation_evidence_record_count": 22`,
`"ready_request_payload_validation_evidence_record_count": 0`,
`"stored_request_payload_validation_evidence_record_count": 0`,
`"runtime_observed_request_payload_validation_evidence_record_count": 0`,
`"request_payload_validation_evidence_records"`,
`"validation_record_contract_ref"`, `"validation_record_store_ref"`,
`"validation_record_writer_ref"`,
`"validation_record_replay_guard_ref"`,
`"validation_record_field_refs"`, `"validation_record_field_count"`,
`"validation_record_contract_ready": false`,
`"validation_record_store_ready": false`,
`"validation_record_writer_enabled": false`,
`"validation_record_replay_guard_ready": false`,
`"validation_recorded": false`,
`"append_only_validation_record": false`, and
`"validation_record_idempotency_bound": false`.
Machine-check evidence: futures request payload validation evidence record contract evidence.
The completed 6521-6540 range also reports futures request payload validation
record schema evidence through
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS` and
`iter_futures_request_payload_validation_record_schemas`, with
`"approved_phase_range": "6541-6560"`,
`"request_payload_validation_record_schema_count": 22`,
`"blocking_request_payload_validation_record_schema_count": 22`,
`"ready_request_payload_validation_record_schema_count": 0`,
`"registered_request_payload_validation_record_schema_count": 0`,
`"runtime_observed_request_payload_validation_record_schema_count": 0`,
`"request_payload_validation_record_schemas"`,
`request_payload_validation_record_schema_count`,
`blocking_request_payload_validation_record_schema_count`,
`ready_request_payload_validation_record_schema_count`,
`registered_request_payload_validation_record_schema_count`,
`runtime_observed_request_payload_validation_record_schema_count`,
`request_payload_validation_record_schemas`,
`"validation_record_schema_ref"`,
`"validation_record_append_only_log_ref"`,
`"validation_record_schema_field_refs"`,
`"validation_record_schema_field_count"`,
`"runtime_evidence_satisfies_validation_record_schema": false`,
`"validation_record_schema_ready": false`,
`"validation_record_schema_registered": false`, and
`"validation_record_append_only_log_ready": false`.
Machine-check evidence: futures request payload validation record schema evidence.
The registry and disabled gate evidence do not validate command request
payloads, record validation evidence, write append-only validation records,
satisfy validator registrations, register payload validators, bind live
adapters, call Coinbase, execute reconciliation, mutate futures/order/exchange
state, or grant browser/BFF authority.
Machine-check evidence: futures request payload contract registry evidence.
Machine-check evidence: futures request payload validation gate evidence.
Machine-check evidence: futures request payload validator contract registry evidence.
Machine-check evidence: route/draft flags remain true while execution remains false.

```http
GET /api/v1/futures/account
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

```http
GET /api/v1/futures/positions?product_id=BIP-20DEC30-CDE&position_side=LONG&limit=50&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

```http
GET /api/v1/futures/positions/{position_key}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Account responses separate configured product metadata from observed runtime
position coverage:

- `configured_product_scope`
- `observed_position_scope`

Position rows are keyed by `position_key`. Do not replace that key with spot
wallet identity, `client_order_id`, or Coinbase `order_id`. Close/reduce sides
are backend-derived from observed position side and are not exchange-observed
reduce-only or close-only order flags. Funding-rate evidence is currently
`not_modeled`.

## Guard/Risk Policy Reads

Guard/risk policy reads expose backend-owned policy posture. They are not
command routes and they do not approve live execution, run wallet checks,
calculate profitability in the browser, or contact Coinbase.

```http
GET /api/v1/admin/guard-risk-policy?product_id=BTC-USDC
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

The response includes `action_condition_policy`, `configured_limit_rules`,
`live_execution_gate`, `product_capability_policy`,
`product_capability_decisions`, `profitability_policy`, `authority_sources`,
and `rejection_categories`.

Expected safety posture:

- `read_only=true`
- `command_routes_mode="live_disabled"`
- `live_coinbase_orders_ran=false`
- `live_coinbase_read_ran=false`

Do not use this route as a browser preflight approval endpoint. Actual command
acceptance/rejection remains in the backend command service path.

## Audit Workbench Reads

Audit workbench reads expose backend-owned cross-module evidence. They are not
command routes and they do not mutate audit history, replay commands, call
Coinbase, or approve live execution.

```http
GET /api/v1/admin/audit-workbench?module=orders&client_order_id=client-order-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: auditor
```

The response includes `module_summary`, `events`, `filters`, `pagination`,
and no-live posture fields. Order events are keyed by `client_order_id`.
Stealth events use `stealth_order_id`. Futures/perpetual events use
`position_key`. Exchange-native ids appear only as exchange evidence.

Expected safety posture:

- `read_only=true`
- `command_routes_mode="evidence_only"`
- `live_coinbase_orders_ran=false`
- `live_coinbase_read_ran=false`

## Live Placement Approval

Current live-disabled command shape:

```json
{
  "product_id": "BTC-USDC",
  "side": "BUY",
  "order_type": "LIMIT",
  "quote_size": "1.00",
  "limit_price": "65000.00",
  "manual_live_acknowledgement": true
}
```

Required headers for that placement include:

```http
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1083
X-Correlation-Id: corr-20260610-002
X-Operator-Intent: manual_one_off
X-Admin-Actor: trader-001
X-Admin-Roles: trader
X-CSRF-Token: <configured-csrf-token-when-required>
```

Current backend behavior:

- parse the request through FastAPI/Pydantic
- authenticate actor and authorize `order:create`
- derive a stable backend-owned `client_order_id` before command admission
  when the request omitted one
- evaluate durable idempotency
- write durable command audit evidence
- return `501` with `status: "not_implemented"`
- never call Coinbase

Future backend behavior:

- validate product capability and size
- run action-condition guards
- enforce live caps
- create or verify an approval snapshot
- reuse the already-derived backend-owned `client_order_id`
- persist idempotency and audit state
- submit to Coinbase only after all gates pass

## Campaign Execution Command

Campaign execution is now a backend-owned command route, but live execution is
still disabled.

```http
POST /api/v1/spot/campaign/executions
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1084
X-Correlation-Id: corr-20260610-003
X-Operator-Intent: campaign_execute
X-Admin-Actor: trader-001
X-Admin-Roles: trader
Content-Type: application/json
X-CSRF-Token: <configured-csrf-token-when-required>
```

```json
{
  "campaign_id": "usdc-sweep-001",
  "side": "BUY",
  "quote_notional_per_product": "1.00",
  "product_ids": ["BTC-USDC", "ETH-USDC"],
  "dry_run": false,
  "manual_live_acknowledgement": true
}
```

Current response behavior:

- authorize `campaign:execute`
- evaluate idempotency
- write command audit evidence
- return `501` with `service_method: "execute_spot_campaign"`
- include approval/cap guard evidence
- never call Coinbase

## Spot Sweep Automation Command

Spot sweep automation now has a backend-owned command route, but live
execution, scheduler execution, and Coinbase submission are still disabled.

```http
POST /api/v1/spot/sweep/automation-runs
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1085
X-Correlation-Id: corr-20260613-001
X-Operator-Intent: sweep_automation_run
X-Admin-Actor: trader-001
X-Admin-Roles: trader
Content-Type: application/json
X-CSRF-Token: <configured-csrf-token-when-required>
```

```json
{
  "sweep_config_id": "spot-sweep-usdc-hourly",
  "side": "BUY",
  "quote_notional_per_product": "1.00",
  "repeat_every_hours": "6",
  "max_runs": 2,
  "max_products": 3,
  "max_total_notional_per_run": "3.00",
  "max_notional_per_order": "1.00",
  "max_planned_orders": 3,
  "run_if_due": true,
  "dry_run": false,
  "manual_live_acknowledgement": true
}
```

Current response behavior:

- authorize `spot_sweep:execute`
- evaluate idempotency
- write command audit and route-bound admission evidence
- return `501` with `service_method: "run_spot_sweep_automation"`
- include approval/cap/reconciliation/live-disabled guard evidence
- report `live_exchange_submitted=false` and `sweep_runner_invoked=false`
- never run sweep CLI tools and never call Coinbase

## Idempotent Retry

If the same `Idempotency-Key` and same command payload are sent again for the
same endpoint, path identity, actor/roles, and operator intent, the API should
return the original command result without minting a second `client_order_id`
or submitting a second Coinbase order.
For manual order create requests that omit `client_order_id`, the route derives
one from endpoint, actor, idempotency key, and payload hash before admission.
That derived id is response/audit evidence and the value future approval
snapshots must bind to; the browser must not invent it.

If the same `Idempotency-Key` is reused with a different payload, path
identity, actor/roles, or `X-Operator-Intent`, the API should return conflict.

## Read-Only Spot Operator Routes

Read-only routes always require `Authorization`. In `bootstrap_bearer` mode
they also require `X-Admin-Actor` and `X-Admin-Roles`. In `oidc_jwt` mode the
backend derives actor and roles from verified JWT claims and ignores those
bootstrap headers. Read routes do not require `Idempotency-Key`. Missing or
invalid auth returns `401`; insufficient role evidence returns `403`.

```http
GET /api/v1/spot/readiness?product_id=BTC-USDC
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Current read-only routes:

- `GET /api/v1/admin/bootstrap`
- `GET /api/v1/admin/health`
- `GET /api/v1/admin/session`
- `GET /api/v1/admin/oidc-readiness`
- `GET /api/v1/admin/capabilities`
- `GET /api/v1/admin/csrf`
- `GET /api/v1/admin/guard-risk-policy`
- `GET /api/v1/admin/audit-workbench`
- `GET /api/v1/admin/release-gate`
- `GET /api/v1/admin/recovery-gate`
- `GET /api/v1/admin/fill-ledger-health`
- `GET /api/v1/admin/frontend-fixtures`
- `GET /api/v1/admin/approvals`
- `GET /api/v1/admin/approvals/requests/{approval_request_id}`
- `GET /api/v1/admin/admission-audits`
- `GET /api/v1/admin/admission-audits/{admission_audit_id}`
- `GET /api/v1/admin/cap-guard/decisions`
- `GET /api/v1/admin/cap-guard/decisions/{decision_id}`
- `GET /api/v1/admin/reconciliation/plans`
- `GET /api/v1/admin/reconciliation/plans/{plan_id}`
- `GET /api/v1/orders`
- `GET /api/v1/orders/{client_order_id}`
- `GET /api/v1/stealth/orders`
- `GET /api/v1/stealth/orders/{stealth_order_id}`
- `GET /api/v1/stealth/command-suite`
- `GET /api/v1/movement-repricing/evidence`
- `GET /api/v1/movement-repricing/orders/{client_order_id}`
- `GET /api/v1/movement-repricing/stealth/{stealth_order_id}`
- `GET /api/v1/futures/account`
- `GET /api/v1/futures/positions`
- `GET /api/v1/futures/positions/{position_key}`
- `GET /api/v1/spot/readiness`
- `GET /api/v1/spot/sweep/status`
- `GET /api/v1/spot/sweep/pnl`
- `GET /api/v1/spot/pnl/checkpoints`
- `GET /api/v1/spot/pnl/checkpoints/{checkpoint_id}`
- `GET /api/v1/spot/cost-basis/status`
- `GET /api/v1/spot/campaign/status`
- `GET /api/v1/spot/direct-orders/{client_order_id}/audit`
- `GET /api/v1/spot/command-suite`

Spot P/L checkpoint records are local-state evidence for operator review. They
must be sourced from `/api/v1/spot/sweep/pnl`; they do not approve sells,
prove profitability, execute reconciliation, create tax lots, or submit
Coinbase orders.

```http
POST /api/v1/spot/pnl/checkpoints
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: trader-001
X-Admin-Roles: trader
Idempotency-Key: spot-pnl-checkpoint-2026-06-13
X-Correlation-Id: spot-pnl-checkpoint-request-2026-06-13
X-Operator-Intent: daily_spot_pnl_review
Content-Type: application/json
```

```json
{
  "checkpoint_id": "spot-pnl-checkpoint-2026-06-13",
  "scope": "portfolio",
  "product_ids": ["BTC-USDC", "ETH-USDC"],
  "source_report_route": "/api/v1/spot/sweep/pnl",
  "review_status": "passed",
  "pnl_snapshot": {
    "portfolio_mark_to_market_usdc": "128.40",
    "since_last_purchase_usdc": "3.21"
  },
  "average_cost_snapshot": {
    "source": "coinbase_average_cost"
  },
  "operator_notes": "Daily operator checkpoint from sweep P/L report."
}
```

Accepted responses include the persisted `checkpoint_id`, status, source
route, payload hash, and explicit no-authority flags:
`profitability_authority=false`, `sell_authority=false`,
`checkpoint_is_tax_accounting=false`, `live_exchange_submitted=false`, and
`live_coinbase_orders_ran=false`.
When the request includes `average_cost_snapshot`, responses also include
`average_cost_reviewed=true`, `average_cost_review_source`, and an
`average_cost_review_detail` warning that the review evidence is not sell,
profit, tax, browser guard, or Coinbase execution authority. List responses
include `average_cost_review_count`.
Accepted checkpoint records also include `audit_id`, `audit_linked=true`,
`audit_source=admin_api_audit_log`, and an `audit_detail` warning when the
append-only Admin API audit row is verified. List responses include
`audit_linked_count` for verified links only. A checkpoint with an `audit_id`
but no matching audit row is reported as unverified evidence. The audit link
does not execute recovery, reconciliation, Coinbase orders, or browser
authority.
Accepted checkpoint records also include `recovery_linked=true`,
`recovery_source=admin_recovery_gate`, `recovery_routes`, and a
`recovery_detail` warning when the checkpoint is linked to backend-owned
recovery triage reads. List responses include `recovery_linked_count`.
Recovery-link evidence points to `/api/v1/admin/recovery-gate` and
`/api/v1/admin/fill-ledger-health` only; it does not execute recovery, apply
repairs, roll back state, run reconciliation, call Coinbase, or create browser
recovery authority.
Accepted checkpoint records also include `reconciliation_linked=true`,
`reconciliation_source=admin_reconciliation_plans`, `reconciliation_routes`,
and a `reconciliation_detail` warning when the checkpoint read model is linked
to backend-owned reconciliation plan reads. List responses include
`reconciliation_linked_count`. Reconciliation-link evidence points to
`/api/v1/admin/reconciliation/plans` and
`/api/v1/admin/reconciliation/plans/{plan_id}` only; it does not execute
reconciliation, mutate order or exchange state, apply repairs, roll back
state, call Coinbase, or create browser reconciliation authority.

```http
GET /api/v1/spot/pnl/checkpoints?checkpoint_status=passed&limit=25
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

```http
GET /api/v1/spot/pnl/checkpoints/{checkpoint_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

`GET /api/v1/spot/command-suite` is M54 read-only backend evidence for the
current spot command families. It covers manual spot order placement, order
cancel by `client_order_id`, and campaign execution readiness. It does not
execute commands, approve live execution, evaluate wallet inventory in the
browser, or make spot-only rules reusable by futures/perpetuals or stealth
modules. Each command row includes backend-owned `proof_routes` for approval,
admission audit, cap/guard, and reconciliation records. These routes are
local-state evidence requirements only; they do not execute the command.
Each command row also includes backend-owned `readiness_preconditions` copied
from live-enablement evidence so operators can see which gates are configured,
blocking, or passed without treating the browser as a gate evaluator.
The response also includes `coverage_gaps` for remaining M54 spot families
that are not command-complete. Gap rows are read-only planning evidence, not
mutation routes or browser authority. Each gap row may include typed
`current_read_evidence` rows for existing read-only evidence routes derived
from backend route inventory.

The payload below is a historical spot command-suite example for the M54
`3301-3320` slice. It is not the current autonomous phase range. Current
active phase metadata lives in `docs/plans/AUTONOMOUS_WORK_QUEUE.md`.

```http
GET /api/v1/spot/command-suite
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

```json
{
  "type": "spot_command_suite",
  "module_id": "spot_operations",
  "status": "blocked",
  "approved_phase_range": "3301-3320",
  "command_count": 10,
  "blocked_command_count": 10,
  "live_enabled_command_count": 0,
  "executable_command_count": 0,
  "coverage_gap_count": 3,
  "spot_rules_platform_default": false,
  "browser_authority": "display_only",
  "bff_authority": "forward_only_no_execution",
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0",
  "commands": [
    {
      "mutation_family": "spot_manual_order",
      "route": "/api/v1/orders",
      "method": "POST",
      "identity_key": "client_order_id",
      "shared_method": "place_manual_order",
      "status": "blocked",
      "live_execution_status": "approval_required",
      "live_adapter_configured": true,
      "live_enabled": false,
      "executable": false,
      "proof_routes": [
        {
          "gate": "approval",
          "route": "/api/v1/admin/approvals/requests",
          "method": "POST",
          "action_class": "local_state_mutation",
          "required_permission": "approval:request",
          "shared_method": "create_approval_request",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "identity_key": "client_order_id",
          "command_identity_key": "client_order_id",
          "backend_owned": true,
          "route_bound": true,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "documentation_refs": [
            "README.admin-api.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/admin-api.md"
          ],
          "detail": "Create a backend-owned approval request bound to the exact route, method, actor, idempotency key, payload hash, and command identity."
        },
        {
          "gate": "approval",
          "route": "/api/v1/admin/approvals/requests/{approval_request_id}/decisions",
          "method": "POST",
          "action_class": "local_state_mutation",
          "required_permission": "approval:manage",
          "shared_method": "decide_approval_request",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "identity_key": "approval_request_id",
          "command_identity_key": "client_order_id",
          "backend_owned": true,
          "route_bound": true,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "documentation_refs": [
            "README.admin-api.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/admin-api.md"
          ],
          "detail": "Record the backend approval decision. Browser approval remains insufficient and does not execute the command."
        },
        {
          "gate": "audit",
          "route": "/api/v1/admin/admission-audits",
          "method": "POST",
          "action_class": "local_state_mutation",
          "required_permission": "admission_audit:record",
          "shared_method": "record_admission_audit",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "identity_key": "client_order_id",
          "command_identity_key": "client_order_id",
          "backend_owned": true,
          "route_bound": true,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "documentation_refs": [
            "README.admission-audits.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/admission-audits.md"
          ],
          "detail": "Append exact admission audit evidence for the route-bound command. The writer cannot mark live admission allowed."
        },
        {
          "gate": "cap_guard",
          "route": "/api/v1/admin/cap-guard/decisions",
          "method": "POST",
          "action_class": "local_state_mutation",
          "required_permission": "cap_guard:record",
          "shared_method": "record_cap_guard_decision",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "identity_key": "client_order_id",
          "command_identity_key": "client_order_id",
          "backend_owned": true,
          "route_bound": true,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "documentation_refs": [
            "README.cap-guard-decisions.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/cap-guard-decisions.md"
          ],
          "detail": "Record backend cap/guard evidence. The browser and BFF must not evaluate wallet, inventory, profitability, margin, or account limits."
        },
        {
          "gate": "reconciliation",
          "route": "/api/v1/admin/reconciliation/plans",
          "method": "POST",
          "action_class": "local_state_mutation",
          "required_permission": "reconciliation:record",
          "shared_method": "record_reconciliation_plan",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "identity_key": "client_order_id",
          "command_identity_key": "client_order_id",
          "backend_owned": true,
          "route_bound": true,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "documentation_refs": [
            "README.reconciliation-plans.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/reconciliation-plans.md"
          ],
          "detail": "Record backend reconciliation proof requirements. This does not execute reconciliation or mutate order/exchange state."
        }
      ],
      "readiness_preconditions": [
        {
          "precondition": "approval_snapshot",
          "status": "blocked",
          "required": true,
          "configured": false,
          "blocking": true,
          "backend_owned": true,
          "route_bound": true,
          "source": "not_configured",
          "expected_source": "approval_snapshot",
          "blocker": "approval_snapshot_missing",
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "evidence": [
            "No browser-side approval snapshot may satisfy live admission."
          ],
          "detail": "Approval snapshot evidence is required before live admission."
        },
        {
          "precondition": "browser_bff_boundary",
          "status": "passed",
          "required": true,
          "configured": true,
          "blocking": false,
          "backend_owned": true,
          "route_bound": true,
          "source": "frontend_boundary",
          "expected_source": "backend_contract",
          "blocker": null,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "evidence": [
            "Browser and BFF authority is bounded to display/forward-only evidence."
          ],
          "detail": "Browser and BFF authority cannot satisfy live admission."
        },
        {
          "precondition": "live_execution_service",
          "status": "blocked",
          "required": true,
          "configured": false,
          "blocking": true,
          "backend_owned": true,
          "route_bound": true,
          "source": "disabled_backend_service",
          "expected_source": "admin_api_live_execution_service",
          "blocker": "live_execution_disabled",
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "evidence": [
            "No Coinbase client method is exposed."
          ],
          "detail": "The backend live execution service is disabled."
        }
      ]
    },
    {
      "mutation_family": "spot_order_cancel",
      "route": "/api/v1/orders/{client_order_id}/cancel",
      "method": "POST",
      "identity_key": "client_order_id",
      "shared_method": "cancel_order_by_client_order_id",
      "status": "blocked",
      "live_execution_status": "live_disabled",
      "live_adapter_configured": false,
      "live_enabled": false,
      "executable": false
    },
    {
      "mutation_family": "spot_campaign_execution",
      "route": "/api/v1/spot/campaign/executions",
      "method": "POST",
      "identity_key": "campaign_id",
      "shared_method": "execute_spot_campaign",
      "status": "blocked",
      "live_execution_status": "live_disabled",
      "live_adapter_configured": false,
      "live_enabled": false,
      "executable": false
    },
    {
      "mutation_family": "spot_sweep_automation",
      "route": "/api/v1/spot/sweep/automation-runs",
      "method": "POST",
      "identity_key": "sweep_config_id",
      "shared_method": "run_spot_sweep_automation",
      "required_permission": "spot_sweep:execute",
      "status": "blocked",
      "live_execution_status": "live_disabled",
      "live_adapter_configured": false,
      "live_enabled": false,
      "executable": false
    }
  ],
  "coverage_gaps": [
    {
      "family": "spot_sweep_automation",
      "status": "blocked",
      "exposure_status": "admin_draft_live_disabled",
      "command_route": "/api/v1/spot/sweep/automation-runs",
      "current_read_evidence_routes": [
        "GET /api/v1/spot/sweep/status",
        "GET /api/v1/spot/campaign/status",
        "GET /api/v1/spot/command-suite"
      ],
      "current_read_evidence": [
        {
          "route": "/api/v1/spot/sweep/status",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "analytics:read",
          "shared_method": "build_spot_sweep_status",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "README.spot-portfolio-sweep.md",
            "docs/COMMAND_WORKFLOWS.md"
          ],
          "detail": "Existing read-only Admin API evidence route for a spot command-suite coverage gap; it does not create a command route, execute reconciliation, or call Coinbase."
        },
        {
          "route": "/api/v1/spot/campaign/status",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "analytics:read",
          "shared_method": "build_spot_campaign_status",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "README.spot-campaign.md",
            "docs/COMMAND_WORKFLOWS.md"
          ],
          "detail": "Existing read-only Admin API evidence route for a spot command-suite coverage gap; it does not create a command route, execute reconciliation, or call Coinbase."
        },
        {
          "route": "/api/v1/spot/command-suite",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "analytics:read",
          "shared_method": "build_spot_command_suite",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/admin-api.md"
          ],
          "detail": "Existing read-only Admin API evidence route for a spot command-suite coverage gap; it does not create a command route, execute reconciliation, or call Coinbase."
        }
      ],
      "required_backend_contract": "Durable enterprise sweep scheduling, pause/resume, run-limit, retry, execution-record, recovery, and reconciliation contract.",
      "required_gate_chain": [
        "route_inventory_contract",
        "approval_snapshot",
        "admission_audit",
        "cap_guard_decision",
        "reconciliation_plan",
        "live_execution_service"
      ],
      "missing_contracts": [
        "enterprise_sweep_scheduler_contract",
        "sweep_run_limit_contract",
        "sweep_pause_resume_contract",
        "sweep_retry_recovery_contract",
        "sweep_reconciliation_execution_contract"
      ],
      "backend_owned": true,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "spot_rule_boundary": "Spot-only wallet, USDC, no-shorting, inventory, cost-basis, and average-cost rules apply only to spot command authority.",
      "documentation_refs": [
        "README.spot-portfolio-sweep.md",
        "README.spot-campaign.md",
        "docs/COMMAND_WORKFLOWS.md"
      ],
      "detail": "Sweep and campaign evidence is readable, but enterprise admin sweep automation is not command-complete until durable scheduler, run-limit, recovery, and reconciliation contracts exist."
    },
    {
      "family": "spot_recovery_workflow",
      "status": "blocked",
      "exposure_status": "admin_draft_live_disabled",
      "command_route": "/api/v1/spot/recovery/apply-executions",
      "current_read_evidence_routes": [
        "GET /api/v1/spot/recovery/preview",
        "GET /api/v1/spot/recovery/apply-review",
        "GET /api/v1/spot/recovery/rollback-plan",
        "GET /api/v1/spot/recovery/reconciliation-proof",
        "GET /api/v1/admin/recovery-gate",
        "GET /api/v1/admin/reconciliation/plans",
        "GET /api/v1/admin/reconciliation/plans/{plan_id}",
        "GET /api/v1/spot/direct-orders/{client_order_id}/audit"
      ],
      "current_read_evidence": [
        {
          "route": "/api/v1/spot/recovery/preview",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "audit:read",
          "shared_method": "build_spot_recovery_preview",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "README.spot-trading.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/admin-api.md"
          ],
          "detail": "Existing read-only Admin API recovery preview route; it does not apply recovery, roll back state, execute reconciliation, mutate orders, or call Coinbase."
        },
        {
          "route": "/api/v1/spot/recovery/apply-review",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "audit:read",
          "shared_method": "build_spot_recovery_apply_review",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "README.admin-api.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/admin-api.md"
          ],
          "detail": "Read-only recovery apply-review contract evidence, including state-repair taxonomy, repair-target evidence, pre-apply snapshots, dry-run repair plans, guarded repair-result evidence, and completion-state evidence; it does not mutate order/exchange state, execute reconciliation, or call Coinbase."
        },
        {
          "route": "/api/v1/spot/recovery/rollback-plan",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "audit:read",
          "shared_method": "build_spot_recovery_rollback_plan",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "README.admin-api.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/admin-api.md"
          ],
          "detail": "Read-only recovery rollback-plan contract evidence, including state-repair taxonomy, repair-target evidence, pre-apply snapshots, dry-run repair plans, guarded repair-result evidence, and completion-state evidence; it does not execute order-state rollback, mutate exchange state, or call Coinbase."
        },
        {
          "route": "/api/v1/spot/recovery/reconciliation-proof",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "audit:read",
          "shared_method": "build_spot_recovery_reconciliation_proof",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "README.admin-api.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/admin-api.md"
          ],
          "detail": "Read-only recovery reconciliation-proof contract evidence, including completion-state, snapshot readback, and fail-closed execution-boundary evidence from backend proof, snapshot, execution-journal, repair-result, and completion records; it reads backend proof/snapshot records but does not write records, execute reconciliation, mutate exchange state, or call Coinbase."
        },
        {
          "route": "/api/v1/admin/recovery-gate",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "audit:read",
          "shared_method": "build_recovery_gate",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "README.admin-api.md",
            "docs/OPERATOR_READ_MODELS.md"
          ],
          "detail": "Existing read-only Admin API evidence route for a spot command-suite coverage gap; it does not create a command route, execute reconciliation, or call Coinbase."
        },
        {
          "route": "/api/v1/spot/direct-orders/{client_order_id}/audit",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "audit:read",
          "shared_method": "build_spot_direct_order_audit",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "README.spot-trading.md",
            "docs/OPERATOR_READ_MODELS.md"
          ],
          "detail": "Existing read-only Admin API evidence route for a spot command-suite coverage gap; it does not create a command route, execute reconciliation, or call Coinbase."
        }
      ],
      "required_backend_contract": "Spot recovery post-apply reconciliation completion evidence and fail-closed execution-boundary evidence exist. Proof persistence, execution journal evidence, guarded local repair-result evidence, state-repair taxonomy, repair-target evidence, pre-apply snapshots, dry-run repair plans, completion-state evidence, execution-boundary evidence, and read-only preview/apply-review/rollback-plan/reconciliation-proof evidence are already exposed.",
      "required_gate_chain": [
        "route_inventory_contract",
        "recovery_preview",
        "idempotency",
        "operator_intent",
        "approval_snapshot",
        "admission_audit",
        "rollback_plan",
        "reconciliation_proof",
        "post_apply_reconciliation_completion",
        "reconciliation_execution_boundary"
      ],
      "missing_contracts": [],
      "backend_owned": true,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "spot_rule_boundary": "Spot-only wallet, USDC, no-shorting, inventory, cost-basis, and average-cost rules apply only to spot command authority.",
      "documentation_refs": [
        "README.spot-trading.md",
        "docs/OPERATOR_READ_MODELS.md",
        "docs/COMMAND_WORKFLOWS.md"
      ],
      "detail": "Spot recovery preview, apply-review, rollback-plan, reconciliation-proof, recovery-gate, reconciliation-plan, direct-order audit reads, and recovery POST contracts do not execute reconciliation, mutate order/exchange state, or call Coinbase. State-repair taxonomy, repair targets, pre-apply snapshots, dry-run repair plans, guarded repair-result journals, completion states, guarded post-apply completion records, and execution-boundary rows are backend evidence only. Reconciliation execution must stay backend-owned before any recovery action can be considered exchange-complete."
    },
    {
      "family": "spot_reconciliation_workflow",
      "status": "blocked",
      "exposure_status": "backend_contract_required",
      "command_route": "/api/v1/spot/recovery/reconciliation-executions",
      "current_read_evidence_routes": [
        "GET /api/v1/spot/recovery/reconciliation-proof",
        "GET /api/v1/admin/reconciliation/plans",
        "GET /api/v1/admin/reconciliation/plans/{plan_id}"
      ],
      "current_read_evidence": [
        {
          "route": "/api/v1/spot/recovery/reconciliation-proof",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "audit:read",
          "shared_method": "build_spot_recovery_reconciliation_proof",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "README.admin-api.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/admin-api.md"
          ],
          "detail": "Existing read-only Admin API recovery reconciliation-proof contract route; it reads backend proof and execution-boundary evidence but does not write proof records, execute reconciliation, mutate exchange state, or call Coinbase."
        },
        {
          "route": "/api/v1/admin/reconciliation/plans",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "reconciliation:read",
          "shared_method": "list_reconciliation_plans",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "README.reconciliation-plans.md",
            "docs/examples/reconciliation-plans.md"
          ],
          "detail": "Existing read-only Admin API evidence route for a spot command-suite coverage gap; it does not create a command route, execute reconciliation, or call Coinbase."
        },
        {
          "route": "/api/v1/admin/reconciliation/plans/{plan_id}",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "reconciliation:read",
          "shared_method": "get_reconciliation_plan",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "README.reconciliation-plans.md",
            "docs/examples/reconciliation-plans.md"
          ],
          "detail": "Existing read-only Admin API evidence route for a spot command-suite coverage gap; it does not create a command route, execute reconciliation, or call Coinbase."
        }
      ],
      "required_backend_contract": "Spot-specific reconciliation execution contract that can compare backend order state with Coinbase evidence after the disabled execution boundary route/service, backend executor, and live Coinbase read authority exist without browser or BFF state mutation. The backend snapshot record contract exists as local no-live evidence only.",
      "required_gate_chain": [
        "route_inventory_contract",
        "reconciliation_plan",
        "reconciliation_proof_contract",
        "reconciliation_execution_boundary",
        "exchange_evidence_snapshot",
        "audit_link",
        "proof_persistence",
        "post_live_reconciliation"
      ],
      "missing_contracts": [
        "spot_reconciliation_execution_contract",
        "spot_reconciliation_repair_policy_contract"
      ],
      "backend_owned": true,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "spot_rule_boundary": "Spot-only wallet, USDC, no-shorting, inventory, cost-basis, and average-cost rules apply only to spot command authority.",
      "documentation_refs": [
        "README.reconciliation-plans.md",
        "docs/examples/reconciliation-plans.md",
        "docs/COMMAND_WORKFLOWS.md"
      ],
      "detail": "Reconciliation plan records are local-state evidence only. The recovery reconciliation-proof read now exposes local snapshot readback, the blocked execution boundary, and disabled command route, but plans, snapshots, and boundary evidence do not execute reconciliation, mutate exchange/order state, read Coinbase, or prove live Coinbase state."
    }
  ]
}
```

## Approval Lifecycle

Approval lifecycle routes write backend-owned local approval evidence only.
They do not submit orders, cancel orders, run guard checks, execute
reconciliation, or call Coinbase.

Create a route-bound approval request:

```http
POST /api/v1/admin/approvals/requests
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: trader-001
X-Admin-Roles: trader
Idempotency-Key: approval-request-001
X-Correlation-Id: corr-approval-001
X-Operator-Intent: request_manual_order_approval
Content-Type: application/json

{
  "route": "/api/v1/orders",
  "method": "POST",
  "module_id": "spot_operations",
  "identity_key": "client_order_id",
  "identity_value": "client-approved-001",
  "action_class": "live_exchange_place",
  "required_permission": "order:create",
  "operator_intent": "manual_one_off",
  "command_idempotency_key": "manual-order-idem-001",
  "payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "request_reason": "bounded canary approval"
}
```

Approve the request. Only an actor with `approval:manage` can decide or revoke
approval lifecycle records:

```http
POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: approval-decision-001
X-Correlation-Id: corr-approval-002
X-Operator-Intent: approve_manual_order_snapshot
Content-Type: application/json

{
  "decision": "approved",
  "decision_reason": "bounded canary approval",
  "expires_at": "2026-06-12T19:00:00+00:00",
  "cap_guard_decision_ref": "cap-guard-001",
  "reconciliation_plan_ref": "reconciliation-001"
}
```

Revoke an approved snapshot:

```http
POST /api/v1/admin/approvals/{approval_id}/revoke
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: approval-revoke-001
X-Correlation-Id: corr-approval-003
X-Operator-Intent: revoke_manual_order_snapshot
Content-Type: application/json

{
  "revoke_reason": "operator cancelled the approval"
}
```

## Admission Audit Records

Admission audit routes persist backend-owned command admission proof only.
They do not submit orders, call Coinbase, run cap/guard checks, execute
reconciliation, or let the browser/BFF write audit authority.

List recorded admission audits:

```http
GET /api/v1/admin/admission-audits?admission_status=blocked&limit=10
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Read one admission audit:

```http
GET /api/v1/admin/admission-audits/audit-admission-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Record one backend admission audit proof:

```http
POST /api/v1/admin/admission-audits
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: admission-audit-record-001
X-Correlation-Id: corr-admission-audit-001
X-Operator-Intent: record_manual_order_admission_audit
Content-Type: application/json

{
  "route": "/api/v1/orders",
  "method": "POST",
  "module_id": "spot_operations",
  "identity_key": "client_order_id",
  "identity_value": "client-approved-001",
  "action_class": "live_exchange_place",
  "required_permission": "order:create",
  "service_method": "place_manual_order",
  "actor_id": "operator-001",
  "operator_intent": "manual_one_off",
  "command_idempotency_key": "manual-order-idem-001",
  "payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "approval_snapshot_id": "approval-snapshot-001",
  "approval_snapshot_approved_by_actor_id": "approver-001",
  "approval_snapshot_requested_by_actor_id": "operator-001",
  "approval_snapshot_expires_at": "2026-06-12T19:00:00+00:00",
  "approval_cap_guard_decision_ref": "cap-guard-001",
  "approval_reconciliation_plan_ref": "reconciliation-001",
  "allowed": false,
  "status": "blocked",
  "reason": "backend admission audit proof recorded before cap/guard and reconciliation proofs"
}
```

The writer rejects records that claim `allowed=true` or `status=passed`.
The returned `admission_audit_id` can be linked by cap/guard and
reconciliation records, but it does not authorize live execution.

## Cap/Guard Decision Records

Cap/guard decision routes persist backend-owned admission evidence only. They
do not submit orders, call Coinbase, or let the browser/BFF evaluate wallet,
margin, profitability, inventory, account-limit, or spot-specific guard rules.

List recorded decisions:

```http
GET /api/v1/admin/cap-guard/decisions?decision_status=passed&limit=10
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Read one decision:

```http
GET /api/v1/admin/cap-guard/decisions/cap-guard-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Record one backend cap/guard decision:

```http
POST /api/v1/admin/cap-guard/decisions
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: cap-guard-record-001
X-Correlation-Id: corr-cap-guard-001
X-Operator-Intent: record_manual_order_cap_guard
Content-Type: application/json

{
  "route": "/api/v1/orders",
  "method": "POST",
  "module_id": "spot_operations",
  "identity_key": "client_order_id",
  "identity_value": "client-approved-001",
  "action_class": "live_exchange_place",
  "required_permission": "order:create",
  "service_method": "place_manual_order",
  "actor_id": "admin-001",
  "operator_intent": "manual_one_off",
  "command_idempotency_key": "manual-order-idem-001",
  "payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "approval_snapshot_id": "approval-snapshot-001",
  "approval_cap_guard_decision_ref": "cap-guard-001",
  "admission_audit_id": "audit-admission-001",
  "allowed": true,
  "status": "passed",
  "cap_policy_ref": "submitted_notional_cap:3.10",
  "guard_policy_ref": "action_condition_guard:manual_order",
  "product_scope": "BTC-USDC",
  "max_submitted_notional_usdc": "3.10",
  "max_executed_notional_usdc": "1.00",
  "reason": "backend cap and guard inputs accepted the route-bound envelope"
}
```

Only `allowed=true` with `status=passed` is resolver-eligible. Any mismatch,
blocked status, warning status, route mismatch, permission mismatch, or
duplicate decision id fails closed as evidence only.

Revoked and expired snapshots fail closed in the existing approval resolver.
An approved snapshot still does not make a command executable while cap/guard,
admission audit, reconciliation, disabled live service, and remaining execution
gates remain blocked.

## Reconciliation Plan Records

Reconciliation plan routes persist backend-owned post-submit reconciliation
plan evidence only. They do not submit orders, call Coinbase, execute
reconciliation, mutate order state, mutate exchange state, or let the
browser/BFF create reconciliation proof.

List recorded plans:

```http
GET /api/v1/admin/reconciliation/plans?plan_status=passed&limit=10
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Read one plan:

```http
GET /api/v1/admin/reconciliation/plans/reconciliation-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Record one backend reconciliation plan:

```http
POST /api/v1/admin/reconciliation/plans
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: reconciliation-plan-record-001
X-Correlation-Id: corr-reconciliation-plan-001
X-Operator-Intent: record_manual_order_reconciliation_plan
Content-Type: application/json

{
  "route": "/api/v1/orders",
  "method": "POST",
  "module_id": "spot_operations",
  "identity_key": "client_order_id",
  "identity_value": "client-approved-001",
  "action_class": "live_exchange_place",
  "required_permission": "order:create",
  "service_method": "place_manual_order",
  "actor_id": "admin-001",
  "operator_intent": "manual_one_off",
  "command_idempotency_key": "manual-order-idem-001",
  "payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "approval_snapshot_id": "approval-snapshot-001",
  "approval_reconciliation_plan_ref": "reconciliation-001",
  "admission_audit_id": "audit-admission-001",
  "cap_guard_decision_id": "cap-guard-001",
  "allowed": true,
  "status": "passed",
  "reconciliation_policy_ref": "post_submit_reconciliation:manual_order",
  "product_scope": "BTC-USDC",
  "exchange_submission_required": true,
  "post_submit_reconciliation_required": true,
  "retained_inventory_required": true,
  "max_submitted_notional_usdc": "3.10",
  "max_executed_notional_usdc": "1.00",
  "reason": "backend reconciliation plan accepted the route-bound envelope"
}
```

Only `allowed=true` with `status=passed` is resolver-eligible. Any mismatch,
blocked status, warning status, read-only route target, local-state route
target, permission mismatch, or duplicate plan id fails closed as evidence
only.

## Live-Service Decision Evidence

Live-service decision routes persist backend-owned disabled-service evidence
only. They do not enable live service, construct adapters, call Coinbase,
invoke managers, execute reconciliation, mutate state, clear M55 blockers, or
let the browser/BFF create execution authority.

List recorded decisions:

```http
GET /api/v1/admin/live-execution/service-decisions?decision_status=blocked&limit=10
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Read one decision:

```http
GET /api/v1/admin/live-execution/service-decisions/live-service-decision-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Record one disabled backend live-service decision:

```http
POST /api/v1/admin/live-execution/service-decisions
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: live-service-decision-record-001
X-Correlation-Id: corr-live-service-decision-001
X-Operator-Intent: record_disabled_live_service_decision
Content-Type: application/json

{
  "decision_id": "live-service-decision-001",
  "status": "blocked",
  "requested_service_status": "live_disabled",
  "service_enabled": false,
  "deployment_ref": "deployment-live-service-disabled",
  "runtime_configuration_ref": "runtime-live-service-disabled",
  "decision_reason": "Record explicit disabled service decision evidence.",
  "live_coinbase_execution_approved": false,
  "max_submitted_notional_usdc": "0",
  "max_executed_notional_usdc": "0"
}
```

The writer rejects enabled service decisions, live Coinbase approval,
`passed` status, any requested service status other than `live_disabled`, and
nonzero submitted or executed notional. Recorded rows remain
`resolver_eligible=false`.

## Live-Adapter Decision Evidence

Live-adapter decision routes persist backend-owned disabled adapter
construction evidence only. They do not construct adapters, enable live
service, call Coinbase, invoke managers, execute reconciliation, mutate state,
clear M55 blockers, or let the browser/BFF create execution authority.

List recorded decisions:

```http
GET /api/v1/admin/live-execution/adapter-decisions?decision_status=blocked&limit=10
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Read one decision:

```http
GET /api/v1/admin/live-execution/adapter-decisions/live-adapter-decision-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Record one disabled backend live-adapter decision:

```http
POST /api/v1/admin/live-execution/adapter-decisions
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: live-adapter-decision-record-001
X-Correlation-Id: corr-live-adapter-decision-001
X-Operator-Intent: record_disabled_live_adapter_decision
Content-Type: application/json

{
  "decision_id": "live-adapter-decision-001",
  "status": "blocked",
  "requested_adapter_status": "live_disabled",
  "target_route": "/api/v1/orders",
  "target_method": "POST",
  "target_module_id": "spot_operations",
  "target_service_method": "place_manual_order",
  "adapter_reference": "AdminApiCommandService.place_manual_order",
  "adapter_constructed": false,
  "adapter_enabled": false,
  "construction_review_ref": "construction-review-001",
  "decision_reason": "Record explicit disabled adapter decision evidence.",
  "live_coinbase_execution_approved": false,
  "max_submitted_notional_usdc": "0",
  "max_executed_notional_usdc": "0"
}
```

The writer rejects constructed or enabled adapter decisions, live Coinbase
approval, `passed` status, requested adapter status other than
`live_disabled`, nonzero submitted or executed notional, and target route
bindings that do not match route inventory. The target route must also be a
`POST` non-read-only command surface whose `shared_method` exists on
`AdminApiCommandService`; read-only routes and unrelated local-state services
are rejected. Recorded rows remain `resolver_eligible=false`.

## Structured Errors

Auth, RBAC, and validation errors return JSON bodies shaped for frontend
display:

```json
{
  "code": "auth_required",
  "message": "Invalid Admin API bearer token",
  "severity": "warning",
  "correlation_id": "corr-20260610-004",
  "live_coinbase_orders_ran": false
}
```

Every response includes `X-Correlation-Id`, `X-Request-Id`,
`X-Admin-Api-Version`, and `X-Live-Execution-Enabled`.

## Frontend Smoke Commands

From `C:\coinbase-frontend`, use the canonical release-hardening gate to
validate the route inventory, artifact evidence, runtime evidence, autonomous
queue posture, tests, and dry smokes without contacting Coinbase:

```powershell
npm run release:gate
```

Against a local Admin API, configure `ADMIN_API_BASE_URL`,
`ADMIN_API_BEARER_TOKEN`, `ADMIN_API_ACTOR_ID`, and `ADMIN_API_ROLES`. If
backend CSRF is required, also configure `ADMIN_API_CSRF_TOKEN`, then run:

```powershell
npm run smoke:read
npm run smoke:command
```

Direct frontend smoke scripts still accept `ADMIN_API_ACTOR` as a legacy
fallback, but `ADMIN_API_ACTOR_ID` is the canonical actor variable shared with
BFF mode.

The command smoke expects `501` live-disabled responses for live execution
commands, `400` prerequisite rejections for Spot recovery proof/snapshot writer probes
when prerequisite records are absent, and accepted local-state responses for
checkpoint/proof records when their backend prerequisites are satisfied. It
reports live Coinbase execution as not run with notional `$0`.

The frontend release artifact bundle includes:

- `artifacts/release-readiness.json`
- `artifacts/deployment-package-manifest.json`
- `artifacts/observability-drill.json`
- `artifacts/synthetic-probes.json`
- `artifacts/public-release-checklist.json`
- `artifacts/runtime-evidence.json`

Those artifacts are no-live deployment evidence. They are not approval for
live Coinbase execution and not backend approval to place or cancel Coinbase
orders.
The autonomous queue remains part of the no-live release gate, and these
artifacts are not approval for live Coinbase execution.

For same-origin BFF smoke, start the frontend with `NEXT_PUBLIC_ADMIN_API_MODE=bff`
and server-only `ADMIN_API_*` variables, then run:

```powershell
$env:FRONTEND_BASE_URL = "http://127.0.0.1:3000"
npm run smoke:bff
```

BFF smoke reads through `/api/admin/api/v1/...` and posts to BFF command
routes expecting backend `501` live-disabled responses for live execution
commands and backend `400` prerequisite rejections for Spot recovery
proof/snapshot writer probes. It must report live Coinbase execution as not run with
notional `$0`.

The BFF copies only documented response-evidence headers back to browser code:
`Content-Type`, `X-Correlation-Id`, `X-Request-Id`,
`X-Admin-Api-Version`, `X-Live-Execution-Enabled`, and
`X-Idempotency-Replayed`. Missing BFF server authority should be handled as
`admin_bff_proxy_error`, not as a trading approval or Coinbase execution
failure.

The frontend deployment package manifest and observability drill are no-live
evidence artifacts. `server_env_static` BFF authority is local/staging evidence
only; production readiness is conditional on frontend `backend_oidc_jwt` BFF
mode and backend `oidc_jwt` verifier configuration.

## Current Futures Validation Record Evidence

Example active `6501-6520` range responses include futures request payload
validation evidence record contract evidence. This carries forward completed
futures request payload validation evidence and adds disabled validation-record
contract rows.
One-line evidence phrase: futures request payload validation evidence record contract evidence.
`"approved_phase_range": "6541-6560"`,
`"request_payload_validation_evidence_count": 22`,
`"blocking_request_payload_validation_evidence_count": 22`,
`"ready_request_payload_validation_evidence_count": 0`,
`"recorded_request_payload_validation_evidence_count": 0`,
`"runtime_observed_request_payload_validation_evidence_count": 0`,
`"request_payload_validation_evidence"`,
`"validation_evidence_contract_ref"`,
`"validation_evidence_field_refs"`,
`"validation_evidence_field_count"`,
`"runtime_evidence_satisfies_validation_evidence": false`,
`"validation_evidence_ready": false`,
`"validation_evidence_recorded": false`,
`"request_payload_validation_evidence_record_count": 22`,
`"blocking_request_payload_validation_evidence_record_count": 22`,
`"ready_request_payload_validation_evidence_record_count": 0`,
`"stored_request_payload_validation_evidence_record_count": 0`,
`"runtime_observed_request_payload_validation_evidence_record_count": 0`,
`"request_payload_validation_evidence_records"`,
`"validation_record_contract_ref"`, `"validation_record_store_ref"`,
`"validation_record_writer_ref"`, `"validation_record_replay_guard_ref"`,
`"validation_record_field_refs"`, `"validation_record_field_count"`,
`"validation_record_contract_ready": false`,
`"validation_record_store_ready": false`,
`"validation_record_writer_enabled": false`,
`"validation_record_replay_guard_ready": false`,
`"validation_recorded": false`,
`"append_only_validation_record": false`,
`"validation_record_idempotency_bound": false`,
`"validator_input_schema_ref"`, `"validator_output_schema_ref"`,
`"validator_registration_ref"`, and `"request_payload_validated": false`.
The validation evidence rows come from
`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS` and
`iter_futures_request_payload_validation_evidence`; validation-record rows come
from `FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS` and
`iter_futures_request_payload_validation_evidence_records`. They are no-live
display evidence and do not validate command request payloads, record
validation evidence, write append-only validation records, or register payload
validators. Completed registration evidence remains available through
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS` and
`iter_futures_request_payload_validator_registrations`, while completed
output-schema evidence remains available through
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS` and
`iter_futures_request_payload_validator_output_schemas`.
