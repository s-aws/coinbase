# Admin Module Capability Matrix

This matrix records what the enterprise Admin API and associated frontend can
support per module. It prevents spot-specific assumptions from becoming the
implicit platform model.

Current Release 0.1 scope: `7981-8000`.

Current Release 0.1 scope details: `7981-8000` pivots the admin platform to a
usable private operator MVP. Active work must clear named Release 0.1 blockers
or directly improve the frontend/API path for managing backend-supported
workflows. Unsupported or incomplete backend behavior must be surfaced as
`unsupported` or `not_modeled`, not hidden and not implemented in browser,
BFF, route-local FastAPI code, or a second trading path.

Completed futures/perpetual M57 scope: `7961-7980` added futures risk-proof
record validation remediation summary evidence on top of completed `7941-7960`
futures risk-proof record validation summary evidence. The
`risk_proof_record_validation_remediation_summaries` fields are backend-owned,
display-only, no-live, and do not treat record-validation remediation summary
presence as remediation execution, work item creation, record validator
registration, contextless review execution, validation gate configuration,
record validation, validation execution, replay passage, store creation,
append-only log configuration, idempotency binding, payload validation
registration, replay-guard registration, audit linkage, validation record
writes, proof record writes, proof record acceptance, proof acceptance
resolution, risk proof acceptance, command readiness passage, command
enablement clearance, approval passage, cap/guard passage, reconciliation
passage, command admission, Coinbase execution, reconciliation execution,
browser/BFF authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7941-7960` added futures risk-proof
record validation summary evidence on top of completed `7921-7940` futures
risk-proof record contract summary evidence. The
`risk_proof_record_validation_summaries` fields are backend-owned,
display-only, no-live, and do not treat record-validation summary presence as
record validation, validator registration, validation execution, replay
passage, store creation, append-only log configuration, idempotency binding,
payload validation registration, replay-guard registration, audit linkage,
proof record writes, proof record acceptance, proof acceptance resolution,
risk proof acceptance, command readiness passage, command enablement
clearance, approval passage, cap/guard passage, reconciliation passage,
command admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7921-7940` added futures risk-proof
record contract summary evidence on top of completed `7901-7920` futures
risk-proof payload field summary evidence. The
`risk_proof_record_contract_summaries` fields are backend-owned,
display-only, no-live, and do not treat record-contract summary presence as
store creation, append-only log configuration, idempotency binding, payload
validation registration, replay-guard registration, audit linkage, proof
record writes, proof record acceptance, proof acceptance resolution, risk
proof acceptance, command readiness passage, command enablement clearance,
approval passage, cap/guard passage, reconciliation passage, command
admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7901-7920` added futures risk-proof
payload field summary evidence on top of completed `7881-7900` futures
risk-proof contract summary evidence. The
`risk_proof_payload_field_summaries` fields are backend-owned, display-only,
no-live, and do not treat payload field summary presence as submitted payload
validation, payload validation registration, proof record writes, proof-route
registration, proof-writer enablement, acceptance criteria acceptance, proof
acceptance resolution, risk proof acceptance, command readiness passage,
command enablement clearance, approval passage, cap/guard passage,
reconciliation passage, command admission, Coinbase execution, reconciliation
execution, browser/BFF authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7881-7900` added futures risk-proof
contract summary evidence on top of completed `7861-7880` futures risk-proof
acceptance criterion summary evidence. The `risk_proof_contract_summaries`
fields are backend-owned, display-only, no-live, and do not treat proof
contract summary presence as proof-route registration, proof-writer
enablement, acceptance criteria acceptance, proof acceptance resolution, risk
proof acceptance, command readiness passage, command enablement clearance,
approval passage, cap/guard passage, reconciliation passage, command
admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7861-7880` added futures risk-proof
acceptance criterion summary evidence on top of completed `7841-7860` futures
risk-proof acceptance blocker summary evidence. The
`risk_proof_acceptance_criterion_summaries` fields are backend-owned,
display-only, no-live, and do not treat acceptance criterion summary presence
as acceptance criteria acceptance, proof acceptance resolution, risk proof
acceptance, proof-route registration, proof-writer enablement, command
readiness passage, command enablement clearance, approval passage, cap/guard
passage, reconciliation passage, command admission, Coinbase execution,
reconciliation execution, browser/BFF authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7841-7860` added futures risk-proof
acceptance blocker summary evidence on top of completed `7821-7840` futures
risk-proof record resolver summary evidence. The
`risk_proof_acceptance_blocker_summaries` fields are backend-owned,
display-only, no-live, and do not treat acceptance blocker summary presence as
proof acceptance resolution, risk proof acceptance, proof-route registration,
proof-writer enablement, command readiness passage, command enablement
clearance, approval passage, cap/guard passage, reconciliation passage,
command admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7821-7840` added futures risk-proof
record resolver summary evidence on top of completed `7801-7820` futures
command readiness-decision summary evidence. The
`risk_proof_record_resolver_summaries` fields are backend-owned,
display-only, no-live, and do not treat resolver summary presence as proof
acceptance resolution, risk proof acceptance, proof-route registration,
proof-writer enablement, command readiness passage, command enablement
clearance, approval passage, cap/guard passage, reconciliation passage,
command admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7801-7820` added futures command
readiness-decision summary evidence on top of completed `7781-7800` futures
command risk-proof requirement summary evidence. The
`readiness_decision_summaries` fields are backend-owned, display-only,
no-live, and do not treat readiness summary presence as command readiness
passage, readiness-decision clearance, command enablement clearance, approval
passage, cap/guard passage, reconciliation passage, command admission,
Coinbase execution, reconciliation execution, browser/BFF authority, or
spot-rule authority.

