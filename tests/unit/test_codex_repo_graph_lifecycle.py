from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from codex_repo_graph import build_graph


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GRAPH_SOURCE = REPOSITORY_ROOT / "codex_repo_graph"
SEMANTIC_FILES = (
    "components.jsonl",
    "invariants.jsonl",
    "runtime_flows.jsonl",
    "persistence.jsonl",
    "concurrency.jsonl",
    "interfaces.jsonl",
    "task_routes.jsonl",
    "claims.jsonl",
    "hazards.jsonl",
)


def _run(
    command: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _git(repository: Path, *arguments: str) -> str:
    return _run(["git", *arguments], cwd=repository).stdout.strip()


def _initialize_repository(repository: Path) -> None:
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repository, "config", "user.name", "Graph Test")
    _git(repository, "config", "user.email", "graph-test@example.invalid")
    _git(repository, "config", "commit.gpgsign", "false")
    _git(repository, "config", "core.autocrlf", "false")


def _commit_all(repository: Path, message: str) -> str:
    _git(repository, "add", "-A")
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _install_minimal_graph_tool(repository: Path) -> Path:
    graph_directory = repository / "codex_repo_graph"
    semantic_directory = graph_directory / "semantic"
    semantic_directory.mkdir(parents=True)
    for filename in ("build_graph.py", "query_graph.py", "ENTRYPOINT.md", "schema.json"):
        shutil.copy2(GRAPH_SOURCE / filename, graph_directory / filename)
    for filename in SEMANTIC_FILES:
        (semantic_directory / filename).write_text("", encoding="utf-8")
    return graph_directory / "build_graph.py"


def _run_builder(repository: Path, builder: Path, *, check: bool = False) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(builder)]
    if check:
        command.append("--check")
    return _run(command, cwd=repository, check=False)


def test_history_snapshot_survives_containing_commit_but_not_two_source_commits(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    _initialize_repository(repository)
    builder = _install_minimal_graph_tool(repository)
    application = repository / "application.py"
    removed_application = repository / "removed_application.py"
    application.write_text("VALUE = 1\n", encoding="utf-8")
    removed_application.write_text("REMOVED = True\n", encoding="utf-8")
    baseline = _commit_all(repository, "baseline")

    application.write_text("VALUE = 2\n", encoding="utf-8")
    removed_application.unlink()
    write_result = _run_builder(repository, builder)
    assert write_result.returncode == 0, write_result.stderr

    manifest = json.loads((repository / "codex_repo_graph" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["graph_format_version"] == "2.0.0"
    assert manifest["history_snapshot_head"] == baseline
    assert "head" not in manifest

    _commit_all(repository, "source and graph")
    first_check = _run_builder(repository, builder, check=True)
    assert first_check.returncode == 0, first_check.stderr

    application.write_text("VALUE = 3\n", encoding="utf-8")
    stale_source_check = _run_builder(repository, builder, check=True)
    assert stale_source_check.returncode == 1
    stale_result = json.loads(stale_source_check.stdout)
    assert "codex_repo_graph/index/files.jsonl" in stale_result["mismatches"]
    application.write_text("VALUE = 2\n", encoding="utf-8")

    graph_note = repository / "codex_repo_graph" / "snapshot-note.md"
    graph_note.write_text("Graph-only successor.\n", encoding="utf-8")
    _commit_all(repository, "graph-only successor")
    graph_only_check = _run_builder(repository, builder, check=True)
    assert graph_only_check.returncode == 0, graph_only_check.stderr

    application.write_text("VALUE = 3\n", encoding="utf-8")
    _commit_all(repository, "second source change")
    second_source_check = _run_builder(repository, builder, check=True)
    assert second_source_check.returncode == 1
    assert "older than one source-changing commit" in second_source_check.stderr


def test_history_snapshot_must_exist_and_be_an_ancestor(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "repository"
    _initialize_repository(repository)
    (repository / "application.py").write_text("VALUE = 1\n", encoding="utf-8")
    current_head = _commit_all(repository, "baseline")
    monkeypatch.setattr(build_graph, "ROOT", repository)

    missing_errors = build_graph.validate_history_snapshot({"head": "0" * 40, "refs": []})
    assert missing_errors == ["history snapshot HEAD does not exist as a commit"]

    tree = _git(repository, "rev-parse", f"{current_head}^{{tree}}")
    unrelated = _git(repository, "commit-tree", tree, "-m", "unrelated")
    ancestor_errors = build_graph.validate_history_snapshot({"head": unrelated, "refs": []})
    assert ancestor_errors == ["history snapshot HEAD is not an ancestor of current HEAD"]


def test_history_snapshot_artifacts_remain_integrity_checked(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _initialize_repository(repository)
    builder = _install_minimal_graph_tool(repository)
    (repository / "application.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(repository, "baseline")

    write_result = _run_builder(repository, builder)
    assert write_result.returncode == 0, write_result.stderr

    refs_path = repository / "codex_repo_graph" / "index" / "git_refs.jsonl"
    original_refs = refs_path.read_bytes()
    refs_path.write_bytes(original_refs + b"\n")
    refs_check = _run_builder(repository, builder, check=True)
    assert refs_check.returncode == 2
    assert "does not match manifest integrity metadata" in refs_check.stderr
    refs_path.write_bytes(original_refs)

    commits_path = (
        repository / "codex_repo_graph" / "index" / "git_commits.jsonl"
    )
    commits_path.write_bytes(commits_path.read_bytes() + b"\n")
    commits_check = _run_builder(repository, builder, check=True)
    assert commits_check.returncode == 1
    result = json.loads(commits_check.stdout)
    assert "codex_repo_graph/index/git_commits.jsonl" in result["mismatches"]
