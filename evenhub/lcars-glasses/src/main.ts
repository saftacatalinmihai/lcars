// LCARS on the G2: browse, read, create, complete and delete journal entries
// from the glasses, with the phone used only for setup.
//
// The whole app is a small state machine over a handful of screens. Input is
// deliberately narrow, because the input devices are: a list you scroll and
// click (R1 ring, or the temple touchpad), and a contextual menu of at most
// ten named actions. There is no keyboard, so text arrives one of two ways -
// a quick-capture preset defined on the phone, or dictation through the LCARS
// server's own speech recogniser (POST /transcribe).

import {
  AudioInputSource,
  OsEventTypeList,
  waitForEvenAppBridge,
  type EvenAppBridge,
  type EvenHubEvent,
} from "@evenrealities/even_hub_sdk";

import { loadConfig, isConfigured, type AppConfig } from "./config";
import { LcarsClient, LcarsError, type LcarsEntry } from "./lcars";
import { GlassesUI, paginate, truncate } from "./glasses";

type Screen =
  | "list"
  | "detail"
  | "kinds"
  | "quick"
  | "record"
  | "confirm"
  | "message";

/**
 * How long dictation may run before it stops itself.
 *
 * The server takes the audio as one request body, capped at 512KB, and the
 * glasses produce 32,000 bytes a second (16 kHz x 2 bytes). That is 16.3
 * seconds; stopping at 15 leaves room and turns "your note was rejected" into
 * "your note ended". A voice note, not a dictation session.
 */
const MAX_RECORD_MS = 15_000;

/**
 * Hard ceiling on a recording, in bytes.
 *
 * MAX_RECORD_MS alone is not enough, because it assumes audio arrives at real
 * time. Nothing guarantees that: a capture source that is not rate-limited
 * delivers as fast as it is read, and the Even Hub simulator's `alsa:null`
 * device does exactly that - 8 seconds of wall clock produced 6MB, twenty-two
 * times real time, and the request came back 413 with the note lost.
 *
 * A byte cap holds whatever the source does. Sized just under the server's
 * 512KB body limit so the recording ends on our terms, with a transcript,
 * rather than on the server's, with an error.
 */
const MAX_AUDIO_BYTES = 500_000;

/** `?debug=1` turns on event tracing to the webview console. Off by default so
 *  the glasses' console is not a firehose during normal use. */
const DEBUG =
  typeof window !== "undefined" &&
  new URLSearchParams(window.location.search).get("debug") === "1";

// Menu item IDs. Non-zero and unique within a page, which is all the SDK
// requires; reusing the same number for the same verb across pages keeps the
// dispatch below readable.
const A_BACK = 1;
const A_NEW = 2;
const A_PAGE = 2;
const A_KIND = 3;
const A_REFRESH = 4;
const A_DONE = 5;
const A_DELETE = 6;
const A_EXIT = 7;
const A_MORE = 8;
const A_TOP = 9;
const A_DICTATE = 10;
const A_STOP = 1;
const A_SAVE = 1;
const A_RETRY = 2;

class App {
  private readonly ui: GlassesUI;
  private client: LcarsClient | null = null;
  private config!: AppConfig;

  private screen: Screen = "message";
  private entries: LcarsEntry[] = [];
  private kinds: string[] = [];
  private selected = 0;
  private current: LcarsEntry | null = null;
  private pages: string[] = [];
  private page = 0;
  // Offset of the first row on screen. The glasses cap a list at 20 items, so
  // a journal is browsed a window at a time rather than scrolled.
  private offset = 0;
  private hasMore = false;
  // Set while a request is in flight, so a double-click on a slow link cannot
  // fire the same delete twice.
  private busy = false;

