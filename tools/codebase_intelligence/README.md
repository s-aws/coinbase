# Codebase Intelligence

This package builds a static AST index and exposes a constrained, read-first
tool registry for smaller models.

Flow:

```text
repo -> AST parser -> symbol index -> retrieval tools -> curated callable bindings
```

The parser never imports target modules. It records file paths, modules, public
functions/classes/methods, signatures, docstrings, imports, callsites, test
callsites, and ownership tags from `.agents/ownership.yaml` when available.

Generate an index from tracked Python files:

```
python -m tools.codebase_intelligence.cli index --root . --tracked-only --output genai_tools/output/codebase_index.json
```

List constrained tools:

```
python -m tools.codebase_intelligence.cli tools --index genai_tools/output/codebase_index.json
```

Executable bindings are default-deny. A callable must be decorated with
`@codebase_read_tool` or `@codebase_tool(read_only=True)`, present in the static
index, explicitly allowlisted by symbol id, type-hinted, free of `**kwargs`, and
pass the static danger checks.
