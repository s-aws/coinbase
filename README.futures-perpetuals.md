# Futures/Perpetuals Admin Reads

This feature exposes read-only futures and perpetual account, risk, and
position evidence through the enterprise Admin API. It is a separate module,
not a Spot variant.

## When To Use

Use these routes when an operator or admin frontend needs to inspect futures
or perpetual state without creating, closing, moving, or cancelling exchange
orders.

Current routes:

- `GET /api/v1/futures/command-suite`
- `GET /api/v1/futures/account`
- `GET /api/v1/futures/positions`
- `GET /api/v1/futures/positions/{position_key}`
- `GET /api/v1/futures/risk-proofs`
- `GET /api/v1/futures/risk-proofs/{futures_risk_proof_id}`
- `POST /api/v1/futures/orders`
- `POST /api/v1/futures/positions/{position_key}/close-reduce`
- `POST /api/v1/futures/orders/{client_order_id}/cancel`
- `POST /api/v1/futures/positions/{position_key}/reconciliation`
- `POST /api/v1/futures/risk-proofs`

Read routes require Admin API auth/RBAC and `analytics:read`. The
`POST /api/v1/futures/risk-proofs` route requires
`futures_risk_proof:record`, idempotency, approval, cap/guard, and audit
evidence through the shared Admin API command service. It persists
append-only local proof evidence only; it does not verify the proof
requirement, satisfy command readiness, call Coinbase, execute reconciliation,
mutate futures/order/exchange state, or grant browser/BFF authority. Account
and position routes return
`read_only=true`, `command_routes_mode="not_modeled"`, and
`live_coinbase_orders_ran=false`; the command-suite route exposes the same
blocked/no-live posture through route-bound draft, execution, browser, BFF,
and notional evidence fields.

## Key Concepts

- `position_key` is the read identity for positions. It is not
  `client_order_id`, and it is not Coinbase `order_id`.
- `configured_product_scope` lists futures/perpetual products known from
  backend metadata.
- `observed_position_scope` lists products with observed runtime position
  evidence.
- Collateral, margin, funding, liquidation, reduce/close-side, and P/L values
  are evidence cells with explicit `status` and `source`.
- Close/reduce order sides are backend-derived from observed position side.
  They are not exchange-observed reduce-only or close-only order flags.
- `GET /api/v1/futures/command-suite` reports blocked M57 command-contract
  evidence for placement, close/reduce, cancel, and reconciliation. It now
  registers route-bound no-live command drafts for those four families, but
  does not call Coinbase, execute reconciliation, mutate state, or grant
  browser/BFF authority.
- Active M57 `7561-7580` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store record-validation check output schema field-constraint
  source-ref evidence while completed M57 `7541-7560` carries forward futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation check output schema field-constraint evidence.

Exact active M57 phrase: Active M57 `7561-7580` evidence adds futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance-step review input store record-validation check output schema field-constraint source-ref evidence while completed M57 `7541-7560` carries forward futures request payload validation record execution-eligibility resolution-plan step review input store record-validation check output schema field-constraint evidence.
- Completed M57 `7541-7560` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store record-validation check output schema field-constraint
  evidence while completed M57 `7521-7540` carries forward futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation check output schema field-type evidence.
- Completed M57 `7521-7540` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store record-validation check output schema field-type evidence while
  completed M57 `7501-7520` carries forward futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation check output schema field-name evidence.
- Completed M57 `7501-7520` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store record-validation check output schema field-name evidence while
  completed M57 `7481-7500` carries forward futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation check output schema field evidence.
- Completed M57 `7481-7500` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store record-validation check output schema field evidence while
  completed M57 `7461-7480` carries forward futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation check output schema evidence.
- Completed M57 `7461-7480` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store record-validation check output schema evidence while
  completed M57 `7441-7460` carries forward futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation check input schema field evidence.
- Completed M57 `7441-7460` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store record-validation check input schema field evidence while
  completed M57 `7421-7440` carries forward futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation check input schema evidence.
- Completed M57 `7421-7440` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store record-validation check input schema evidence while
  completed M57 `7401-7420` carries forward futures request payload validation record
  execution-eligibility resolution-plan step review input store
  record-validation check contract evidence.
- Completed M57 `7401-7420` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store record-validation check contract evidence while completed
  M57 `7381-7400` carries forward futures request payload validation record
  execution-eligibility resolution-plan step review input store
  record-validation check evidence.
- Completed M57 `7381-7400` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store record-validation check evidence while completed M57
  `7361-7380` carries forward futures request payload validation record
  execution-eligibility resolution-plan step review input store
  record-validation evidence.
- Completed M57 `7361-7380` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store record-validation evidence while completed M57 `7341-7360`
  carries forward futures request payload validation record execution-eligibility
  resolution-plan step review input store record-validation remediation
  dependency work-item claim-trace clearance-step review input store
  record-contract evidence.
- Completed M57 `7341-7360` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store record-contract evidence while completed M57 `7321-7340`
  carries forward futures request payload validation record
  execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store requirement evidence.
- Completed M57 `7321-7340` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store requirement evidence while completed M57 `7301-7320`
  carries forward futures request payload validation record
  execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input evidence.
- Completed M57 `7301-7320` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review input evidence while completed M57 `7281-7300` carries forward futures
  request payload validation record execution-eligibility resolution-plan step
  review input store record-validation remediation dependency work-item
  claim-trace clearance-step review evidence.
- Completed M57 `7281-7300` evidence adds futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency work-item claim-trace clearance-step
  review evidence while completed M57 `7261-7280` carries forward futures request
  payload validation record execution-eligibility resolution-plan step review
  input store record-validation remediation dependency work-item claim-trace
  clearance step evidence, completed M57 `7241-7260` carries forward futures request
  payload validation record execution-eligibility resolution-plan step review
  input store record-validation remediation dependency work-item claim-trace
  clearance plan evidence, completed M57 `7221-7240` carries forward futures request
  payload validation record execution-eligibility resolution-plan step review
  input store record-validation remediation dependency work-item claim trace
  evidence, completed M57 `7201-7220` carries forward futures request payload
  validation record execution-eligibility resolution-plan step review input
  store record-validation remediation dependency work-item evidence, and
  completed M57 `7181-7200` carries forward futures request payload validation
  record execution-eligibility resolution-plan step review input store
  record-validation remediation dependency evidence, completed M57
  `7161-7180` carries forward futures request payload validation record
  execution-eligibility resolution-plan step review input store
  record-validation remediation evidence, completed M57 `7141-7160` carries
  forward futures request payload validation record execution-eligibility
  resolution-plan step review input store record-validation evidence, completed
  M57 `7121-7140` carries forward
  futures request payload validation record execution-eligibility
  resolution-plan step review input store record-contract evidence, completed
  M57 `7101-7120` carries forward
  futures request payload validation record execution-eligibility
  resolution-plan step review input store requirement evidence, completed M57
  `7081-7100` carries forward futures request payload validation record
  execution-eligibility resolution-plan step review input evidence, completed
  M57 `7061-7080` carries forward futures
  request payload validation record execution-eligibility resolution-plan step
  review evidence, completed
  M57 `7041-7060` carries forward futures request payload validation record
  execution-eligibility resolution-plan step evidence, completed M57
  `7021-7040` carries forward futures request payload validation record
  execution-eligibility resolution-plan evidence, completed M57 `7001-7020`
  carries forward futures request payload validation record
  execution-eligibility semantic closure evidence, completed M57 `6981-7000`
  carries forward disabled futures request payload validation record
  reconciliation semantics, completed M57 `6961-6980` carries forward
  disabled futures request payload validation record cancel semantics, completed
  M57 `6941-6960` carries forward disabled futures request
  payload validation record order semantics, and completed M57 `6921-6940`
  carries forward disabled futures
  request payload validation record funding
  semantics, completed M57 `6881-6900` carries forward disabled futures request
  payload validation record reduce-only semantics, completed M57 `6861-6880`
  carries forward disabled futures request payload validation record liquidation
  semantics, completed M57 `6841-6860` carries forward disabled futures request
  payload validation record collateral semantics, completed M57 `6821-6840` carries forward disabled futures
  request payload validation record margin semantics, and completed M57
  `6801-6820` carries forward disabled futures
  request payload validation record position semantics.
- The command-suite route also exposes request-field contract metadata for
  each planned command family. These fields are blocked backend contract
  evidence only; they are not accepted payloads and do not create executable
  routes.