  // Dictation. The chunks are 100ms of PCM each, straight off the glasses
  // microphone, accumulated until the user (or MAX_RECORD_MS) stops it.
  private audioChunks: Uint8Array[] = [];
  private audioBytes = 0;
  private recording = false;
  private recordTimer: ReturnType<typeof setTimeout> | null = null;
  private transcript = "";
  // the journal's log kind (GET /kinds/roles), where nothing else names one
  private logKind = "personal_log";

  constructor(private readonly bridge: EvenAppBridge) {
    this.ui = new GlassesUI(bridge);
  }

  async start(): Promise<void> {
    this.config = await loadConfig(this.bridge);
    this.bridge.onEvenHubEvent((e) => {
      void this.onEvent(e);
    });

    if (!isConfigured(this.config)) {
      await this.message(
        "LCARS not configured",
        "Open this app on your phone and enter the API URL, user and password.",
      );
      return;
    }
    this.client = new LcarsClient(this.config);
    const roles = await this.client.kindRoles();
    if (roles.log) this.logKind = roles.log;
    await this.openList();
  }

  // --- screens -------------------------------------------------------------

  private async message(header: string, body: string): Promise<void> {
    this.screen = "message";
    await this.ui.showText({
      header,
      body,
      footer: "",
      actions: [{ id: A_EXIT, label: "Close" }],
    });
  }

  private async openList(resetOffset = true): Promise<void> {
    if (!this.client) return;
    this.screen = "list";
    if (resetOffset) this.offset = 0;
    await this.ui.showList({
      header: this.listHeader("loading…"),
      items: ["…"],
      footer: "",
      actions: this.listActions(),
    });

    try {
      // One extra row is fetched purely to answer "is there a next page?"
      // without a second request; it is never displayed.
      const page = await this.client.list(
        this.config.kind,
        this.config.limit + 1,
        this.offset,
      );
      this.hasMore = page.length > this.config.limit;
      this.entries = page.slice(0, this.config.limit);
    } catch (e) {
      await this.fail(e);
      return;
    }
    this.selected = 0;
    await this.renderList();
  }

  private async renderList(): Promise<void> {
    const items = this.entries.map((e) => this.listLabel(e));
    await this.ui.showList({
      header: this.listHeader(this.listRange()),
      items: items.length > 0 ? items : ["(no entries)"],
      // Not the selected entry: the highlight is invisible to the app (see
      // onEvent). A static hint is honest; a stale row id would not be.
      footer: this.listFooter(),
      actions: this.listActions(),
    });
  }

  private listFooter(): string {
    if (this.entries.length === 0) return "nothing here · menu to change kind";
    return "click to open · hold to go back";
  }

  private listHeader(suffix: string): string {
    const kind = this.config.kind || "all kinds";
    return `LCARS · ${kind} · ${suffix}`;
  }

  /** "1-20+" - which window of the journal is on screen. */
  private listRange(): string {
    if (this.entries.length === 0) return "0";
    const first = this.offset + 1;
    const last = this.offset + this.entries.length;
    return `${first}-${last}${this.hasMore ? "+" : ""}`;
  }

  private listLabel(e: LcarsEntry): string {
    // A task's state is the thing you want to see at a glance; everything else
    // leads with its title.
    const mark = e.kind === "task" ? (e.done_bool ? "[x] " : "[ ] ") : "";
    const title = e.title && e.title !== "HTTP Entry" ? e.title : e.created_at_utc;
    return `${mark}${title}`;
  }

  /**
   * Deliberately carries no Open / Done / Delete.
   *
   * Those would have to act on "the highlighted row", and the app cannot know
   * which row that is: the glasses report a selection index only when
   * something is clicked, never while the highlight moves. A Delete driven
   * from a stale index deletes whatever was clicked last, which is not what
   * anyone pointed at. So per-entry verbs live on the detail screen, where the
   * entry is unambiguous because you opened it.
   */
  private listActions() {
    const actions = [
      { id: A_DICTATE, label: "Dictate" },
      { id: A_NEW, label: "New" },
      { id: A_KIND, label: "Kind" },
      { id: A_REFRESH, label: "Refresh" },
    ];
    // Only offered when they lead somewhere - the menu caps at 10 items, and a
    // dead "Older" is worse than no "Older".
    if (this.hasMore) actions.push({ id: A_MORE, label: "Older" });
    if (this.offset > 0) actions.push({ id: A_TOP, label: "Newest" });
    actions.push({ id: A_EXIT, label: "Exit" });
    return actions;
  }

