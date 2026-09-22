/* Opt-in real Chrome checks; all application records and dispatch are fictional. */
import fs from "node:fs/promises";
import path from "node:path";
import http from "node:http";
import { pathToFileURL } from "node:url";
const { chromium, expect } = await import(pathToFileURL(path.join(process.env.PBOT_PLAYWRIGHT_MODULE, "index.mjs")).href);

const root = process.env.PBOT_BROWSER_EVIDENCE;
const api = `http://127.0.0.1:${process.env.PBOT_FIXTURE_API_PORT}`;
const ui = `http://127.0.0.1:${process.env.PBOT_FIXTURE_UI_PORT}`;
const hostile = `http://127.0.0.1:${process.env.PBOT_FIXTURE_HOSTILE_PORT}`;
const selected = new Set((process.env.PBOT_BROWSER_CASES || "").split(",").filter(Boolean));
const report = { cases: [], external_requests: [], started_at: new Date().toISOString() };
const allowed = new Set([api, ui, hostile]);
let browser;

async function fixture(endpoint, body) {
  const response = await fetch(`${api}/__fixture/${endpoint}`, {
    method: body ? "POST" : "GET",
    headers: { "x-fixture-id": process.env.PBOT_FIXTURE_ID, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`Fixture ${endpoint}: ${response.status} ${await response.text()}`);
  return response.json();
}

async function run(name, scenario, action, options = {}) {
  if (selected.size && !selected.has(name)) return;
  await fixture("reset", { scenario, ...options.fixture });
  const context = await browser.newContext({ viewport: { width: options.width || 1280, height: 900 }, reducedMotion: "reduce", serviceWorkers: options.opaqueFrame ? "allow" : "block" });
  const item = { name, scenario, width: options.width || 1280, errors: [], console_errors: [] };
  await context.route("**/*", async route => {
    const url = new URL(route.request().url());
    if (allowed.has(url.origin) || ["data:", "blob:"].includes(url.protocol)) return route.continue();
    report.external_requests.push({ case: name, url: url.href });
    return route.abort("blockedbyclient");
  });
  const page = await context.newPage();
  page.on("pageerror", error => item.errors.push(String(error)));
  page.on("console", message => { if (message.type() === "error") item.console_errors.push(message.text()); });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  try {
    await action(page, context);
    expect(item.errors, "No unhandled browser application errors").toEqual([]);
    item.status = "passed";
  } catch (error) {
    item.status = "failed";
    item.failure = String(error.stack || error);
  } finally {
    if (options.fixture?.delay) await page.waitForTimeout(options.fixture.delay * 1000 + 100);
    item.receipt = await fixture("receipt");
    if (item.receipt.forbidden.length) { item.status = "failed"; item.failure = "API attempted a forbidden subprocess"; }
    await page.screenshot({ path: path.join(root, `${name}.png`), fullPage: true }).catch(error => { item.screenshot_error = String(error); });
    await fs.writeFile(path.join(root, `${name}.html`), await page.content());
    await context.tracing.stop({ path: path.join(root, `${name}-trace.zip`) });
    await context.close();
    report.cases.push(item);
    await fs.writeFile(path.join(root, "browser-report.json"), JSON.stringify(report, null, 2));
    console.log(`${name}: ${item.status}${item.failure ? ` (${item.failure.split("\n")[0]})` : ""}`);
  }
}

for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, async () => {
  if (browser) await browser.close();
  process.exit(130);
});

async function open(page) {
  await page.goto(ui, { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { name: "Control room" })).toBeVisible();
  await expect(page.locator(".runState")).not.toContainText("API OFFLINE", { timeout: 8000 });
}

async function main() {
  browser = await chromium.launch({ executablePath: process.env.PBOT_CHROME, headless: true,
    args: ["--disable-background-networking", "--disable-component-update", "--no-first-run", "--disable-sync",
      `--proxy-server=${hostile}`, "--proxy-bypass-list=127.0.0.1;localhost",
      "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost", "--dns-prefetch-disable"] });
  report.browser_version = browser.version();

  await run("startup-empty-reconnect", "empty", async page => {
    await page.goto(ui, { waitUntil: "networkidle" });
    await expect(page.locator(".runState")).toHaveText("API OFFLINE");
    await expect(page.getByRole("button", { name: "Scan account first" })).toBeDisabled();
    await page.screenshot({ path: path.join(root, "startup-offline.png"), fullPage: true });
    await fixture("options", { status_error: false });
    await expect(page.locator(".runState")).toHaveText("OFFLINE", { timeout: 8000 });
    await expect(page.getByText("Battle objectives will appear after discovery.")).toBeVisible();
    await expect(page.getByText("No events recorded yet.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Device check" })).toBeEnabled();
  }, { fixture: { status_error: true } });

  await run("scan-disabled-stop", "unscanned", async page => {
    await open(page);
    await expect(page.getByRole("button", { name: "Scan account first" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Scan recipe cards", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Scan account", exact: true }).click();
    await expect(page.getByRole("button", { name: "Stop scan" })).toBeEnabled();
    await expect(page.getByRole("button", { name: "Scan account", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Stop scan" }).click();
    await expect(page.getByRole("heading", { name: "Fictional run stopped" })).toBeVisible();
    expect((await fixture("receipt")).dispatch.filter(x => x.kind.startsWith("controller.")).map(x => x.kind)).toEqual(["controller.start", "controller.stop"]);
  });

  await run("start-stop-confirmation", "ready", async page => {
    await open(page);
    await page.getByRole("button", { name: "Run pbot", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Fictional run started" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Rescan account" })).toBeDisabled();
    await page.getByRole("button", { name: "Stop pbot", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Fictional run stopped" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Run pbot", exact: true })).toBeEnabled();
    expect((await fixture("receipt")).dispatch.filter(x => x.kind.startsWith("controller.")).map(x => x.kind)).toEqual(["controller.start", "controller.stop"]);
  });

  await run("command-error-retry", "ready", async page => {
    await open(page);
    await page.getByRole("button", { name: "Run pbot", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("Fictional launch rejected", { timeout: 2500 });
    await expect(page.getByRole("button", { name: "Run pbot", exact: true })).toBeEnabled();
    await page.screenshot({ path: path.join(root, "command-error-visible.png"), fullPage: true });
    await fixture("options", { reject_start: false });
    await page.getByRole("button", { name: "Run pbot", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Fictional run started" })).toBeVisible();
    await expect(page.getByRole("alert")).toHaveCount(0);
  }, { fixture: { reject_start: true } });

  await run("pending-stop-disables-pause", "running", async page => {
    await open(page);
    await page.getByRole("button", { name: "Stop pbot", exact: true }).click();
    await expect(page.getByRole("button", { name: "Working…", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeDisabled({ timeout: 250 });
    await page.getByRole("button", { name: /Spending lock/ }).focus();
    await expect(page.getByRole("heading", { name: "Fictional run stopped" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Spending lock/ })).toBeFocused();
  }, { fixture: { delay: 1.0 } });

  await run("command-network-error-retry", "ready", async (page, context) => {
    await open(page);
    await context.route(`${api}/api/device/check`, route => route.abort("connectionrefused"), { times: 1 });
    await page.getByRole("button", { name: "Device check", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("Could not reach the local control service");
    await page.getByRole("button", { name: "Device check", exact: true }).click();
    await expect(page.getByRole("alert")).toHaveCount(0);
    expect((await fixture("receipt")).dispatch.filter(item => item.kind === "device.doctor")).toHaveLength(1);
  });

  await run("disconnected-ready-disables-run", "disconnected-ready", async page => {
    await open(page);
    await expect(page.getByRole("button", { name: "Run pbot", exact: true })).toBeDisabled({ timeout: 1000 });
    expect((await fixture("receipt")).dispatch).toEqual([]);
  });

  await run("disconnected-active-can-stop", "disconnected-running", async page => {
    await open(page);
    await expect(page.getByRole("button", { name: "Stop pbot", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Stop pbot", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Fictional run stopped" })).toBeVisible();
    expect((await fixture("receipt")).dispatch.filter(item => item.kind === "controller.stop")).toHaveLength(1);
  });

  await run("needs-attention-no-loop", "needs-attention", async page => {
    await open(page);
    await expect(page.getByRole("heading", { name: "No safe strategies remain for the fictional objective. Review the saved evidence." })).toBeVisible();
    await expect(page.locator(".runState")).toHaveText("NEEDS_ATTENTION");
    await page.waitForTimeout(2800); // Cross a real dashboard poll boundary.
    expect((await fixture("receipt")).dispatch).toEqual([]);
  });

  await run("late-status-cannot-undo-command", "ready", async page => {
    await open(page);
    await fixture("options", { status_delay_once: 1.5 });
    await expect.poll(async () => (await fixture("receipt")).held_status, { timeout: 6000 }).toBe(true);
    await page.getByRole("button", { name: "Run pbot", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Fictional run started" })).toBeVisible();
    await page.evaluate(() => {
      window.fixtureHeadings = [];
      window.fixtureObserver = new MutationObserver(() => window.fixtureHeadings.push(document.querySelector("h2").textContent));
      window.fixtureObserver.observe(document.querySelector("h2"), { childList: true, subtree: true, characterData: true });
    });
    await expect.poll(async () => (await fixture("receipt")).held_status).toBe(false);
    await page.waitForTimeout(200);
    const history = await page.evaluate(() => { window.fixtureObserver.disconnect(); return window.fixtureHeadings; });
    expect(history).not.toContain("Fictional device ready");
    await expect(page.getByRole("button", { name: "Stop pbot", exact: true })).toBeEnabled();
    expect((await fixture("receipt")).dispatch.filter(item => item.kind === "controller.start")).toHaveLength(1);
  });

  for (const width of [320, 375, 768, 1280]) {
    await run(`viewport-${width}`, "long-content", async page => {
      await open(page);
      const dimensions = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
      expect(Math.max(dimensions.document, dimensions.body), JSON.stringify(dimensions)).toBeLessThanOrEqual(width);
      const controls = await page.locator(".heroActions button").evaluateAll(nodes => nodes.map(node => { const r = node.getBoundingClientRect(); return { left: r.left, right: r.right }; }));
      for (const rect of controls) { expect(rect.left).toBeGreaterThanOrEqual(0); expect(rect.right).toBeLessThanOrEqual(width); }
      expect(await page.locator(".activityList p").first().evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
    }, { width });
  }

  await run("keyboard-focus-actions", "ready", async page => {
    await open(page);
    await page.keyboard.press("Tab");
    const runButton = page.getByRole("button", { name: "Run pbot", exact: true });
    await expect(runButton).toBeFocused();
    expect(await runButton.evaluate(node => { const s = getComputedStyle(node); return s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0 || s.boxShadow !== "none"; })).toBe(true);
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Fictional run started" })).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Paused by user" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Resume", exact: true })).toBeFocused();
  }, { width: 375 });

  await run("reduced-motion-tooltip", "ready", async page => {
    await open(page);
    await page.getByRole("button", { name: /Spending lock/ }).focus();
    const tooltip = page.getByRole("tooltip");
    await expect(tooltip).toHaveCSS("opacity", "1");
    expect(await tooltip.evaluate(node => getComputedStyle(node).transitionDuration.split(",").every(value => parseFloat(value) === 0))).toBe(true);
    await expect(tooltip).toContainText("will not buy, craft, or spend");
  }, { width: 375 });

  await run("browser-origin-and-host-rejection", "running", async page => {
    const before = await fixture("receipt");
    await page.goto(hostile);
    const opaque = await page.evaluate(async apiUrl => {
      const response = await fetch(`${apiUrl}/api/runs/current/stop`, { method: "POST", mode: "no-cors" });
      return { type: response.type, status: response.status };
    }, api);
    expect(opaque).toEqual({ type: "opaque", status: 0 });
    await page.evaluate(apiUrl => new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("Opaque-origin fixture timed out")), 5000);
      addEventListener("message", event => { if (event.data === "fixture-done") { clearTimeout(timeout); resolve(); } }, { once: true });
      const frame = document.createElement("iframe");
      frame.sandbox = "allow-scripts";
      frame.srcdoc = `<script>fetch(${JSON.stringify(apiUrl + "/api/runs/current/stop")},{method:'POST',mode:'no-cors'}).then(()=>parent.postMessage('fixture-done','*'))</script>`;
      document.body.append(frame);
    }), api);
    const badHost = await new Promise((resolve, reject) => {
      const request = http.request(`${api}/api/runs/current/stop`, { method: "POST", headers: { Host: "fictional-rebind.invalid" } }, response => { response.resume(); response.on("end", () => resolve(response.statusCode)); });
      request.on("error", reject); request.end();
    });
    expect(badHost).toBe(400);
    const after = await fixture("receipt");
    expect(after.store_sha256).toBe(before.store_sha256);
    expect(after.dispatch).toEqual([]);
    const requests = (await fs.readFile(path.join(root, "requests.jsonl"), "utf8")).trim().split("\n").map(line => JSON.parse(line));
    expect(requests.some(r => r.origin === hostile && r.status === 403)).toBe(true);
    expect(requests.some(r => r.origin === "null" && r.status === 403)).toBe(true);
    expect(requests.some(r => r.host === "fictional-rebind.invalid" && r.status === 400)).toBe(true);
    expect(page.context().serviceWorkers()).toEqual([]);
  }, { opaqueFrame: true });
}

main().catch(error => { report.fatal = String(error.stack || error); }).finally(async () => {
  if (browser) await browser.close();
  report.finished_at = new Date().toISOString();
  report.passed = !report.fatal && report.cases.length > 0 && report.cases.every(item => item.status === "passed") && report.external_requests.length === 0;
  await fs.writeFile(path.join(root, "browser-report.json"), JSON.stringify(report, null, 2));
  process.exitCode = report.passed ? 0 : 1;
});
