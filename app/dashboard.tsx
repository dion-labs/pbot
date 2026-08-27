"use client";
/* eslint-disable @next/next/no-img-element -- the source is a live local device frame */

import { useCallback, useEffect, useState } from "react";

type RunState = { status: string; objective: string; device_serial: string | null; updated_at: string };
type Metrics = { battles_total: number; battles_won: number; missions_total: number; missions_complete: number; attempts_total: number };
type EventItem = { id: number; occurred_at: string; level: string; message: string };
type QueueItem = { id: string; expansion: string; difficulty: string; name: string; missions_complete: number | null; missions_total: number | null; work_state?: string; reason?: string | null };
type ManagedJob = { id: string; status: string; message: string } | null;
type AutonomousRun = { id: string; status: string; checkpoint?: { phase: string; message: string } | null } | null;
type AccountProfile = { status: "not_scanned" | "scanning" | "ready" | "needs_attention"; deck_count: number; message: string };
type CardInventoryProfile = { status: "not_scanned" | "scanning" | "ready" | "needs_attention"; target_count: number; known_count: number; exact_recipe_count: number; message: string };
type RecipeBuildability = { recipe_id: string; status: "exact" | "blocked" | "unknown" };
type Snapshot = { state: RunState; metrics: Metrics; queue: QueueItem[]; events: EventItem[]; screenshot_available: boolean; job: ManagedJob; account_profile: AccountProfile; card_inventory_profile: CardInventoryProfile; recipe_buildability: RecipeBuildability[]; autonomous_run: AutonomousRun };

const API = process.env.NEXT_PUBLIC_PBOT_API_URL ?? "http://127.0.0.1:8765";
const empty: Snapshot = {
  state: { status: "offline", objective: "Connect an Android device", device_serial: null, updated_at: "" },
  metrics: { battles_total: 0, battles_won: 0, missions_total: 0, missions_complete: 0, attempts_total: 0 },
  queue: [], events: [], screenshot_available: false, job: null, autonomous_run: null,
  account_profile: { status: "not_scanned", deck_count: 0, message: "Scan the connected account before running pbot" },
  card_inventory_profile: { status: "not_scanned", target_count: 0, known_count: 0, exact_recipe_count: 0, message: "Scan shipped recipe cards before autonomous construction" },
  recipe_buildability: [],
};

function eventTone(level: string) {
  return level === "success" ? "ok" : level === "error" ? "bad" : level === "warning" ? "wait" : "info";
}

