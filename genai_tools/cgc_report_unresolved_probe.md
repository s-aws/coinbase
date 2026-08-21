# CGC Report

_Generated: 2026-06-02 03:59 UTC_


## God Nodes — Highest Fan-In
_These nodes are called from many places. High fan-in increases risk: a change here affects every caller._

| Kind | Name | File | In-degree |
| --- | --- | --- | --- |
| Function | get | C:\coinbase\tests\regression\test_hotpoint_placer.py | 423 |
| Class | AuditLedger | C:\coinbase-codex\audit\ledger.py | 389 |
| Function | append | C:\coinbase-codex\audit\ledger.py | 284 |
| Class | AuditCore | C:\coinbase-codex\core\engine.py | 275 |
| Function | normalize_json | C:\coinbase-codex\core\json_tools.py | 150 |
| Function | from_ledger | C:\coinbase-codex\projections\state.py | 145 |
| Function | emit | C:\coinbase-codex\core\engine.py | 129 |
| Class | PostgresDB | C:\coinbase\database\database.py | 116 |
| Class | ActionGateway | C:\coinbase-codex\actions\gateway.py | 115 |
| Function | run_from_args | C:\coinbase-codex\app\main.py | 90 |
| Function | iter_records | C:\coinbase-codex\audit\ledger.py | 85 |
| Class | PlaceOrderIntent | C:\coinbase-codex\actions\gateway.py | 84 |
| Class | CoinbaseBotConfig | C:\coinbase-codex\config\assembly.py | 77 |
| Function | submit_and_execute | C:\coinbase-codex\actions\gateway.py | 77 |
| Class | OrderBook | C:\coinbase\configuration.py | 66 |


## Most Complex Functions
_Cyclomatic complexity > 10 is a refactoring candidate._

| Function | File | Cyclomatic Complexity |
| --- | --- | --- |
| run_from_args | C:\coinbase-codex\app\main.py | 250 |
| handle_client_message | C:\coinbase\dashboard_server.py | 191 |
| run_review | C:\agentic_agents\vllm_agent_gateway\controllers\documenter\orchestrator.py | 96 |
| reveal_order_slice | C:\coinbase\core\stealth_order_manager.py | 54 |
| _validate_place_order_lineage | C:\coinbase-codex\actions\gateway.py | 54 |
| _strategy_simulation_contract_check | C:\coinbase-codex\app\ledger_health.py | 53 |
| _evaluate_logical_order_contract | C:\coinbase-codex\app\ledger_health.py | 49 |
| _feed_lifecycle_contract_check | C:\coinbase-codex\app\ledger_health.py | 48 |
| run_streaming_mode | C:\agentic_agents\vllm_agent_gateway\controllers\documenter\streaming.py | 47 |
| audit_missed_fills | C:\coinbase\core\startup_reconciler.py | 42 |
| _operator_canary_evidence_result_contract_check | C:\coinbase-codex\app\ledger_health.py | 37 |
| build_doc_change_plan | C:\agentic_agents\vllm_agent_gateway\controllers\documenter\orchestrator.py | 35 |
| classify | C:\coinbase\tools\classify_repo_files.py | 34 |
| apply_same_side_post_fill_retreat | C:\coinbase\core\stealth_order_manager.py | 34 |
| __post_init__ | C:\coinbase-codex\config\assembly.py | 33 |


## Potential Dead Code
_Functions with zero callers (not guaranteed dead — may be entry points or called via reflection)._

| Function | File |
| --- | --- |
| <module> | C:\agentic_agents\scripts\run_code_structure_index.py |
| <module> | C:\agentic_agents\scripts\run_documenter_orchestrator.py |
| <module> | C:\agentic_agents\scripts\run_documenter_service_example.py |
| <module> | C:\agentic_agents\scripts\run_implementation_workflow.py |
| <module> | C:\agentic_agents\scripts\run_streaming_documenter.py |
| <module> | C:\agentic_agents\tests\conftest.py |
| tmp_path | C:\agentic_agents\tests\conftest.py |
| <module> | C:\agentic_agents\tests\regression\test_code_structure_index.py |
| test_code_structure_index_all_scope_includes_untracked_supported_files | C:\agentic_agents\tests\regression\test_code_structure_index.py |
| test_code_structure_index_generates_static_python_indexes | C:\agentic_agents\tests\regression\test_code_structure_index.py |
| test_code_structure_index_invocation_contract_runs_without_shelling_out | C:\agentic_agents\tests\regression\test_code_structure_index.py |
| test_code_structure_index_records_markdown_graph_and_config_key_paths | C:\agentic_agents\tests\regression\test_code_structure_index.py |
| test_code_structure_index_slice_is_bounded_and_packet_ready | C:\agentic_agents\tests\regression\test_code_structure_index.py |
| <module> | C:\agentic_agents\tests\regression\test_controller_service.py |
| __enter__ | C:\agentic_agents\tests\regression\test_controller_service.py |
| __enter__ | C:\agentic_agents\tests\regression\test_controller_service.py |
| __exit__ | C:\agentic_agents\tests\regression\test_controller_service.py |
| __exit__ | C:\agentic_agents\tests\regression\test_controller_service.py |
| __init__ | C:\agentic_agents\tests\regression\test_controller_service.py |
| __init__ | C:\agentic_agents\tests\regression\test_controller_service.py |


## Suggested Cypher Queries
_Copy these into `execute_cypher_query` to explore further._

### Callers of a specific function
```cypher
MATCH (caller)-[:CALLS]->(fn:Function {name: 'yourFunctionName'})
RETURN caller.name, caller.path LIMIT 20
```

### Class hierarchy for a specific class
```cypher
MATCH path = (c:Class {name: 'YourClass'})-[:INHERITS*]->(parent)
RETURN [n IN nodes(path) | n.name] AS hierarchy
```

### Most-injected Spring beans
```cypher
MATCH ()-[:INJECTS]->(bean:Class)
RETURN bean.name, count(*) AS injection_count
ORDER BY injection_count DESC LIMIT 10
```

### All external library dependencies
```cypher
MATCH (m:MavenModule)-[:USES_LIBRARY]->(lib:ExternalLibrary)
RETURN m.artifact_id, lib.group_id, lib.artifact_id, lib.version
ORDER BY lib.artifact_id
```

### CALLS edges with low confidence (potential mis-resolutions)
```cypher
MATCH (a)-[c:CALLS]->(b)
WHERE c.confidence_label = 'AMBIGUOUS'
RETURN a.name, b.name, c.resolution_tier, a.path LIMIT 20
```
