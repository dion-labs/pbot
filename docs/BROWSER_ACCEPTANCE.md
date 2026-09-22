# Isolated local browser acceptance

PB-012/031/038/041 use a disposable copy of the real dashboard and HTTP API.
The fixture must never import an API app before installing its fake device and
controller classes and setting temporary configuration. The actual Store,
request validation, Host/Origin middleware, handlers and rendered UI remain in
use. Fake dispatch records commands but never executes them; subprocess creation
inside the API process is forbidden. All records are fictional.

The trusted dashboard uses an unused port from the production Origin allowlist
(3001 or 3000). The API prefers 18731. A second HTTP origin prefers 5186 and is
intentionally untrusted. This avoids weakening Origin enforcement just to make
a nonstandard dashboard port work. Ports are checked before any server starts.

The opt-in harness copies tracked source (or an explicit code/configuration
allowlist from a source archive), excluding environment files, runtime data and
logs. Symlinked source paths are rejected. It builds in that temporary tree and
uses installed Playwright and headless Chrome with a fresh profile. Page
requests are limited to the three owned loopback origins; Chrome's external
HTTP(S) requests use a local proxy that rejects them, with background networking
and external DNS resolution disabled. The hostile page is served locally;
opaque-origin requests come from a sandboxed frame. Host-header checks use an
owned HTTP client because browsers do not let scripts set Host.

Screenshots, browser errors, dispatch receipts, source hashes and per-case
results are retained in the printed evidence directory. Exact owned fixture
processes are stopped and checked at the end of every invocation, including
failed assertions. Missing identity metadata is not proof of termination; an
unknown process keeps cleanup unconfirmed and is not signalled. Fresh parent
identity and the child's current parent relation must agree before adoption.
Production services, browsers and hardware are untouched.

## Running the opt-in harness

Use an installed checkout (`npm ci` and `uv sync --frozen`) and an existing
Playwright installation. The default resolves the sibling showcase's shared
`@playwright/test`; pass its absolute path when using another installation:

```bash
uv run python scripts/check_browser_acceptance.py --run \
  --playwright /path/to/node_modules/@playwright/test
```

The default Chrome path is `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`;
override it with `--chrome`. Dependency cloning and PID inspection currently
target macOS. The command creates its own temporary evidence directory and
prints the path. Without `--run`, it starts nothing. Use repeated `--case NAME`
for targeted follow-ups. Portfolio runs must use the shared resource wrapper.
This harness is intentionally separate from `npm test`.

## Browser cases

| Stable gate | Case | Expected behavior |
|---|---|---|
| PB-012.01 | startup-empty-reconnect | Offline controls stay disabled; polling recovers to a real empty Store without a reload. |
| PB-012.02 | scan-disabled-stop | Missing scans disable run/card actions; a fake account scan exposes Stop scan and disables another scan. |
| PB-012.03 | start-stop-confirmation | One fake dispatch per action; the objective and primary control confirm start and stop. |
| PB-012.04 | command-error-retry | Server detail is visible in an alert; retry succeeds with no unhandled browser error. |
| PB-012.05 | pending-stop-disables-pause | Pause is unavailable while Stop is pending; completion does not steal deliberately moved focus. |
| PB-012.06 | command-network-error-retry | A failed command transport is visible and retry reaches only the fake adapter. |
| PB-012.07 | disconnected-ready-disables-run | Old ready scans cannot enable Run while disconnected. |
| PB-012.08 | disconnected-active-can-stop | Losing the device does not prevent stopping an already-active job. |
| PB-012.09 | late-status-cannot-undo-command | A held old HTTP snapshot cannot overwrite a later confirmed command state. |
| PB-031.01 | needs-attention-no-loop | The specific fictional handoff reason remains visible across polling; no automatic dispatch occurs. |
| PB-041.01–04 | viewport-320/375/768/1280 | Controls stay within the viewport and long activity text remains readable. |
| PB-041.05 | keyboard-focus-actions | Keyboard start/pause works with visible focus retained through the pending state. |
| PB-041.06 | reduced-motion-tooltip | The keyboard-accessible spending policy remains readable without the tooltip transition. |
| PB-038.01 | browser-origin-and-host-rejection | Actual hostile and opaque browser origins receive 403; raw invalid Host receives 400; Store digest and dispatch remain unchanged. |

This proves only synthetic desktop-Chrome UI behavior, including mobile-sized
viewports. It does not prove physical phones, Safari, real Android/ADB adapters,
account/deck correctness or live production sessions.