- The command-suite route also exposes request-payload validation record
  execution-eligibility evidence through
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_CONTRACTS`,
  `iter_futures_request_payload_validation_record_execution_eligibilities`,
  `request_payload_validation_record_execution_eligibility_count`,
  `blocking_request_payload_validation_record_execution_eligibility_count`,
  `ready_request_payload_validation_record_execution_eligibility_count`,
  `execution_eligible_request_payload_validation_record_count`,
  `runtime_observed_request_payload_validation_record_execution_eligibility_count`,
  and `request_payload_validation_record_execution_eligibilities`. Rows expose
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
  `validation_record_execution_eligibility_field_count`,
  `runtime_evidence_satisfies_validation_record_execution_eligibility=false`,
  `validation_record_execution_eligibility_contract_ready=false`, and
  `validation_record_execution_eligible=false`. Semantic flags remain
  validation_record_position_semantics_ready=false,
  validation_record_margin_semantics_ready=false,
  validation_record_collateral_semantics_ready=false,
  validation_record_liquidation_semantics_ready=false,
  validation_record_reduce_only_semantics_ready=false,
  validation_record_close_only_semantics_ready=false,
  validation_record_funding_semantics_ready=false,
  validation_record_order_semantics_ready=false,
  validation_record_cancel_semantics_ready=false, and
  validation_record_reconciliation_semantics_ready=false. Semantic contract
  rows are present as disabled evidence through
  validation_record_semantic_contracts_present=true, but
  validation_record_semantic_contracts_ready=false. This evidence is disabled
  and does not make admitted futures/perpetual validation records executable,
  encode futures position/margin/collateral/liquidation/reduce-only/close-only/
  funding/order/cancel/reconciliation semantics, call Coinbase, mutate futures
  state, or grant browser/BFF or spot-rule authority.
- The command-suite route also exposes request-payload validation record
  semantic artifact definition review evidence through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_definition_reviews.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_CONTRACTS`,
  `iter_futures_request_payload_validation_record_semantic_artifact_definition_reviews`,
  `request_payload_validation_record_semantic_artifact_definition_review_count`,
  `blocking_request_payload_validation_record_semantic_artifact_definition_review_count`,
  `ready_request_payload_validation_record_semantic_artifact_definition_review_count`,
  `runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_count`,
  and `request_payload_validation_record_semantic_artifact_definition_reviews`.
  Rows expose `semantic_artifact_definition_review_ref`,
  `semantic_artifact_definition_review_contract_ref`,
  `semantic_artifact_definition_review_input_ref`,
  `semantic_artifact_definition_review_output_ref`,
  `semantic_artifact_definition_ref`,
  `semantic_artifact_definition_contract_ref`,
  `contextless_review_required=true`,
  `semantic_artifact_definition_available=false`,
  `semantic_artifact_definition_review_available=false`,
  `semantic_artifact_definition_reviewed=false`,
  `semantic_artifact_definition_review_passed=false`,
  `semantic_artifact_runtime_evidence_bound=false`,
  `semantic_artifact_defined=false`, `semantic_artifact_reviewed=false`,
  `runtime_evidence_satisfies_semantic_artifact_definition=false`, and
  `execution_eligibility_blocker_resolved=false`. Completed M57 `6701-6720`
  carries forward disabled futures request payload validation record semantic
  artifact definition review input evidence through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_definition_review_inputs.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS`,
  `iter_futures_request_payload_validation_record_semantic_artifact_definition_review_inputs`,
  `request_payload_validation_record_semantic_artifact_definition_review_input_count`,
  `blocking_request_payload_validation_record_semantic_artifact_definition_review_input_count`,
  `ready_request_payload_validation_record_semantic_artifact_definition_review_input_count`,
  `runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_input_count`,
  and `request_payload_validation_record_semantic_artifact_definition_review_inputs`.
  Rows expose `semantic_artifact_definition_review_input_contract_ref`,
  `semantic_artifact_definition_review_input_available=false`, and
  `semantic_artifact_definition_review_input_accepted=false`. Completed M57
  `6721-6740` carries forward disabled futures request payload validation
  record semantic artifact definition review output evidence through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_definition_review_outputs.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_CONTRACTS`,
  `iter_futures_request_payload_validation_record_semantic_artifact_definition_review_outputs`,
  `request_payload_validation_record_semantic_artifact_definition_review_output_count`,
  `blocking_request_payload_validation_record_semantic_artifact_definition_review_output_count`,
  `ready_request_payload_validation_record_semantic_artifact_definition_review_output_count`,
  `runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_count`,
  and `request_payload_validation_record_semantic_artifact_definition_review_outputs`.
  Rows expose `semantic_artifact_definition_review_output_contract_ref`,
  `semantic_artifact_definition_review_output_available=false`, and
  `semantic_artifact_definition_review_output_accepted=false`. Completed M57
  `6781-6800` evidence adds disabled futures request payload validation record
  semantic artifact runtime evidence acceptance through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS`,
  `iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances`,
  `request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count`,
  `blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count`,
  `ready_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count`,
  `runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count`,
  and
  `request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances`.
  Rows expose `semantic_artifact_runtime_evidence_acceptance_ref`,
  `semantic_artifact_runtime_evidence_acceptance_contract_ref`,
  `semantic_artifact_runtime_evidence_acceptance_available=false`, and
  `semantic_artifact_runtime_evidence_acceptance_accepted=false`.
  Completed M57 `6961-6980` carries forward disabled futures request payload
  validation record cancel semantics through
  `application/admin_api/futures_request_payload_validation_record_cancel_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CANCEL_SEMANTIC_CONTRACTS`,
  `iter_futures_request_payload_validation_record_cancel_semantics`,
  `request_payload_validation_record_cancel_semantic_count`,
  `blocking_request_payload_validation_record_cancel_semantic_count`,
  `ready_request_payload_validation_record_cancel_semantic_count`,
  `runtime_observed_request_payload_validation_record_cancel_semantic_count`,
  and `request_payload_validation_record_cancel_semantics`. Rows expose
  `cancel_semantics_ref`, `cancel_semantics_contract_ref`,
  `evidence_routes`, `cancel_semantics_contract_available=false`,
  `cancel_semantics_contract_ready=false`, `cancel_identity_bound=false`,
  `cancel_client_order_id_bound=false`,
  `cancel_order_wrapper_bound=false`,
  `cancel_active_placement_bound=false`, `cancel_audit_bound=false`,
  `runtime_cancel_evidence_observed=false`,
  `runtime_evidence_satisfies_cancel_semantics=false`, and
  `validation_record_cancel_semantics_ready=false`.
  Completed M57 `6941-6960` carries forward disabled futures request payload
  validation record order semantics through
  `application/admin_api/futures_request_payload_validation_record_order_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ORDER_SEMANTIC_CONTRACTS`,
  `iter_futures_request_payload_validation_record_order_semantics`,
  `request_payload_validation_record_order_semantic_count`,
  `blocking_request_payload_validation_record_order_semantic_count`,
  `ready_request_payload_validation_record_order_semantic_count`,
  `runtime_observed_request_payload_validation_record_order_semantic_count`,
  and `request_payload_validation_record_order_semantics`. Rows expose
  `order_semantics_ref`, `order_semantics_contract_ref`,
  `evidence_routes`, `order_semantics_contract_available=false`,
  `order_semantics_contract_ready=false`, `order_identity_bound=false`,
  `order_side_bound=false`, `order_size_bound=false`,
  `order_price_bound=false`, `order_type_bound=false`,
  `runtime_order_evidence_observed=false`,
  `runtime_evidence_satisfies_order_semantics=false`, and
  `validation_record_order_semantics_ready=false`.
  Completed M57 `6921-6940` carries forward disabled futures request payload
  validation record funding semantics through
  `application/admin_api/futures_request_payload_validation_record_funding_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_FUNDING_SEMANTIC_CONTRACTS`,
  `iter_futures_request_payload_validation_record_funding_semantics`,
  `request_payload_validation_record_funding_semantic_count`,
  `blocking_request_payload_validation_record_funding_semantic_count`,
  `ready_request_payload_validation_record_funding_semantic_count`,
  `runtime_observed_request_payload_validation_record_funding_semantic_count`,
  and `request_payload_validation_record_funding_semantics`. Rows expose
  `funding_semantics_ref`, `funding_semantics_contract_ref`,
  `evidence_routes`, `funding_semantics_contract_available=false`,
  `funding_semantics_contract_ready=false`, `funding_rate_bound=false`,
  `funding_fee_bound=false`, `funding_interval_bound=false`,
  `funding_cost_bound=false`, `runtime_funding_evidence_observed=false`,
  `runtime_evidence_satisfies_funding_semantics=false`, and
  `validation_record_funding_semantics_ready=false`.
  Completed M57 `6901-6920` carries forward disabled futures request payload
  validation record close-only semantics through
  `application/admin_api/futures_request_payload_validation_record_close_only_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CLOSE_ONLY_SEMANTIC_CONTRACTS`,
  `iter_futures_request_payload_validation_record_close_only_semantics`,
  `request_payload_validation_record_close_only_semantic_count`,
  `blocking_request_payload_validation_record_close_only_semantic_count`,
  `ready_request_payload_validation_record_close_only_semantic_count`,
  `runtime_observed_request_payload_validation_record_close_only_semantic_count`,
  and `request_payload_validation_record_close_only_semantics`. Rows expose
  `close_only_semantics_ref`, `close_only_semantics_contract_ref`,
  `evidence_routes`, `close_only_semantics_contract_available=false`,
  `close_only_semantics_contract_ready=false`,
  `close_only_flag_bound=false`, `close_only_position_side_bound=false`,
  `close_only_position_size_bound=false`, `close_only_order_side_bound=false`,
  `runtime_close_only_evidence_observed=false`,
  `runtime_evidence_satisfies_close_only_semantics=false`, and
  `validation_record_close_only_semantics_ready=false`.
  Completed M57 `6881-6900` carries forward disabled futures request payload
  validation record reduce-only semantics through
  `application/admin_api/futures_request_payload_validation_record_reduce_only_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS`,
  `iter_futures_request_payload_validation_record_reduce_only_semantics`,
  `request_payload_validation_record_reduce_only_semantic_count`,
  `blocking_request_payload_validation_record_reduce_only_semantic_count`,
  `ready_request_payload_validation_record_reduce_only_semantic_count`,
  `runtime_observed_request_payload_validation_record_reduce_only_semantic_count`,
  and `request_payload_validation_record_reduce_only_semantics`. Rows expose
  `reduce_only_semantics_ref`, `reduce_only_semantics_contract_ref`,
  `evidence_routes`, `reduce_only_semantics_contract_available=false`,
  `reduce_only_semantics_contract_ready=false`,
  `reduce_only_flag_bound=false`, `reduce_only_position_side_bound=false`,
  `reduce_only_position_size_bound=false`, `reduce_only_order_side_bound=false`,
  `runtime_reduce_only_evidence_observed=false`,
  `runtime_evidence_satisfies_reduce_only_semantics=false`, and
  `validation_record_reduce_only_semantics_ready=false`.
  Completed M57 `6861-6880` carries forward disabled futures request payload
  validation record liquidation semantics through
  `application/admin_api/futures_request_payload_validation_record_liquidation_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_liquidation_semantics`.
  Completed M57 `6841-6860` carries forward disabled futures request payload
  validation record collateral semantics through
  `application/admin_api/futures_request_payload_validation_record_collateral_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS`,
  `iter_futures_request_payload_validation_record_collateral_semantics`,
  `request_payload_validation_record_collateral_semantic_count`,
  `blocking_request_payload_validation_record_collateral_semantic_count`,
  `ready_request_payload_validation_record_collateral_semantic_count`,
  `runtime_observed_request_payload_validation_record_collateral_semantic_count`,
  and `request_payload_validation_record_collateral_semantics`. Rows expose
  `collateral_semantics_ref`, `collateral_semantics_contract_ref`,
  `evidence_routes`, `collateral_semantics_contract_available=false`,
  `collateral_semantics_contract_ready=false`,
  `collateral_balance_bound=false`, `collateral_currency_bound=false`,
  `collateral_requirement_bound=false`, `collateral_source_bound=false`,
  `runtime_collateral_evidence_observed=false`,
  `runtime_evidence_satisfies_collateral_semantics=false`, and
  `validation_record_collateral_semantics_ready=false`.
  Completed M57 `6821-6840` carries forward disabled futures request payload
  validation record margin semantics through
  `application/admin_api/futures_request_payload_validation_record_margin_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS`,
  `iter_futures_request_payload_validation_record_margin_semantics`,
  `request_payload_validation_record_margin_semantic_count`,
  `blocking_request_payload_validation_record_margin_semantic_count`,
  `ready_request_payload_validation_record_margin_semantic_count`,
  `runtime_observed_request_payload_validation_record_margin_semantic_count`,
  and `request_payload_validation_record_margin_semantics`. Rows expose
  `margin_semantics_ref`, `margin_semantics_contract_ref`, `evidence_routes`,
  `margin_semantics_contract_available=false`,
  `margin_semantics_contract_ready=false`, `margin_account_bound=false`,
  `margin_requirement_bound=false`, `margin_mode_bound=false`,
  `margin_buffer_bound=false`, `runtime_margin_evidence_observed=false`,
  `runtime_evidence_satisfies_margin_semantics=false`, and
  `validation_record_margin_semantics_ready=false`.
  Completed M57 `6801-6820` carries forward disabled futures request payload
  validation record position semantics through
  `application/admin_api/futures_request_payload_validation_record_position_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS`,
  `iter_futures_request_payload_validation_record_position_semantics`,
  `request_payload_validation_record_position_semantic_count`,
  `blocking_request_payload_validation_record_position_semantic_count`,
  `ready_request_payload_validation_record_position_semantic_count`,
  `runtime_observed_request_payload_validation_record_position_semantic_count`,
  and `request_payload_validation_record_position_semantics`. Rows expose
  `position_semantics_ref`, `position_semantics_contract_ref`,
  `evidence_routes`, `position_semantics_contract_available=false`,
  `position_semantics_contract_ready=false`, `position_identity_bound=false`,
  `position_scope_bound=false`, `position_side_derivation_bound=false`,
  `position_size_bound=false`, `position_notional_bound=false`,
  `runtime_position_evidence_observed=false`,
  `runtime_evidence_satisfies_position_semantics=false`, and
  `validation_record_position_semantics_ready=false`.
  Completed M57 `6761-6780` carries forward disabled futures request payload
  validation record semantic artifact runtime evidence binding through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_runtime_evidences.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS`,
  `iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidences`,
  `request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
  `blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
  `ready_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
  `runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
  and `request_payload_validation_record_semantic_artifact_runtime_evidences`.
  Rows expose `semantic_artifact_runtime_evidence_ref`,
  `semantic_artifact_runtime_evidence_contract_ref`,
  `semantic_artifact_runtime_evidence_available=false`,
  `semantic_artifact_runtime_evidence_bound=false`, and
  `semantic_artifact_runtime_evidence_accepted=false`. Completed M57
  `6741-6760` carries forward disabled futures request payload validation
  record semantic artifact definition review output acceptance evidence through
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_ACCEPTANCE_CONTRACTS`,
  `iter_futures_request_payload_validation_record_semantic_artifact_definition_review_output_acceptances`,
  `request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
  `blocking_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
  `ready_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
  `runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
  and `request_payload_validation_record_semantic_artifact_definition_review_output_acceptances`.
  Rows expose `semantic_artifact_definition_review_output_acceptance_ref`,
  `semantic_artifact_definition_review_output_acceptance_contract_ref`,
  `semantic_artifact_definition_review_output_acceptance_available=false`, and
  `semantic_artifact_definition_review_output_acceptance_accepted=false`.
  Completed M57
  `6661-6680` still carries forward disabled futures request payload validation
  record semantic artifact definition evidence through
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_CONTRACTS`,
  `iter_futures_request_payload_validation_record_semantic_artifact_definitions`,
  `request_payload_validation_record_semantic_artifact_definition_count`,
  `blocking_request_payload_validation_record_semantic_artifact_definition_count`,
  `ready_request_payload_validation_record_semantic_artifact_definition_count`,
  `runtime_observed_request_payload_validation_record_semantic_artifact_definition_count`,
  and `request_payload_validation_record_semantic_artifact_definitions`.
  This evidence does not accept review inputs, accept review outputs, accept
  resolution plans, accept runtime evidence, admit validation records, accept
  review-output acceptances, accept order semantics, bind live account or
  order evidence, accept funding semantics, bind live account or
  funding evidence, accept close-only semantics, bind live account or
  close-only evidence, accept reduce-only semantics, bind live account or
  reduce-only evidence, accept liquidation semantics, bind live account or
  liquidation-risk evidence, accept collateral semantics, bind live account or
  collateral evidence, accept margin semantics, accept position semantics, bind live position evidence,
  accept or bind runtime evidence, define futures semantics, pass contextless
  reviews as execution authority, validate payloads, resolve blockers, admit
  commands, call Coinbase, execute reconciliation, mutate futures/order/
  exchange state, or grant browser/BFF or spot-rule authority.
  Current M57 `7321-7340` adds first-class resolution-plan step review input
  store record-validation remediation dependency work-item claim-trace
  clearance-step review input store requirement rows through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_requirements.py`,
  while completed `7301-7320` carries forward first-class resolution-plan step review input
  store record-validation remediation dependency work-item claim-trace
  clearance-step review input rows through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_inputs.py`,
  while completed `7281-7300` carries forward first-class resolution-plan step review input
  store record-validation remediation dependency work-item claim-trace
  clearance-step review rows through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_reviews.py`,
  carrying forward completed `7261-7280` store record-validation remediation
  dependency work-item claim-trace clearance step rows through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_steps.py`,
  carrying forward completed `7241-7260` store record-validation remediation
  dependency work-item claim-trace clearance plan rows through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plans.py`,
  carrying forward completed `7221-7240` store record-validation remediation
  dependency work-item claim-trace rows through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_traces.py`,
  carrying forward completed `7201-7220` store record-validation remediation
  dependency work-item rows through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_items.py`,
  carrying forward completed `7181-7200` store record-validation remediation
  dependency rows through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependencies.py`,
  carrying forward completed `7161-7180` store record-validation remediation
  rows through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediations.py`,
  completed `7141-7160` store record-validation rows through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validations.py`,
  completed `7121-7140` store record-contract rows through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contracts.py`
  and completed `7101-7120` store requirement rows through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirements.py`,
  `execution_eligibility_resolution_plan_step_review_input_store_record_validation_ref`,
  `execution_eligibility_resolution_plan_step_review_input_store_record_validation_contract_ref`,
  `review_input_store_record_validation_kind`,
  `record_validation_required=true`, `record_validation_ready=false`,
  `record_validation_configured=false`, `record_validation_registered=false`,
  `record_validation_gate_ready=false`, `record_validation_gate_passed=false`,
  `record_validation_replay_guard_ready=false`,
  `record_validation_schema_ready=false`,
  `record_validation_append_only_log_ready=false`,
  `record_validation_idempotency_bound=false`,
  `record_validation_payload_bound=false`,
  `record_validation_contextless_review_passed=false`,
  `record_validation_performed=false`, `record_validation_accepted=false`, and
  `record_validation_recorded=false`,
  `execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_ref`,
  `execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_contract_ref`,
  `execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_ref`,
  `execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_contract_ref`,
  `review_input_store_record_validation_remediation_dependency_work_item_claim_trace_kind`,
  `record_validation_remediation_dependency_work_item_claim_trace_gate`,
  `record_validation_remediation_dependency_work_item_claim_trace_action_refs`,
  `record_validation_remediation_dependency_work_item_claim_trace_blockers`,
  `record_validation_remediation_dependency_work_item_claim_trace_required=true`,
  `record_validation_remediation_dependency_work_item_claim_trace_ready=false`,
  `record_validation_remediation_dependency_work_item_claim_trace_created=false`,
  `claim_trace_created=false`, `claim_trace_ready=false`,
  `claim_allowed=false`, `claim_resolved=false`,
  `claim_review_accepted=false`,
  `execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_ref`,
  `execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_contract_ref`,
  `review_input_store_record_validation_remediation_dependency_work_item_kind`,
  `record_validation_remediation_dependency_work_item_gate`,
  `record_validation_remediation_dependency_work_item_action_refs`,
  `record_validation_remediation_dependency_work_item_blockers`,
  `record_validation_remediation_dependency_work_item_required=true`,
  `record_validation_remediation_dependency_work_item_ready=false`,
  `record_validation_remediation_dependency_work_item_created=false`,
  `record_validation_remediation_dependency_work_item_claimed=false`,
  `claim_ledger_registered=false`, `owner_review_accepted=false`,
  `contextless_review_passed=false`, `accepts_evidence=false`,
  `writes_evidence=false`,
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
  `review_input_store_record_validation_remediation_kind`,
  `record_validation_remediation_required=true`,
  `record_validation_remediation_ready=false`,
  `record_validation_remediation_configured=false`,
  `record_validation_remediation_performed=false`,
  `record_validation_remediation_recorded=false`,
  `record_validation_remediation_accepted=false`,
  `record_validation_remediation_work_item_created=false`, and
  `record_validation_remediation_dependency_ready=false`, with parent fields
  `execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref`,
  `execution_eligibility_resolution_plan_step_review_input_store_record_contract_contract_ref`,
  `review_input_store_record_contract_kind`,
  `record_contract_required=true`, `record_contract_available=false`,
  `record_schema_available=false`, `append_only_log_available=false`,
  `idempotency_key_bound=false`, `payload_schema_validated=false`,
  `replay_protected=false`, `store_available=false`,
  `writer_available=false`, `writer_allowed=false`, `write_allowed=false`,
  `record_present=false`, `record_accepted=false`, `record_validated=false`,
  `validation_configured=false`, and `replay_protection_configured=false`.
  Dependency work-item claim-trace presence is not dependency resolution,
  claim-ledger registration, claim-trace readiness, claim allowance, claim
  resolution, claim-review acceptance, contextless review acceptance, evidence
  recording, command admission, Coinbase execution, reconciliation execution,
  futures/order/exchange mutation, browser/BFF authority, or spot-rule
  authority. Dependency work-item presence is not dependency resolution,
  claim-ledger registration, owner review acceptance, contextless review
  acceptance, evidence recording, command admission, Coinbase execution,
  reconciliation execution, futures/order/exchange mutation, browser/BFF
  authority, or spot-rule authority. Resolution plan step review input store
  record-validation remediation
  dependency presence is not blocker resolution, dependency graph creation,
  work item creation, claim trace creation, remediation execution, command
  admission, Coinbase execution, reconciliation execution, futures/order/
  exchange mutation, browser/BFF authority, or spot-rule authority. Resolution
  plan step review input store record-validation remediation presence is not
  blocker resolution. Resolution plan step review input store record-validation
  presence is not blocker resolution. Resolution plan step review input store
  record-contract presence is not blocker resolution.
  Exact autonomous phrase: Active M57 `7361-7380` evidence adds futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance-step review input store record-validation evidence while completed M57 `7341-7360` carries forward futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance-step review input store record-contract evidence.
  Completed autonomous phrase: Active M57 `7341-7360` evidence adds futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance-step review input store record-contract evidence while completed M57 `7321-7340` carries forward futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance-step review input store requirement evidence.
  Completed autonomous phrase: Active M57 `7321-7340` evidence adds futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance-step review input store requirement evidence while completed M57 `7301-7320` carries forward futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance-step review input evidence.
  Completed autonomous phrase: Active M57 `7301-7320` evidence adds futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance-step review input evidence while completed M57 `7281-7300` carries forward futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance-step review evidence.
  Literal machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance-step review evidence.
  Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance step evidence.
  Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance plan evidence.
  Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim trace evidence.
  Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item evidence.
  Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency evidence.
  Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation evidence.
  Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation evidence.
  Completed M57 `7101-7120` added first-class resolution-plan step review input store requirement rows through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_steps.py`,
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_reviews.py`,
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_inputs.py`,
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirements.py`,
  `execution_eligibility_resolution_plan_step_ref`,
  `execution_eligibility_resolution_plan_step_contract_ref`,
  `execution_eligibility_resolution_plan_step_review_ref`,
  `execution_eligibility_resolution_plan_step_review_contract_ref`,
  `execution_eligibility_resolution_plan_step_review_input_ref`,
  `execution_eligibility_resolution_plan_step_review_input_contract_ref`,
  `execution_eligibility_resolution_plan_step_review_input_store_requirement_ref`,
  `execution_eligibility_resolution_plan_step_review_input_store_requirement_contract_ref`,
  `resolution_plan_step_kind`, `resolution_plan_step_ready=false`, and
  `resolution_plan_step_accepted=false`,
  `resolution_plan_step_review_required=true`,
  `resolution_plan_step_review_ready=false`,
  `resolution_plan_step_reviewed=false`,
  `resolution_plan_step_review_accepted=false`, `review_input_kind`,
  `review_input_index`, `input_evidence_store`,
  `resolution_plan_step_review_input_required=true`,
  `resolution_plan_step_review_input_present=false`,
  `resolution_plan_step_review_input_accepted=false`, and
  `resolution_plan_step_review_input_validated=false`,
  `resolution_plan_step_review_input_store_requirement_required=true`,
  `resolution_plan_step_review_input_store_available=false`,
  `resolution_plan_step_review_input_writer_available=false`,
  `resolution_plan_step_review_input_record_key_available=false`,
  `resolution_plan_step_review_input_validation_gate_ready=false`, and
  `resolution_plan_step_review_input_replay_gate_ready=false`. Resolution plan
  step review input store requirement presence is not blocker resolution.
  Resolution plan step review input presence is not blocker resolution.
  Resolution plan step review presence is not blocker resolution.
  Exact autonomous phrase: Active M57 `7101-7120` evidence adds futures request payload validation record execution-eligibility resolution-plan step review input store requirement evidence while completed M57 `7081-7100` carries forward futures request payload validation record execution-eligibility resolution-plan step review input evidence.
  Literal machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store requirement evidence.
