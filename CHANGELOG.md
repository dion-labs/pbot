# Changelog

## Unreleased

- Reuse durable account-local win evidence to rank untried owned decks after every weakness-matched counter has failed, while preserving the one-attempt-per-deck and no-spend guards.
- Ignore both runtime directories and local runtime symlinks so an operational checkout can safely reference retained evidence.

## 0.1.0 — 2026-08-30

First experimental public release.

- Local Android observation and control through screenshots, OCR, and guarded ADB input.
- Durable SQLite checkpoints, recoverable autonomous jobs, and a localhost control room.
- Owned-deck and no-spend safety policies with fail-closed state verification.
- Account, deck, card-inventory, discovery, strategy, and recovery test coverage.
- Agent-assisted porting guide for adapting the reference setup without weakening its guards.
