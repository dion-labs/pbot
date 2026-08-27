#!/usr/bin/env python3
"""Tool-style detached control for pbot queue workers."""

from __future__ import annotations

import argparse
import json
import sys

from pbot.config import Settings
from pbot.managed_job import ManagedQueueController


def snapshot(controller: ManagedQueueController) -> dict[str, object]:
    return {
        "job": controller.status(),
        "pbot": {
            "state": controller.store.get_state(),
            "metrics": controller.store.metrics(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)

    start = subparsers.add_parser("start", help="start a detached queue worker and return immediately")
    start.add_argument("--serial")
    start.add_argument("--difficulty", action="append", dest="difficulties")
    start.add_argument("--deck-name")
    start.add_argument("--battle-id", help="run only the exact persisted frontier battle")
    start.add_argument("--limit", type=int, default=5)
    start.add_argument("--timeout", type=float, default=900)
    start.add_argument("--poll-interval", type=float, default=5)
    start.add_argument("--one-per-expansion", action="store_true")
    start.add_argument("--continuous", action="store_true")
    start.add_argument("--max-rounds", type=int, default=0)
    start.add_argument("--autonomous", action="store_true")
    start.add_argument("--max-actions", type=int, default=500)
    start.add_argument("--max-attempts-per-deck", type=int, default=1)

    subparsers.add_parser("status", help="show durable job, harness, and progress state")
    logs = subparsers.add_parser("logs", help="show only a bounded tail when diagnosis is needed")
    logs.add_argument("--lines", type=int, default=40)
    subparsers.add_parser("stop", help="stop the detached worker and recover its queue boundary")
    args = parser.parse_args()

    settings = Settings.load()
    controller = ManagedQueueController(settings.project_root, settings.database_path, settings.data_dir)

    if args.action == "start":
        if not 1 <= args.limit <= 100:
            parser.error("limit must be between 1 and 100")
        if not 1 <= args.max_actions <= 500:
            parser.error("max-actions must be between 1 and 500")
        if not 1 <= args.max_attempts_per_deck <= 3:
            parser.error("max-attempts-per-deck must be between 1 and 3")
        command = [
            sys.executable,
            str(
                settings.project_root
                / "scripts"
                / ("run_autonomous.py" if args.autonomous else "run_queue_worker.py")
            ),
        ]
        if args.serial or settings.adb_serial:
            command.extend(["--serial", args.serial or settings.adb_serial])
        for difficulty in args.difficulties or ():
            command.extend(["--difficulty", difficulty])
        if args.deck_name and not args.autonomous:
            command.extend(["--deck-name", args.deck_name])
        if args.battle_id and not args.autonomous:
            command.extend(["--battle-id", args.battle_id])
        command.extend(["--timeout", str(args.timeout), "--poll-interval", str(args.poll_interval)])
        if args.autonomous:
            command.extend([
                "--max-actions",
                str(args.max_actions),
                "--max-attempts-per-deck",
                str(args.max_attempts_per_deck),
            ])
        else:
            command.extend(["--limit", str(args.limit)])
        if args.one_per_expansion and not args.autonomous:
            command.append("--one-per-expansion")
        if args.continuous and not args.autonomous:
            command.append("--continuous")
        if args.max_rounds and not args.autonomous:
            command.extend(["--max-rounds", str(args.max_rounds)])
        controller.start(command)
        print(json.dumps(snapshot(controller), indent=2))
    elif args.action == "status":
        print(json.dumps(snapshot(controller), indent=2))
    elif args.action == "logs":
        print(json.dumps({**snapshot(controller), "log_tail": controller.log_tail(args.lines)}, indent=2))
    else:
        controller.stop()
        print(json.dumps(snapshot(controller), indent=2))


if __name__ == "__main__":
    main()
