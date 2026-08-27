# One-button autonomous operation

## Product objective

The released project is a verified Dionlabs personal workbench, not a universal compatibility promise. On its reference setup, a user should be able to connect and authorize the known Android device, complete login when asked, and press **Run pbot**. From that point pbot should discover the account's Step-Up state, complete first wins, resolve losses with owned-card decks, and stop only when the objective is complete or a genuine human handoff is required.

Clone-to-run operation on arbitrary hardware and complete mission planning remain aspirational phases. Other users should expect to adapt device, OCR, layout, and collection knowledge with the [agent porting guide](AGENT_PORTING.md).

The default safety policy remains:

- owned cards and owned decks only;
- no purchases, crafting, currency, pack points, or resource spending;
- no rental decks unless a user explicitly changes policy;
- screen/OCR observation and human-like ADB interaction only;
- secure unlock, login, app updates, and terms prompts are human handoffs.

## What the journal taught us

| Process | Current automation | Historical agent work to remove |
| --- | --- | --- |
| Device setup | ADB doctor, authorization diagnostics, reversible awake policy | Choosing emulator versus phone and explaining RSA/login handoffs |
| Navigation | Deterministic routing, modal recovery, foreground relaunch, guarded screen checks | Adding a new classifier/recovery whenever an unseen game screen appeared |
| Discovery | Incremental frontier scan and canonical import | Deciding when to rescan and reconciling some OCR aliases |
| First pass | Restart-safe queues, auto mode, results, rewards, unlocks | Starting successive difficulty runs and interpreting queue exhaustion |
| Loss evidence | Screenshot retained; loss is deferred | Reading recommendation type/deck from the screenshot and requeuing a counter |
| Deck choice | Recommended owned deck, named owned deck, deterministic fallback | Remembering which existing deck maps to a type or battle |
| Deck creation | Guarded recipe planning, QR import, ownership validation, declared substitutions, naming, and strict managed-slot read-back | Capturing complete new recipes and choosing substitutions not already encoded in repository knowledge |
| Recovery | Interrupted claims and attempts are durable; some phone-side win reconciliation exists | Deciding whether an interrupted battle really won and invoking reconciliation |
| Detached execution | Durable start/status/log/stop job controller | Polling foreground terminals and recognizing that a clean loss needs attention |
| Missions | Counts are tracked | Extracting mission text, selecting decks that cover conditions, and planning minimum retries |

The primary missing capability is not general phone control. It is a durable strategy/knowledge layer and an orchestrator that turns every terminal outcome into the next safe action.

A live example found during this design pass reinforces the rule: the game can end in `Tie`, not only victory/defeat. Deterministic outcome handling now recognizes and reconciles ties, while the future orchestrator must treat a tie as empirical strategy evidence and continue candidate resolution rather than reporting an OCR failure.

## Target architecture

```text
Dashboard / CLI
      |
      v
Autonomous run orchestrator  <---->  SQLite run/checkpoint state
      |
      +--> policy engine (owned only, no spend, retry limits)
      |
      +--> deterministic observer/router/executor --> Android device
      |
      +--> strategy resolver
             |
             +--> repository knowledge (recipes, battle rules, UI signatures)
             +--> local profile (owned cards/decks, outcomes, calibration)
             +--> optional LLM/vision/research provider
```

The orchestrator owns the lifecycle. Models may suggest a plan, but deterministic validators decide whether it is safe and executable.

## Durable state machine

```text
BOOTSTRAP
  -> NEEDS_LOGIN (human handoff when required)
  -> DISCOVER
  -> FIRST_PASS
  -> RESOLVE_DEFERRED
       -> SELECT_KNOWN_DECK
       -> BUILD_KNOWN_RECIPE
       -> RESEARCH_RECIPE
       -> RETRY_AUTO
  -> COMPLETE_FIRST_WINS
  -> EXTRACT_MISSIONS
  -> PLAN_MISSION_COVERAGE
  -> RUN_MISSIONS
  -> VERIFY_ACCOUNT_STATE
  -> COMPLETED

Any state -> RECOVER -> previous safe checkpoint
RECOVER exhausted -> NEEDS_ATTENTION
```

Every state transition must be stored before an external action. After a restart, pbot observes the phone, reconciles the stored checkpoint, and either resumes or enters `needs_attention` with evidence and one requested human action.

## The Run pbot experience

The dashboard's current **Run device check** is diagnostic, not the final run control. Replace it with a first-run wizard and a persistent **Run pbot** control.

