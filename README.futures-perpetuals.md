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
- `POST /api/v1/futures/risk-proofs`

Read routes require Admin API auth/RBAC and `analytics:read`. The
`POST /api/v1/futures/risk-proofs` route requires
`futures_risk_proof:record`, idempotency, approval, cap/guard, and audit
evidence through the shared Admin API command service. It persists
append-only local proof evidence only; it does not verify the proof
requirement, register futures command routes, create command drafts, call
Coinbase, execute reconciliation, mutate futures/order/exchange state, or
grant browser/BFF authority. Account and position routes return
`read_only=true`, `command_routes_mode="not_modeled"`, and
`live_coinbase_orders_ran=false`; the command-suite route exposes the same
blocked/no-live posture through its disabled route, draft, execution,
browser, BFF, and notional evidence fields.

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
  evidence for placement, close/reduce, cancel, and reconciliation. It does
  not register futures command routes, create command drafts, call Coinbase,
  mutate state, or grant browser/BFF authority.
- The command-suite route also exposes request-field contract metadata for
  each planned command family. These fields are blocked backend contract
  evidence only; they are not accepted payloads and do not create executable
  routes.
- The command-suite route exposes semantic guard metadata for each planned
  command family. These rows identify identity, risk, audit, reconciliation,
  and live-boundary blockers; they are not browser validation authority and do
  not make commands executable.
- Each semantic guard row also exposes backend evidence routes, missing
  evidence refs, route/ref counts, and disabled proof-route/proof-writer
  posture so a contextless operator can see what still blocks that guard.
- Each command row also exposes a backend-owned readiness decision with blocker
  counts, first blocker, next required backend contract, and explicit
  route/draft/execution false flags. The decision summarizes existing blocked
  evidence; it does not create a command route or approval.
- Each command row also exposes ordered backend-owned readiness closure steps
  for the remaining prerequisite, payload, semantic-guard, command-service,
  route, live-adapter, and contextless-review work. These steps are planning
  evidence only; they do not register a route, write proofs, call Coinbase, or
  make the browser an execution authority.
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
  does not register a semantic contract, satisfy proof acceptance, create
  command drafts, register futures routes, call Coinbase, execute
  reconciliation, mutate state, or grant browser/BFF authority.
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
  acceptance, create command drafts, register futures routes, call Coinbase,
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
  validators, make validation gates ready, satisfy proof acceptance, create
  command drafts, register futures routes, call Coinbase, execute
  reconciliation, mutate state, or grant browser/BFF authority.
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
  acceptance, create command drafts, register futures routes, call Coinbase,
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
  acceptance, create command drafts, register futures routes, call Coinbase,
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
  validation gates ready, satisfy proof acceptance, create command drafts,
  register futures routes, call Coinbase, execute reconciliation, mutate state,
  or grant browser/BFF authority.
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
- Do not add futures command routes until backend guard/risk policy evidence,
  command contracts, approval/cap/audit gates, and contextless review are in
  place.
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
  command routes, create drafts, or grant browser/BFF authority. Route
  registration was the next missing backend contract gap through 6021-6040.
- Do not treat disabled route-registration contract metadata as a registered
  command route. M57 phases 6041-6060 define
  `api/v1/routes/futures.py::*_route_contract` refs as required/present
  disabled backend evidence only. Command route count, command draft count, and
  executable command count stay zero. The next missing backend gaps are
  `application/admin_api/live_execution.py::*_adapter_contract` refs; those
  refs do not construct adapters, call Coinbase, execute reconciliation, mutate
  futures state, or grant browser/BFF authority.
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
  insufficient to create command drafts, satisfy risk proof requirements,
  execute reconciliation, call Coinbase, or mutate futures/order/exchange
  state.
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
