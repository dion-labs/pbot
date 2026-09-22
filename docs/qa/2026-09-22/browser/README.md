# Synthetic browser screenshots — 2026-09-22

All records, device labels, decks and errors shown here are fictional. These
images come from the actual pbot UI and HTTP app with fake dispatch; no Android
screen, real account, production database or existing browser profile was used.

- [320px baseline overflow](before-320.png): the viewport was 320px but content extended to 428px.
- [320px corrected layout](after-320.png) and [375px corrected layout](after-375.png): controls wrap and long activity content stays readable.
- [Command rejection](command-error.png): the API error is visible and the action can be retried.
- [Keyboard focus](keyboard-focus.png): focus remains on Resume after keyboard Pause completes.

Corrected capture source: `pbot-browser-acceptance-3kutdi48`, 17/17 cases passed,
cleanup verified-empty with no uncertain candidates. The final archive receipt
and exact remaining acceptance gates are in [the burn ledger](../../../TOKEN_BURN_2026-09-22.md).
These are desktop Chrome viewport simulations, not physical mobile acceptance.
