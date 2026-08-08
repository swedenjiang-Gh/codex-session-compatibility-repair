#!/usr/bin/env python3
"""Scan and safely repair incompatible Codex history records."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Callable
import uuid


class SessionChangedError(RuntimeError):
    """Raised when a session changes between preview and repair."""


@dataclass(frozen=True)
class SessionCandidate:
    path: Path
    group: str
    thread_id: str
    title: str
    timestamp: str
    incompatible_count: int
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class RepairResult:
    thread_id: str
    path: Path
    modified_count: int
    backup_path: Path | None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _decode_record(line: bytes, path: Path, line_number: int) -> dict[str, object]:
    payload = line.rstrip(b"\r\n")
    if line_number == 1 and payload.startswith(b"\xef\xbb\xbf"):
        payload = payload[3:]
    try:
        record = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSONL record: {path}:{line_number}") from exc
    if not isinstance(record, dict):
        raise ValueError(f"JSONL record is not an object: {path}:{line_number}")
    return record


def _is_incompatible_reasoning(record: dict[str, object]) -> bool:
    payload = record.get("payload")
    return bool(
        record.get("type") == "response_item"
        and isinstance(payload, dict)
        and payload.get("type") == "reasoning"
        and isinstance(payload.get("content"), list)
        and payload["content"]
    )


def _is_incompatible_web_search_call(record: dict[str, object]) -> bool:
    payload = record.get("payload")
    return bool(
        record.get("type") == "response_item"
        and isinstance(payload, dict)
        and payload.get("type") == "web_search_call"
        and isinstance(payload.get("id"), str)
        and payload["id"].startswith("call_")
    )


def _is_incompatible_record(record: dict[str, object]) -> bool:
    return _is_incompatible_reasoning(record) or _is_incompatible_web_search_call(record)


def _inspect_session(path: Path, group: str) -> SessionCandidate | None:
    thread_id = ""
    title = ""
    timestamp = ""
    incompatible_count = 0
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = _decode_record(line, path, line_number)
            if record.get("type") == "session_meta" and isinstance(record.get("payload"), dict):
                payload = record["payload"]
                assert isinstance(payload, dict)
                thread_id = str(payload.get("id") or thread_id)
                title = str(payload.get("title") or title)
                timestamp = str(record.get("timestamp") or timestamp)
            if _is_incompatible_record(record):
                incompatible_count += 1
    if incompatible_count == 0:
        return None
    if not thread_id:
        thread_id = path.stem.rsplit("-", 1)[-1]
    stat = path.stat()
    return SessionCandidate(
        path=path,
        group=group,
        thread_id=thread_id,
        title=title,
        timestamp=timestamp,
        incompatible_count=incompatible_count,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sha256=_file_sha256(path),
    )


def scan_sessions(root: Path) -> list[SessionCandidate]:
    root = root.expanduser().resolve()
    candidates: list[SessionCandidate] = []
    for group in ("sessions", "archived_sessions"):
        folder = root / group
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.jsonl")):
            candidate = _inspect_session(path, group)
            if candidate is not None:
                candidates.append(candidate)
    return sorted(candidates, key=lambda item: (item.timestamp, str(item.path)), reverse=True)


def default_backup_root(*, drive_exists: Callable[[Path], bool] = Path.is_dir) -> Path:
    d_drive = Path("D:/")
    if drive_exists(d_drive):
        return d_drive / "codex" / "backups"
    return Path.home() / "codex-backups"


def _line_ending(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return b"\r\n"
    if line.endswith(b"\n"):
        return b"\n"
    return b""


def _prepare_repaired_lines(candidate: SessionCandidate, source_lines: list[bytes]) -> tuple[list[bytes], set[int]]:
    repaired_lines: list[bytes] = []
    changed_indexes: set[int] = set()
    for index, line in enumerate(source_lines):
        record = _decode_record(line, candidate.path, index + 1)
        if _is_incompatible_reasoning(record):
            payload = record["payload"]
            assert isinstance(payload, dict)
            payload["content"] = []
            repaired_lines.append(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                + _line_ending(line)
            )
            changed_indexes.add(index)
        elif _is_incompatible_web_search_call(record):
            payload = record["payload"]
            assert isinstance(payload, dict)
            identifier = payload["id"]
            assert isinstance(identifier, str)
            payload["id"] = "ws_" + identifier.removeprefix("call_")
            repaired_lines.append(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                + _line_ending(line)
            )
            changed_indexes.add(index)
        else:
            repaired_lines.append(line)
    return repaired_lines, changed_indexes


def repair_session(candidate: SessionCandidate, *, backup_directory: Path | None) -> RepairResult:
    current = candidate.path.stat()
    current_hash = _file_sha256(candidate.path)
    if (
        current.st_size != candidate.size
        or current.st_mtime_ns != candidate.mtime_ns
        or current_hash != candidate.sha256
    ):
        raise SessionChangedError(f"Session changed after preview: {candidate.path}")

    source_lines = candidate.path.read_bytes().splitlines(keepends=True)
    repaired_lines, changed_indexes = _prepare_repaired_lines(candidate, source_lines)
    if len(changed_indexes) != candidate.incompatible_count:
        raise SessionChangedError(
            f"Incompatible record count changed: expected {candidate.incompatible_count}, found {len(changed_indexes)}"
        )

    backup_path: Path | None = None
    if backup_directory is not None:
        backup_directory.mkdir(parents=True, exist_ok=True)
        backup_path = backup_directory / f"{candidate.thread_id}-{candidate.path.name}"
        if backup_path.exists():
            raise FileExistsError(f"Backup already exists: {backup_path}")
        shutil.copy2(candidate.path, backup_path)
        if _file_sha256(backup_path) != current_hash:
            raise RuntimeError(f"Backup hash verification failed: {backup_path}")

    temp_path = candidate.path.with_name(f".{candidate.path.name}.{uuid.uuid4().hex}.repairing")
    try:
        with temp_path.open("xb") as handle:
            for line in repaired_lines:
                handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

        verified_lines = temp_path.read_bytes().splitlines(keepends=True)
        if len(verified_lines) != len(source_lines):
            raise RuntimeError("Prepared session line count changed")
        remaining = 0
        for index, line in enumerate(verified_lines):
            record = _decode_record(line, temp_path, index + 1)
            if _is_incompatible_record(record):
                remaining += 1
            if index not in changed_indexes and line != source_lines[index]:
                raise RuntimeError(f"Non-target line changed: {index + 1}")
        if remaining:
            raise RuntimeError(f"Prepared session still has {remaining} incompatible records")

        latest = candidate.path.stat()
        if latest.st_size != current.st_size or latest.st_mtime_ns != current.st_mtime_ns:
            raise SessionChangedError(f"Session changed before replacement: {candidate.path}")
        os.replace(temp_path, candidate.path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return RepairResult(
        thread_id=candidate.thread_id,
        path=candidate.path,
        modified_count=len(changed_indexes),
        backup_path=backup_path,
    )