- The command-suite route also exposes request-payload validation record
  semantic artifact evidence through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifacts.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_CONTRACTS`,
  `iter_futures_request_payload_validation_record_semantic_artifacts`,
  `request_payload_validation_record_semantic_artifact_count`,
  `blocking_request_payload_validation_record_semantic_artifact_count`,
  `ready_request_payload_validation_record_semantic_artifact_count`,
  `runtime_observed_request_payload_validation_record_semantic_artifact_count`,
  and `request_payload_validation_record_semantic_artifacts`. Rows expose
  `semantic_artifact_ref`, `semantic_artifact_contract_ref`,
  `semantic_artifact_defined=false`, `semantic_artifact_reviewed=false`,
  `runtime_evidence_satisfies_semantic_artifact=false`, and
  `execution_eligibility_blocker_resolved=false`. Completed M57 `6641-6660`
  evidence adds disabled futures request payload validation record semantic
  artifact evidence while completed M57 `6621-6640` carries forward disabled
  futures request payload validation record execution-eligibility blocker
  evidence. This evidence does not define futures semantics, validate payloads,
  resolve blockers, admit commands, call Coinbase, execute reconciliation,
  mutate futures/order/exchange state, or grant browser/BFF or spot-rule
  authority.
  Literal machine-check phrase: futures request payload validation record semantic artifact evidence.
- The command-suite route also exposes request-payload validation record
  execution-eligibility blocker evidence through
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_EXECUTION_ELIGIBILITY_BLOCKER_CONTRACTS`,
  `iter_futures_request_payload_validation_record_execution_eligibility_blockers`,
  `request_payload_validation_record_execution_eligibility_blocker_count`,
  `blocking_request_payload_validation_record_execution_eligibility_blocker_count`,
  `resolved_request_payload_validation_record_execution_eligibility_blocker_count`,
  `runtime_observed_request_payload_validation_record_execution_eligibility_blocker_count`,
  and `request_payload_validation_record_execution_eligibility_blockers`.
  Rows expose `validation_record_execution_eligibility_blocker_ref`,
  `semantic_ref`, `required_backend_artifact_ref`, `missing_reason`, and
  `forbidden_execution_claims` while semantic readiness, blocker resolution,
  validation-record execution eligibility, execution, live Coinbase, browser,
  BFF, and spot-rule authority remain false. Completed M57 `6621-6640` evidence adds disabled futures request payload validation record execution-eligibility blocker evidence while completed M57 `6601-6620` carries forward disabled futures request payload validation record execution-eligibility evidence.
  Literal machine-check phrase: futures request payload validation record execution-eligibility blocker evidence.
