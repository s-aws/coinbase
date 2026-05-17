# Public/Private Repository Split

The public repository is the published source of truth for code that users can
run and review. The private repository is an orchestration layer around that
public code.

## Public Repo

Allowed:

- source code
- public regression/unit/integration tests
- public roadmap
- public architecture docs
- public ownership boundaries
- non-secret coding conventions

Forbidden:

- model names and model routing rules
- private prompts and private system instructions
- private release gates and release-only tests
- private eval logs or agent run traces
- private future roadmap details
- secrets or credentials

## Private Repo

Allowed:

- model config and routing metadata
- private prompts and role packs
- agent state and run logs
- release scripts and private release tests
- private roadmaps and future plans
- publish scripts that project public files back to this repo

## Publish Rule

Use an allowlist, not a denylist.

Only files explicitly classified as public may flow from private orchestration
back into the public repo. Public code must not import, read, or require private
repo files.

