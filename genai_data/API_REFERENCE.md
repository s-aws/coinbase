# API Reference

This file covers active API surfaces in the codebase:
- Coinbase REST wrapper (`external/coinbase_client.py`)
- Coinbase WebSocket wrapper (`external/coinbase_websocket.py`)
- Dashboard WebSocket message contract (`dashboard_server.py`)
- Enterprise Admin API contract (`api/v1/app.py`)

## Enterprise Admin API (`api/v1/app.py`)

The backend owns the OpenAPI contract for the enterprise admin frontend.
Read-only operator routes are active. Mutating HTTP routes are intentionally
not a live trading path yet: they run auth/RBAC, idempotency, audit, and shared
command-service parity logic, then stop at the fail-closed live execution gate.

Current generated schema artifact:
- `openapi/coinbase-admin-api.yaml`

Current M57 `7721-7740` futures/perpetual command prerequisite summary
evidence for `GET /api/v1/futures/command-suite` is the active slice. It adds
read-only `prerequisite_summary_count`,
`prerequisite_summary_blocking_count`, and `prerequisite_summaries` fields
derived from existing per-command prerequisite rows and carries forward
completed `7701-7720` command enablement contextless-review blocker evidence.
The fields are read-only/no-live evidence and must not resolve prerequisites,
clear command enablement, pass contextless review for command readiness, admit
commands, pass approval, cap/guard, or reconciliation gates, execute
reconciliation, call Coinbase, mutate futures/order/exchange state, or grant
browser/BFF or spot-rule authority.

Completed M57 `7701-7720` futures/perpetual command enablement
contextless-review blocker summary evidence for
`GET /api/v1/futures/command-suite` is carried forward history. It added
read-only review evidence fields to the existing command enablement blocker
summary and carried the latest completed `7681-7700` blind-review result.

Completed M57 `7681-7700` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
record-validation check output schema field-constraint source-ref
validation-record acceptance contextless-review acceptance evidence for
`GET /api/v1/futures/command-suite` is carried forward history. It added
disabled clearance-step review input store record-validation check output
schema field-constraint source-ref validation-record acceptance
contextless-review acceptance rows through a registry derived from
`application/admin_api/futures_request_payload_validation_record_validation_check_output_schema_field_constraint_source_ref_validation_record_acceptance_contextless_reviews.py`.

Completed M57 `7661-7680` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
record-validation check output schema field-constraint source-ref
validation-record acceptance contextless-review evidence for
`GET /api/v1/futures/command-suite` adds disabled rows through
`application/admin_api/futures_request_payload_validation_record_validation_check_output_schema_field_constraint_source_ref_validation_record_acceptance_contextless_reviews.py`.
Completed M57 `7641-7660` clearance-step review input store
record-validation check output schema field-constraint source-ref
validation-record acceptance evidence is now carried forward history.

Completed M57 `7541-7560` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
record-validation check output schema field-constraint evidence for
`GET /api/v1/futures/command-suite` adds disabled clearance-step review input
store record-validation check output schema field-constraint rows through
`application/admin_api/futures_request_payload_validation_record_validation_check_output_schema_field_constraints.py`.
Completed M57 `7521-7540` clearance-step review input store
record-validation check output schema field-type evidence is now carried
forward history.

Completed M57 `7501-7520` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
record-validation check output schema field-name evidence for
`GET /api/v1/futures/command-suite` adds disabled clearance-step review input
store record-validation check output schema field-name rows through
`application/admin_api/futures_request_payload_validation_record_validation_check_output_schema_field_names.py`.
Completed M57 `7481-7500` clearance-step review input store
record-validation check output schema field evidence is now carried forward
history.
Those rows are read-only/no-live evidence and do not declare field names,
source refs, fields, schemas, acceptance contracts, or contextless review; they
also do not ready validation-check output schema field names, accept or validate
records, admit commands, execute reconciliation, call Coinbase, mutate
futures/order/exchange state, or grant browser/BFF or spot-rule authority.

Completed M57 `7481-7500` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
record-validation check output schema field evidence for
`GET /api/v1/futures/command-suite` adds disabled clearance-step review input
store record-validation check output schema field rows through
`application/admin_api/futures_request_payload_validation_record_validation_check_output_schema_fields.py`.
Completed M57 `7461-7480` clearance-step review input store
record-validation check output schema evidence is now carried forward history.
Those rows are read-only/no-live evidence and do not declare field names,
field types, constraints, source refs, acceptance contracts, or contextless
review; they also do not ready validation-check output schema fields, accept or
validate records, admit commands, execute reconciliation, call Coinbase, mutate
futures/order/exchange state, or grant browser/BFF or spot-rule authority.

Completed M57 `7461-7480` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
record-validation check output schema evidence for
`GET /api/v1/futures/command-suite` adds disabled clearance-step review input
store record-validation check output schema rows through
`application/admin_api/futures_request_payload_validation_record_validation_check_output_schemas.py`.
Completed M57 `7441-7460` clearance-step review input store
record-validation check input schema field evidence is now carried forward
history.

Completed M57 `7421-7440` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
record-validation check input schema evidence for `GET /api/v1/futures/command-suite`:
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency work-item
claim-trace clearance-step review input store record-validation check input
schema evidence; futures request payload validation record execution-eligibility
resolution-plan step review input store record-validation remediation
dependency work-item claim-trace clearance-step review input store
record-validation check input schema display.

Completed M57 `7401-7420` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
record-validation check contract evidence for `GET /api/v1/futures/command-suite`:
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency work-item
claim-trace clearance-step review input store record-validation check contract
evidence; futures request payload validation record execution-eligibility
resolution-plan step review input store record-validation remediation
dependency work-item claim-trace clearance-step review input store
record-validation check contract display.

Completed M57 `7381-7400` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
record-validation check evidence for `GET /api/v1/futures/command-suite`:
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency work-item
claim-trace clearance-step review input store record-validation check evidence;
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency work-item
claim-trace clearance-step review input store record-validation check display.

Completed M57 `7361-7380` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
record-validation evidence for `GET /api/v1/futures/command-suite`: futures
request payload validation record execution-eligibility resolution-plan step
review input store record-validation remediation dependency work-item
claim-trace clearance-step review input store record-validation evidence;
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency work-item
claim-trace clearance-step review input store record-validation display.

Completed M57 `7341-7360` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
record-contract evidence for `GET /api/v1/futures/command-suite`: futures
request payload validation record execution-eligibility resolution-plan step
review input store record-validation remediation dependency work-item
claim-trace clearance-step review input store record-contract evidence;
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency work-item
claim-trace clearance-step review input store record-contract display.

Completed M57 `7321-7340` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
requirement evidence for `GET /api/v1/futures/command-suite`: futures request
payload validation record execution-eligibility resolution-plan step review
input store record-validation remediation dependency work-item claim-trace
clearance-step review input store requirement evidence; futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store requirement display.

Completed M57 `7301-7320` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input
evidence for `GET /api/v1/futures/command-suite`:
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency work-item
claim-trace clearance-step review input evidence; futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input display.

Completed M57 `7281-7300` futures/perpetual request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review evidence for
`GET /api/v1/futures/command-suite`:
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency work-item
claim-trace clearance-step review evidence; futures request payload validation
record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review display; carried-forward completed `7261-7280` futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance step
evidence; futures request payload validation record execution-eligibility
resolution-plan step review input store record-validation remediation
dependency work-item claim-trace clearance step display; carried-forward
completed `7241-7260` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item
claim-trace clearance plan evidence; futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance plan
display; carried-forward completed `7221-7240` futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim trace evidence;
carried-forward completed `7201-7220`
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency work-item
evidence; futures request payload validation record execution-eligibility
resolution-plan step review input store record-validation remediation
dependency work-item display; carried-forward completed `7181-7200`
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency evidence;
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency display;
carried-forward completed `7161-7180` futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation evidence and display; carried-forward completed `7141-7160`
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation evidence and display; carried-forward
completed `7121-7140` futures request payload validation record
execution-eligibility resolution-plan step review input store record-contract
evidence and display; and earlier carried-forward store requirement, review
input, review, step, and resolution-plan evidence. The
current source registries are
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plans.py`
and
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_steps.py`
and
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_reviews.py`
and
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_inputs.py`
and
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirements.py`
and
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contracts.py`
and
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validations.py`
and
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediations.py`
and
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependencies.py`
and
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_items.py`
and
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_traces.py`
with store record-validation remediation dependency work-item claim-trace rows
derived from each store record-validation remediation dependency work-item row.
Representative command-suite keys:
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_contract_ref`,
`review_input_store_record_validation_remediation_dependency_work_item_claim_trace_kind`,
`record_validation_remediation_dependency_work_item_claim_trace_gate`,
`claim_trace_claim`,
`claim_trace_target_ref`,
`claim_trace_source_ref`,
`record_validation_remediation_dependency_work_item_claim_trace_required=true`,
`record_validation_remediation_dependency_work_item_claim_trace_ready=false`,
`record_validation_remediation_dependency_work_item_claim_trace_created=false`,
`claim_trace_created=false`,
`claim_trace_ready=false`,
`claim_allowed=false`,
`claim_resolved=false`,
`claim_review_accepted=false`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_contract_ref`,
`review_input_store_record_validation_remediation_dependency_work_item_kind`,
`record_validation_remediation_dependency_work_item_gate`,
`record_validation_remediation_dependency_work_item_required=true`,
`record_validation_remediation_dependency_work_item_ready=false`,
`record_validation_remediation_dependency_work_item_created=false`,
`record_validation_remediation_dependency_work_item_claimed=false`,
`claim_ledger_registered=false`,
`owner_review_accepted=false`,
`contextless_review_passed=false`,
`accepts_evidence=false`,
`writes_evidence=false`,
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
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_contract_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_contract_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_contract_ref`,
`review_input_store_record_validation_remediation_dependency_kind`,
`record_validation_remediation_dependency_gate`,
`record_validation_remediation_dependency_action_refs`,
`record_validation_remediation_dependency_blockers`,
`record_validation_remediation_dependency_required=true`,
`record_validation_remediation_dependency_ready=false`,
`record_validation_remediation_dependency_resolved=false`,
`record_validation_remediation_dependency_performed=false`,
`record_validation_remediation_dependency_graph_ready=false`,
`record_validation_remediation_dependency_work_item_created=false`,
`record_validation_remediation_dependency_work_item_claimed=false`,
`record_validation_remediation_dependency_claim_trace_created=false`,
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
`record_validation_required=true`,
`record_validation_ready=false`,
`record_validation_configured=false`,
`record_validation_registered=false`,
`record_validation_gate_ready=false`,
`record_validation_gate_passed=false`,
`record_validation_replay_guard_ready=false`,
`record_validation_schema_ready=false`,
`record_validation_append_only_log_ready=false`,
`record_validation_idempotency_bound=false`,
`record_validation_payload_bound=false`,
`record_validation_contextless_review_passed=false`,
`record_validation_performed=false`,
`record_validation_accepted=false`,
`record_validation_recorded=false`,
`record_validation_remediation_required=true`,
`record_validation_remediation_ready=false`,
`record_validation_remediation_configured=false`,
`record_validation_remediation_performed=false`,
`record_validation_remediation_recorded=false`,
`record_validation_remediation_accepted=false`,
`record_validation_remediation_work_item_created=false`,
`record_validation_remediation_dependency_ready=false`,
`ordered_resolution_step_ref`,
`ordered_resolution_step_refs`, `ordered_resolution_step_count`,
`resolution_plan_present=true`, `resolution_plan_ready=false`,
`resolution_plan_accepted=false`,
`runtime_evidence_satisfies_semantic_contract=false`,
`validation_record_admission_link_ready=false`, and
`blocker_resolved=false`. Resolution plan step review input store
record-validation remediation dependency presence is not blocker resolution,
runtime acceptance, dependency graph creation, work item creation, claim trace
creation, command admission, Coinbase execution, reconciliation execution,
futures/order/exchange mutation, browser/BFF execution authority, remediation
dependency authority, remediation authority, validation authority, or
spot-rule authority. Resolution plan step review input store record-validation
remediation presence is not blocker resolution, runtime acceptance, command
admission, Coinbase execution, reconciliation execution, futures/order/exchange
mutation, browser/BFF execution authority, remediation authority, validation
authority, or spot-rule authority. Resolution plan step review input store
record-validation presence is not blocker resolution,
runtime acceptance,
command admission, Coinbase execution, reconciliation execution,
futures/order/exchange mutation, browser/BFF execution authority, validation
authority, or spot-rule authority. Resolution plan step review input store
record-contract presence is not blocker resolution. Resolution plan step review
input store requirement presence is not blocker resolution. Resolution plan step
review input presence is not blocker resolution. Resolution plan step review
presence is not blocker resolution.

