# Futures/Perpetuals Examples

These examples use the enterprise Admin API. They are read-only examples and
do not place, close, cancel, or modify Coinbase orders.

Start the local Admin API:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
```

## Command-Suite Contract Evidence

The active 6561-6580 range targets explicit M57 futures/perpetual request
payload validation record audit-link evidence for
`GET /api/v1/futures/command-suite` and the disabled command draft routes.
Representative response metadata includes
`"approved_phase_range": "6561-6580"` and no-live audit-link counts such as
`"request_payload_validation_record_audit_link_count"`,
`"blocking_request_payload_validation_record_audit_link_count"`,
`"ready_request_payload_validation_record_audit_link_count"`,
`"audit_bound_request_payload_validation_record_count"`,
`"runtime_observed_request_payload_validation_record_audit_link_count"`, and
`"request_payload_validation_record_audit_links"`. Completed 6541-6560 replay
guard evidence remains visible through
`"request_payload_validation_record_replay_guard_count"`,
`"blocking_request_payload_validation_record_replay_guard_count"`,
`"ready_request_payload_validation_record_replay_guard_count"`,
`"idempotency_bound_request_payload_validation_record_count"`,
`"runtime_observed_request_payload_validation_record_replay_guard_count"`, and
`"request_payload_validation_record_replay_guards"`.
Completed 6221-6240 work added aggregate
blocked summaries for unresolved prerequisites, request payload contracts,
semantic guard evidence, risk proof acceptance, live service adapters, and
contextless review. Completed 6241-6260 work added
ordered `command_enablement_sequence_steps` derived from backend
`readiness_closure_steps`. Completed 6261-6280 work added
`command_enablement_sequence_command_traces` so contextless maintainers can see
which per-command closure rows back the sequence:
`resolve_prerequisite_contracts`, `define_request_payload_contract`,
`bind_semantic_guard_evidence`, `bind_live_service_adapter`, and
`run_contextless_review_gate`. Completed
6281-6300 work reports `service_method="reconcile_futures_position"` for the
`futures_reconcile` row as a disabled shared command-service bridge while
keeping `record_futures_reconciliation_plan` as the separate required
reconciliation-plan contract. Completed 6301-6320 work reports registry-backed
`proof_contracts` with
`application/admin_api/futures_proof_routes.py::post_futures_place_margin_collateral_proof`,
`application/admin_api/futures_proof_writer.py::write_futures_place_margin_collateral_proof`,
`registered_proof_route_count=0`, and `enabled_proof_writer_count=0`.
Machine-check evidence: proof route/writer contract registry evidence;
`"application/admin_api/futures_proof_routes.py::post_futures_place_margin_collateral_proof"`;
`"application/admin_api/futures_proof_writer.py::write_futures_place_margin_collateral_proof"`;
`"registered_proof_route_count": 0`; `"enabled_proof_writer_count": 0`.
Completed 6321-6340 work reports registry-backed `payload_fields` with
`proof_payload.command`, `proof_payload.validation.status`,
`futures_place_margin_collateral_payload_command_validated`,
`payload_field_present=false`, and `validation_registered=false`.
Machine-check evidence: proof payload-field contract registry evidence;
`"proof_payload.command"`; `"proof_payload.validation.status"`;
`"futures_place_margin_collateral_payload_command_validated"`;
`"payload_field_present": false`; `"validation_registered": false`.
Completed 6341-6360 work reports route-bound command draft evidence for
`/api/v1/futures/orders`,
`/api/v1/futures/positions/{position_key}/close-reduce`,
`/api/v1/futures/orders/{client_order_id}/cancel`, and
`/api/v1/futures/positions/{position_key}/reconciliation`. Machine-check
evidence: futures route-bound command draft evidence; route/draft flags are
true while execution remains false; cancel by client_order_id.
Completed 6361-6380 work reports futures request payload contract registry
evidence through `FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS` and
`iter_futures_request_payload_contracts`. Machine-check evidence:
futures request payload contract registry evidence; `"request_field_count": 22`;
`"blocking_request_field_count": 22`;
`"application/admin_api/futures_request_payload_contracts.py::futures_cancel_client_order_id_request_payload_contract"`.
Completed 6381-6400 work reports futures request payload validation gate evidence
with `"validation_gate_ref"`, `"validation_evidence_ref"`,
`"validator_contract_ref"`, `"validator_registration_ref"`,
`"validation_gate_ready": false`, `"validation_gate_passed": false`,
`"validator_contract_registered": false`, `"validator_registered": false`,
and `"request_payload_validated": false`.
Completed 6401-6420 work reports futures request payload validator contract
registry evidence through `FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS` and
`iter_futures_request_payload_validator_contracts`, with
`"request_payload_validator_contract_count": 22`,
`"blocking_request_payload_validator_contract_count": 22`,
`"ready_request_payload_validator_contract_count": 0`,
`"registered_request_payload_validator_contract_count": 0`,
`"request_payload_validator_contracts"`, `"validator_input_schema_ref"`,
`"validator_output_schema_ref"`,
`"validator_input_schema_registered": false`, and
`"validator_output_schema_registered": false`.
Machine-check evidence: futures request payload validator contract registry evidence.
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
`"ready_request_payload_validator_output_schema_count": 0`,
`"registered_request_payload_validator_output_schema_count": 0`,
`"request_payload_validator_output_schemas"`, `"output_schema_field_refs"`,
`"output_schema_field_count": 5`, and `"output_schema_registered": false`.
Machine-check evidence: futures request payload validator output-schema evidence.
Completed 6461-6480 work reports futures request payload validator
registration evidence through
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS` and
`iter_futures_request_payload_validator_registrations`, with
`"request_payload_validator_registration_count": 22`,
`"blocking_request_payload_validator_registration_count": 22`,
`"ready_request_payload_validator_registration_count": 0`,
`"registered_request_payload_validator_registration_count": 0`,
`"runtime_observed_request_payload_validator_registration_count": 0`,
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
`"validation_record_schema_ref"`,
`"validation_record_append_only_log_ref"`,
`"validation_record_schema_field_refs"`,
`"validation_record_schema_field_count"`,
`"runtime_evidence_satisfies_validation_record_schema": false`,
`"validation_record_schema_ready": false`,
`"validation_record_schema_registered": false`, and
`"validation_record_append_only_log_ready": false`.
Machine-check evidence: futures request payload validation record schema
evidence.
Route/draft flags are true while execution remains false; the registries do
not validate command request payloads, record validation evidence, write
append-only validation records, register payload validators, call Coinbase,
execute reconciliation, mutate
futures/order/exchange state, or grant browser/BFF authority.
Concrete risk-proof record readbacks at `GET /api/v1/futures/risk-proofs` use
read-only resolver evidence. `POST /api/v1/futures/risk-proofs` records
append-only local proof evidence only; it does not accept proofs, satisfy
readiness, make route-bound command drafts executable, call Coinbase, execute
reconciliation, mutate futures/order/exchange state, or grant browser/BFF
authority. Exact safe latest
records may be displayed, while missing or stale/invalid records fail closed.
Resolver evidence and runtime evidence do not satisfy validator input schemas,
satisfy validator output schemas, satisfy validator registrations, register
input/output schemas, register validator contracts, register validators,
execute disabled service methods, make validation gates ready,
make semantic contract definitions ready, register semantic contracts, satisfy risk proof
requirements, make route-bound futures command drafts executable, call Coinbase,
execute reconciliation, mutate futures/order/exchange state, or grant browser/BFF
authority.

`place_futures_order`, `close_or_reduce_futures_position`,
`cancel_futures_order`, and `reconcile_futures_position` are named disabled
backend command-service methods. The completed 6001-6020 range adds
`evaluate_futures_margin_collateral_liquidation` as a named disabled backend
risk-guard method. These are service boundary evidence only: the command-suite
keeps command-service and risk-guard contracts in `required_backend_contracts`
but removes them from `missing_backend_contracts`. The active range keeps
`record_futures_reconciliation_plan` as the separate required reconciliation-plan contract
and as disabled reconciliation-plan evidence in
`required_backend_contracts`. Route-registration contracts are required present
disabled evidence. Adapter contract refs are required/present disabled evidence.
Adapter construction refs are required/present disabled evidence. Adapter
decision refs are required/present disabled evidence. Adapter decision-record
refs are required/present disabled evidence. Adapter invocation refs are
required/present disabled evidence. Adapter execution refs are
required/present disabled evidence. Coinbase exchange-submission refs are
required/present disabled evidence. Post-exchange-submission reconciliation refs
are required/present disabled evidence. The adapter, exchange-submission, and
post-submission reconciliation evidence
does not configure adapters, construct adapters, record executable decisions,
invoke adapters, execute adapters, submit Coinbase orders, execute
post-exchange reconciliation,
mutate futures/order/exchange state, or grant browser/BFF execution authority.
Exact current boundary phrases: adapter contract refs are required/present disabled evidence; adapter construction refs are required/present disabled evidence; adapter decision refs are required/present disabled evidence; adapter decision-record refs are required/present disabled evidence; adapter invocation refs are required/present disabled evidence; adapter execution refs are required/present disabled evidence; Coinbase exchange-submission refs are required/present disabled evidence; post-exchange-submission reconciliation refs are required/present disabled evidence.

