from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from .managed_job import JOB_TOKEN_ENV, ManagedJobState, utc_now
from .storage import Store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a queue worker command is required after --")

    state = ManagedJobState(args.data_dir / "managed-queue-job.json")
    store = Store(args.database)
    store.initialize()
    state.update(
        args.job_id,
        status="running",
        pid=os.getpid(),
        started_at=utc_now(),
        message="Detached queue worker is running",
    )

    try:
        completed = subprocess.run(command, cwd=args.project_root, check=False,
                                   env={**os.environ, JOB_TOKEN_ENV: args.job_id})
        success = completed.returncode == 0
        run_state = store.get_state()
        pbot_status = str(run_state.get("status") or "")
        status = (
            pbot_status
            if success and pbot_status in {"completed", "needs_attention"}
            else "succeeded" if success else "failed"
        )
        message = {
            "completed": "Autonomous objective completed",
            "needs_attention": str(run_state.get("objective") or "Autonomous run needs attention"),
            "succeeded": "Detached queue worker completed successfully",
        }.get(status, f"Detached queue worker exited with code {completed.returncode}")
        state.update(
            args.job_id,
            status=status,
            finished_at=utc_now(),
            exit_code=completed.returncode,
            message=message,
        )
        store.add_event(
            f"job.{status}",
            f"Detached queue job {args.job_id}: {message}",
            "warning" if status == "needs_attention" else "success" if success else "error",
            {"job_id": args.job_id, "exit_code": completed.returncode},
        )
        raise SystemExit(completed.returncode)
    except BaseException as exc:
        # SIGKILL cannot be handled, but status() repairs that case on the next
        # query. All ordinary Python failures get a durable terminal record.
        current = state.read()
        if current and current.get("status") in {"starting", "running"}:
            state.update(
                args.job_id,
                status="failed",
                finished_at=utc_now(),
                message=f"Managed runner failed: {exc}",
            )
            store.add_event(
                "job.failed",
                f"Detached queue job {args.job_id} failed: {exc}",
                "error",
                {"job_id": args.job_id},
            )
        raise


if __name__ == "__main__":
    main()