Completed futures/perpetual M57 scope: `7781-7800` added futures command
risk-proof requirement summary evidence on top of completed `7761-7780`
futures command semantic-guard summary evidence. The
`risk_proof_requirement_summaries` fields are backend-owned, display-only,
no-live, and do not treat risk-proof requirement summary presence as
risk-proof acceptance, proof-route registration, proof-writer enablement,
command enablement clearance, command readiness passage, approval passage,
cap/guard passage, reconciliation passage, command admission, Coinbase
execution, reconciliation execution, browser/BFF authority, or spot-rule
authority.

Completed futures/perpetual M57 scope: `7761-7780` added futures command
semantic-guard summary evidence on top of completed `7741-7760` futures
command request-field summary evidence. The `semantic_guard_summaries` fields
are backend-owned, display-only, no-live, and do not treat semantic-guard
summary presence as semantic guard evaluation, risk-proof acceptance,
proof-writer enablement, command enablement clearance, command readiness
passage, approval passage, cap/guard passage, reconciliation passage, command
admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7741-7760` added futures command
request-field summary evidence on top of completed `7721-7740` futures command
prerequisite summary evidence. The `request_field_summaries` fields are
backend-owned, display-only, no-live, and do not treat request-field summary
presence as request payload validation, validator registration, command
enablement clearance, command readiness passage, approval passage, cap/guard
passage, reconciliation passage, command admission, Coinbase execution,
reconciliation execution, browser/BFF authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7721-7740` added futures command
prerequisite summary evidence on top of completed `7701-7720` futures command
enablement contextless-review blocker summary evidence. The
`prerequisite_summaries` fields are backend-owned, display-only, no-live, and
do not treat prerequisite summary presence as prerequisite resolution, command
enablement clearance, contextless review passage for command readiness,
approval passage, cap/guard passage, reconciliation passage, command
admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7701-7720` added futures command
enablement contextless-review blocker summary evidence on top of completed
`7681-7700` futures request payload validation record execution-eligibility
resolution-plan step review input store record-validation remediation
dependency work-item claim-trace clearance-step review input store
record-validation check output schema field-constraint source-ref
validation-record acceptance contextless-review acceptance evidence. The
blocker-summary fields are backend-owned, display-only, no-live, and do not
treat contextless-review evidence presence as command enablement clearance,
contextless review passage for command readiness, approval passage, cap/guard
passage, reconciliation passage, command admission, Coinbase execution,
reconciliation execution, browser/BFF authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7681-7700` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-constraint
source-ref validation-record acceptance contextless-review acceptance evidence
on top of completed `7661-7680` futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
record-validation check output schema field-constraint source-ref
validation-record acceptance contextless-review evidence. The completed rows
are backend-owned, display-only, no-live, and do not treat
contextless-review acceptance presence as contextless-review acceptance
passage, contextless-review passage, validation-record acceptance passage,
source-ref record acceptance passage, source-ref acceptance passage,
source-ref declaration, constraint declaration, field-type declaration,
field-name declaration, field declaration, schema declaration, command
admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.
Focused backend and frontend validators passed for this slice, and blind
contextless review found no behavioral blockers after confirming the new
registry file must be included in the commit.

Completed futures/perpetual M57 scope: `7661-7680` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-constraint
source-ref validation-record acceptance contextless-review evidence on top of
completed `7641-7660` futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
record-validation check output schema field-constraint source-ref
validation-record acceptance evidence. The completed rows are backend-owned,
display-only, no-live, and do not treat contextless-review presence as
contextless-review passage, validation-record acceptance passage,
source-ref record acceptance passage, source-ref acceptance passage,
source-ref declaration, constraint declaration, field-type declaration,
field-name declaration, field declaration, schema declaration, command
admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7641-7660` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-constraint
source-ref validation-record acceptance evidence on top of completed `7621-7640` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-constraint source-ref record-acceptance evidence. The current
rows are backend-owned, display-only, no-live, and do not treat
validation-record acceptance presence as validation-record acceptance passage,
source-ref record acceptance passage, source-ref acceptance passage,
contextless review passage, source-ref declaration, constraint declaration,
field-type declaration, field-name declaration, field declaration, schema
declaration, command admission, Coinbase execution, reconciliation execution,
browser/BFF authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7621-7640` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-constraint
source-ref record-acceptance evidence on top of completed `7601-7620` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-constraint source-ref acceptance evidence.

Completed futures/perpetual M57 scope: `7601-7620` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-constraint
source-ref acceptance evidence on top of completed `7581-7600` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-constraint source-ref evidence.