export function Dashboard() {
  const [snapshot, setSnapshot] = useState<Snapshot>(empty);
  const [reachable, setReachable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [screenUrl, setScreenUrl] = useState<string | null>(null);
  const [streamState, setStreamState] = useState<"idle" | "live" | "stalled">("idle");

  const load = useCallback(async () => {
    try {
      const response = await fetch(`${API}/api/status`, { cache: "no-store" });
      if (!response.ok) throw new Error("API unavailable");
      setSnapshot(await response.json());
      setReachable(true);
    } catch {
      setReachable(false);
    }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(load, 0);
    const timer = window.setInterval(load, 2500);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [load]);

  async function command(path: string, body?: object) {
    setBusy(true);
    try {
      const response = await fetch(`${API}${path}`, {
        method: "POST",
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) throw new Error("Command failed");
      await load();
    } finally {
      setBusy(false);
    }
  }

  const { state, metrics, queue, events } = snapshot;
  const missionPercent = metrics.missions_total ? Math.round(metrics.missions_complete / metrics.missions_total * 100) : 0;
  const connected = reachable && Boolean(state.device_serial);
  const runActive = snapshot.job?.status === "starting" || snapshot.job?.status === "running" || snapshot.job?.status === "stopping";
  const accountReady = snapshot.account_profile.status === "ready";
  const inventoryReady = snapshot.card_inventory_profile.status === "ready";
  const deckScanActive = runActive && snapshot.account_profile.status === "scanning";
  const cardScanActive = runActive && snapshot.card_inventory_profile.status === "scanning";
  const status = !reachable ? "API OFFLINE" : state.status.toUpperCase();

  useEffect(() => {
    if (!connected || !snapshot.screenshot_available) {
      return;
    }

    let stopped = false;
    let timer: number | undefined;
    let activeUrl: string | null = null;
    let controller: AbortController | null = null;

    const schedule = (delay: number) => {
      if (!stopped) timer = window.setTimeout(captureFrame, delay);
    };

    const captureFrame = async () => {
      if (document.hidden) {
        setStreamState("idle");
        schedule(1000);
        return;
      }

      controller = new AbortController();
      try {
        const response = await fetch(`${API}/api/device/screenshot?refresh=true&v=${Date.now()}`, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Screen capture unavailable");
        const nextUrl = URL.createObjectURL(await response.blob());
        if (stopped) {
          URL.revokeObjectURL(nextUrl);
          return;
        }
        if (activeUrl) URL.revokeObjectURL(activeUrl);
        activeUrl = nextUrl;
        setScreenUrl(nextUrl);
        setStreamState("live");
      } catch (error) {
        if (!stopped && !(error instanceof DOMException && error.name === "AbortError")) {
          setStreamState("stalled");
        }
      } finally {
        // Keep exactly one ADB capture in flight, then request the next frame promptly.
        schedule(150);
      }
    };

    captureFrame();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
      controller?.abort();
      if (activeUrl) URL.revokeObjectURL(activeUrl);
    };
  }, [connected, snapshot.screenshot_available]);

  const streamLabel = !connected
    ? "NO SIGNAL"
    : !snapshot.screenshot_available || streamState === "idle"
      ? "STANDBY"
      : streamState === "live"
        ? "STREAMING"
        : "RECONNECTING";

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand"><span className="brandMark">PB</span><div><p className="eyebrow">POCKET BOT</p><h1>Control room</h1></div></div>
        <div className={`runState ${connected ? "connected" : ""}`}><span /> {status}</div>
      </header>

      <section className="hero">
        <div><p className="eyebrow">CURRENT OBJECTIVE</p><h2>{state.objective}</h2><p className="lede">{connected ? !accountReady ? `Connected to ${state.device_serial}. ${snapshot.account_profile.message}. The scan is read-only and must finish before autonomous play.` : !inventoryReady ? `${snapshot.account_profile.deck_count} usable decks are verified. ${snapshot.card_inventory_profile.message}. Recipe preflight reads only the 44 stable card identities shipped with pbot.` : `Connected to ${state.device_serial}. ${snapshot.account_profile.deck_count} decks and ${snapshot.card_inventory_profile.known_count}/${snapshot.card_inventory_profile.target_count} recipe card identities are known; ${snapshot.card_inventory_profile.exact_recipe_count} shipped recipes are exact.` : "Connect and authorize an Android phone, then scan the account. Login or a secure unlock remains a human handoff."}</p></div>
        <div className="heroActions">
          <button className="primary" disabled={busy || !reachable || ((!accountReady || !inventoryReady) && !runActive)} onClick={() => command(runActive ? "/api/runs/current/stop" : "/api/runs", runActive ? undefined : {})}>{busy ? "Working…" : runActive ? deckScanActive || cardScanActive ? "Stop scan" : "Stop pbot" : !accountReady ? "Scan account first" : !inventoryReady ? "Scan recipe cards first" : "Run pbot"}</button>
          <button className="secondary active" disabled={!reachable || !runActive} onClick={() => command(state.status === "paused" ? "/api/control/resume" : "/api/control/pause")}>{state.status === "paused" ? "Resume" : "Pause"}</button>
          <button className="deviceCheck" disabled={busy || !connected || runActive} onClick={() => command("/api/account/bootstrap")}>{accountReady ? "Rescan account" : "Scan account"}</button>
          <button className="deviceCheck" disabled={busy || !connected || !accountReady || runActive} onClick={() => command("/api/account/cards")}>{inventoryReady ? "Rescan recipe cards" : "Scan recipe cards"}</button>
          <button className="deviceCheck" disabled={busy || !reachable || runActive} onClick={() => command("/api/device/check")}>Device check</button>
        </div>
      </section>

      <section className="metrics" aria-label="Progress summary">
        <article><p>Battles total</p><strong>{metrics.battles_total}</strong><span>{queue.length ? `${queue.length} currently actionable` : "Awaiting discovery"}</span></article>
        <article><p>First wins</p><strong>{metrics.battles_won}</strong><span>of {metrics.battles_total} discovered</span></article>
        <article><p>Missions</p><strong>{missionPercent}%</strong><span>{metrics.missions_complete} of {metrics.missions_total} complete</span></article>
        <article><p>Auto attempts</p><strong>{metrics.attempts_total}</strong><span>{metrics.attempts_total ? "Recorded attempts" : "No runs yet"}</span></article>
      </section>

      <section className="workspace">
        <article className="screenPanel panel">
          <div className="panelHead"><div><p className="eyebrow">DEVICE VIEW</p><h3>Live screen</h3></div><span className={`chip ${connected && streamState === "live" ? "live" : ""}`}>{streamLabel}</span></div>
          <div className="deviceStage">
            <div className="phone"><div className="phoneNotch" />
              {screenUrl && connected
                ? <img className="deviceImage" src={screenUrl} alt="Current Android device screen" />
                : <div className="emptyScreen"><span className="scanline" /><b>ADB</b><p>Waiting for device</p></div>}
            </div>
          </div>
        </article>

        <aside className="sideColumn">
          <article className="panel objectivePanel">
            <div className="panelHead"><div><p className="eyebrow">QUEUE</p><h3>Run plan</h3></div><span className="count">{queue.length}</span></div>
            {queue.length
              ? <ol className="queueList">{queue.map((item, index) => <li key={item.id}>
                  <span className="queueIndex">{String(index + 1).padStart(2, "0")}</span>
                  <div><strong>{item.name}</strong><p>{item.work_state === "deferred" ? item.reason : `${item.difficulty} · ${item.expansion}`}</p></div>
                  <span className={`queueTasks ${item.work_state === "deferred" ? "deferred" : ""}`}>{item.work_state === "deferred" ? "DEFER" : `${item.missions_complete ?? 0}/${item.missions_total ?? "?"}`}</span>
                </li>)}</ol>
              : <div className="emptyQueue"><span>01</span><p>Battle objectives will appear after discovery.</p></div>}
          </article>
          <article className="panel activityPanel">
            <div className="panelHead"><div><p className="eyebrow">EVENT LOG</p><h3>Recent activity</h3></div></div>
            {events.length ? <ol className="activityList">{events.slice(0, 8).map((item) => <li key={item.id}><span className={`dot ${eventTone(item.level)}`} /><time>{new Date(item.occurred_at).toLocaleTimeString([], { hour12: false })}</time><p>{item.message}</p></li>)}</ol>
              : <div className="emptyEvents"><p>{reachable ? "No events recorded yet." : "Start the local control service to see live events."}</p></div>}
          </article>
        </aside>
      </section>
      <footer>
        <span>pbot / local session</span>
        <span className="spendingLock">
          <button className="spendingLockTrigger" type="button" aria-describedby="spending-lock-tooltip">
            Spending lock: <b>ON</b><span className="spendingLockHelp" aria-hidden="true"><span>?</span></span>
          </button>
          <span className="spendingLockTooltip" id="spending-lock-tooltip" role="tooltip">
            pbot will not buy, craft, or spend currency, pack points, premium resources, or consumable account items. It only uses cards and decks you already own; this is a pbot safety policy, not an in-game setting.
          </span>
        </span>
      </footer>
    </main>
  );
}
