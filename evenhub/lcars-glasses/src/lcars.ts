// The LCARS HTTP API, as much of it as a pair of glasses needs.
//
// Every route here already exists and is documented in ARCHITECTURE.md ("HTTP
// API"); nothing on the server side was added for this app. The mapping is:
//
//   C  POST   /entries
//   R  GET    /entries?...     (list, bodies omitted)
//      GET    /entries/<id>    (one entry, with its content)
//   U  PATCH  /entries/<id>    (only the fields the body names)
//   D  DELETE /entries/<id>    (soft delete; the row survives)
//
// Deletes are soft on purpose and there is deliberately no hard-delete route,
// so nothing this app can do from a wrist flick is unrecoverable.

export interface LcarsEntry {
  id: number;
  kind: string;
  title: string;
  content?: string;
  content_length: number;
  done_bool: number;
  deleted: number;
  created_at_utc: string;
  last_modified_at_utc: string;
}

/**
 * What the write routes actually answer: an acknowledgement, not the row.
 * POST gives {status,id}, PUT/PATCH {status,id,updated}, DELETE {status,id}.
 * Nothing returns the updated entry, so a caller that needs the new state has
 * to re-read it - or, as this app does, apply the change to its own copy.
 */
export interface LcarsWriteAck {
  status: string;
  id: number;
  updated?: number;
}

export interface LcarsKind {
  kind: string;
  count: number;
  last_modified_at_utc: string;
}

export interface LcarsConfig {
  baseUrl: string;
  user: string;
  pass: string;
}

export class LcarsError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "LcarsError";
    this.status = status;
  }
}

export class LcarsClient {
  private readonly base: string;
  private readonly auth: string;

  constructor(config: LcarsConfig) {
    // Trailing slashes would produce "//entries", which the server's exact
    // path match does not recognise.
    this.base = config.baseUrl.replace(/\/+$/, "");
    this.auth = "Basic " + btoa(`${config.user}:${config.pass}`);
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const headers: Record<string, string> = { Authorization: this.auth };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }

    let res: Response;
    try {
      res = await fetch(this.base + path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: "no-store",
      });
    } catch (e) {
      // The three ways this fails in a WebView, none of which reach the
      // server: the host is not in app.json's network whitelist, the page is
      // https and the API is http (mixed content), or the tailnet is down.
      throw new LcarsError(`unreachable: ${(e as Error).message}`, 0);
    }

    if (res.status === 401 || res.status === 403) {
      throw new LcarsError("auth rejected", res.status);
    }
    if (!res.ok) {
      // The API answers errors as {"error":...,"status":...}; fall back to the
      // status line when the body is not that shape.
      let detail = `HTTP ${res.status}`;
      try {
        const j = (await res.json()) as { error?: string };
        if (j && typeof j.error === "string") detail = j.error;
      } catch {
        /* keep the status line */
      }
      throw new LcarsError(detail, res.status);
    }
    if (res.status === 204) {
      return undefined as T;
    }
    return (await res.json()) as T;
  }

  /** Liveness only - /health is the one unauthenticated route. */
  async health(): Promise<boolean> {
    try {
      const res = await fetch(this.base + "/health", { cache: "no-store" });
      return res.ok;
    } catch {
      return false;
    }
  }

  /**
   * Entry titles for one kind, newest first.
   *
   * content=0 is not an optimisation, it is a requirement: the server builds
   * each response inside a 1MB per-connection arena, and a page of entries
   * *with* bodies 500s on a real journal. The list never shows content anyway.
   */
  async list(kind: string, limit: number, offset = 0): Promise<LcarsEntry[]> {
    const q = new URLSearchParams({
      content: "0",
      limit: String(limit),
      offset: String(offset),
      order: "id",
      dir: "desc",
    });
    if (kind) q.set("kind", kind);
    return this.request<LcarsEntry[]>("GET", `/entries?${q.toString()}`);
  }

  /** One entry, content included. */
  async get(id: number): Promise<LcarsEntry> {
    return this.request<LcarsEntry>("GET", `/entries/${id}`);
  }

  async kinds(): Promise<LcarsKind[]> {
    return this.request<LcarsKind[]>("GET", "/kinds");
  }

  /**
   * The journal's kind for each role (GET /kinds/roles, docs/design/kinds.md):
   * role -> kind, e.g. {log: "personal_log", task: "task"}. Empty when the
   * server is older than the route or does not answer - the caller keeps its
   * defaults then, so a glasses app never stops for it.
   */
  async kindRoles(): Promise<Record<string, string>> {
    try {
      const j = await this.request<{ roles?: { role?: string; kind?: string }[] }>("GET", "/kinds/roles");
      const out: Record<string, string> = {};
      for (const r of j.roles ?? []) if (r && r.role && r.kind) out[r.role] = r.kind.split(",")[0];
      return out;
    } catch {
      return {};
    }
  }

  /**
   * Speech to text, through the LCARS server, which relays the audio to
   * Deepgram with its own key.
   *
   * `pcm` must be 16 kHz, mono, signed 16-bit little-endian. That is what the
   * glasses microphone emits and what the server tells Deepgram, so nothing
   * resamples at either end. The server caps a request body at 512KB, i.e.
   * about 16 seconds - see MAX_RECORD_MS in main.ts, which stops before that.
   */
  async transcribe(pcm: Uint8Array): Promise<string> {
    let res: Response;
    try {
      res = await fetch(this.base + "/transcribe", {
        method: "POST",
        headers: { Authorization: this.auth, "Content-Type": "audio/l16" },
        body: pcm as BodyInit,
        cache: "no-store",
      });
    } catch (e) {
      throw new LcarsError(`unreachable: ${(e as Error).message}`, 0);
    }
    if (res.status === 401 || res.status === 403) {
      throw new LcarsError("auth rejected", res.status);
    }
    if (res.status === 503) {
      throw new LcarsError("no transcription on the server", 503);
    }
    if (res.status === 413) {
      throw new LcarsError("recording too long", 413);
    }
    if (!res.ok) {
      throw new LcarsError(`HTTP ${res.status}`, res.status);
    }
    const j = (await res.json()) as { text?: string };
    return typeof j.text === "string" ? j.text : "";
  }

  /** Returns the new entry's id. The row itself has to be read back. */
  async create(kind: string, title: string, content: string): Promise<number> {
    const ack = await this.request<LcarsWriteAck>("POST", "/entries", {
      kind,
      title,
      content,
    });
    return ack.id;
  }

  /**
   * PATCH rather than PUT: both are partial updates server-side, but PATCH is
   * what this is. Only the named fields are touched, so toggling `done` cannot
   * blank a title.
   */
  async update(
    id: number,
    fields: Partial<Pick<LcarsEntry, "title" | "content" | "done_bool" | "deleted">>,
  ): Promise<LcarsWriteAck> {
    return this.request<LcarsWriteAck>("PATCH", `/entries/${id}`, fields);
  }

  async setDone(id: number, done: boolean): Promise<LcarsWriteAck> {
    return this.update(id, { done_bool: done ? 1 : 0 });
  }

  /** Soft delete. `restore` is the undo, and it is why this is safe here. */
  async remove(id: number): Promise<void> {
    await this.request<void>("DELETE", `/entries/${id}`);
  }

  async restore(id: number): Promise<LcarsWriteAck> {
    return this.update(id, { deleted: 0 });
  }
}