Completed futures/perpetual M57 scope: `7561-7580` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-constraint
source-ref evidence on top of completed `7541-7560` futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-constraint
evidence. The completed rows are backend-owned, display-only, no-live, and do
not treat validation-check output-schema-field-constraint-source-ref presence
as source-ref declaration, constraint declaration, field-type declaration,
field-name declaration, field declaration, schema declaration, contextless
review passage, command admission, Coinbase execution, reconciliation
execution, browser/BFF authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7541-7560` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-constraint evidence on top
of completed `7521-7540` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-type evidence. The completed
rows are backend-owned, display-only, no-live, and do not treat
validation-check output-schema-field-constraint presence as constraint declaration,
field-type declaration, field-name declaration, field declaration, schema declaration,
source-ref declaration, contextless review passage, validation-check output schema
field-constraint readiness, command admission, Coinbase execution, reconciliation
execution, browser/BFF authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7521-7540` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-type evidence on top
of completed `7501-7520` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field-name evidence. The completed
rows are backend-owned, display-only, no-live, and do not treat
validation-check output-schema-field-type presence as field-type declaration,
field declaration, schema declaration, source-ref declaration, contextless
review passage, validation-check output schema field-type readiness, command
admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7481-7500` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema field evidence on top
of completed `7461-7480` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema evidence.

Completed futures/perpetual M57 scope: `7461-7480` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check output schema evidence on top
of completed `7441-7460` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check input schema field evidence.

Completed futures/perpetual M57 scope: `7441-7460` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check input schema field evidence on top
of completed `7421-7440` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check input schema evidence.

Completed futures/perpetual M57 scope: `7421-7440` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check input schema evidence on top of
completed `7401-7420` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check contract evidence. The completed
rows are backend-owned, display-only, no-live, and do not treat
validation-check input-schema presence as schema declaration, field
declaration, type declaration, constraint declaration, acceptance contract
declaration, contextless review passage, validation-check contract readiness,
command admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7401-7420` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check contract evidence on top of
completed `7381-7400` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check evidence. The completed rows are
backend-owned, display-only, no-live, and do not treat validation-check
contract presence as contract declaration, schema declaration, validation-gate
declaration, replay-guard declaration, evidence-record declaration,
idempotency binding, contextless review passage, record acceptance, command
admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7381-7400` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation check evidence on top of completed
`7361-7380`
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency work-item
claim-trace clearance-step review input store record-validation evidence. The
completed rows are backend-owned, display-only, no-live, and do not treat
clearance-step review input store record-validation check presence as
validator configuration, validation check execution, validation gate readiness,
replay gate readiness, schema availability, append-only log availability,
idempotency binding, payload binding, record acceptance, record validation,
command admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7361-7380` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-validation evidence on top of completed `7341-7360`
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency work-item
claim-trace clearance-step review input store record-contract evidence. The
completed rows are backend-owned, display-only, no-live, and do not treat
clearance-step review input store record-validation presence as validator
configuration, validation gate readiness, replay gate readiness, schema
availability, append-only log availability, idempotency binding, payload
binding, record acceptance, record validation, command admission, Coinbase
execution, reconciliation execution, browser/BFF authority, or spot-rule
authority.

Completed futures/perpetual M57 scope: `7341-7360` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store record-contract evidence on top of completed `7321-7340`
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency work-item
claim-trace clearance-step review input store requirement evidence. Those
rows are backend-owned, display-only, no-live, and do not treat
clearance-step review input store record-contract presence as record contract
availability, record schema availability, append-only log availability,
idempotency binding, payload schema validation, replay protection, store
availability, writer availability, write allowance, record acceptance, record
validation, command admission, Coinbase execution, reconciliation execution,
browser/BFF authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7321-7340` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input store requirement evidence on top of completed `7301-7320`
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency work-item
claim-trace clearance-step review input evidence. Those rows are
backend-owned, display-only, no-live, and do not treat clearance-step review
input store requirement presence as store availability, writer availability,
record-key availability, validation-gate readiness, replay-gate readiness,
review-input acceptance, review-input validation, review gate passage,
clearance-step review completion, clearance-step completion, command
admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7301-7320` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input evidence on top of completed `7281-7300` futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review evidence. Those rows are backend-owned, display-only, no-live, and do
not treat clearance-step review input presence as review-input acceptance,
review-input validation, review gate passage, clearance-step review
completion, clearance-step completion, command admission, Coinbase execution,
reconciliation execution, browser/BFF authority, or spot-rule authority.

Completed futures/perpetual M57 scope: `7281-7300` adds futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review evidence on top of completed `7261-7280` futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance step
evidence, completed `7241-7260` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance plan
evidence, completed `7221-7240` futures request payload validation
record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim trace evidence,
completed `7201-7220` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item evidence, and completed
`7181-7200` futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency evidence, completed `7161-7180`
futures request payload validation record execution-eligibility
resolution-plan step review input store record-validation remediation evidence,
completed `7141-7160`
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation evidence and completed `7121-7140`
futures
request payload validation record execution-eligibility resolution-plan step
review input store record-contract evidence and completed `7101-7120` futures request
payload validation record execution-eligibility resolution-plan step review
input store requirement evidence, completed `7081-7100` futures request payload
validation record execution-eligibility resolution-plan step review input
evidence, completed
`7061-7080` execution-eligibility resolution-plan step review evidence,
completed `7041-7060` execution-eligibility resolution-plan step evidence,
completed `7021-7040` execution-eligibility resolution-plan evidence,
completed `7001-7020` execution-eligibility semantic closure evidence,
completed `6981-7000` reconciliation semantics, completed `6961-6980` cancel
semantics, completed `6941-6960` order semantics, completed `6921-6940`
funding semantics, completed `6901-6920` close-only semantics, completed
`6881-6900` reduce-only semantics, completed `6861-6880` liquidation
semantics, completed `6841-6860` collateral semantics, completed `6821-6840`
margin semantics, and completed `6801-6820` position semantics. These rows are
backend-owned, display-only, no-live, and do not treat resolution plan step
review input store record-validation remediation dependency work-item
claim-trace clearance-step review presence as clearance-step review completion,
review input presence, review gate passage, claim-trace clearance, command
admission, Coinbase execution, reconciliation execution, browser/BFF
authority, or spot-rule authority. They also do not treat resolution plan step
review input store record-validation remediation dependency work-item
claim-trace presence,
resolution plan step review input store record-validation remediation dependency work-item
presence,
review input store record-validation remediation dependency presence,
resolution plan step review input store record-validation remediation presence,
resolution plan step review input store record-validation presence, resolution
plan step review input store record-contract presence, resolution plan step
review input store requirement presence, resolution plan step review input
presence, or resolution plan step review presence as blocker resolution, create
dependency graphs, create work items, claim work, create claimable work items, register claim ledgers, accept
owner review, accept contextless review, write evidence, create claim traces, make claim traces ready, allow or resolve claims, create stores,
configure writers, create record keys, enable validation or replay gates,
accept runtime evidence, accept reconciliation
semantics, bind live reconciliation/audit evidence, execute reconciliation,
accept cancel semantics, bind live active-placement or audit evidence, submit
Coinbase cancellation, accept order semantics, bind live account/order evidence,
accept funding semantics, bind live account/funding evidence, accept
close-only semantics, bind live account/close-only evidence, accept
reduce-only semantics, bind live account/reduce-only evidence, accept
liquidation semantics, bind live account/risk evidence, accept collateral
semantics, bind live account/collateral evidence, accept margin semantics,
accept position semantics, bind live position evidence, accept or bind runtime
evidence, define executable futures semantics, pass contextless reviews as
execution authority, validate payloads, resolve blockers, admit commands, call
Coinbase, execute reconciliation, mutate futures/order/exchange state, or grant
browser/BFF authority. They also do not treat claim-trace clearance-step
presence as clearance-step execution, clearance-step completion,
clearance-step review readiness, claim-trace clearance, Coinbase execution, or
futures/order/exchange mutation authority. They also do not treat claim-trace clearance-plan
presence as claim-trace clearance, clearance-plan creation, clearance-plan
readiness, claim allowance, claim resolution, claim-review acceptance,
contextless review acceptance, evidence recording, reconciliation execution,
Coinbase execution, or futures/order/exchange mutation authority.

Machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance step evidence.
Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim-trace clearance plan evidence.
Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item claim trace evidence.
Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency work-item evidence.
Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation dependency evidence.
Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation remediation evidence.
Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-validation evidence.
Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store record-contract evidence.
Carried-forward machine-check phrase: futures request payload validation record execution-eligibility resolution-plan step review input store requirement evidence.
Boundary token: dependency work-item claim-trace clearance-step presence is not clearance-step execution.
Boundary token: dependency work-item claim-trace clearance-plan presence is not claim-trace clearance.
Boundary token: resolution plan step review input store record-validation remediation dependency work-item claim-trace presence is not dependency resolution.
Boundary token: resolution plan step review input store record-validation remediation dependency work-item presence is not dependency resolution.
Boundary token: resolution plan step review input store record-validation remediation dependency presence is not blocker resolution.
Boundary token: resolution plan step review input store record-validation remediation presence is not blocker resolution.
Boundary token: resolution plan step review input store record-validation presence is not blocker resolution.
Boundary token: resolution plan step review input store record-contract presence is not blocker resolution.
Boundary token: do not create dependency graphs.

| Module | Read-only views | Command drafts | Dry-submit | Live execution | Backend namespace | Identity key | Product-specific rules | Required gates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Admin / System Health | Implemented for bootstrap, health, session, OIDC readiness, capabilities, CSRF, live-enablement readiness, enterprise-readiness evidence including lifecycle support classification, approval lifecycle reads, admission audit reads, cap/guard decision reads, reconciliation plan reads, guard/risk policy, audit workbench, release gate, spot/direct-order recovery gate, fill-ledger health, and frontend fixtures | Implemented as backend-owned approval request/decision/revoke lifecycle mutations, admission audit record mutations, cap/guard decision record mutations, reconciliation plan record mutations, and runtime pause/resume/drain lifecycle commands; lifecycle support is backend-owned and not trading commands | Approval lifecycle, admission audit, cap/guard decision, and reconciliation plan mutations are idempotent/audited backend records only and do not dry-submit Coinbase commands; lifecycle support forwards only backend-owned pause/resume/drain runtime commands and does not forward unsupported or not-modeled process-control commands | Live-enablement and enterprise-readiness routes are read-only evidence; lifecycle pause/resume/drain mutate only `RuntimeController` state and do not enable Coinbase execution or mark the runtime stopped; approval lifecycle, admission audit, cap/guard decision, and reconciliation plan routes do not enable live execution | `/api/v1/admin/*` | Request id, correlation id, actor id, approval request id, approval id, admission audit id, cap/guard decision id, reconciliation plan id, lifecycle action, backend policy ids, audit ids, and module-specific identity when reported | Platform primitive; no trading rules; lifecycle support displays `status` through health, exposes `pause`/`resume`/`drain` only through backend-owned Admin API command routes, displays `start` as `unsupported`, and displays `stop` as `not_modeled`; it must not call dashboard WebSockets, add route-local process control outside `AdminApiCommandService`, grant BFF process authority, infer support from internal controller methods, invoke stop hooks, mark `STOPPED`, or call Coinbase; live-enablement reports cap/approval/guard/audit/reconciliation requirements, controlled-live preflight check evidence, route-specific approval snapshot requirements, approval-store contract requirements, live-admission audit trail requirements, route-specific cap/guard contract requirements, live execution adapter contract evidence, and M46 normalized live readiness precondition evidence; command responses report M34 route-bound admission decision evidence; M35 persists that evidence in append-only Admin API audit events and read-only Audit Workbench rows; M36 adds backend-owned append-only approval-store infrastructure while approval snapshots remain absent and live execution remains disabled; M37 adds backend-only approval snapshot resolver infrastructure without approving commands or enabling live execution; M38 wires live-disabled command admission evidence to that resolver so snapshot-present/missing status is auditable without live authority; M39-M41 wire live-disabled command admission evidence to backend-owned audit, cap/guard, and reconciliation proof without browser authority or live execution; M42-M46 define disabled live execution service, adapter, intent, and readiness precondition evidence without adding a live switch, browser authority, BFF execution authority, or Coinbase calls; M47 adds enterprise-readiness `functionality_inventory`; M48 adds enterprise-readiness `mutation_taxonomy`; M49 adds backend-owned approval lifecycle request/decision/revoke/expiry/snapshot-linking contracts and the `admin.approval_lifecycle` mutation taxonomy row; M50 adds backend-owned cap/guard decision execution records and the `admin.cap_guard_decisions` mutation taxonomy row; M51 adds backend-owned admission audit records and the `admin.admission_audits` mutation taxonomy row; M52 adds backend-owned reconciliation plan records and the `admin.reconciliation_plans` mutation taxonomy row without reconciliation execution or exchange/order-state mutation; browser approval, browser/BFF audit, browser/BFF guard evaluation, and browser/BFF reconciliation proof remain insufficient for execution | Admin API contract tests, frontend release gate when consumed |
| Spot Operations | Implemented for readiness, sweep status, P/L, P/L checkpoint list/detail evidence, cost basis, campaign status, direct-order audit, recovery preview/apply-review/rollback-plan/reconciliation-proof read contracts, fail-closed reconciliation execution boundary evidence, state-repair taxonomy, repair-target, pre-apply snapshot, dry-run repair-plan, guarded repair-result, and completion-state recovery evidence, command-suite readiness with proof routes, readiness preconditions, coverage gaps, typed coverage-gap evidence-route linkage, proof-record readback, snapshot-record readback, recovery execution journal readback, order reads, and frontend read-model interactions | Implemented as no-live-by-default HTTP contracts for manual order, cancel by `client_order_id`, campaign execution, sweep automation keyed by `sweep_config_id`, backend-owned recovery apply/rollback execution journal records, backend-owned guarded local repair-result records, backend-owned recovery exchange-state-proof/exchange-state-snapshot/reconciliation-proof record contracts keyed by `client_order_id`, and a backend-owned fail-closed recovery reconciliation execution boundary route keyed by `client_order_id`; manual order and cancel are explicit route-scoped configured live-service exceptions only after exact backend admission gates pass; P/L tracking has local checkpoint records with average-cost review, audit-link evidence, recovery-read linkage, reconciliation-plan read linkage, and read-only recovery repair evidence, while the reconciliation executor, live Coinbase read authority, full reconciliation execution, and full sweep scheduler/recovery execution remain explicit command-suite coverage gaps | Implemented for tests, smokes, gated no-live frontend review, and manual Spot order/cancel forward-only command submission when backend capability and admission evidence explicitly allow it; UI may call canonical backend/BFF helpers only when capability evidence is matched and frontend-safe; P/L checkpoint records, recovery proof records, recovery snapshot records, recovery execution journal records, recovery repair result records, and recovery preview/apply-review/rollback-plan/reconciliation-proof repair and execution-boundary evidence are backend-owned local-state/read evidence, not browser authority | Manual Spot order/cancel are no-live by default and may reach the shared backend live branch only after exact backend auth/RBAC, idempotency, approval, admission-audit, cap/guard, reconciliation, manual acknowledgement, configured live-service, REST-client, and event-stream gates pass; cancel calls only `cancel_order(client_order_id)`. HTTP recovery apply/rollback command routes persist append-only local execution journal evidence and guarded local repair-result evidence only after exact backend prerequisites match; they do not mutate order/exchange state, read Coinbase, or submit Coinbase REST orders. Proof and snapshot POST routes persist append-only local evidence only after backend prerequisites match; snapshot records keep Coinbase read/source-trust flags false in this range. `GET /api/v1/spot/command-suite`, `GET /api/v1/spot/recovery/preview`, `GET /api/v1/spot/recovery/apply-review`, `GET /api/v1/spot/recovery/rollback-plan`, and `GET /api/v1/spot/recovery/reconciliation-proof` are read-only coverage/contract evidence and never live authority; the reconciliation-proof readback exposes blocked execution-boundary rows and the disabled `POST /api/v1/spot/recovery/reconciliation-executions` route/service boundary; P/L checkpoint routes never submit Coinbase orders; legacy approved tools remain outside frontend authority | `/api/v1/spot/*`, `/api/v1/orders`, `/api/v1/orders/{client_order_id}` | `client_order_id`, `sweep_config_id`, `checkpoint_id`; exchange `order_id` evidence only | spot-only USDC scope, wallet inventory, no shorting, cost basis, average cost, lot authority, known profitable inventory; P/L checkpoints, average-cost review evidence, audit-link evidence, recovery-read linkage, recovery proof records, recovery snapshot records, recovery execution journal records, recovery repair result records, recovery read contracts, recovery repair evidence, reconciliation execution boundary evidence, and reconciliation-plan read linkage are not tax accounting, profitability proof, sell authority, browser guard evidence, order/exchange-state mutation, reconciliation execution, or Coinbase calls; these rules must not become platform defaults | Admin API regression, spot readiness regression, frontend release gate, contextless spot-order review |
| Futures / Perpetuals | Implemented as backend read-only account, risk, position, command-suite contract, risk-proof record list/detail readbacks, request-field metadata, semantic guard metadata, semantic guard evidence-route linkage, command readiness-decision evidence, readiness closure-plan evidence routes, risk proof requirement evidence, risk proof route/writer contract evidence, risk proof payload-field contract evidence, risk proof record/store contract evidence, risk proof record-validation evidence, risk proof record-validation remediation evidence, risk proof record-validation remediation dependency evidence, risk proof record-validation remediation dependency work-item evidence, risk proof record-validation remediation dependency work-item claim-trace evidence, risk proof record-validation remediation dependency work-item claim-trace clearance-plan evidence, risk proof record-validation remediation dependency work-item claim-trace clearance-step evidence, risk proof record-validation remediation dependency work-item claim-trace clearance-step review evidence, risk proof record-validation remediation dependency work-item claim-trace clearance-step review input evidence, risk proof record-validation remediation dependency work-item claim-trace clearance-step review input store requirement evidence, risk proof record-validation remediation dependency work-item claim-trace clearance-step review input store record-contract evidence, risk proof record-validation remediation dependency work-item claim-trace clearance-step review input store record-validation evidence, risk proof acceptance-criteria evidence, command enablement blocker summary evidence, command enablement sequence evidence, command enablement sequence command-trace evidence, route-bound command draft evidence, and request payload contract registry evidence with enterprise frontend read model | Trading command drafts are modeled as no-live route-bound evidence for placement, close/reduce, cancel by `client_order_id`, and reconciliation. Request fields are registry-backed by `FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS` and `iter_futures_request_payload_contracts`; route/draft flags are true while execution remains false; `POST /api/v1/futures/risk-proofs` remains append-only local proof-evidence mutation through `record_futures_risk_proof` and is not proof acceptance or command readiness | Futures trading dry-submit is not yet modeled; command draft routes, request payload contracts, and proof-record POST persist local evidence only and must not be treated as dry-submit for placement, close/reduce, cancel, or reconciliation | Not approved through frontend | `/api/v1/futures/*` for reads, no-live command drafts, and local proof evidence | `position_key` for positions and reconciliation, `product_id` for placement contract scope, `client_order_id` for cancel contract scope, and `futures_risk_proof_id` for proof-record readbacks; configured product scope and observed position scope are separate | Must not import spot-only rules; close/reduce sides are backend-derived from observed position side, not exchange-observed order flags; funding semantics are modeled as disabled display evidence only and are not accepted execution authority; `/api/v1/futures/risk-proofs` records append-only local proof evidence only and does not accept risk proof requirements, satisfy command readiness, execute reconciliation, call Coinbase, mutate futures/order/exchange state, or grant browser/BFF authority; command draft routes return disabled command responses and do not bind live adapters, submit or cancel Coinbase orders, acknowledge exchange orders, execute reconciliation, mutate futures/order/exchange state, accept proof records as command readiness, or grant browser/BFF authority; request payload contract registry evidence does not validate command request payloads, register payload validators, call Coinbase, execute reconciliation, mutate futures/order/exchange state, or grant browser/BFF authority; command-suite route reports forbidden spot wallet, no-shorting, USDC quote, cost-basis, and inventory-lot assumptions as non-authority; route/draft flags are true while execution, Coinbase activity, reconciliation execution, futures state mutation, browser authority, BFF authority, and spot-rule authority remain false | Admin API contract tests, frontend route coverage, frontend release gate, contextless non-spot review |
| Stealth Orders | Implemented as backend read-only stealth lifecycle list/detail routes, detail-route active-placement audit evidence, detail-route mutation-claim audit evidence, detail-route recovery-proof evidence, reveal-trigger proof evidence, detail-route reveal-trigger audit evidence, detail-route reveal submission-adapter audit evidence, detail-route reveal reconciliation audit evidence, and read-only command-suite readiness evidence | Implemented as live-disabled HTTP contracts for create, reveal, move, cancel, recovery, and reconciliation by `stealth_order_id`, movement/repricing reprice by `stealth_order_id`, backend-owned recovery-proof record evidence by `stealth_order_id`, and backend-owned reveal-trigger proof record evidence by `stealth_order_id` | Implemented for tests, smokes, and gated no-live frontend review; UI may call canonical backend/BFF stealth create, reveal, move, cancel, recovery, reconciliation, reprice dry-submit, recovery-proof record, and reveal-trigger proof record helpers only when capability evidence is matched, `frontend_safe=true`, and `live_enabled=false`; detail active-placement audit, detail mutation-claim audit, detail recovery-proof readback, reveal-trigger proof readback, detail reveal-trigger audit, detail reveal submission-adapter audit, detail reveal reconciliation audit, and command-suite evidence are display-only | HTTP stealth create/reveal/move/cancel/recovery/reconciliation return `501` until lifecycle/trigger, mutation-claim, active-placement, exchange handling, cancel/replace, recovery, and reconciliation gates are complete; recovery-proof and reveal-trigger-proof POST routes persist append-only no-live evidence only after route-bound admission prerequisites match and do not repair state, roll back state, evaluate triggers, call `should_trigger_reveal`, call `reveal_order_slice`, execute reconciliation, call Coinbase, submit/cancel orders, acquire/release mutation claims, invoke managers, or mutate order/lifecycle/exchange state; read-only detail and command-suite evidence never prove live authority | `/api/v1/stealth/orders`, `/api/v1/stealth/orders/{stealth_order_id}`, `/api/v1/stealth/orders/{stealth_order_id}/recovery-proof`, `/api/v1/stealth/orders/{stealth_order_id}/recovery-proofs`, `/api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proof`, `/api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proofs`, `/api/v1/stealth/command-suite`, `/api/v1/stealth/orders/{stealth_order_id}/reveal`, `/api/v1/stealth/orders/{stealth_order_id}/move`, `/api/v1/stealth/orders/{stealth_order_id}/cancel`, `/api/v1/stealth/orders/{stealth_order_id}/recovery`, `/api/v1/stealth/orders/{stealth_order_id}/reconciliation`; dashboard remains compatibility surface | `stealth_order_id`; active placement client id, exchange ids, runtime mutation-claim state, reveal-condition state, trigger evidence refs, recovery evidence refs, recovery proof ids, reveal-trigger proof ids, reconciliation plan ids, and reconciliation proof ids are evidence only | Must preserve exchange-reality state, flat hierarchy, mutation claims, reveal trigger boundaries, and placement lifecycle rules; no spot wallet/cost-basis assumptions; no active-placement or exchange-id command keys; recovery and reconciliation command contracts are fail-closed and do not execute recovery repair, rollback, reconciliation, Coinbase reads, Coinbase orders, lifecycle mutation, or exchange-state mutation; recovery-proof records are append-only no-live evidence and become command prerequisites only when exact route/method/service/actor/operator/idempotency/payload-hash/admission links match; reveal-trigger proof records are append-only no-live evidence and become reveal prerequisites only under the same exact-context matching rule; detail active-placement audit does not prove Coinbase truth, cancel/replace, reconciliation, or browser/BFF enablement; detail mutation-claim audit does not acquire/release claims or prove command authority; detail recovery-proof readback does not repair state, roll back state, execute reconciliation, call Coinbase, mutate state, or prove browser authority; detail reveal-trigger proof readback does not evaluate triggers, call `should_trigger_reveal`, call `reveal_order_slice`, call Coinbase, mutate state, or prove browser authority; detail reveal-trigger audit does not evaluate triggers, call `should_trigger_reveal`, call `reveal_order_slice`, or prove reveal authority; detail reveal submission-adapter audit does not call `reveal_order_slice`, create active placements, submit/cancel Coinbase orders, read Coinbase, execute reconciliation, mutate lifecycle state, or prove reveal authority; detail reveal reconciliation audit does not read Coinbase, write proof records, execute reconciliation, mutate order/lifecycle state, or prove reveal authority; revealed orders cannot be locally hidden/cancelled/moved without exchange proof | Stealth regression, Admin API contract tests, frontend release gate, command dry smoke, contextless module review |
| Order Movement / Repricing | Implemented as backend movement/repricing evidence routes and enterprise frontend read model | `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice` live-disabled | Implemented as live-disabled `501` dry-submit evidence for tests, smokes, and gated no-live frontend review; UI may call the canonical backend/BFF reprice dry-submit helper only when capability evidence is matched, `frontend_safe=true`, and `live_enabled=false` | Not approved through frontend | `/api/v1/movement-repricing/*` for reads plus live-disabled reprice draft; dashboard remains compatibility surface | `client_order_id` for order/placement evidence; `stealth_order_id` for stealth lifecycle and reprice draft; exchange ids are evidence only | Must preserve move/reprice claim locks and cannot hide revealed live placements without exchange handling; the reprice draft must not clear cooldowns or invoke live repricing; cancel-class permission is intentional because future live repricing is cancel/replace-shaped | Movement/repricing regression, Admin API contract tests, frontend release gate, contextless review |
| Campaigns / Sweeps | Spot campaign and sweep reads implemented under Spot Operations | Spot campaign execution and spot sweep automation run routes exist but are live-disabled | Spot campaign and sweep automation dry-submit paths exist for tests, smokes, and gated no-live frontend review; UI keeps `dry_run=true` and requires matched live-disabled capability evidence before request | Not approved through frontend | `/api/v1/spot/campaign/*` and `/api/v1/spot/sweep/automation-runs` today; other campaign/sweep namespaces require backend contract first | Campaign id, sweep config id, plus backend-defined order identity | Spot campaign/sweep rules are spot-only; non-spot campaigns need separate domain contracts | Admin API regression, frontend command smoke, contextless review |
| P/L, Ledger, And Reconciliation | Implemented for spot P/L, Spot P/L checkpoint and average-cost review evidence, audit-link evidence, recovery-read linkage, recovery preview/apply-review/rollback-plan/reconciliation-proof read contracts, recovery repair evidence, recovery proof record readback, recovery snapshot record readback, recovery execution journal readback, fail-closed reconciliation execution boundary evidence, reconciliation-plan read linkage, and fill-ledger health evidence | Implemented only as backend-owned Spot P/L checkpoint, Spot recovery proof local-state records, Spot recovery snapshot local-state records, Spot recovery execution journal local-state records, and read-only recovery contract/repair/execution-boundary evidence; the fail-closed reconciliation-execution boundary is modeled, but actual reconciliation execution is not implemented or enabled | Checkpoint, recovery proof, recovery snapshot, recovery execution journal records, recovery repair evidence, and execution-boundary rows are idempotent/audited backend evidence only and recovery read contracts are read-only; none dry-submit Coinbase commands | Not applicable through frontend | `/api/v1/spot/sweep/pnl`, `/api/v1/spot/pnl/checkpoints`, `/api/v1/spot/pnl/checkpoints/{checkpoint_id}`, `/api/v1/spot/recovery/preview`, `/api/v1/spot/recovery/apply-review`, `/api/v1/spot/recovery/rollback-plan`, `/api/v1/spot/recovery/reconciliation-proof`, `/api/v1/spot/recovery/apply-executions`, `/api/v1/spot/recovery/rollback-executions`, `/api/v1/spot/recovery/exchange-state-proofs`, `/api/v1/spot/recovery/exchange-state-snapshots`, `/api/v1/spot/recovery/reconciliation-executions`, `/api/v1/spot/recovery/reconciliation-proofs`, `/api/v1/admin/recovery-gate`, `/api/v1/admin/fill-ledger-health`, `/api/v1/admin/reconciliation/plans`, `/api/v1/admin/reconciliation/plans/{plan_id}` today | Backend-defined ledger ids, `checkpoint_id`, `audit_id`, and `client_order_id` where applicable | Spot operational P/L, average-cost review evidence, audit-link evidence, recovery-read linkage, recovery proof records, recovery snapshot records, recovery execution journal records, recovery read contracts, recovery repair evidence, reconciliation execution boundary evidence, and reconciliation-plan read linkage are not tax accounting; checkpoint, recovery proof, recovery snapshot, recovery execution journal, recovery repair evidence, and execution-boundary contracts are not sell authority, profitability proof, browser guard evidence, state repair authority, order/exchange-state mutation, reconciliation execution, or Coinbase calls; futures/perpetual P/L must be position/collateral aware | Backend read/local-state contract tests and frontend adapter tests |
| Guard / Risk Policy | Implemented as backend read-only guard/risk policy evidence and consumed by the enterprise frontend | Not a frontend command module | Not applicable | Not approved through frontend | `/api/v1/admin/guard-risk-policy` | Backend-defined policy ids, product id filter, correlation ids, and audit ids | Browser must not calculate wallet, margin, guard, profitability, or live approval authority; route does not fetch Coinbase wallets | Guard regression, Admin API contract tests, frontend release gate, contextless review |
| Audit Workbench | Implemented as backend read-only cross-module route, command, correlation, audit, and exchange evidence | Not a frontend command module | Not applicable | Not approved through frontend | `/api/v1/admin/audit-workbench` | `client_order_id`, `stealth_order_id`, or `position_key` depending on module; exchange ids are evidence only | Browser must not mutate audit history, call Coinbase, replay commands, or treat exchange ids as tracking/cancel keys | Admin API contract tests, frontend route coverage, frontend release gate, contextless review |

