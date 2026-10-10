# Coinbase WebSocket Integration Reference

Reconciled with local code on 2026-10-09. This documents the project's wrapper
and engine contracts, not a complete current Coinbase SDK/API specification.
Stored payload examples live in `websocket_reference/`.

## Transport ownership

`configuration.py::Subscription` declares public ticker/heartbeat channels and
private user/futures-balance/heartbeat channels. OrderEngine runs configured
redundant SDK `WSClient` public connections and exactly one authenticated
`WSUserClient` private connection. Role-specific lists drive subscriptions;
their deduplicated union drives local channel worker ownership.

`external/coinbase_websocket.py::CoinbaseWebSocketClient` wraps either SDK role:

- `connect`, `disconnect`, `is_connected`
- `subscribe(products, channels, on_message=None, on_error=None)`
- `unsubscribe(products=None, channels=None)`
- `on_message`, `on_error`, `on_open`, `on_close`
- `sleep_with_exception_check`, `get_sdk_client`

The selected SDK client role owns authentication/channel validity. The wrapper
subscribes separately to each channel. Its unsubscribe helper currently forwards
only the first supplied channel; no arguments closes the client. Do not infer
multi-channel unsubscribe support from the plural argument name.

## Public ingress

`OrderEngine.on_message` deduplicates redundant public envelopes before attaching
local receipt time. The bounded ticker queue serializes producer recovery,
retains the newest envelope, and carries exact per-product loss counts. The
worker publishes continuity resets before the retained ticker reaches the
stealth decision scheduler. Coinbase's envelope timestamp and local ingress
monotonic time retain their separate meanings.

## Private ingress

`OrderEngine.on_user_message` retains the complete envelope with connection
generation and one connection-global sequence number. User, futures-balance,
and private-heartbeat envelopes traverse one ordered reducer queue. The private
path does not use public payload-hash deduplication.

Bootstrap phases are AWAITING_SNAPSHOT, BOOTSTRAPPING, LIVE, and DESYNCHRONIZED.
Initial order pages accumulate in batches of 50 until a shorter page completes
the snapshot; bootstrap drift comparison/hydration does not invoke DB, fill,
or follow-up side effects. Known payload malformation, sequence discontinuity,
overflow, conflicting duplicate, or ten-second snapshot timeout fails closed
and requests reconnect. Old-generation work cannot revive the new generation.

Later canonical order rows are atomically admitted per envelope into a bounded
FIFO keyed by internal `client_order_id`. Each COID's complete lifecycle runs in
order, while unrelated IDs may proceed concurrently. `snapshot`, `update`, and
`patch` are wire kinds, separate from row status. EXPIRED is terminal cleanup
without FILLED/CANCELLED replacement semantics. Position errors are isolated
from order processing in mixed messages.

Exact rearm/withdrawal recovery uses the engine's canonical terminal-order path;
absence from an open-order snapshot alone is not cancellation evidence.

## Validation references

`tests/regression/test_user_channel_patch_dispatch.py` verifies the private
contract, `test_redundant_public_ticker_fanout.py` verifies public fan-out, and
`tests/unit/test_order_engine_ticker_ingress.py` checks queue continuity.
Run the complete local gate in `genai_data/TESTING_STRATEGY.md`. Static samples
and local mocks do not establish current live Coinbase behavior; external
network execution is governed by `docs/EXTERNAL_TESTING_RUNBOOK.md`.