First-run wizard:

1. Verify platform dependencies, ADB, OCR/vision provider, and the game package.
2. Select and authorize exactly one Android device.
3. Apply the reversible awake policy.
4. Ask the user to unlock/login only if the observed screen requires it.
5. Choose policies: owned-only, no-spend lock, managed deck slot(s), first-wins or all-missions objective, and retry budget.
6. Scan existing decks and enough of the owned collection/theme lists to validate recipes. Both the read-only numbered-deck scan and targeted shipped-recipe card preflight are implemented.
7. Store a local device/account profile under ignored runtime data.

Run control:

- `POST /api/runs` starts or resumes one durable autonomous run and returns its ID.
- The UI shows phase, current battle, selected strategy, last outcome, aggregate progress, and whether intervention is required.
- `Pause` checkpoints between safe actions; `Stop` terminates the process group and recovers the queue boundary.
- Terminal states are `completed`, `needs_attention`, `failed`, and `stopped`. A cleanly executed loss is never presented as generic success.
- The dashboard may notify locally when a run completes or requests attention. No model or agent needs to hold a terminal open.

## Knowledge model

### Repository knowledge (shareable)

Versioned files committed with pbot:

- canonical expansion/battle aliases and UI signatures;
- recommendation observations that are stable across accounts;
- deck recipes with stable card identity, variant/attack disambiguation, energy type, provenance, and game-data version;
- battle strategy candidates and aggregated anonymous/local test evidence;
- substitution rules and mission capability tags;
- safe recovery recipes for known UI states.

Example logical deck record:

```json
{
  "id": "elite-mega-lucario-ex",
  "display_name": "Elite Deck (Mega Lucario ex)",
  "energy_types": ["Fighting"],
  "cards": [
    {"card_id": "stable-id", "name": "Example", "variant": "attack-or-set-identity", "count": 2}
  ],
  "capabilities": ["fighting-knockout", "auto-battle"],
  "source": {"kind": "in_game_theme_list", "game_version": "..."}
}
```

`pbotfire`, `pbotfight`, and `pbotdark` are now fully captured 20-card
recipes with stable card IDs and shipped 2D pattern codes. `pbotdark` retains
the published Hoopa ex theme recipe and its auditable one-copy Galarian
Linoone substitution. Existing `vaporcuno`, `aeroape`, `zapdoS`, and `mewpoo`
are now discovered and energy-classified by the local account bootstrap, but
they still have no portable card-list recipe in repository knowledge.

The first portable construction recipe is now complete: the published
Mega Sharpedo ex / Milotic ex list and the account-safe `pbotwater-articuno`
adaptation. `scripts/build_managed_deck.py` proves the guarded constructor
contract. Existing slots are verified without mutation; absent slots may be
built only when they are the next free slot, and only recipe-declared
substitutions are permitted. The autonomous resolver now invokes this
constructor only after verified owned counters are exhausted and a complete
shipped recipe matches the game's named recommendation. The matcher now covers
Mega Sharpedo ex, Elite Mega Charizard Y ex, Elite Mega Lucario ex, and Hoopa
ex. It first searches for
an existing exactly named slot, otherwise uses only the next free slot, stores
`build_deck` checkpoints, and reports construction blockers as
`needs_attention`. Additional recipe capture now grows coverage without
changing the deterministic constructor.

### Local account profile (never committed)

Stored under `var/` or SQLite:

- device calibration and serial;
- owned card quantities and exact variants;
- owned deck slots, names, recipes, and last verification time;
- per-battle attempts, mission deltas, deck performance, and evidence paths;
- which repository recipes can be built exactly or with approved substitutions;
- run policies and retry budgets.

### Required database additions

- `run_objectives` and `run_checkpoints` for the autonomous state machine;
- `battle_recommendations` with type, named deck, OCR text, confidence, and evidence;
- `deck_recipes` and `deck_cards` for reusable structured recipes;
- `owned_decks` and `owned_cards` for account capabilities;
- `strategy_candidates` for battle/deck ranking, provenance, and status;
- `mission_requirements` for normalized task conditions and coverage tags;
- `planner_decisions` for optional model input/output, validation, and outcome.

Attempts remain the source of truth for empirical deck performance.

## Automatic loss resolution

On every loss:

1. Capture and parse the recommendation type and named theme deck into `battle_recommendations` instead of only retaining a screenshot.
2. Rank candidates in this order:
   - a locally verified auto-win for this exact battle;
   - a repository strategy with a recipe the account can build;
   - an existing owned deck matching the recommended type/capabilities;
   - a known recipe with deterministic owned-card substitutions;
   - an optional research-provider proposal.
3. Validate ownership and policy before selecting or editing a deck.
4. Build/update only a configured pbot-managed slot, then read the visible deck back to verify it.
5. Retry with a bounded per-strategy budget and store the result.
6. Promote winners and penalize losers so later users/runs reuse learned strategy instead of researching again.
7. Enter `needs_attention` only when all permitted candidates are exhausted or the UI cannot be safely classified.

This makes the work we did for Fire, Fighting, and Darkness reusable. A future account with enough matching cards can build those decks without an agent.

## Mission completion

After every first win:

1. OCR and normalize each incomplete mission, not only the completed/total counter.
2. Translate mission text into capability tags such as energy type, rarity, evolution stage, maximum points conceded, or turn constraints.
3. Score owned/known decks against each mission.
4. Solve a small set-cover problem to group compatible missions into the fewest likely attempts.
5. Prefer auto mode and update coverage after each result.
6. Use the optional battle planner only for missions that repeatedly fail in auto mode.

No manual battle intelligence is required for the autonomous first-win alpha. End-to-end battle planning belongs to the later all-missions fallback.

## Optional LLM and vision providers

LLM use must be explicit and replaceable. Supported policy should be `disabled`, `local_openai_compatible`, and later opt-in remote providers. A local server may host DeepSeek or another model; OCR/vision may remain Apple Vision on macOS or use a configured local vision endpoint.

The model receives structured observations plus only the minimum required screenshots. It returns JSON matching a strict schema, for example:

- `use_existing_deck`;
- `build_recipe`;
- `substitute_cards`;
- `retry_auto`;
- `request_new_observation`;
- `request_handoff`.

The model cannot tap, spend, craft, select rentals, or mutate SQLite directly. pbot validates the proposal against ownership, policy, confidence, current screen, and allowed actions. All prompts, provider/model identity, proposed decisions, validation failures, and outcomes are logged locally. Screenshots never leave the machine unless the user explicitly configures a remote provider.

LLM use is appropriate for:

- interpreting an unseen but non-sensitive UI state;
- converting recommendation/mission text into structured constraints;
- ranking substitutions when an exact recipe is unavailable;
- proposing a battle plan after auto strategies are exhausted.

It should not replace deterministic navigation, result recognition, queue accounting, or safety checks.

## Implementation sequence

### Phase 1 — Autonomous first-win loop

1. Persist structured loss recommendations.
2. Add recipe/owned-deck schemas and capture the seven currently known owned decks.
3. Implement deterministic strategy ranking and pbot-managed deck-slot construction/verification. (Complete for four named recommendation families.)
4. Add a durable orchestrator that alternates queued first passes and deferred resolution until exhausted.
5. Add `needs_attention` semantics and the real **Run pbot** API/dashboard control.
6. Convert current manual reconciliation cases into an automatic recovery audit.

Definition of done: from an already logged-in account, one run control completes all first wins it can satisfy from shipped knowledge and owned cards, learns from results, and asks for help only with evidence when no permitted plan remains.

### Phase 2 — Clone-to-run onboarding

1. Dependency/device/login wizard and clean-clone validation.
2. Account deck/card capability scan and managed-slot setup. (Deck bootstrap and targeted recipe-card capability preflight implemented.)
3. Local notification and clear resume behavior across disconnects/reboots.
4. Replay fixtures for every supported visual state.

Definition of done: a second user/device can follow documentation and reach the autonomous first-win loop without a project author editing code or SQLite.

### Phase 3 — All missions

1. Mission text extraction and normalization.
2. Capability tagging and set-cover retry planner.
3. Mission-oriented deck knowledge and empirical scoring.
4. Optional battle-planner fallback for auto-resistant missions.

Definition of done: pbot verifies all available Step-Up first-win rewards and missions complete, or reports a precise unsatisfied constraint such as missing owned cards.

### Phase 4 — Learning/research ecosystem

1. Versioned import/export for anonymized deck recipes and battle outcomes.
2. Optional local LLM and vision adapters with evaluations.
3. Optional web/community research connectors with provenance and review.
4. Game-version compatibility checks and knowledge migrations.

## Immediate next engineering slice

The smallest slice that removes real agent work is:

1. add `battle_recommendations`, `deck_recipes`, and `owned_decks` persistence;
2. parse loss recommendation type/name during the existing result lifecycle;
3. seed structured recipes for `pbotfire`, `pbotfight`, and `pbotdark` from verified evidence; (complete)
4. replace manual requeue commands with a resolver that selects a known owned counter and starts a bounded retry;
5. report `needs_attention` only when no known safe counter is available.

That slice would have handled Mega Mawile automatically: capture Fire/Typhlosion, resolve it to verified owned `pbotfire`, requeue once, and learn the result without an agent.

### Implemented 2026-08-23

- Added durable `battle_recommendations`, `deck_recipes`, `owned_decks`, `run_objectives`, and `run_checkpoints` storage.
- Removed account-specific owned-deck seeding. Clean databases contain reusable recipes only; a completed read-only device scan is now the authority for locally available decks.
- The result lifecycle now parses and persists recommendation type, named theme deck, confidence, OCR text, attempt, and screenshot evidence.
- Added a deterministic resolver that selects an untried verified owned deck of the recommended type, preferring an exact theme-reference match and refusing blind repeat attempts.
- Added a targeted autonomous first-win loop, detached managed execution, `completed`/`needs_attention` semantics, API Run/Stop endpoints, and the dashboard **Run pbot** control.
- Backfilled Mega Kangaskhan's Water / Mega Sharpedo recommendation from saved evidence. Because `vaporcuno` has now already lost that retry, the resolver correctly reports that a new Water strategy is required instead of looping.
- Added the first complete portable recipe: the exact 20-card tournament-derived Mega Sharpedo ex / Milotic ex list, including stable set/card IDs and provenance.
- Proved the owned-card adaptation flow on device. QR import identified one missing second Mega Sharpedo ex; pbot removed only that unavailable copy, substituted owned Genetic Apex Articuno ex (`A1-084`), retained Water energy and 20/20 legality, saved slot 21 as `pbotwater`, and read it back before marking it verified.
- Added durable deck-build evidence and substitution records, complete/adapted recipe validation, managed owned-deck registration, and exact-battle detached targeting. The strategy resolver now chooses the newly verified `pbotwater` for Mega Kangaskhan without an agent requeueing a generic Water deck.
- The bounded proof succeeded: `pbotwater` beat Advanced Mega Kangaskhan in auto mode on attempt 165 and completed two missions. The worker also recovered that retained battle after an interruption by reattaching to the matching durable attempt, draining the result lifecycle, and reconciling the win without replaying it.
- Added safe recovery from account deck-detail/builder/list roots and slot-aware managed-deck selection for a final odd slot whose name is hidden under the selector bar; selection is still verified by visible deck name on Battle Rules before play.
- Captured and shipped the exact 20-card Fire, Fighting, and Darkness managed recipes and their on-device 2D pattern codes. The Dark recipe is derived from the published Hoopa ex list with one declared `B4-096` to `B2-099` Galarian Linoone replacement.
- Expanded named-recommendation construction to Elite Mega Charizard Y ex, Elite Mega Lucario ex, and Hoopa ex while retaining exact-name, complete-recipe, owned-only, and no-spend guards.
- Added durable account-profile state and a read-only deck bootstrap exposed through the dashboard and API. It verifies name, `20/20`, energy, usability, and detail-screen signatures for each usable slot, excludes visibly unusable decks, commits availability only after a complete pass, and blocks autonomous runs until the account profile is ready.
- Added a second atomic local profile for the 44 stable card IDs referenced by complete shipped recipes. My Cards exact-name filters record quantities only for uniquely identified prints or explicit identity hints; alternate prints remain `unknown`. Recipe buildability is persisted as `exact`, `blocked`, or `unknown`, and the resolver cannot invoke the constructor without an `exact` adapted recipe.
- Card observations are checkpointed after each stable identity and reused only for the same device and unchanged card identity. The authoritative inventory/buildability snapshot remains atomic, while interrupted scans resume at the first unfinished card and clear checkpoints only after a complete commit.
- Versioned stable-ID visual anchors (attack, ability, or distinctive effect text) resolve alternate prints without a model. Quantity selection is tied geometrically to the matched tile, with a high-contrast crop fallback when the full-frame OCR misses the overlay.

The next slice is to encode the now-proven QR import, ownership failure, substitution, rename, and read-back interactions as a guarded constructor, then capture the remaining managed and pre-existing deck lists.