## Stealth Manager-Invocation Policy Note

The Stealth Orders row includes manager-invocation policy evidence through
`GET /api/v1/stealth/orders/{stealth_order_id}/manager-invocation-policy` and
`POST /api/v1/stealth/orders/{stealth_order_id}/manager-invocation-policy-proofs`.
The GET route is read-only backend evidence. The POST route records
append-only local proof evidence after backend guarded-context validation. It
does not invoke `StealthOrderManager`, call Coinbase, cancel or replace active
placements, execute reconciliation, mutate lifecycle/order/exchange state, or
create browser/BFF authority.

## Update Rules

- Add or update a row before adding a module route or frontend module.
- Use `Not yet modeled` instead of vague planned support.
- Keep spot-only rules in the Spot Operations row or spot-specific docs.
- Add backend contracts before frontend read models, drafts, dry-submit, or
  live UI.
- Keep `GET /api/v1/admin/enterprise-readiness` command-gap evidence aligned
  with this matrix when a module moves between unsupported, not modeled,
  live-disabled draft, or live-approved status.
- Keep enterprise-readiness module registry fields aligned with this matrix:
  `module_id`, `primary_owner`, contract refs, docs, identity keys, and
  spot-rule boundary must change with module ownership or scope.
- Keep enterprise-readiness `functionality_inventory` rows aligned with this
  matrix whenever a workflow becomes admin-exposed, draft/live-disabled,
  backend-contract-required, unsupported, or compatibility-only.