The command-suite contract still exposes read-only M57 futures/perpetual risk
proof record-validation remediation dependency work-item claim-trace
clearance-step review input store record-validation remediation dependency
work-item claim-trace clearance-step review input evidence below the existing
nested clearance-step review evidence.
Each readiness decision, ordered closure step, risk proof requirement, proof
contract, payload field, record/store contract,
record-validation row, record-validation remediation row, remediation
dependency row, remediation dependency work-item row, remediation dependency
work-item claim-trace row, remediation dependency work-item claim-trace
clearance-plan row, remediation dependency work-item claim-trace
clearance-step row, remediation dependency work-item claim-trace
clearance-step review row, remediation dependency work-item claim-trace
clearance-step review input row, clearance-step review input store requirement
row
(`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_requirements"`),
clearance-step review input store record-contract row
(`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_contracts"`),
clearance-step review input store record-validation row
(`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validations"`),
clearance-step review input store record-validation remediation row
(`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediations"`),
clearance-step review input store record-validation remediation dependency row
(`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependencies"`),
clearance-step review input store record-validation remediation dependency
work-item row
(`"remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_items"`),
dependency work-item count field
(`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_count"`),
dependency work-item claim-trace count field
(`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_count"`),
dependency work-item claim-trace rows
(`"remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_traces"`),
dependency work-item claim-trace clearance-plan rows
(`"remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plans"`),
dependency work-item claim-trace clearance-step count field
(`"record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_count"`),
dependency work-item claim-trace clearance-step rows
(`"remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_steps"`),
and acceptance criterion is derived from backend-owned prerequisites, request
fields, semantic guards, evidence routes, missing evidence refs, and missing
backend contracts. It is not a command route,
enabled proof writer, registered payload validator, registered record store,
registered record validator, remediation executor, remediation work-item
creator, dependency work-item creator, work-item claimant, claim trace
resolver, claim-trace clearance-plan creator, clearance-step executor, claim ledger,
clearance-step review completer, review-input acceptor,
review-input store creator, review-input writer, record-key registrar,
input record-contract creator, record schema creator, append-only log creator,
idempotency binder, payload validator, replay protector, input validator,
record-validator registrar, validation-gate passer, replay acceptor, command
draft surface, or execution approval.

Aggregate count fields are authoritative for the full logical scope. The
default command-suite response intentionally materializes only bounded
representative nested detail rows, currently the `futures_cancel` /
`product_scope` / `store_schema` branch, so the admin read model remains
serializable without losing total blocked/present/accepted counts.