Completed M57 `7041-7060` futures/perpetual request payload validation record
execution-eligibility resolution-plan step evidence for
`GET /api/v1/futures/command-suite` exposed
`execution_eligibility_resolution_plan_step_ref`,
`execution_eligibility_resolution_plan_step_contract_ref`,
`resolution_plan_step_kind`, `resolution_plan_step_ready=false`,
`resolution_plan_step_accepted=false`, and `blocker_resolved=false`.

Completed M57 `7021-7040` futures/perpetual request payload validation record
execution-eligibility resolution-plan evidence for
`GET /api/v1/futures/command-suite` exposed
`execution_eligibility_resolution_plan_ref`,
`execution_eligibility_resolution_plan_contract_ref`,
`ordered_resolution_step_refs`, `ordered_resolution_step_count`,
`resolution_plan_present=true`, `resolution_plan_ready=false`,
`resolution_plan_accepted=false`, and `blocker_resolved=false`.

Completed M57 `7001-7020` futures/perpetual request payload validation record
execution-eligibility semantic closure for
`GET /api/v1/futures/command-suite`: futures request payload validation record
execution-eligibility semantic closure evidence; futures request payload
validation record execution-eligibility evidence; futures request payload
validation record execution-eligibility blocker evidence; carried-forward
futures request payload contract registry evidence; futures request payload validator contract
registry evidence; futures request payload validator input-schema evidence;
futures request payload validator output-schema evidence; futures request
payload validator registration evidence; futures request payload validation
evidence; futures request payload validation evidence record contract evidence;
futures request payload validation record schema evidence; futures request
payload validation record replay guard evidence; futures request payload
validation record audit-link evidence; futures request payload validation
record admission-link evidence; futures request payload validation record
semantic artifact definition review evidence; futures request payload
validation record semantic artifact definition review input evidence; futures
request payload validation record semantic artifact definition review output
evidence; futures request payload validation record semantic artifact
definition review output acceptance evidence; futures request payload
validation record semantic artifact runtime evidence binding; futures request
payload validation record semantic artifact runtime evidence acceptance
evidence; futures request payload validation record position semantics;
futures request payload validation record margin semantics; futures request
payload validation record collateral semantics; futures request payload
validation record liquidation semantics; futures request payload validation
record reduce-only semantics; futures request payload validation record
close-only semantics; futures request payload validation record funding
semantics; futures request payload validation record order semantics; futures
request payload validation record cancel semantics; and completed
`6981-7000` futures request payload validation record reconciliation
semantics. Source registries include
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

