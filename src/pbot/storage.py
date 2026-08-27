from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .deck_recipe import BUILTIN_DECK_RECIPES


SCHEMA = """
CREATE TABLE IF NOT EXISTS run_state (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  status TEXT NOT NULL,
  objective TEXT NOT NULL,
  device_serial TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  level TEXT NOT NULL,
  message TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS battles (
  id TEXT PRIMARY KEY,
  expansion TEXT NOT NULL,
  difficulty TEXT NOT NULL,
  name TEXT NOT NULL,
  first_win INTEGER NOT NULL DEFAULT 0,
  discovered_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS missions (
  id TEXT PRIMARY KEY,
  battle_id TEXT NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
  description TEXT NOT NULL,
  complete INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  battle_id TEXT NOT NULL REFERENCES battles(id),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  deck_name TEXT,
  mode TEXT NOT NULL,
  result TEXT,
  evidence_path TEXT
);
CREATE TABLE IF NOT EXISTS battle_progress (
  battle_id TEXT PRIMARY KEY REFERENCES battles(id) ON DELETE CASCADE,
  missions_complete INTEGER NOT NULL DEFAULT 0,
  missions_total INTEGER NOT NULL DEFAULT 0,
  evidence_path TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS progress_summary (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  battles_total INTEGER NOT NULL DEFAULT 0,
  battles_won INTEGER NOT NULL DEFAULT 0,
  missions_total INTEGER NOT NULL DEFAULT 0,
  missions_complete INTEGER NOT NULL DEFAULT 0,
  captured_at TEXT
);
CREATE TABLE IF NOT EXISTS battle_work (
  battle_id TEXT PRIMARY KEY REFERENCES battles(id) ON DELETE CASCADE,
  state TEXT NOT NULL CHECK (state IN ('queued', 'in_progress', 'completed', 'deferred')),
  reason TEXT,
  last_attempt_id INTEGER REFERENCES attempts(id),
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS battle_recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  battle_id TEXT NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
  attempt_id INTEGER REFERENCES attempts(id) ON DELETE SET NULL,
  recommended_type TEXT,
  recommended_deck_name TEXT,
  source_text TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  evidence_path TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(battle_id, attempt_id)
);
CREATE TABLE IF NOT EXISTS deck_recipes (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  energy_types TEXT NOT NULL DEFAULT '[]',
  cards TEXT NOT NULL DEFAULT '[]',
  capabilities TEXT NOT NULL DEFAULT '[]',
  source_kind TEXT NOT NULL,
  source_ref TEXT,
  game_version TEXT,
  capture_status TEXT NOT NULL CHECK (capture_status IN ('reference_only', 'complete')),
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS owned_decks (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL UNIQUE,
  recipe_id TEXT REFERENCES deck_recipes(id) ON DELETE SET NULL,
  energy_types TEXT NOT NULL DEFAULT '[]',
  available INTEGER NOT NULL DEFAULT 1,
  verified INTEGER NOT NULL DEFAULT 0,
  managed INTEGER NOT NULL DEFAULT 0,
  slot_number INTEGER,
  source TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_profile (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  status TEXT NOT NULL CHECK (status IN ('not_scanned', 'scanning', 'ready', 'needs_attention')),
  device_serial TEXT,
  deck_count INTEGER NOT NULL DEFAULT 0,
  scanned_at TEXT,
  evidence_path TEXT,
  message TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS card_inventory_profile (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  status TEXT NOT NULL CHECK (status IN ('not_scanned', 'scanning', 'ready', 'needs_attention')),
  device_serial TEXT,
  target_count INTEGER NOT NULL DEFAULT 0,
  known_count INTEGER NOT NULL DEFAULT 0,
  exact_recipe_count INTEGER NOT NULL DEFAULT 0,
  scanned_at TEXT,
  evidence_path TEXT,
  message TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS owned_cards (
  card_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  quantity INTEGER,
  identity_hint TEXT,
  status TEXT NOT NULL CHECK (status IN ('verified', 'missing', 'ambiguous')),
  evidence_path TEXT,
  message TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS card_scan_checkpoint (
  card_id TEXT PRIMARY KEY,
  device_serial TEXT,
  name TEXT NOT NULL,
  quantity INTEGER,
  identity_hint TEXT,
  status TEXT NOT NULL CHECK (status IN ('verified', 'missing', 'ambiguous')),
  evidence_path TEXT,
  message TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recipe_buildability (
  recipe_id TEXT PRIMARY KEY REFERENCES deck_recipes(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('exact', 'blocked', 'unknown')),
  missing_cards TEXT NOT NULL DEFAULT '[]',
  unknown_cards TEXT NOT NULL DEFAULT '[]',
  checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deck_builds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recipe_id TEXT NOT NULL REFERENCES deck_recipes(id) ON DELETE CASCADE,
  deck_name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (
    status IN ('planned', 'imported', 'needs_substitution', 'verified', 'failed')
  ),
  missing_cards TEXT NOT NULL DEFAULT '[]',
  substitutions TEXT NOT NULL DEFAULT '[]',
  evidence_path TEXT,
  message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_objectives (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'needs_attention', 'failed', 'stopped')),
  objective TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT '{}',
  policy TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS run_checkpoints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES run_objectives(id) ON DELETE CASCADE,
  phase TEXT NOT NULL,
  battle_id TEXT REFERENCES battles(id) ON DELETE SET NULL,
  strategy TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_occurred_at ON events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_missions_battle_id ON missions(battle_id);
CREATE INDEX IF NOT EXISTS idx_attempts_battle_started ON attempts(battle_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_battle_work_state ON battle_work(state, updated_at);
CREATE INDEX IF NOT EXISTS idx_recommendations_battle ON battle_recommendations(battle_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_owned_decks_available ON owned_decks(available, verified);
CREATE INDEX IF NOT EXISTS idx_owned_cards_status ON owned_cards(status, name);
CREATE INDEX IF NOT EXISTS idx_recipe_buildability_status ON recipe_buildability(status, recipe_id);
CREATE INDEX IF NOT EXISTS idx_deck_builds_recipe ON deck_builds(recipe_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_run_checkpoints_run ON run_checkpoints(run_id, id DESC);
"""