- The command-suite route also exposes request-payload validation record
  admission-link evidence through
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ADMISSION_LINK_CONTRACTS`,
  `iter_futures_request_payload_validation_record_admission_links`,
  `request_payload_validation_record_admission_link_count`,
  `blocking_request_payload_validation_record_admission_link_count`,
  `ready_request_payload_validation_record_admission_link_count`,
  `admission_bound_request_payload_validation_record_count`,
  `runtime_observed_request_payload_validation_record_admission_link_count`,
  and `request_payload_validation_record_admission_links`. Rows expose
  `validation_record_admission_link_contract_ref`,
  `validation_record_approval_snapshot_ref`,
  `validation_record_cap_guard_decision_ref`,
  `validation_record_reconciliation_plan_ref`,
  `validation_record_live_intent_ref`,
  `validation_record_command_admission_ref`,
  `validation_record_admission_link_field_refs`,
  `validation_record_admission_link_field_count`,
  `runtime_evidence_satisfies_validation_record_admission_link=false`,
  `validation_record_admission_link_contract_ready=false`,
  `validation_record_admission_link_ready=false`,
  `validation_record_approval_snapshot_bound=false`,
  `validation_record_cap_guard_decision_bound=false`,
  `validation_record_reconciliation_plan_bound=false`,
  `validation_record_live_intent_bound=false`,
  `validation_record_command_admission_bound=false`, and
  `validation_record_admitted=false`. This evidence is disabled and does not
  bind approval snapshots, enforce caps, execute reconciliation, express live
  intent, admit commands, validate payloads, call Coinbase, mutate futures
  state, or grant browser/BFF or spot-rule authority. Completed M57
  `6561-6580` audit-link evidence remains visible for contextless review and
  display parity.
  Completed M57 `6601-6620` evidence adds disabled futures request payload
  validation record execution-eligibility evidence while completed M57
  `6581-6600` carries forward disabled futures request payload
  validation record admission-link evidence while carrying forward futures
  request payload validation record audit-link evidence through
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_AUDIT_LINK_CONTRACTS`,
  `iter_futures_request_payload_validation_record_audit_links`,
  `request_payload_validation_record_audit_link_count`,
  `blocking_request_payload_validation_record_audit_link_count`,
  `request_payload_validation_record_audit_links`,
  `validation_record_audit_link_contract_ref`,
  `validation_record_actor_ref`, `validation_record_operator_intent_ref`,
  `validation_record_correlation_ref`,
  `validation_record_admission_audit_ref`,
  `validation_record_audit_record_ref`,
  `validation_record_audit_link_field_refs`,
  `validation_record_audit_link_field_count`,
  runtime_evidence_satisfies_validation_record_audit_link=false,
  validation_record_audit_link_contract_ready=false,
  validation_record_audit_link_ready=false,
  validation_record_actor_bound=false,
  validation_record_operator_intent_bound=false,
  validation_record_correlation_bound=false,
  validation_record_admission_audit_bound=false, and
  validation_record_audit_recorded=false.
  Literal machine-check phrases: futures request payload validation record execution-eligibility evidence; futures request payload validation record admission-link evidence; futures request payload validation record audit-link evidence.