Completed semantic closure source files are
`application/admin_api/futures_request_payload_validation_record_execution_eligibilities.py`
and
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_blockers.py`.
They expose present disabled contract evidence, not readiness or runtime
acceptance. Semantic contract presence is not runtime acceptance, command
admission, Coinbase execution, reconciliation execution,
futures/order/exchange mutation, browser/BFF execution authority, or
spot-rule authority.

Representative command-suite keys:
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
`semantic_contract_ref`, `semantic_contract_present=true`,
`semantic_contract_ready=false`,
`request_payload_validator_contract_count`,
`blocking_request_payload_validator_contract_count`,
`request_payload_validator_input_schema_count`,
`blocking_request_payload_validator_input_schema_count`,
`request_payload_validator_output_schema_count`,
`blocking_request_payload_validator_output_schema_count`,
`request_payload_validator_registration_count`,
`blocking_request_payload_validator_registration_count`,
`request_payload_validation_evidence_count`,
`blocking_request_payload_validation_evidence_count`,
`request_payload_validation_evidence_record_count`,
`blocking_request_payload_validation_evidence_record_count`,
`request_payload_validation_record_schema_count`,
`blocking_request_payload_validation_record_schema_count`,
`request_payload_validation_record_replay_guard_count`,
`blocking_request_payload_validation_record_replay_guard_count`,
`request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
`blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
`ready_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
`runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
`request_payload_validation_record_semantic_artifact_runtime_evidences`,
`request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
`blocking_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
`ready_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
`runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
`request_payload_validation_record_semantic_artifact_definition_review_output_acceptances`,
`request_payload_validation_record_reconciliation_semantic_count`,
`blocking_request_payload_validation_record_reconciliation_semantic_count`,
`ready_request_payload_validation_record_reconciliation_semantic_count`,
`runtime_observed_request_payload_validation_record_reconciliation_semantic_count`,
`request_payload_validation_record_reconciliation_semantics`,
`validation_gate_ref`, `validation_evidence_ref`, `validator_contract_ref`,
`validator_input_schema_ref`, `validator_output_schema_ref`,
`output_schema_field_refs`, `output_schema_field_count`,
`validator_registration_ref`, `validator_registration_field_refs`,
`validator_registration_field_count`, `validation_evidence_contract_ref`,
`validation_evidence_field_refs`, `validation_evidence_field_count`,
`validation_record_contract_ref`, `validation_record_store_ref`,
`validation_record_writer_ref`, `validation_record_replay_guard_ref`,
`validation_record_field_refs`, `validation_record_field_count`,
`validation_record_schema_ref`, `validation_record_append_only_log_ref`,
`validation_record_replay_guard_contract_ref`,
`validation_record_idempotency_contract_ref`,
`validation_record_replay_window_ref`,
`validation_record_duplicate_policy_ref`,
`validation_record_schema_field_refs`,
`validation_record_schema_field_count`,
`validation_record_replay_guard_field_refs`,
`validation_record_replay_guard_field_count`,
`semantic_artifact_definition_review_output_acceptance_ref`,
`semantic_artifact_definition_review_output_acceptance_contract_ref`,
`semantic_artifact_runtime_evidence_ref`,
`semantic_artifact_runtime_evidence_contract_ref`,
`reconciliation_semantics_ref`, `reconciliation_semantics_contract_ref`,
reconciliation_identity_bound=false,
reconciliation_position_key_bound=false, reconciliation_plan_bound=false,
reconciliation_reason_bound=false, post_exchange_reconciliation_bound=false,
reconciliation_audit_bound=false,
runtime_reconciliation_evidence_observed=false,
runtime_evidence_satisfies_reconciliation_semantics=false, and
validation_record_reconciliation_semantics_ready=false.

Completed execution-eligibility semantic closure refs are authoritative
display-only evidence:
`validation_record_execution_eligibility_contract_ref`,
`validation_record_position_semantics_ref`,
`validation_record_margin_semantics_ref`,
`validation_record_collateral_semantics_ref`,
`validation_record_liquidation_semantics_ref`,
`validation_record_reduce_only_semantics_ref`,
`validation_record_close_only_semantics_ref`,
`validation_record_funding_semantics_ref`,
`validation_record_order_semantics_ref`,
`validation_record_cancel_semantics_ref`,
`validation_record_reconciliation_semantics_ref`,
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
`validation_record_execution_eligibility_field_refs`,
`validation_record_semantic_contracts_present=true`,
`validation_record_semantic_contracts_ready=false`,
`semantic_contract_ref`, `semantic_contract_present=true`,
`semantic_contract_ready=false`,
runtime_evidence_satisfies_validation_record_execution_eligibility=false, and
validation_record_execution_eligibility_contract_ready=false. Present
semantic contract rows are not validators, not runtime-accepted contracts, and
not command execution authority.

False flags remain validation_gate_ready=false,
validation_gate_passed=false, output_schema_registered=false,
validator_registration_ready=false,
runtime_evidence_satisfies_validator_registration=false,
runtime_evidence_satisfies_validation_evidence=false,
validation_evidence_ready=false, validation_evidence_recorded=false,
validation_record_contract_ready=false, validation_record_store_ready=false,
validation_record_writer_enabled=false,
validation_record_replay_guard_ready=false,
runtime_evidence_satisfies_validation_record_schema=false,
runtime_evidence_satisfies_validation_record_replay_guard=false,
validation_record_schema_ready=false, validation_record_schema_registered=false,
validation_record_replay_guard_contract_ready=false,
validation_record_idempotency_contract_ready=false,
validation_record_replay_protected=false,
append_only_validation_record=false,
validation_record_idempotency_bound=false, and request_payload_validated=false.

Current route adapters:
- `POST /api/v1/orders`
- `GET /api/v1/orders`
- `GET /api/v1/orders/{client_order_id}`
- `GET /api/v1/stealth/orders`
- `GET /api/v1/stealth/orders/{stealth_order_id}`
- `GET /api/v1/stealth/command-suite`
- `GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof`
- `GET /api/v1/stealth/orders/{stealth_order_id}/lifecycle-write-guard-proof`
- `GET /api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proof`
- `GET /api/v1/stealth/orders/{stealth_order_id}/manager-invocation-policy`
- `GET /api/v1/stealth/orders/{stealth_order_id}/coinbase-exchange-submission-policy`
- `GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy`
- `GET /api/v1/stealth/orders/{stealth_order_id}/recovery-proof`
- `GET /api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proof`
- `GET /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proof`
- `GET /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof`
- `GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proof`
- `POST /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-snapshots`
- `POST /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proofs`
- `POST /api/v1/stealth/orders/{stealth_order_id}/lifecycle-write-guard-proofs`
- `POST /api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proofs`
- `POST /api/v1/stealth/orders/{stealth_order_id}/manager-invocation-policy-proofs`
- `POST /api/v1/stealth/orders/{stealth_order_id}/coinbase-exchange-submission-policy-proofs`
- `POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy-proofs`
- `POST /api/v1/stealth/orders/{stealth_order_id}/recovery-proofs`
- `POST /api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proofs`
- `POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proofs`
- `POST /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proofs`
- `POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proofs`
- `GET /api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals`
- `POST /api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals`
- `GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications`
- `POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications`
- `POST /api/v1/stealth/orders`
- `POST /api/v1/stealth/orders/{stealth_order_id}/reveal`
- `POST /api/v1/stealth/orders/{stealth_order_id}/move`
- `POST /api/v1/stealth/orders/{stealth_order_id}/cancel`
- `POST /api/v1/stealth/orders/{stealth_order_id}/recovery`
- `POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation`
- `GET /api/v1/movement-repricing/evidence`
- `GET /api/v1/movement-repricing/orders/{client_order_id}`
- `GET /api/v1/movement-repricing/stealth/{stealth_order_id}`
- `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice`
- `GET /api/v1/futures/command-suite`
- `GET /api/v1/futures/account`
- `GET /api/v1/futures/positions`
- `GET /api/v1/futures/positions/{position_key}`
- `POST /api/v1/orders/{client_order_id}/cancel`
- `POST /api/v1/spot/campaign/executions`
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
- `GET /api/v1/spot/readiness`
- `GET /api/v1/spot/sweep/status`
- `GET /api/v1/spot/sweep/pnl`
- `GET /api/v1/spot/cost-basis/status`
- `GET /api/v1/spot/campaign/status`
- `GET /api/v1/spot/direct-orders/{client_order_id}/audit`

Current behavior:
- mutating HTTP routes authenticate, authorize, evaluate idempotency, write
  command audit records, then return HTTP `501` with `status:
  "not_implemented"`
- mutating HTTP routes do not submit orders, cancel orders, call Coinbase, or
  mutate live exchange state
- the generated OpenAPI contract includes eventual `200` accepted/replayed
  command response schemas, but the current runtime still returns `501` for
  create, order cancel, stealth create, stealth reveal, stealth move,
  stealth cancel, movement reprice, and campaign execution commands because HTTP live
  execution is not approved
- `X-Operator-Intent` is durable command audit evidence and part of the
  idempotency payload hash
- `GET /api/v1/orders` and `GET /api/v1/orders/{client_order_id}` expose
  read-only local order evidence keyed by `client_order_id`; exchange-native
  ids can appear only as `exchange_order_id` evidence and are not cancel keys
- `GET /api/v1/stealth/orders` and
  `GET /api/v1/stealth/orders/{stealth_order_id}` expose read-only local
  stealth lifecycle evidence keyed by `stealth_order_id`; active placement
  client ids and exchange ids are evidence only
- `GET /api/v1/stealth/command-suite` exposes read-only M55 stealth
  command-suite readiness for create, cancel, reveal, move, reprice,
  recovery, and reconciliation workflows. It links live-disabled stealth
  create, reveal, move, cancel, recovery, reconciliation, and movement/reprice routes, reports
  exchange-truth blockers, and does not create, reveal, cancel, move/reprice,
  reconcile, mutate state, read Coinbase, or call Coinbase.
  `execution_live_readiness` also includes forbidden execution claim evidence
  and summary rows mapping each forbidden claim to the backend decision,
  clearance/work-queue refs, backend contract evidence, and disabled
  claim-cleared/resolver/writer/execution flags that keep it blocked.
  Exact command contracts also expose
  `live_execution_adapter_contract.construction_contract.acceptance_evidence_producer_clearance_dependency_summary`
  when backend construction evidence is present. That summary is blocked
  aggregate evidence over producer-readiness clearance action rows. It does
  not clear readiness, write or accept evidence, satisfy producer contracts,
  construct adapters, invoke managers, call Coinbase, mutate state, or grant
  browser/BFF execution authority.
  The same construction contract may expose
  `acceptance_evidence_producer_clearance_work_items` and
  `acceptance_evidence_producer_clearance_work_queue_summary` as backend-
  derived queue evidence over each producer contract's first blocked
  clearance action. It may also expose
  `acceptance_evidence_producer_clearance_claim_traces` and
  `acceptance_evidence_producer_clearance_claim_trace_summary` mapping the
  forbidden `producer_route_contract_available` claim back to each blocked
  work item. These fields do not resolve claims, clear work items, write or
  accept evidence, satisfy producer contracts, construct adapters, invoke
  managers, call Coinbase, mutate state, or grant browser/BFF execution
  authority.
  The same construction contract may expose
  `acceptance_evidence_producer_route_requirements` and
  `acceptance_evidence_producer_route_requirement_summary` as backend-derived
  route requirement evidence over those unresolved claim traces. These fields
  name the missing route contract refs, route requirement ids, claim ids, work
  item refs, gates, blockers, and disabled authority flags. They do not
  register routes, bind route inventory, bind a shared command service, resolve
  claims, clear work items, write or accept evidence, satisfy producer
  contracts, construct adapters, invoke managers, call Coinbase, mutate state,
  or grant browser/BFF execution authority.
  The same construction contract may expose
  `acceptance_evidence_producer_route_contract_proposals` and
  `acceptance_evidence_producer_route_contract_proposal_summary` as backend-
  derived proposal evidence over those unresolved route requirements. These
  fields name the missing route contract refs, route inventory refs, shared
  command-service refs, proposal ids, requirement ids, claim ids, gates,
  blockers, and disabled authority flags. They do not register routes, bind
  route inventory, bind shared command services, resolve requirements or
  claims, clear work items, write or accept evidence, satisfy producer
  contracts, construct adapters, invoke managers, call Coinbase, mutate state,
  or grant browser/BFF execution authority.
  The same construction contract may expose
  `acceptance_evidence_producer_route_contract_validation_items` and
  `acceptance_evidence_producer_route_contract_validation_summary` as backend-
  derived validation evidence over those unresolved route-contract proposals.
  These fields name validation ids, check keys, blockers, route contract ids,
  route inventory refs, shared command-service refs, false observed state,
  false pass state, and disabled handler/store/validation/replay/writer/
  acceptance/construction/execution authority. They do not register routes,
  bind route inventory, bind shared command services, register handlers,
  resolve requirements or claims, clear work items, write or accept evidence,
  satisfy producer contracts, construct adapters, invoke managers, call
  Coinbase, mutate state, or grant browser/BFF execution authority.
  The same construction contract may expose
  `acceptance_evidence_producer_route_contract_remediation_items` and
  `acceptance_evidence_producer_route_contract_remediation_summary` as
  backend-derived remediation evidence over failed validation rows. These
  fields name remediation ids, validation ids, remediation actions, validation
  blockers, check keys, route contract ids, false readiness, and disabled
  route/store/validation/replay/writer/acceptance/construction/execution
  authority. They do not perform remediation, register routes, bind route
  inventory, bind shared command services, register handlers, resolve
  requirements or claims, clear work items, write or accept evidence, satisfy
  producer contracts, construct adapters, invoke managers, call Coinbase,
  mutate state, or grant browser/BFF execution authority.
  The same construction contract may expose
  `acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_items`
  and
  `acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_summary`
  as backend-derived remediation evidence over failed review-input store
  record-validation rows. These fields name remediation ids, record
  validation ids, record contract ids, missing backend work, work refs,
  validation gates, replay gates, remediation gates, validation blockers,
  false remediation readiness, false remediation execution, and disabled
  record/store/review/step/claim/acceptance/construction/execution
  authority. They do not perform remediation, create validators, bind
  idempotency, validate payloads, protect replay, create or accept records,
  validate records, complete inputs or reviews, make steps ready, resolve
  claims, clear work items, write or accept evidence, satisfy producer
  contracts, construct adapters, invoke managers, call Coinbase, mutate
  state, or grant browser/BFF execution authority.
  The same construction contract may expose
  `acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_dependencies`
  and
  `acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_dependency_summary`
  as backend-derived dependency evidence over blocked review-input store
  record-validation remediation rows. These fields name dependency ids,
  remediation ids, record validation ids, immediate predecessor/successor
  remediation ids, immediate predecessor/successor record-validation ids,
  dependency blockers, edge counts, missing backend work, gates, false
  dependency readiness, false remediation execution, false validation
  readiness, and disabled record/store/review/step/claim/acceptance/
  construction/execution authority. The dependency rows intentionally carry
  immediate-neighbor links only, not an all-pairs graph. They do not resolve
  dependencies, perform remediation, create validators, bind idempotency,
  validate payloads, protect replay, create or accept records, validate records, complete inputs or
  reviews, make steps ready, resolve claims, clear work items, write or accept
  evidence, satisfy producer contracts, construct adapters, invoke managers,
  call Coinbase, mutate state, or grant browser/BFF execution authority.
- `GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof`
  exposes read-only persisted active-placement exchange-truth evidence keyed
  by `stealth_order_id`; it does not read Coinbase, verify exchange truth,
  cancel/replace placements, execute reconciliation, or mutate lifecycle state
- `POST /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-snapshots`
  and
  `POST /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proofs`
  persist append-only local evidence after backend admission prerequisites
  match. The path `stealth_order_id` is the command identity; placement client
  ids and exchange ids are evidence only. The routes do not read Coinbase,
  submit or cancel orders, cancel/replace active placements, verify exchange
  truth, execute reconciliation, or mutate order/exchange/lifecycle state
- `GET /api/v1/stealth/orders/{stealth_order_id}/coinbase-exchange-submission-policy`
  exposes read-only persisted Coinbase exchange submission-policy proof
  evidence keyed by `stealth_order_id`. It is readback only and does not
  submit, cancel, or read Coinbase orders, invoke managers, execute
  reconciliation, cancel/replace active placements, mutate
  order/exchange/lifecycle state, or satisfy live execution prerequisites.
- `POST /api/v1/stealth/orders/{stealth_order_id}/coinbase-exchange-submission-policy-proofs`
  persists append-only local proof evidence for guarded stealth create,
  reveal, cancel, move, recovery, reconciliation, and movement/reprice command
  contexts after backend admission prerequisites match. The path
  `stealth_order_id` is the command identity; `client_order_id`,
  active-placement ids, exchange ids, and Coinbase order ids remain evidence
  only. The route does not submit, cancel, or read Coinbase orders, does not
  invoke `StealthOrderManager`, does not execute reconciliation, does not
  cancel/replace active placements, does not mutate
  order/exchange/lifecycle state, and does not make the command
  live-executable.
- `GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy`
  exposes read-only persisted post-write reconciliation execution-policy proof
  evidence keyed by `stealth_order_id`. It is readback only and does not
  execute reconciliation, invoke managers, call Coinbase, submit/cancel/read
  Coinbase orders, cancel/replace active placements, mutate
  order/exchange/lifecycle state, or satisfy live execution prerequisites.
- `POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy-proofs`
  persists append-only local proof evidence for guarded stealth create,
  reveal, cancel, move, recovery, reconciliation, and movement/reprice command
  contexts after backend admission prerequisites match. The path
  `stealth_order_id` is the command identity; `client_order_id`,
  active-placement ids, exchange ids, and Coinbase order ids remain evidence
  only. The route does not execute reconciliation, submit/cancel/read
  Coinbase orders, invoke `StealthOrderManager`, cancel/replace active
  placements, mutate order/exchange/lifecycle state, or make the command
  live-executable.
- `GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proof`
  exposes read-only persisted post-write reconciliation proof evidence keyed
  by `stealth_order_id`. It is readback only and does not execute
  reconciliation, invoke managers, call Coinbase, cancel/replace active
  placements, mutate order/exchange/lifecycle state, or satisfy live
  execution prerequisites.
- `POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proofs`
  persists append-only local proof evidence for guarded stealth create,
  reveal, cancel, move, recovery, reconciliation, and movement/reprice command
  contexts after backend admission prerequisites match. The path
  `stealth_order_id` is the command identity; `client_order_id`,
  active-placement ids, and exchange ids remain evidence only. The route does
  not accept execution journals as complete, does not call Coinbase, does not
  invoke `StealthOrderManager`, does not execute reconciliation, does not
  cancel/replace placements, does not mutate order/exchange/lifecycle state,
  and does not make the command live-executable.
- `GET /api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals`
  exposes read-only persisted post-write execution-journal acceptance evidence
  keyed by `stealth_order_id`. It is readback only and does not execute or
  verify reconciliation, invoke managers, call Coinbase, cancel/replace active
  placements, mutate order/exchange/lifecycle state, or satisfy live execution
  prerequisites.
- `POST /api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals`
  persists append-only local execution-journal acceptance evidence only when
  it matches a safe post-write reconciliation proof and exact guarded command
  context. The path `stealth_order_id` is the command identity. The route does
  not execute or verify reconciliation, call Coinbase, invoke
  `StealthOrderManager`, cancel/replace placements, mutate
  order/exchange/lifecycle state, or make the command live-executable.
- `GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications`
  exposes read-only persisted post-write reconciliation verification evidence
  keyed by `stealth_order_id`. It lists persisted records but counts
  verification as verified only for an exact safe proof plus accepted journal
  chain. It is readback only and does not execute reconciliation, call
  Coinbase, invoke managers, mutate state, or satisfy live execution service
  or adapter prerequisites.
- `POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications`
  persists append-only local verification evidence only when it matches a safe
  post-write reconciliation proof and accepted execution journal for the exact
  guarded command context. It may participate in resolving only the
  `post_write_reconciliation` prerequisite evidence as part of the exact safe
  proof, accepted journal, and verification chain. The route does not execute
  reconciliation, call Coinbase, invoke `StealthOrderManager`, cancel/replace
  placements, mutate order/exchange/lifecycle state, or make the command
  live-executable.
- Exact stealth create and non-create command responses may expose
  `remaining_execution_blocker_count` and `remaining_execution_blockers`.
  Those typed rows stay blocked after prerequisite lookup and keep live
  service, live adapter, manager invocation, Coinbase submit/cancel/read,
  active-placement cancel/replace, reconciliation execution, and state
  mutation disabled. A resolved exact post-write chain removes only the
  `post_write_reconciliation_missing` blocker.
- Exact stealth create and non-create command responses may expose
  `execution_candidate` and `execution_preflight`. `execution_candidate`
  names the future backend manager path and unresolved blocker chain as
  blocked planning evidence. `execution_preflight` is derived from that
  candidate and reports blocked checks for candidate readiness, remaining
  blockers, live service, live adapter, manager invocation, Coinbase exchange
  actions, post-write reconciliation, state mutation, and browser/BFF
  authority. These fields are read-only evidence only: they do not construct
  an executable adapter, invoke `StealthOrderManager`, call Coinbase,
  cancel/replace active placements, execute reconciliation, mutate
  lifecycle/order/exchange state, approve browser actions, or grant BFF
  execution authority.
- Exact stealth create and non-create command responses may expose
  `execution_live_readiness.backend_decisions[].resolution_readiness_items`.
  These rows expand decision-resolution plan steps, dependency refs, and
  verification gates into structured blocked planning evidence with source,
  order, missing reason, and backend planning authority. Every item remains
  required, unresolved, no-live, backend-owned, route-bound,
  command-context-bound, browser `display_only`, BFF
  `forward_only_no_execution`, `execution_allowed=false`, and
  `executed=false`. The rows are not a resolver, writer, plan executor,
  manager invocation path, Coinbase submit/cancel/read path, reconciliation
  executor, state mutation path, browser authority, or BFF execution
  authority.
- The same backend decision rows expose
  `execution_live_readiness.backend_decisions[].resolution_readiness_summary`.
  This is a backend-derived aggregate over the readiness items with item
  counts, type counts, first-blocking item, missing reasons, summary
  authority, and disabled execution/resolver/writer flags. It is not a
  resolver, writer, plan executor, Coinbase path, reconciliation executor,
  browser evaluator, or BFF execution authority.
- The same backend decision rows expose
  `execution_live_readiness.backend_decisions[].resolution_handoff`. This is
  backend-derived classification evidence over the readiness summary. It
  reports clearance categories, blocked clearance refs, first-clearance
  evidence, handoff authority, and disabled resolution/execution/writer flags.
  Its `clearance_actions` rows name the source readiness item type/order,
  clearance sequence, predecessor refs, successor refs, backend contract,
  route, method, service, required artifact, evidence ref, dependency
  authority, dependency readiness, action authority, and disabled
  execution/resolver/writer flags for each blocked handoff ref. These rows are not a resolver, decision
  writer, live service switch, live adapter, manager invocation path, Coinbase
  path, reconciliation executor, state mutation path, browser authority, or
  BFF execution authority.
  `clearance_dependency_summary` aggregates those rows with blocked/ready
  counts, predecessor/successor edge counts, dependency-blocked refs,
  clearable refs, terminal refs, and disabled graph readiness, clearance,
  resolver, writer, and execution flags. It is also display-only backend
  evidence and must not be
  treated as resolution authority.
  `backend_decision_resolution_summary` aggregates the full backend decision
  ledger with blocked decision counts, owners, required artifacts, missing
  reasons, first blocker, clearance action totals, and disabled
  resolver/writer/completion/execution authority. It is display-only backend
  evidence and must not be treated as a resolver, writer, live switch,
  Coinbase path, reconciliation executor, browser authority, or BFF execution
  path.
  `backend_decision_resolution_work_items` and
  `backend_decision_resolution_work_queue_summary` expose the first blocked
  clearance action for each unresolved backend decision as a cross-decision
  work queue with owner, artifact, contract, route, method, service, evidence
  ref, dependency state, and disabled resolver/writer/execution authority.
  They are display-only backend evidence and must not be treated as a
  resolver, writer, live switch, Coinbase path, reconciliation executor,
  browser authority, or BFF execution path.
  Live-adapter construction evidence also exposes
  `acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_dependency_work_items`
  and
  `acceptance_evidence_producer_route_contract_clearance_step_review_input_store_record_validation_remediation_dependency_work_queue_summary`
  as display-only work-queue readback over blocked record-validation
  remediation dependency rows. They may name missing backend work and refs but
  must not perform remediation, accept records, resolve claims, construct
  adapters, call Coinbase, or grant browser/BFF execution authority.
- `POST /api/v1/stealth/orders/{stealth_order_id}/move` is a live-disabled
  cancel/replace-shaped command draft keyed by `stealth_order_id`; it returns
  `501`, writes command audit evidence, never calls `build_stealth_move_plan`
  or `execute_stealth_move`, never calls Coinbase, and must not use active
  placement ids or exchange ids as command keys
- `POST /api/v1/stealth/orders/{stealth_order_id}/cancel` is a
  live-disabled command draft keyed by `stealth_order_id`; it returns `501`,
  writes command audit evidence, never calls Coinbase, and must not use active
  placement ids or exchange ids as cancel keys
- `POST /api/v1/stealth/orders/{stealth_order_id}/recovery` and
  `POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation` are
  live-disabled local-state command contracts keyed by `stealth_order_id`.
  They return fail-closed command evidence and do not execute recovery,
  reconciliation, proof writers, Coinbase reads, Coinbase orders,
  `StealthOrderManager` mutations, local lifecycle mutations, or
  exchange-state mutations
- `GET /api/v1/movement-repricing/evidence`,
  `GET /api/v1/movement-repricing/orders/{client_order_id}`, and
  `GET /api/v1/movement-repricing/stealth/{stealth_order_id}` expose
  read-only movement/repricing evidence from `order_moves`,
  `stealth_order_moves`, `stealth_orders.anchor_repricing_state_json`, and
  runtime claim snapshots when safely observable
- `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice` is a
  live-disabled command draft keyed by `stealth_order_id`; it returns `501`,
  writes command audit evidence, never calls Coinbase, and does not clear
  cooldowns or invoke the live dashboard repricer
- `GET /api/v1/futures/command-suite` exposes read-only futures/perpetual
  command readiness evidence for placement, close/reduce, cancel, and
  reconciliation. Completed M57 `6281-6300` evidence reports
  `service_method="reconcile_futures_position"` for `futures_reconcile` while
  preserving
  `application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan`
  as the separate required reconciliation-plan contract. Completed M57
  `6301-6320` evidence reports futures proof route/writer contract registry
  evidence through `FUTURES_PROOF_ROUTE_CONTRACTS` and
  `FUTURES_PROOF_WRITER_CONTRACTS`, including
  `application/admin_api/futures_proof_routes.py::post_futures_place_margin_collateral_proof`
  and
  `application/admin_api/futures_proof_writer.py::write_futures_place_margin_collateral_proof`.
  The command-suite response keeps `registered_proof_route_count=0` and
  `enabled_proof_writer_count=0`. These rows do not register futures command
  routes, register proof routes, create proof writers, accept proof records,
  make route-bound command drafts executable, call Coinbase, execute
  reconciliation, mutate futures/order/exchange state, or grant browser, BFF,
  or spot-rule authority
  Completed M57 `6321-6340` evidence reports futures proof payload-field
  contract registry evidence through `FUTURES_PROOF_PAYLOAD_FIELD_CONTRACTS`
  and `iter_futures_proof_payload_field_contracts`, including
  `proof_payload.command`, `proof_payload.validation.status`, and
  `futures_place_margin_collateral_payload_command_validated`. The
  command-suite response keeps `payload_field_present=false` and
  `validation_registered=false`. These rows do not validate submitted proof
  payloads, register validators, accept proof records, create proof writers,
  make route-bound command drafts executable, call Coinbase, execute
  reconciliation, mutate futures/order/exchange state, or grant browser, BFF,
  or spot-rule authority
  Completed M57 `6341-6360` evidence reports futures route-bound command draft
  evidence for `POST /api/v1/futures/orders`,
  `POST /api/v1/futures/positions/{position_key}/close-reduce`,
  `POST /api/v1/futures/orders/{client_order_id}/cancel`, and
  `POST /api/v1/futures/positions/{position_key}/reconciliation`. The
  command-suite response keeps route/draft flags true while execution remains
  false. Cancel route evidence uses `client_order_id`. These drafts do not bind
  live adapters, submit or cancel Coinbase orders, acknowledge exchange orders,
  execute reconciliation, mutate futures/order/exchange state, accept proof
  records as readiness, or grant browser/BFF authority.
  Completed M57 `6361-6380` evidence reports futures request payload contract
  registry evidence through `FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS` and
  `iter_futures_request_payload_contracts`. The command-suite response keeps
  `request_field_count=22`, `blocking_request_field_count=22`, and
  route/draft flags true while execution remains false; request-field
  `required_backend_contracts` include refs such as
  `application/admin_api/futures_request_payload_contracts.py::futures_cancel_client_order_id_request_payload_contract`.
  Completed M57 `6381-6400` evidence adds disabled `validation_gate_ref`,
  `validation_evidence_ref`, `validator_contract_ref`,
  `validator_registration_ref`, validation_gate_ready=false,
  validation_gate_passed=false, and request_payload_validated=false to those
  request-field rows. Completed M57 `6401-6420` evidence adds disabled futures
  request payload validator contract registry evidence through
  `application/admin_api/futures_request_payload_validators.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS`, and
  `iter_futures_request_payload_validator_contracts`. The command-suite
  response exposes `request_payload_validator_contract_count`,
  `blocking_request_payload_validator_contract_count`,
  `request_payload_validator_contracts`, `validator_input_schema_ref`,
  `validator_output_schema_ref`, validator_input_schema_registered=false, and
  validator_output_schema_registered=false. These rows do not validate command
  request payloads, register payload validators, bind live adapters, submit or
  cancel Coinbase orders, execute reconciliation, mutate futures/order/exchange
  state, or grant browser, BFF, or spot-rule authority.
  Completed M57 `6421-6440` evidence adds disabled futures request payload
  validator input-schema evidence through
  `application/admin_api/futures_request_payload_validator_input_schemas.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS`, and
  `iter_futures_request_payload_validator_input_schemas`. The command-suite
  response exposes `request_payload_validator_input_schema_count`,
  `blocking_request_payload_validator_input_schema_count`,
  `ready_request_payload_validator_input_schema_count`,
  `registered_request_payload_validator_input_schema_count`,
  `request_payload_validator_input_schemas`, `input_schema_field_refs`,
  `input_schema_field_count`, and input_schema_registered=false. These rows do
  not validate command request payloads, register payload validators, bind live
  adapters, submit or cancel Coinbase orders, execute reconciliation, mutate
  futures/order/exchange state, or grant browser, BFF, or spot-rule authority.
  Completed M57 `6441-6460` evidence adds disabled futures request payload
  validator output-schema evidence through
  `application/admin_api/futures_request_payload_validator_output_schemas.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS`, and
  `iter_futures_request_payload_validator_output_schemas`. The command-suite
  response exposes `request_payload_validator_output_schema_count`,
  `blocking_request_payload_validator_output_schema_count`,
  `ready_request_payload_validator_output_schema_count`,
  `registered_request_payload_validator_output_schema_count`,
  `request_payload_validator_output_schemas`, `output_schema_field_refs`,
  `output_schema_field_count`, and output_schema_registered=false.
  Completed M57 `6461-6480` evidence adds disabled futures request payload
  validator registration evidence through
  `application/admin_api/futures_request_payload_validator_registrations.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS`, and
  `iter_futures_request_payload_validator_registrations`. The command-suite
  response exposes `request_payload_validator_registration_count`,
  `blocking_request_payload_validator_registration_count`,
  `request_payload_validator_registrations`,
  `validator_registration_field_refs`,
  `validator_registration_field_count`,
  validator_registration_ready=false, and
  runtime_evidence_satisfies_validator_registration=false.
  Completed M57 `6481-6500` evidence adds disabled futures request payload
  validation evidence through
  `application/admin_api/futures_request_payload_validation_evidence.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS`, and
  `iter_futures_request_payload_validation_evidence`. The command-suite
  response exposes `request_payload_validation_evidence_count`,
  `blocking_request_payload_validation_evidence_count`,
  `ready_request_payload_validation_evidence_count`,
  `recorded_request_payload_validation_evidence_count`,
  `runtime_observed_request_payload_validation_evidence_count`,
  `request_payload_validation_evidence`, `validation_evidence_contract_ref`,
  `validation_evidence_field_refs`, `validation_evidence_field_count`,
  runtime_evidence_satisfies_validation_evidence=false,
  validation_evidence_ready=false, and validation_evidence_recorded=false.
  Completed M57 `6501-6520` evidence adds disabled futures request payload
  validation evidence record contract evidence through
  `application/admin_api/futures_request_payload_validation_evidence_records.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS`, and
  `iter_futures_request_payload_validation_evidence_records`. The command-suite
  response exposes `request_payload_validation_evidence_record_count`,
  `blocking_request_payload_validation_evidence_record_count`,
  `ready_request_payload_validation_evidence_record_count`,
  `stored_request_payload_validation_evidence_record_count`,
  `runtime_observed_request_payload_validation_evidence_record_count`,
  `request_payload_validation_evidence_records`,
  `validation_record_contract_ref`, `validation_record_store_ref`,
  `validation_record_writer_ref`, `validation_record_replay_guard_ref`,
  `validation_record_field_refs`, `validation_record_field_count`,
  validation_record_contract_ready=false,
  validation_record_store_ready=false,
  validation_record_writer_enabled=false,
  validation_record_replay_guard_ready=false,
  validation_recorded=false, append_only_validation_record=false, and
  validation_record_idempotency_bound=false.
  Completed M57 `6521-6540` evidence added disabled futures request payload
  validation record schema and append-only log evidence through
  `application/admin_api/futures_request_payload_validation_record_schemas.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS`, and
  `iter_futures_request_payload_validation_record_schemas`. The command-suite
  response exposes `request_payload_validation_record_schema_count`,
  `blocking_request_payload_validation_record_schema_count`,
  `ready_request_payload_validation_record_schema_count`,
  `registered_request_payload_validation_record_schema_count`,
  `runtime_observed_request_payload_validation_record_schema_count`,
  `request_payload_validation_record_schemas`,
  `validation_record_schema_ref`,
  `validation_record_append_only_log_ref`,
  `validation_record_schema_field_refs`,
  `validation_record_schema_field_count`,
  runtime_evidence_satisfies_validation_record_schema=false,
  validation_record_schema_ready=false,
  validation_record_schema_registered=false, and
  validation_record_append_only_log_ready=false.
- Completed M57 `6541-6560` evidence added disabled futures request payload
  validation record replay guard evidence through
  `application/admin_api/futures_request_payload_validation_record_replay_guards.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS`, and
  `iter_futures_request_payload_validation_record_replay_guards`. The
  command-suite response exposes
  `request_payload_validation_record_replay_guard_count`,
  `blocking_request_payload_validation_record_replay_guard_count`,
  `ready_request_payload_validation_record_replay_guard_count`,
  `idempotency_bound_request_payload_validation_record_count`,
  `runtime_observed_request_payload_validation_record_replay_guard_count`,
  `request_payload_validation_record_replay_guards`,
  `validation_record_replay_guard_contract_ref`,
  `validation_record_idempotency_contract_ref`,
  `validation_record_replay_window_ref`,
  `validation_record_duplicate_policy_ref`,
  `validation_record_replay_guard_field_refs`,
  `validation_record_replay_guard_field_count`,
  runtime_evidence_satisfies_validation_record_replay_guard=false,
  validation_record_replay_guard_contract_ready=false,
  validation_record_idempotency_contract_ready=false, and
  validation_record_replay_protected=false.
- Completed M57 `6781-6800` evidence carries forward disabled futures request payload
  validation record semantic artifact runtime evidence acceptance through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances`.
  The command-suite response exposes
  `request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count`,
  `blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count`,
  `ready_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count`,
  `runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count`,
  `request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances`,
  `semantic_artifact_runtime_evidence_acceptance_ref`,
  `semantic_artifact_runtime_evidence_acceptance_contract_ref`,
  semantic_artifact_runtime_evidence_acceptance_available=false, and
  semantic_artifact_runtime_evidence_acceptance_accepted=false.
  Completed `6761-6780` evidence carries forward disabled futures request
  payload validation record semantic artifact runtime evidence binding through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_runtime_evidences.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidences`.
  The carried-forward response exposes
  `request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
  `blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
  `ready_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
  `runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
  `request_payload_validation_record_semantic_artifact_runtime_evidences`,
  `semantic_artifact_runtime_evidence_ref`,
  `semantic_artifact_runtime_evidence_contract_ref`,
  semantic_artifact_runtime_evidence_available=false,
  semantic_artifact_runtime_evidence_bound=false, and
  semantic_artifact_runtime_evidence_accepted=false.
  Completed `6741-6760` evidence carries forward disabled futures request
  payload validation record semantic artifact definition review output
  acceptance evidence through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_definition_review_output_acceptances.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_ACCEPTANCE_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_semantic_artifact_definition_review_output_acceptances`.
  The carried-forward response exposes
  `request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
  `blocking_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
  `ready_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
  `runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
  `request_payload_validation_record_semantic_artifact_definition_review_output_acceptances`,
  `semantic_artifact_definition_review_output_acceptance_ref`,
  `semantic_artifact_definition_review_output_acceptance_contract_ref`,
  `semantic_artifact_definition_review_output_ref`,
  `semantic_artifact_definition_review_output_contract_ref`,
  `semantic_artifact_definition_review_ref`,
  `semantic_artifact_definition_review_contract_ref`,
  `semantic_artifact_definition_ref`,
  `semantic_artifact_definition_contract_ref`,
  contextless_review_required=true,
  semantic_artifact_definition_review_output_acceptance_available=false, and
  semantic_artifact_definition_review_output_acceptance_accepted=false.
  Completed `6721-6740` evidence carries forward disabled futures request
  payload validation record semantic artifact definition review output
  evidence through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_definition_review_outputs.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_semantic_artifact_definition_review_outputs`.
  The carried-forward response exposes
  `request_payload_validation_record_semantic_artifact_definition_review_output_count`,
  `blocking_request_payload_validation_record_semantic_artifact_definition_review_output_count`,
  `ready_request_payload_validation_record_semantic_artifact_definition_review_output_count`,
  `runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_count`,
  and
  `request_payload_validation_record_semantic_artifact_definition_review_outputs`.
  The older execution-eligibility and admission-link rows remain present as
  backend-owned blockers through
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS`,
  `iter_futures_request_payload_validation_record_execution_eligibilities`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ADMISSION_LINK_CONTRACTS`, and
  `iter_futures_request_payload_validation_record_admission_links`. These
  rows preserve validation_record_execution_eligible=false,
  validation_record_admitted=false,
  validation_record_admission_link_contract_ready=false,
  validation_record_admission_link_ready=false,
  validation_record_approval_snapshot_bound=false,
  validation_record_cap_guard_decision_bound=false,
  validation_record_reconciliation_plan_bound=false,
  validation_record_live_intent_bound=false,
  validation_record_command_admission_bound=false, and
  validation_record_admitted=false. Completed `6561-6580` audit-link evidence
  remains available through
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_AUDIT_LINK_CONTRACTS`.
- Machine-check evidence: futures request payload contract registry evidence.
- Machine-check evidence: futures request payload validation gate evidence.
- Machine-check evidence: futures request payload validator contract registry evidence.
- Machine-check evidence: futures request payload validator input-schema evidence.
- Machine-check evidence: futures request payload validator output-schema evidence.
- Machine-check evidence: futures request payload validator registration evidence.
- Machine-check evidence: futures request payload validation evidence.
- Machine-check evidence: futures request payload validation record execution-eligibility evidence.
- Machine-check evidence:
  `application/admin_api/futures_request_payload_contracts.py`.
