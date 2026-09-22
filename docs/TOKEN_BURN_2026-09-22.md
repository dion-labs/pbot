# PB sustained-work record — 2026-09-22

## Baseline and boundaries

Baseline revision: `ae11413a1ef396a916fd1b2b9e0c810d1f9a8aae`. Preexisting status:

```text
clean
```

Preserve preexisting edits and user data. No installed application replacement, running-session restart, personal-account mutation or website deployment occurred. Synthetic/isolated automated tests do not certify hardware or account acceptance.

## Automated evidence

2026-09-22: npm test and npm run lint passed: production build, 1 rendered-HTML test, 108 Python tests. Raw local logs: `/tmp/dionlabs-burn-*.log`; durable counts recorded here because temporary logs may expire. No previous test result substituted for this current-tree baseline.

## Risk-based case register

Stable IDs below identify flow, failure, recovery and privacy requirements. Mapping names identify automated coverage, not proof that every manual procedure passed. All manual cases are **NOT RUN** this burn until a dated receipt is appended; hardware/account-dependent cases are **BLOCKED** without the designated disposable target/account.

| ID | Procedure / risk | Expected result | Automation / manual mapping |
|---|---|---|---|
| PB-001 | Start local dashboard/API with no connected device | Clear disconnected state; no fabricated progress | test_device; rendered HTML; manual local UI |
| PB-002 | Discover battle catalogue through scroll/unlock navigation | Stable IDs deduplicate observations and retain canonical progress | test_discovery_navigation/storage |
| PB-003 | Scan fresh account with unreadable or partial OCR | Incomplete evidence remains unknown; no guessed ownership | test_account_scan/account_bootstrap/card_scan |
| PB-004 | Select requested owned deck with similar names or changed geometry | Battle Rules confirms exact deck before battle; mismatch stops | test_owned_selector/requested_owned_deck |
| PB-005 | Request recipe containing unowned card or insufficient copies | Reject recipe; no craft/purchase/resource spend | test_deck_recipe/managed_deck |
| PB-006 | Launch one autonomous job; retry same command or concurrent claim | Single owner/claim; no duplicate battle attempts | test_autonomous/queue_worker/scheduler |
| PB-007 | Observe victory/loss/tie then return through recommendation and rules | Correct result once; return to list without timeout loop | test_result_lifecycle/executor |
| PB-008 | Lose ADB during battle and reconnect | Needs-attention persists; reconcile evidence before replay | test_device/managed_job; manual disposable device |
| PB-009 | Restart after persisted attempt before result commit | Interrupted state remains inspectable; no false win or replay | test_storage/managed_job |
| PB-010 | Encounter unknown screen, dialog or purchase offer | No guessed tap or spend; stop with bounded diagnostic evidence | test_executor/discovery_navigation |
| PB-011 | Choose rental versus owned strategy under safety policy | Only allowed existing owned strategy selected | test_rental_selector/strategy |
| PB-012 | Run mobile UI while automation status changes | Controls remain readable and job status accurate | rendered HTML; manual desktop/mobile browser |
| PB-013 | Inspect exported diagnostics/source release archive | No account database, screenshot, device serial or credentials exposed | Manual packaging review; synthetic fixtures only |
| PB-014 | Database integrity and progress reconciliation on copied fixture | No duplicated missions/wins; transactions retain stable records | test_storage/recommendation_backfill |
| PB-015 | Clean shutdown of isolated worker/API | Claims released or recoverable; unrelated runtime untouched | test_queue_worker; manual isolated process |

## Deferred acceptance and next checkpoint

Run mapped manual flows using synthetic data and isolated profiles; record actual device/runtime versions and outcome per ID. Never replace a physical/account gate with a unit count. Release-eligible changes require built/validated artifacts and GitHub release coordination; documentation-only baseline creates no package release. Next: finish portfolio baseline, inspect vision-defined gaps and execute a concrete milestone with impacted checks.

## Dedicated worker checkpoint — 2026-09-22

Start revision remains ae11413a1ef396a916fd1b2b9e0c810d1f9a8aae. Dedicated worker inherited this untracked ledger; preserved it. Read parent AGENTS.md, README, autonomous vision and private journal. Verified same-day baseline raw log timestamp/content and unchanged tracked source; reused 108-test/build/render/lint baseline.

Milestone 1: comprehensive [QA registry](QA_CASES.md), PB-001–042, with stable expected outcomes, priority, happy/error/recovery/privacy/platform mappings and explicit unrun manual gates.

Milestone 2: reproduced three managed startup failures (duplicate reservation, spawn failure stuck starting, abandoned reservation not recovered). Added lifecycle serialization, launcher reservation identity, spawn failure terminal state, and runner self-recorded PID. Targeted tests pass: 10 tests including two concurrent synthetic controllers, nonzero exit, stale update protection, recovery idempotence and bounded logs. No device, account, or retained runtime accessed. Root inbox explicitly assigned this worker release ownership; prepare v0.1.1 artifacts after further validation.

Next: isolated API safety/HTTP tests, final suite, source archive privacy/build review, version bump and coordinated publication. Physical tests listed in QA registry remain deferred for lack of authorized disposable device/account session.

Milestone 3: added isolated ASGI HTTP coverage without sockets, ADB or real storage. Preflight limits/scan gates and screenshot 404/503/no-store pass. Eight new P0 regression cases reproduced foreign Origin and malformed/nonlocal Host mutations; request middleware now rejects before handlers, while IPv4/IPv6/localhost and allowlisted dashboard origins work. Added duplicate/missing header tests. Package remains experimental; local process authentication is not claimed.

## Final candidate validation — 2026-09-22

`python3 <portfolio>/resource-run.py -- npm test`: production dashboard build, one rendered-HTML test and **141 Python tests passed**. `npm run lint` and `git diff --check` passed. Raw suite log: `/tmp/pbot-worker-final-suite.log`. Version 0.1.1 aligned in npm manifests, Python metadata/lock, API and README; changelog includes previously unreleased safe-deck fixes. Showcase worker confirmed no pinned version/download link needs changing.

Final candidate acceptance still deferred: physical USB disconnect/reconnect/RSA, exact deck-selection/read-back and managed-slot behavior, pause/resume and awake-setting restoration (PB-004/008/029/033–036); desktop/mobile keyboard/focus and actual browser origin flows (PB-012/031/038/041); long-running stop/process-tree acceptance (PB-025). Reasons: no coordinated disposable device/account or live browser/session authorization used. Isolated tests are not evidence those passed. All account gameplay remains untouched.