- Keep enterprise-readiness `mutation_taxonomy` rows aligned with this matrix
  and `ADMIN_API_ROUTE_INVENTORY` whenever a command route, legacy command
  surface, required permission, identity key, idempotency rule, approval rule,
  cap/guard rule, audit rule, reconciliation rule, or owning backend service
  changes.
- Keep route inventory and capability `module_id` evidence aligned with this
  matrix whenever routes move between modules.
- Keep enterprise-readiness `action_posture` counts aligned with backend
  route-inventory `module_id` ownership; do not use path-prefix grouping as
  module authority.
- Keep Enterprise Command Gap Triage aligned with enterprise-readiness
  command gaps and backend capability rows. It is read-only triage evidence,
  not a command backlog, approval surface, or browser authority source.
- Keep Enterprise Module Capability Linkage aligned with backend capability
  rows and enterprise-readiness command routes. It is read-only evidence for
  command workflow posture, not a separate source of command authority.
- Keep live-enablement governance linkage aligned with backend capability
  rows, enterprise-readiness module rows, and route-inventory live-shaped
  command paths. It is read-only evidence for gate posture and blockers, not
  approval for live execution.
- Keep controlled-live preflight checks aligned with live-enablement path
  rows. They are readiness evidence only; they must not become a browser
  approval path, live switch, command route, or reconciliation substitute.