- Machine-check evidence:
  `application/admin_api/futures_request_payload_validators.py`.
- Machine-check evidence:
  `application/admin_api/futures_request_payload_validator_input_schemas.py`.
- Machine-check evidence: `FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS`.
- Machine-check evidence: `iter_futures_request_payload_contracts`.
- Machine-check evidence: `FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS`.
- Machine-check evidence:
  `iter_futures_request_payload_validator_contracts`.
- Machine-check evidence: `FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS`.
- Machine-check evidence:
  `iter_futures_request_payload_validator_input_schemas`.
- Machine-check evidence: `FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS`.
- Machine-check evidence:
  `iter_futures_request_payload_validator_output_schemas`.
- Machine-check evidence: `FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS`.
- Machine-check evidence:
  `iter_futures_request_payload_validator_registrations`.
- Machine-check evidence: request_field_count.
- Machine-check evidence: blocking_request_field_count.
- Machine-check evidence: `request_payload_validator_contract_count`.
- Machine-check evidence: `blocking_request_payload_validator_contract_count`.
- Machine-check evidence: `request_payload_validator_input_schema_count`.
- Machine-check evidence: `blocking_request_payload_validator_input_schema_count`.
- Machine-check evidence: `request_payload_validator_output_schema_count`.
- Machine-check evidence: `blocking_request_payload_validator_output_schema_count`.
- Machine-check evidence: `request_payload_validator_registration_count`.
- Machine-check evidence: `blocking_request_payload_validator_registration_count`.
- Machine-check evidence: `validation_gate_ref`.
- Machine-check evidence: `validation_evidence_ref`.
- Machine-check evidence: `validator_contract_ref`.
- Machine-check evidence: `validator_input_schema_ref`.
- Machine-check evidence: `validator_output_schema_ref`.
- Machine-check evidence: `validator_registration_ref`.
- Machine-check evidence: validator_input_schema_registered=false.
- Machine-check evidence: validator_output_schema_registered=false.
- Machine-check evidence: validation_gate_ready=false.
- Machine-check evidence: validation_gate_passed=false.
- Machine-check evidence: request_payload_validated=false.
- Machine-check evidence: validate command request payloads remains forbidden.
- Machine-check evidence: register payload validators remains forbidden.
- Machine-check evidence: route/draft flags are true while execution remains
  false.
