# Agent-assisted porting

pbot is intentionally released as a working personal automation system, not a compatibility promise. This guide is the handoff contract for a coding agent adapting it to another user's Mac, Android device, screen layout, collection, or Pocket version.

## Reference contract

The verified setup is Apple Silicon macOS, Apple Vision OCR, a Samsung Android phone over authorized USB ADB, and one existing account. The current first-win workflow is deterministic and does not require an LLM. A port is successful when pbot can observe the new setup, fail closed on uncertainty, complete the read-only scans, and run one guarded battle without weakening the safety invariants.

## Start here

From a clean clone:

```bash
uv sync --frozen
npm ci
cp .env.example .env.local
uv run pbot doctor
npm run lint
npm test
```

Then connect and authorize exactly one Android device, start `npm run dev`, complete secure unlock/login manually, and use **Scan account** before any autonomous run. Keep all captured evidence under `var/`; it is private and ignored.

## Architecture map

| Area | Main locations | Responsibility |
| --- | --- | --- |
| Dashboard and API | `app/`, `worker/`, `scripts/dev.mjs` | Setup, progress, run control, local event stream |
| Configuration and device bridge | `src/pbot/config.py`, `src/pbot/device.py` | ADB discovery, serial selection, screenshots, guarded input |
| Persistence and orchestration | `src/pbot/storage.py`, `src/pbot/autonomous.py`, `src/pbot/executor.py` | Durable checkpoints, policies, classification, recovery |
| Step-Up discovery and routing | `scripts/discover_step_up.py`, `scripts/run_first_pass.py` | OCR, normalized coordinates, battle/deck selection |
| Deck knowledge | `src/pbot/deck_recipe.py`, `src/pbot/strategy.py`, `resources/deck-qr/` | Stable recipes, substitutions, owned-counter selection |
| Replay and regression tests | `tests/`, `tests_python/` | Rendered dashboard and deterministic harness behavior |
| Private runtime evidence | `var/` | SQLite state, frames, logs, calibration, account profile |

## Safety invariants

An adaptation must preserve these rules:

- no purchasing, crafting, currency use, pack points, or resource spending;
- no rental decks unless a future user explicitly changes policy;
- no credentials, secure-lock bypass, memory inspection, traffic interception, or process injection;
- verify the intended battle and selected deck from visible UI before committing an action;
- treat ambiguous OCR, ownership, coordinates, or state as `needs_attention` rather than guessing;
- keep the API local and all account/device evidence out of Git;
- make deck construction idempotent and restrict edits to an expected pbot-managed slot;
- validate every optional model proposal with deterministic policy and ownership checks.

## Evidence-first adaptation workflow

1. Reproduce one unsupported state with spending lock enabled and autonomous execution stopped.
2. Capture the smallest useful frame or OCR output under `var/`.
3. Identify whether the failure is device discovery, coordinate normalization, OCR, classification, routing, deck geometry, or strategy knowledge.
4. Change the narrowest seam and add a synthetic or carefully sanitized regression fixture. Do not commit a full private screenshot when a crop, OCR transcript, or generated fixture is sufficient.
5. Run the focused test, then `npm run lint` and `npm test`.
6. Perform a read-only scan on the device. For action changes, manually observe the first guarded attempt and confirm its visible read-back.

Coordinates are reference observations, not authority. Prefer normalized geometry and OCR anchors; use absolute values only where the game surface is known to be fixed, and bound them with screen classification and post-action verification.

## Common porting seams

### ADB and device behavior

Use `uv run pbot doctor` first. If ADB is not in Android Studio's normal macOS location, set `PBOT_ADB`. If multiple devices are attached, set `PBOT_ADB_SERIAL`. Adapt wake/unlock behavior in the device layer without attempting to bypass a secure keyguard.

### Resolution and navigation

Bottom navigation, expansion tabs, battle rows, and owned-deck selectors are based on observed geometry plus OCR anchors. Update normalization and anchor detection before adding device-specific tap constants. Require a recognized destination screen after each route.

### OCR and classifiers

Apple Vision is the reference provider. Keep provider output behind the existing observation/classification boundary. New OCR backends should return comparable text/box data and be covered by replay tests. Never let an OCR string alone authorize a spending or deck mutation action.

### Account and deck knowledge

Account scans are authoritative for usable numbered decks and recipe-card quantities. Add new recipes as stable card identities with exact quantities, energy, provenance, and explicit substitutions. Missing or ambiguous cards must remain unavailable rather than being optimistically inferred.

### Strategy knowledge

The autonomous loop ranks existing verified wins, repository knowledge, matching owned decks, and constructible recipes. Add a reusable strategy record when evidence supports it; do not hard-code one account's slot number or assume a deck exists without scan evidence.

## Optional models

An LLM or auxiliary vision model is not required today. If a port adds one, document the provider, model, whether data leaves the machine, its JSON contract, retry/timeout behavior, and deterministic validation. Models may propose interpretation, research, substitution, or planning; they must not tap directly, mutate SQLite, or override ownership and spending policy.

## Before enabling an autonomous run

- `pbot doctor`, lint, build, rendered HTML smoke test, and Python tests pass.
- The correct device is selected and stays awake while powered.
- Login is complete and the game is on a recognized home or battle screen.
- Account and recipe-card scans completed without ambiguity being counted as ownership.
- The no-spend lock is visible and enabled.
- A single supervised battle confirms navigation, deck read-back, auto-mode activation, outcome capture, and checkpoint recovery.

If any item is uncertain, stop and retain evidence. That is a valid porting result; guessing is not.