BUILTIN_RECIPES = tuple(
    {
        "id": recipe.id,
        "display_name": recipe.display_name,
        "energy_types": list(recipe.energy_types),
        "cards": recipe.card_dicts(),
        "capabilities": list(recipe.capabilities),
        "source_kind": recipe.source_kind,
        "source_ref": recipe.source_ref,
        "capture_status": "complete",
    }
    for recipe in BUILTIN_DECK_RECIPES.values()
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            now = utc_now()
            connection.execute(
                "INSERT OR IGNORE INTO run_state(singleton, status, objective, updated_at) VALUES(1, ?, ?, ?)",
                ("offline", "Connect an Android device", now),
            )
            connection.execute("INSERT OR IGNORE INTO progress_summary(singleton) VALUES(1)")
            connection.execute(
                """INSERT OR IGNORE INTO account_profile(
                       singleton, status, deck_count, message, updated_at
                   ) VALUES(1, 'not_scanned', 0, 'Scan the connected account before running pbot', ?)""",
                (now,),
            )
            connection.execute(
                """INSERT OR IGNORE INTO card_inventory_profile(
                       singleton, status, target_count, known_count, exact_recipe_count,
                       message, updated_at
                   ) VALUES(1, 'not_scanned', 0, 0, 0,
                            'Scan recipe card capabilities before autonomous construction', ?)""",
                (now,),
            )
            for recipe in BUILTIN_RECIPES:
                connection.execute(
                    """INSERT INTO deck_recipes(
                           id, display_name, energy_types, cards, capabilities, source_kind,
                           source_ref, game_version, capture_status, updated_at
                       ) VALUES(?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         display_name = excluded.display_name,
                         energy_types = excluded.energy_types,
                         cards = CASE
                           WHEN excluded.capture_status = 'complete' THEN excluded.cards
                           ELSE deck_recipes.cards
                         END,
                         capabilities = excluded.capabilities,
                         source_kind = excluded.source_kind,
                         source_ref = excluded.source_ref,
                         capture_status = CASE
                           WHEN deck_recipes.capture_status = 'complete' THEN 'complete'
                           ELSE excluded.capture_status
                         END,
                         updated_at = excluded.updated_at""",
                    (
                        recipe["id"],
                        recipe["display_name"],
                        json.dumps(recipe["energy_types"]),
                        json.dumps(recipe.get("cards", [])),
                        json.dumps(recipe["capabilities"]),
                        recipe["source_kind"],
                        recipe["source_ref"],
                        recipe["capture_status"],
                        now,
                    ),
                )
            connection.execute("PRAGMA optimize")

    def get_account_profile(self) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM account_profile WHERE singleton = 1"
            ).fetchone()
        return dict(row) if row else {}

    def begin_account_scan(self, device_serial: str | None) -> dict[str, object]:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """UPDATE account_profile SET
                     status = 'scanning', device_serial = ?,
                     message = 'Reading owned deck slots from the connected account',
                     updated_at = ?
                   WHERE singleton = 1""",
                (device_serial, now),
            )
            row = connection.execute(
                "SELECT * FROM account_profile WHERE singleton = 1"
            ).fetchone()
        return dict(row) if row else {}

    def finish_account_scan(
        self,
        device_serial: str | None,
        decks: list[dict[str, object]],
        evidence_path: str | None,
    ) -> dict[str, object]:
        """Atomically replace local owned-deck availability after a complete scan."""
        slots = [int(deck["slot_number"]) for deck in decks]
        names = [str(deck["display_name"]).strip() for deck in decks]
        if not decks:
            raise ValueError("Account scan did not find any owned decks")
        if len(slots) != len(set(slots)) or any(slot < 1 or slot > 25 for slot in slots):
            raise ValueError("Account scan contains invalid or duplicate deck slots")
        if any(not name for name in names) or len({name.casefold() for name in names}) != len(names):
            raise ValueError("Account scan contains empty or duplicate deck names")

        now = utc_now()
        with self.connect() as connection:
            previous = {
                str(row["display_name"]).casefold(): dict(row)
                for row in connection.execute("SELECT * FROM owned_decks").fetchall()
            }
            connection.execute("UPDATE owned_decks SET available = 0, verified = 0, updated_at = ?", (now,))
            for deck in decks:
                display_name = str(deck["display_name"]).strip()
                prior = previous.get(display_name.casefold())
                recipe_id = deck.get("recipe_id") or (prior.get("recipe_id") if prior else None)
                managed = bool(deck.get("managed")) or bool(prior and prior.get("managed"))
                connection.execute(
                    """INSERT INTO owned_decks(
                           id, display_name, recipe_id, energy_types, available, verified,
                           managed, slot_number, source, updated_at
                       ) VALUES(?, ?, ?, ?, 1, 1, ?, ?, 'account_bootstrap_scan', ?)
                       ON CONFLICT(display_name) DO UPDATE SET
                         recipe_id = excluded.recipe_id,
                         energy_types = excluded.energy_types,
                         available = 1,
                         verified = 1,
                         managed = excluded.managed,
                         slot_number = excluded.slot_number,
                         source = excluded.source,
                         updated_at = excluded.updated_at""",
                    (
                        display_name.casefold(),
                        display_name,
                        recipe_id,
                        json.dumps(list(deck.get("energy_types") or [])),
                        int(managed),
                        int(deck["slot_number"]),
                        now,
                    ),
                )
            connection.execute(
                """UPDATE account_profile SET
                     status = 'ready', device_serial = ?, deck_count = ?, scanned_at = ?,
                     evidence_path = ?, message = ?, updated_at = ?
                   WHERE singleton = 1""",
                (
                    device_serial,
                    len(decks),
                    now,
                    evidence_path,
                    f"Verified {len(decks)} owned deck slots",
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM account_profile WHERE singleton = 1"
            ).fetchone()
        return dict(row) if row else {}

    def fail_account_scan(self, device_serial: str | None, message: str) -> dict[str, object]:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """UPDATE account_profile SET
                     status = 'needs_attention', device_serial = ?, message = ?, updated_at = ?
                   WHERE singleton = 1""",
                (device_serial, message, now),
            )
            row = connection.execute(
                "SELECT * FROM account_profile WHERE singleton = 1"
            ).fetchone()
        return dict(row) if row else {}

    def get_card_inventory_profile(self) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM card_inventory_profile WHERE singleton = 1"
            ).fetchone()
        return dict(row) if row else {}

    def begin_card_scan(self, device_serial: str | None, target_count: int) -> dict[str, object]:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """UPDATE card_inventory_profile SET
                     status = 'scanning', device_serial = ?, target_count = ?,
                     message = 'Reading shipped recipe card quantities from My Cards',
                     updated_at = ?
                   WHERE singleton = 1""",
                (device_serial, target_count, now),
            )
            row = connection.execute(
                "SELECT * FROM card_inventory_profile WHERE singleton = 1"
            ).fetchone()
        return dict(row) if row else {}

    def finish_card_scan(
        self,
        device_serial: str | None,
        cards: list[dict[str, object]],
        buildability: list[dict[str, object]],
        evidence_path: str | None,
    ) -> dict[str, object]:
        if not cards or len({str(card["card_id"]) for card in cards}) != len(cards):
            raise ValueError("Card scan contains no cards or duplicate stable IDs")
        valid_card_statuses = {"verified", "missing", "ambiguous"}
        valid_recipe_statuses = {"exact", "blocked", "unknown"}
        if any(str(card.get("status")) not in valid_card_statuses for card in cards):
            raise ValueError("Card scan contains an unsupported status")
        if any(str(item.get("status")) not in valid_recipe_statuses for item in buildability):
            raise ValueError("Recipe preflight contains an unsupported status")
        known_count = sum(card.get("status") != "ambiguous" for card in cards)
        exact_count = sum(item.get("status") == "exact" for item in buildability)
        now = utc_now()
        with self.connect() as connection:
            connection.execute("DELETE FROM owned_cards")
            for card in cards:
                connection.execute(
                    """INSERT INTO owned_cards(
                           card_id, name, quantity, identity_hint, status,
                           evidence_path, message, source, updated_at
                       ) VALUES(?, ?, ?, ?, ?, ?, ?, 'my_cards_recipe_scan', ?)""",
                    (
                        str(card["card_id"]),
                        str(card["name"]),
                        card.get("quantity"),
                        card.get("identity_hint"),
                        str(card["status"]),
                        card.get("evidence_path"),
                        str(card.get("message") or ""),
                        now,
                    ),
                )
            connection.execute("DELETE FROM recipe_buildability")
            for item in buildability:
                connection.execute(
                    """INSERT INTO recipe_buildability(
                           recipe_id, status, missing_cards, unknown_cards, checked_at
                       ) VALUES(?, ?, ?, ?, ?)""",
                    (
                        str(item["recipe_id"]),
                        str(item["status"]),
                        json.dumps(item.get("missing_cards") or []),
                        json.dumps(item.get("unknown_cards") or []),
                        now,
                    ),
                )
            connection.execute("DELETE FROM card_scan_checkpoint")
            connection.execute(
                """UPDATE card_inventory_profile SET
                     status = 'ready', device_serial = ?, target_count = ?, known_count = ?,
                     exact_recipe_count = ?, scanned_at = ?, evidence_path = ?,
                     message = ?, updated_at = ?
                   WHERE singleton = 1""",
                (
                    device_serial,
                    len(cards),
                    known_count,
                    exact_count,
                    now,
                    evidence_path,
                    f"Checked {len(cards)} recipe cards; {exact_count} recipes are exact",
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM card_inventory_profile WHERE singleton = 1"
            ).fetchone()
        return dict(row) if row else {}

    def save_card_scan_checkpoint(
        self, device_serial: str | None, card: dict[str, object]
    ) -> None:
        status = str(card.get("status"))
        if status not in {"verified", "missing", "ambiguous"}:
            raise ValueError("Card scan checkpoint contains an unsupported status")
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO card_scan_checkpoint(
                       card_id, device_serial, name, quantity, identity_hint, status,
                       evidence_path, message, updated_at
                   ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(card_id) DO UPDATE SET
                     device_serial = excluded.device_serial,
                     name = excluded.name,
                     quantity = excluded.quantity,
                     identity_hint = excluded.identity_hint,
                     status = excluded.status,
                     evidence_path = excluded.evidence_path,
                     message = excluded.message,
                     updated_at = excluded.updated_at""",
                (
                    str(card["card_id"]),
                    device_serial,
                    str(card["name"]),
                    card.get("quantity"),
                    card.get("identity_hint"),
                    status,
                    card.get("evidence_path"),
                    str(card.get("message") or ""),
                    utc_now(),
                ),
            )

    def card_scan_checkpoints(self, device_serial: str | None) -> list[dict[str, object]]:
        with self.connect() as connection:
            if device_serial is None:
                rows = connection.execute(
                    "SELECT * FROM card_scan_checkpoint WHERE device_serial IS NULL ORDER BY card_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM card_scan_checkpoint WHERE device_serial = ? ORDER BY card_id",
                    (device_serial,),
                ).fetchall()
        return [dict(row) for row in rows]

    def update_card_scan_progress(self, completed: int, target_count: int, card_name: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE card_inventory_profile SET
                     target_count = ?, message = ?, updated_at = ?
                   WHERE singleton = 1 AND status = 'scanning'""",
                (
                    target_count,
                    f"Checked {completed}/{target_count} recipe cards · {card_name}",
                    utc_now(),
                ),
            )

    def fail_card_scan(self, device_serial: str | None, message: str) -> dict[str, object]:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """UPDATE card_inventory_profile SET
                     status = 'needs_attention', device_serial = ?, message = ?, updated_at = ?
                   WHERE singleton = 1""",
                (device_serial, message, now),
            )
            row = connection.execute(
                "SELECT * FROM card_inventory_profile WHERE singleton = 1"
            ).fetchone()
        return dict(row) if row else {}

    def owned_cards(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM owned_cards ORDER BY name COLLATE NOCASE, card_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def recipe_buildability(self, recipe_id: str | None = None) -> list[dict[str, object]]:
        query = "SELECT * FROM recipe_buildability"
        parameters: tuple[object, ...] = ()
        if recipe_id:
            query += " WHERE recipe_id = ?"
            parameters = (recipe_id,)
        query += " ORDER BY recipe_id"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["missing_cards"] = json.loads(str(item["missing_cards"]))
            item["unknown_cards"] = json.loads(str(item["unknown_cards"]))
            result.append(item)
        return result

    def set_state(self, status: str, objective: str, device_serial: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE run_state SET status = ?, objective = ?, device_serial = ?, updated_at = ? WHERE singleton = 1",
                (status, objective, device_serial, utc_now()),
            )

    def get_state(self) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM run_state WHERE singleton = 1").fetchone()
        return dict(row) if row else {}

    def add_event(self, kind: str, message: str, level: str = "info", payload: dict | None = None) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO events(occurred_at, kind, level, message, payload) VALUES(?, ?, ?, ?, ?)",
                (utc_now(), kind, level, message, json.dumps(payload or {}, separators=(",", ":"))),
            )
            return int(cursor.lastrowid)

    def recent_events(self, limit: int = 20) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, occurred_at, kind, level, message, payload FROM events ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        events = [dict(row) for row in rows]
        for event in events:
            event["payload"] = json.loads(str(event["payload"]))
        return events

    def record_battle_recommendation(
        self,
        battle_id: str,
        attempt_id: int | None,
        recommended_type: str | None,
        recommended_deck_name: str | None,
        source_text: str,
        confidence: float,
        evidence_path: str | None,
    ) -> dict[str, object]:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO battle_recommendations(
                       battle_id, attempt_id, recommended_type, recommended_deck_name,
                       source_text, confidence, evidence_path, created_at
                   ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(battle_id, attempt_id) DO UPDATE SET
                     recommended_type = excluded.recommended_type,
                     recommended_deck_name = excluded.recommended_deck_name,
                     source_text = excluded.source_text,
                     confidence = excluded.confidence,
                     evidence_path = excluded.evidence_path,
                     created_at = excluded.created_at""",
                (
                    battle_id,
                    attempt_id,
                    recommended_type,
                    recommended_deck_name,
                    source_text,
                    max(0.0, min(float(confidence), 1.0)),
                    evidence_path,
                    now,
                ),
            )
            row = connection.execute(
                """SELECT * FROM battle_recommendations
                   WHERE battle_id = ? AND attempt_id IS ? ORDER BY id DESC LIMIT 1""",
                (battle_id, attempt_id),
            ).fetchone()
        return dict(row) if row else {}

    def latest_battle_recommendation(self, battle_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT * FROM battle_recommendations
                   WHERE battle_id = ? ORDER BY id DESC LIMIT 1""",
                (battle_id,),
            ).fetchone()
        return dict(row) if row else None

    def pending_recommendation_backfill(self) -> list[dict[str, object]]:
        """Return deferred losses whose retained lifecycle evidence has not been parsed."""
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT b.id battle_id, b.name battle_name,
                          a.id attempt_id, a.evidence_path
                   FROM battle_work w
                   JOIN battles b ON b.id = w.battle_id
                   JOIN attempts a ON a.id = COALESCE(
                     w.last_attempt_id,
                     (SELECT a2.id FROM attempts a2
                      WHERE a2.battle_id = b.id
                      ORDER BY a2.id DESC LIMIT 1)
                   )
                   WHERE w.state = 'deferred'
                     AND a.evidence_path IS NOT NULL
                     AND NOT EXISTS (
                       SELECT 1 FROM battle_recommendations r
                       WHERE r.battle_id = b.id
                     )
                   ORDER BY a.id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_recommendations(self, limit: int = 20) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT r.id, r.battle_id, r.attempt_id, r.recommended_type,
                          r.recommended_deck_name, r.confidence, r.evidence_path,
                          r.created_at, b.name battle_name, b.expansion, b.difficulty
                   FROM battle_recommendations r JOIN battles b ON b.id = r.battle_id
                   ORDER BY r.id DESC LIMIT ?""",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_deck_recipe(
        self,
        recipe_id: str,
        display_name: str,
        energy_types: list[str],
        cards: list[dict[str, object]],
        capabilities: list[str],
        source_kind: str,
        source_ref: str | None,
        capture_status: str,
        game_version: str | None = None,
    ) -> dict[str, object]:
        if capture_status not in {"reference_only", "complete"}:
            raise ValueError(f"Unsupported recipe capture status: {capture_status}")
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO deck_recipes(
                       id, display_name, energy_types, cards, capabilities, source_kind,
                       source_ref, game_version, capture_status, updated_at
                   ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     display_name = excluded.display_name,
                     energy_types = excluded.energy_types,
                     cards = excluded.cards,
                     capabilities = excluded.capabilities,
                     source_kind = excluded.source_kind,
                     source_ref = excluded.source_ref,
                     game_version = excluded.game_version,
                     capture_status = excluded.capture_status,
                     updated_at = excluded.updated_at""",
                (
                    recipe_id,
                    display_name,
                    json.dumps(energy_types, separators=(",", ":")),
                    json.dumps(cards, separators=(",", ":")),
                    json.dumps(capabilities, separators=(",", ":")),
                    source_kind,
                    source_ref,
                    game_version,
                    capture_status,
                    now,
                ),
            )
        recipe = self.get_deck_recipe(recipe_id)
        if not recipe:
            raise RuntimeError(f"Failed to persist deck recipe {recipe_id}")
        return recipe

    def get_deck_recipe(self, recipe_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM deck_recipes WHERE id = ?", (recipe_id,)
            ).fetchone()
        if not row:
            return None
        recipe = dict(row)
        for field in ("energy_types", "cards", "capabilities"):
            recipe[field] = json.loads(str(recipe[field]))
        return recipe

    def record_deck_build(
        self,
        recipe_id: str,
        deck_name: str,
        status: str,
        missing_cards: list[dict[str, object]] | None = None,
        substitutions: list[dict[str, object]] | None = None,
        evidence_path: str | None = None,
        message: str | None = None,
    ) -> dict[str, object]:
        allowed = {"planned", "imported", "needs_substitution", "verified", "failed"}
        if status not in allowed:
            raise ValueError(f"Unsupported deck build status: {status}")
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO deck_builds(
                       recipe_id, deck_name, status, missing_cards, substitutions,
                       evidence_path, message, created_at, updated_at
                   ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    recipe_id,
                    deck_name,
                    status,
                    json.dumps(missing_cards or [], separators=(",", ":")),
                    json.dumps(substitutions or [], separators=(",", ":")),
                    evidence_path,
                    message,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM deck_builds WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        build = dict(row) if row else {}
        for field in ("missing_cards", "substitutions"):
            if field in build:
                build[field] = json.loads(str(build[field]))
        return build

    def register_owned_deck(
        self,
        display_name: str,
        recipe_id: str | None,
        energy_types: list[str],
        *,
        verified: bool,
        managed: bool,
        slot_number: int | None,
        source: str,
        available: bool = True,
    ) -> dict[str, object]:
        deck_id = display_name.casefold()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO owned_decks(
                       id, display_name, recipe_id, energy_types, available, verified,
                       managed, slot_number, source, updated_at
                   ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     display_name = excluded.display_name,
                     recipe_id = excluded.recipe_id,
                     energy_types = excluded.energy_types,
                     available = excluded.available,
                     verified = excluded.verified,
                     managed = excluded.managed,
                     slot_number = excluded.slot_number,
                     source = excluded.source,
                     updated_at = excluded.updated_at""",
                (
                    deck_id,
                    display_name,
                    recipe_id,
                    json.dumps(energy_types, separators=(",", ":")),
                    int(available),
                    int(verified),
                    int(managed),
                    slot_number,
                    source,
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM owned_decks WHERE id = ?", (deck_id,)
            ).fetchone()
        deck = dict(row) if row else {}
        if "energy_types" in deck:
            deck["energy_types"] = json.loads(str(deck["energy_types"]))
        return deck

    def owned_decks(self, energy_type: str | None = None) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT d.*, r.source_ref recipe_source_ref, r.capture_status recipe_capture_status
                   FROM owned_decks d LEFT JOIN deck_recipes r ON r.id = d.recipe_id
                   WHERE d.available = 1 AND d.verified = 1
                   ORDER BY d.managed DESC, d.display_name"""
            ).fetchall()
        decks: list[dict[str, object]] = []
        for row in rows:
            deck = dict(row)
            deck["energy_types"] = json.loads(str(deck["energy_types"]))
            if energy_type and energy_type.casefold() not in {
                str(item).casefold() for item in deck["energy_types"]
            }:
                continue
            decks.append(deck)
        return decks

    def deck_attempt_summary(self, battle_id: str, deck_name: str) -> dict[str, int]:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) attempts,
                          COALESCE(SUM(result = 'win'), 0) wins,
                          COALESCE(SUM(result = 'loss'), 0) losses,
                          COALESCE(SUM(result = 'tie'), 0) ties
                   FROM attempts WHERE battle_id = ? AND lower(deck_name) = lower(?)
                     AND result IN ('win', 'loss', 'tie')""",
                (battle_id, deck_name),
            ).fetchone()
        return {key: int(row[key]) for key in ("attempts", "wins", "losses", "ties")}

    def latest_recoverable_attempt(
        self,
        battle_id: str,
        deck_name: str,
    ) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT * FROM attempts
                   WHERE battle_id = ? AND lower(deck_name) = lower(?)
                     AND result IN ('interrupted', 'error')
                   ORDER BY id DESC LIMIT 1""",
                (battle_id, deck_name),
            ).fetchone()
        return dict(row) if row else None

    def start_run_objective(
        self,
        objective: str,
        scope: dict[str, object],
        policy: dict[str, object],
    ) -> dict[str, object]:
        now = utc_now()
        run_id = uuid.uuid4().hex[:12]
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO run_objectives(
                       id, status, objective, scope, policy, started_at, updated_at, finished_at
                   ) VALUES(?, 'running', ?, ?, ?, ?, ?, NULL)""",
                (
                    run_id,
                    objective,
                    json.dumps(scope, separators=(",", ":")),
                    json.dumps(policy, separators=(",", ":")),
                    now,
                    now,
                ),
            )
        return self.get_run_objective(run_id) or {}

    def update_run_objective(self, run_id: str, status: str) -> dict[str, object]:
        terminal = status in {"completed", "needs_attention", "failed", "stopped"}
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """UPDATE run_objectives SET status = ?, updated_at = ?, finished_at = ?
                   WHERE id = ?""",
                (status, now, now if terminal else None, run_id),
            )
        return self.get_run_objective(run_id) or {}

    def add_run_checkpoint(
        self,
        run_id: str,
        phase: str,
        status: str,
        message: str,
        battle_id: str | None = None,
        strategy: dict[str, object] | None = None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO run_checkpoints(
                       run_id, phase, battle_id, strategy, status, message, created_at
                   ) VALUES(?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    phase,
                    battle_id,
                    json.dumps(strategy or {}, separators=(",", ":")),
                    status,
                    message,
                    utc_now(),
                ),
            )
        return int(cursor.lastrowid)

    def get_run_objective(self, run_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM run_objectives WHERE id = ?", (run_id,)).fetchone()
            checkpoint = connection.execute(
                "SELECT * FROM run_checkpoints WHERE run_id = ? ORDER BY id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["scope"] = json.loads(str(payload["scope"]))
        payload["policy"] = json.loads(str(payload["policy"]))
        payload["checkpoint"] = dict(checkpoint) if checkpoint else None
        if payload["checkpoint"]:
            payload["checkpoint"]["strategy"] = json.loads(str(payload["checkpoint"]["strategy"]))
        return payload

    def latest_run_objective(self) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM run_objectives ORDER BY started_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        return self.get_run_objective(str(row["id"])) if row else None

    def set_progress_summary(
        self,
        battles_total: int,
        battles_won: int,
        missions_total: int,
        missions_complete: int,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE progress_summary
                   SET battles_total = ?, battles_won = ?, missions_total = ?,
                       missions_complete = ?, captured_at = ?
                   WHERE singleton = 1""",
                (battles_total, battles_won, missions_total, missions_complete, utc_now()),
            )

    def record_attempt(
        self,
        battle_id: str,
        expansion: str,
        difficulty: str,
        name: str,
        deck_name: str,
        mode: str,
        result: str,
        evidence_path: str | None = None,
    ) -> int:
        attempt_id = self.start_attempt(battle_id, expansion, difficulty, name, deck_name, mode)
        self.finish_attempt(attempt_id, result, evidence_path)
        return attempt_id

    def start_attempt(
        self,
        battle_id: str,
        expansion: str,
        difficulty: str,
        name: str,
        deck_name: str,
        mode: str,
    ) -> int:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO battles(id, expansion, difficulty, name, first_win, discovered_at, updated_at)
                   VALUES(?, ?, ?, ?, 0, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at""",
                (battle_id, expansion, difficulty, name, now, now),
            )
            cursor = connection.execute(
                """INSERT INTO attempts(battle_id, started_at, finished_at, deck_name, mode, result, evidence_path)
                   VALUES(?, ?, NULL, ?, ?, NULL, NULL)""",
                (battle_id, now, deck_name, mode),
            )
        return int(cursor.lastrowid)

    def finish_attempt(
        self,
        attempt_id: int,
        result: str,
        evidence_path: str | None = None,
        missions_complete: int | None = None,
        missions_total: int | None = None,
    ) -> dict[str, int | str | None]:
        now = utc_now()
        with self.connect() as connection:
            attempt = connection.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
            if not attempt:
                raise ValueError(f"Unknown attempt {attempt_id}")
            if attempt["finished_at"]:
                raise ValueError(f"Attempt {attempt_id} is already finished")

            battle = connection.execute("SELECT first_win FROM battles WHERE id = ?", (attempt["battle_id"],)).fetchone()
            previous_win = int(battle["first_win"]) if battle else 0
            progress = connection.execute(
                "SELECT missions_complete, missions_total FROM battle_progress WHERE battle_id = ?",
                (attempt["battle_id"],),
            ).fetchone()
            previous_missions = int(progress["missions_complete"]) if progress else 0
            previous_total = int(progress["missions_total"]) if progress else 0

            connection.execute(
                "UPDATE attempts SET finished_at = ?, result = ?, evidence_path = ? WHERE id = ?",
                (now, result, evidence_path, attempt_id),
            )
            won = int(result == "win")
            connection.execute(
                "UPDATE battles SET first_win = MAX(first_win, ?), updated_at = ? WHERE id = ?",
                (won, now, attempt["battle_id"]),
            )

            mission_delta = 0
            if missions_complete is not None or missions_total is not None:
                next_missions = max(previous_missions, int(missions_complete or 0))
                next_total = max(previous_total, int(missions_total or 0))
                mission_delta = next_missions - previous_missions
                connection.execute(
                    """INSERT INTO battle_progress(battle_id, missions_complete, missions_total, evidence_path, updated_at)
                       VALUES(?, ?, ?, ?, ?)
                       ON CONFLICT(battle_id) DO UPDATE SET
                         missions_complete = excluded.missions_complete,
                         missions_total = excluded.missions_total,
                         evidence_path = excluded.evidence_path,
                         updated_at = excluded.updated_at""",
                    (attempt["battle_id"], next_missions, next_total, evidence_path, now),
                )

            win_delta = int(won and not previous_win)
            summary = connection.execute("SELECT captured_at FROM progress_summary WHERE singleton = 1").fetchone()
            if summary and summary["captured_at"]:
                connection.execute(
                    """UPDATE progress_summary SET
                         battles_won = battles_won + ?,
                         missions_complete = missions_complete + ?,
                         captured_at = ?
                       WHERE singleton = 1""",
                    (win_delta, mission_delta, now),
                )

        return {
            "attempt_id": attempt_id,
            "battle_id": str(attempt["battle_id"]),
            "result": result,
            "win_delta": win_delta,
            "mission_delta": mission_delta,
            "evidence_path": evidence_path,
        }

    def import_battles(self, battles: list[dict[str, object]]) -> int:
        now = utc_now()
        with self.connect() as connection:
            for battle in battles:
                connection.execute(
                    """INSERT INTO battles(id, expansion, difficulty, name, first_win, discovered_at, updated_at)
                       VALUES(?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         expansion = excluded.expansion,
                         difficulty = excluded.difficulty,
                         name = excluded.name,
                         first_win = MAX(first_win, excluded.first_win),
                         updated_at = excluded.updated_at""",
                    (
                        battle["id"],
                        battle["expansion"],
                        battle["difficulty"],
                        battle["name"],
                        int(bool(battle["first_win"])),
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """INSERT INTO battle_progress(battle_id, missions_complete, missions_total, evidence_path, updated_at)
                       VALUES(?, ?, ?, ?, ?)
                       ON CONFLICT(battle_id) DO UPDATE SET
                         missions_complete = MAX(missions_complete, excluded.missions_complete),
                         missions_total = MAX(missions_total, excluded.missions_total),
                         evidence_path = excluded.evidence_path,
                         updated_at = excluded.updated_at""",
                    (
                        battle["id"],
                        int(battle["missions_complete"]),
                        int(battle["missions_total"]),
                        battle.get("evidence_path"),
                        now,
                    ),
                )
        return len(battles)

    def pending_battles(self, limit: int = 100) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT b.id, b.expansion, b.difficulty, b.name,
                          p.missions_complete, p.missions_total,
                          COALESCE(w.state, 'queued') work_state, w.reason
                   FROM battles b
                   LEFT JOIN battle_progress p ON p.battle_id = b.id
                   LEFT JOIN battle_work w ON w.battle_id = b.id
                   WHERE b.first_win = 0
                   ORDER BY CASE b.difficulty
                              WHEN 'Beginner' THEN 1 WHEN 'Intermediate' THEN 2
                              WHEN 'Advanced' THEN 3 WHEN 'Expert' THEN 4 ELSE 5 END,
                            b.expansion, b.name
                   LIMIT ?""",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def recover_interrupted_work(self) -> dict[str, int]:
        now = utc_now()
        with self.connect() as connection:
            interrupted = connection.execute(
                """UPDATE attempts SET finished_at = ?, result = 'interrupted'
                   WHERE finished_at IS NULL""",
                (now,),
            ).rowcount
            released = connection.execute(
                """UPDATE battle_work SET state = 'queued', reason = 'Recovered after interrupted worker', updated_at = ?
                   WHERE state = 'in_progress'""",
                (now,),
            ).rowcount
        return {"interrupted_attempts": interrupted, "released_claims": released}

    def reconcile_interrupted_win(
        self,
        attempt_id: int,
        battle: dict[str, object],
        alias_ids: tuple[str, ...] = (),
    ) -> dict[str, int | str]:
        """Attach a phone-confirmed win to an interrupted or errored attempt."""
        if not bool(battle.get("first_win")):
            raise ValueError("Crash reconciliation requires phone-side first-win evidence")

        now = utc_now()
        canonical_id = str(battle["id"])
        with self.connect() as connection:
            attempt = connection.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
            recoverable_results = {"interrupted", "error"}
            if not attempt or attempt["result"] not in recoverable_results:
                raise ValueError(f"Attempt {attempt_id} is not interrupted or errored")

            existing = connection.execute(
                "SELECT first_win FROM battles WHERE id = ?", (canonical_id,)
            ).fetchone()
            previous_win = int(existing["first_win"]) if existing else 0
            progress = connection.execute(
                "SELECT missions_complete FROM battle_progress WHERE battle_id = ?", (canonical_id,)
            ).fetchone()
            previous_missions = int(progress["missions_complete"]) if progress else 0
            next_missions = max(previous_missions, int(battle.get("missions_complete", 0)))
            next_total = int(battle.get("missions_total", 0))
            evidence_path = str(battle.get("evidence_path") or "") or None

            connection.execute(
                """INSERT INTO battles(id, expansion, difficulty, name, first_win, discovered_at, updated_at)
                   VALUES(?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     expansion = excluded.expansion, difficulty = excluded.difficulty,
                     name = excluded.name, first_win = 1, updated_at = excluded.updated_at""",
                (
                    canonical_id,
                    battle["expansion"],
                    battle["difficulty"],
                    battle["name"],
                    now,
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO battle_progress(battle_id, missions_complete, missions_total, evidence_path, updated_at)
                   VALUES(?, ?, ?, ?, ?)
                   ON CONFLICT(battle_id) DO UPDATE SET
                     missions_complete = MAX(missions_complete, excluded.missions_complete),
                     missions_total = MAX(missions_total, excluded.missions_total),
                     evidence_path = excluded.evidence_path, updated_at = excluded.updated_at""",
                (canonical_id, next_missions, next_total, evidence_path, now),
            )
            connection.execute(
                "UPDATE attempts SET battle_id = ?, finished_at = ?, result = 'win', evidence_path = ? WHERE id = ?",
                (canonical_id, now, evidence_path, attempt_id),
            )
            connection.execute(
                """INSERT INTO battle_work(battle_id, state, reason, last_attempt_id, updated_at)
                   VALUES(?, 'completed', 'Reconciled from phone-side progress after interruption', ?, ?)
                   ON CONFLICT(battle_id) DO UPDATE SET
                     state = 'completed', reason = excluded.reason,
                     last_attempt_id = excluded.last_attempt_id, updated_at = excluded.updated_at""",
                (canonical_id, attempt_id, now),
            )

            for alias_id in {str(attempt["battle_id"]), *alias_ids} - {canonical_id}:
                connection.execute("DELETE FROM battle_work WHERE battle_id = ?", (alias_id,))
                remaining = connection.execute(
                    "SELECT COUNT(*) count FROM attempts WHERE battle_id = ?", (alias_id,)
                ).fetchone()
                if remaining and int(remaining["count"]) == 0:
                    connection.execute("DELETE FROM battles WHERE id = ?", (alias_id,))

            win_delta = int(not previous_win)
            mission_delta = next_missions - previous_missions
            summary = connection.execute("SELECT captured_at FROM progress_summary WHERE singleton = 1").fetchone()
            if summary and summary["captured_at"]:
                connection.execute(
                    """UPDATE progress_summary SET battles_won = battles_won + ?,
                         missions_complete = missions_complete + ?, captured_at = ? WHERE singleton = 1""",
                    (win_delta, mission_delta, now),
                )

        return {
            "attempt_id": attempt_id,
            "battle_id": canonical_id,
            "win_delta": win_delta,
            "mission_delta": mission_delta,
        }

    def reconcile_error_result(
        self,
        attempt_id: int,
        result: str,
        evidence_path: str,
        missions_complete: int | None = None,
        missions_total: int | None = None,
    ) -> dict[str, int | str]:
        """Reclassify an errored/interrupted attempt from durable terminal evidence."""
        if result not in {"loss", "tie"}:
            raise ValueError(f"Unsupported error reconciliation result: {result}")
        with self.connect() as connection:
            attempt = connection.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
            if not attempt or attempt["result"] not in {"error", "interrupted"}:
                raise ValueError(f"Attempt {attempt_id} is not errored or interrupted")
            connection.execute(
                "UPDATE attempts SET result = ?, evidence_path = ? WHERE id = ?",
                (result, evidence_path, attempt_id),
            )
            mission_delta = 0
            if missions_complete is not None or missions_total is not None:
                progress = connection.execute(
                    "SELECT missions_complete, missions_total FROM battle_progress WHERE battle_id = ?",
                    (attempt["battle_id"],),
                ).fetchone()
                previous_missions = int(progress["missions_complete"]) if progress else 0
                previous_total = int(progress["missions_total"]) if progress else 0
                next_missions = max(previous_missions, int(missions_complete or 0))
                next_total = max(previous_total, int(missions_total or 0))
                mission_delta = next_missions - previous_missions
                now = utc_now()
                connection.execute(
                    """INSERT INTO battle_progress(battle_id, missions_complete, missions_total, evidence_path, updated_at)
                       VALUES(?, ?, ?, ?, ?)
                       ON CONFLICT(battle_id) DO UPDATE SET
                         missions_complete = excluded.missions_complete,
                         missions_total = excluded.missions_total,
                         evidence_path = excluded.evidence_path,
                         updated_at = excluded.updated_at""",
                    (attempt["battle_id"], next_missions, next_total, evidence_path, now),
                )
                summary = connection.execute(
                    "SELECT captured_at FROM progress_summary WHERE singleton = 1"
                ).fetchone()
                if summary and summary["captured_at"]:
                    connection.execute(
                        """UPDATE progress_summary SET missions_complete = missions_complete + ?, captured_at = ?
                           WHERE singleton = 1""",
                        (mission_delta, now),
                    )
        return {
            "attempt_id": attempt_id,
            "battle_id": str(attempt["battle_id"]),
            "result": result,
            "mission_delta": mission_delta,
        }

    def reconcile_error_as_loss(self, attempt_id: int, evidence_path: str) -> dict[str, int | str]:
        """Backward-compatible loss-specific reconciliation helper."""
        return self.reconcile_error_result(attempt_id, "loss", evidence_path)

    def claim_next_battle(
        self,
        difficulties: tuple[str, ...] = ("Intermediate", "Advanced", "Expert"),
        exclude_expansions: tuple[str, ...] = (),
    ) -> dict[str, object] | None:
        if not difficulties:
            return None
        difficulty_marks = ",".join("?" for _ in difficulties)
        exclusion_sql = ""
        parameters: list[object] = list(difficulties)
        if exclude_expansions:
            exclusion_sql = f" AND b.expansion NOT IN ({','.join('?' for _ in exclude_expansions)})"
            parameters.extend(exclude_expansions)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""SELECT b.id, b.expansion, b.difficulty, b.name,
                            p.missions_complete, p.missions_total
                     FROM battles b
                     LEFT JOIN battle_progress p ON p.battle_id = b.id
                     LEFT JOIN battle_work w ON w.battle_id = b.id
                     WHERE b.first_win = 0
                       AND b.difficulty IN ({difficulty_marks})
                       AND COALESCE(w.state, 'queued') = 'queued'
                       {exclusion_sql}
                     ORDER BY CASE b.difficulty
                                WHEN 'Beginner' THEN 1 WHEN 'Intermediate' THEN 2
                                WHEN 'Advanced' THEN 3 WHEN 'Expert' THEN 4 ELSE 5 END,
                              b.expansion, b.name
                     LIMIT 1""",
                parameters,
            ).fetchone()
            if not row:
                return None
            connection.execute(
                """INSERT INTO battle_work(battle_id, state, reason, last_attempt_id, updated_at)
                   VALUES(?, 'in_progress', NULL, NULL, ?)
                   ON CONFLICT(battle_id) DO UPDATE SET
                     state = 'in_progress', reason = NULL, updated_at = excluded.updated_at""",
                (row["id"], utc_now()),
            )
        return dict(row)

    def claim_battle(
        self,
        battle_id: str,
        difficulties: tuple[str, ...] = ("Intermediate", "Advanced", "Expert"),
    ) -> dict[str, object] | None:
        """Atomically claim one explicitly planned frontier."""
        if not difficulties:
            return None
        difficulty_marks = ",".join("?" for _ in difficulties)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""SELECT b.id, b.expansion, b.difficulty, b.name,
                            p.missions_complete, p.missions_total
                     FROM battles b
                     LEFT JOIN battle_progress p ON p.battle_id = b.id
                     LEFT JOIN battle_work w ON w.battle_id = b.id
                     WHERE b.id = ? AND b.first_win = 0
                       AND b.difficulty IN ({difficulty_marks})
                       AND COALESCE(w.state, 'queued') = 'queued'""",
                (battle_id, *difficulties),
            ).fetchone()
            if not row:
                return None
            connection.execute(
                """INSERT INTO battle_work(battle_id, state, reason, last_attempt_id, updated_at)
                   VALUES(?, 'in_progress', NULL, NULL, ?)
                   ON CONFLICT(battle_id) DO UPDATE SET
                     state = 'in_progress', reason = NULL, updated_at = excluded.updated_at""",
                (battle_id, utc_now()),
            )
        return dict(row)

    def resolve_battle_work(
        self,
        battle_id: str,
        state: str,
        reason: str | None = None,
        last_attempt_id: int | None = None,
    ) -> None:
        if state not in {"queued", "completed", "deferred"}:
            raise ValueError(f"Invalid resolved work state: {state}")
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO battle_work(battle_id, state, reason, last_attempt_id, updated_at)
                   VALUES(?, ?, ?, ?, ?)
                   ON CONFLICT(battle_id) DO UPDATE SET
                     state = excluded.state,
                     reason = excluded.reason,
                     last_attempt_id = COALESCE(excluded.last_attempt_id, battle_work.last_attempt_id),
                     updated_at = excluded.updated_at""",
                (battle_id, state, reason, last_attempt_id, utc_now()),
            )

    def deferred_battles(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT b.id, b.expansion, b.difficulty, b.name, w.reason, w.last_attempt_id, w.updated_at
                   FROM battle_work w JOIN battles b ON b.id = w.battle_id
                   WHERE w.state = 'deferred' ORDER BY w.updated_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def metrics(self) -> dict[str, int]:
        with self.connect() as connection:
            battle = connection.execute("SELECT COUNT(*) total, COALESCE(SUM(first_win), 0) won FROM battles").fetchone()
            mission = connection.execute("SELECT COUNT(*) total, COALESCE(SUM(complete), 0) complete FROM missions").fetchone()
            attempts = connection.execute("SELECT COUNT(*) total FROM attempts").fetchone()
            summary = connection.execute("SELECT * FROM progress_summary WHERE singleton = 1").fetchone()
        if summary and summary["captured_at"]:
            battles_total = int(summary["battles_total"])
            battles_won = int(summary["battles_won"])
            missions_total = int(summary["missions_total"])
            missions_complete = int(summary["missions_complete"])
        else:
            battles_total = int(battle["total"])
            battles_won = int(battle["won"])
            missions_total = int(mission["total"])
            missions_complete = int(mission["complete"])
        return {
            "battles_total": battles_total,
            "battles_won": battles_won,
            "missions_total": missions_total,
            "missions_complete": missions_complete,
            "attempts_total": int(attempts["total"]),
        }