- Machine-check evidence: route/draft flags true while execution remains.
- Historical machine-check evidence: proof payload-field contract registry evidence.
- Historical machine-check evidence: validate submitted proof payloads remains
  forbidden for the completed disabled payload-field registry.
- `GET /api/v1/futures/account`, `GET /api/v1/futures/positions`, and
  `GET /api/v1/futures/positions/{position_key}` expose read-only
  futures/perpetual account, risk, and position evidence; `position_key` is
  the read identity, configured product scope is separate from observed
  position scope, close/reduce sides are backend-derived from observed
  position side, and futures/perpetual command draft routes remain no-live
- `GET /api/v1/admin/guard-risk-policy` exposes backend-owned guard/risk
  policy evidence: action-condition policy, configured cap rules, live gate
  posture, product capability policy, profitability-validator posture,
  authority sources, and rejection categories. It does not fetch Coinbase
  wallets, approve live execution, or move guard calculations into the browser
- `GET /api/v1/admin/audit-workbench` exposes backend-owned cross-module
  audit evidence: route inventory, command audit events, correlation ids,
  request ids, audit ids, module summaries, and exchange evidence. It does not
  mutate audit history, fetch Coinbase, approve live execution, or create a
  second command path
- admin bootstrap, health, session, OIDC readiness, capabilities, CSRF,
  release gate, recovery gate, fill-ledger health, and frontend fixture routes
  are read-only and auth/RBAC-gated
