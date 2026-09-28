# pbot acceptance checkpoint — 2026-09-28

## Reconciled baseline

Started from clean `a855db65c1c91b50d2a100e73243853920e0e28a`. No intervening code or local edits since September 22. Current parent AGENTS and [product objective](AUTONOMOUS_RUN.md) were reread. Version 0.1.5 had been prepared but was unpublished; exact-head CI had passed. Historical screenshots remained, but temporary browser receipts had disappeared, so the exact archive and isolated browser checks were repeated.

## Completed milestones

- Published and downloaded-verified [v0.1.5](https://github.com/dion-labs/pbot/releases/tag/v0.1.5): recoverable dashboard actions, preserved focus, narrow layouts, delayed-status protection. Exact archive passed frozen installs, lint/build/render,177 Python tests, 17 Chrome cases and verified-empty owned-fixture cleanup. Chrome 153.0.8010.54; zero forbidden API dispatch and external page requests. npm/Python audits found no known vulnerabilities. Source SHA256 `ea9bfe6ec8ffbdf323ac9e07a44af7a405af4e4cec9f4b76e73410898a02de65`.
- Complete-queue regression: four fictional 501-row cases reproduced false completion/exhaustion or missing first-pass target behind the dashboard listing cap. Internal callers now inspect all pending rows while dashboard caps and safety budgets remain unchanged.27 affected tests and independent review cover the correction; the verified release receipt follows below.

The 13-case actual macOS inert-process receipt from v0.1.4 is reused only for unchanged lifecycle code. Fresh v0.1.5 browser evidence is reused for unchanged UI and bounded default Store queries. Neither receipt certifies new platform or hardware behavior.

Durable raw reports, traces, screenshots and logs are retained in the portfolio's `qa/token-burn-2026-09-28/pbot/evidence/`. No personal data was used as a fixture. Public source contains only deliberately retained fictional browser screenshots.

## Exact deferred acceptance

| Gate | Remaining evidence required |
|---|---|
| PB-004/029 | Coordinated disposable physical Android/account: exact owned-deck Battle Rules read-back, managed-slot reuse and unrelated-slot preservation. |
| PB-008/034/036 | USB/RSA authorization, disconnect/reconnect, device ambiguity and unseen layout/game-version handoff on a permitted device. |
| PB-033/035 | Physical pause/human handoff/resume, original awake-setting restoration and secure unlock by the human. |
| PB-047 | Account changes on the same hardware still require rescanning; serial equality is not account identity. |
| PB-012/031/038/041 | Other browser engines, actual mobile browsers, native zoom and assistive technology; current proof is isolated desktop Chrome with mobile-sized viewports. |
| PB-025 | Other kernels, descendants escaping process sessions and broader inaccessible-metadata/PID-reuse interleavings beyond documented same-group fixtures. |

No ADB, real gameplay/account/device mutation, live-session restart, website push or deployment occurred. Future recipes/layouts/mission behavior require permitted observations; synthetic tests do not supply that evidence.

## v0.1.6 published and downloaded-verified — 2026-09-28

Experimental release: https://github.com/dion-labs/pbot/releases/tag/v0.1.6
Source revision: `702bf24a0e13327875762c665ee949b6dc428a4e`.
Source: https://github.com/dion-labs/pbot/releases/download/v0.1.6/pbot-0.1.6.tar.gz
Checksums: https://github.com/dion-labs/pbot/releases/download/v0.1.6/SHA256SUMS
Downloaded bytes match the validated archive and published checksum: `583f988fe10fd17e6a8b5a267b7a61a0424875a04c86e32227c378a78a1fba7a`.

Exact clean archive passed frozen installs, lint/build/render and **181 Python tests**. Four-way package version agreement is 0.1.6. Four synthetic regressions reproduced the queue cap bugs before the fix; 27 affected tests passed afterward. Root independently reviewed the original three files and final first-pass caller, running the relevant tests. Exact-head CI verify and secrets passed: https://github.com/dion-labs/pbot/actions/runs/36466738582 . Release notes were retrieved and compared with the validated text. Existing releases remain immutable.

The unchanged UI retains today's 17-case isolated Chrome acceptance; unchanged process lifecycle retains the September 22 13-case macOS receipt. Dependency versions are unchanged and today's npm/Python audits found no known vulnerabilities. Physical/device/account/other-browser gates remain explicitly unrun. Source manifest excludes private runtime/environment/journal and symlinks. No ADB, real gameplay, account mutation, live-session restart or site deployment occurred.
