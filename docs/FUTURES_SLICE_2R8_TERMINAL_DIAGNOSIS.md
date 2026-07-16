# Futures Slice 2R8 Terminal Diagnosis

## Terminal State

Slice 2R8 is consumed, terminal `blocked`, and cannot be retried. It produced
no accepted Preview evidence and grants no Slice 3 or exchange authority.

On 2026-07-16 UTC, the synthetic malformed-key unit test entered a fixed-path
producer because its helper patched the generation path tuple but not the
concrete R8 constant used by the store. The test used a synthetic invalid
secret result and a mocked request boundary. No AWS service or real Coinbase
request ran.

## Immutable Binding

The fixed artifact must remain byte-for-byte unchanged:

- name: `futures_exact_no_live_preview_slice_2r8.jsonl`
- SHA-256: `b32aba4868f08ee7a44f19ceacbcf42cb7e4d70da1552f2d8b333ef59ddc8696`
- mode: `0400`
- size: `14921`
- device/inode: `2096/400341`
- link count: `1`
- mtime ns: `1784160315297279427`

R8's SHA-256 remains a documented preexisting binding and is not recomputed.
Runtime validation hash-binds the exact immutable R1-R7 chain, then verifies
R8 only through two stable `lstat` metadata snapshots. R8 is never opened,
read, hashed again, deserialized, exposed, normalized, or reconstructed. The
Admin API synthesizes a separately typed forensic readback only after that
documented-SHA/stat-metadata binding validates.

## Sanitized Failure Boundary

Independent diagnosis records only this allowlisted classification:

- blocker: `preflight_or_preview_blocked:Exception`
- localized boundary: `api_key_permissions_read_boundary`
- entered read boundaries: API-key permissions `1`; all other fixed reads `0`
- real AWS service calls: `0`
- real Coinbase requests: `0`
- Preview attempts: `0`
- retry, fallback, redirect, Create, Cancel, Close, Reduce: `0`
- exchange submissions and submitted/executed notional: `0`
- live Coinbase execution: `not_run`

No raw response, secret, private identifier, or exception text is part of this
classification or browser readback.

## Remediation And Successor

All Preview unit tests now replace both the generation selector and concrete
fixed artifact constant with temporary paths, and they snapshot production R8
metadata before and after focused execution. R8 call authority and its
end-to-end entry point are permanently retired.

R9 is the current conditional generation under the unchanged V3 policy,
`AVP-20DEC30-CDE`, one-contract scope, and strict `<100 / <150 / <300 USDC`
caps. It remains dormant until focused validation and fresh independent safety
plus blind contextless audits pass. R10 remains conditional on a terminal
non-accepted R9 and the same remediation/audit gates. Slice 3 remains inactive
without accepted, unexpired Preview evidence and its separate readiness gates.

Coinbase's public Preview contract currently has no documented Preview expiry
field or TTL. Therefore, even if R9 returns accepted evidence, the current
runner halts at the `PLAN` boundary with zero admission, activation, port
construction, or exchange mutation. Consuming an accepted R9 under this runner
cannot activate Slice 3; it produces only sanitized terminal handoff evidence.

The dormant post-mutation continuation is same-process only and cannot survive
`SIGKILL`, interpreter/container loss, or host loss without violating the
private-identifier and fixed-read constraints. Slice 3 mutation authority must
remain disabled even if authoritative expiry evidence later becomes available,
until that recovery gap is separately remediated, validated, and audited.

R9 uses fresh, distinct UUIDv4 trace identifiers and rejects hashes already
known from R1-R7. R8 identifier hashes remain intentionally unavailable under
the opaque no-deserialization contract, so an explicit R9-to-R8 hash comparison
cannot be performed without violating preservation. This residual is limited to
UUIDv4 collision probability and grants no retry or additional call authority.