- auth, RBAC, and validation errors return structured error payloads with
  `code`, `message`, `severity`, optional `field_path`, and correlation id
- responses include `X-Correlation-Id`, `X-Request-Id`,
  `X-Admin-Api-Version`, and `X-Live-Execution-Enabled`
- legacy dashboard `place_order` and `cancel_order` messages now delegate to
  `application.admin_api.command_service.AdminApiCommandService` as
  compatibility adapters
- read-only spot routes are available for operator views and remain
  permission-gated; the OpenAPI contract documents `401` and `403` for those
  auth/RBAC failures

Canonical path:

```text
frontend request
-> FastAPI route
-> auth/RBAC
-> idempotency and approval gate
-> shared command service
-> existing domain/bridge/exchange path
-> durable audit
-> typed response
```

Cancel remains `client_order_id` keyed. The future implementation must call the
project Coinbase wrapper `cancel_order(client_order_id)` rather than resolving
to exchange `order_id` first.

HTTP auth bootstrap mode:
- set `COINBASE_ADMIN_API_BEARER_TOKEN`
- send `Authorization: Bearer <token>`
- send `X-Admin-Actor`
- send comma-separated `X-Admin-Roles`

HTTP OIDC/JWT mode:
- set `COINBASE_ADMIN_API_AUTH_MODE=oidc_jwt`
- set `COINBASE_ADMIN_API_OIDC_ISSUER`
- set `COINBASE_ADMIN_API_OIDC_AUDIENCE`
- set `COINBASE_ADMIN_API_OIDC_JWKS_URL`
- send `Authorization: Bearer <jwt>`
- do not use browser-supplied actor/role headers as authority; the backend
  derives actor and roles from verified JWT claims
- read `GET /api/v1/admin/oidc-readiness` for active auth mode,
  required/missing OIDC env, claim mapping, JWKS reachability, and no-live
  notional evidence
- prove the no-live OIDC verifier path with
  `python tools\run_admin_oidc_readiness_smoke.py --summary-only`

Without configured backend auth, routes fail closed with `401`.

Route inventory:
- `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`

Generate the schema with:

```powershell
python tools\generate_admin_api_openapi.py
```

Run the local Admin API for frontend development with:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
```

The runner starts `api.v1.app:app`, defaults to `http://127.0.0.1:8787`, and
keeps live Coinbase execution disabled.

## 1) Coinbase REST Wrapper (`CoinbaseRestClient`)

### Account and portfolio
- `get_account_wallets()`
- `get_transaction_summary()`
- `get_accounts()`
- `get_portfolio(portfolio_id)`
- `list_portfolios()`

`get_account_wallets()` follows Coinbase `get_accounts` pagination before
building the currency-to-wallet map. Do not replace it with a single
`get_accounts()` call at guard boundaries.

### Product metadata
- `get_product(product_id)`
- `get_products(product_ids)`
- `get_product_dict(product_id)`

### Orders
- `get_open_orders()`
- `place_limit_order(product_id, side, limit_price, base_size|quote_size, client_order_id, post_only, time_in_force)`
- `create_order(...)` (pass-through/flexible order configuration)
- `list_orders(order_status=None)`
- `cancel_order(client_order_id)`
- `cancel_orders(order_ids)`
- `limit_order_gtc(...)`

### Fills and candles
- `list_fills(order_id=None, product_id=None, start_date=None, end_date=None, cursor=None, limit=100)`
- `get_candles(product_id, start, end, granularity="ONE_MINUTE")`

### Futures
- `get_futures_positions()`
- `list_futures_positions()`

### Notes
- `place_limit_order` returns raw SDK response dict (do not coerce to `Order`).
- `list_fills` maps user-facing params to SDK keys (`order_ids`, `product_ids`, `start_sequence_timestamp`, `end_sequence_timestamp`).
- `cancel_order(client_order_id)` calls the Coinbase cancel wrapper with the
  project `client_order_id` and treats only explicit `success: true` cancel
  evidence as success. Non-empty failure payloads such as `success: false` are
  rejected.

## Spot Sweep And Campaign CLI Outputs

`tools/run_spot_campaign.py --sell-authority-allowlist` writes three optional
artifacts:
- allowlist audit JSON from `--write-allowlist-file`
- narrowed campaign config from `--write-allowlist-config-file`
- rendered sweep config from `--write-allowlist-sweep-config-file`

Rendered SELL allowlist sweep configs include a
`sell_authority_allowlist` metadata block with `generated_at`,
`max_age_seconds`, `expires_at`, `freshness_status`, allow/block counts, and
estimated allowlisted quote notional. `tools/run_spot_portfolio_sweep_live.py`
copies that block from config files, reports
`sell_authority_allowlist_freshness` during `--validate-config`, and rejects
stale or invalid allowlist metadata before live mode can submit Coinbase
orders.

Spot inventory coverage and sweep validation include
`inventory_baseline_freshness_audit`. Imported baseline lots should carry
source freshness metadata such as `source_updated_at`, `updated_at`,
`generated_at`, `observed_at`, `as_of`, `snapshot_at`, or `refreshed_at`.

When Coinbase average cost is explicitly enabled for SELL authority,
`coinbase_average_cost_authority_gate` blocks only planned SELL rows whose
authority comes from Coinbase average cost and whose record is stale, missing,
invalid, or stale versus the local drift audit.

## 2) Coinbase WebSocket Wrapper (`CoinbaseWebSocketClient`)

Connection lifecycle:
- `connect()`
- `disconnect()`
- `is_connected()`

Subscription and callbacks:
- `subscribe(products, channels, on_message=None, on_error=None)`
- `unsubscribe(products=None, channels=None)`
- `on_message(callback)`
- `on_error(callback)`
- `on_open(callback)`
- `on_close(callback)`

Utility:
- `sleep_with_exception_check(duration)`
- `get_sdk_client()`

## 3) Dashboard WebSocket Contract (`ws://localhost:8765`)

### Client request message types

Runtime/admin:
- `admin_status`
- `admin_pause`
- `admin_resume`
- `admin_shutdown`

General order actions:
- `place_order`
- `cancel_order`

Parent order views and CRUD:
- `request_parent_orders`
- `create_parent_order`
- `update_parent_order`
- `delete_parent_order`
- `update_parent_target_movement`

`create_parent_order` is local dashboard/database CRUD only. It creates an
`order_parent` row and does not submit a Coinbase order. Live dashboard
submission uses `place_order`.

Compatibility warning: the enterprise admin frontend must not build product
workflows on this dashboard WebSocket surface. New frontend work uses the HTTP
Admin API contract and BFF/session boundary described above. The dashboard
messages below remain legacy/operator compatibility surfaces.

`place_order` submits a live Coinbase order when REST is available and the
product capability, size validator, manual spot live acknowledgement, and
action-condition guard admit the request. For spot products,
`params.manual_live_acknowledgement=true` is required before the handler reaches
REST submission. Direct spot placement also requires a matching planning-phase
`max_notional` action-condition guard, and direct spot `SELL` requires
`known_inventory_available` to be enabled before REST submission. Direct spot
placement also requires an enabled local `order_event_stream` publisher before
REST submission. On success, `order_response` includes both the internal
`client_order_id` and Coinbase `order_id` so dashboard submissions can be
correlated with websocket, reconciliation, and fill-ledger evidence. The
handler also writes an `order_submitted` event with source channel
`rest_submit` to `order_event_stream` when the local event stream is available.
The handler normalizes SDK objects, `to_dict()` responses, and nested
`success_response.order_id` payloads before building that audit response.
Base-sized orders are validated through `validate_and_quantize_size`.
Quote-sized market BUYs validate `quote_size` directly against product
`quote_increment` and `quote_min_size`. The direct dashboard handler does not
pre-insert `order_parent` or opt the order into automated follow-up policy
state before submission. It is an immediate manual order surface; websocket
lifecycle and reconciliation own later local evidence rows.