- The command-suite route exposes semantic guard metadata for each planned
  command family. These rows identify identity, risk, audit, reconciliation,
  and live-boundary blockers; they are not browser validation authority and do
  not make commands executable.
- Each semantic guard row also exposes backend evidence routes, missing
  evidence refs, route/ref counts, and disabled proof-route/proof-writer
  posture so a contextless operator can see what still blocks that guard.
- Each command row also exposes a backend-owned readiness decision with blocker
  counts, first blocker, next required backend contract, and explicit
  route/draft true and execution false flags. The decision summarizes existing
  blocked evidence; it does not create approval or execution authority.
- Each command row also exposes ordered backend-owned readiness closure steps
  for the remaining prerequisite, payload, semantic-guard, live-adapter, and
  contextless-review work. These steps are planning evidence only; they do not
  write proofs, call Coinbase, execute reconciliation, or make the browser an
  execution authority.
- The command-suite route also aggregates those closure steps into
  backend-owned `command_enablement_sequence_steps` with sequence counts,
  source blockers, affected commands, required backend contracts, and required
  evidence refs. These aggregate rows are read-only orientation evidence; they
  do not create routes, drafts, adapters, Coinbase calls, reconciliation
  execution, futures state mutation, browser authority, BFF authority, or
  spot-rule authority.
- The command-suite route also exposes
  `command_enablement_sequence_command_traces` with
  `trace_id`, `command_step_sequence`,
  `reconciliation_execution_allowed`, and
  `futures_state_mutation_allowed` fields. Trace rows map each aggregate
  sequence step back to exact per-command readiness closure evidence. They are
  backend-owned read-only evidence and do not create execution authority, bind
  live adapters, call Coinbase, execute reconciliation, mutate
  futures/order/exchange state, or grant browser, BFF, or spot-rule authority.
- The `futures_reconcile` command-suite row reports
  `service_method="reconcile_futures_position"` as a disabled shared
  command-service bridge. The row still keeps
  `application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan`
  in `required_backend_contracts` as the separate reconciliation-plan
  contract. The bridge is backend-owned read-only evidence and does not
  execute reconciliation, call Coinbase, mutate futures/order/exchange state,
  or grant browser/BFF authority.
- Each command row also exposes backend-owned risk proof requirements for
  product scope, position scope, margin, collateral, liquidation buffer,
  funding fee, reduce-only, close-only, cap guard, and reconciliation-plan
  semantics. These rows are blocked evidence requirements only; they do not
  write proofs, register proof routes, or make a command executable.
- Each risk proof requirement also exposes backend-owned proof route/writer
  contract rows. These rows name required future proof-route and proof-writer
  artifacts, evidence refs, proposed route paths, and disabled
  route/writer/execution flags. They do not register routes, enable writers,
  accept proof payloads, or make a command executable.
- `/api/v1/futures/risk-proofs` is the first concrete append-only
  futures/perpetual proof-record route. It records exact-context proof
  evidence through the backend command service, but accepted records remain
  evidence only and do not satisfy command-suite risk proof requirements or
  enable futures command routes.
- Each risk proof requirement also exposes five backend-owned acceptance
  criteria: required evidence present, proof route registered, proof writer
  reviewed, spot-rule boundary reviewed, and browser/BFF authority reviewed.
  All acceptance criteria remain blocked and unaccepted in the current
  contract; `satisfies_risk_proof=false` means later command enablement still
  has no proof authority.
- Each risk proof requirement also exposes backend-owned semantic contract
  definition rows through `semantic_contract_definitions` and definition
  counts such as `risk_proof_semantic_contract_definition_count`. These rows
  name the missing backend definition contract, semantic definition ref,
  validation gate, acceptance gate, required evidence refs, and missing
  evidence refs for each semantic contract ref. They remain blocked with
  `definition_ready=false`, `validation_ready=false`,
  `acceptance_ready=false`, and
  `runtime_evidence_satisfies_definition=false`; observed runtime evidence
  does not register a semantic contract, satisfy proof acceptance, make
  route-bound command drafts executable, call Coinbase, execute reconciliation,
  mutate state, or grant browser/BFF authority.