- Keep route-specific approval snapshot evidence aligned with live-enablement
  path rows. It is missing-approval evidence only; it must not become
  approval storage, browser approval, command authority, Coinbase execution,
  or reconciliation evidence.
- Keep approval-store contract evidence aligned with live-enablement path
  rows. After M36 it may report configured backend store infrastructure, but
  it must not become an approval endpoint, browser approval, command
  authority, Coinbase execution, or reconciliation evidence.
- Keep approval snapshot resolver infrastructure backend-only. It may derive
  immutable evidence from exact unexpired approval-store records, but it must
  not become approval mutation, browser approval, command authority, Coinbase
  execution, or reconciliation evidence.
- Keep approval lifecycle routes backend-owned and separate from command
  execution. They may request, approve/reject, revoke, and display expiring
  snapshot evidence, but browser approval, BFF forwarding, or a linked
  approval snapshot is not sufficient live execution authority.
- Keep live-admission audit trail evidence aligned with live-enablement path
  rows. It is missing append-only backend audit evidence only; it must not
  become audit storage, approval storage, browser approval, command authority,
  Coinbase execution, or reconciliation authority.
- Keep route-specific cap/guard contract evidence aligned with
  live-enablement path rows. It is missing backend cap/guard decision evidence
  only; it must not become guard execution, browser wallet/profitability
  authority, browser approval, command authority, Coinbase execution, or
  reconciliation authority.
