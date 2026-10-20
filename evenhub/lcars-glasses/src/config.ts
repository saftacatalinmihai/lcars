// Settings, kept on the phone.
//
// Everything here is typed on the phone and read on the glasses. That split is
// forced: the G2 has no keyboard and the SDK's mic hands back raw PCM, not
// text (AudioEvent.audioPcm), so there is no way to enter a URL or a password
// from the glasses at all.
//
// Storage goes through the Even App bridge rather than window.localStorage so
// the values survive however the host chooses to host the WebView.

import type { EvenAppBridge } from "@evenrealities/even_hub_sdk";

import { MAX_LIST_ITEMS } from "./glasses";

const STORAGE_KEY = "lcars.glasses.config";

/** A one-tap entry the glasses can create without any text input. */
export interface QuickCapture {
  label: string; // shown in the glasses list, keep it short
  kind: string;
  title: string;
  content: string;
}

export interface AppConfig {
  baseUrl: string;
  user: string;
  pass: string;
  /** Kind the list opens on. Empty means every kind. */
  kind: string;
  /**
   * Entries per page. The glasses reject a list container with more than 20
   * items, so this is a hard ceiling rather than a preference - browsing
   * further happens by paging, not by fetching more at once.
   */
  limit: number;
  quickCaptures: QuickCapture[];
}

export const DEFAULT_CONFIG: AppConfig = {
  // No default host on purpose. Whatever goes here must also appear in
  // app.json's network permission whitelist, or the WebView blocks the
  // request before it is made - see the README.
  baseUrl: "",
  user: "",
  pass: "",
  // The roles' defaults (docs/design/kinds.md): the log and the task kind.
  // A journal that maps them elsewhere is read at start (kindRoles), and
  // dictation saves to its log kind when no kind is picked.
  kind: "personal_log",
  limit: 20,
  quickCaptures: [
    { label: "Log now", kind: "personal_log", title: "", content: "" },
    { label: "New task", kind: "task", title: "Task", content: "" },
  ],
};

function coerce(raw: unknown): AppConfig {
  const o = (raw ?? {}) as Partial<AppConfig>;
  const limit =
    typeof o.limit === "number" && o.limit > 0
      ? Math.min(Math.floor(o.limit), MAX_LIST_ITEMS)
      : DEFAULT_CONFIG.limit;
  return {
    baseUrl: typeof o.baseUrl === "string" ? o.baseUrl.trim() : "",
    user: typeof o.user === "string" ? o.user : "",
    pass: typeof o.pass === "string" ? o.pass : "",
    kind: typeof o.kind === "string" ? o.kind : DEFAULT_CONFIG.kind,
    limit,
    quickCaptures: Array.isArray(o.quickCaptures)
      ? o.quickCaptures.filter(
          (q): q is QuickCapture =>
            !!q && typeof q.label === "string" && typeof q.kind === "string",
        )
      : DEFAULT_CONFIG.quickCaptures,
  };
}

/**
 * Query-string overrides, layered on top of whatever is stored.
 *
 * `?api=…&user=…&pass=…&kind=…`, the same shape the LCARS web build accepts
 * (see ARCHITECTURE.md, "Two backends, one entry layer"). This is how the app
 * gets configured in the Even Hub simulator, which loads a URL and has no way
 * to type into the phone form - and it is how you point a dev build at a
 * scratch server without touching your real settings.
 *
 * Nothing is persisted from here: an override lasts as long as the URL does.
 */
function applyUrlOverrides(config: AppConfig): AppConfig {
  if (typeof window === "undefined" || !window.location?.search) return config;
  const q = new URLSearchParams(window.location.search);
  const next = { ...config };
  const api = q.get("api");
  const user = q.get("user");
  const pass = q.get("pass");
  const kind = q.get("kind");
  const limit = q.get("limit");
  if (api !== null) next.baseUrl = api.trim();
  if (user !== null) next.user = user;
  if (pass !== null) next.pass = pass;
  if (kind !== null) next.kind = kind;
  if (limit !== null) {
    const n = parseInt(limit, 10);
    if (Number.isFinite(n) && n > 0) next.limit = Math.min(n, MAX_LIST_ITEMS);
  }
  return next;
}

export async function loadConfig(bridge: EvenAppBridge): Promise<AppConfig> {
  try {
    const raw = await bridge.getLocalStorage(STORAGE_KEY);
    if (!raw) return applyUrlOverrides({ ...DEFAULT_CONFIG });
    return applyUrlOverrides(coerce(JSON.parse(raw)));
  } catch {
    // A corrupt blob must not brick the app on a device with no keyboard.
    return applyUrlOverrides({ ...DEFAULT_CONFIG });
  }
}

export async function saveConfig(
  bridge: EvenAppBridge,
  config: AppConfig,
): Promise<boolean> {
  return bridge.setLocalStorage(STORAGE_KEY, JSON.stringify(config));
}

export function isConfigured(config: AppConfig): boolean {
  return config.baseUrl.length > 0 && config.user.length > 0;
}