  private async openDetail(entry: LcarsEntry): Promise<void> {
    if (!this.client) return;
    this.screen = "detail";
    try {
      // The list was fetched with content=0, so the body has to be read now.
      this.current = await this.client.get(entry.id);
    } catch (e) {
      await this.fail(e);
      return;
    }
    this.pages = paginate(this.current.content ?? "");
    this.page = 0;
    await this.renderDetail();
  }

  private async renderDetail(): Promise<void> {
    const e = this.current;
    if (!e) return;
    await this.ui.showText({
      header: truncate(e.title || `#${e.id}`, 44),
      body: this.pages[this.page] ?? "",
      footer: `${this.page + 1}/${this.pages.length} · ${e.last_modified_at_utc}`,
      actions: [
        { id: A_BACK, label: "Back" },
        { id: A_PAGE, label: "Page" },
        { id: A_DONE, label: e.done_bool ? "Mark undone" : "Mark done" },
        { id: A_DELETE, label: "Delete" },
      ],
    });
  }

  private async openKinds(): Promise<void> {
    if (!this.client) return;
    this.screen = "kinds";
    try {
      const list = await this.client.kinds();
      // "" first: the all-kinds view, which the API expresses as no filter.
      this.kinds = ["", ...list.map((k) => k.kind)];
    } catch (e) {
      await this.fail(e);
      return;
    }
    this.selected = 0;
    await this.ui.showList({
      header: "Kind",
      items: this.kinds.map((k) => k || "(all kinds)"),
      footer: "click to filter",
      actions: [{ id: A_BACK, label: "Back" }],
    });
  }

  private async openQuick(): Promise<void> {
    this.screen = "quick";
    this.selected = 0;
    const caps = this.config.quickCaptures;
    await this.ui.showList({
      header: "New entry",
      items:
        caps.length > 0
          ? caps.map((q) => q.label)
          : ["(none - add some on the phone)"],
      footer: "click to create",
      actions: [{ id: A_BACK, label: "Back" }],
    });
  }

  // --- dictation -----------------------------------------------------------

  /**
   * Record, transcribe, confirm, save.
   *
   * The confirm step is not politeness: speech recognition is wrong sometimes,
   * and an entry you cannot edit from the glasses is one you would have to fix
   * somewhere else. Seeing the text before it is written is the whole
   * difference between this being useful and being a source of junk entries.
   */
  private async startDictation(): Promise<void> {
    if (!this.client) return;
    this.screen = "record";
    this.audioChunks = [];
    this.audioBytes = 0;
    this.transcript = "";

    await this.ui.showText({
      header: "Dictate",
      body: "● Recording\n\nClick to stop.",
      footer: `stops itself after ${MAX_RECORD_MS / 1000}s`,
      actions: [
        { id: A_STOP, label: "Stop" },
        { id: A_EXIT, label: "Cancel" },
      ],
    });

    const started = await this.bridge.audioControl(true, AudioInputSource.Glasses);
    if (!started) {
      await this.message("Dictate", "The microphone could not be opened.");
      return;
    }
    this.recording = true;
    this.recordTimer = setTimeout(() => {
      void this.stopDictation();
    }, MAX_RECORD_MS);
  }