- Keep command admission decision evidence aligned with existing live-disabled
  command responses and the shared command service. It is backend-owned
  route/payload blocker evidence only; it must not become browser approval,
  command authority, Coinbase execution, or reconciliation authority.
- Keep persisted command admission audit evidence aligned with existing
  append-only Admin API audit events and read-only Audit Workbench rows. It
  must not become audit mutation, browser approval, command authority,
  Coinbase execution, or reconciliation authority.
- Keep command admission cap/guard proof evidence aligned with backend-owned
  append-only cap/guard decision rows and existing live-disabled command
  responses. It must not become guard mutation, browser wallet/profitability
  authority, browser approval, command authority, Coinbase execution, or
  reconciliation authority.
- Keep command admission reconciliation plan proof evidence aligned with
  backend-owned append-only reconciliation plan rows and existing
  live-disabled command responses. It must not become reconciliation
  execution, browser approval, command authority, Coinbase execution, or live
  admission authority.
- Keep command admission live execution service boundary evidence aligned with
  existing live-disabled command responses. It must not become a live switch,
  browser approval, command authority, Coinbase execution, or BFF execution
  authority.
- Keep disabled live execution service descriptor evidence non-executable. It
  may expose service state to admission evidence, but must not expose create,
  cancel, submit, execute, browser, BFF, or Coinbase authority methods.
- Keep live execution adapter contract evidence aligned with live-enablement
  path rows and shared `AdminApiCommandService` methods. It may name the
  future backend adapter boundary, but must not become route-local execution,
  browser approval, BFF execution authority, Coinbase execution, or
  order/exchange-state mutation.
- Keep live readiness precondition evidence aligned with live-enablement path
  rows. It must be derived from existing evidence and must not become a new
  preflight endpoint, command admission call, browser approval, BFF execution
  authority, Coinbase execution, or route-local executor.
- Update route inventory, OpenAPI, examples, frontend association, and
  contextless review prompts when a module changes status.