`cancel_order` is a manual dashboard cancellation request keyed by
`client_order_id`. The handler accepts top-level `client_order_id` or
`params.client_order_id`, rejects requests that provide only `order_id`, and
calls `REST_CLIENT.cancel_order(client_order_id)`. Do not add an exchange-id
resolver to this dashboard path. Raw batch `cancel_orders(order_ids=[...])`
remains exchange-id oriented for paths that explicitly use the batch API.

Stealth views/actions:
- `request_stealth_orders`
- `create_stealth_order`
- `cancel_stealth_order`
- `update_stealth_target_movement`
- `update_stealth_price_threshold`
- `reprice_now_stealth_order`
- `move_revealed_stealth_order`
- `clear_all_stealth_orders`
- `export_active_stealth_orders`
- `import_stealth_orders`

Move and product utilities:
- `request_move_history`
- `move_order`
- `premark_move`
- `request_products`
- `update_products_list`
- `request_spot_readiness`
- `request_spot_sweep_status`
- `request_spot_sweep_pnl`
- `request_spot_cost_basis_status`
- `request_spot_campaign_status`
- `request_spot_direct_order_audit`

Hotpoint manager:
- `request_hotpoint_state`
- `set_hotpoint_kill_switch`
- `place_hotpoint_test_order`

`place_hotpoint_test_order` is a live Coinbase submission surface used by
`ui_hotpoint_manager.html` to seed the hotpoint detector with a normal limit
order whose `order_parent` row has `enable_hotpoint_replication=TRUE`. It is
not a generic spot bypass. The handler is runtime-admission gated, requires
`ProductCapability.HOTPOINT_AUTO_PLACEMENT`, validates size, runs the
planning-phase `ActionConditionGuard`, pre-inserts the parent row, and submits
through `AdminApiCommandService.place_hotpoint_test_order`. That shared service
calls `REST_CLIENT.limit_order_gtc` and writes `order_submitted` /
`rest_submit` evidence when the local event stream is available. Spot products
are blocked by default unless the hotpoint capability is explicitly enabled in
product capability policy.

Analytics/storyboard:
- `request_slide_calibration_summary`
- `request_market_chart_history`
- `request_storyboard_products`
- `request_investor_storyboard`

Connectivity:
- `ping`

### Server response message types

Administrative:
- `admin_status_response`
- `admin_pause_response`
- `admin_resume_response`
- `admin_shutdown_response`
- `admission_rejected`

Order/parent responses:
- `order_response`
- `cancel_response`
- `parent_orders_list`
- `parent_order_created`
- `parent_order_updated`
- `parent_order_deleted`
- `parent_target_movement_updated`

Stealth responses:
- `stealth_orders_snapshot`
- `stealth_order_created`
- `stealth_order_cancelled`
- `stealth_order_updated`
- `stealth_order_moved`
- `stealth_threshold_updated`
- `reprice_now_result`
- `export_active_stealth_orders_response`
- `import_stealth_orders_response`
- `stealth_orders_imported`
- `stealth_orders_cleared`

Move/product/analytics responses:
- `move_history_list`
- `order_moved`
- `order_premarked`
- `products_list`
- `products_list_updated`
- `spot_readiness`
- `spot_sweep_status`
- `spot_sweep_pnl`
- `spot_cost_basis_status`
- `spot_campaign_status`
- `spot_direct_order_audit`
- `hotpoint_state`
- `hotpoint_kill_switch_response`
- `place_hotpoint_test_order_response`
- `slide_calibration_summary`
- `market_chart_history`
- `storyboard_products`
- `spread_snapshot`

Common/global:
- `state_update`
- `update_success`
- `error`
- `pong`
- `ticker`

### Stealth message contract rules

- A dashboard request type is considered active only when it is implemented end to end: browser/terminal caller, `dashboard_server.py` handler, bridge method if the handler routes through `StealthOrderBridge`, manager/domain method, and regression coverage.
- Do not document speculative message types as active. If a design is not implemented, keep it in design notes, not in the request/response tables above.
- Cancel/re-entry is active as a policy carried by `create_stealth_order` and import/export payloads, not as a separate WebSocket request type.
- Cancel/re-entry is not general hide-again behavior. It cancels a live no-fill placement, marks the stealth order hidden with `cancelled_by_policy` state, then re-enters through the normal reveal path when thresholds allow.
- Same-side post-fill retreat is active as a policy carried by `create_stealth_order` and import/export payloads, not as a separate WebSocket request type. It only mutates opted-in hidden orders with no live exchange placement.
- The old UI "Hide" action must not be described as re-hide either.

### `create_stealth_order` high-impact fields

Core fields:
- `product_id`
- `side`
- `total_size`
- `limit_price`
- `reveal_condition`
- `sizing_strategy`
- `target_movement`
- `target_movement_type`

Policy fields:
- `anchor_repricing_policy`
- `cancel_reentry_policy`
- `post_fill_retreat_policy`
- `reveal_pricing_policy`
- `follow_up_reveal_direction`

`cancel_reentry_policy` shape:
- `enabled`
- `reference_price_source`: `last_trade`, `midpoint`, or `top_of_book`
- `distance_type`: `A` absolute or `P` percent
- `cancel_distance`
- `reentry_distance`
- `cooldown_seconds`
- `max_reentry_count`
- `inherit_to_follow_ups`

Validation contract:
- `cancel_distance` must be greater than `0`.
- `reentry_distance` must be greater than `cancel_distance`.
- The policy only cancels revealed orders with no executed size.
- If exchange cancel fails, the order remains `REVEALED` and active placement pointers stay intact.

`post_fill_retreat_policy` shape:
- `enabled`
- `scope`: `same_product_same_side`
- `retreat_ticks`
- `inherit_to_follow_ups`

Runtime contract:
- Triggered by a filled same-product/same-side stealth placement.
- Selects one nearest eligible hidden order that opted in.
- Moves BUY lower and SELL higher by `retreat_ticks * product.price_increment`.
- Updates `limit_price`, absolute reveal-condition price fields, trigger timestamps, and cumulative anchor offset in `anchor_repricing_state_json`.
- Does not cancel/move/reprice any live `REVEALED` exchange placement.

Import/export contract:
- Active-stealth export stores persisted field names such as `cancel_reentry_policy_json`.
- Import maps those names back to request names such as `cancel_reentry_policy` and `post_fill_retreat_policy`.
- `ui_order_span_builder.html` and `ui_stealth_orders_manager.html` both send `cancel_reentry_policy` and `post_fill_retreat_policy` when configured.

### `request_spot_readiness`

Request shape:

```json
{"type": "request_spot_readiness"}
```

Optional product filter:

```json
{
  "type": "request_spot_readiness",
  "params": {"product_ids": ["BTC-USD"]}
}
```

Response shape:

```json
{
  "type": "spot_readiness",
  "status": "success",
  "generated_at": "2026-06-08T00:00:00",
  "products": [
    {
      "product_id": "BTC-USD",
      "product_type": "SPOT",
      "base_currency": "BTC",
      "quote_currency": "USD",
      "capabilities": {
        "direct_placement": {"mode": "enabled", "reason": "allowed by policy"}
      },
      "inventory": {
        "imported_baselines": {
          "configured": true,
          "known_quantity": 0.25,
          "unknown_cost_basis_quantity": 0.1,
          "lots": [
            {
              "source_id": "manual-baseline",
              "cost_basis_status": "known",
              "remaining_quantity": 0.25,
              "entry_price": 90000.0,
              "min_profitable_exit_price": 90450.0
            }
          ]
        }
      }
    }
  ],
  "planned_budget": {"USD": 125.5},
  "wallet_snapshot": {
    "available": true,
    "age_seconds": 0.0,
    "currencies": {"USD": {"available_balance": 1000.0}}
  },
  "action_guards": {
    "wallet_available": {"enabled": true},
    "known_inventory_available": {"enabled": true}
  },
  "action_guard_summary": [
    {
      "condition": "planned_budget_available",
      "label": "planned spot budget",
      "mode": "enabled",
      "phases": ["planning", "reveal"],
      "reason": "spot wallet availability is reduced by local hidden, pending, and triggered spot commitments"
    }
  ]
}
```

Operator contract:
- The dashboard may render `capabilities`, `action_guard_summary`, wallet
  snapshot data, planned budget, and imported baseline inventory directly.
- `inventory.imported_baselines` is an operator summary, not a replacement for
  the lot-authority guard. Concrete spot `SELL` admission still requires a size
  and price and is decided by the shared action-condition guard.
- Structured `error` payloads may include `guard` or `capability` dictionaries
  when a planning boundary rejects an action.

### `request_spot_sweep_status`

Request shape:

```json
{"type": "request_spot_sweep_status"}
```

Optional sweep ledger override:

```json
{
  "type": "request_spot_sweep_status",
  "params": {"state_file": "runtime_state/spot_portfolio_sweeps.jsonl"}
}
```

Response shape:

```json
{
  "type": "spot_sweep_status",
  "status": "success",
  "state_file": "runtime_state/spot_portfolio_sweeps.jsonl",
  "operator_status": {
    "config_count": 1,
    "run_count": 1,
    "submitted_order_count": 385,
    "blocked_or_error_count": 0,
    "total_submitted_notional_usdc": "385",
    "total_executed_notional_usdc": "381.4362450472677185",
    "configs": [
      {
        "config_id": "spot-sweep-example",
        "latest_run": {
          "status": "completed",
          "recorded_status": "partial",
          "execution": {
            "submitted_order_count": 385,
            "skipped_order_count": 2
          }
        }
      }
    ]
  }
}
```

Operator contract:
- This request reads the local sweep ledger only. It does not call Coinbase and
  does not submit orders.
- Planned skips, such as below-minimum quote-notional rows, remain visible in
  order details but are not counted as Coinbase submission failures.
- Live sweep placement still requires
  `tools/run_spot_portfolio_sweep_live.py --approved-live-orders`.
- Live SELL sweep placement also requires
  `--require-known-profitable-inventory`; wallet balance alone cannot
  authorize live SELL sweep execution.
- Live sweep order reports include UUID `client_order_id` values and
  `submission_event_recorded`. When the local event stream is available,
  accepted placements publish `order_submitted` / `rest_submit` evidence to
  `order_event_stream`; the JSONL sweep ledger remains the run-level audit
  record.

### `request_spot_sweep_pnl`

Request shape:

```json
{"type": "request_spot_sweep_pnl"}
```

Optional filters:

```json
{
  "type": "request_spot_sweep_pnl",
  "params": {
    "product_ids": ["BTC-USDC"],
    "include_coinbase_average_cost": false
  }
}
```

Response shape:

```json
{
  "type": "spot_sweep_pnl",
  "status": "success",
  "read_only_coinbase_requests": ["get_public_products"],
  "pnl_report": {
    "product_count": 1,
    "portfolio": {"total_unrealized_pnl_usdc": "0"},
    "since_last_purchase": {"total_unrealized_pnl_usdc": "0"}
  }
}
```

Operator contract:
- This request reads public product marks and local fill-ledger evidence. If
  `include_coinbase_average_cost` is true, it may also read Coinbase portfolio
  average-cost data.
- The response is operational P/L, not tax accounting.
- It never submits Coinbase orders.

### `request_spot_cost_basis_status`

Request shape:

```json
{"type": "request_spot_cost_basis_status"}
```

