# pbot risk-based QA registry

Updated 2026-09-22. Stable PB IDs are never reused. P0 = account/privacy/concurrency safety; P1 = durable correctness/recovery; P2 = presentation/portability. Existing PB-001–015 remain compatibility IDs from the baseline ledger. File mappings describe partial coverage, not a claim that a physical procedure passed. All device, account, browser and release acceptance below is NOT RUN unless a dated receipt explicitly records it.

Run synthetic Python coverage with `uv run pytest`; dashboard smoke/build with `npm test`; static checks with `npm run lint`. Never point fixtures at ignored runtime storage, import the global API app with production environment, or run ADB during this suite. macOS is the reference platform; Linux/Windows and emulators are not certified.

## Existing flow cases

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


## Detailed risk and acceptance cases

| ID | Priority / class | Procedure | Expected result | Automated mapping / manual gate |
|---|---|---|---|---|
| PB-016 | P0 privacy/error | Configure wildcard, LAN, public or empty API host | Settings reject before serving | tests_python/test_config.py |
| PB-017 | P0 privacy/happy | Configure IPv4, IPv6 or localhost loopback | Settings accept only local exposure | tests_python/test_config.py; browser gate for actual listener |
| PB-018 | P0 concurrency/error | Second start while first start has no worker PID | Second start rejected; first ID and command unchanged | New regression in test_managed_job.py |
| PB-019 | P1 recovery/error | Worker process creation fails | Failed state durably recorded; subsequent valid start possible | New regression in test_managed_job.py |
| PB-020 | P1 recovery | Starting reservation owner disappears before spawn | Status marks failed and recovers claims; new start possible | New regression in test_managed_job.py |
| PB-021 | P0 concurrency | Runner and parent update startup state in opposite orders | Canonical PID retained, terminal completion never overwritten | test_managed_job.py detached synthetic process; concurrency review |
| PB-022 | P1 happy/error | Detached synthetic command exits zero/nonzero | Exact exit status and log persisted; failure never called success | test_managed_job.py |
| PB-023 | P1 error | Old worker attempts update after replacement | Stale job ID rejected without modifying current job | test_managed_job.py |
| PB-024 | P1 recovery | Query vanished running process twice | One recovery transition/event, no fabricated win | test_managed_job.py; test_storage.py |
| PB-025 | P0 recovery | Stop isolated active process group | Only owned group terminated; interrupted claims recoverable | Manual isolated process acceptance; never existing session |
| PB-026 | P1 happy | No job, missing log, excessive requested log length | Empty result or bounded tail, no crash | test_managed_job.py |
| PB-027 | P0 error | Partial deck/card scan fails mid-traversal | No partial collection published as ready | test_account_scan.py, test_card_scan.py, test_account_bootstrap.py |
| PB-028 | P0 error | Wrong variant, missing card or insufficient copies | Constructor rejects; no spend or substitution outside recipe | test_deck_recipe.py, test_card_inventory.py, test_managed_deck.py |
| PB-029 | P0 recovery | Managed deck slot already exists, differs or is not next free slot | Exact verified reuse or handoff; unrelated decks preserved | test_managed_deck_android.py; disposable account gate |
| PB-030 | P1 happy/error | Exhaust counters, rank proven fallbacks, repeat same battle | Proven owned untried deck chosen; budget bounds retries | test_strategy.py, test_autonomous.py |
| PB-031 | P1 error | All safe strategies exhausted | Durable needs_attention with specific reason; no retry loop | test_autonomous.py; manual dashboard status gate |
| PB-032 | P1 recovery | Replay retained terminal battle outcome | Reconcile once without replaying battle or double counting | test_result_lifecycle.py, test_storage.py |
| PB-033 | P1 recovery | Pause/handoff/resume during queue processing | Safe checkpoint honored; no action during human control | test_executor.py, test_queue_worker.py; physical gate |
| PB-034 | P1 platform/error | Missing ADB, unauthorized or multiple devices | Diagnostic handoff; no implicit wrong-device selection | test_device.py; manual USB/RSA gate |
| PB-035 | P1 platform/recovery | Enable then restore awake settings | Exact original settings restored; secure unlock stays human | test_device_awake.py; physical setting acceptance |
| PB-036 | P1 platform/error | OCR/layout or game-version changes | Unknown state stops with evidence; no coordinate guessing | test_discovery_navigation.py, test_requested_owned_deck.py; physical gate |
| PB-037 | P0 privacy | Clean source archive and release artifact inspection | No var, journal, device screenshots, credentials or serials | Manual artifact manifest audit before release |
| PB-038 | P0 privacy/error | External browser origin/host accesses control API | Review request rejection independently of CORS visibility | tests_python/test_api.py rejects external/opaque origins, malformed/nonlocal/missing/duplicate Host and duplicate Origin; live browser gate remains |
| PB-039 | P1 error | Invalid run difficulty/action/retry limits or missing scan | API rejects and launches no job | tests_python/test_api.py (isolated ASGI requests) |
| PB-040 | P1 recovery | Missing screenshot or capture failure | 404/503; screenshots served no-store | tests_python/test_api.py (synthetic screenshot/errors) |
| PB-041 | P2 platform | Desktop/mobile viewport, keyboard navigation, reduced motion | Controls readable, focus visible, status understandable | tests/rendered-html.test.mjs partial only; manual browser gate |
| PB-042 | P1 platform | Clean release checkout, frozen dependencies and offline fixtures | Build/render/Python/lint pass without personal runtime | Baseline commands; clean archive rerun before package release |

## Additional review regressions

| ID | Priority / class | Procedure | Expected result | Mapping |
|---|---|---|---|---|
| PB-043 | P0 concurrency/recovery | PID publication fails after spawning; cleanup succeeds or fails | New session killed/reaped before reservation released, or active ownership retained; no overlapping worker | test_pid_publication_failure_cannot_leave_replaceable_live_worker |
| PB-044 | P0 privacy/recovery | Stored worker PID belongs to unrelated process | Exact random job token required; unrelated group never signalled | test_reused_pid_is_never_signalled; test_runner_identity_requires_exact_launch_token |
| PB-045 | P1 recovery | Runner completes while status probes process | State lock preserves recorded terminal outcome | test_detached_job_records_completion_and_log; test_nonzero_worker_exit_is_failure |

## Dependency maintenance

| ID | Priority / class | Procedure | Expected result | Mapping |
|---|---|---|---|---|
| PB-046 | P1 privacy/platform | Audit complete frozen npm/Python dependency graph and rebuild with patched versions | Known advisories resolved without weakening platform support; frozen install/build/test still pass | npm audit --json; uv export --frozen --no-hashes --no-emit-project then pip-audit --no-deps --disable-pip; npm test |

## Evidence and unresolved coverage

Baseline: 2026-09-22 at ae11413a1ef396a916fd1b2b9e0c810d1f9a8aae, 108 Python tests and one rendered HTML test plus build/lint passed (verified raw log `/tmp/dionlabs-burn-pbot.log`). That receipt is suite-level; it does not certify every expected outcome above. Specific newly added cases must record their test names/counts in the burn ledger. Full multi-minute suites use the portfolio resource wrapper.

Post-burn acceptance: PB-004/008/029/033–036 need D-coordinated disposable device/account access; PB-012/031/041 need isolated browser interaction; PB-025 needs coordinated isolated process lifecycle acceptance; PB-037/042 need exact final artifact review; PB-038 needs isolated real-browser acceptance; PB-039–040 now have isolated HTTP coverage. None authorizes spending, crafting, gameplay changes on D's account, runtime cleanup, or emulator/session restarts.
