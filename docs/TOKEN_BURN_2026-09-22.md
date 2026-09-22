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

Independent review checkpoint: initial exact source archive installed/built/rendered/linted and passed 141 tests, but publication was held when root reviewer reproduced a post-Popen PID-write failure leaving a live process behind. Correction kills/reaps only the just-created process group before releasing ownership; unconfirmed cleanup retains active PID/reservation. Two synthetic regressions verify both branches (38 API/job tests passed). The initial archive is superseded and must not be published. Awaiting coordinator rereview while validating corrected source.

Corrected candidate: full resource-wrapped `npm test` now passes **149 Python tests**, one rendered HTML test and production build; lint and diff whitespace checks pass. PB-043–045 cover post-spawn cleanup, reused-PID signal safety and terminal-state race. Exact random runner job token is checked before stop signals; local-process authentication is not claimed. Root rereview requested; release remains held until corrected artifact is validated and hold cleared.

## Published release and final resume state — 2026-09-22

- Root independent rereview cleared the startup cleanup blocker. Final code commits: c4fa66f and **56253f38d0f057a0e10fb5ddaf0be12d2014f724**.
- Published experimental [v0.1.1](https://github.com/dion-labs/pbot/releases/tag/v0.1.1), preserving experimental prerelease status. Assets: `pbot-0.1.1.tar.gz` and `SHA256SUMS`; README points to this release. Showcase worker received actual verified URLs for local-only alignment.
- Corrected exact source archive: clean `npm ci --ignore-scripts`, `uv sync --frozen`, `npm run lint`, and resource-wrapped `npm test` passed: **149 Python tests**, one rendered-HTML test, production build. Log: `/tmp/pbot-release-reviewed-validation.log`. Artifact has 114 manifest entries and excludes runtime/journal/env/symlinks; limited credential-signature scan passed.
- Downloaded published assets and verified bytes match the validated archive. SHA-256: `26587041ace1b0f3ba824495daad84e794230bf88d347a921e6b323c2b3f8597`.
- GitHub CI for the exact code head passed: https://github.com/dion-labs/pbot/actions/runs/35697127344 . A duplicate tag-triggered CI run was still in progress at this checkpoint; no different code is involved.
- Release creation initially rejected a short target hash; retry with the full commit hash succeeded. No partial release or old artifact was published.

Ready report: 45 stable QA cases; managed start/stop/status serialization and startup reservation/recovery; failed-spawn process ownership retained until cleanup; exact runner-token checks for saved PIDs; atomic terminal observation; local API Host/Origin rejection; 41 added Python test cases over the 108-test baseline; released source/checksums and download reference.

Remaining acceptance is exactly the physical/browser/process-tree list above, not an automated pass. No user runtime data, device, emulator, game account, running app, website deployment, or excluded integration was changed. Remaining vision work (new safe strategies/recipes, visual-state/device compatibility and mission evidence) needs authorized disposable account/device observations and cannot be truthfully validated from these synthetic fixtures. Resume from this ledger and QA_CASES.md, read coordinator inbox and current Git status first; use the published release as the baseline and keep manual gates explicit.

## Successive milestone — dependency alerts and v0.1.2 preparation

Final v0.1.1 push exposed four GitHub dependency alerts. Queried exact manifests/advisories: pytest <9.0.3, sharp <0.35.4, baseline-browser-mapping <2.11.0, Browserslist <=4.28.6. Full npm audit additionally found fflate <0.7.5. Updated pytest to 9.1.1; pinned @cloudflare/vite-plugin 1.57.1 and wrangler 4.136.1 to obtain sharp 0.35.4; resolved Browserslist 4.29.0, baseline-browser-mapping 2.11.25 and fflate 0.7.5. No forced overrides or application-policy changes.

`npm audit --json`: zero known vulnerabilities. `uv export --frozen --no-hashes --no-emit-project` plus `uvx pip-audit -r <export> --no-deps --disable-pip --format json`: no known vulnerabilities (audits are time-sensitive). Resource-wrapped full build/render/149 Python suite passed with patched graph. Logs: `/tmp/pbot-dependency-suite.log`, `/tmp/pbot-npm-audit.json`, `/tmp/pbot-python-audit.json`. Added PB-046 and preparing v0.1.2 exact artifact; v0.1.1 remains published and unchanged.

## v0.1.2 published and metadata follow-up

Published v0.1.2 at code 94e5daa66748a37b18f44a2883eb41f39979941c. Clean archive lint/build/render/149 tests and npm audit passed; Python audit remained clean. Downloaded source SHA256 `5cc2503d2437e601eae1626f18d4297d30eb307e918ebfecf963972b5efa874d` matches validated bytes. Exact-head GitHub CI 35697596692 passed, and GitHub open Dependabot alerts are now empty. Site worker notified.

Final consistency check caught preexisting `pbot.__version__ = "0.1.0"` despite current package/API metadata. v0.1.3 will derive Python and API reporting from installed distribution metadata (uninstalled source reports `0+unknown`) so the values cannot drift independently. Existing published releases remain unchanged; this is a version-reporting correction, no gameplay/control-policy change.

## Final burn handoff — v0.1.3, 2026-09-22

Final experimental release: https://github.com/dion-labs/pbot/releases/tag/v0.1.3 ; exact code head `e4fd2b2ba1faa0b5deccbdecce45c0efaa9d56bb`. Source and SHA256SUMS uploaded and downloaded again; validated archive SHA256 `0659d549b98e4694c2146e1d336e5e950898ea1a7dd5e845276a289388a207f2` matches published bytes. Earlier releases remain immutable.

Exact clean-source validation passed: frozen npm/uv installs, lint, production build, rendered HTML, **149 Python tests**, npm audit (zero known vulnerabilities), and installed package version assertion. Independent isolated check verified Python package, installed distribution, pyproject, npm and API all report 0.1.3. Python frozen dependency audit reports no known vulnerabilities. GitHub Dependabot open alert count is **0**; exact-head CI including secrets/verify passed: https://github.com/dion-labs/pbot/actions/runs/35697908420 . Local raw log: `/tmp/pbot-release-0.1.3-validation.log`.

Final scope: **46 stable QA IDs**, 41 additional Python cases over baseline, reviewed worker lifecycle/recovery and process ownership corrections, API Host/Origin enforcement, patched build/test dependencies, consistent installed version reporting, published source/checksums and current download link. Site worker received final verified URLs for local alignment only. Four worker-created extracted install/test trees were removed after validation; source archives, checksum files, downloads and logs retained.

Exact unrun post-burn acceptance:

1. PB-004/029: on a coordinated disposable account/device, select the intended owned deck, verify Battle Rules read-back, and confirm managed slot changes preserve unrelated decks.
2. PB-008/034/036: USB loss/reconnect, RSA authorization, unsupported layout/OCR and game-version handoffs; prove no wrong-device or guessed action.
3. PB-033/035: physical pause/handoff/resume and awake-setting restore; verify secure unlock remains human-controlled.
4. PB-012/031/038/041: isolated live desktop/mobile browser, keyboard/focus/status presentation, and real-browser Origin rejection with unchanged state.
5. PB-025: coordinated long-running isolated process-tree stop/recovery acceptance; synthetic PID/cleanup tests do not certify every OS process-tree race.

These require coordinated manual/device/browser sessions and remain explicitly unrun. No real account gameplay/spending/crafting, live session/emulator restart, website deployment, personal runtime cleanup or excluded integration work occurred. Further recipe/strategy/visual-state vision work needs new permitted observations; do not invent recipes or resume D's account to generate evidence. Resume from this ledger, QA_CASES.md, journal, inbox and current Git state.

## PB-025 real OS boundary continuation — 2026-09-22

Explicit coordinated authorization permits actual disposable inert subprocess trees only. Resumed clean at c694fdac1b13241f643c112df2e5c12524af753d; v0.1.3 preserved. Added opt-in scripts/check_process_lifecycle.py with fresh mkdtemp project/data/database/logs, minimal explicit environment, UUID fixture tokens, PID/PGID/creation identities, bounded inert children and ownership-verified cleanup. No production env/runtime, network, ADB, account or device used.

First real run: `python3 <portfolio>/resource-run.py -- uv run python scripts/check_process_lifecycle.py --run`, log `/tmp/pbot-process-baseline.log`; full evidence `/var/folders/vq/rkb95_8n02d4c91kltpxr1r80000gp/T/pbot-process-acceptance-h8xa51fa/report.json` includes source hashes, owned identities and per-case outcomes. Five of seven cases passed: separate-process simultaneous launch, graceful stop, controller interruption plus restart, unrelated live fixture identity rejection, natural completion plus restart. Two reproduced product bugs: stubborn grandchild survives a reported stopped job; runner-only interruption leaves child/grandchild alive while state is failed/recovered. All seven fixtures subsequently cleaned up with verified-empty groups; no unowned process was signalled. Next: fix process-group ownership/termination beyond runner liveness, then rerun actual OS acceptance and unit suite before one coherent follow-up release.

### PB-025 continued checkpoints and coherent v0.1.4 candidate

- Corrected original seven real cases passed with every group empty: `.../pbot-process-acceptance-2cow4xqc/report.json`.
- Repeated run `.../pbot-process-acceptance-5jrc_yu9/report.json` reproduced cold SQLite WAL initialization contention between two controller processes. Controller initialization now uses the lifecycle lock. That run also exposed a harness-only transient macOS argv omission during exit; snapshots now retry, never granting signal authority from missing identity.
- A real SQLite writer barrier reproduced a candidate terminal-publication regression (`.../pbot-process-acceptance-vlpnx5e2/report.json`): success was overwritten while only the finishing runner remained. Corrected to retain terminal results in that window while still detecting actual descendants.
- Eleven real cases repeated three times passed **33/33**, all groups verified empty: `.../pbot-process-acceptance-wjely9kx/report.json`, log `/tmp/pbot-process-acceptance-final.log`. Added direct-start rejection after runner loss and pre-PID reservation interruption; **6/6** targeted repeats passed: `.../pbot-process-acceptance-9e0z2jyg/report.json`, log `/tmp/pbot-process-startup-followup.log`.
- Independent review found failed/empty argv inspection was incorrectly positive evidence of PID reuse. `runner_identity` now distinguishes owned/unrelated/uncertain, including placeholder argv and empty global process listings; fault-injected regressions preserve reservation and reject signals/restart when uncertain.
- Actual directory chmod denial after child/grandchild startup reproduced unrecovered claims on failed PID publication: errno13, `.../pbot-process-acceptance-4eps5rr2/report.json`. Corrected path verifies complete group termination, retains PID ownership on unconfirmed cleanup and recovers claims only after confirmed termination. Three real repeats passed with empty groups: `.../pbot-process-acceptance-l8_hc3v8/report.json`, log `/tmp/pbot-process-publication-green.log`.
- All abbreviated evidence directories above are beneath `/var/folders/vq/rkb95_8n02d4c91kltpxr1r80000gp/T/`. Reports contain source hashes, fixture tokens, PID/PGID/start identities, actual outcomes and cleanup receipts. Only generated inert fixture groups were signalled; no production env/data/log, ADB/network or device/account work occurred.

Safe successive preflight milestone: five isolated API regressions and two CLI regressions reproduced accepting ready scans from another/unknown device before launch/adapter construction. Raw red logs `/tmp/pbot-profile-red.log` and `/tmp/pbot-profile-cli-red.log`. Shared guard now binds deck/card scan evidence to the selected device; CLI default pins the scanned serial; mismatches preserve profiles and hand off. Matching-device positive cases pass. This does not detect account switching on the same hardware; that still requires manual rescanning. Added PB-047; all 62 targeted managed-job/API/CLI tests passed.

Current freeze: version metadata/README prepared for **v0.1.4**, prior releases immutable. Final opt-in harness has PB-025.01–13, including real permission-error timing (not mocked process/signal/liveness results). Full matrix x3 is running at `/tmp/pbot-process-v014-final.log`; full resource-wrapped `npm test` queued/running at `/tmp/pbot-v014-suite.log`. Publication remains held for root rereview of identity uncertainty and final candidate. Next: inspect final results, rerun only affected failures if any, commit reviewed coherent batch, clean-source archive validate, publish1.4 only after hold clears, verify downloaded checksum and notify showcase worker.

Root rereview cleared the scoped v0.1.4 publication hold:62targeted tests and independent terminal/identity/cleanup checks passed; shared API/CLI binding reviewed. Reviewed managed_job.py SHA256 `50d38bf553b40ef02f63638c1ed5ffab608e3702d359860be538eceabc4e9122`. Remaining gates are final actual OS run, full suite, exact clean artifact and publication verification; no physical acceptance implied.

Final frozen candidate verification: **39/39 actual OS cases passed**, every cleanup `verified-empty`, evidence `/var/folders/vq/rkb95_8n02d4c91kltpxr1r80000gp/T/pbot-process-acceptance-9dybsc2u/report.json`. Full build/render/**167 Python tests** and lint passed, logs `/tmp/pbot-v014-suite.log` and `/tmp/pbot-process-v014-final.log`. Root review hold is cleared. Next gate is exact committed source archive validation and publication.