Optional snapshot ledger override:

```json
{
  "type": "request_spot_cost_basis_status",
  "params": {"state_file": "runtime_state/spot_cost_basis_snapshots.jsonl"}
}
```

Response shape:

```json
{
  "type": "spot_cost_basis_status",
  "status": "success",
  "state_file": "runtime_state/spot_cost_basis_snapshots.jsonl",
  "operator_status": {
    "snapshot_count": 1,
    "latest_snapshot": {
      "record_type": "spot_cost_basis_snapshot",
      "status": "available",
      "baseline": {"record_count": 376, "baseline_count": 376},
      "inventory_coverage": {"wallet_only_product_count": 8},
      "drift_audit": {"status_counts": {"stale": 1}},
      "gap_triage": {"product_count": 381}
    }
  }
}
```

Operator contract:
- This request reads the local cost-basis snapshot ledger only. It does not
  call Coinbase and does not submit orders.
- Generate or refresh snapshots with
  `tools/run_spot_portfolio_sweep_live.py --cost-basis-triage --record-cost-basis-snapshot`.

### `request_spot_campaign_status`

Request shape:

```json
{"type": "request_spot_campaign_status"}
```

Optional campaign ledger override:

```json
{
  "type": "request_spot_campaign_status",
  "params": {"state_file": "runtime_state/spot_campaigns.jsonl"}
}
```

Response shape:

```json
{
  "type": "spot_campaign_status",
  "status": "success",
  "state_file": "runtime_state/spot_campaigns.jsonl",
  "operator_status": {
    "campaign_count": 1,
    "snapshot_count": 2,
    "total_submitted_notional_usdc": "0",
    "total_executed_notional_usdc": "0",
    "operator_summary": {
      "readiness_status": "ready",
      "ready": true,
      "blocked": false,
      "gate_status": "passed",
      "automation_decision": "due",
      "next_run_at": "2026-01-01T06:00:00+00:00",
      "operation_lock_status": "released",
      "operation_lock_exists": false,
      "operation_lock_stale": false,
      "recovery_status": "passed",
      "planned_reconciliation_run_count": 0,
      "planned_backfill_order_count": 0,
      "planned_order_count": 10,
      "planned_skip_count": 0,
      "safety_decision": "allowed",
      "latest_live_run_id": "spot-sweep-example",
      "total_submitted_notional_usdc": "10",
      "total_executed_notional_usdc": "9.95",
      "portfolio_total_pnl": "0.12",
      "sell_authority_profile": "fill_ledger_strict",
      "sell_authority_allowlist_count": 33,
      "sell_authority_blocked_count": 319,
      "sell_authority_source_counts": {"fill_ledger": 33, "wallet_only": 319},
      "sell_authority_status_counts": {
        "known_profitable": 33,
        "insufficient_known_profitable": 317,
        "no_lots": 2
      },
      "sell_authority_estimated_allowlisted_quote_notional": "33.26606405",
      "sell_authority_allow_products_preview": ["ALT-USDC", "B3-USDC"]
    },
    "latest_snapshot": {
      "record_type": "spot_campaign_snapshot",
      "campaign_id": "spot-campaign-example",
      "mode": "release_gate",
      "status": "ready",
      "dry_run": {
        "plan": {"planned_count": 10, "skipped_count": 0},
        "safety_evaluation": {"decision": "allowed"}
      },
      "release_gate": {
        "gate_status": "passed",
        "failures": [],
        "warnings": []
      }
    },
    "latest_readiness_snapshot": {
      "record_type": "spot_campaign_snapshot",
      "mode": "release_gate",
      "status": "ready"
    },
    "latest_live_snapshot": {
      "record_type": "spot_campaign_snapshot",
      "mode": "live_canary",
      "sweep_summary": {"run_id": "spot-sweep-example"}
    }
  }
}
```

Operator contract:
- This request reads the local campaign snapshot ledger only. It does not call
  Coinbase and does not submit orders.
- `latest_snapshot` is the newest campaign ledger record. It can be a live
  canary record with no dry-run/release-gate details.
- `latest_readiness_snapshot` is the newest dry-run or release-gate record with
  readiness data. `latest_live_snapshot` is the newest live-canary record.
- `operator_summary` is the dashboard-ready read-only summary for readiness,
  due state, lock state, recovery state, planned skips, notional, and P/L.
- When the latest readiness record contains a SELL authority allowlist,
  `operator_summary` also includes the authority profile, allowlist and
  blocked counts, authority source/status counts, estimated allowlisted USDC
  notional, and a product preview.
- Generate or refresh snapshots with
  `tools/run_spot_campaign.py --config-file <path> --dry-run-matrix --record-snapshot`
  or `tools/run_spot_campaign.py --config-file <path> --release-gate --record-snapshot`.
- Generate a narrowed SELL authority allowlist with
  `tools/run_spot_campaign.py --config-file <path> --sell-authority-allowlist --write-allowlist-sweep-config-file <path>`.
- Live campaign canaries use a rendered sweep config and
  `tools/run_spot_portfolio_sweep_live.py --approved-live-orders`.
- SELL canaries also require the rendered config or CLI to set
  `--require-known-profitable-inventory`.

### `request_spot_direct_order_audit`

Request shape:

```json
{
  "type": "request_spot_direct_order_audit",
  "params": {
    "client_order_id": "client-order-id",
    "include_events": true,
    "include_fills": true
  }
}
```

Response shape:

```json
{
  "type": "spot_direct_order_audit",
  "status": "success",
  "client_order_id": "client-order-id",
  "audit": {
    "record_type": "spot_direct_order_audit",
    "client_order_id": "client-order-id",
    "status": "found",
    "audit_is_read_only": true,
    "audit_command_live_coinbase_orders_ran": false,
    "audited_order_live_submission_evidence": true,
    "audited_order_live_coinbase_orders_ran": true,
    "audited_order_estimated_submitted_notional_usdc": "5",
    "audited_order_fill_notional_usdc": "5",
    "live_coinbase_orders_ran": false,
    "total_submitted_notional_usdc": "0",
    "total_executed_notional_usdc": "0",
    "read_only_coinbase_requests": []
  }
}
```

Operator contract:
- This request reads local direct-order event and fill evidence by
  `client_order_id`.
- It does not call Coinbase, place orders, cancel orders, retry orders, or run
  reconciliation.
- `live_coinbase_orders_ran` and
  `audit_command_live_coinbase_orders_ran` describe the audit request itself.
  Use `audited_order_live_submission_evidence`,
  `audited_order_estimated_submitted_notional_usdc`, and
  `audited_order_fill_notional_usdc` for evidence about the order being
  audited.
- The equivalent CLI is
  `python tools\run_spot_direct_order_audit.py --client-order-id <client_order_id>`.
- Missing `client_order_id` returns an error payload before local DB reads.

## 4) Internal Runtime Control API

`core/runtime_controller.py` exposes:
- `get_runtime_controller()` singleton accessor
- `check_admission(category)` gate
- `track_inflight(category)` context manager
- `request_pause()`, `resume()`, `request_shutdown()`
- `drain_and_stop(timeout_seconds)`
- `register_stop_hook(name, hook)`

Inflight categories used by callers include:
- `INFLIGHT_REST_PLACE`
- `INFLIGHT_REST_CANCEL`
- `INFLIGHT_FILL_PROCESSING`
- `INFLIGHT_STEALTH_REVEAL`
- `INFLIGHT_DB_WRITE`

## 5) Error-Handling Guidance

- Use domain-specific exceptions from `core/exceptions.py`.
- WebSocket handlers should return structured `error` payloads, not raw tracebacks.
- Reconciliation and analytics helpers are fail-soft by design; log and degrade rather than crash engine loops.

---

Last updated: 2026-06-24

## Completed M57 Futures Request Payload Validation Record Schema Evidence

`GET /api/v1/futures/command-suite` completed `6501-6520` evidence includes
futures request payload validation evidence record contract evidence through
disabled rows from
`application/admin_api/futures_request_payload_validation_evidence_records.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS`, and
`iter_futures_request_payload_validation_evidence_records`. Completed
futures request payload validation evidence remains available through
`application/admin_api/futures_request_payload_validation_evidence.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS`, and
`iter_futures_request_payload_validation_evidence`. The response includes
`request_payload_validation_evidence_count`,
`blocking_request_payload_validation_evidence_count`,
`ready_request_payload_validation_evidence_count`,
`recorded_request_payload_validation_evidence_count`,
`runtime_observed_request_payload_validation_evidence_count`,
`request_payload_validation_evidence`, `validation_evidence_contract_ref`,
`validation_evidence_field_refs`, `validation_evidence_field_count`,
`required_evidence_refs`, `missing_evidence_refs`,
`request_payload_validation_evidence_record_count`,
`blocking_request_payload_validation_evidence_record_count`,
`ready_request_payload_validation_evidence_record_count`,
`stored_request_payload_validation_evidence_record_count`,
`runtime_observed_request_payload_validation_evidence_record_count`,
`request_payload_validation_evidence_records`,
`validation_record_contract_ref`, `validation_record_store_ref`,
`validation_record_writer_ref`, `validation_record_replay_guard_ref`,
`validation_record_field_refs`, `validation_record_field_count`,
`runtime_evidence_satisfies_validation_evidence=false`,
`validation_evidence_ready=false`, `validation_evidence_recorded=false`,
`validation_record_contract_ready=false`,
`validation_record_store_ready=false`,
`validation_record_writer_enabled=false`,
`validation_record_replay_guard_ready=false`,
`validation_recorded=false`, `append_only_validation_record=false`,
`validation_record_idempotency_bound=false`,
`validator_input_schema_ref`, `validator_output_schema_ref`,
`validator_registration_ref`, and `request_payload_validated=false`. These
rows are evidence only; they do not validate command request payloads, record
validation evidence, write append-only validation records, register payload
validators, call Coinbase, execute reconciliation, mutate futures/order or
exchange state, or grant browser/BFF/spot-rule authority. Route/draft flags
true while execution remains false. Carried-forward validator-registration
rows still expose `validator_registration_ready=false` and
`runtime_evidence_satisfies_validator_registration=false`; carried-forward
output-schema rows still expose `output_schema_registered=false`.

Completed `6521-6540` evidence added futures request payload validation record
schema and append-only log evidence through disabled rows from
`application/admin_api/futures_request_payload_validation_record_schemas.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS`, and
`iter_futures_request_payload_validation_record_schemas`. The response now
also includes `request_payload_validation_record_schema_count`,
`blocking_request_payload_validation_record_schema_count`,
`ready_request_payload_validation_record_schema_count`,
`registered_request_payload_validation_record_schema_count`,
`runtime_observed_request_payload_validation_record_schema_count`,
`request_payload_validation_record_schemas`,
`validation_record_schema_ref`, `validation_record_append_only_log_ref`,
`validation_record_schema_field_refs`, `validation_record_schema_field_count`,
`runtime_evidence_satisfies_validation_record_schema=false`,
`validation_record_schema_ready=false`,
`validation_record_schema_registered=false`, and
`validation_record_append_only_log_ready=false`. These rows are evidence only;
they do not register schemas, write append-only validation logs, validate
command request payloads, write validation records, call Coinbase, execute
reconciliation, mutate futures/order or exchange state, or grant browser/BFF/
spot-rule authority.
