"""Dormant composition root for one R10 Preview and conditional Slice 3.

The production readiness bit and every audited revision/hash binding remain
unset until the focused validation and independent audits are complete.
Preflight is deliberately credential-free and mutation-free.  It validates
only fixed local bytes, immutable predecessor evidence, and absence of every
one-use successor path.

The accepted callback is the sole future bridge from the persisted R10
terminal to Slice 3.  It must reuse the already-hydrated R10 session and is
required to fail closed until admission evidence is durably bound into both
activation and orchestration validation.
"""

from __future__ import annotations

import argparse
import ast
import base64
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.machinery
import inspect
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import signal
import threading
from types import MappingProxyType
from typing import Any, Callable


_STAGE0_REPO_ROOT = Path("/home/developer/coinbase/coinbase")
_STAGE0_RUNNER_PATH = (
    _STAGE0_REPO_ROOT / "tools" / "run_admin_api_futures_r10_slice3_end_to_end.py"
)
_STAGE0_PYCACHE_PREFIX = Path("/tmp/coinbase-r10-slice3-empty-pycache")
_STAGE0_PYTHON = "/usr/local/bin/python3.13"
_STAGE0_PYTHON_SHA256 = (
    "5d0a083b8e070d82f4223a89562c1131deed8e1cd76797aaa6f20a604edbc228"
)
_STAGE0_LIBPYTHON_PATH = Path("/usr/local/lib/libpython3.13.so.1.0")
_STAGE0_LIBPYTHON_SHA256 = (
    "b6f30b1f20850555815402065cb70fd520c66ae1e478d627f1945ea776659fac"
)
_AWS_CLI_VERSION_ROOT = Path(
    "/home/developer/.local/aws-cli/v2/2.35.24"
)
_AWS_CLI_CANONICAL_PATH = _AWS_CLI_VERSION_ROOT / "dist" / "aws"
_AWS_CLI_CA_BUNDLE = (
    _AWS_CLI_VERSION_ROOT / "dist" / "awscli" / "botocore" / "cacert.pem"
)
_AWS_CLI_SHA256 = (
    "cf06831bd626c1132effdff0c403cc115ae15fe83aaf455f43e504c148d344e5"
)
_AWS_CLI_VERSION_OUTPUT = (
    "aws-cli/2.35.24 Python/3.14.6 "
    "Linux/6.18.33.2-microsoft-standard-WSL2 exe/x86_64.debian.12"
)
_AWS_CLI_TREE_ENTRY_COUNT = 8649
_AWS_CLI_TREE_FILE_BYTES = 254415287
_AWS_CLI_TREE_SHA256 = (
    "ec5b4574cc2fd9ee0f91afe7cef682a52ded5ac98faeae9bbc23b0b6f04ff7c1"
)
_CLOSED_GIT_COMMAND_PREFIX = (
    "/usr/bin/git",
    "--no-optional-locks",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.untrackedCache=false",
)
_CLOSED_GIT_ENV = MappingProxyType(
    {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "HOME": "/nonexistent",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }
)
_STAGE0_AUTHORIZATION_PATH = Path(
    "/home/developer/.codex/attachments/"
    "3d0f7f52-a084-40c1-b686-e3f8d072d68e/pasted-text.txt"
)
_STAGE0_AUTHORIZATION_SHA256 = (
    "5c9c2432179989446d79da2e8f173729103844a96f00e1eeec56dcf5c8e2dc51"
)
_STAGE0_COMPONENT_RELATIVE_PATHS: tuple[tuple[str, str], ...] = (
    ("preview", "application/admin_api/futures_order_preview.py"),
    ("slice3_core", "application/admin_api/futures_terminal_roundtrip.py"),
    (
        "slice3_activation",
        "application/admin_api/futures_terminal_roundtrip_activation.py",
    ),
    (
        "slice3_admission",
        "application/admin_api/futures_terminal_roundtrip_admission.py",
    ),
    (
        "slice3_coinbase",
        "application/admin_api/futures_terminal_roundtrip_coinbase.py",
    ),
    (
        "slice3_handoff",
        "application/admin_api/futures_terminal_roundtrip_handoff.py",
    ),
    (
        "slice3_handoff_terminal",
        "application/admin_api/futures_terminal_roundtrip_handoff_terminal.py",
    ),
    (
        "slice3_orchestrator",
        "application/admin_api/futures_terminal_roundtrip_orchestrator.py",
    ),
    (
        "slice3_reads",
        "application/admin_api/futures_terminal_roundtrip_reads.py",
    ),
    (
        "slice3_terminal",
        "application/admin_api/futures_terminal_roundtrip_terminal.py",
    ),
    ("r10_preview_tool", "tools/run_admin_api_futures_no_live_preview_r10.py"),
    ("r9_preview_tool", "tools/run_admin_api_futures_no_live_preview_r9.py"),
    (
        "r9_end_to_end_tombstone",
        "tools/run_admin_api_futures_r9_slice3_end_to_end.py",
    ),
    ("r8_preview_tool", "tools/run_admin_api_futures_no_live_preview_r8.py"),
    (
        "r8_end_to_end_tombstone",
        "tools/run_admin_api_futures_r8_slice3_end_to_end.py",
    ),
    ("r7_preview_tool", "tools/run_admin_api_futures_no_live_preview_r7.py"),
    ("r6_preview_tool", "tools/run_admin_api_futures_no_live_preview_r6.py"),
    ("r5_preview_tool", "tools/run_admin_api_futures_no_live_preview_r5.py"),
    ("r4_preview_tool", "tools/run_admin_api_futures_no_live_preview.py"),
    ("live_credentials", "tools/coinbase_live_credentials.py"),
    ("coinbase_rest_wrapper", "external/coinbase_client.py"),
    ("core_enums", "core/enums.py"),
)
_STAGE0_DEPENDENCIES: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "coinbase-advanced-py",
        "1.8.4",
        "/home/developer/.local/lib/python3.13/site-packages",
        "coinbase_advanced_py-1.8.4.dist-info",
        "coinbase",
        "40430123aeb0b6b38b333b676c0b5775b86188e5082ee2bbb54f337d48edeba1",
    ),
    (
        "requests",
        "2.34.2",
        "/home/developer/.local/lib/python3.13/site-packages",
        "requests-2.34.2.dist-info",
        "requests",
        "2e48b2db823e566cd0e9c99df87dfa6117fe020e6519f3f9909f4470291fab4b",
    ),
    (
        "urllib3",
        "2.7.0",
        "/usr/local/lib/python3.13/site-packages",
        "urllib3-2.7.0.dist-info",
        "urllib3",
        "bab9edcf76ec02bac68329df0e7de530efcbd3dc131551f5f86a83ff4d087106",
    ),
    (
        "PyJWT",
        "2.13.0",
        "/home/developer/.local/lib/python3.13/site-packages",
        "pyjwt-2.13.0.dist-info",
        "jwt",
        "e66ede74c7a4eaef0332c82e25c313c183114ecb993cae8c2d9a72efe89cdf27",
    ),
    (
        "cryptography",
        "49.0.0",
        "/home/developer/.local/lib/python3.13/site-packages",
        "cryptography-49.0.0.dist-info",
        "cryptography",
        "8aef53314efc7136ef9aafcaf3da40e9b2b2d71086e969f354e9f744f14b5be5",
    ),
    (
        "cffi",
        "2.1.0",
        "/home/developer/.local/lib/python3.13/site-packages",
        "cffi-2.1.0.dist-info",
        "cffi",
        "b4126874ee638ae57d4b6291a819e92c0ba4e4cf538ca4cec3ee360fc28d243a",
    ),
    (
        "certifi",
        "2026.6.17",
        "/usr/local/lib/python3.13/site-packages",
        "certifi-2026.6.17.dist-info",
        "certifi",
        "99d26202d832e6cde4539b481e5956858b5e051bdc7f407f101e03b4319e4c4c",
    ),
    (
        "charset-normalizer",
        "3.4.9",
        "/home/developer/.local/lib/python3.13/site-packages",
        "charset_normalizer-3.4.9.dist-info",
        "charset_normalizer",
        "ce77d38b745a896acd0f012d1300fa4afea386d991835c943dec27d74fb9e963",
    ),
    (
        "idna",
        "3.18",
        "/usr/local/lib/python3.13/site-packages",
        "idna-3.18.dist-info",
        "idna",
        "0d15c3a9678cec4de0ae64abb7f85a636e44dea89d15f73c94d58e24ffaae78f",
    ),
    (
        "backoff",
        "2.2.1",
        "/home/developer/.local/lib/python3.13/site-packages",
        "backoff-2.2.1.dist-info",
        "backoff",
        "ac9598ad7ca72d341773345bce960fd6b392f38d33ef1766a4d752a23f794b6e",
    ),
    (
        "websockets",
        "13.1",
        "/home/developer/.local/lib/python3.13/site-packages",
        "websockets-13.1.dist-info",
        "websockets",
        "9ce8a817feeced95d3a864c5c14bf964a21fc572b8f7649d58f377140032e802",
    ),
    (
        "pydantic",
        "2.13.4",
        "/home/developer/.local/lib/python3.13/site-packages",
        "pydantic-2.13.4.dist-info",
        "pydantic",
        "774c7cbfbb195bcfebdd1b6b3f0ea3ce47fad225b8b1e8e172c5864dec34a358",
    ),
    (
        "pydantic_core",
        "2.46.4",
        "/home/developer/.local/lib/python3.13/site-packages",
        "pydantic_core-2.46.4.dist-info",
        "pydantic_core",
        "cf9ba47e87c106a9c3a90175556a5e62b66bc0747e754f5d31441314910e7318",
    ),
    (
        "annotated-types",
        "0.7.0",
        "/home/developer/.local/lib/python3.13/site-packages",
        "annotated_types-0.7.0.dist-info",
        "annotated_types",
        "f7c0160ccf09bebdec2eb160bb86d1a170670af060991dd2b16299da91a43b84",
    ),
    (
        "typing-inspection",
        "0.4.2",
        "/home/developer/.local/lib/python3.13/site-packages",
        "typing_inspection-0.4.2.dist-info",
        "typing_inspection",
        "0f03ce122a0ee9bbadaf2877040b7b14ca553bdead97797be3333171f7ab153c",
    ),
    (
        "typing_extensions",
        "4.16.0",
        "/usr/local/lib/python3.13/site-packages",
        "typing_extensions-4.16.0.dist-info",
        "typing_extensions.py",
        "87c5132ed922c2e300fd3c36b828e1b3694f2e2ac38f26f556064c4bf3d9af81",
    ),
    (
        "PySocks",
        "1.7.1",
        "/usr/local/lib/python3.13/site-packages",
        "PySocks-1.7.1.dist-info",
        "socks.py",
        "c82333a9b7743d58eb07ca1721d35803bbcdc42a048c8154133d142151c5be91",
    ),
)
EXPECTED_DEPENDENCY_BINDING_SHA256 = (
    "f005dfea7b35ffff646a1cb4b4a3d02ed5a3e9a472768ae4c22db4d0f0bb78a6"
)
_STAGE0_MAX_FILE_BYTES = 32 * 1024 * 1024
_STAGE0_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STAGE0_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_STAGE0_SENTINEL = object()
_STAGE0_VERIFIED_DEPENDENCY_FILES: set[str] = set()


class _Stage0Error(RuntimeError):
    pass


def _stage0_raise(reason: str) -> None:
    raise _Stage0Error(reason)


