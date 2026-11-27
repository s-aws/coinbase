# Design Spec: <Title>

| Field | Value |
|---|---|
| Status | `DRAFT` |
| Operator approval | Pending |
| Checklist or objective | <reference> |
| Last evidence review | <YYYY-MM-DD and checkout/commit> |
| Implementation | Not started |

> A `DRAFT` records a proposal only. It does not authorize implementation or
> establish current behavior.

## Problem

Describe the observed problem and why it warrants a cross-cutting design.

## Evidence From the Current Checkout

Link the relevant source symbols, tests, living documentation, boundary debt,
and repository-graph routes. Distinguish verified facts from inference.

## Decision Under Review

State the smallest coherent design and its intended outcome.

## Ownership and Invariants

Declare the single owner for each state mutation or lifecycle transition. Cover
identifier, hierarchy, concurrency, persistence, and recovery constraints.

## Public Contract

Describe typed commands, queries, events, results, and errors. Avoid generic
string dispatch and mutable authoritative state.

## Failure and Transaction Semantics

Describe admission, idempotency, transaction ownership, compensating actions,
partial failure, retries, and fail-open/fail-closed behavior.

## Scope

List included behavior.

## Non-Goals

List adjacent work deliberately deferred.

## Alternatives Rejected

Record materially different options and why they were rejected.

## Staged Plan and Blast Radius

For every stage, list the affected owners, constructors, transports, persistence
paths, tests, documentation, and graph/boundary records. Require separate
approval where the blast radius or behavior changes materially.

## Acceptance Criteria

Define observable completion conditions and required validation.

## Open Decisions

Keep unresolved material choices here. An open decision that changes behavior,
ownership, or scope blocks `ACCEPTED` status.

## Implementation Mapping

When implementation begins, link each accepted contract to its source owner and
tests. Do not claim completion from documentation alone.