  private async stopDictation(): Promise<void> {
    if (!this.recording || !this.client) return;
    this.recording = false;
    if (this.recordTimer !== null) {
      clearTimeout(this.recordTimer);
      this.recordTimer = null;
    }
    await this.bridge.audioControl(false);

    if (this.audioBytes === 0) {
      await this.message("Dictate", "No audio was captured.");
      return;
    }

    if (DEBUG) {
      console.log(
        "[lcars] captured",
        JSON.stringify({
          bytes: this.audioBytes,
          chunks: this.audioChunks.length,
          seconds: +(this.audioBytes / 32000).toFixed(2),
        }),
      );
    }
    await this.ui.showText({
      header: "Dictate",
      body: "Transcribing…",
      footer: `${(this.audioBytes / 32000).toFixed(1)}s of audio`,
      actions: [],
    });

    // One flat buffer: the chunks arrive as 100ms fragments and the server
    // wants a single body.
    const pcm = new Uint8Array(this.audioBytes);
    let at = 0;
    for (const chunk of this.audioChunks) {
      pcm.set(chunk, at);
      at += chunk.length;
    }
    this.audioChunks = [];

    try {
      this.transcript = await this.client.transcribe(pcm);
    } catch (e) {
      await this.fail(e);
      return;
    }
    if (this.transcript.trim() === "") {
      await this.message("Dictate", "Nothing was recognised. Try again.");
      return;
    }
    await this.showConfirm();
  }

  private async showConfirm(): Promise<void> {
    this.screen = "confirm";
    this.pages = paginate(this.transcript);
    this.page = 0;
    await this.ui.showText({
      header: `Save to ${this.config.kind || this.logKind}?`,
      body: this.pages[0] ?? "",
      footer: `${this.transcript.length} chars`,
      actions: [
        { id: A_SAVE, label: "Save" },
        { id: A_RETRY, label: "Again" },
        { id: A_EXIT, label: "Discard" },
      ],
    });
  }

  // --- events --------------------------------------------------------------

  private async onEvent(event: EvenHubEvent): Promise<void> {
    // Audio events arrive ten times a second; tracing them drowns everything
    // else in the console and tells you nothing a byte count would not.
    if (DEBUG && !event.audioEvent) {
      // Goes to the webview console, which the Even Hub simulator exposes at
      // GET /api/console - the only way to see what the glasses actually sent.
      console.log(
        "[lcars]",
        JSON.stringify({
          screen: this.screen,
          listIdx: event.listEvent?.currentSelectItemIndex,
          menu: event.menuItemClickEvent?.itemID,
          sys: event.sysEvent?.eventType,
        }),
      );
    }
    // A listEvent *is* the click. Two things about the real event stream make
    // this the only correct reading, and neither is obvious from the docs:
    //
    //   - Scrolling emits nothing. up/down move the highlight inside the
    //     firmware and the app is never told, so there is no way to track the
    //     cursor between clicks - only to learn where it was when one landed.
    //   - A click carries no eventType. CLICK_EVENT is 0 and the zero value is
    //     omitted on the wire, so `eventType === CLICK_EVENT` is never true.
    //     The field only appears for values that are not 0.
    //
    // Checking for the index rather than the type is what makes this work on
    // hardware; checking the type silently does nothing at all.
    if (event.listEvent) {
      // Absent means 0, for the same reason eventType is absent on a click:
      // the zero value is omitted on the wire. Treating "absent" as "keep the
      // previous index" instead would open the wrong entry every time row 0 is
      // clicked after the highlight has been anywhere else.
      this.selected = event.listEvent.currentSelectItemIndex ?? 0;
      await this.activate();
      return;
    }

    if (event.audioEvent) {
      // 100ms of 16 kHz mono s16le per event. Dropped unless dictation asked
      // for them, so a stray event after audioControl(false) cannot grow the
      // buffer behind the app's back.
      const pcm = event.audioEvent.audioPcm;
      if (this.recording && pcm && pcm.length > 0) {
        this.audioChunks.push(pcm);
        this.audioBytes += pcm.length;
        if (this.audioBytes >= MAX_AUDIO_BYTES) {
          // Full. Stop here rather than let the request grow into a 413 -
          // see MAX_AUDIO_BYTES. What was captured is still transcribed.
          await this.stopDictation();
        }
      }
      return;
    }

    // A click on a text container that captures events - which is how the
    // record screen is stopped without reaching for the menu.
    if (event.textEvent) {
      if (this.screen === "record") await this.stopDictation();
      return;
    }

    if (event.menuItemClickEvent) {
      const id = event.menuItemClickEvent.itemID;
      if (typeof id === "number") await this.action(id);
      return;
    }

    if (event.sysEvent) {
      const t = event.sysEvent.eventType;
      if (
        t === OsEventTypeList.SYSTEM_EXIT_EVENT ||
        t === OsEventTypeList.ABNORMAL_EXIT_EVENT
      ) {
        this.current = null;
      }
      // A long press anywhere is "back", the one gesture worth binding: it is
      // reachable from both the ring and the temple.
      if (t === OsEventTypeList.LONG_PRESS_EVENT) {
        await this.back();
      }
    }
  }