def _stage0_read_regular(
    path: Path,
    *,
    maximum_bytes: int,
    reason: str,
    allow_empty: bool = False,
) -> bytes:
    try:
        before = path.lstat()
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or (before.st_size == 0 and not allow_empty)
            or before.st_size > maximum_bytes
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            _stage0_raise(reason)
        before_tuple = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        with path.open("rb") as handle:
            payload = handle.read(maximum_bytes + 1)
            opened = os.fstat(handle.fileno())
        after = path.lstat()
        opened_tuple = (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_uid,
            opened.st_gid,
            opened.st_nlink,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        after_tuple = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if (
            before_tuple != opened_tuple
            or before_tuple != after_tuple
            or len(payload) != before.st_size
            or len(payload) > maximum_bytes
        ):
            _stage0_raise(reason)
        return payload
    except _Stage0Error:
        raise
    except Exception:
        _stage0_raise(reason)


def _stage0_audit_literal(
    node: ast.expr,
    *,
    pattern: re.Pattern[str] | None = None,
    boolean: bool = False,
) -> object:
    if not isinstance(node, ast.Constant):
        _stage0_raise("futures_r10_slice3_stage0_binding_invalid")
    value = node.value
    if boolean:
        if not isinstance(value, bool):
            _stage0_raise("futures_r10_slice3_stage0_binding_invalid")
        return value
    if value is None:
        return None
    if not isinstance(value, str) or pattern is None or pattern.fullmatch(value) is None:
        _stage0_raise("futures_r10_slice3_stage0_binding_invalid")
    return value


def _stage0_parse_audit_bindings(payload: bytes) -> dict[str, object]:
    begin = b"# AUDIT_BINDINGS_BEGIN\n"
    end = b"# AUDIT_BINDINGS_END\n"
    if payload.count(begin) != 1 or payload.count(end) != 1:
        _stage0_raise("futures_r10_slice3_stage0_binding_invalid")
    _prefix, remainder = payload.split(begin, 1)
    bindings, _suffix = remainder.split(end, 1)
    try:
        module = ast.parse(bindings.decode("utf-8"), mode="exec")
    except (SyntaxError, UnicodeDecodeError):
        _stage0_raise("futures_r10_slice3_stage0_binding_invalid")
    if len(module.body) != 5:
        _stage0_raise("futures_r10_slice3_stage0_binding_invalid")
    ready, backend, openapi, components, runner_logic = module.body
    if (
        not isinstance(ready, ast.Assign)
        or len(ready.targets) != 1
        or not isinstance(ready.targets[0], ast.Name)
        or ready.targets[0].id != "R10_SLICE3_END_TO_END_READY"
    ):
        _stage0_raise("futures_r10_slice3_stage0_binding_invalid")
    parsed: dict[str, object] = {
        "ready": _stage0_audit_literal(ready.value, boolean=True)
    }
    for node, key, expected_name, pattern in (
        (backend, "backend", "AUDITED_BACKEND_REVISION", _STAGE0_REVISION_RE),
        (openapi, "openapi", "AUDITED_OPENAPI_SHA256", _STAGE0_SHA256_RE),
        (
            runner_logic,
            "runner_logic",
            "AUDITED_RUNNER_LOGIC_SHA256",
            _STAGE0_SHA256_RE,
        ),
    ):
        if (
            not isinstance(node, ast.AnnAssign)
            or not isinstance(node.target, ast.Name)
            or node.target.id != expected_name
            or node.value is None
        ):
            _stage0_raise("futures_r10_slice3_stage0_binding_invalid")
        parsed[key] = _stage0_audit_literal(node.value, pattern=pattern)
    if (
        not isinstance(components, ast.AnnAssign)
        or not isinstance(components.target, ast.Name)
        or components.target.id != "AUDITED_COMPONENT_SHA256"
        or not isinstance(components.value, ast.Call)
        or not isinstance(components.value.func, ast.Name)
        or components.value.func.id != "MappingProxyType"
        or components.value.keywords
        or len(components.value.args) != 1
        or not isinstance(components.value.args[0], ast.Dict)
    ):
        _stage0_raise("futures_r10_slice3_stage0_binding_invalid")
    component_hashes: dict[str, object] = {}
    component_dict = components.value.args[0]
    for key_node, value_node in zip(
        component_dict.keys,
        component_dict.values,
        strict=True,
    ):
        if not isinstance(key_node, ast.Constant) or not isinstance(
            key_node.value, str
        ):
            _stage0_raise("futures_r10_slice3_stage0_binding_invalid")
        if key_node.value in component_hashes:
            _stage0_raise("futures_r10_slice3_stage0_binding_invalid")
        component_hashes[key_node.value] = _stage0_audit_literal(
            value_node,
            pattern=_STAGE0_SHA256_RE,
        )
    if tuple(component_hashes) != tuple(
        name for name, _relative in _STAGE0_COMPONENT_RELATIVE_PATHS
    ):
        _stage0_raise("futures_r10_slice3_stage0_binding_invalid")
    parsed["components"] = component_hashes
    return parsed


def _stage0_normalize_runner(payload: bytes) -> bytes:
    _stage0_parse_audit_bindings(payload)
    begin = b"# AUDIT_BINDINGS_BEGIN\n"
    end = b"# AUDIT_BINDINGS_END\n"
    prefix, remainder = payload.split(begin, 1)
    _bindings, suffix = remainder.split(end, 1)
    return prefix + begin + b"<AUDIT_BINDINGS_NORMALIZED>\n" + end + suffix


def _stage0_git_text(*args: str) -> str:
    try:
        completed = subprocess.run(
            [*_CLOSED_GIT_COMMAND_PREFIX, *args],
            cwd=_STAGE0_REPO_ROOT,
            env=_CLOSED_GIT_ENV,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return completed.stdout.strip()
    except Exception:
        _stage0_raise("futures_r10_slice3_stage0_git_binding_invalid")


def _stage0_runner_at_revision(revision: str) -> bytes:
    try:
        completed = subprocess.run(
            [
                *_CLOSED_GIT_COMMAND_PREFIX,
                "show",
                f"{revision}:tools/run_admin_api_futures_r10_slice3_end_to_end.py",
            ],
            cwd=_STAGE0_REPO_ROOT,
            env=_CLOSED_GIT_ENV,
            check=True,
            capture_output=True,
            timeout=10,
        )
        payload = completed.stdout
    except Exception:
        _stage0_raise("futures_r10_slice3_stage0_git_binding_invalid")
    if not payload or len(payload) > _STAGE0_MAX_FILE_BYTES:
        _stage0_raise("futures_r10_slice3_stage0_git_binding_invalid")
    return payload


def _stage0_validate_cache_prefix() -> None:
    try:
        metadata = _STAGE0_PYCACHE_PREFIX.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or any(os.scandir(_STAGE0_PYCACHE_PREFIX))
        ):
            _stage0_raise("futures_r10_slice3_stage0_pycache_invalid")
    except _Stage0Error:
        raise
    except Exception:
        _stage0_raise("futures_r10_slice3_stage0_pycache_invalid")


def _stage0_validate_runtime() -> None:
    flags = sys.flags
    expected_orig_argv = [
        _STAGE0_PYTHON,
        "-I",
        "-S",
        "-B",
        "-X",
        f"pycache_prefix={_STAGE0_PYCACHE_PREFIX}",
        str(_STAGE0_RUNNER_PATH),
        *sys.argv[1:],
    ]
    if (
        sys.version_info[:2] != (3, 13)
        or sys.executable != _STAGE0_PYTHON
        or flags.isolated != 1
        or flags.dont_write_bytecode != 1
        or flags.no_site != 1
        or flags.no_user_site != 1
        or flags.ignore_environment != 1
        or flags.safe_path is not True
        or sys.pycache_prefix != str(_STAGE0_PYCACHE_PREFIX)
        or sys.orig_argv != expected_orig_argv
        or sys.argv[0] != str(_STAGE0_RUNNER_PATH)
        or sys.argv[1:]
        not in (
            ["--preflight"],
            ["--confirm-one-r10-preview-and-slice3"],
        )
        or sys.path
        != [
            "/usr/local/lib/python313.zip",
            "/usr/local/lib/python3.13",
            "/usr/local/lib/python3.13/lib-dynload",
        ]
    ):
        _stage0_raise("futures_r10_slice3_stage0_isolation_required")
    interpreter = _stage0_read_regular(
        Path(_STAGE0_PYTHON),
        maximum_bytes=_STAGE0_MAX_FILE_BYTES,
        reason="futures_r10_slice3_stage0_interpreter_invalid",
    )
    libpython = _stage0_read_regular(
        _STAGE0_LIBPYTHON_PATH,
        maximum_bytes=_STAGE0_MAX_FILE_BYTES,
        reason="futures_r10_slice3_stage0_interpreter_invalid",
    )
    if (
        hashlib.sha256(interpreter).hexdigest() != _STAGE0_PYTHON_SHA256
        or hashlib.sha256(libpython).hexdigest() != _STAGE0_LIBPYTHON_SHA256
    ):
        _stage0_raise("futures_r10_slice3_stage0_interpreter_invalid")


def _stage0_aws_tree_sha256() -> str:
    digest = hashlib.sha256()
    entry_count = 0
    file_bytes = 0
    allowed_links = {
        "bin/aws": "../dist/aws",
        "bin/aws_completer": "../dist/aws_completer",
    }
    try:
        entries = sorted(
            _AWS_CLI_VERSION_ROOT.rglob("*"),
            key=lambda path: path.relative_to(_AWS_CLI_VERSION_ROOT).as_posix(),
        )
        for path in entries:
            relative = path.relative_to(_AWS_CLI_VERSION_ROOT).as_posix()
            metadata = path.lstat()
            mode = stat.S_IMODE(metadata.st_mode)
            if metadata.st_uid != os.geteuid():
                _stage0_raise("futures_r10_slice3_aws_cli_binding_invalid")
            if stat.S_ISLNK(metadata.st_mode):
                target = os.readlink(path)
                if allowed_links.get(relative) != target:
                    _stage0_raise("futures_r10_slice3_aws_cli_binding_invalid")
                line = (
                    f"L\t{relative}\t{mode:o}\t{metadata.st_uid}\t"
                    f"{metadata.st_gid}\t{target}\n"
                ).encode("utf-8")
            elif stat.S_ISDIR(metadata.st_mode):
                if mode & 0o022:
                    _stage0_raise("futures_r10_slice3_aws_cli_binding_invalid")
                line = (
                    f"D\t{relative}\t{mode:o}\t{metadata.st_uid}\t"
                    f"{metadata.st_gid}\n"
                ).encode("utf-8")
            elif stat.S_ISREG(metadata.st_mode):
                payload = _stage0_read_regular(
                    path,
                    maximum_bytes=64 * 1024 * 1024,
                    reason="futures_r10_slice3_aws_cli_binding_invalid",
                    allow_empty=True,
                )
                file_bytes += len(payload)
                line = (
                    f"F\t{relative}\t{mode:o}\t{metadata.st_uid}\t"
                    f"{metadata.st_gid}\t{len(payload)}\t"
                    f"{hashlib.sha256(payload).hexdigest()}\n"
                ).encode("utf-8")
            else:
                _stage0_raise("futures_r10_slice3_aws_cli_binding_invalid")
            digest.update(line)
            entry_count += 1
    except _Stage0Error:
        raise
    except Exception:
        _stage0_raise("futures_r10_slice3_aws_cli_binding_invalid")
    if (
        entry_count != _AWS_CLI_TREE_ENTRY_COUNT
        or file_bytes != _AWS_CLI_TREE_FILE_BYTES
    ):
        _stage0_raise("futures_r10_slice3_aws_cli_binding_invalid")
    return digest.hexdigest()


def _stage0_validate_aws_cli() -> None:
    expected_links = (
        (
            Path("/home/developer/.local/bin/aws"),
            "/home/developer/.local/aws-cli/v2/current/bin/aws",
        ),
        (
            Path("/home/developer/.local/aws-cli/v2/current"),
            "/home/developer/.local/aws-cli/v2/2.35.24",
        ),
        (
            _AWS_CLI_VERSION_ROOT / "bin" / "aws",
            "../dist/aws",
        ),
    )
    try:
        for path, expected_target in expected_links:
            metadata = path.lstat()
            if (
                not stat.S_ISLNK(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or os.readlink(path) != expected_target
            ):
                _stage0_raise("futures_r10_slice3_aws_cli_binding_invalid")
        executable = _stage0_read_regular(
            _AWS_CLI_CANONICAL_PATH,
            maximum_bytes=16 * 1024 * 1024,
            reason="futures_r10_slice3_aws_cli_binding_invalid",
        )
        executable_metadata = _AWS_CLI_CANONICAL_PATH.lstat()
        if (
            executable_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(executable_metadata.st_mode) != 0o755
            or hashlib.sha256(executable).hexdigest() != _AWS_CLI_SHA256
            or _stage0_aws_tree_sha256() != _AWS_CLI_TREE_SHA256
        ):
            _stage0_raise("futures_r10_slice3_aws_cli_binding_invalid")
        completed = subprocess.run(
            [str(_AWS_CLI_CANONICAL_PATH), "--version"],
            env={
                "AWS_CLI_HISTORY_FILE": "/dev/null",
                "AWS_CONFIG_FILE": "/dev/null",
                "AWS_EC2_METADATA_DISABLED": "true",
                "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
                "HOME": "/nonexistent",
                "LC_ALL": "C",
                "PATH": str(_AWS_CLI_CANONICAL_PATH.parent),
            },
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        version_output = (completed.stdout + completed.stderr).strip()
        if version_output != _AWS_CLI_VERSION_OUTPUT:
            _stage0_raise("futures_r10_slice3_aws_cli_version_invalid")
    except _Stage0Error:
        raise
    except Exception:
        _stage0_raise("futures_r10_slice3_aws_cli_binding_invalid")


def _stage0_secure_credential_file_present(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        _stage0_raise("futures_r10_slice3_credential_provider_invalid")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or metadata.st_size <= 0
        or metadata.st_size > 64 * 1024
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        _stage0_raise("futures_r10_slice3_credential_provider_invalid")
    return True


def _stage0_validate_credential_provider_presence() -> None:
    names = set(os.environ)
    tls_overrides = {
        "BOTO_CONFIG",
        "CURL_CA_BUNDLE",
        "NETRC",
        "OPENSSL_CONF",
        "OPENSSL_MODULES",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "SSLKEYLOGFILE",
    }
    forbidden_overrides = {
        name
        for name in names
        if name.upper().startswith("AWS_")
        or name.upper().endswith("_PROXY")
        or name.upper() in tls_overrides
    }
    if forbidden_overrides:
        _stage0_raise("futures_r10_slice3_credential_provider_override_present")
    credentials_file = _stage0_secure_credential_file_present(
        Path("/home/developer/.aws/credentials")
    )
    if not credentials_file:
        _stage0_raise("futures_r10_slice3_credential_provider_absent")


def _stage0_distribution_target(site_root: Path, record_path: str) -> Path:
    lexical = Path(os.path.abspath(site_root / record_path))
    installation_root = (
        Path("/home/developer/.local")
        if str(site_root).startswith("/home/developer/.local/")
        else Path("/usr/local")
    )
    try:
        if (
            os.path.commonpath((str(lexical), str(installation_root)))
            != str(installation_root)
            or os.path.realpath(lexical) != str(lexical)
        ):
            _stage0_raise("futures_r10_slice3_dependency_record_invalid")
    except (OSError, ValueError):
        _stage0_raise("futures_r10_slice3_dependency_record_invalid")
    return lexical


def _stage0_verify_distribution(
    spec: tuple[str, str, str, str, str, str],
) -> dict[str, str]:
    name, version, site_root_text, dist_info_name, package_name, record_sha256 = spec
    site_root = Path(site_root_text)
    record_path = site_root / dist_info_name / "RECORD"
    record_payload = _stage0_read_regular(
        record_path,
        maximum_bytes=512 * 1024,
        reason="futures_r10_slice3_dependency_record_invalid",
    )
    if hashlib.sha256(record_payload).hexdigest() != record_sha256:
        _stage0_raise("futures_r10_slice3_dependency_record_invalid")
    try:
        rows = list(csv.reader(record_payload.decode("utf-8").splitlines()))
    except (csv.Error, UnicodeDecodeError):
        _stage0_raise("futures_r10_slice3_dependency_record_invalid")
    seen: set[str] = set()
    hashed_paths: set[str] = set()
    for row in rows:
        if len(row) != 3 or not row[0] or row[0] in seen:
            _stage0_raise("futures_r10_slice3_dependency_record_invalid")
        relative, encoded_hash, size_text = row
        seen.add(relative)
        if not encoded_hash:
            if relative.endswith(".py"):
                _stage0_raise("futures_r10_slice3_dependency_record_invalid")
            continue
        if not encoded_hash.startswith("sha256=") or not size_text.isdigit():
            _stage0_raise("futures_r10_slice3_dependency_record_invalid")
        target = _stage0_distribution_target(site_root, relative)
        payload = _stage0_read_regular(
            target,
            maximum_bytes=_STAGE0_MAX_FILE_BYTES,
            reason="futures_r10_slice3_dependency_record_invalid",
            allow_empty=True,
        )
        expected_encoded = base64.urlsafe_b64encode(
            hashlib.sha256(payload).digest()
        ).rstrip(b"=").decode("ascii")
        if (
            encoded_hash != f"sha256={expected_encoded}"
            or int(size_text) != len(payload)
        ):
            _stage0_raise("futures_r10_slice3_dependency_record_invalid")
        hashed_paths.add(relative)
        _STAGE0_VERIFIED_DEPENDENCY_FILES.add(str(target))
    metadata_relative = f"{dist_info_name}/METADATA"
    if metadata_relative not in hashed_paths:
        _stage0_raise("futures_r10_slice3_dependency_record_invalid")
    metadata_payload = _stage0_read_regular(
        site_root / metadata_relative,
        maximum_bytes=2 * 1024 * 1024,
        reason="futures_r10_slice3_dependency_record_invalid",
    )
    metadata_lines = metadata_payload.decode("utf-8").splitlines()
    if f"Name: {name}" not in metadata_lines or f"Version: {version}" not in (
        metadata_lines
    ):
        _stage0_raise("futures_r10_slice3_dependency_version_invalid")
    package_root = site_root / package_name
    try:
        for directory, directories, filenames in os.walk(
            package_root,
            followlinks=False,
        ):
            for child in directories:
                if (Path(directory) / child).is_symlink():
                    _stage0_raise("futures_r10_slice3_dependency_record_invalid")
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                relative = str((Path(directory) / filename).relative_to(site_root))
                if relative not in hashed_paths:
                    _stage0_raise("futures_r10_slice3_dependency_record_invalid")
    except _Stage0Error:
        raise
    except Exception:
        _stage0_raise("futures_r10_slice3_dependency_record_invalid")
    return {
        "name": name,
        "version": version,
        "site_root": site_root_text,
        "record_sha256": record_sha256,
    }


def _stage0_validate_installed_dependencies() -> str:
    _STAGE0_VERIFIED_DEPENDENCY_FILES.clear()
    packages = [_stage0_verify_distribution(spec) for spec in _STAGE0_DEPENDENCIES]
    binding = {
        "schema_version": "r10-slice3-dependency-binding-v1",
        "packages": packages,
    }
    digest = hashlib.sha256(
        json.dumps(
            binding,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if digest != EXPECTED_DEPENDENCY_BINDING_SHA256:
        _stage0_raise("futures_r10_slice3_dependency_binding_invalid")
    return digest


class _Stage0VerifiedDependencyFinder:
    """Reject executable imports from site roots unless RECORD-verified."""

    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is None:
            return None
        site_roots = tuple(dict.fromkeys(specification[2] for specification in (
            _STAGE0_DEPENDENCIES
        )))
        origin = spec.origin
        if origin in {None, "built-in", "frozen"}:
            locations = spec.submodule_search_locations or ()
            if any(
                os.path.commonpath((os.path.abspath(location), root)) == root
                for location in locations
                for root in site_roots
            ):
                raise ImportError(
                    "futures_r10_slice3_unverified_dependency_import_blocked"
                )
            return spec
        absolute_origin = os.path.abspath(origin)
        for root in site_roots:
            try:
                inside = os.path.commonpath((absolute_origin, root)) == root
            except ValueError:
                inside = False
            if inside:
                if (
                    os.path.realpath(absolute_origin) != absolute_origin
                    or absolute_origin not in _STAGE0_VERIFIED_DEPENDENCY_FILES
                ):
                    raise ImportError(
                        "futures_r10_slice3_unverified_dependency_import_blocked"
                    )
                break
        return spec


def _stage0_install_verified_import_guard() -> None:
    if not _STAGE0_VERIFIED_DEPENDENCY_FILES:
        _stage0_raise("futures_r10_slice3_dependency_binding_invalid")
    try:
        path_finder_index = sys.meta_path.index(importlib.machinery.PathFinder)
    except ValueError:
        _stage0_raise("futures_r10_slice3_dependency_binding_invalid")
    if _Stage0VerifiedDependencyFinder not in sys.meta_path:
        sys.meta_path.insert(path_finder_index, _Stage0VerifiedDependencyFinder)


def _stage0_validate_ready_source(
    runner_payload: bytes,
    bindings: Mapping[str, object],
) -> None:
    if Path(os.path.abspath(__file__)) != _STAGE0_RUNNER_PATH:
        _stage0_raise("futures_r10_slice3_stage0_runner_path_invalid")
    if _stage0_git_text("status", "--porcelain", "--untracked-files=all"):
        _stage0_raise("futures_r10_slice3_stage0_worktree_not_clean")
    backend = bindings.get("backend")
    openapi = bindings.get("openapi")
    runner_logic = bindings.get("runner_logic")
    components = bindings.get("components")
    if (
        not isinstance(backend, str)
        or _STAGE0_REVISION_RE.fullmatch(backend) is None
        or not isinstance(openapi, str)
        or _STAGE0_SHA256_RE.fullmatch(openapi) is None
        or not isinstance(runner_logic, str)
        or _STAGE0_SHA256_RE.fullmatch(runner_logic) is None
        or not isinstance(components, Mapping)
        or any(not isinstance(value, str) for value in components.values())
    ):
        _stage0_raise("futures_r10_slice3_stage0_binding_incomplete")
    current = _stage0_git_text("rev-parse", "HEAD").lower()
    if (
        _STAGE0_REVISION_RE.fullmatch(current) is None
        or _stage0_git_text("symbolic-ref", "--short", "HEAD") != "main"
        or _stage0_git_text("rev-parse", "refs/remotes/origin/main").lower()
        != current
    ):
        _stage0_raise("futures_r10_slice3_stage0_git_binding_invalid")
    parents = _stage0_git_text("rev-list", "--parents", "-n", "1", current).split()
    if (
        parents != [current, backend]
        or _stage0_git_text("rev-list", "--count", f"{backend}..{current}") != "1"
    ):
        _stage0_raise("futures_r10_slice3_stage0_audit_transition_invalid")
    changed = tuple(
        line
        for line in _stage0_git_text(
            "diff",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            f"{backend}..{current}",
            "--",
        ).splitlines()
        if line
    )
    if changed != ("tools/run_admin_api_futures_r10_slice3_end_to_end.py",):
        _stage0_raise("futures_r10_slice3_stage0_audit_transition_invalid")
    normalized = _stage0_normalize_runner(runner_payload)
    if (
        normalized != _stage0_normalize_runner(_stage0_runner_at_revision(backend))
        or hashlib.sha256(normalized).hexdigest() != runner_logic
    ):
        _stage0_raise("futures_r10_slice3_stage0_runner_hash_invalid")
    openapi_payload = _stage0_read_regular(
        _STAGE0_REPO_ROOT / "openapi" / "coinbase-admin-api.yaml",
        maximum_bytes=_STAGE0_MAX_FILE_BYTES,
        reason="futures_r10_slice3_stage0_file_binding_invalid",
    )
    if hashlib.sha256(openapi_payload).hexdigest() != openapi:
        _stage0_raise("futures_r10_slice3_stage0_file_binding_invalid")
    for name, relative in _STAGE0_COMPONENT_RELATIVE_PATHS:
        expected = components.get(name)
        payload = _stage0_read_regular(
            _STAGE0_REPO_ROOT / relative,
            maximum_bytes=_STAGE0_MAX_FILE_BYTES,
            reason="futures_r10_slice3_stage0_file_binding_invalid",
        )
        if hashlib.sha256(payload).hexdigest() != expected:
            _stage0_raise("futures_r10_slice3_stage0_file_binding_invalid")
    authorization = _stage0_read_regular(
        _STAGE0_AUTHORIZATION_PATH,
        maximum_bytes=64 * 1024,
        reason="futures_r10_slice3_stage0_authorization_invalid",
    )
    if hashlib.sha256(authorization).hexdigest() != _STAGE0_AUTHORIZATION_SHA256:
        _stage0_raise("futures_r10_slice3_stage0_authorization_invalid")
    _stage0_validate_installed_dependencies()
    _stage0_validate_aws_cli()
    _stage0_validate_credential_provider_presence()


def _stage0_blocked(reason: str) -> None:
    print(
        json.dumps(
            {
                "status": "blocked",
                "blocker": reason,
                "stage0_validated": False,
                "project_modules_imported": False,
                "coinbase_client_constructed": False,
                "preview_order_attempt_count": 0,
                "slice3_exchange_mutation_attempt_count": 0,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    raise SystemExit(2)


def _stage0_before_project_imports() -> tuple[bool, object | None]:
    source_path = Path(os.path.abspath(__file__))
    try:
        runner_payload = _stage0_read_regular(
            source_path,
            maximum_bytes=_STAGE0_MAX_FILE_BYTES,
            reason="futures_r10_slice3_stage0_runner_path_invalid",
        )
        bindings = _stage0_parse_audit_bindings(runner_payload)
        ready = bindings.get("ready") is True
        if not ready:
            return False, None
        if __name__ != "__main__":
            _stage0_raise("futures_r10_slice3_stage0_direct_import_blocked")
        _stage0_validate_runtime()
        _stage0_validate_cache_prefix()
        _stage0_validate_ready_source(runner_payload, bindings)
        _stage0_validate_cache_prefix()
        for site_root in dict.fromkeys(
            spec[2] for spec in _STAGE0_DEPENDENCIES
        ):
            if site_root in sys.path:
                _stage0_raise("futures_r10_slice3_stage0_import_path_invalid")
            sys.path.append(site_root)
        _stage0_install_verified_import_guard()
        return True, _STAGE0_SENTINEL
    except _Stage0Error as exc:
        reason = str(exc)
        if __name__ == "__main__":
            _stage0_blocked(reason)
        raise ImportError(reason) from None


_SOURCE_DECLARED_READY, _STAGE0_EVIDENCE = _stage0_before_project_imports()


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application.admin_api.futures_order_preview import (  # noqa: E402
    FUTURES_PREVIEW_R9_TERMINAL_BINDING,
    FUTURES_PREVIEW_R10_ARTIFACT_PATH,
    FUTURES_PREVIEW_R10_ARTIFACT_TYPE,
    FuturesOrderPreviewArtifactError,
    FuturesOrderPreviewArtifactStore,
    FuturesOrderPreviewProducer,
)
from application.admin_api.futures_terminal_roundtrip import (  # noqa: E402
    FileSlice3ActionClaimStore,
    Slice3ActionKind,
    Slice3ClaimEvent,
)
from application.admin_api.futures_terminal_roundtrip_activation import (  # noqa: E402
    SLICE3_ACTION_JOURNAL_PATH,
    SLICE3_ACTIVATION_ARTIFACT_PATH,
    SLICE3_READ_JOURNAL_PATH,
    SLICE3_TERMINAL_EVIDENCE_PATH,
    Slice3AcceptedR8Binding as Slice3AcceptedR10Binding,
    production_slice3_activation_store,
)
from application.admin_api.futures_terminal_roundtrip_admission import (  # noqa: E402
    SLICE3_ADMISSION_ARTIFACT_PATH,
    build_slice3_admission_chain,
    production_slice3_admission_store,
)
from application.admin_api.futures_terminal_roundtrip_coinbase import (  # noqa: E402
    StrictSlice3CoinbasePort,
)
from application.admin_api.futures_terminal_roundtrip_handoff import (  # noqa: E402
    _validate_documented_preview_expiry,
    build_slice3_activation_manifest as _build_slice3_activation_manifest,
    build_slice3_admitted_plan_from_r8 as _build_slice3_admitted_plan_from_r8,
)
from application.admin_api.futures_terminal_roundtrip_handoff_terminal import (  # noqa: E402,E501
    ACCEPTED_HANDOFF_ARTIFACT_PATH,
    AcceptedHandoffArtifactError,
    AcceptedHandoffStage,
    AcceptedHandoffTerminalizer,
    FileAcceptedHandoffArtifactStore,
    halt_accepted_preview_handoff_offline,
)
from application.admin_api.futures_terminal_roundtrip_orchestrator import (  # noqa: E402
    FileSlice3TerminalArtifactStore,
    Slice3OrchestrationResult,
    Slice3OrchestrationStatus,
    Slice3TerminalRoundtripOrchestrator,
)
from application.admin_api.futures_terminal_roundtrip_reads import (  # noqa: E402
    FileSlice3ReadJournal,
)
from application.admin_api.futures_terminal_roundtrip_terminal import (  # noqa: E402
    Slice3HaltedReconciliationEvidence,
    Slice3TerminalRoundtripEvidence,
)
from tools import run_admin_api_futures_no_live_preview_r10 as r10_tool  # noqa: E402


OPERATOR_AUTHORIZATION_PATH = Path(
    "/home/developer/.codex/attachments/"
    "3d0f7f52-a084-40c1-b686-e3f8d072d68e/pasted-text.txt"
)
OPERATOR_AUTHORIZATION_SHA256 = (
    "5c9c2432179989446d79da2e8f173729103844a96f00e1eeec56dcf5c8e2dc51"
)
OPENAPI_PATH = REPO_ROOT / "openapi" / "coinbase-admin-api.yaml"
RUNNER_PATH = REPO_ROOT / "tools" / "run_admin_api_futures_r10_slice3_end_to_end.py"

AUDITED_COMPONENT_PATHS: Mapping[str, Path] = MappingProxyType(
    {
        "preview": REPO_ROOT / "application" / "admin_api" / "futures_order_preview.py",
        "slice3_core": REPO_ROOT
        / "application"
        / "admin_api"
        / "futures_terminal_roundtrip.py",
        "slice3_activation": REPO_ROOT
        / "application"
        / "admin_api"
        / "futures_terminal_roundtrip_activation.py",
        "slice3_admission": REPO_ROOT
        / "application"
        / "admin_api"
        / "futures_terminal_roundtrip_admission.py",
        "slice3_coinbase": REPO_ROOT
        / "application"
        / "admin_api"
        / "futures_terminal_roundtrip_coinbase.py",
        "slice3_handoff": REPO_ROOT
        / "application"
        / "admin_api"
        / "futures_terminal_roundtrip_handoff.py",
        "slice3_handoff_terminal": REPO_ROOT
        / "application"
        / "admin_api"
        / "futures_terminal_roundtrip_handoff_terminal.py",
        "slice3_orchestrator": REPO_ROOT
        / "application"
        / "admin_api"
        / "futures_terminal_roundtrip_orchestrator.py",
        "slice3_reads": REPO_ROOT
        / "application"
        / "admin_api"
        / "futures_terminal_roundtrip_reads.py",
        "slice3_terminal": REPO_ROOT
        / "application"
        / "admin_api"
        / "futures_terminal_roundtrip_terminal.py",
        "r10_preview_tool": REPO_ROOT
        / "tools"
        / "run_admin_api_futures_no_live_preview_r10.py",
        "r9_preview_tool": REPO_ROOT
        / "tools"
        / "run_admin_api_futures_no_live_preview_r9.py",
        "r9_end_to_end_tombstone": REPO_ROOT
        / "tools"
        / "run_admin_api_futures_r9_slice3_end_to_end.py",
        "r8_preview_tool": REPO_ROOT
        / "tools"
        / "run_admin_api_futures_no_live_preview_r8.py",
        "r8_end_to_end_tombstone": REPO_ROOT
        / "tools"
        / "run_admin_api_futures_r8_slice3_end_to_end.py",
        "r7_preview_tool": REPO_ROOT
        / "tools"
        / "run_admin_api_futures_no_live_preview_r7.py",
        "r6_preview_tool": REPO_ROOT
        / "tools"
        / "run_admin_api_futures_no_live_preview_r6.py",
        "r5_preview_tool": REPO_ROOT
        / "tools"
        / "run_admin_api_futures_no_live_preview_r5.py",
        "r4_preview_tool": REPO_ROOT
        / "tools"
        / "run_admin_api_futures_no_live_preview.py",
        "live_credentials": REPO_ROOT / "tools" / "coinbase_live_credentials.py",
        "coinbase_rest_wrapper": REPO_ROOT / "external" / "coinbase_client.py",
        "core_enums": REPO_ROOT / "core" / "enums.py",
    }
)

# AUDIT_BINDINGS_BEGIN
# This bit is intentionally hard-false until the final safety and blind audits.
R10_SLICE3_END_TO_END_READY = True

# Audit output must replace every ``None`` atomically.  A partial update fails
# before claim construction, credential hydration, or successor persistence.
AUDITED_BACKEND_REVISION: str | None = (
    "edd7035650bb3478c011c1739da15fa56c1479b7"
)
AUDITED_OPENAPI_SHA256: str | None = (
    "007ff39754aaf484d487a5b19ea731f25b37264419ae3cc77f90140c563c0c18"
)
AUDITED_COMPONENT_SHA256: Mapping[str, str | None] = MappingProxyType(
    {
        "preview": "4ddbb2678ccd1de20dd6d81d2eac71e36469a19979ef24856e774a3a7692c2bd",
        "slice3_core": "93ec2dde963d4ea029d6c567b2c93161e6c4a5ad64fa7f5cbce1352a7a537635",
        "slice3_activation": "9ff75ae90900444c2ffb2f0496913b0ba2283322aa87ebcd9a703fbf81bf5edd",
        "slice3_admission": "ebcfde6a556cdc885fe2f9800e5fd227b5fcba5ad167e369c4594af6c3ecd25e",
        "slice3_coinbase": "7cedb371412ad8d2b3a3420164b37fd4424162a010c13963f66d7760137e33de",
        "slice3_handoff": "b3d634eba646f109dd5785eb96f6d57a287cb213450e15c7c0f37eae9818a0bb",
        "slice3_handoff_terminal": "546cfe1eec1f399e113bd3f6aa5f089124c65c6fe423c56eb0a21bd5ba599c8e",
        "slice3_orchestrator": "012abaecb5e28a20f20907e01af75303e274b4ecf4272ce522b4112300e8759a",
        "slice3_reads": "3e381ea69d62f90022ae8c3ed5ef591ea7e86a2a57ff72146f21a81fcefd6647",
        "slice3_terminal": "6f684458911bdf0cb7fda60b36e5c7072d70adbf0735010240f9eebbcee2f2d8",
        "r10_preview_tool": "88404f71f98b8199a8562254c199d76627212fa0c95ea9635c33e6dad65b98bc",
        "r9_preview_tool": "af9eff0bf35910520cbe0e4244a5c12d2c9c62620223935c4691cdeffb462610",
        "r9_end_to_end_tombstone": "e694ba1f873a97fa0c6508aab580a3eeeb2616345ecfabbea3598fa98cefe8c6",
        "r8_preview_tool": "b3183360ade81836c8c232474044c4221535aeb874fad835fa80a24851112732",
        "r8_end_to_end_tombstone": "2352967074b15cb1d70a4bd655a33f29c90a4e6352c14a294e9b9b054c40ccce",
        "r7_preview_tool": "a64c7a9087fe6e5b41ab1ae276966e34930361e6f4450378987df04a7127097a",
        "r6_preview_tool": "b92ef4b1f3e925408e7cace095e031bef694f2dca0c292a508fbd458d862ae80",
        "r5_preview_tool": "3f70bacb6064e6916eb9286790c4ee37f9d360760021f4a243a8c6d0ef263edc",
        "r4_preview_tool": "ed37a2ee20fbe664da8a7cddc1618c56b95f4fe01eac773b6e22db0758c9b0fd",
        "live_credentials": "51b9c1c6f68d3f15c5dbe30a90f99f6bcea423ec29f41ce4da893a17f7ae82c2",
        "coinbase_rest_wrapper": "6baabe95db51890eb0f8311d82295730b22be1d3e34fcf31c6bbb23493f6c6f1",
        "core_enums": "16919a92cc9073e297e92e17e465bfa0782b516bd353eb37dafd9ef036bee0e8",
    }
)
AUDITED_RUNNER_LOGIC_SHA256: str | None = (
    "6d60cc61526e6b731205725c0ae2e429d7596f74e920b66638f40ad75d1e894f"
)
# AUDIT_BINDINGS_END

FIXED_ATTEMPT_PATHS: tuple[Path, ...] = (
    FUTURES_PREVIEW_R10_ARTIFACT_PATH,
    ACCEPTED_HANDOFF_ARTIFACT_PATH,
    SLICE3_ADMISSION_ARTIFACT_PATH,
    SLICE3_ACTIVATION_ARTIFACT_PATH,
    SLICE3_ACTION_JOURNAL_PATH,
    SLICE3_READ_JOURNAL_PATH,
    SLICE3_TERMINAL_EVIDENCE_PATH,
)

_MAX_AUTHORIZATION_BYTES = 64 * 1024
_MAX_AUDITED_FILE_BYTES = 8 * 1024 * 1024
_MAX_AWS_SECRET_RESPONSE_BYTES = 128 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_SAFE_STATUS_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SLICE3_DEFERRED_SIGNALS: tuple[signal.Signals, ...] = tuple(
    signal.Signals(value)
    for value in (
        signal.SIGINT,
        signal.SIGTERM,
        signal.SIGHUP,
        signal.SIGQUIT,
        signal.SIGTSTP,
    )
)


class R10Slice3RunnerError(RuntimeError):
    """A fixed, sanitized fail-closed reason from the composition root."""


def _validate_r10_documented_preview_expiry_boundary(
    *,
    ephemeral_evidence: Mapping[str, Any],
    now: datetime,
) -> None:
    """Require authoritative expiry before any accepted-R10 plan binding."""

    response = ephemeral_evidence.get("preview_response")
    completed_at = ephemeral_evidence.get("completed_at")
    if (
        not isinstance(response, Mapping)
        or not isinstance(completed_at, str)
        or not isinstance(now, datetime)
        or now.tzinfo is None
    ):
        _raise("futures_r10_slice3_preview_expiry_evidence_invalid")
    try:
        accepted_at = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError:
        _raise("futures_r10_slice3_preview_expiry_evidence_invalid")
    if accepted_at.tzinfo is None:
        _raise("futures_r10_slice3_preview_expiry_evidence_invalid")
    # Coinbase's public contract currently has no Preview expiry field/TTL,
    # so production terminalizes at PLAN before the legacy Slice 3 binder,
    # admission, ports, or any exchange mutation.
    _validate_documented_preview_expiry(
        response=response,
        accepted_at=accepted_at.astimezone(timezone.utc),
        current=now.astimezone(timezone.utc),
    )


def build_slice3_admitted_plan_from_r10(
    *,
    ephemeral_evidence: Mapping[str, Any],
    persisted_terminal: Mapping[str, Any],
    accepted_r10_binding: object,
    account_binding: object,
    authorization_sha256: str,
    now: datetime,
    backend_revision: str,
    openapi_revision: str,
) -> tuple[object, object]:
    """Adapt the dormant R10 surface to the still-R8-named Slice 3 contract.

    Production currently halts in this plan boundary because Coinbase has not
    documented Preview expiry.  The adapter grants no authority and exists so
    the generation-specific runner never rewrites an accepted R10 artifact.
    """

    _validate_r10_documented_preview_expiry_boundary(
        ephemeral_evidence=ephemeral_evidence,
        now=now,
    )
    return _build_slice3_admitted_plan_from_r8(
        ephemeral_evidence=ephemeral_evidence,
        persisted_terminal=persisted_terminal,
        accepted_r8_binding=accepted_r10_binding,
        account_binding=account_binding,
        authorization_sha256=authorization_sha256,
        now=now,
        backend_revision=backend_revision,
        openapi_revision=openapi_revision,
    )


def build_slice3_activation_manifest(
    *,
    plan: object,
    persisted_terminal: Mapping[str, Any],
    r10_artifact_file_sha256: str,
    authorization_text: bytes,
    admission_seal: object,
    now: datetime,
) -> object:
    """Keep the R10 runner vocabulary outside the legacy manifest API."""

    return _build_slice3_activation_manifest(
        plan=plan,
        persisted_terminal=persisted_terminal,
        r8_artifact_file_sha256=r10_artifact_file_sha256,
        authorization_text=authorization_text,
        admission_seal=admission_seal,
        now=now,
    )


@dataclass(frozen=True, slots=True)
class PreflightEvidence:
    authorization_bytes: bytes
    backend_revision: str
    openapi_sha256: str
    dependency_binding_sha256: str = EXPECTED_DEPENDENCY_BINDING_SHA256


@dataclass(frozen=True, slots=True)
class EndToEndExecutionResult:
    terminal: Mapping[str, Any]
    slice3_result: SanitizedSlice3Result | None
    dependency_binding_sha256: str = EXPECTED_DEPENDENCY_BINDING_SHA256


@dataclass(frozen=True, slots=True)
class SanitizedSlice3Result:
    status: str
    reason_code: str
    terminal_artifact_sha256: str | None
    terminal_evidence: Mapping[str, object] | None = None


class _AcceptedHandoffCapabilities:
    """One-use opaque identities issued only inside the accepted callback."""

    def __init__(self) -> None:
        self.__bindings: dict[object, tuple[object, object, object, object]] = {}

    def issue(
        self,
        *,
        deferred_session: object,
        accepted_session: object,
        r10_store: object,
        persisted_terminal: object,
    ) -> object:
        capability = object()
        self.__bindings[capability] = (
            deferred_session,
            accepted_session,
            r10_store,
            persisted_terminal,
        )
        return capability

    def consume(
        self,
        capability: object,
        *,
        deferred_session: object,
        accepted_session: object,
        r10_store: object,
        persisted_terminal: object,
    ) -> bool:
        binding = self.__bindings.pop(capability, None)
        return bool(
            binding is not None
            and binding[0] is deferred_session
            and binding[1] is accepted_session
            and binding[2] is r10_store
            and binding[3] is persisted_terminal
        )

    def revoke(self, capability: object) -> None:
        self.__bindings.pop(capability, None)


_ACCEPTED_HANDOFF_CAPABILITIES = _AcceptedHandoffCapabilities()


def _raise(reason: str) -> None:
    raise R10Slice3RunnerError(reason)


@contextmanager
def _defer_slice3_termination_signals():
    """Defer catchable operator termination until terminal persistence."""

    if (
        threading.current_thread() is not threading.main_thread()
        or not hasattr(signal, "pthread_sigmask")
        or not _SLICE3_DEFERRED_SIGNALS
    ):
        _raise("futures_r10_slice3_signal_deferral_unavailable")
    try:
        previous_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK,
            _SLICE3_DEFERRED_SIGNALS,
        )
    except (OSError, ValueError):
        _raise("futures_r10_slice3_signal_deferral_unavailable")
    try:
        yield
    finally:
        try:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        except (OSError, ValueError):
            _raise("futures_r10_slice3_signal_restore_failed")


def _read_regular_file(path: Path, *, maximum_bytes: int, reason: str) -> bytes:
    try:
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size <= 0
            or metadata.st_size > maximum_bytes
        ):
            _raise(reason)
        before = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_uid,
            metadata.st_gid,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
        with path.open("rb") as handle:
            payload = handle.read(maximum_bytes + 1)
            opened = os.fstat(handle.fileno())
        after = path.lstat()
        after_tuple = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        opened_tuple = (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_uid,
            opened.st_gid,
            opened.st_nlink,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        if (
            before != opened_tuple
            or before != after_tuple
            or len(payload) != metadata.st_size
            or len(payload) > maximum_bytes
        ):
            _raise(reason)
        return payload
    except R10Slice3RunnerError:
        raise
    except Exception:
        _raise(reason)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(
        _read_regular_file(
            path,
            maximum_bytes=_MAX_AUDITED_FILE_BYTES,
            reason="futures_r10_slice3_file_binding_invalid",
        )
    ).hexdigest()


def _audit_literal(
    node: ast.expr,
    *,
    pattern: re.Pattern[str] | None = None,
    boolean: bool = False,
) -> object:
    if not isinstance(node, ast.Constant):
        _raise("futures_r10_slice3_runner_binding_invalid")
    value = node.value
    if boolean:
        if not isinstance(value, bool):
            _raise("futures_r10_slice3_runner_binding_invalid")
        return value
    if value is None:
        return None
    if not isinstance(value, str) or pattern is None or pattern.fullmatch(value) is None:
        _raise("futures_r10_slice3_runner_binding_invalid")
    return value


def _validate_audit_binding_syntax(payload: bytes) -> None:
    """Allow only five fixed literal declarations in the excluded block."""

    try:
        module = ast.parse(payload.decode("utf-8"), mode="exec")
    except (SyntaxError, UnicodeDecodeError):
        _raise("futures_r10_slice3_runner_binding_invalid")
    if len(module.body) != 5:
        _raise("futures_r10_slice3_runner_binding_invalid")
    ready, backend, openapi, components, runner_logic = module.body
    if (
        not isinstance(ready, ast.Assign)
        or len(ready.targets) != 1
        or not isinstance(ready.targets[0], ast.Name)
        or ready.targets[0].id != "R10_SLICE3_END_TO_END_READY"
    ):
        _raise("futures_r10_slice3_runner_binding_invalid")
    _audit_literal(ready.value, boolean=True)

    scalar_nodes = (
        (backend, "AUDITED_BACKEND_REVISION", _REVISION_RE),
        (openapi, "AUDITED_OPENAPI_SHA256", _SHA256_RE),
        (runner_logic, "AUDITED_RUNNER_LOGIC_SHA256", _SHA256_RE),
    )
    for node, expected_name, pattern in scalar_nodes:
        if (
            not isinstance(node, ast.AnnAssign)
            or not isinstance(node.target, ast.Name)
            or node.target.id != expected_name
            or node.value is None
        ):
            _raise("futures_r10_slice3_runner_binding_invalid")
        _audit_literal(node.value, pattern=pattern)

    if (
        not isinstance(components, ast.AnnAssign)
        or not isinstance(components.target, ast.Name)
        or components.target.id != "AUDITED_COMPONENT_SHA256"
        or not isinstance(components.value, ast.Call)
        or not isinstance(components.value.func, ast.Name)
        or components.value.func.id != "MappingProxyType"
        or components.value.keywords
        or len(components.value.args) != 1
        or not isinstance(components.value.args[0], ast.Dict)
    ):
        _raise("futures_r10_slice3_runner_binding_invalid")
    component_dict = components.value.args[0]
    keys: list[str] = []
    for key_node, value_node in zip(
        component_dict.keys,
        component_dict.values,
        strict=True,
    ):
        if not isinstance(key_node, ast.Constant) or not isinstance(
            key_node.value, str
        ):
            _raise("futures_r10_slice3_runner_binding_invalid")
        keys.append(key_node.value)
        _audit_literal(value_node, pattern=_SHA256_RE)
    if tuple(keys) != tuple(AUDITED_COMPONENT_PATHS):
        _raise("futures_r10_slice3_runner_binding_invalid")


def _normalize_runner_logic(payload: bytes) -> bytes:
    begin = b"# AUDIT_BINDINGS_BEGIN\n"
    end = b"# AUDIT_BINDINGS_END\n"
    if payload.count(begin) != 1 or payload.count(end) != 1:
        _raise("futures_r10_slice3_runner_binding_invalid")
    prefix, remainder = payload.split(begin, 1)
    bindings, suffix = remainder.split(end, 1)
    _validate_audit_binding_syntax(bindings)
    return prefix + begin + b"<AUDIT_BINDINGS_NORMALIZED>\n" + end + suffix


def _current_runner_bytes() -> bytes:
    if Path(os.path.abspath(__file__)) != RUNNER_PATH:
        _raise("futures_r10_slice3_runner_binding_invalid")
    return _read_regular_file(
        RUNNER_PATH,
        maximum_bytes=_MAX_AUDITED_FILE_BYTES,
        reason="futures_r10_slice3_runner_binding_invalid",
    )


def _current_runner_logic_sha256() -> str:
    return hashlib.sha256(_normalize_runner_logic(_current_runner_bytes())).hexdigest()


def _current_backend_revision() -> str:
    revision = _git_text("rev-parse", "HEAD").lower()
    if _REVISION_RE.fullmatch(revision) is None:
        _raise("futures_r10_slice3_backend_revision_unavailable")
    return revision


def _git_text(*args: str) -> str:
    try:
        completed = subprocess.run(
            [*_CLOSED_GIT_COMMAND_PREFIX, *args],
            cwd=REPO_ROOT,
            env=_CLOSED_GIT_ENV,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        value = completed.stdout.strip()
    except Exception:
        _raise("futures_r10_slice3_backend_revision_unavailable")
    return value


def _runner_bytes_at_revision(revision: str) -> bytes:
    try:
        completed = subprocess.run(
            [
                *_CLOSED_GIT_COMMAND_PREFIX,
                "show",
                f"{revision}:tools/run_admin_api_futures_r10_slice3_end_to_end.py",
            ],
            cwd=REPO_ROOT,
            env=_CLOSED_GIT_ENV,
            check=True,
            capture_output=True,
            timeout=10,
        )
        payload = completed.stdout
    except Exception:
        _raise("futures_r10_slice3_audit_base_runner_unavailable")
    if not payload or len(payload) > _MAX_AUDITED_FILE_BYTES:
        _raise("futures_r10_slice3_audit_base_runner_unavailable")
    return payload


def _validate_audit_commit_transition(base_revision: str) -> str:
    current = _current_backend_revision()
    if _git_text("status", "--porcelain", "--untracked-files=all"):
        _raise("futures_r10_slice3_tracked_worktree_not_clean")
    if _git_text("symbolic-ref", "--short", "HEAD") != "main":
        _raise("futures_r10_slice3_branch_not_main")
    if _git_text("rev-parse", "refs/remotes/origin/main").lower() != current:
        _raise("futures_r10_slice3_origin_main_not_synchronized")
    parent_row = _git_text("rev-list", "--parents", "-n", "1", current).split()
    if len(parent_row) != 2 or parent_row != [current, base_revision]:
        _raise("futures_r10_slice3_audit_commit_transition_invalid")
    if _git_text("rev-list", "--count", f"{base_revision}..{current}") != "1":
        _raise("futures_r10_slice3_audit_commit_transition_invalid")
    changed = tuple(
        line
        for line in _git_text(
            "diff",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            f"{base_revision}..{current}",
            "--",
        ).splitlines()
        if line
    )
    expected_path = "tools/run_admin_api_futures_r10_slice3_end_to_end.py"
    if changed != (expected_path,):
        _raise("futures_r10_slice3_audit_commit_scope_invalid")
    base_logic = _normalize_runner_logic(_runner_bytes_at_revision(base_revision))
    current_logic = _normalize_runner_logic(_current_runner_bytes())
    if base_logic != current_logic:
        _raise("futures_r10_slice3_audit_commit_logic_changed")
    return current


def _validate_authorization() -> bytes:
    payload = _read_regular_file(
        OPERATOR_AUTHORIZATION_PATH,
        maximum_bytes=_MAX_AUTHORIZATION_BYTES,
        reason="futures_r10_slice3_authorization_binding_invalid",
    )
    if hashlib.sha256(payload).hexdigest() != OPERATOR_AUTHORIZATION_SHA256:
        _raise("futures_r10_slice3_authorization_binding_invalid")
    return payload


def _validate_local_runtime_readiness() -> str:
    if _SOURCE_DECLARED_READY and _STAGE0_EVIDENCE is not _STAGE0_SENTINEL:
        _raise("futures_r10_slice3_stage0_evidence_missing")
    try:
        dependency_sha256 = _stage0_validate_installed_dependencies()
        _stage0_validate_aws_cli()
        _stage0_validate_credential_provider_presence()
    except _Stage0Error as exc:
        reason = str(exc)
        if _SAFE_REASON_RE.fullmatch(reason) is None:
            reason = "futures_r10_slice3_local_runtime_invalid"
        _raise(reason)
    return dependency_sha256


def _validate_audited_state() -> tuple[str, str]:
    if (
        AUDITED_BACKEND_REVISION is None
        or AUDITED_OPENAPI_SHA256 is None
        or AUDITED_RUNNER_LOGIC_SHA256 is None
        or _REVISION_RE.fullmatch(AUDITED_BACKEND_REVISION) is None
        or _SHA256_RE.fullmatch(AUDITED_OPENAPI_SHA256) is None
        or _SHA256_RE.fullmatch(AUDITED_RUNNER_LOGIC_SHA256) is None
        or set(AUDITED_COMPONENT_SHA256) != set(AUDITED_COMPONENT_PATHS)
        or any(
            value is None or _SHA256_RE.fullmatch(value) is None
            for value in AUDITED_COMPONENT_SHA256.values()
        )
    ):
        _raise("futures_r10_slice3_audit_binding_incomplete")
    if _current_runner_logic_sha256() != AUDITED_RUNNER_LOGIC_SHA256:
        _raise("futures_r10_slice3_audited_runner_changed")
    current_revision = _validate_audit_commit_transition(AUDITED_BACKEND_REVISION)
    openapi_sha256 = _sha256_file(OPENAPI_PATH)
    if openapi_sha256 != AUDITED_OPENAPI_SHA256:
        _raise("futures_r10_slice3_audited_openapi_changed")
    for name, path in AUDITED_COMPONENT_PATHS.items():
        if _sha256_file(path) != AUDITED_COMPONENT_SHA256[name]:
            _raise("futures_r10_slice3_audited_component_changed")
    return current_revision, openapi_sha256


def _validate_attempt_paths_absent() -> None:
    if len(FIXED_ATTEMPT_PATHS) != 7 or len(set(FIXED_ATTEMPT_PATHS)) != 7:
        _raise("futures_r10_slice3_attempt_path_binding_invalid")
    for path in FIXED_ATTEMPT_PATHS:
        if not path.is_absolute():
            _raise("futures_r10_slice3_attempt_path_binding_invalid")
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            _raise("futures_r10_slice3_attempt_path_not_fresh")
        _raise("futures_r10_slice3_attempt_path_not_fresh")


def _validate_immutable_predecessors() -> None:
    try:
        binding = dict(r10_tool.validate_production_predecessor())
    except Exception:
        _raise("futures_r10_slice3_predecessor_binding_invalid")
    if binding != FUTURES_PREVIEW_R9_TERMINAL_BINDING:
        _raise("futures_r10_slice3_predecessor_binding_invalid")


def _validate_exclusive_r10_entrypoint() -> None:
    if (
        r10_tool.R9_PREVIEW_CALL_AUTHORITY_ACTIVE is not False
        or r10_tool.R10_PREVIEW_CALL_AUTHORITY_ACTIVE is not False
        or r10_tool.R10_FINAL_AUDIT_BINDING_READY is not False
    ):
        _raise("futures_r10_slice3_parallel_preview_path_enabled")


def _validate_fresh_r10_claim_contract() -> None:
    try:
        r10_tool._validate_fresh_claim_contract(FUTURES_PREVIEW_R10_ARTIFACT_PATH)
    except Exception:
        _raise("futures_r10_slice3_claim_contract_invalid")


def validate_production_preflight() -> PreflightEvidence:
    """Validate every local fixed binding without constructing a client."""

    authorization = _validate_authorization()
    dependency_sha256 = _validate_local_runtime_readiness()
    _validate_attempt_paths_absent()
    _validate_exclusive_r10_entrypoint()
    _validate_immutable_predecessors()
    _validate_fresh_r10_claim_contract()
    if not _runtime_enforces_admission_binding():
        _raise("futures_r10_slice3_runtime_admission_binding_unavailable")
    backend_revision, openapi_sha256 = _validate_audited_state()
    return PreflightEvidence(
        authorization_bytes=authorization,
        backend_revision=backend_revision,
        openapi_sha256=openapi_sha256,
        dependency_binding_sha256=dependency_sha256,
    )


def _lookup_fixed_r10_secret(secret_id: str, region: str | None) -> str:
    """Resolve the exact Default secret once with a closed AWS CLI process."""

    if secret_id != "coinbase" or region != "us-east-1":
        _raise("futures_r10_slice3_credential_preparation_failed")
    argv = [
        str(_AWS_CLI_CANONICAL_PATH),
        "secretsmanager",
        "get-secret-value",
        "--secret-id",
        "coinbase",
        "--region",
        "us-east-1",
        "--endpoint-url",
        "https://secretsmanager.us-east-1.amazonaws.com",
        "--ca-bundle",
        str(_AWS_CLI_CA_BUNDLE),
        "--output",
        "json",
        "--no-cli-pager",
        "--cli-connect-timeout",
        "10",
        "--cli-read-timeout",
        "20",
    ]
    environment = {
        "AWS_CLI_AUTO_PROMPT": "off",
        "AWS_CLI_HISTORY_FILE": "/dev/null",
        "AWS_CONFIG_FILE": "/dev/null",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_MAX_ATTEMPTS": "1",
        "AWS_PAGER": "",
        "AWS_PROFILE": "default",
        "AWS_REGION": "us-east-1",
        "AWS_RETRY_MODE": "standard",
        "AWS_SHARED_CREDENTIALS_FILE": "/home/developer/.aws/credentials",
        "HOME": "/nonexistent",
        "LC_ALL": "C",
        "PATH": str(_AWS_CLI_CANONICAL_PATH.parent),
    }
    try:
        completed = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=35,
        )
        payload = completed.stdout
        if (
            completed.returncode != 0
            or not isinstance(payload, str)
            or not payload.strip()
            or len(payload.encode("utf-8")) > _MAX_AWS_SECRET_RESPONSE_BYTES
        ):
            _raise("futures_r10_slice3_credential_preparation_failed")
        return payload
    except R10Slice3RunnerError:
        raise
    except Exception:
        _raise("futures_r10_slice3_credential_preparation_failed")


def _prepare_r10_canonical_session() -> Any:
    """Resolve credentials and construct the zero-retry client before claim."""

    try:
        with r10_tool._suppress_coinbase_sdk_logging():
            session = r10_tool._build_r10_canonical_preview_session(
                run_secret_lookup=_lookup_fixed_r10_secret,
            )
        if type(session) is not r10_tool._R10CanonicalPreviewSession:
            _raise("futures_r10_slice3_credential_preparation_failed")
        session.validate()
        return session
    except R10Slice3RunnerError:
        raise
    except Exception:
        _raise("futures_r10_slice3_credential_preparation_failed")


def build_deferred_r10_session(
    *,
    store: FuturesOrderPreviewArtifactStore,
    prepared_session: Any,
) -> Any:
    """Inject the exact already-prepared R10 session into its one-use holder."""

    if type(prepared_session) is not r10_tool._R10CanonicalPreviewSession:
        _raise("futures_r10_slice3_credential_preparation_failed")
    prepared_session.validate()
    session = r10_tool.DeferredR10PreviewRestClient(
        store=store,
        prepared_session=prepared_session,
    )
    take = getattr(session, "take_accepted_session", None)
    if not callable(take):
        _raise("futures_r10_slice3_same_session_handoff_unavailable")
    return session


def _build_r10_store() -> FuturesOrderPreviewArtifactStore:
    return r10_tool.build_r10_store(FUTURES_PREVIEW_R10_ARTIFACT_PATH)


def _build_accepted_handoff_store() -> FileAcceptedHandoffArtifactStore:
    return FileAcceptedHandoffArtifactStore(ACCEPTED_HANDOFF_ARTIFACT_PATH)


def _sanitized_handoff_halted_result(
    store: FileAcceptedHandoffArtifactStore,
    *,
    preview_generation: int,
    preview_artifact_type: str,
    preview_artifact_file_sha256: str,
    preview_evidence_sha256: str,
) -> SanitizedSlice3Result:
    try:
        terminal = store.read_terminal_result()
    except AcceptedHandoffArtifactError:
        _raise("futures_r10_slice3_accepted_handoff_terminal_invalid")
    expected_reasons = {
        "plan": "accepted_handoff_plan_failed",
        "admission": "accepted_handoff_admission_failed",
        "activation": "accepted_handoff_activation_failed",
        "port_construction": "accepted_handoff_port_construction_failed",
        "delegation": "accepted_handoff_delegation_failed",
    }
    if (
        terminal.status != "halted"
        or expected_reasons.get(terminal.stage) != terminal.reason_code
        or terminal.preview_generation != preview_generation
        or terminal.preview_artifact_type != preview_artifact_type
        or terminal.preview_artifact_file_sha256
        != preview_artifact_file_sha256
        or terminal.preview_evidence_sha256 != preview_evidence_sha256
        or _SAFE_REASON_RE.fullmatch(terminal.reason_code) is None
        or _SHA256_RE.fullmatch(terminal.artifact_sha256) is None
    ):
        _raise("futures_r10_slice3_accepted_handoff_terminal_invalid")
    return SanitizedSlice3Result(
        status="handoff_halted",
        reason_code=terminal.reason_code,
        terminal_artifact_sha256=terminal.artifact_sha256,
        terminal_evidence=None,
    )


def recover_r10_accepted_handoff_offline(
    *,
    now_provider: Callable[[], datetime] | None = None,
) -> SanitizedSlice3Result:
    """Terminalize only the accepted-Preview handoff after a local crash gap.

    This path performs file validation only.  It does not hydrate credentials,
    construct a Coinbase delegate or port, run Preview, or open an action claim.
    """

    if not R10_SLICE3_END_TO_END_READY:
        _raise("futures_r10_slice3_workflow_not_ready")
    _validate_audited_state()
    for path in (
        SLICE3_ADMISSION_ARTIFACT_PATH,
        SLICE3_ACTIVATION_ARTIFACT_PATH,
        SLICE3_ACTION_JOURNAL_PATH,
        SLICE3_READ_JOURNAL_PATH,
        SLICE3_TERMINAL_EVIDENCE_PATH,
    ):
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            _raise("futures_r10_slice3_offline_handoff_recovery_blocked")
        _raise("futures_r10_slice3_offline_handoff_recovery_blocked")
    try:
        preview_store = FuturesOrderPreviewArtifactStore(
            FUTURES_PREVIEW_R10_ARTIFACT_PATH,
            reservation_lock_nonblocking=True,
        )
        terminal = preview_store.read_completed()
    except FuturesOrderPreviewArtifactError:
        _raise("futures_r10_slice3_offline_handoff_preview_invalid")
    evidence_sha256 = terminal.get("evidence_sha256")
    if (
        terminal.get("status") != "accepted"
        or terminal.get("outcome") != "accepted"
        or terminal.get("artifact_type") != FUTURES_PREVIEW_R10_ARTIFACT_TYPE
        or not isinstance(evidence_sha256, str)
        or _SHA256_RE.fullmatch(evidence_sha256) is None
    ):
        _raise("futures_r10_slice3_offline_handoff_preview_invalid")
    preview_file_sha256 = _sha256_file(FUTURES_PREVIEW_R10_ARTIFACT_PATH)
    try:
        recovered = halt_accepted_preview_handoff_offline(
            path=ACCEPTED_HANDOFF_ARTIFACT_PATH,
            preview_generation=10,
            preview_artifact_type=FUTURES_PREVIEW_R10_ARTIFACT_TYPE,
            preview_artifact_file_sha256=preview_file_sha256,
            preview_evidence_sha256=evidence_sha256,
            now=(now_provider or (lambda: datetime.now(timezone.utc)))(),
        )
    except AcceptedHandoffArtifactError:
        _raise("futures_r10_slice3_accepted_handoff_terminal_invalid")
    if recovered.status != "halted":
        _raise("futures_r10_slice3_accepted_handoff_terminal_invalid")
    return _sanitized_handoff_halted_result(
        _build_accepted_handoff_store(),
        preview_generation=10,
        preview_artifact_type=FUTURES_PREVIEW_R10_ARTIFACT_TYPE,
        preview_artifact_file_sha256=preview_file_sha256,
        preview_evidence_sha256=evidence_sha256,
    )


def _build_r10_producer(
    *,
    deferred_session: Any,
    store: FuturesOrderPreviewArtifactStore,
) -> FuturesOrderPreviewProducer:
    return r10_tool.build_r10_producer(
        rest_client=deferred_session,
        store=store,
    )


def _validate_accepted_handoff_provenance(
    *,
    deferred_session: object,
    accepted_session: object,
    r10_store: object,
    persisted_terminal: Mapping[str, Any],
    r10_artifact_file_sha256: str,
) -> None:
    """Bind Slice 3 to the exact callback-local R10 delegate and fixed file."""

    try:
        if (
            type(deferred_session) is not r10_tool.DeferredR10PreviewRestClient
            or type(accepted_session) is not r10_tool.R10AcceptedSessionHandoff
            or type(r10_store) is not FuturesOrderPreviewArtifactStore
            or getattr(
                deferred_session,
                "_DeferredR10PreviewRestClient__store",
                None,
            )
            is not r10_store
            or r10_store.path != FUTURES_PREVIEW_R10_ARTIFACT_PATH
            or _SHA256_RE.fullmatch(r10_artifact_file_sha256) is None
        ):
            raise ValueError
        canonical_session = getattr(
            deferred_session,
            "_DeferredR10PreviewRestClient__session",
            None,
        )
        if type(canonical_session) is not r10_tool._R10CanonicalPreviewSession:
            raise ValueError
        canonical_session.validate()
        account_binding = accepted_session.account_binding
        account_binding.validate()
        if (
            accepted_session.delegate is not canonical_session.delegate
            or account_binding.session_binding_token
            != canonical_session.session_binding_token
            or dict(r10_store.read_completed()) != dict(persisted_terminal)
            or _sha256_file(FUTURES_PREVIEW_R10_ARTIFACT_PATH)
            != r10_artifact_file_sha256
        ):
            raise ValueError
    except Exception:
        _raise("futures_r10_slice3_same_session_handoff_invalid")


def _consume_accepted_handoff_capability(
    capability: object,
    *,
    deferred_session: object,
    accepted_session: object,
    r10_store: object,
    persisted_terminal: object,
) -> None:
    if not _ACCEPTED_HANDOFF_CAPABILITIES.consume(
        capability,
        deferred_session=deferred_session,
        accepted_session=accepted_session,
        r10_store=r10_store,
        persisted_terminal=persisted_terminal,
    ):
        _raise("futures_r10_slice3_same_session_handoff_invalid")


def _validated_detached_terminal_envelope(
    value: object,
    *,
    expected_status: str,
) -> Mapping[str, object]:
    try:
        if not isinstance(value, Mapping):
            raise TypeError
        canonical = json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        detached = json.loads(canonical)
    except (TypeError, ValueError):
        _raise("futures_r10_slice3_terminal_result_invalid")
    if not isinstance(detached, dict):
        _raise("futures_r10_slice3_terminal_result_invalid")
    expected_schema = {
        "restored_baseline": "slice3-terminal-roundtrip-evidence-v2",
        "halted": "slice3-halted-reconciliation-evidence-v1",
    }.get(expected_status)
    supplied_hash = detached.get("evidence_sha256")
    without_hash = {
        key: item for key, item in detached.items() if key != "evidence_sha256"
    }
    computed_hash = hashlib.sha256(
        json.dumps(
            without_hash,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    if (
        expected_schema is None
        or detached.get("schema_version") != expected_schema
        or detached.get("status") != expected_status
        or detached.get("raw_response_included") is not False
        or detached.get("identifier_values_included") is not False
        or (
            expected_status == "halted"
            and detached.get("exception_text_included") is not False
        )
        or not isinstance(supplied_hash, str)
        or supplied_hash != computed_hash
    ):
        _raise("futures_r10_slice3_terminal_result_invalid")
    return MappingProxyType(detached)


def _sanitize_slice3_result(
    value: object,
    *,
    plan: object,
    now: datetime,
) -> SanitizedSlice3Result:
    if type(value) is not Slice3OrchestrationResult:
        _raise("futures_r10_slice3_terminal_result_invalid")
    status = value.status
    evidence = value.terminal_evidence
    try:
        if (
            status is Slice3OrchestrationStatus.RESTORED_BASELINE
            and type(evidence) is Slice3TerminalRoundtripEvidence
        ):
            evidence.validate(plan, now=now)
            envelope = evidence.sanitized_evidence()
        elif (
            status is Slice3OrchestrationStatus.HALTED
            and type(evidence) is Slice3HaltedReconciliationEvidence
        ):
            evidence.validate(plan=plan, now=now)
            envelope = evidence.sanitized_evidence(plan=plan, now=now)
        else:
            _raise("futures_r10_slice3_terminal_result_invalid")
    except R10Slice3RunnerError:
        raise
    except Exception:
        _raise("futures_r10_slice3_terminal_result_invalid")
    status_value = status.value
    reason_code = value.reason_code
    terminal_sha256 = value.terminal_artifact_sha256
    detached = _validated_detached_terminal_envelope(
        envelope,
        expected_status=status_value,
    )
    if (
        detached.get("plan_sha256") != getattr(plan, "plan_sha256", None)
        or not isinstance(reason_code, str)
        or _SAFE_REASON_RE.fullmatch(reason_code) is None
        or not isinstance(terminal_sha256, str)
        or _SHA256_RE.fullmatch(terminal_sha256) is None
    ):
        _raise("futures_r10_slice3_terminal_result_invalid")
    return SanitizedSlice3Result(
        status=status_value,
        reason_code=reason_code,
        terminal_artifact_sha256=terminal_sha256,
        terminal_evidence=detached,
    )


def _create_boundary_is_consumed(*, action_store: object, plan: object) -> bool:
    try:
        claim = plan.action_claim(Slice3ActionKind.CREATE)
        record = action_store.inspect(claim)
    except Exception:
        return False
    return bool(
        record is not None
        and record.event
        in {
            Slice3ClaimEvent.EXCHANGE_BOUNDARY,
            Slice3ClaimEvent.OUTCOME,
        }
    )


def _run_with_same_process_risk_off_continuation(
    *,
    orchestrator: object,
    action_store: object,
    plan: object,
    activation_store: object,
    expected_activation_manifest_sha256: str,
) -> object:
    """Re-enter once after a catchable consumed Create boundary.

    The second call reaches the orchestrator's recovered-lease branch and may
    perform only sealed reads/risk-off actions.  It cannot survive SIGKILL,
    interpreter death, container loss, or host loss because private identifiers
    and the canonical delegate are intentionally never persisted.
    """

    kwargs = {
        "plan": plan,
        "activation_store": activation_store,
        "expected_activation_manifest_sha256": (
            expected_activation_manifest_sha256
        ),
    }
    try:
        return orchestrator.run(**kwargs)
    except BaseException:
        if not _create_boundary_is_consumed(
            action_store=action_store,
            plan=plan,
        ):
            raise
        return orchestrator.run(**kwargs)


def _runtime_enforces_admission_binding() -> bool:
    """Detect the audited activation/orchestrator admission hash contract.

    This is intentionally structural and fail-closed.  Readiness additionally
    requires non-placeholder file hashes, so a matching signature alone can
    never activate unreviewed code.
    """

    try:
        from application.admin_api.futures_terminal_roundtrip_activation import (
            Slice3ActivationManifest,
        )

        manifest_fields = set(inspect.signature(Slice3ActivationManifest).parameters)
        orchestrator_fields = set(
            inspect.signature(Slice3TerminalRoundtripOrchestrator.__init__).parameters
        )
    except Exception:
        return False
    return bool(
        "admission_chain_sha256" in manifest_fields
        and "admission_record_sha256" in manifest_fields
        and "admission_artifact_file_sha256" in manifest_fields
        and "admission_module_sha256" in manifest_fields
        and "admission_store" in orchestrator_fields
    )


def run_accepted_slice3_handoff(
    *,
    ephemeral_evidence: Mapping[str, Any],
    persisted_terminal: Mapping[str, Any],
    accepted_session: Any,
    deferred_session: Any,
    r10_store: FuturesOrderPreviewArtifactStore,
    callback_capability: object,
    authorization_bytes: bytes,
    r10_artifact_file_sha256: str,
    now: datetime,
    handoff_terminalizer: AcceptedHandoffTerminalizer,
) -> SanitizedSlice3Result:
    """Seal admission and activation, then run one exact finite Slice 3."""

    if type(handoff_terminalizer) is not AcceptedHandoffTerminalizer:
        _raise("futures_r10_slice3_accepted_handoff_terminal_invalid")
    terminal_now = lambda: now
    try:
        def validate_delegation() -> tuple[str, str, object, object]:
            if not R10_SLICE3_END_TO_END_READY:
                _raise("futures_r10_slice3_workflow_not_ready")
            if not _runtime_enforces_admission_binding():
                _raise("futures_r10_slice3_runtime_admission_binding_unavailable")
            current_backend_revision, current_openapi_sha256 = (
                _validate_audited_state()
            )
            if (
                not isinstance(authorization_bytes, bytes)
                or hashlib.sha256(authorization_bytes).hexdigest()
                != OPERATOR_AUTHORIZATION_SHA256
                or not isinstance(now, datetime)
                or now.tzinfo is None
                or not isinstance(r10_artifact_file_sha256, str)
                or _SHA256_RE.fullmatch(r10_artifact_file_sha256) is None
            ):
                _raise("futures_r10_slice3_accepted_handoff_binding_invalid")
            _consume_accepted_handoff_capability(
                callback_capability,
                deferred_session=deferred_session,
                accepted_session=accepted_session,
                r10_store=r10_store,
                persisted_terminal=persisted_terminal,
            )
            _validate_accepted_handoff_provenance(
                deferred_session=deferred_session,
                accepted_session=accepted_session,
                r10_store=r10_store,
                persisted_terminal=persisted_terminal,
                r10_artifact_file_sha256=r10_artifact_file_sha256,
            )
            delegate = getattr(accepted_session, "delegate", None)
            account_binding = getattr(accepted_session, "account_binding", None)
            if delegate is None or account_binding is None:
                _raise("futures_r10_slice3_same_session_handoff_invalid")
            validate_account = getattr(account_binding, "validate", None)
            if callable(validate_account):
                validate_account()
            return (
                current_backend_revision,
                current_openapi_sha256,
                delegate,
                account_binding,
            )

        (
            current_backend_revision,
            current_openapi_sha256,
            delegate,
            account_binding,
        ) = handoff_terminalizer.call(
            AcceptedHandoffStage.DELEGATION,
            validate_delegation,
            now=terminal_now,
        )

        def build_plan() -> tuple[object, object]:
            _validate_r10_documented_preview_expiry_boundary(
                ephemeral_evidence=ephemeral_evidence,
                now=now,
            )
            accepted_r10_binding = Slice3AcceptedR10Binding.from_accepted_evidence(
                artifact_file_sha256=r10_artifact_file_sha256,
                evidence=persisted_terminal,
            )
            return build_slice3_admitted_plan_from_r10(
                ephemeral_evidence=ephemeral_evidence,
                persisted_terminal=persisted_terminal,
                accepted_r10_binding=accepted_r10_binding,
                account_binding=account_binding,
                authorization_sha256=OPERATOR_AUTHORIZATION_SHA256,
                now=now,
                backend_revision=current_backend_revision,
                openapi_revision=current_openapi_sha256,
            )

        plan, authority_bundle = handoff_terminalizer.call(
            AcceptedHandoffStage.PLAN,
            build_plan,
            now=terminal_now,
        )

        def seal_admission() -> tuple[object, object]:
            admission_chain = build_slice3_admission_chain(
                plan=plan,
                authority_bundle=authority_bundle,
                now=now,
                expires_at=plan.risk_off_expires_at,
            )
            admission_store = production_slice3_admission_store()
            admission_seal = admission_store.seal(admission_chain, now=now)
            if (
                not (
                    admission_seal.chain is admission_chain
                    or admission_seal.chain == admission_chain
                )
                or admission_seal.chain_sha256 != admission_chain.chain_sha256
            ):
                _raise("futures_r10_slice3_admission_seal_invalid")
            return admission_store, admission_seal

        admission_store, admission_seal = handoff_terminalizer.call(
            AcceptedHandoffStage.ADMISSION,
            seal_admission,
            now=terminal_now,
        )

        def seal_activation() -> tuple[object, object]:
            activation_manifest = build_slice3_activation_manifest(
                plan=plan,
                persisted_terminal=persisted_terminal,
                r10_artifact_file_sha256=r10_artifact_file_sha256,
                authorization_text=authorization_bytes,
                admission_seal=admission_seal,
                now=now,
            )
            activation_store = production_slice3_activation_store()
            activation_seal = activation_store.seal(
                activation_manifest,
                now=now,
            )
            if (
                activation_seal.manifest_sha256
                != activation_manifest.manifest_sha256
            ):
                _raise("futures_r10_slice3_activation_seal_invalid")
            return activation_store, activation_seal

        activation_store, activation_seal = handoff_terminalizer.call(
            AcceptedHandoffStage.ACTIVATION,
            seal_activation,
            now=terminal_now,
        )

        def prepare_port_dependencies() -> tuple[object, object, object, str]:
            action_store = FileSlice3ActionClaimStore(SLICE3_ACTION_JOURNAL_PATH)
            read_journal = FileSlice3ReadJournal(SLICE3_READ_JOURNAL_PATH)
            terminal_store = FileSlice3TerminalArtifactStore(
                SLICE3_TERMINAL_EVIDENCE_PATH
            )
            portfolio_evidence = plan.portfolio.sanitized_evidence()
            expected_portfolio_id_sha256 = portfolio_evidence.get(
                "portfolio_id_sha256"
            )
            if (
                not isinstance(expected_portfolio_id_sha256, str)
                or _SHA256_RE.fullmatch(expected_portfolio_id_sha256) is None
            ):
                _raise("futures_r10_slice3_portfolio_binding_invalid")
            return (
                action_store,
                read_journal,
                terminal_store,
                expected_portfolio_id_sha256,
            )

        (
            action_store,
            read_journal,
            terminal_store,
            expected_portfolio_id_sha256,
        ) = handoff_terminalizer.call(
            AcceptedHandoffStage.PORT_CONSTRUCTION,
            prepare_port_dependencies,
            now=terminal_now,
        )
        constructed_ports: list[StrictSlice3CoinbasePort] = []

        def one_port_factory(observed_activation_seal: Any) -> Any:
            def construct_port() -> Any:
                if (
                    getattr(observed_activation_seal, "manifest_sha256", None)
                    != activation_seal.manifest_sha256
                ):
                    _raise("futures_r10_slice3_activation_seal_invalid")
                if constructed_ports:
                    return constructed_ports[0]
                port = StrictSlice3CoinbasePort(
                    delegate,
                    create_client_order_id=plan.create.client_order_id,
                    close_client_order_id=plan.close_client_order_id,
                    preview_id=plan.create.preview_id,
                    limit_price=plan.create.limit_price,
                    contract_size=plan.preview.candidate_contract_size,
                    order_lookup_start_at=plan.preview.accepted_at,
                    order_lookup_end_at=plan.risk_off_expires_at,
                    account_binding=account_binding,
                    expected_portfolio_id_sha256=expected_portfolio_id_sha256,
                    expected_permission_evidence_sha256=(
                        plan.portfolio.permission_evidence_sha256
                    ),
                    expected_portfolio_catalog_sha256=(
                        plan.portfolio.portfolio_catalog_sha256
                    ),
                    expected_adapter_evidence_sha256=(
                        account_binding.adapter_evidence_sha256
                    ),
                )
                constructed_ports.append(port)
                return port

            return handoff_terminalizer.call(
                AcceptedHandoffStage.PORT_CONSTRUCTION,
                construct_port,
                now=terminal_now,
            )

        orchestrator = handoff_terminalizer.call(
            AcceptedHandoffStage.DELEGATION,
            lambda: Slice3TerminalRoundtripOrchestrator(
                action_store=action_store,
                read_journal=read_journal,
                terminal_store=terminal_store,
                port_factory=one_port_factory,
                now_provider=lambda: datetime.now(timezone.utc),
                admission_store=admission_store,
            ),
            now=terminal_now,
        )

        def delegate_and_sanitize() -> SanitizedSlice3Result:
            result = _run_with_same_process_risk_off_continuation(
                orchestrator=orchestrator,
                action_store=action_store,
                plan=plan,
                activation_store=activation_store,
                expected_activation_manifest_sha256=(
                    activation_seal.manifest_sha256
                ),
            )
            if len(constructed_ports) != 1:
                _raise("futures_r10_slice3_one_port_invariant_failed")
            return _sanitize_slice3_result(
                result,
                plan=plan,
                now=datetime.now(timezone.utc),
            )

        return handoff_terminalizer.delegate(
            delegate_and_sanitize,
            now=terminal_now,
        )
    except AcceptedHandoffArtifactError:
        _raise("futures_r10_slice3_accepted_handoff_terminal_invalid")
    except R10Slice3RunnerError:
        raise
    except Exception:
        _raise("futures_r10_slice3_accepted_handoff_blocked")


def execute_confirmed_workflow(
    *,
    authorization_bytes: bytes,
    now_provider: Callable[[], datetime] | None = None,
) -> EndToEndExecutionResult:
    """Consume R10 once and invoke Slice 3 only from its accepted callback."""

    if not R10_SLICE3_END_TO_END_READY:
        _raise("futures_r10_slice3_workflow_not_ready")
    validated = validate_production_preflight()
    if (
        not isinstance(authorization_bytes, bytes)
        or authorization_bytes != validated.authorization_bytes
        or hashlib.sha256(authorization_bytes).hexdigest()
        != OPERATOR_AUTHORIZATION_SHA256
    ):
        _raise("futures_r10_slice3_authorization_binding_invalid")
    clock = now_provider or (lambda: datetime.now(timezone.utc))
    prepared_session = _prepare_r10_canonical_session()
    _validate_attempt_paths_absent()
    store = _build_r10_store()
    deferred_session = build_deferred_r10_session(
        store=store,
        prepared_session=prepared_session,
    )
    producer = _build_r10_producer(
        deferred_session=deferred_session,
        store=store,
    )
    slice3_holder: list[SanitizedSlice3Result] = []

    def accepted_callback(
        ephemeral: dict[str, Any],
        persisted: dict[str, Any],
    ) -> None:
        artifact_sha256 = _sha256_file(FUTURES_PREVIEW_R10_ARTIFACT_PATH)
        r10_evidence_sha256 = persisted.get("evidence_sha256")
        try:
            handoff_store = _build_accepted_handoff_store()
            handoff_lease = handoff_store.reserve(
                preview_generation=10,
                preview_artifact_type=FUTURES_PREVIEW_R10_ARTIFACT_TYPE,
                preview_artifact_file_sha256=artifact_sha256,
                preview_evidence_sha256=r10_evidence_sha256,
                now=clock(),
            )
        except AcceptedHandoffArtifactError:
            _raise("futures_r10_slice3_accepted_handoff_terminal_invalid")
        handoff_terminalizer = AcceptedHandoffTerminalizer(
            store=handoff_store,
            lease=handoff_lease,
        )
        callback_capability: object | None = None
        try:
            accepted_session = handoff_terminalizer.call(
                AcceptedHandoffStage.DELEGATION,
                lambda: deferred_session.take_accepted_session(
                    ephemeral,
                    persisted,
                ),
                now=clock,
            )
            callback_capability = handoff_terminalizer.call(
                AcceptedHandoffStage.DELEGATION,
                lambda: _ACCEPTED_HANDOFF_CAPABILITIES.issue(
                    deferred_session=deferred_session,
                    r10_store=store,
                    accepted_session=accepted_session,
                    persisted_terminal=persisted,
                ),
                now=clock,
            )
            result = run_accepted_slice3_handoff(
                ephemeral_evidence=ephemeral,
                persisted_terminal=persisted,
                accepted_session=accepted_session,
                deferred_session=deferred_session,
                r10_store=store,
                callback_capability=callback_capability,
                authorization_bytes=authorization_bytes,
                r10_artifact_file_sha256=artifact_sha256,
                now=clock(),
                handoff_terminalizer=handoff_terminalizer,
            )
        except Exception:
            result = _sanitized_handoff_halted_result(
                handoff_store,
                preview_generation=10,
                preview_artifact_type=FUTURES_PREVIEW_R10_ARTIFACT_TYPE,
                preview_artifact_file_sha256=artifact_sha256,
                preview_evidence_sha256=r10_evidence_sha256,
            )
        finally:
            if callback_capability is not None:
                _ACCEPTED_HANDOFF_CAPABILITIES.revoke(callback_capability)
        if slice3_holder:
            _raise("futures_r10_slice3_callback_reentered")
        slice3_holder.append(result)

    try:
        # The producer invokes the accepted callback synchronously.  Keep the
        # same suppression scope around Preview and every immediate Slice 3
        # call so the reused SDK delegate cannot log raw response bodies.
        with _defer_slice3_termination_signals():
            with r10_tool._suppress_coinbase_sdk_logging():
                terminal = producer.run(accepted_callback=accepted_callback)
    except FuturesOrderPreviewArtifactError:
        try:
            terminal = store.read_completed()
        except FuturesOrderPreviewArtifactError:
            _raise("futures_r10_terminal_unavailable_after_consumption")
    if not isinstance(terminal, Mapping):
        _raise("futures_r10_terminal_invalid")
    accepted = (
        terminal.get("status") == "accepted" and terminal.get("outcome") == "accepted"
    )
    if accepted and len(slice3_holder) != 1:
        _raise("futures_r10_slice3_accepted_handoff_incomplete")
    if not accepted and slice3_holder:
        _raise("futures_r10_slice3_unaccepted_handoff_invalid")
    return EndToEndExecutionResult(
        terminal=dict(terminal),
        slice3_result=(slice3_holder[0] if slice3_holder else None),
        dependency_binding_sha256=validated.dependency_binding_sha256,
    )


def _safe_atom(value: object, *, status: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    pattern = _SAFE_STATUS_RE if status else _SAFE_REASON_RE
    return value if pattern.fullmatch(value) is not None else None


def safe_terminal_summary(result: EndToEndExecutionResult) -> dict[str, object]:
    """Return a strict allowlist that cannot echo raw terminal content."""

    if result.dependency_binding_sha256 != EXPECTED_DEPENDENCY_BINDING_SHA256:
        _raise("futures_r10_slice3_dependency_binding_invalid")
    r10_status = _safe_atom(result.terminal.get("status"), status=True)
    r10_outcome = _safe_atom(result.terminal.get("outcome"), status=True)
    summary: dict[str, object] = {
        "status": "terminal_halted",
        "r10_status": r10_status or "unknown",
        "r10_outcome": r10_outcome or "unknown",
        "r10_artifact_created": True,
        "raw_response_included": False,
        "private_identifier_values_included": False,
        "withheld_exception_text_included": False,
        "dependency_binding_sha256": result.dependency_binding_sha256,
    }
    slice3 = result.slice3_result
    if slice3 is None:
        summary["status"] = "terminal_no_mutation"
        summary.update(
            {
                "slice3_status": "not_run",
                "slice3_reason_code": "r10_not_accepted",
                "slice3_terminal_artifact_sha256": None,
            }
        )
        return summary
    raw_status = slice3.status
    raw_reason = getattr(slice3, "reason_code", None)
    raw_hash = getattr(slice3, "terminal_artifact_sha256", None)
    terminal_envelope: dict[str, object] | None = None
    if raw_status in {"restored_baseline", "halted"}:
        validated_envelope = _validated_detached_terminal_envelope(
            slice3.terminal_evidence,
            expected_status=raw_status,
        )
        terminal_envelope = json.loads(
            json.dumps(
                dict(validated_envelope),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    summary.update(
        {
            "slice3_status": _safe_atom(raw_status, status=True) or "unknown",
            "slice3_reason_code": _safe_atom(raw_reason) or "unknown",
            "slice3_terminal_artifact_sha256": (
                raw_hash
                if isinstance(raw_hash, str) and _SHA256_RE.fullmatch(raw_hash)
                else None
            ),
            "slice3_terminal_evidence": terminal_envelope,
        }
    )
    if raw_status == "restored_baseline":
        summary["status"] = "terminal_restored"
    elif raw_status == "handoff_halted":
        summary["slice3_exchange_mutation_attempt_count"] = 0
    return summary


def _before_attempt_summary(
    *,
    status: str,
    blocker: str | None,
    dependency_binding_sha256: str | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "blocker": blocker,
        "workflow_ready": R10_SLICE3_END_TO_END_READY,
        "artifact_created": False,
        "coinbase_client_constructed": False,
        "coinbase_read_ran": False,
        "preview_order_attempt_count": 0,
        "slice3_exchange_mutation_attempt_count": 0,
        "dependency_binding_sha256": dependency_binding_sha256,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "One fixed R10 Preview and conditional terminal Slice 3; no retry, "
            "fallback, redirect, second Create, R11, Slice 4, or Slice 5."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument(
        "--confirm-one-r10-preview-and-slice3",
        action="store_true",
    )
    return parser


def _safe_error_reason(exc: R10Slice3RunnerError) -> str:
    reason = str(exc)
    if _SAFE_REASON_RE.fullmatch(reason) is None or not reason.startswith(
        "futures_r10_slice3_"
    ):
        return "futures_r10_slice3_validation_blocked"
    return reason


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.confirm_one_r10_preview_and_slice3 and not R10_SLICE3_END_TO_END_READY:
        print(
            json.dumps(
                _before_attempt_summary(
                    status="blocked",
                    blocker="futures_r10_slice3_workflow_not_ready",
                ),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    try:
        preflight = validate_production_preflight()
    except R10Slice3RunnerError as exc:
        print(
            json.dumps(
                _before_attempt_summary(
                    status="blocked",
                    blocker=_safe_error_reason(exc),
                ),
                sort_keys=True,
            )
        )
        return 2
    except Exception:
        print(
            json.dumps(
                _before_attempt_summary(
                    status="blocked",
                    blocker="futures_r10_slice3_validation_blocked",
                ),
                sort_keys=True,
            )
        )
        return 2
    if args.preflight:
        if not R10_SLICE3_END_TO_END_READY:
            print(
                json.dumps(
                    _before_attempt_summary(
                        status="blocked",
                        blocker="futures_r10_slice3_workflow_not_ready",
                    ),
                    sort_keys=True,
                )
            )
            return 2
        print(
            json.dumps(
                _before_attempt_summary(
                    status="ready",
                    blocker=None,
                    dependency_binding_sha256=(
                        preflight.dependency_binding_sha256
                    ),
                ),
                sort_keys=True,
            )
        )
        return 0
    try:
        result = execute_confirmed_workflow(
            authorization_bytes=preflight.authorization_bytes,
        )
    except R10Slice3RunnerError as exc:
        print(
            json.dumps(
                {
                    "status": "blocked_or_consumed",
                    "blocker": _safe_error_reason(exc),
                    "raw_response_included": False,
                    "private_identifier_values_included": False,
                    "withheld_exception_text_included": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            json.dumps(
                {
                    "status": "blocked_or_consumed",
                    "blocker": "futures_r10_slice3_validation_blocked",
                    "raw_response_included": False,
                    "private_identifier_values_included": False,
                    "withheld_exception_text_included": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    try:
        summary = safe_terminal_summary(result)
    except Exception:
        print(
            json.dumps(
                {
                    "status": "terminal_summary_blocked",
                    "blocker": "futures_r10_slice3_validation_blocked",
                    "raw_response_included": False,
                    "private_identifier_values_included": False,
                    "withheld_exception_text_included": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] in {
        "terminal_restored",
        "terminal_no_mutation",
    } else 2


def _cli_entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        return main(argv)
    except BaseException:
        print(
            json.dumps(
                {
                    "status": "blocked_or_consumed",
                    "blocker": "futures_r10_slice3_outer_baseexception_blocked",
                    "raw_response_included": False,
                    "private_identifier_values_included": False,
                    "withheld_exception_text_included": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(_cli_entrypoint())
