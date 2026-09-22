# Changelog

## 0.1.5 — 2026-09-22

- Show actionable command errors and allow retry without unhandled browser exceptions.
- Disable conflicting pending controls and disconnected starts while preserving Stop for active jobs; retain keyboard focus after completion without overriding user navigation.
- Ignore late status responses that would overwrite a newer confirmed command state.
- Wrap narrow-screen controls and long activity messages, and honor reduced-motion preferences for the spending-policy tooltip.
- Add opt-in actual Chrome/HTTP acceptance with temporary data, fake device/controller dispatch, blocked external browser traffic, real Origin/Host rejection checks and identity-verified fixture cleanup.

## 0.1.4 — 2026-09-22

- Stop and recover the entire owned process group, including descendants surviving a runner exit; retain reservations and claims when identity or termination is uncertain.
- Serialize fresh controller database initialization and preserve terminal results during the runner's final bookkeeping window.
- Recover interrupted claims only after confirmed cleanup when PID publication fails after a worker has started.
- Add an opt-in real-process acceptance harness with disposable projects, inert child/grandchild fixtures, interruption/restart cases and verified owned-process cleanup.
- Reject missing or mismatched device bindings in deck/card preflight before API launch or CLI adapter construction; CLI defaults stay pinned to the scanned device.

## 0.1.3 — 2026-09-22

- Derive Python package and API version reporting from installed distribution metadata, replacing a stale 0.1.0 constant and preventing future drift between those reports.

## 0.1.2 — 2026-09-22

- Update the development/build dependency graph to patched pytest, sharp, Browserslist, baseline-browser-mapping and fflate releases. Cloudflare build tooling moves to compatible pinned versions that include patched sharp.
- Frozen Python and npm dependency audits report no known vulnerabilities at validation time; build, rendered HTML and all 149 Python tests pass.

## 0.1.1 — 2026-09-22

- Serialize detached start/status/stop operations, reserve launches before a worker PID exists, and recover failed or abandoned startup without allowing duplicate jobs.
- Verify the detached runner launch token before signalling a saved PID, and retain ownership if failed-start cleanup cannot be confirmed.
- Reject untrusted browser origins and non-loopback Host headers before local API actions, including bodyless requests.
- Add synthetic concurrency, startup recovery, HTTP preflight and screenshot privacy coverage; publish a stable risk-based QA registry.

- Reuse durable account-local win evidence to rank untried owned decks after every weakness-matched counter has failed, while preserving the one-attempt-per-deck and no-spend guards.
- Ignore both runtime directories and local runtime symlinks so an operational checkout can safely reference retained evidence.
- Tap a visible owned-deck name inside the actionable card body instead of its decorative slot-number header; Battle Rules read-back continues to block mismatches.

## 0.1.0 — 2026-08-30

First experimental public release.

- Local Android observation and control through screenshots, OCR, and guarded ADB input.
- Durable SQLite checkpoints, recoverable autonomous jobs, and a localhost control room.
- Owned-deck and no-spend safety policies with fail-closed state verification.
- Account, deck, card-inventory, discovery, strategy, and recovery test coverage.
- Agent-assisted porting guide for adapting the reference setup without weakening its guards.