  /** Click on the focused list row. */
  private async activate(): Promise<void> {
    if (this.busy) return;
    switch (this.screen) {
      case "list": {
        const entry = this.entries[this.selected];
        if (entry) await this.openDetail(entry);
        break;
      }
      case "kinds": {
        const kind = this.kinds[this.selected];
        if (kind !== undefined) {
          this.config.kind = kind;
          await this.openList();
        }
        break;
      }
      case "quick": {
        const cap = this.config.quickCaptures[this.selected];
        if (cap) await this.runGuarded(() => this.createFrom(cap.kind, cap.title, cap.content));
        break;
      }
      default:
        break;
    }
  }

  private async action(id: number): Promise<void> {
    if (this.busy) return;
    if (id === A_EXIT && this.screen !== "detail") {
      // Cancel on the dictation screens means "stop and go back", not "quit
      // the app" - and the microphone has to be released either way.
      if (this.screen === "record" || this.screen === "confirm") {
        await this.cancelDictation();
        return;
      }
      await this.ui.close();
      return;
    }
    switch (this.screen) {
      case "list":
        if (id === A_NEW) return this.openQuick();
        if (id === A_KIND) return this.openKinds();
        if (id === A_REFRESH) return this.openList(false);
        if (id === A_MORE) {
          this.offset += this.config.limit;
          return this.openList(false);
        }
        if (id === A_TOP) return this.openList();
        if (id === A_DICTATE) return this.startDictation();
        break;
      case "record":
        if (id === A_STOP) return this.stopDictation();
        break;
      case "confirm":
        if (id === A_SAVE) {
          return this.runGuarded(() =>
            this.createFrom(this.config.kind || this.logKind, "", this.transcript),
          );
        }
        if (id === A_RETRY) return this.startDictation();
        break;
      case "detail":
        if (id === A_BACK) return this.back();
        if (id === A_PAGE) return this.nextPage();
        if (id === A_DONE) return this.runGuarded(() => this.toggleDone());
        if (id === A_DELETE) return this.runGuarded(() => this.deleteSelected());
        break;
      case "kinds":
      case "quick":
        if (id === A_BACK) return this.back();
        break;
      case "message":
        await this.ui.close();
        break;
    }
  }

  /** Abandons a recording and returns to the list, with the mic closed. */
  private async cancelDictation(): Promise<void> {
    if (this.recordTimer !== null) {
      clearTimeout(this.recordTimer);
      this.recordTimer = null;
    }
    if (this.recording) {
      this.recording = false;
      await this.bridge.audioControl(false);
    }
    this.audioChunks = [];
    this.audioBytes = 0;
    this.transcript = "";
    this.screen = "list";
    await this.renderList();
  }

