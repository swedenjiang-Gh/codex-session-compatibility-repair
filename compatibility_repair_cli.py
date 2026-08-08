#!/usr/bin/env python3
"""Interactive Windows console frontend for Codex session compatibility repair."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import locale
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Iterable, Iterator

from session_compatibility import (
    SessionCandidate,
    default_backup_root,
    repair_session,
    scan_sessions,
)


OutputFunction = Callable[[str], None]


def parse_selection(text: str, candidate_count: int) -> list[int]:
    value = text.strip()
    if value.casefold() == "all":
        return list(range(candidate_count))
    if not value:
        raise ValueError("未选择任务")
    indexes: set[int] = set()
    for part in value.replace("，", ",").split(","):
        try:
            number = int(part.strip())
        except ValueError as exc:
            raise ValueError(f"无效序号：{part.strip() or '<空>'}") from exc
        if number < 1 or number > candidate_count:
            raise ValueError(f"序号超出范围：{number}")
        indexes.add(number - 1)
    return sorted(indexes)


def codex_processes_from_tasklist(tasklist_output: str) -> list[str]:
    related = {"chatgpt.exe", "codex.exe", "codex-code-mode-host.exe", "codexdesktop.exe"}
    found = {
        row[0]
        for row in csv.reader(io.StringIO(tasklist_output))
        if row and row[0].casefold() in related
    }
    return sorted(found, key=str.casefold)


def running_codex_processes() -> list[str]:
    result = subprocess.run(
        ["tasklist.exe", "/FO", "CSV", "/NH"],
        check=True,
        capture_output=True,
    )
    encoding = locale.getpreferredencoding(False) or "utf-8"
    return codex_processes_from_tasklist(result.stdout.decode(encoding, errors="replace"))


def wait_for_codex_exit(
    *,
    process_checker: Callable[[], list[str]] = running_codex_processes,
    sleep_fn: Callable[[float], None] = time.sleep,
    timeout_seconds: float = 1800,
    monotonic_values: Iterator[float] | None = None,
) -> bool:
    def now() -> float:
        if monotonic_values is not None:
            return next(monotonic_values)
        return time.monotonic()

    started = now()
    while process_checker():
        if now() - started >= timeout_seconds:
            return False
        sleep_fn(2.0)
    return True


def _wait_if_running(
    *,
    process_checker: Callable[[], list[str]],
    sleep_fn: Callable[[float], None],
    monotonic_values: Iterator[float] | None,
    output_fn: OutputFunction,
) -> bool:
    running = process_checker()
    if not running:
        return True
    output_fn("检测到 Codex/ChatGPT 正在运行：" + ", ".join(running))
    output_fn("请完全退出 Codex；工具正在等待 Codex 关闭（最长 30 分钟）……")
    return wait_for_codex_exit(
        process_checker=process_checker,
        sleep_fn=sleep_fn,
        timeout_seconds=1800,
        monotonic_values=monotonic_values,
    )


def _candidate_label(index: int, candidate: SessionCandidate) -> str:
    title = candidate.title or "<无标题>"
    timestamp = candidate.timestamp or "<未知时间>"
    return (
        f"{index:>3}. {candidate.thread_id} | {candidate.incompatible_count} 条 | "
        f"{timestamp} | {title}"
    )


def _write_log(log_file: Path, lines: Iterable[str]) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(line + "\n")


def run_interactive(
    codex_root: Path,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: OutputFunction = print,
    process_checker: Callable[[], list[str]] = running_codex_processes,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_values: Iterator[float] | None = None,
    backup_root: Path | None = None,
    log_root: Path | None = None,
) -> int:
    codex_root = codex_root.expanduser().resolve()
    backup_root = (backup_root or default_backup_root()).resolve()
    log_root = (log_root or (backup_root.parent / "logs")).resolve()

    if not _wait_if_running(
        process_checker=process_checker,
        sleep_fn=sleep_fn,
        monotonic_values=monotonic_values,
        output_fn=output_fn,
    ):
        output_fn("等待 Codex 退出超时，未修改任何会话。")
        return 3

    output_fn("正在扫描 Codex 会话……")
    candidates = scan_sessions(codex_root)
    if not candidates:
        output_fn("未发现需要修复的跨模型 reasoning 记录。")
        return 0

    output_fn(f"发现 {len(candidates)} 个候选任务：")
    for index, candidate in enumerate(candidates, start=1):
        output_fn(_candidate_label(index, candidate))

    try:
        selected_indexes = parse_selection(
            input_fn("输入任务序号（多个用逗号分隔，或输入 ALL）："),
            len(candidates),
        )
    except ValueError as exc:
        output_fn(f"选择无效：{exc}")
        return 2
    selected = [candidates[index] for index in selected_indexes]

    mode = input_fn("选择模式：1=修复并备份（推荐），2=修复但不备份：").strip()
    if mode not in {"1", "2"}:
        output_fn("已取消，未修改任何数据。")
        return 0
    with_backup = mode == "1"
    expected_confirmation = "APPLY" if with_backup else "APPLY-NO-BACKUP"

    output_fn("\n修复预览：")
    output_fn(f"任务数量：{len(selected)}")
    output_fn(f"reasoning 记录：{sum(item.incompatible_count for item in selected)}")
    output_fn("备份：" + ("是" if with_backup else "否（不可回退）"))
    confirmation = input_fn(f"输入 {expected_confirmation} 执行，输入其他内容取消：").strip()
    if confirmation != expected_confirmation:
        output_fn("已取消，未修改任何数据。")
        return 0

    if not _wait_if_running(
        process_checker=process_checker,
        sleep_fn=sleep_fn,
        monotonic_values=monotonic_values,
        output_fn=output_fn,
    ):
        output_fn("等待 Codex 退出超时，未修改任何会话。")
        return 3

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_directory = (
        backup_root / f"session-compatibility-repair-{timestamp}"
        if with_backup
        else None
    )
    log_file = log_root / f"session-compatibility-repair-{timestamp}.log"
    log_lines = [
        f"started={dt.datetime.now().isoformat()}",
        f"mode={'backup' if with_backup else 'no-backup'}",
        f"selected={len(selected)}",
    ]

    failures = 0
    modified_total = 0
    for candidate in selected:
        try:
            result = repair_session(candidate, backup_directory=backup_directory)
        except Exception as exc:
            failures += 1
            output_fn(f"失败：{candidate.thread_id}：{exc}")
            log_lines.append(f"FAILED thread={candidate.thread_id} error={type(exc).__name__}: {exc}")
        else:
            modified_total += result.modified_count
            output_fn(f"成功：{candidate.thread_id}，修复 {result.modified_count} 条")
            log_lines.append(
                f"SUCCESS thread={candidate.thread_id} modified={result.modified_count} "
                f"backup={result.backup_path or '<none>'}"
            )

    log_lines.append(f"completed={dt.datetime.now().isoformat()} modified={modified_total} failures={failures}")
    _write_log(log_file, log_lines)
    output_fn(f"日志：{log_file}")
    if failures:
        output_fn(f"处理完成，但有 {failures} 个任务失败。")
        return 1
    output_fn(f"修复完成，共清空 {modified_total} 条不兼容 reasoning 记录。")
    if backup_directory is not None:
        output_fn(f"备份目录：{backup_directory}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex 跨模型历史会话兼容修复工具")
    parser.add_argument(
        "--codex-root",
        type=Path,
        default=Path.home() / ".codex",
        help="Codex 数据目录，默认是 %%USERPROFILE%%\\.codex",
    )
    parser.add_argument("--backup-root", type=Path, help="备份根目录；默认优先使用 D:\\codex\\backups")
    parser.add_argument("--log-root", type=Path, help="日志根目录；默认使用备份目录旁的 logs")
    parser.add_argument("--no-pause", action="store_true", help="结束时不等待按 Enter，供自动化测试使用")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        return run_interactive(
            arguments.codex_root,
            backup_root=arguments.backup_root,
            log_root=arguments.log_root,
        )
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    finally:
        if not arguments.no_pause:
            try:
                input("\n按 Enter 退出……")
            except EOFError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