- Each risk proof requirement also exposes backend-owned semantic contract
  validation gate rows through `semantic_contract_validation_gates` and
  validation gate counts such as
  `risk_proof_semantic_contract_validation_gate_count`. These rows name the
  validation gate, missing backend validator contract, validation input refs,
  required evidence refs, and missing evidence refs for each semantic
  definition. They remain blocked with `validator_registered=false`,
  `validation_ready=false`, `definition_ready=false`, and
  `runtime_evidence_satisfies_validation=false`; observed runtime evidence
  does not register validators, make definitions ready, satisfy proof
  acceptance, make route-bound command drafts executable, call Coinbase,
  execute reconciliation, mutate state, or grant browser/BFF authority.
- Each risk proof requirement also exposes backend-owned semantic validator
  contract rows through `semantic_contract_validator_contracts` and validator
  contract counts such as
  `risk_proof_semantic_contract_validator_contract_count`. These rows name the
  missing backend validator contract, input schema ref, output schema ref,
  registration ref, required evidence refs, and missing evidence refs for each
  semantic validation gate. They remain blocked with
  `validator_contract_registered=false`, `input_schema_registered=false`,
  `output_schema_registered=false`, `validator_registered=false`,
  `validation_ready=false`, and
  `runtime_evidence_satisfies_validator_contract=false`; observed runtime
  evidence does not register validator contracts, register schemas, register
  validators, make validation gates ready, satisfy proof acceptance, make
  route-bound command drafts executable, call Coinbase, execute reconciliation,
  mutate state, or grant browser/BFF authority.
- Each risk proof requirement also exposes backend-owned semantic validator
  input schema rows through `semantic_validator_input_schemas` and input schema
  counts such as `risk_proof_semantic_validator_input_schema_count`. These rows
  name the missing backend input schema contract, input schema field refs,
  schema registration evidence, required evidence refs, and missing evidence
  refs for each semantic validator contract. They remain blocked with
  `input_schema_registered=false`, `validator_contract_registered=false`,
  `validator_registered=false`, `validation_ready=false`, and
  `runtime_evidence_satisfies_input_schema=false`; observed runtime evidence
  does not satisfy input schemas, register schemas, register validator
  contracts, register validators, make validation gates ready, satisfy proof
  acceptance, make route-bound command drafts executable, call Coinbase,
  execute reconciliation, mutate state, or grant browser/BFF authority.
- Each risk proof requirement also exposes backend-owned semantic validator
  output schema rows through `semantic_validator_output_schemas` and output
  schema counts such as `risk_proof_semantic_validator_output_schema_count`.
  These rows name the missing backend output schema contract, output schema
  field refs, schema registration evidence, required evidence refs, and
  missing evidence refs for each semantic validator contract. They remain
  blocked with `output_schema_registered=false`,
  `validator_contract_registered=false`, `validator_registered=false`,
  `validation_ready=false`, and
  `runtime_evidence_satisfies_output_schema=false`; observed runtime evidence
  does not satisfy output schemas, register schemas, register validator
  contracts, register validators, make validation gates ready, satisfy proof
  acceptance, make route-bound command drafts executable, call Coinbase,
  execute reconciliation, mutate state, or grant browser/BFF authority.
- Each risk proof requirement also exposes backend-owned semantic validator
  registration rows through `semantic_validator_registrations` and registration
  counts such as `risk_proof_semantic_validator_registration_count`. These rows
  name the missing backend registration contract, registry record,
  validator-contract ref, input-schema ref, output-schema ref, registration
  field refs, required evidence refs, and missing evidence refs for each
  semantic validator contract. They remain blocked with
  `validator_registration_ready=false`, `validator_registered=false`,
  `validation_ready=false`, and
  `runtime_evidence_satisfies_validator_registration=false`; observed runtime
  evidence does not satisfy validator registration, register validators, make
  validation gates ready, satisfy proof acceptance, make route-bound command
  drafts executable, call Coinbase, execute reconciliation, mutate state, or
  grant browser/BFF authority.
- Each risk proof requirement also exposes backend-owned proof record/store
  contract rows, blocked record-validation rows, and blocked
  record-validation remediation rows. These rows name required store refs,
  record keys, payload fields, validation gates, replay gates, validation
  checks, and required remediation actions, but they do not create stores,
  register validators, create remediation work items, perform remediation,
  write proof records, accept evidence, or make a command executable.
- Each risk proof requirement also exposes backend-owned clearance-step review
  input store record-contract rows and store record-validation rows. These
  rows name required input-record contracts, schemas, append-only logs,
  idempotency keys, validation checks, validation gates, replay gates, and
  inherited blockers, but they do not create record contracts, register
  schemas, configure logs, bind idempotency keys, validate payloads, register
  validators, accept records, write evidence, or make a command executable.
- Each risk proof requirement also exposes backend-owned record-validation
  remediation dependency rows. These rows order blocked remediation rows with
  predecessor/successor refs, dependency gates, missing backend contracts,
  required evidence refs, and blocker lists. They do not resolve
  dependencies, create dependency work items, perform remediation, accept
  proof records, register routes, enable writers, or make commands
  executable.
- Each risk proof requirement also exposes backend-owned record-validation
  remediation dependency work-item rows. These rows name the backend work-item
  contract, work-item store, claim-ledger blocker, owner-review blocker,
  contextless-review blocker, and predecessor/successor work-item refs needed
  before dependency work could ever be queued. They do not create or claim
  work items, register claim ledgers, resolve dependencies, perform
  remediation, accept proof records, register routes, enable writers, or make
  commands executable.
- Each risk proof requirement also exposes backend-owned record-validation
  remediation dependency work-item claim-trace rows. These rows name the
  backend claim-trace contract, claim-trace store, claim target, claim-ledger
  blocker, claim-review blocker, contextless-review blocker, and
  predecessor/successor claim-trace refs needed before dependency work could
  ever be claimed or used as clearance evidence. They do not create claim
  traces, allow claims, resolve claims, claim work items, register claim
  ledgers, resolve dependencies, perform remediation, accept proof records,
  register routes, enable writers, or make commands executable.
- Each risk proof requirement also exposes backend-owned record-validation
  remediation dependency work-item claim-trace clearance-plan rows. These rows
  name the backend clearance-plan contract, clearance-plan store, required
  plan steps, claim target, upstream claim-trace ref, and
  predecessor/successor clearance-plan refs needed before a claim trace could
  ever be cleared. They do not create clearance plans, execute plan steps,
  clear claim traces, resolve claims, clear work items, resolve dependencies,
  perform remediation, accept proof records, register routes, enable writers,
  or make commands executable.
- Each risk proof requirement also exposes backend-owned record-validation
  remediation dependency work-item claim-trace clearance-step rows. These
  rows name the backend clearance-step contract, step gate, missing
  step-review/contextless-review evidence, plan refs, and
  predecessor/successor step refs needed before a clearance plan could ever
  be reviewed or executed. They do not execute steps, complete reviews, clear
  claim traces, resolve claims, clear work items, resolve dependencies,
  perform remediation, accept proof records, register routes, enable writers,
  or make commands executable.
- Each risk proof requirement also exposes backend-owned record-validation
  remediation dependency work-item claim-trace clearance-step review,
  review-input, review-input store requirement, and review-input store
  record-contract rows. These rows name missing review evidence, required
  input evidence, backend store/writer/record-key refs, record contract refs,
  record schema refs, append-only log refs, idempotency keys, payload fields,
  validation gates, replay gates, and blocker chains before evidence could
  ever be accepted. They do not complete reviews, accept inputs, create
  stores, enable writers, register schemas, configure logs, bind idempotency,
  validate payloads, protect replay, write evidence, call Coinbase, grant
  browser/BFF authority, or make commands executable.
- In this contract, "risk proof requirements" is the umbrella for command
  safety prerequisites, including identity/product-scope and reconciliation
  proof requirements that must exist before risk-sensitive commands can be
  reviewed for enablement.
- Spot wallet, no-shorting, USDC quote scope, average/cost-basis, and
  inventory-lot assumptions are explicitly forbidden as futures/perpetual
  command authority.

## Sources

The read service prefers runtime orderbook position snapshots. Dashboard
engine-state positions are a labeled fallback. Coinbase REST futures reads are
not called by default from these Admin API routes.

Collateral and liquidation evidence remains `unavailable` unless the runtime
retains a futures balance summary snapshot. Funding-rate evidence is
`not_modeled` in this milestone.

## Safety Constraints

- Do not import Spot wallet, no-shorting, cost-basis, known-profitable
  inventory, or average-cost rules into this module.
- Do not enable futures command routes for execution until backend guard/risk
  policy evidence, command contracts, approval/cap/audit gates, live adapter
  contracts, reconciliation gates, and contextless review are in place.
- Do not treat command-suite request fields as browser-side form authority.
  The backend must own validation, audit, idempotency, risk checks, and future
  service mapping before any command can become executable.
- Do not treat command-suite semantic guards as satisfied checks. They are
  blocked contract evidence until backend-owned guard/risk/admission/audit,
  reconciliation, approval, cap, and live-service prerequisites are built.
- Do not treat semantic guard evidence routes as proof writers. The current
  routes are read evidence only; `proof_route_registered=false` and
  `proof_writer_enabled=false` remain part of the contract.