```http
GET /api/v1/futures/command-suite
Authorization: Bearer local-admin-token
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected response posture:

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
  "command_enablement_sequence_step_count": 5,
  "command_enablement_sequence_step_blocking_count": 5,
  "command_enablement_sequence_steps": [
    {"step": "resolve_prerequisite_contracts", "status": "blocked"},
    {"step": "define_request_payload_contract", "status": "blocked"},
    {"step": "bind_semantic_guard_evidence", "status": "blocked"},
    {"step": "bind_live_service_adapter", "status": "blocked"},
    {"step": "run_contextless_review_gate", "status": "blocked"}
  ],
  "command_enablement_sequence_command_trace_count": 20,
  "command_enablement_sequence_command_trace_blocking_count": 20,
  "command_enablement_sequence_command_traces": [
    {
      "trace_id": "resolve_prerequisite_contracts::futures_place",
      "step": "resolve_prerequisite_contracts",
      "sequence": 1,
      "command": "futures_place",
      "command_step_sequence": 1,
      "status": "blocked",
      "source_blockers": ["unresolved_prerequisites"],
      "reconciliation_execution_allowed": false,
      "futures_state_mutation_allowed": false
    }
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
  "request_payload_validator_registrations": [
    {
      "field": "client_order_id",
      "validator_registration_ref": "application/admin_api/futures_request_payload_validator_registrations.py::futures_cancel_client_order_id_request_payload_validator_registration",
      "validator_registration_field_refs": [
        "application/admin_api/futures_request_payload_validator_registrations.py::futures_cancel_client_order_id_request_payload_validator_registration.validator_contract_ref"
      ],
      "validator_registration_field_count": 6,
      "required_evidence_refs": [
        "application/admin_api/futures_request_payload_validators.py::futures_cancel_client_order_id_request_payload_validator_contract"
      ],
      "required_evidence_count": 6,
      "missing_evidence_refs": [
        "application/admin_api/futures_request_payload_validators.py::futures_cancel_client_order_id_request_payload_validator_contract"
      ],
      "missing_evidence_count": 6,
      "validator_registration_ready": false,
      "runtime_evidence_satisfies_validator_registration": false,
      "validator_registered": false,
      "request_payload_validated": false
    }
  ],
  "request_payload_validation_evidence": [
    {
      "field": "client_order_id",
      "validation_evidence_contract_ref": "application/admin_api/futures_request_payload_validation_evidence.py::futures_cancel_client_order_id_request_payload_validation_evidence",
      "validation_evidence_field_refs": [
        "application/admin_api/futures_request_payload_validation_evidence.py::futures_cancel_client_order_id_request_payload_validation_evidence.validation_evidence_ref"
      ],
      "validation_evidence_field_count": 6,
      "required_evidence_count": 7,
      "missing_evidence_count": 7,
      "runtime_evidence_satisfies_validation_evidence": false,
      "validation_evidence_ready": false,
      "validation_evidence_recorded": false,
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
  "risk_proof_record_resolver_count": 20,
  "resolved_risk_proof_record_resolver_count": 0,
  "missing_risk_proof_record_resolver_count": 20,
  "stale_or_invalid_risk_proof_record_resolver_count": 0,
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
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 8640,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 8640,
  "ready_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 0,
  "completed_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 0,
  "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 17280,
  "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 17280,
  "present_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 0,
  "accepted_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 0,
  "record_validation_remediation_dependency_work_item_claim_trace_clearance_plans": [
    {
      "clearance_plan_created": false,
      "clearance_plan_ready": false,
      "record_validation_remediation_dependency_work_item_claim_trace_clearance_steps": [
        {
          "clearance_step_name": "inspect_claim_trace",
          "clearance_step_ready": false,
          "clearance_step_complete": false,
          "prior_clearance_step_complete": false,
          "next_clearance_step_enabled": false,
          "claim_resolved": false,
          "execution_allowed": false,
          "remediation_dependency_work_item_claim_trace_clearance_step_reviews": [
            {
              "clearance_step_review_claim": "claim_trace_clearance_step_review",
              "clearance_step_review_ready": false,
              "clearance_step_review_complete": false,
              "clearance_step_review_inputs_present": false,
              "clearance_step_review_gates_passed": false,
              "clearance_step_review_input_count": 2,
              "blocking_clearance_step_review_input_count": 2,
              "present_clearance_step_review_input_count": 0,
              "accepted_clearance_step_review_input_count": 0,
              "remediation_dependency_work_item_claim_trace_clearance_step_review_inputs": [
                {
                  "clearance_step_review_input_claim": "claim_trace_clearance_step_review_input",
                  "required_review_input": "futures_place.product_scope.record_validation_remediation_dependency_work_item_claim_trace_clearance_plan.store_schema.clearance_step.inspect_claim_trace.step_review.owner_review_evidence",
                  "clearance_step_review_input_present": false,
                  "clearance_step_review_input_accepted": false,
                  "clearance_step_review_input_validated": false,
                  "clearance_step_review_input_gate_passed": false,
                  "clearance_step_review_input_store_requirement_count": 1,
                  "blocking_clearance_step_review_input_store_requirement_count": 1,
                  "available_clearance_step_review_input_store_requirement_count": 0,
                  "writer_available_clearance_step_review_input_store_requirement_count": 0,
                  "remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_requirements": [
                    {
                      "clearance_step_review_input_store_requirement_claim": "claim_trace_clearance_step_review_input_store_requirement",
                      "store_required": true,
                      "store_available": false,
                      "writer_available": false,
                      "record_key_registered": false,
                      "validation_gate_passed": false,
                      "replay_gate_passed": false,
                      "clearance_step_review_input_store_record_contract_count": 1,
                      "blocking_clearance_step_review_input_store_record_contract_count": 1,
                      "available_clearance_step_review_input_store_record_contract_count": 0,
                      "accepted_clearance_step_review_input_store_record_contract_count": 0,
                      "remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_contracts": [
                        {
                          "clearance_step_review_input_store_record_contract_claim": "claim_trace_clearance_step_review_input_store_record_contract",
                          "record_contract_required": true,
                          "record_contract_available": false,
                          "record_schema_available": false,
                          "append_only_log_available": false,
                          "idempotency_key_bound": false,
                          "payload_schema_validated": false,
                          "replay_protected": false,
                          "store_available": false,
                          "writer_available": false,
                          "writer_allowed": false,
                          "write_allowed": false,
                          "record_present": false,
                          "record_accepted": false,
                          "record_validated": false,
                          "clearance_step_review_input_store_record_validation_count": 1,
                          "blocking_clearance_step_review_input_store_record_validation_count": 1,
                          "ready_clearance_step_review_input_store_record_validation_count": 0,
                          "configured_clearance_step_review_input_store_record_validation_count": 0,
                          "remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validations": [
                            {
                              "clearance_step_review_input_store_record_validation_claim": "claim_trace_clearance_step_review_input_store_record_validation",
                              "record_validation_required": true,
                              "record_validation_ready": false,
                              "validation_checks": [
                                "record_contract_available",
                                "record_schema_available",
                                "append_only_log_available",
                                "idempotency_key_bound",
                                "payload_schema_validated",
                                "replay_protected",
                                "record_present",
                                "record_accepted",
                                "record_validated"
                              ],
                              "validation_checks_passed": false,
                              "validation_configured": false,
                              "clearance_step_review_input_store_record_validation_remediation_count": 1,
                              "blocking_clearance_step_review_input_store_record_validation_remediation_count": 1,
                              "ready_clearance_step_review_input_store_record_validation_remediation_count": 0,
                              "recorded_clearance_step_review_input_store_record_validation_remediation_count": 0,
                              "remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediations": [
                                {
                                  "record_validation_remediation_required": true,
                                  "record_validation_remediation_ready": false,
                                  "record_validation_remediation_performed": false,
                                  "record_validation_remediation_recorded": false,
                                  "clearance_step_review_input_store_record_validation_remediation_dependency_count": 1,
                                  "blocking_clearance_step_review_input_store_record_validation_remediation_dependency_count": 1,
                                  "ready_clearance_step_review_input_store_record_validation_remediation_dependency_count": 0,
                                  "performed_clearance_step_review_input_store_record_validation_remediation_dependency_count": 0,
                                  "required_remediation_work": [
                                    "create_store_record_validation_remediation_contract",
                                    "bind_validation_remediation_action",
                                    "record_missing_validation_work",
                                    "attach_validation_remediation_evidence",
                                    "replay_protect_validation_remediation",
                                    "contextless_review_validation_remediation"
                                  ],
                                  "remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependencies": [
                                    {
                                      "record_validation_remediation_dependency_required": true,
                                      "record_validation_remediation_dependency_ready": false,
                                      "record_validation_remediation_dependency_resolved": false,
                                      "record_validation_remediation_dependency_performed": false,
                                      "required_dependency_work": [
                                        "create_store_record_validation_remediation_dependency_contract",
                                        "bind_validation_remediation_dependency_order",
                                        "record_validation_remediation_dependency_graph",
                                        "attach_validation_remediation_dependency_evidence",
                                        "replay_protect_validation_remediation_dependency",
                                        "contextless_review_validation_remediation_dependency"
                                      ],
                                      "dependency_ready": false,
                                      "dependency_resolved": false,
                                      "dependency_performed": false,
                                      "accepts_evidence": false,
                                      "writes_evidence": false,
                                      "execution_allowed": false
                                    }
                                  ],
                                  "accepts_evidence": false,
                                  "writes_evidence": false,
                                  "execution_allowed": false
                                }
                              ],
                              "accepts_evidence": false,
                              "writes_evidence": false,
                              "execution_allowed": false
                            }
                          ],
                          "accepts_evidence": false,
                          "writes_evidence": false,
                          "execution_allowed": false
                        }
                      ],
                      "accepts_evidence": false,
                      "writes_evidence": false,
                      "execution_allowed": false
                    }
                  ],
                  "accepts_evidence": false,
                  "writes_evidence": false,
                  "execution_allowed": false
                }
              ],
              "accepts_evidence": false,
              "writes_evidence": false,
              "execution_allowed": false
            }
          ]
        }
      ]
    }
  ],
  "record_validation_remediation_dependency_work_item_claim_trace_clearance_steps": [
    {
      "clearance_step_name": "inspect_claim_trace",
      "clearance_step_ready": false,
      "clearance_step_complete": false
    }
  ],
  "record_validation_remediation_dependency_work_item_claim_trace_clearance_step_reviews": [
    {
      "clearance_step_review_claim": "claim_trace_clearance_step_review",
      "clearance_step_review_ready": false,
      "clearance_step_review_complete": false,
      "clearance_step_review_inputs_present": false,
      "clearance_step_review_gates_passed": false,
      "required_review_inputs": [
        "futures_place.margin_sufficiency.latest_margin_snapshot.record_validation.remediation.missing_margin_snapshot_source.dependency.required_backend_contract.work_item.claim_trace.clearance_plan.clearance_step.inspect_claim_trace.step_review.owner_review_evidence",
        "futures_place.margin_sufficiency.latest_margin_snapshot.record_validation.remediation.missing_margin_snapshot_source.dependency.required_backend_contract.work_item.claim_trace.clearance_plan.clearance_step.inspect_claim_trace.step_review.contextless_review_evidence"
      ],
      "accepts_evidence": false,
      "writes_evidence": false,
      "execution_allowed": false
    }
  ],
  "record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_inputs": [
    {
      "clearance_step_review_input_claim": "claim_trace_clearance_step_review_input",
      "required_clearance_step_review_input_store_ref": "admin_futures_remediation_dependency_work_item_claim_trace_clearance_step_review_inputs.futures_place.product_scope",
      "required_review_input": "futures_place.product_scope.record_validation_remediation_dependency_work_item_claim_trace_clearance_plan.store_schema.clearance_step.inspect_claim_trace.step_review.owner_review_evidence",
      "clearance_step_review_input_present": false,
      "clearance_step_review_input_accepted": false,
      "clearance_step_review_input_validated": false,
      "clearance_step_review_input_gate_passed": false,
      "clearance_step_review_input_store_requirement_count": 1,
      "blocking_clearance_step_review_input_store_requirement_count": 1,
      "available_clearance_step_review_input_store_requirement_count": 0,
      "writer_available_clearance_step_review_input_store_requirement_count": 0,
      "remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_requirements": [
        {
          "clearance_step_review_input_store_requirement_claim": "claim_trace_clearance_step_review_input_store_requirement",
          "required_clearance_step_review_input_store_ref": "admin_futures_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_requirements.futures_place.product_scope",
          "required_writer_ref": "futures_place.product_scope.record_validation_remediation_dependency_work_item_claim_trace_clearance_plan.store_schema.clearance_step.inspect_claim_trace.step_review.owner_review_evidence.input_store_requirement.input_writer",
          "required_record_key": "futures_place.product_scope.record_validation_remediation_dependency_work_item_claim_trace_clearance_plan.store_schema.clearance_step.inspect_claim_trace.step_review.owner_review_evidence.input_record",
          "validation_gate": "futures_place.product_scope.record_validation_remediation_dependency_work_item_claim_trace_clearance_plan.store_schema.clearance_step.inspect_claim_trace.step_review.owner_review_evidence.input_store_requirement.input_record_validation_gate",
          "replay_gate": "futures_place.product_scope.record_validation_remediation_dependency_work_item_claim_trace_clearance_plan.store_schema.clearance_step.inspect_claim_trace.step_review.owner_review_evidence.input_store_requirement.input_record_replay_gate",
          "store_required": true,
          "store_available": false,
          "writer_available": false,
          "record_key_registered": false,
          "validation_gate_passed": false,
          "replay_gate_passed": false,
          "clearance_step_review_input_present": false,
          "clearance_step_review_input_accepted": false,
          "accepts_evidence": false,
          "writes_evidence": false,
          "execution_allowed": false
        }
      ],
      "clearance_step_review_ready": false,
      "clearance_step_review_complete": false,
      "clearance_step_review_inputs_present": false,
      "clearance_step_review_gates_passed": false,
      "claim_trace_created": false,
      "claim_allowed": false,
      "claim_resolved": false,
      "accepts_evidence": false,
      "writes_evidence": false,
      "execution_allowed": false
    }
  ],
  "risk_proof_acceptance_criterion_count": 100,
  "blocking_risk_proof_acceptance_criterion_count": 100,
  "accepted_risk_proof_acceptance_criterion_count": 0,
  "forbidden_spot_assumptions": [
    "spot_wallet_available",
    "spot_no_shorting",
    "spot_usdc_quote_required",
    "spot_average_cost_basis",
    "spot_inventory_lot_authority"
  ],
  "commands": [
    {
      "command": "futures_place",
      "status": "blocked",
      "action_class": "live_exchange_place",
      "route": "/api/v1/futures/orders",
      "service_method": "place_futures_order",
      "identity_key": "product_id",
      "required_backend_contracts": [
        "application/admin_api/futures_command_service.py::place_futures_order",
        "application/admin_api/futures_risk_guard.py::evaluate_futures_margin_collateral_liquidation",
        "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan",
        "api/v1/routes/futures.py::futures_place_route_contract",
        "application/admin_api/live_execution.py::futures_place_adapter_contract",
        "application/admin_api/live_execution.py::futures_place_adapter_construction_contract",
        "application/admin_api/live_execution.py::futures_place_adapter_decision_contract",
        "application/admin_api/live_execution.py::futures_place_adapter_decision_record_contract",
        "application/admin_api/live_execution.py::futures_place_adapter_invocation_contract",
        "application/admin_api/live_execution.py::futures_place_adapter_execution_contract",
        "application/admin_api/live_execution.py::futures_place_coinbase_exchange_submission_contract",
        "application/admin_api/live_execution.py::futures_place_post_exchange_submission_reconciliation_contract"
      ],
      "missing_backend_contracts": [],
      "request_field_count": 7,
      "blocking_request_field_count": 7,
      "semantic_guard_count": 10,
      "blocking_semantic_guard_count": 10,
      "risk_semantic_guard_count": 4,
      "request_fields": [
        {
          "field": "product_id",
          "status": "blocked",
          "identity_field": true,
          "risk_field": false,
          "spot_rule_authority": false,
          "browser_authority": "display_only"
        },
        {
          "field": "size",
          "status": "blocked",
          "identity_field": false,
          "risk_field": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only"
        },
        {
          "field": "client_order_id",
          "status": "blocked",
          "identity_field": true,
          "risk_field": false,
          "spot_rule_authority": false,
          "browser_authority": "display_only"
        }
      ],
      "semantic_guards": [
        {
          "semantic_guard": "product_scope",
          "status": "blocked",
          "evidence_routes": [
            "/api/v1/futures/account",
            "/api/v1/futures/positions"
          ],
          "evidence_route_count": 2,
          "missing_evidence_refs": [
            "futures_product_scope_readback",
            "futures_command_product_scope_contract"
          ],
          "missing_evidence_count": 2,
          "proof_route_registered": false,
          "proof_writer_enabled": false,
          "identity_semantic": true,
          "risk_semantic": false,
          "spot_rule_authority": false,
          "browser_authority": "display_only"
        },
        {
          "semantic_guard": "margin_collateral",
          "status": "blocked",
          "evidence_routes": [
            "/api/v1/futures/account",
            "/api/v1/admin/cap-guard/decisions"
          ],
          "evidence_route_count": 2,
          "missing_evidence_refs": [
            "futures_margin_collateral_risk_contract",
            "futures_cap_guard_margin_collateral_link"
          ],
          "missing_evidence_count": 2,
          "proof_route_registered": false,
          "proof_writer_enabled": false,
          "identity_semantic": false,
          "risk_semantic": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only"
        },
        {
          "semantic_guard": "live_execution_boundary",
          "status": "blocked",
          "evidence_routes": [
            "/api/v1/admin/live-enablement",
            "/api/v1/admin/live-execution/service-decisions",
            "/api/v1/admin/live-execution/adapter-decisions"
          ],
          "evidence_route_count": 3,
          "missing_evidence_refs": [
            "futures_live_enablement_precondition_contract",
            "futures_live_service_decision_contract",
            "futures_live_adapter_decision_contract"
          ],
          "missing_evidence_count": 3,
          "proof_route_registered": false,
          "proof_writer_enabled": false,
          "execution_semantic": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution"
        }
      ],
      "readiness_decision": {
        "decision": "blocked_backend_contracts_required",
        "status": "blocked",
        "ready": false,
        "blocker_count": 26,
        "blocking_prerequisite_count": 9,
        "blocking_request_field_count": 7,
        "blocking_semantic_guard_count": 10,
        "missing_backend_contract_count": 0,
        "missing_evidence_ref_count": 13,
        "evidence_route_count": 6,
        "first_blocker": "prerequisite:product_scope",
        "next_required_backend_contract": null,
        "command_route_registered": true,
        "command_draft_allowed": true,
        "execution_allowed": false,
        "backend_owned": true,
        "read_only": true,
        "spot_rule_authority": false,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution"
      },
      "readiness_closure_step_count": 6,
      "blocking_readiness_closure_step_count": 6,
      "readiness_closure_steps": [
        {
          "step": "resolve_prerequisite_contracts",
          "sequence": 1,
          "status": "blocked",
          "blocking": true,
          "required_evidence_refs": ["product_scope"],
          "command_route_registered": true,
          "command_draft_allowed": true,
          "execution_allowed": false,
          "proof_writer_enabled": false,
          "backend_owned": true,
          "read_only": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution"
        },
        {
          "step": "run_contextless_review_gate",
          "sequence": 6,
          "status": "blocked",
          "execution_allowed": false,
          "proof_writer_enabled": false,
          "spot_rule_authority": false
        }
      ],
      "risk_proof_requirement_count": 6,
      "blocking_risk_proof_requirement_count": 6,
      "risk_proof_contract_count": 12,
      "blocking_risk_proof_contract_count": 12,
      "registered_risk_proof_route_count": 0,
      "enabled_risk_proof_writer_count": 0,
      "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 2592,
      "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 2592,
      "ready_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 0,
      "completed_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 0,
      "risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 5184,
      "blocking_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 5184,
      "present_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 0,
      "accepted_risk_proof_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 0,
      "risk_proof_acceptance_criterion_count": 30,
      "blocking_risk_proof_acceptance_criterion_count": 30,
      "accepted_risk_proof_acceptance_criterion_count": 0,
      "risk_proof_acceptance_blocker_count": 36,
      "proof_record_resolved_but_acceptance_blocked_count": 0,
      "risk_proof_semantic_contract_requirement_count": 10,
      "blocking_risk_proof_semantic_contract_requirement_count": 10,
      "registered_risk_proof_semantic_contract_count": 0,
      "runtime_observed_risk_proof_semantic_contract_requirement_count": 4,
      "risk_proof_semantic_contract_definition_count": 10,
      "blocking_risk_proof_semantic_contract_definition_count": 10,
      "ready_risk_proof_semantic_contract_definition_count": 0,
      "registered_risk_proof_semantic_contract_definition_count": 0,
      "runtime_observed_risk_proof_semantic_contract_definition_count": 4,
      "risk_proof_semantic_contract_validation_gate_count": 10,
      "blocking_risk_proof_semantic_contract_validation_gate_count": 10,
      "ready_risk_proof_semantic_contract_validation_gate_count": 0,
      "registered_risk_proof_semantic_contract_validator_count": 0,
      "runtime_observed_risk_proof_semantic_contract_validation_gate_count": 4,
      "risk_proof_semantic_contract_validator_contract_count": 10,
      "blocking_risk_proof_semantic_contract_validator_contract_count": 10,
      "ready_risk_proof_semantic_contract_validator_contract_count": 0,
      "registered_risk_proof_semantic_contract_validator_contract_count": 0,
      "runtime_observed_risk_proof_semantic_contract_validator_contract_count": 4,
      "risk_proof_semantic_validator_input_schema_count": 10,
      "blocking_risk_proof_semantic_validator_input_schema_count": 10,
      "ready_risk_proof_semantic_validator_input_schema_count": 0,
      "registered_risk_proof_semantic_validator_input_schema_count": 0,
      "runtime_observed_risk_proof_semantic_validator_input_schema_count": 4,
      "risk_proof_semantic_validator_output_schema_count": 10,
      "blocking_risk_proof_semantic_validator_output_schema_count": 10,
      "ready_risk_proof_semantic_validator_output_schema_count": 0,
      "registered_risk_proof_semantic_validator_output_schema_count": 0,
      "runtime_observed_risk_proof_semantic_validator_output_schema_count": 4,
      "risk_proof_semantic_validator_registration_count": 10,
      "blocking_risk_proof_semantic_validator_registration_count": 10,
      "ready_risk_proof_semantic_validator_registration_count": 0,
      "registered_risk_proof_semantic_validator_registration_count": 0,
      "runtime_observed_risk_proof_semantic_validator_registration_count": 4,
      "risk_proof_requirements": [
        {
          "proof_kind": "product_scope",
          "sequence": 1,
          "status": "blocked",
          "blocking": true,
          "source": "semantic_guard",
          "semantic_guard": "product_scope",
          "applies_to_fields": ["product_id"],
          "evidence_routes": [
            "/api/v1/futures/account",
            "/api/v1/futures/positions"
          ],
          "required_evidence_refs": [
            "futures_product_scope_readback",
            "futures_command_product_scope_contract"
          ],
          "missing_evidence_refs": [
            "futures_product_scope_readback",
            "futures_command_product_scope_contract"
          ],
          "runtime_evidence_observed": false,
          "semantic_contract_requirement_count": 2,
          "blocking_semantic_contract_requirement_count": 2,
          "registered_semantic_contract_count": 0,
          "runtime_observed_semantic_contract_requirement_count": 0,
          "semantic_contract_definition_count": 2,
          "blocking_semantic_contract_definition_count": 2,
          "ready_semantic_contract_definition_count": 0,
          "registered_semantic_contract_definition_count": 0,
          "runtime_observed_semantic_contract_definition_count": 0,
          "semantic_contract_validation_gate_count": 2,
          "blocking_semantic_contract_validation_gate_count": 2,
          "ready_semantic_contract_validation_gate_count": 0,
          "registered_semantic_contract_validator_count": 0,
          "runtime_observed_semantic_contract_validation_gate_count": 0,
          "semantic_contract_validator_contract_count": 2,
          "blocking_semantic_contract_validator_contract_count": 2,
          "ready_semantic_contract_validator_contract_count": 0,
          "registered_semantic_contract_validator_contract_count": 0,
          "runtime_observed_semantic_contract_validator_contract_count": 0,
          "semantic_contract_requirements": [
            {
              "proof_kind": "product_scope",
              "semantic_guard": "product_scope",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "required_contract_ref": "futures_product_scope_readback",
              "missing_contract_ref": "futures_product_scope_readback",
              "evidence_routes": [
                "/api/v1/futures/account",
                "/api/v1/futures/positions"
              ],
              "runtime_evidence_observed": false,
              "runtime_evidence_satisfies_contract": false,
              "contract_registered": false,
              "acceptance_ready": false,
              "satisfies_risk_proof": false,
              "command_route_registered": true,
              "command_draft_allowed": true,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "semantic_contract_definitions": [
            {
              "proof_kind": "product_scope",
              "semantic_guard": "product_scope",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "source": "backend_contract",
              "contract_ref": "futures_product_scope_readback",
              "semantic_contract_definition_ref": "futures_product_scope_readback_definition",
              "required_backend_contract": "application/admin_api/futures_semantic_contracts.py::futures_product_scope_readback_definition",
              "missing_backend_contract": "application/admin_api/futures_semantic_contracts.py::futures_product_scope_readback_definition",
              "validation_gate": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation",
              "acceptance_gate": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_acceptance",
              "required_evidence_refs": [
                "futures_product_scope_readback",
                "futures_product_scope_readback_definition",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_acceptance"
              ],
              "missing_evidence_refs": [
                "futures_product_scope_readback",
                "futures_product_scope_readback_definition",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_acceptance"
              ],
              "runtime_evidence_observed": false,
              "runtime_evidence_satisfies_definition": false,
              "contract_registered": false,
              "definition_ready": false,
              "validation_ready": false,
              "acceptance_ready": false,
              "satisfies_risk_proof": false,
              "command_route_registered": true,
              "command_draft_allowed": true,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "semantic_contract_validation_gates": [
            {
              "proof_kind": "product_scope",
              "semantic_guard": "product_scope",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "source": "backend_contract",
              "contract_ref": "futures_product_scope_readback",
              "semantic_contract_definition_ref": "futures_product_scope_readback_definition",
              "validation_gate": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation",
              "validation_contract_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator",
              "required_backend_contract": "application/admin_api/futures_semantic_contracts.py::futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator",
              "missing_backend_contract": "application/admin_api/futures_semantic_contracts.py::futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator",
              "validation_input_refs": [
                "futures_product_scope_readback",
                "futures_product_scope_readback_definition",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_acceptance"
              ],
              "required_evidence_refs": [
                "futures_product_scope_readback_definition",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_contextless_review"
              ],
              "missing_evidence_refs": [
                "futures_product_scope_readback_definition",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_contextless_review"
              ],
              "runtime_evidence_observed": false,
              "runtime_evidence_satisfies_validation": false,
              "validator_registered": false,
              "validation_ready": false,
              "definition_ready": false,
              "acceptance_ready": false,
              "satisfies_risk_proof": false,
              "command_route_registered": true,
              "command_draft_allowed": true,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "semantic_contract_validator_contracts": [
            {
              "proof_kind": "product_scope",
              "semantic_guard": "product_scope",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "source": "backend_contract",
              "contract_ref": "futures_product_scope_readback",
              "semantic_contract_definition_ref": "futures_product_scope_readback_definition",
              "validation_gate": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation",
              "validation_contract_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator",
              "validator_contract_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
              "required_backend_contract": "application/admin_api/futures_semantic_contracts.py::futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
              "missing_backend_contract": "application/admin_api/futures_semantic_contracts.py::futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
              "validator_input_schema_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema",
              "validator_output_schema_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema",
              "validator_registration_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration",
              "validation_input_refs": [
                "futures_product_scope_readback",
                "futures_product_scope_readback_definition",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_acceptance"
              ],
              "required_evidence_refs": [
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contextless_review"
              ],
              "missing_evidence_refs": [
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contextless_review"
              ],
              "runtime_evidence_observed": false,
              "runtime_evidence_satisfies_validator_contract": false,
              "validator_contract_registered": false,
              "input_schema_registered": false,
              "output_schema_registered": false,
              "validator_registered": false,
              "validation_ready": false,
              "definition_ready": false,
              "acceptance_ready": false,
              "satisfies_risk_proof": false,
              "command_route_registered": true,
              "command_draft_allowed": true,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "semantic_validator_input_schema_count": 1,
          "blocking_semantic_validator_input_schema_count": 1,
          "ready_semantic_validator_input_schema_count": 0,
          "registered_semantic_validator_input_schema_count": 0,
          "runtime_observed_semantic_validator_input_schema_count": 0,
          "semantic_validator_output_schema_count": 1,
          "blocking_semantic_validator_output_schema_count": 1,
          "ready_semantic_validator_output_schema_count": 0,
          "registered_semantic_validator_output_schema_count": 0,
          "runtime_observed_semantic_validator_output_schema_count": 0,
          "semantic_validator_registration_count": 1,
          "blocking_semantic_validator_registration_count": 1,
          "ready_semantic_validator_registration_count": 0,
          "registered_semantic_validator_registration_count": 0,
          "runtime_observed_semantic_validator_registration_count": 0,
          "semantic_validator_input_schemas": [
            {
              "proof_kind": "product_scope",
              "semantic_guard": "product_scope",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "source": "backend_contract",
              "contract_ref": "futures_product_scope_readback",
              "semantic_contract_definition_ref": "futures_product_scope_readback_definition",
              "validation_gate": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation",
              "validation_contract_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator",
              "validator_contract_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
              "validator_input_schema_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema",
              "required_backend_contract": "application/admin_api/futures_semantic_contracts.py::futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema",
              "missing_backend_contract": "application/admin_api/futures_semantic_contracts.py::futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema",
              "input_schema_field_refs": [
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema.risk_proof_payload",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema.semantic_contract_definition_ref",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema.validation_gate_ref",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema.validator_contract_ref",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema.runtime_evidence_snapshot"
              ],
              "required_evidence_refs": [
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema_field_contracts",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema_schema_registration",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema_contextless_review"
              ],
              "missing_evidence_refs": [
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema_field_contracts",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema_schema_registration",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema_contextless_review"
              ],
              "runtime_evidence_observed": false,
              "runtime_evidence_satisfies_input_schema": false,
              "input_schema_registered": false,
              "validator_contract_registered": false,
              "validator_registered": false,
              "validation_ready": false,
              "definition_ready": false,
              "acceptance_ready": false,
              "satisfies_risk_proof": false,
              "command_route_registered": true,
              "command_draft_allowed": true,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "semantic_validator_output_schemas": [
            {
              "proof_kind": "product_scope",
              "semantic_guard": "product_scope",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "source": "backend_contract",
              "contract_ref": "futures_product_scope_readback",
              "semantic_contract_definition_ref": "futures_product_scope_readback_definition",
              "validation_gate": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation",
              "validation_contract_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator",
              "validator_contract_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
              "validator_output_schema_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema",
              "required_backend_contract": "application/admin_api/futures_semantic_contracts.py::futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema",
              "missing_backend_contract": "application/admin_api/futures_semantic_contracts.py::futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema",
              "output_schema_field_refs": [
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema.validation_result_status",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema.accepted_evidence_refs",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema.missing_evidence_refs",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema.validator_contract_ref",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema.authority_flags"
              ],
              "required_evidence_refs": [
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema_field_contracts",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema_schema_registration",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema_contextless_review"
              ],
              "missing_evidence_refs": [
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema_field_contracts",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema_schema_registration",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema_contextless_review"
              ],
              "runtime_evidence_observed": false,
              "runtime_evidence_satisfies_output_schema": false,
              "output_schema_registered": false,
              "validator_contract_registered": false,
              "validator_registered": false,
              "validation_ready": false,
              "definition_ready": false,
              "acceptance_ready": false,
              "satisfies_risk_proof": false,
              "command_route_registered": true,
              "command_draft_allowed": true,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "semantic_validator_registrations": [
            {
              "proof_kind": "product_scope",
              "semantic_guard": "product_scope",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "source": "backend_contract",
              "contract_ref": "futures_product_scope_readback",
              "semantic_contract_definition_ref": "futures_product_scope_readback_definition",
              "validation_gate": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation",
              "validation_contract_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator",
              "validator_contract_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
              "validator_input_schema_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema",
              "validator_output_schema_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema",
              "validator_registration_ref": "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration",
              "required_backend_contract": "application/admin_api/futures_semantic_contracts.py::futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration",
              "missing_backend_contract": "application/admin_api/futures_semantic_contracts.py::futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration",
              "validator_registration_field_refs": [
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration.validator_contract_ref",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration.validator_input_schema_ref",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration.validator_output_schema_ref",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration.semantic_contract_definition_ref",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration.validation_gate_ref",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration.authority_flags"
              ],
              "required_evidence_refs": [
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration_registry_record",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration_contextless_review"
              ],
              "missing_evidence_refs": [
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_contract",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_input_schema",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_output_schema",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration_registry_record",
                "futures_place_product_scope_futures_product_scope_readback_semantic_contract_validation_validator_registration_contextless_review"
              ],
              "runtime_evidence_observed": false,
              "runtime_evidence_satisfies_validator_registration": false,
              "validator_contract_registered": false,
              "input_schema_registered": false,
              "output_schema_registered": false,
              "validator_registration_ready": false,
              "validator_registered": false,
              "validation_ready": false,
              "definition_ready": false,
              "acceptance_ready": false,
              "satisfies_risk_proof": false,
              "command_route_registered": true,
              "command_draft_allowed": true,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "proof_route_required": true,
          "proof_route_registered": false,
          "proof_writer_enabled": false,
          "proof_contract_count": 2,
          "blocking_proof_contract_count": 2,
          "registered_proof_route_count": 0,
          "enabled_proof_writer_count": 0,
          "proof_contracts": [
            {
              "contract_kind": "proof_route",
              "required_backend_contract": "application/admin_api/futures_proof_routes.py::post_futures_place_product_scope_proof",
              "required_route_path": "/api/v1/futures/proofs/futures_place/product_scope",
              "required_method": "POST",
              "required_evidence_ref": "futures_place_product_scope_proof_route_registered",
              "missing_evidence_ref": "futures_place_product_scope_proof_route_registered",
              "route_registered": false,
              "writer_enabled": false,
              "execution_allowed": false
            },
            {
              "contract_kind": "proof_writer",
              "required_backend_contract": "application/admin_api/futures_proof_writer.py::write_futures_place_product_scope_proof",
              "required_route_path": null,
              "required_method": "LOCAL",
              "required_evidence_ref": "futures_place_product_scope_proof_writer_reviewed",
              "missing_evidence_ref": "futures_place_product_scope_proof_writer_reviewed",
              "route_registered": false,
              "writer_enabled": false,
              "execution_allowed": false
            }
          ],
          "payload_field_count": 10,
          "blocking_payload_field_count": 10,
          "present_payload_field_count": 0,
          "registered_payload_validation_count": 0,
          "payload_fields": [
            {
              "field": "command",
              "payload_path": "proof_payload.command",
              "validation_rule": "Must equal futures_place.",
              "required_evidence_ref": "futures_place_product_scope_payload_command_validated",
              "missing_evidence_ref": "futures_place_product_scope_payload_command_validated",
              "payload_field_present": false,
              "validation_registered": false,
              "execution_allowed": false,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            },
            {
              "field": "identity_key",
              "payload_path": "proof_payload.identity.key",
              "validation_rule": "Must equal product_id.",
              "required_evidence_ref": "futures_place_product_scope_payload_identity_key_validated",
              "missing_evidence_ref": "futures_place_product_scope_payload_identity_key_validated",
              "payload_field_present": false,
              "validation_registered": false,
              "execution_allowed": false,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "record_contract_count": 6,
          "blocking_record_contract_count": 6,
          "registered_record_store_count": 0,
          "registered_record_validation_count": 0,
          "accepted_record_contract_count": 0,
          "record_contracts": [
            {
              "contract_kind": "store_schema",
              "sequence": 1,
              "status": "blocked",
              "required_backend_contract": "application/admin_api/futures_proof_records.py::futures_place_product_scope_store_schema",
              "required_store_ref": "futures_proof_records.futures_place.product_scope",
              "required_record_key": "proof_record.futures_place.product_scope.product_id.idempotency_key.correlation_id",
              "required_payload_fields": [
                "command",
                "proof_kind",
                "identity_key",
                "identity_value",
                "required_evidence_refs",
                "source_snapshot_ref",
                "validation_status",
                "idempotency_key",
                "correlation_id",
                "audit_id"
              ],
              "validation_gate": "futures_place_product_scope_record_store_schema_gate",
              "required_evidence_ref": "futures_place_product_scope_record_store_schema_ready",
              "missing_evidence_ref": "futures_place_product_scope_record_store_schema_ready",
              "store_registered": false,
              "append_only_log_configured": false,
              "idempotency_bound": false,
              "payload_validation_registered": false,
              "replay_guard_registered": false,
              "audit_linked": false,
              "proof_record_accepted": false,
              "execution_allowed": false,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "record_validation_count": 6,
          "blocking_record_validation_count": 6,
          "ready_record_validation_count": 0,
          "record_validations": [
            {
              "contract_kind": "store_schema",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "record_contract_ref": "futures_place.product_scope.record_contract.store_schema",
              "required_backend_contract": "application/admin_api/futures_proof_validation.py::futures_place_product_scope_store_schema_record_validation",
              "required_store_ref": "futures_proof_records.futures_place.product_scope",
              "required_record_key": "proof_record.futures_place.product_scope.product_id.idempotency_key.correlation_id",
              "validation_gate": "futures_place_product_scope_store_schema_record_validation_gate",
              "replay_gate": "futures_place_product_scope_store_schema_replay_gate",
              "required_validation_checks": [
                "record_contract_available",
                "store_schema_registered",
                "append_only_log_configured",
                "idempotency_bound",
                "payload_validation_registered",
                "replay_guard_registered",
                "audit_linked"
              ],
              "required_evidence_ref": "futures_place_product_scope_store_schema_record_validation_ready",
              "missing_evidence_ref": "futures_place_product_scope_store_schema_record_validation_ready",
              "record_contract_available": false,
              "record_validation_registered": false,
              "record_validation_ready": false,
              "proof_record_accepted": false,
              "execution_allowed": false,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "record_validation_remediation_count": 6,
          "blocking_record_validation_remediation_count": 6,
          "ready_record_validation_remediation_count": 0,
          "record_validation_remediations": [
            {
              "contract_kind": "store_schema",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "record_validation_ref": "futures_place.product_scope.record_validation.store_schema",
              "record_contract_ref": "futures_place.product_scope.record_contract.store_schema",
              "remediation_ref": "futures_place.product_scope.record_validation_remediation.store_schema",
              "remediation_gate": "futures_place_product_scope_store_schema_record_validation_remediation_gate",
              "required_backend_contract": "application/admin_api/futures_proof_validation_remediation.py::futures_place_product_scope_store_schema_record_validation_remediation",
              "required_store_ref": "futures_proof_records.futures_place.product_scope",
              "required_record_key": "proof_record.futures_place.product_scope.product_id.idempotency_key.correlation_id",
              "validation_gate": "futures_place_product_scope_store_schema_record_validation_gate",
              "replay_gate": "futures_place_product_scope_store_schema_replay_gate",
              "required_validation_checks": [
                "record_contract_available",
                "store_schema_registered",
                "append_only_log_configured",
                "idempotency_bound",
                "payload_validation_registered",
                "replay_guard_registered",
                "audit_linked"
              ],
              "required_remediation_actions": [
                "register_record_contract",
                "create_store_schema",
                "configure_append_only_log",
                "bind_idempotency",
                "register_payload_validation",
                "register_replay_guard",
                "link_audit_evidence",
                "register_record_validator",
                "run_contextless_review"
              ],
              "required_evidence_refs": [
                "futures_place.product_scope.record_contract.store_schema",
                "application/admin_api/futures_proof_validation.py::futures_place_product_scope_store_schema_record_validation",
                "futures_place_product_scope_store_schema_record_validation_ready"
              ],
              "missing_evidence_refs": [
                "futures_place.product_scope.record_contract.store_schema",
                "application/admin_api/futures_proof_validation.py::futures_place_product_scope_store_schema_record_validation",
                "futures_place_product_scope_store_schema_record_validation_ready"
              ],
              "remediation_work_item_created": false,
              "remediation_owner": "backend_admin_api_owner",
              "record_contract_available": false,
              "store_schema_registered": false,
              "append_only_log_configured": false,
              "idempotency_bound": false,
              "payload_validation_registered": false,
              "replay_guard_registered": false,
              "audit_linked": false,
              "record_validation_registered": false,
              "record_validation_ready": false,
              "remediation_ready": false,
              "remediation_performed": false,
              "proof_record_accepted": false,
              "command_route_registered": true,
              "command_draft_allowed": true,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "record_validation_remediation_dependency_count": 6,
          "blocking_record_validation_remediation_dependency_count": 6,
          "ready_record_validation_remediation_dependency_count": 0,
          "record_validation_remediation_dependencies": [
            {
              "contract_kind": "store_schema",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "record_validation_ref": "futures_place.product_scope.record_validation.store_schema",
              "record_contract_ref": "futures_place.product_scope.record_contract.store_schema",
              "remediation_ref": "futures_place.product_scope.record_validation_remediation.store_schema",
              "remediation_dependency_ref": "futures_place.product_scope.record_validation_remediation_dependency.store_schema",
              "remediation_dependency_gate": "futures_place_product_scope_store_schema_record_validation_remediation_dependency_gate",
              "remediation_gate": "futures_place_product_scope_store_schema_record_validation_remediation_gate",
              "required_backend_contract": "application/admin_api/futures_proof_validation_remediation_dependency.py::futures_place_product_scope_store_schema_record_validation_remediation_dependency",
              "required_store_ref": "futures_proof_records.futures_place.product_scope",
              "required_record_key": "proof_record.futures_place.product_scope.product_id.idempotency_key.correlation_id",
              "validation_gate": "futures_place_product_scope_store_schema_record_validation_gate",
              "replay_gate": "futures_place_product_scope_store_schema_replay_gate",
              "predecessor_remediation_ref": null,
              "successor_remediation_ref": "futures_place.product_scope.record_validation_remediation.append_only_log",
              "predecessor_dependency_ref": null,
              "successor_dependency_ref": "futures_place.product_scope.record_validation_remediation_dependency.append_only_log",
              "dependency_actions": [
                "register_record_contract",
                "create_store_schema",
                "configure_append_only_log",
                "bind_idempotency",
                "register_payload_validation",
                "register_replay_guard",
                "link_audit_evidence",
                "register_record_validator",
                "run_contextless_review"
              ],
              "dependency_blockers": [
                "record_contract_missing",
                "store_schema_missing",
                "append_only_log_missing",
                "idempotency_binding_missing",
                "payload_validation_missing",
                "replay_guard_missing",
                "audit_link_missing",
                "record_validator_missing",
                "contextless_review_missing"
              ],
              "required_evidence_refs": [
                "futures_place.product_scope.record_validation_remediation.store_schema",
                "application/admin_api/futures_proof_validation_remediation.py::futures_place_product_scope_store_schema_record_validation_remediation",
                "futures_place.product_scope.record_contract.store_schema",
                "application/admin_api/futures_proof_validation.py::futures_place_product_scope_store_schema_record_validation",
                "futures_place_product_scope_store_schema_record_validation_ready"
              ],
              "missing_evidence_refs": [
                "application/admin_api/futures_proof_validation_remediation_dependency.py::futures_place_product_scope_store_schema_record_validation_remediation_dependency",
                "futures_place.product_scope.record_contract.store_schema",
                "application/admin_api/futures_proof_validation.py::futures_place_product_scope_store_schema_record_validation",
                "futures_place_product_scope_store_schema_record_validation_ready"
              ],
              "dependency_work_item_created": false,
              "dependency_owner": "backend_admin_api_owner",
              "dependency_ready": false,
              "dependency_resolved": false,
              "dependency_performed": false,
              "remediation_ready": false,
              "remediation_performed": false,
              "record_validation_ready": false,
              "proof_record_accepted": false,
              "command_route_registered": true,
              "command_draft_allowed": true,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "record_validation_remediation_dependency_work_item_count": 6,
          "blocking_record_validation_remediation_dependency_work_item_count": 6,
          "ready_record_validation_remediation_dependency_work_item_count": 0,
          "record_validation_remediation_dependency_work_items": [
            {
              "contract_kind": "store_schema",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "record_validation_ref": "futures_place.product_scope.record_validation.store_schema",
              "record_contract_ref": "futures_place.product_scope.record_contract.store_schema",
              "remediation_ref": "futures_place.product_scope.record_validation_remediation.store_schema",
              "remediation_dependency_ref": "futures_place.product_scope.record_validation_remediation_dependency.store_schema",
              "remediation_dependency_work_item_ref": "futures_place.product_scope.record_validation_remediation_dependency_work_item.store_schema",
              "remediation_dependency_work_item_gate": "futures_place_product_scope_store_schema_record_validation_remediation_dependency_work_item_gate",
              "required_backend_contract": "application/admin_api/futures_proof_validation_remediation_dependency_work_item.py::futures_place_product_scope_store_schema_record_validation_remediation_dependency_work_item",
              "required_dependency_contract": "application/admin_api/futures_proof_validation_remediation_dependency.py::futures_place_product_scope_store_schema_record_validation_remediation_dependency",
              "required_work_item_store_ref": "admin_futures_remediation_dependency_work_items.futures_place.product_scope",
              "predecessor_dependency_work_item_refs": [],
              "successor_dependency_work_item_refs": [
                "futures_place.product_scope.record_validation_remediation_dependency_work_item.append_only_log"
              ],
              "work_item_actions": [
                "register_record_contract",
                "create_store_schema",
                "configure_append_only_log",
                "bind_idempotency",
                "register_payload_validation",
                "register_replay_guard",
                "link_audit_evidence",
                "register_record_validator",
                "run_contextless_review"
              ],
              "work_item_blockers": [
                "dependency_not_ready",
                "dependency_unresolved",
                "work_item_store_missing",
                "claim_ledger_missing",
                "owner_review_missing",
                "contextless_review_missing"
              ],
              "work_item_created": false,
              "work_item_claimed": false,
              "claim_ledger_registered": false,
              "dependency_ready": false,
              "dependency_resolved": false,
              "dependency_performed": false,
              "remediation_ready": false,
              "remediation_performed": false,
              "record_validation_ready": false,
              "proof_record_accepted": false,
              "command_route_registered": true,
              "command_draft_allowed": true,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "record_validation_remediation_dependency_work_item_claim_trace_count": 6,
          "blocking_record_validation_remediation_dependency_work_item_claim_trace_count": 6,
          "ready_record_validation_remediation_dependency_work_item_claim_trace_count": 0,
          "record_validation_remediation_dependency_work_item_claim_traces": [
            {
              "contract_kind": "store_schema",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "record_validation_ref": "futures_place.product_scope.record_validation.store_schema",
              "record_contract_ref": "futures_place.product_scope.record_contract.store_schema",
              "remediation_ref": "futures_place.product_scope.record_validation_remediation.store_schema",
              "remediation_dependency_ref": "futures_place.product_scope.record_validation_remediation_dependency.store_schema",
              "remediation_dependency_work_item_ref": "futures_place.product_scope.record_validation_remediation_dependency_work_item.store_schema",
              "remediation_dependency_work_item_claim_trace_ref": "futures_place.product_scope.record_validation_remediation_dependency_work_item_claim_trace.store_schema",
              "remediation_dependency_work_item_claim_trace_gate": "futures_place_product_scope_store_schema_record_validation_remediation_dependency_work_item_claim_trace_gate",
              "required_backend_contract": "application/admin_api/futures_proof_validation_remediation_dependency_work_item_claim_trace.py::futures_place_product_scope_store_schema_record_validation_remediation_dependency_work_item_claim_trace",
              "required_work_item_contract": "application/admin_api/futures_proof_validation_remediation_dependency_work_item.py::futures_place_product_scope_store_schema_record_validation_remediation_dependency_work_item",
              "required_claim_trace_store_ref": "admin_futures_remediation_dependency_work_item_claim_traces.futures_place.product_scope",
              "required_work_item_store_ref": "admin_futures_remediation_dependency_work_items.futures_place.product_scope",
              "claim_trace_claim": "work_item_availability_claim",
              "claim_trace_target_ref": "futures_place.product_scope.record_validation_remediation_dependency_work_item.store_schema",
              "claim_trace_source_ref": "application/admin_api/futures_proof_validation_remediation_dependency_work_item.py::futures_place_product_scope_store_schema_record_validation_remediation_dependency_work_item",
              "predecessor_claim_trace_refs": [],
              "successor_claim_trace_refs": [
                "futures_place.product_scope.record_validation_remediation_dependency_work_item_claim_trace.append_only_log"
              ],
              "claim_trace_blockers": [
                "work_item_not_created",
                "work_item_not_claimed",
                "claim_ledger_missing",
                "claim_trace_store_missing",
                "dependency_not_ready",
                "dependency_unresolved",
                "claim_review_missing",
                "contextless_review_missing"
              ],
              "claim_trace_created": false,
              "claim_trace_ready": false,
              "claim_allowed": false,
              "claim_resolved": false,
              "work_item_created": false,
              "work_item_claimed": false,
              "claim_ledger_registered": false,
              "dependency_ready": false,
              "dependency_resolved": false,
              "dependency_performed": false,
              "remediation_ready": false,
              "remediation_performed": false,
              "record_validation_ready": false,
              "proof_record_accepted": false,
              "command_route_registered": true,
              "command_draft_allowed": true,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 432,
          "blocking_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 432,
          "ready_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 0,
          "completed_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_count": 0,
          "record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 864,
          "blocking_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 864,
          "present_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 0,
          "accepted_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_count": 0,
          "acceptance_criterion_count": 5,
          "blocking_acceptance_criterion_count": 5,
          "accepted_acceptance_criterion_count": 0,
          "proof_acceptance_blocked": true,
          "proof_acceptance_blocker_count": 6,
          "proof_acceptance_blockers": [
            "futures_semantic_contracts_missing",
            "proof_record_not_accepted",
            "acceptance_criteria_blocking",
            "command_route_missing",
            "command_draft_disabled",
            "live_execution_disabled"
          ],
          "proof_acceptance_blocker_refs": [
            "futures_place_product_scope_futures_semantic_contracts",
            "futures_place_product_scope_proof_record_acceptance",
            "futures_place_product_scope_acceptance_criteria",
            "futures_place_command_route",
            "futures_place_command_draft",
            "futures_place_live_execution"
          ],
          "proof_acceptance_blocker_authority": "backend_futures_semantics_no_execution",
          "proof_record_resolves_acceptance": false,
          "acceptance_criteria": [
            {
              "check": "required_evidence_present",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "required_evidence_ref": "futures_product_scope_readback",
              "missing_evidence_ref": "futures_product_scope_readback",
              "negative_check": false,
              "accepted": false,
              "satisfies_risk_proof": false,
              "command_route_registered": true,
              "command_draft_allowed": true,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            },
            {
              "check": "proof_route_registered",
              "sequence": 2,
              "status": "blocked",
              "blocking": true,
              "required_evidence_ref": "futures_place_product_scope_proof_route_registered",
              "missing_evidence_ref": "futures_place_product_scope_proof_route_registered",
              "negative_check": false,
              "accepted": false,
              "satisfies_risk_proof": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false
            },
            {
              "check": "proof_writer_reviewed",
              "sequence": 3,
              "status": "blocked",
              "blocking": true,
              "required_evidence_ref": "futures_place_product_scope_proof_writer_reviewed",
              "missing_evidence_ref": "futures_place_product_scope_proof_writer_reviewed",
              "negative_check": false,
              "accepted": false,
              "satisfies_risk_proof": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false
            },
            {
              "check": "spot_rule_boundary_reviewed",
              "sequence": 4,
              "status": "blocked",
              "blocking": true,
              "required_evidence_ref": "futures_place_product_scope_spot_rule_boundary_reviewed",
              "missing_evidence_ref": "futures_place_product_scope_spot_rule_boundary_reviewed",
              "negative_check": true,
              "accepted": false,
              "satisfies_risk_proof": false,
              "spot_rule_authority": false
            },
            {
              "check": "browser_bff_authority_reviewed",
              "sequence": 5,
              "status": "blocked",
              "blocking": true,
              "required_evidence_ref": "futures_place_product_scope_browser_bff_authority_reviewed",
              "missing_evidence_ref": "futures_place_product_scope_browser_bff_authority_reviewed",
              "negative_check": true,
              "accepted": false,
              "satisfies_risk_proof": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "all_acceptance_criteria_accepted": false,
          "satisfies_risk_proof": false,
          "backend_owned": true,
          "read_only": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution"
        },
        {
          "proof_kind": "margin_collateral",
          "sequence": 2,
          "status": "blocked",
          "blocking": true,
          "source": "semantic_guard",
          "semantic_guard": "margin_collateral",
          "applies_to_fields": ["margin_mode", "leverage"],
          "evidence_routes": [
            "/api/v1/futures/account",
            "/api/v1/admin/cap-guard/decisions"
          ],
          "required_evidence_refs": [
            "futures_margin_collateral_risk_contract",
            "futures_cap_guard_margin_collateral_link"
          ],
          "missing_evidence_refs": [
            "futures_margin_collateral_risk_contract",
            "futures_cap_guard_margin_collateral_link"
          ],
          "runtime_evidence_observed": true,
          "semantic_contract_requirement_count": 2,
          "blocking_semantic_contract_requirement_count": 2,
          "registered_semantic_contract_count": 0,
          "runtime_observed_semantic_contract_requirement_count": 2,
          "semantic_contract_requirements": [
            {
              "proof_kind": "margin_collateral",
              "semantic_guard": "margin_collateral",
              "sequence": 1,
              "status": "blocked",
              "blocking": true,
              "required_contract_ref": "futures_margin_collateral_risk_contract",
              "missing_contract_ref": "futures_margin_collateral_risk_contract",
              "evidence_routes": [
                "/api/v1/futures/account",
                "/api/v1/admin/cap-guard/decisions"
              ],
              "runtime_evidence_observed": true,
              "runtime_evidence_satisfies_contract": false,
              "contract_registered": false,
              "acceptance_ready": false,
              "satisfies_risk_proof": false,
              "command_route_registered": true,
              "command_draft_allowed": true,
              "execution_allowed": false,
              "proof_route_registered": false,
              "proof_writer_enabled": false,
              "backend_owned": true,
              "read_only": true,
              "spot_rule_authority": false,
              "browser_authority": "display_only",
              "bff_authority": "forward_only_no_execution"
            }
          ],
          "proof_route_required": true,
          "proof_route_registered": false,
          "proof_writer_enabled": false,
          "backend_owned": true,
          "read_only": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution"
        },
        {
          "proof_kind": "reconciliation_plan",
          "sequence": 6,
          "status": "blocked",
          "blocking": true,
          "source": "semantic_guard",
          "semantic_guard": "reconciliation_plan",
          "applies_to_fields": ["client_order_id"],
          "evidence_routes": ["/api/v1/admin/reconciliation/plans"],
          "required_evidence_refs": [
            "futures_reconciliation_plan_contract"
          ],
          "missing_evidence_refs": [
            "futures_reconciliation_plan_contract"
          ],
          "runtime_evidence_observed": false,
          "proof_route_required": true,
          "proof_route_registered": false,
          "proof_writer_enabled": false,
          "backend_owned": true,
          "read_only": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution"
        }
      ],
      "command_route_registered": true,
      "command_draft_allowed": true,
      "execution_allowed": false
    },
    {
      "command": "futures_close_reduce",
      "status": "blocked",
      "action_class": "live_exchange_cancel",
      "route": "/api/v1/futures/positions/{position_key}/close-reduce",
      "service_method": "close_or_reduce_futures_position",
      "identity_key": "position_key",
      "required_backend_contracts": [
        "application/admin_api/futures_command_service.py::close_or_reduce_futures_position",
        "application/admin_api/futures_risk_guard.py::evaluate_futures_margin_collateral_liquidation",
        "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan",
        "api/v1/routes/futures.py::futures_close_reduce_route_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_adapter_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_adapter_construction_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_adapter_decision_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_adapter_decision_record_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_adapter_invocation_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_adapter_execution_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_coinbase_exchange_submission_contract",
        "application/admin_api/live_execution.py::futures_close_reduce_post_exchange_submission_reconciliation_contract"
      ],
      "missing_backend_contracts": [],
      "readiness_decision": {
        "decision": "blocked_backend_contracts_required",
        "status": "blocked",
        "blocker_count": 29,
        "missing_backend_contract_count": 0,
        "next_required_backend_contract": null,
        "command_route_registered": true,
        "command_draft_allowed": true,
        "execution_allowed": false
      },
      "readiness_closure_step_count": 6,
      "blocking_readiness_closure_step_count": 6,
      "readiness_closure_steps": [
        {
          "step": "run_contextless_review_gate",
          "sequence": 6,
          "status": "blocked",
          "execution_allowed": false,
          "proof_writer_enabled": false,
          "spot_rule_authority": false
        }
      ],
      "command_route_registered": true,
      "command_draft_allowed": true,
      "execution_allowed": false
    },
    {
      "command": "futures_cancel",
      "status": "blocked",
      "action_class": "live_exchange_cancel",
      "route": "/api/v1/futures/orders/{client_order_id}/cancel",
      "service_method": "cancel_futures_order",
      "identity_key": "client_order_id",
      "required_backend_contracts": [
        "application/admin_api/futures_command_service.py::cancel_futures_order",
        "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan",
        "api/v1/routes/futures.py::futures_cancel_route_contract",
        "application/admin_api/live_execution.py::futures_cancel_adapter_contract",
        "application/admin_api/live_execution.py::futures_cancel_adapter_construction_contract",
        "application/admin_api/live_execution.py::futures_cancel_adapter_decision_contract",
        "application/admin_api/live_execution.py::futures_cancel_adapter_decision_record_contract",
        "application/admin_api/live_execution.py::futures_cancel_adapter_invocation_contract",
        "application/admin_api/live_execution.py::futures_cancel_adapter_execution_contract",
        "application/admin_api/live_execution.py::futures_cancel_coinbase_exchange_submission_contract",
        "application/admin_api/live_execution.py::futures_cancel_post_exchange_submission_reconciliation_contract"
      ],
      "missing_backend_contracts": [],
      "semantic_guard_count": 5,
      "blocking_semantic_guard_count": 5,
      "risk_semantic_guard_count": 0,
      "request_fields": [
        {
          "field": "client_order_id",
          "status": "blocked",
          "identity_field": true,
          "detail": "Futures cancel must call the project wrapper with client_order_id; exchange order_id is exchange evidence only."
        },
        {
          "field": "product_id",
          "status": "blocked",
          "identity_field": false
        },
        {
          "field": "operator_notes",
          "status": "blocked",
          "identity_field": false
        }
      ],
      "semantic_guards": [
        {
          "semantic_guard": "idempotency",
          "status": "blocked",
          "identity_semantic": true,
          "detail": "Futures cancel must call cancel_order with client_order_id; exchange order_id is exchange evidence only."
        },
        {
          "semantic_guard": "admission_audit",
          "status": "blocked",
          "audit_semantic": true,
          "spot_rule_authority": false
        }
      ],
      "readiness_decision": {
        "decision": "blocked_backend_contracts_required",
        "status": "blocked",
        "blocker_count": 15,
        "missing_backend_contract_count": 0,
        "next_required_backend_contract": null,
        "command_route_registered": true,
        "command_draft_allowed": true,
        "execution_allowed": false
      },
      "readiness_closure_step_count": 6,
      "blocking_readiness_closure_step_count": 6,
      "readiness_closure_steps": [
        {
          "step": "run_contextless_review_gate",
          "sequence": 6,
          "status": "blocked",
          "execution_allowed": false,
          "proof_writer_enabled": false,
          "spot_rule_authority": false
        }
      ],
      "command_route_registered": true,
      "command_draft_allowed": true,
      "execution_allowed": false
    },
    {
      "command": "futures_reconcile",
      "status": "blocked",
      "action_class": "local_state_mutation",
      "route": "/api/v1/futures/positions/{position_key}/reconciliation",
      "service_method": "reconcile_futures_position",
      "identity_key": "position_key",
      "required_backend_contracts": [
        "application/admin_api/futures_command_service.py::reconcile_futures_position",
        "application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan",
        "application/admin_api/futures_risk_guard.py::evaluate_futures_margin_collateral_liquidation",
        "api/v1/routes/futures.py::futures_reconcile_route_contract",
        "application/admin_api/live_execution.py::futures_reconcile_adapter_contract",
        "application/admin_api/live_execution.py::futures_reconcile_adapter_construction_contract",
        "application/admin_api/live_execution.py::futures_reconcile_adapter_decision_contract",
        "application/admin_api/live_execution.py::futures_reconcile_adapter_decision_record_contract",
        "application/admin_api/live_execution.py::futures_reconcile_adapter_invocation_contract",
        "application/admin_api/live_execution.py::futures_reconcile_adapter_execution_contract",
        "application/admin_api/live_execution.py::futures_reconcile_coinbase_exchange_submission_contract",
        "application/admin_api/live_execution.py::futures_reconcile_post_exchange_submission_reconciliation_contract"
      ],
      "missing_backend_contracts": [],
      "readiness_decision": {
        "decision": "blocked_backend_contracts_required",
        "status": "blocked",
        "blocker_count": 22,
        "missing_backend_contract_count": 0,
        "next_required_backend_contract": null,
        "command_route_registered": true,
        "command_draft_allowed": true,
        "execution_allowed": false
      },
      "readiness_closure_step_count": 6,
      "blocking_readiness_closure_step_count": 6,
      "readiness_closure_steps": [
        {
          "step": "run_contextless_review_gate",
          "sequence": 6,
          "status": "blocked",
          "execution_allowed": false,
          "proof_writer_enabled": false,
          "spot_rule_authority": false
        }
      ],
      "command_route_registered": true,
      "command_draft_allowed": true,
      "execution_allowed": false
    }
  ],
  "spot_rule_authority": false,
  "browser_authority": "display_only",
  "bff_authority": "forward_only_no_execution",
  "live_coinbase_orders_ran": false,
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0"
}
```