  private async back(): Promise<void> {
    if (this.screen === "list" || this.screen === "message") return;
    if (this.screen === "record" || this.screen === "confirm") {
      await this.cancelDictation();
      return;
    }
    this.current = null;
    await this.renderList();
    this.screen = "list";
  }

  private async nextPage(): Promise<void> {
    if (this.pages.length <= 1) return;
    this.page = (this.page + 1) % this.pages.length;
    await this.ui.updateBody(this.pages[this.page] ?? "");
    await this.ui.updateFooter(
      `${this.page + 1}/${this.pages.length} · ${this.current?.last_modified_at_utc ?? ""}`,
    );
  }

  // --- mutations -----------------------------------------------------------

  /** Only ever the opened entry - see the note on listActions(). */
  private targetEntry(): LcarsEntry | null {
    return this.current;
  }

  private async toggleDone(): Promise<void> {
    if (!this.client) return;
    const e = this.targetEntry();
    if (!e) return;
    const next = e.done_bool ? 0 : 1;
    // The API acknowledges the write rather than returning the row, so the
    // local copy is updated here instead of being replaced by the response.
    await this.client.setDone(e.id, next === 1);
    e.done_bool = next;
    if (this.current && this.current.id === e.id) {
      this.current.done_bool = next;
    }
    if (this.screen === "detail") await this.renderDetail();
    else await this.renderList();
  }

  private async deleteSelected(): Promise<void> {
    if (!this.client) return;
    const e = this.targetEntry();
    if (!e) return;
    // Soft delete - the row survives and `restore` is the undo - which is the
    // only reason a single menu tap is allowed to do this with no confirm step.
    await this.client.remove(e.id);
    this.entries = this.entries.filter((x) => x.id !== e.id);
    if (this.selected >= this.entries.length) {
      this.selected = Math.max(0, this.entries.length - 1);
    }
    this.current = null;
    this.screen = "list";
    await this.renderList();
  }

  private async createFrom(kind: string, title: string, content: string): Promise<void> {
    if (!this.client) return;
    // An untitled quick capture is stamped with the time, matching what the
    // journal already does for entries posted without one.
    const stamp = new Date().toISOString().replace("T", " ").slice(0, 19);
    await this.client.create(kind, title || stamp, content);
    // Re-list rather than synthesising a row from what was sent: create
    // answers with an id only, and the server stamps created_at/last_modified
    // itself, so a locally invented entry would show the wrong time.
    this.config.kind = kind;
    await this.openList();
  }

  /** Runs a mutation with the in-flight guard and one place to report failure. */
  private async runGuarded(fn: () => Promise<void>): Promise<void> {
    this.busy = true;
    try {
      await fn();
    } catch (e) {
      await this.fail(e);
    } finally {
      this.busy = false;
    }
  }

  private async fail(e: unknown): Promise<void> {
    const err = e instanceof LcarsError ? e : null;
    let text = err ? err.message : String(e);
    if (err && err.status === 0) {
      text =
        "Cannot reach the API. Check the tailnet, and that the host is in app.json's network whitelist.";
    } else if (err && (err.status === 401 || err.status === 403)) {
      text = "Credentials rejected. Fix them on the phone.";
    }
    console.error("LCARS request failed:", e);
    await this.message("LCARS error", text);
  }
}

// Dictation goes over POST /transcribe, which the LCARS server relays to
// Deepgram with its own key. The SDK gives raw PCM (AudioEvent.audioPcm) and
// no speech-to-text of its own. Quick captures remain for the notes you log
// often enough to not want to say out loud.

async function boot(): Promise<void> {
  const bridge = await waitForEvenAppBridge();
  const app = new App(bridge);
  await app.start();
}

// Only drive the glasses when the Even App actually hosts us. Opened in a
// normal browser (or the phone settings page), index.html renders the form
// instead and this bootstrap stays out of the way.
if (typeof window !== "undefined" && "flutter_inappwebview" in window) {
  void boot();
}

export { App, boot };