- Do not treat command readiness decisions as live-readiness approval. They
  remain blocked while backend command routes, drafts, live adapters, guard
  proof, admission audit, reconciliation proof, and service contracts are
  missing.
- Do not treat disabled command-service methods as executable. M57 phases
  5981-6000 define `place_futures_order`,
  `close_or_reduce_futures_position`, and `cancel_futures_order` as disabled
  backend service-contract evidence only. These methods prove there is a
  shared backend boundary for future work; they do not register routes, create
  drafts, call Coinbase, execute reconciliation, mutate futures state, or grant
  browser/BFF authority.
- Do not treat the disabled reconciliation command-service bridge as
  reconciliation execution. M57 phases 6281-6300 define
  `reconcile_futures_position` as disabled shared command-service evidence for
  `futures_reconcile` while `record_futures_reconciliation_plan` remains the
  separate required reconciliation-plan contract. The bridge must not reconcile
  positions, read or write Coinbase, mutate futures/order/exchange state,
  satisfy proof acceptance, register command routes, create drafts, or grant
  browser/BFF authority.
- Do not treat futures proof route/writer contract registry evidence as proof
  acceptance. M57 phases 6301-6320 define
  `FUTURES_PROOF_ROUTE_CONTRACTS` and `FUTURES_PROOF_WRITER_CONTRACTS` as
  disabled backend-owned registries for risk-proof contract refs such as
  `application/admin_api/futures_proof_routes.py::post_futures_place_margin_collateral_proof`
  and
  `application/admin_api/futures_proof_writer.py::write_futures_place_margin_collateral_proof`.
  These registries must not register proof routes, create proof writers,
  accept proof records, satisfy risk proof requirements, register command
  routes, create drafts, call Coinbase, execute reconciliation, mutate
  futures/order/exchange state, or grant browser/BFF authority.
- Do not treat futures proof payload-field contract registry evidence as
  payload validation or proof acceptance. M57 phases 6321-6340 define
  `FUTURES_PROOF_PAYLOAD_FIELD_CONTRACTS` and
  `iter_futures_proof_payload_field_contracts` as disabled backend-owned
  registry evidence for payload paths and validation refs such as
  `proof_payload.command`, `proof_payload.validation.status`, and
  `futures_place_margin_collateral_payload_command_validated`. These rows keep
  `payload_field_present=false` and `validation_registered=false`; they must
  not validate submitted proof payloads, register validators, accept proof
  records, create proof writers, make route-bound command drafts executable,
  call Coinbase, execute reconciliation, mutate futures/order/exchange state,
  or grant browser/BFF authority.
