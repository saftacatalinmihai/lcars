// The phone half of the app: the form you fill in once.
//
// This page is what the Even App shows on the handset while the glasses show
// the containers from main.ts. It exists because the G2 has no keyboard, so a
// URL, a password and a set of quick-capture presets have to come from
// somewhere else.
//
// It also runs in a plain browser (`npm run dev`), where there is no bridge:
// storage then falls back to window.localStorage so the form and the LCARS
// client can be exercised without the hardware.

import {
  waitForEvenAppBridge,
  type EvenAppBridge,
} from "@evenrealities/even_hub_sdk";

import {
  DEFAULT_CONFIG,
  loadConfig,
  saveConfig,
  type AppConfig,
  type QuickCapture,
} from "./config";
import { LcarsClient } from "./lcars";

const BROWSER_KEY = "lcars.glasses.config";

/** In a browser there is no Even App to call, so fake the two storage methods
 *  the config module uses. Nothing else on the bridge is touched here. */
function browserBridge(): EvenAppBridge {
  return {
    getLocalStorage: async (k: string) => window.localStorage.getItem(k) ?? "",
    setLocalStorage: async (k: string, v: string) => {
      window.localStorage.setItem(k, v);
      return true;
    },
  } as unknown as EvenAppBridge;
}

async function getBridge(): Promise<EvenAppBridge> {
  if (typeof window !== "undefined" && "flutter_inappwebview" in window) {
    return waitForEvenAppBridge();
  }
  return browserBridge();
}

function el<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing element #${id}`);
  return node as T;
}

function parseQuickCaptures(text: string): QuickCapture[] {
  // One per line: label | kind | title | content. Deliberately not JSON - this
  // is typed on a phone keyboard.
  const out: QuickCapture[] = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const [label, kind, title, ...rest] = line.split("|").map((s) => s.trim());
    if (!label) continue;
    out.push({
      label,
      kind: kind || "personal_log",
      title: title || "",
      content: rest.join("|").trim(),
    });
  }
  return out;
}

function formatQuickCaptures(caps: QuickCapture[]): string {
  return caps
    .map((q) => [q.label, q.kind, q.title, q.content].join(" | "))
    .join("\n");
}

function status(message: string, ok: boolean): void {
  const node = el<HTMLParagraphElement>("status");
  node.textContent = message;
  node.className = ok ? "ok" : "err";
}

export async function mountSettings(): Promise<void> {
  if (!document.getElementById("settings")) return;
  const bridge = await getBridge();
  const config = await loadConfig(bridge);

  el<HTMLInputElement>("baseUrl").value = config.baseUrl;
  el<HTMLInputElement>("user").value = config.user;
  el<HTMLInputElement>("pass").value = config.pass;
  el<HTMLInputElement>("kind").value = config.kind;
  el<HTMLInputElement>("limit").value = String(config.limit);
  el<HTMLTextAreaElement>("quick").value = formatQuickCaptures(
    config.quickCaptures,
  );

  function read(): AppConfig {
    const limit = parseInt(el<HTMLInputElement>("limit").value, 10);
    return {
      baseUrl: el<HTMLInputElement>("baseUrl").value.trim(),
      user: el<HTMLInputElement>("user").value.trim(),
      pass: el<HTMLInputElement>("pass").value,
      kind: el<HTMLInputElement>("kind").value.trim(),
      limit: Number.isFinite(limit) && limit > 0 ? limit : DEFAULT_CONFIG.limit,
      quickCaptures: parseQuickCaptures(el<HTMLTextAreaElement>("quick").value),
    };
  }

  el<HTMLButtonElement>("save").addEventListener("click", () => {
    void (async () => {
      const next = read();
      const ok = await saveConfig(bridge, next);
      status(ok ? "Saved." : "Could not save.", ok);
    })();
  });

  el<HTMLButtonElement>("test").addEventListener("click", () => {
    void (async () => {
      const next = read();
      if (!next.baseUrl) {
        status("Enter the API URL first.", false);
        return;
      }
      status("Testing…", true);
      const client = new LcarsClient(next);
      try {
        // /kinds, not /health: health is unauthenticated by design and would
        // happily answer with the wrong password. This proves the credentials.
        const kinds = await client.kinds();
        const total = kinds.reduce((n, k) => n + k.count, 0);
        status(`OK - ${kinds.length} kinds, ${total} entries.`, true);
      } catch (e) {
        status(`Failed: ${(e as Error).message}`, false);
      }
    })();
  });
}

// Kept out of main.ts's WebView guard: the form is useful in both contexts.
if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => void mountSettings());
  } else {
    void mountSettings();
  }
}

export { BROWSER_KEY };
