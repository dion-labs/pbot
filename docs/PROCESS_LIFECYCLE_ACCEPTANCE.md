# Disposable process lifecycle acceptance (PB-025)

This is an opt-in OS-boundary harness for `ManagedQueueController` and the actual
managed runner. It creates inert Python process trees, sends real signals only
to verified fixture-owned targets, and records cleanup. It never runs ADB,
network clients, gameplay scripts, an API server, or the dashboard. It does not
read a production environment file, database, log, or runtime directory.

Run from an installed checkout:

```bash
uv run python scripts/check_process_lifecycle.py --run --repeat 3
```

Without `--run`, the command exits before creating any fixture process. Use
`--case stubborn-grandchild` (repeatable) for a targeted rerun. `npm test` does
not implicitly opt in. Portfolio workers must wrap this command with their
coordinator's resource runner.

Every invocation creates a fresh temporary evidence directory and prints its
path. Each case gets its own project, database, logs, UUID token, and explicit
minimal environment. The fixture creates a synthetic attempt and queue claim;
there is no device adapter or account data. Reports include source hashes,
platform/Python versions, owned PIDs, process groups, creation times, fixture
tokens, controller outcomes, and cleanup results. Preserve `report.json` and
the case logs when investigating failures. Temporary evidence contains synthetic
data only and is intentionally retained for review.

The command exits nonzero on any assertion failure. It stops immediately if
cleanup cannot be verified. It handles SIGINT/SIGTERM by cleaning the current
fixture; inert fixtures also have a 45-second lifetime bound if the harness is
forcibly killed. A cleanup result of `verified-empty` means all tracked fixture
groups were absent after cleanup, including reaped controller processes.

## Stable cases

| ID | Harness case | Expected outcome |
|---|---|---|
| PB-025.01 | concurrent-launch | Separate processes initialize a fresh database, race at a launch barrier, and yield exactly one worker plus one rejection; stop clears its tree and recovers one claim/attempt. |
| PB-025.02 | graceful-stop | Child and grandchild receive TERM, exit, and leave no process group; interrupted work recovers only afterward. |
| PB-025.03 | stubborn-grandchild | TERM-resistant grandchild cannot outlive a reported stop; escalation clears the group before recovery. |
| PB-025.04 | controller-interruption | Killing only the launching controller's owned group preserves the detached job; duplicate start rejects, then stop and a fresh run succeed. |
| PB-025.05 | runner-interruption | Killing the verified runner PID leaves descendants observable and reserved; stop clears them before recovery/restart. |
| PB-025.06 | unrelated-identity | A stale PID pointing to a different inert fixture is rejected as job ownership; that unrelated fixture receives no signal and survives a replacement job. |
| PB-025.07 | natural-completion | Successful inert trees finish without signals and a subsequent run gets a new ID. |
| PB-025.08 | stopper-interruption | Interrupting the stop controller after TERM leaves durable ownership; new start rejects and another stop finishes safely. |
| PB-025.09 | uncertain-descendant | A descendant that drops its inherited ownership marker causes refusal to signal/recover/restart after runner loss; the independently authorized harness cleans it up. |
| PB-025.10 | completion-with-descendant | A successful direct child cannot release ownership while a grandchild remains; stop is still required and available. |
| PB-025.11 | terminal-publication-window | A real temporary SQLite writer holds the finishing runner after terminal JSON publication; status preserves success when no descendants remain. |
| PB-025.12 | reservation-interruption | A live pre-PID reservation rejects duplicates; killing its controller permits failed-start recovery and a fresh run with no phantom claim. |
| PB-025.13 | pid-publication-failure | Actual write permission failure after child/grandchild startup clears the owned group and recovers work before allowing restart. |

The permission case requires a normal non-root user. It wraps the parent PID
publication step only to time a temporary directory permission change; the
filesystem raises the real error, and all process creation, signals, liveness,
cleanup and recovery use actual OS operations. Original permissions are restored
before the controller's failure handling proceeds.

## Ownership and acceptance limits

The controller checks the runner's exact random job ID in its command. Managed
children inherit a per-job environment marker, allowing remaining group members
to be verified after the runner exits. Inspection reads arguments/environment
only for candidate group members; environment contents are neither logged nor
stored. The marker identifies ownership, not authentication against another
local process.

If descendant ownership cannot be verified, the controller retains the job and
its work claims, refuses new launches and refuses to signal the uncertain group.
This includes legacy or custom descendants that discard the marker after the
runner disappears. Stop waits for executable group members, escalates TERM to
KILL when necessary, and does not claim success if termination is unconfirmed.
Jobs that deliberately escape their process group are outside this harness's
acceptance boundary.

The recorded 2026-09-22 acceptance applies to macOS/Apple Silicon and the exact
source hashes in each report. It does not certify physical device reconnect,
account/deck behavior, other OS kernels, escaped sessions, inaccessible process
metadata, or every scheduler/PID-reuse interleaving. Those remain separate gates
in [QA_CASES.md](QA_CASES.md).