Spot wallet, no-shorting, USDC, cost-basis, and inventory-lot rules are forbidden
as futures/perpetual command authority. Readiness decisions report blocker
counts and the next missing backend contract. Route/draft flags are true for
the four draft routes, but commands remain non-executable while
`execution_allowed=false`.

## Account Evidence

```http
GET /api/v1/futures/account
Authorization: Bearer local-admin-token
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected response posture:

```json
{
  "type": "admin_futures_account",
  "configured_product_scope": ["BIP-20DEC30-CDE"],
  "observed_position_scope": ["BIP-20DEC30-CDE"],
  "collateral": {
    "name": "collateral",
    "status": "unavailable",
    "source": "runtime_unavailable"
  },
  "margin": {
    "name": "margin",
    "status": "observed",
    "source": "fee_manager",
    "value": {"margin_window_type": "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT"}
  },
  "funding": {
    "name": "funding",
    "status": "not_modeled",
    "source": "backend_contract"
  },
  "liquidation": {
    "name": "liquidation",
    "status": "unavailable",
    "source": "runtime_unavailable"
  },
  "reduce_only_close_only": {
    "name": "reduce_only_close_only",
    "status": "observed",
    "source": "position_side_derivation"
  },
  "position_pnl": {
    "name": "position_pnl",
    "status": "observed",
    "source": "runtime_positions"
  },
  "position_count": 1,
  "read_only": true,
  "command_routes_mode": "not_modeled",
  "live_coinbase_orders_ran": false
}
```

## Position List

```http
GET /api/v1/futures/positions?product_id=BIP-20DEC30-CDE&position_side=LONG&limit=50&offset=0
Authorization: Bearer local-admin-token
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Rows are keyed by `position_key`:

```json
{
  "type": "admin_futures_positions",
  "filters": {
    "product_id": "BIP-20DEC30-CDE",
    "position_side": "LONG",
    "limit": 50,
    "offset": 0
  },
  "count": 1,
  "pagination": {
    "limit": 50,
    "offset": 0,
    "returned_count": 1,
    "total_matching_count": 1,
    "next_offset": null,
    "has_more": false
  },
  "items": [
    {
      "position_key": "futures_position:runtime:BIP-20DEC30-CDE",
      "product_id": "BIP-20DEC30-CDE",
      "product_type": "FUTURE",
      "position_side": "LONG",
      "close_order_side": "SELL",
      "source": "runtime_orderbook"
    }
  ],
  "read_only": true,
  "command_routes_mode": "not_modeled",
  "live_coinbase_orders_ran": false
}
```

## Position Detail

```http
GET /api/v1/futures/positions/futures_position%3Aruntime%3ABIP-20DEC30-CDE
Authorization: Bearer local-admin-token
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

The path uses `position_key`. Do not replace it with `client_order_id` or
Coinbase `order_id`.

## Risk-Proof Records

List persisted local futures risk-proof evidence:

```http
GET /api/v1/futures/risk-proofs?command=futures_place&proof_kind=product_scope&limit=20
Authorization: Bearer local-admin-token
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Detail readbacks use the backend proof id:

```http
GET /api/v1/futures/risk-proofs/futures-risk-proof-001
Authorization: Bearer local-admin-token
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Record append-only local proof evidence only:

```http
POST /api/v1/futures/risk-proofs
Authorization: Bearer local-admin-token
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
Idempotency-Key: idem-futures-risk-proof
X-Correlation-Id: corr-futures-risk-proof
Content-Type: application/json

{
  "command": "futures_place",
  "proof_kind": "margin_collateral",
  "proof_contract_ref": "futures_place.margin_collateral.proof_contract",
  "evidence_source": "test_evidence",
  "evidence_ref": "tests/regression/test_admin_api_futures_risk_proofs.py",
  "risk_evidence_refs": [
    "futures.account.margin",
    "futures.account.collateral"
  ],
  "product_id": "BIT-20DEC30-CDE",
  "approval_snapshot_id": "approval-snapshot-futures-risk-proof-001",
  "admission_audit_id": "admission-audit-futures-risk-proof-001",
  "cap_guard_decision_id": "cap-guard-futures-risk-proof-001",
  "reconciliation_plan_id": "reconciliation-plan-futures-risk-proof-001",
  "dry_run": true,
  "operator_reason": "Record local proof evidence for M57 contract review.",
  "manual_live_acknowledgement": false
}
```

The accepted response is a backend command response with
`live_exchange_submitted=false`, `submitted_notional_usdc="0"`, and
`executed_notional_usdc="0"`. It persists proof evidence only; it does not
accept proof requirements, make route-bound futures command drafts executable,
execute reconciliation, call Coinbase, mutate futures/order/exchange state, or
grant browser/BFF authority.

## Operator Rules

- Treat `configured_product_scope` as configured metadata coverage.
- Treat `observed_position_scope` as observed runtime position coverage.
- Treat close/reduce sides as backend-derived from position side, not as
  exchange-observed order flags.
- Treat `funding.status="not_modeled"` as unsupported until the backend
  contract is extended.
- Live Coinbase execution for these examples: not run; notional `$0`.

## Completed Validation Record Example Evidence

The completed 6521-6540 range reports futures request payload validation evidence
record contract evidence in `GET /api/v1/futures/command-suite`. This carries
forward completed futures request payload validation evidence and adds disabled
validation-record contract rows.
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
The validation evidence registry is
`application/admin_api/futures_request_payload_validation_evidence.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS`, and
`iter_futures_request_payload_validation_evidence`; the validation-record
registry is
`application/admin_api/futures_request_payload_validation_evidence_records.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS`, and
`iter_futures_request_payload_validation_evidence_records`. These rows remain
blocked, backend-owned, read-only, display-only, and no-live. Completed
registration evidence remains available through
`application/admin_api/futures_request_payload_validator_registrations.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS`, and
`iter_futures_request_payload_validator_registrations`; completed output-schema
evidence remains available through
`application/admin_api/futures_request_payload_validator_output_schemas.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS`, and
`iter_futures_request_payload_validator_output_schemas`.