- Do not treat futures request payload contract registry evidence as payload
  validation or command authority. Completed M57 phases 6361-6380 define
  `FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS` and
  `iter_futures_request_payload_contracts` as disabled backend-owned registry
  evidence for the exact command request fields emitted by
  `GET /api/v1/futures/command-suite`. Command-suite `request_field_count`,
  `blocking_request_field_count`, and request-field
  `required_backend_contracts` derive from that registry. route/draft true
  and execution false flags remain in force. These rows must not validate
  command request payloads, register payload validators, bind live adapters,
  submit or cancel Coinbase orders, execute reconciliation, mutate
  futures/order/exchange state, or grant browser/BFF or spot-rule authority.
  Completed M57 phases 6381-6400 exposed disabled `validation_gate_ref`,
  `validation_evidence_ref`, `validator_contract_ref`,
  `validator_registration_ref`, and false readiness flags on those request
  fields: validation_gate_ready=false, validation_gate_passed=false, and
  request_payload_validated=false. Completed M57 phases 6401-6420 exposed
  disabled futures request payload validator contract registry evidence
  through `FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS`,
  `iter_futures_request_payload_validator_contracts`,
  `request_payload_validator_contract_count`,
  `blocking_request_payload_validator_contract_count`,
  `validator_input_schema_ref`, `validator_output_schema_ref`,
  validator_input_schema_registered=false, and
  validator_output_schema_registered=false. Completed M57 phases 6421-6440
  expose disabled futures request payload validator input-schema evidence
  through `FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS`,
  `iter_futures_request_payload_validator_input_schemas`,
  `request_payload_validator_input_schema_count`,
  `blocking_request_payload_validator_input_schema_count`,
  `request_payload_validator_input_schemas`, `input_schema_field_refs`,
  `input_schema_field_count`, and input_schema_registered=false.
  Completed M57 phases 6441-6460 expose disabled futures request payload
  validator output-schema evidence through
  `FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS`,
  `iter_futures_request_payload_validator_output_schemas`,
  `request_payload_validator_output_schema_count`,
  `blocking_request_payload_validator_output_schema_count`,
  `request_payload_validator_output_schemas`, `output_schema_field_refs`,
  `output_schema_field_count`, and output_schema_registered=false. Completed
  M57 phases 6461-6480 expose disabled futures request payload validator
  registration evidence through
  `FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS`,
  `iter_futures_request_payload_validator_registrations`,
  `request_payload_validator_registration_count`,
  `blocking_request_payload_validator_registration_count`,
  `request_payload_validator_registrations`,
  `validator_registration_field_refs`,
  `validator_registration_field_count`,
  validator_registration_ready=false, and
  runtime_evidence_satisfies_validator_registration=false.
  Completed M57 phases 6481-6500 expose disabled futures request payload
  validation evidence through
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS`,
  `iter_futures_request_payload_validation_evidence`,
  `request_payload_validation_evidence_count`,
  `blocking_request_payload_validation_evidence_count`,
  `request_payload_validation_evidence`, `validation_evidence_contract_ref`,
  `validation_evidence_field_refs`, `validation_evidence_field_count`,
  runtime_evidence_satisfies_validation_evidence=false,
  validation_evidence_ready=false, and validation_evidence_recorded=false.
  Machine-check evidence: futures request payload validator output-schema evidence.
  Machine-check evidence: futures request payload validator registration evidence.
  Machine-check evidence: futures request payload validation evidence.
  Completed M57 phases 6501-6520 expose disabled futures request payload
  validation evidence record contract evidence through
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS`,
  `iter_futures_request_payload_validation_evidence_records`,
  `request_payload_validation_evidence_record_count`,
  `blocking_request_payload_validation_evidence_record_count`,
  `request_payload_validation_evidence_records`,
  `validation_record_contract_ref`, `validation_record_store_ref`,
  `validation_record_writer_ref`, `validation_record_replay_guard_ref`,
  `validation_record_field_refs`, `validation_record_field_count`,
  runtime_evidence_satisfies_validation_record=false,
  validation_record_contract_ready=false,
  validation_record_store_ready=false,
  validation_record_writer_enabled=false,
  validation_record_replay_guard_ready=false, validation_recorded=false,
  append_only_validation_record=false,
  validation_record_idempotency_bound=false, and request_payload_validated=false.
  Machine-check evidence: futures request payload validation evidence record contract evidence.
  Completed M57 phases 6541-6560 expose disabled futures request payload
  validation record replay guard evidence through
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS`,
  `iter_futures_request_payload_validation_record_replay_guards`,
  `request_payload_validation_record_replay_guard_count`,
  `blocking_request_payload_validation_record_replay_guard_count`,
  `request_payload_validation_record_replay_guards`,
  `validation_record_replay_guard_contract_ref`,
  `validation_record_idempotency_contract_ref`,
  `validation_record_replay_window_ref`,
  `validation_record_duplicate_policy_ref`,
  `validation_record_replay_guard_field_refs`,
  `validation_record_replay_guard_field_count`,
  runtime_evidence_satisfies_validation_record_replay_guard=false,
  validation_record_replay_guard_contract_ready=false,
  validation_record_idempotency_contract_ready=false,
  validation_record_replay_protected=false, and
  validation_record_idempotency_bound=false.
  Machine-check evidence: futures request payload validation record replay guard evidence.
  Carried-forward machine-check evidence: futures request payload validation record schema evidence.
  Machine-check evidence: validate command request payloads remains forbidden.
- Do not treat disabled risk-guard methods as executable proof acceptance.
  M57 phases 6001-6020 define
  `evaluate_futures_margin_collateral_liquidation` as disabled backend
  risk-guard contract evidence only. The method proves there is a shared
  backend boundary for future risk checks; it does not validate margin,
  collateral, liquidation, or funding, accept proof records, register routes,
  create drafts, call Coinbase, execute reconciliation, mutate futures state,
  or grant browser/BFF authority.
- Do not treat disabled reconciliation planning as reconciliation execution.
  M57 phases 6021-6040 define
  `record_futures_reconciliation_plan` as disabled backend contract evidence
  only. The method must not reconcile positions, read or write Coinbase,
  mutate futures/order/exchange state, satisfy proof acceptance, register
  live adapters, or grant browser/BFF authority. Route registration was the
  next missing backend contract gap through 6021-6040.
- Do not treat disabled route-registration contract metadata by itself as
  execution authority. M57 phases 6041-6060 define
  `api/v1/routes/futures.py::*_route_contract` refs as required/present
  disabled backend evidence only. Completed phases 6341-6360 register
  route-bound no-live drafts for the four command families, completed phases
  6361-6380 bind disabled request payload contract registry evidence,
  completed phases 6381-6400 bind disabled request payload validation gate
  evidence, completed phases 6401-6420 bind disabled validator contract
  registry evidence, and completed phases 6421-6440 bind disabled validator
  input-schema evidence while keeping route/draft flags true while
  executable command count stays zero.
- Do not treat disabled live-adapter contract metadata as adapter construction
  or invocation. M57 phases 6061-6080 define
  `application/admin_api/live_execution.py::*_adapter_contract` refs as
  required/present disabled backend evidence only. M57 phases 6081-6100 define
  `application/admin_api/live_execution.py::*_adapter_construction_contract`
  refs as required/present disabled backend evidence only. M57 phases
  6101-6120 define
  `application/admin_api/live_execution.py::*_adapter_decision_contract` refs
  as required/present disabled backend evidence only. M57 phases 6121-6140
  define
  `application/admin_api/live_execution.py::*_adapter_decision_record_contract`
  refs as required/present disabled backend evidence only. M57 phases
  6141-6160 define
  `application/admin_api/live_execution.py::*_adapter_invocation_contract`
  refs as required/present disabled backend evidence only. M57 phases
  6161-6180 define
  `application/admin_api/live_execution.py::*_adapter_execution_contract`
  refs as required/present disabled backend evidence only. M57 phases
  6181-6200 define
  `application/admin_api/live_execution.py::*_coinbase_exchange_submission_contract`
  refs as required/present disabled backend evidence only. The next missing
  backend gaps are
  `application/admin_api/live_execution.py::*_post_exchange_submission_reconciliation_contract`
  refs. Adapter, adapter-construction, adapter-decision, adapter
  decision-record, adapter-invocation, and adapter-execution refs do not
  configure or construct adapters, record executable decisions, invoke
  adapters, execute adapters, submit Coinbase orders, execute post-exchange
  reconciliation, mutate futures state, or grant browser/BFF authority.
- Do not treat command readiness closure steps as completed implementation.
  They are an ordered backend-owned plan for future enablement slices and
  remain blocked until implemented and reviewed through backend contracts.
- Do not treat command risk proof requirements as completed guard proofs.
  They are backend-owned evidence requirements and remain blocked until
  implemented and reviewed through backend contracts.
- Do not treat risk proof route/writer contracts as registered routes or
  enabled writers. They are blocked contract targets for future backend work
  and keep route registration, writer enablement, command drafts, execution,
  browser authority, and BFF execution authority disabled.
- Do not treat futures risk-proof records as proof acceptance or command
  readiness. They are append-only local evidence records and remain
  insufficient to make route-bound command drafts executable, satisfy risk
  proof requirements, execute reconciliation, call Coinbase, or mutate
  futures/order/exchange state.
- Do not treat risk proof acceptance criteria as completed proof reviews.
  They are blocked acceptance checks that name what a later backend-owned
  proof route and proof writer must satisfy; they do not enable routes,
  drafts, proof writers, live adapters, browser execution, or BFF execution.
- Do not treat semantic contract definition rows as registered semantic
  contracts or proof acceptance. `semantic_contract_definitions` rows are
  missing backend definition-contract evidence only; `definition_ready=false`
  and `runtime_evidence_satisfies_definition=false` keep command routes,
  command drafts, proof satisfaction, reconciliation execution, Coinbase
  activity, state mutation, browser authority, and BFF execution authority
  disabled.
- Do not treat semantic contract validation gate rows as registered validators
  or proof acceptance. `semantic_contract_validation_gates` rows are missing
  backend validator-contract evidence only; `validation_ready=false` and
  `runtime_evidence_satisfies_validation=false` keep validator registration,
  definition readiness, command routes, command drafts, proof satisfaction,
  reconciliation execution, Coinbase activity, state mutation, browser
  authority, and BFF execution authority disabled.
- Do not treat semantic validator contract rows as registered validator
  implementations, registered schemas, or proof acceptance.
  `semantic_contract_validator_contracts` rows are missing backend validator
  contract evidence only; `validator_contract_registered=false`,
  `input_schema_registered=false`, `output_schema_registered=false`,
  `validator_registered=false`, and
  `runtime_evidence_satisfies_validator_contract=false` keep validation
  readiness, command routes, command drafts, proof satisfaction,
  reconciliation execution, Coinbase activity, state mutation, browser
  authority, and BFF execution authority disabled.
- Do not treat risk proof record/store contracts, record-validation rows,
  record-validation remediation rows, record-validation remediation dependency
  rows, record-validation remediation dependency work-item rows, or
  record-validation remediation dependency work-item claim-trace rows, or
  record-validation remediation dependency work-item claim-trace
  clearance-plan rows, or record-validation remediation dependency work-item
  claim-trace clearance-step rows, or record-validation remediation
  dependency work-item claim-trace clearance-step review rows, or
  record-validation remediation dependency work-item claim-trace
  clearance-step review input rows, clearance-step review input store
  requirement rows, clearance-step review input store record-contract rows, or
  clearance-step review input store record-validation rows
  as
  registered stores, registered validators, created or claimed work items,
  created or resolved claim traces, created or executed clearance plans,
  executed clearance steps, completed clearance-step reviews, cleared claim
  traces, accepted review inputs, created review-input stores, created record
  contracts, registered schemas, configured append-only logs, bound
  idempotency, validated payloads, configured replay protection, written
  evidence, registered claim ledgers, resolved dependencies, performed
  remediation, proof writes, accepted proof evidence, or command authority.
  They are blocked backend contract evidence for future work only.
- Do not use browser code to calculate margin, liquidation, funding, close
  eligibility, or P/L authority.
- Do not treat exchange-native ids as futures position identity.

## Examples

See [Futures/Perpetuals Examples](docs/examples/futures-perpetuals.md).

## Related Docs

- [Admin API](README.admin-api.md)
- [Admin Module Capability Matrix](docs/ADMIN_MODULE_CAPABILITY_MATRIX.md)
- [Admin API Route Inventory](docs/plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Documentation Index](docs/README.md)

## Completed M57 Validation Record Schema Evidence

Completed `6501-6520` extends the no-live futures/perpetual command-suite
contract with disabled request payload validation evidence record contract rows.
Backend
registry:
`application/admin_api/futures_request_payload_validation_evidence_records.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS`, and
`iter_futures_request_payload_validation_evidence_records`. Command-suite
evidence: `request_payload_validation_evidence_record_count`,
`blocking_request_payload_validation_evidence_record_count`,
`request_payload_validation_evidence_records`, `validator_input_schema_ref`,
`validator_output_schema_ref`, `validator_registration_ref`,
`validation_evidence_contract_ref`, `validation_record_contract_ref`,
`validation_record_store_ref`, `validation_record_writer_ref`,
`validation_record_replay_guard_ref`, `validation_record_field_refs`,
`validation_record_field_count`, `required_evidence_refs`,
`missing_evidence_refs`,
`runtime_evidence_satisfies_validation_record=false`,
`validation_record_contract_ready=false`,
`validation_record_store_ready=false`,
`validation_record_writer_enabled=false`,
`validation_record_replay_guard_ready=false`, `validation_recorded=false`,
`append_only_validation_record=false`,
`validation_record_idempotency_bound=false`, and
`request_payload_validated=false`. Route/draft true and execution false flags
remain required; this evidence must not validate command request payloads,
write validation records, register record stores, call Coinbase, execute
reconciliation, mutate state, or create spot-rule authority. Carried-forward
validation-evidence rows still expose `validation_evidence_ready=false` and
`validation_evidence_recorded=false`; validator-registration rows still expose
`validator_registration_ready=false` and
`runtime_evidence_satisfies_validator_registration=false`, while output-schema
rows expose `output_schema_registered=false`.

Completed `6521-6540` extends the same no-live futures/perpetual command-suite
contract with disabled request payload validation record schema and append-only
log rows. Backend registry:
`application/admin_api/futures_request_payload_validation_record_schemas.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS`, and
`iter_futures_request_payload_validation_record_schemas`. Command-suite
evidence: `request_payload_validation_record_schema_count`,
`blocking_request_payload_validation_record_schema_count`,
`request_payload_validation_record_schemas`, `validation_record_schema_ref`,
`validation_record_append_only_log_ref`, `validation_record_schema_field_refs`,
`validation_record_schema_field_count`, `required_evidence_refs`,
`missing_evidence_refs`,
`runtime_evidence_satisfies_validation_record_schema=false`,
`validation_record_schema_ready=false`,
`validation_record_schema_registered=false`, and
`validation_record_append_only_log_ready=false`. Route/draft true and execution
false flags remain required; this evidence must not register schemas, write
append-only validation logs, validate command request payloads, write
validation records, call Coinbase, execute reconciliation, mutate state, or
create spot-rule authority.
