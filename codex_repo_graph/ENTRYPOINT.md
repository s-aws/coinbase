# CODEX_REPO_GRAPH/2

PURPOSE=token-bounded current-checkout retrieval; not narrative documentation
AUTHORITY=AGENTS.md>agent.md>current_code+schema+config+tests>verified_current semantic records>other docs
FRESHNESS_KEYS=manifest.json.graph_digest+manifest.json.source_tree_digest
HISTORY_SNAPSHOT=manifest.json.history_snapshot_head+index/git_refs.jsonl
CHECK_CONTRACT=source_indexes_match_current_worktree;git_history_indexes_match_persisted_snapshot
COMMIT_WINDOW=one_post_snapshot_source_changing_commit+unlimited_graph_only_successors

LOAD_PROTOCOL:
1. Read `manifest.json`.
2. Run `.venv/Scripts/python.exe codex_repo_graph/build_graph.py --check` before relying on cached records.
3. Route with `query_graph.py task <tag>`; do not preload `index/*.jsonl`.
4. Load only returned files/records, then inspect cited source lines.
5. Treat `heuristic`, `unknown`, `conflicted`, `intended_only`, and `historical` records as non-proof.
6. Rebuild before a second commit touching paths outside `codex_repo_graph/` is added after `history_snapshot_head`.

QUERY_PROTOCOL:
- `query_graph.py task websocket`
- `query_graph.py task stealth_reveal`
- `query_graph.py flow user_order_event`
- `query_graph.py symbol process_user_order`
- `query_graph.py file core/order_engine.py`
- `query_graph.py neighbors 's:core/order_engine.py::OrderEngine.process_user_order'`
- `query_graph.py search normalize_price_for_product`

EVIDENCE_MAINTENANCE:
- Python evidence uses `symbol_id=s:<path>::<qualified.name>` when one exact definition contains the excerpt. Repeated definitions (including repeated enclosing scopes) are ambiguous; occurrence suffixes such as `#2` are not durable identities.
- `reviewed_scope_sha256` fingerprints the full definition from `scope_line_start` (including decorators) through `line_end`. `excerpt_sha256` fingerprints the cited excerpt. Both are authored review baselines, never refreshed by a normal build.
- Without `symbol_id`, the reviewed scope is the exact excerpt and both hashes must match. This fallback supports module/multiple-definition excerpts and non-Python files; it does not review surrounding content.
- Fingerprint formula: decode with the builder's `decode_text`, split with its `source_lines`, then SHA-256 of `"\n".join(lines[start - 1:end]).encode("utf-8")`. Ranges are inclusive and one-based. CRLF/CR/LF and the terminal newline are normalized; Unicode separators inside source literals remain content, not line breaks.
- A successful build derives evidence line positions by finding one exact unchanged excerpt within its unchanged symbol scope (or the same file for text fallback). The stored range supplies excerpt length. Only locations and current `file_sha256` are refreshed; `file_sha256` is file freshness, not review approval.
- Changed/missing scopes or excerpts, missing fingerprints, renames, and ambiguous matches require review. Failed validation publishes no artifacts, including no replacement report; a previous `validation/report.json` is not evidence that the failed attempt passed. Use the command's exit status and diagnostics.
- After an intentional source change, inspect the affected claim and source, revise its summary/state/evidence as needed, and explicitly update only the reviewed fingerprints justified by that review. Do not bulk-refresh hashes to silence errors. A state downgrade alone does not bypass evidence validation.
- Author `start_here` with exact symbol IDs or file-only paths. Query output retains these references and adds `resolved_start_here` with current indexed line positions. Legacy numeric references remain accepted but have no relocation guarantee. Rebuild/check after source edits before trusting query output.
- Fingerprints detect textual changes, not semantic equivalence or transitive behavior. Changes in callees, configuration, enclosing class context, or code outside a cited scope still require normal source review and tests; an unchanged hash does not re-prove a claim.

RECORD_ID_PREFIXES:
- `f:` repository file
- `s:` source symbol
- `db:` database relation mentioned or defined in SQL
- `cfg:` configuration/environment key
- `evt:` handled message/event candidate (heuristic)
- `disc:` generic `type` discriminator candidate; never event proof
- `rt:` runtime primitive
- `e:` directed edge
- `test:` static test record
- `commit:` Git commit
- `ref:` Git ref (local Codex turn-diff refs excluded)
- `history:` per-path Git history aggregate
- `component:` curated subsystem or ownership boundary
- `conc:` curated concurrency or lock contract
- `flow:` curated ordered flow
- `iface:` curated interface
- `inv:` verified/intended invariant
- `persist:` curated persistence lifecycle/ownership
- `risk:` hazard or unresolved contradiction
- `claim:` documented or operator-stated assertion
- `task:` task-to-evidence retrieval route

STATIC_GRAPH_LIMITS:
- Dynamic dispatch, monkeypatching, callbacks, reflection, SQL composition, and JavaScript object wiring may remain unresolved; all call edges are heuristic.
- `target_ref` is a textual target, not a proven edge.
- Static test `production_targets` are call-derived candidates, not file-wide coverage proof.
- Documentation nodes are claims, never implementation evidence by themselves.
- `genai_tools` nodes are non-authoritative and may be destructive or live-capable.
- Raw constant/default/decorator payloads and UUID-shaped operational identifiers are omitted or redacted.
- Log, dump, captured-account, credential, browser-profile, dependency, cache, and graph-output contents are excluded; tracked runtime logs retain metadata only.
- `validation/report.json.status=pass` requires source parsing, schema conformance, semantic references/evidence, index locations, redaction, sensitive-pattern checks, IDs, and edges to pass.
- Write mode captures Git history/ref/path-history inputs at `history_snapshot_head`; check mode reuses that snapshot so its containing commit does not invalidate it.
- Check mode requires the snapshot commit to exist and remain an ancestor of current HEAD. Live HEAD and snapshot distance are transient validation inputs and are not stored in generated artifacts.

REBUILD=`.venv/Scripts/python.exe codex_repo_graph/build_graph.py`
CHECK=`.venv/Scripts/python.exe codex_repo_graph/build_graph.py --check`
