#ifndef LCARS_TYPES_H
#define LCARS_TYPES_H

#include "raylib.h"
#include "vendor/sqlite3.h"
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

#include "lcars_arena.h"
#include "lcars_string.h"
#include "lcars_voice_rec.h"

#define LCARS_PURPLE (Color){206, 153, 205, 255}
#define LCARS_RED_ORANGE (Color){204, 102, 102, 255}
#define LCARS_ORANGE (Color){255, 154, 102, 255}
#define LCARS_YELLOW (Color){255, 205, 154, 255}
#define LCARS_BLUE (Color){155, 155, 255, 255}
#define LCARS_GREEN (Color){153, 204, 153, 255}
// Marks a code path that isn't implemented yet. Writes straight to stderr
// (unbuffered, unlike stdout) and aborts immediately, so a hit can't get
// lost in a buffered printf that never got flushed before the crash.
#define TODO                                                                   \
  fprintf(stderr, "TODO hit at %s:%d\n", __FILE__, __LINE__);                  \
  abort()

#define WINDOW_WIDTH 1600
#define WINDOW_HEIGHT 900

#define MAX_ELEMENTS 10000
#define MAX_KINDS 32
#define MAX_LIST_ITEMS 32

#define TEXT_VOICE_INPUT "Voice Input"
#define TEXT_RECORDING "RECORDING..."

// SQLite database file path, relative to the process's working directory.
// Shared by every entry point that opens it directly: the main app
// (liblcars.h), --http-only's minimal init (lcars.c), and the HTTP API
// server (lcars_http.h).
#define LCARS_DB_PATH "lcars.db"

// The entry "kind" used to seed the DB on first run and to fall back to
// when nothing else (a selected kind, an existing entry) is available.
#define DEFAULT_ENTRY_KIND "architect_log"

#define NOTIFICATION_DURATION 3.0f
#define NOTIFICATION_MAX_LEN 48

// Text editor / entry-list tuning constants
#define SCROLL_SPEED_PX 30.0f
#define CURSOR_MOVE_REPEAT_DELAY 0.4f
#define DELETE_REPEAT_DELAY 0.5f
#define GAP_BUFFER_INITIAL_CAPACITY 4096
#define GAP_BUFFER_MIN_GROWN_CAPACITY 1024
#define LINE_STARTS_MAX 1024
#define EDITOR_TEXT_PADDING 5.0f
#define SCROLLBAR_MIN_HANDLE_HEIGHT 20.0f
#define LIST_SCROLLBAR_MIN_HANDLE_HEIGHT 15.0f

// How long an editor must sit idle (no edits) before its content is
// auto-saved to the DB. Content is also always flushed immediately when
// switching away from an entry, regardless of this delay.
#define CONTENT_SAVE_DEBOUNCE_SECONDS 1.0f

// Drag/resize edit-mode handle hit-box: a HANDLE_SIZE square offset by
// HANDLE_OFFSET from the element's corner.
#define EDIT_HANDLE_SIZE 16.0f
#define EDIT_HANDLE_OFFSET 8.0f

typedef enum ButtonAction {
  ACTION_NONE = 0,
  ACTION_DEBUG,
  ACTION_EDIT,
  ACTION_RESET,
  ACTION_VOICE_INPUT,
  ACTION_PRINT_DB,
  ACTION_LOAD_HYPERMEDIA,
} ButtonAction;

// ---------------------------------------------------------------------------
// Hypermedia controls — the lc-* document attributes
// ---------------------------------------------------------------------------
// A "control" is what turns a static element into one that issues a request
// and does something with the reply: the HTMX/DataStar idea, minus the
// scripting. See lcars_hypermedia_controls.h for the dispatch side and
// ParseHyperControl() in lcars_hypermedia.h for the parse side.

// Which request the control issues, taken from *which* attribute carried the
// URL (lc-get/lc-post/lc-put/lc-delete). NONE means the element has no
// control at all, which is also why Element.control is NULL in that case -
// the two must never disagree.
typedef enum HyperMethod {
  HYPER_METHOD_NONE = 0,
  HYPER_METHOD_GET,
  HYPER_METHOD_POST,
  HYPER_METHOD_PUT,
  HYPER_METHOD_DELETE,
  HYPER_METHOD_TOTAL,
} HyperMethod;

// What to do with the response body (lc-swap). DEFAULT is not a swap: it
// means the document didn't say, and ResolveHyperSwap() picks one from the
// method and whether an lc-target was given.
typedef enum HyperSwap {
  HYPER_SWAP_DEFAULT = 0,
  HYPER_SWAP_NONE,     // discard the body (a notification still shows)
  HYPER_SWAP_TEXT,     // replace the target element's text
  HYPER_SWAP_APPEND,   // append to the target element's text
  HYPER_SWAP_DOCUMENT, // parse the body as a hypermedia document
  HYPER_SWAP_RELOAD,   // re-load the document that is currently displayed
  HYPER_SWAP_TOTAL,
} HyperSwap;

// What makes the control fire (lc-trigger). LOAD fires once, right after the
// document that declares it finishes parsing. ENTER fires when the focused
// text editor that declares it sees the Enter key - which also means Enter
// stops inserting a newline there, i.e. the element becomes a single-line
// submit field (the URL bar) rather than a document being typed.
typedef enum HyperTrigger {
  HYPER_TRIGGER_CLICK = 0,
  HYPER_TRIGGER_LOAD,
  HYPER_TRIGGER_ENTER,
  HYPER_TRIGGER_TOTAL,
} HyperTrigger;

// Upper bound on the name=value pairs one request can carry (lc-vals plus
// lc-include). Requests are built into a fixed stack array of this size, so
// a document asking for more gets the extras dropped with a warning rather
// than an overrun - document content is runtime input, not a programmer
// error.
#define MAX_HYPER_FIELDS 16

// One name=value pair of a request body. Both halves live in scratch_arena:
// fields are collected at dispatch time and never outlive the frame.
typedef struct HyperField {
  String name;
  String value;
} HyperField;

// The parsed lc-* attributes of one element. Allocated on demand into
// doc_arena by ParseHyperControl() and referenced by pointer from Element,
// for the same reason as EntryListState/SphereState: most elements have no
// control, and there are MAX_ELEMENTS of them.
//
// Every String here points into doc_arena, so a control is only valid until
// the next document load - see the snapshot comment in FireHyperControl().
typedef struct HyperControl {
  HyperMethod method;
  HyperSwap swap;
  HyperTrigger trigger;
  // Where the request goes: a path starting with '/' is handled in-process
  // against lcars.db (this app is its own origin), http(s):// goes out over
  // the network. A '#id' url is an indirection instead of a location - the
  // named element's text is read at fire time and used as the url, which is
  // how a document expresses "go wherever this field says" (the URL bar).
  String url;
  String target;  // id of the element a TEXT/APPEND swap writes into
  String vals;    // literal "name=value,name=value" pairs
  String include; // ids of elements whose text becomes a field
} HyperControl;

typedef struct KindList {
  String kinds[MAX_KINDS];
  int count;
} KindList;

typedef struct EntryListItem {
  int id;
  char title[128];
  char created_at[32];
  char last_modified[32];
} EntryListItem;

// State only meaningful for kind == ELEM_ENTRY_LIST. Allocated on demand by
// make_entry_list() into doc_arena and referenced via Element.entryList — a
// flat embed would put ~7KB of list-only state (dominated by cachedEntries)
// on every one of MAX_ELEMENTS elements, even though at most one is ever an
// entry list.
typedef struct EntryListState {
  bool listCollapsed;
  float listScrollY;
  int selectedEntryId;

  KindList kindList;
  String selectedKind;
  // kindList is only re-fetched when this is false — see
  // EnsureKindListCache()/InvalidateKindListCache() in lcars_db.h. Avoids
  // re-querying (and re-allocating a fresh KindList into doc_arena) on
  // every click in the list panel.
  bool kindListCacheValid;

  // Cache of GetEntriesByKind(selectedKind) — see EnsureEntryListCache() /
  // InvalidateEntryListCache() in lcars_db.h. Avoids re-querying the DB
  // every frame just to draw the list.
  EntryListItem cachedEntries[MAX_LIST_ITEMS];
  int cachedEntryCount;
  bool entryListCacheValid;
} EntryListState;

// State only meaningful for kind == ELEM_SPHERE. Allocated on demand by
// make_sphere() into doc_arena and referenced via Element.sphere, for the
// same reason as EntryListState above.
typedef struct SphereState {
  Model model;
  float rotation;
  RenderTexture renderTexture;
  Camera camera;
} SphereState;

typedef enum ElemKind {
  ELEM_NOTHING = 0,
  ELEM_RECTANGLE,
  ELEM_ELBOW,
  ELEM_BUTTON,
  ELEM_TEXT,
  ELEM_TEXT_EDITOR,
  ELEM_ENTRY_LIST,
  ELEM_SPHERE,
  ELEM_TOTAL_KINDS
} ElemKind;

typedef struct KeyRepeat {
  bool isHeld;
  float startTime;
} KeyRepeat;

// Self-contained gap buffer for text editing — no Element/raylib dependency,
// so the editing logic in lcars_gap_buffer.h can operate on it (and be
// tested) directly. See lcars_gap_buffer.h for the operations.
typedef struct GapBuffer {
  char *buffer;
  int gapStart;
  int gapEnd;
  int capacity;
  // Scratch buffer holding the flattened (gap-free) contents, handed out as
  // Element.text by ReconstructText(). Owned here, and reused across
  // reconstructions, because text is rebuilt on *every* keystroke and
  // doc_arena reclaims nothing until the document is reloaded — allocating a
  // fresh buffer per edit costs O(n^2) of the arena over an editing session
  // and eventually trips its OOM abort. Grows geometrically like `buffer`.
  char *text;
  int textCapacity; // Allocated size of `text`, including the '\0'.
} GapBuffer;

// The structural invariant every GapBuffer holds between operations: the
// gap is a well-formed (possibly empty) range lying entirely inside the
// allocation. Every operation in lcars_gap_buffer.h asserts it on entry and
// on exit, because the failure mode when it breaks is not a wrong character
// on screen - ReconstructText() computes `capacity - gapEnd` as a memcpy
// length, so a gapEnd past capacity becomes a negative length and then a
// gigantic size_t. Declared here rather than in lcars_gap_buffer.h because
// lcars_db.h and make_text_editor() are compiled before that header is
// included and assert against it too.
static inline bool GapBufferValid(const GapBuffer *gap) {
  return gap != NULL && gap->buffer != NULL && gap->capacity >= 0 &&
         gap->gapStart >= 0 && gap->gapStart <= gap->gapEnd &&
         gap->gapEnd <= gap->capacity;
}

// Number of characters the buffer currently holds: everything outside the
// gap. This is the length the flattened text (Element.text) will have.
static inline int GapTextLen(const GapBuffer *gap) {
  assert(GapBufferValid(gap));
  return gap->gapStart + (gap->capacity - gap->gapEnd);
}

// A text selection expressed as gap-buffer indices. `length` is signed: a
// selection made by dragging/shift-arrowing backwards has a negative
// length, with `start` still the anchor (where the selection began) and
// `end` the current cursor position.
typedef struct Selection {
  int start;
  int length;
  int end;
} Selection;

// Geometry of a text editor's vertical scrollbar, shared between input
// handling and drawing so they can't compute it differently. See
// ComputeScrollbarLayout() in lcars_ui.h.
typedef struct ScrollbarLayout {
  Rectangle bounds;
  Rectangle upButton;
  Rectangle downButton;
  Rectangle track;
  Rectangle handle;
  float scrollRange;
} ScrollbarLayout;

// Geometry of an ELEM_ENTRY_LIST's left-hand entry list panel, shared
// between input handling, drawing, and cursor-visibility logic in
// lcars_text.h so they can't disagree about the panel's width. See
// ComputeEntryListLayout() in lcars_ui.h.
typedef struct EntryListLayout {
  float width;           // 30 collapsed, 350 expanded
  Rectangle panelRec;    // whole panel: {pos.x, pos.y, width, *height}
  Rectangle toggleBtn;   // top-left collapse/expand button
  Rectangle newEntryBtn; // "+ NEW ENTRY" button (only meaningful when expanded)
  float headerHeight;    // vertical offset from panel top to the first item row
  float itemStride;      // vertical spacing between item rows
  float itemHeight;      // height of each item row
  float viewportHeight;  // *height - headerHeight
} EntryListLayout;

typedef struct Element {
  ElemKind kind;
  // Optional stable identifier from the hypermedia `id="..."` attribute.
  // Empty (data == NULL) unless the document set one. See FindElementById()
  // in lcars_ui.h.
  String id;
  // Optional navigation target from the hypermedia `href="..."` attribute,
  // used by ACTION_LOAD_HYPERMEDIA. Empty (data == NULL) unless the
  // document set one, in which case the click handler falls back to
  // reading the "url_input" element's typed text instead. See
  // HandleElementClick() in liblcars.h.
  String href;
  ButtonAction on_click;
  // Only non-NULL if the document gave this element an lc-get/lc-post/
  // lc-put/lc-delete attribute — see HyperControl.
  HyperControl *control;
  // The hypermedia `lc-from="<id>"` attribute: this element declares no
  // request of its own, it only names the element whose request a click
  // fires (the GO button next to a URL field). Empty (data == NULL) unless
  // the document set one. Kept out of HyperControl on purpose — an element
  // with only lc-from has no method, and a HyperControl with
  // HYPER_METHOD_NONE would break the invariant above. See
  // FireHyperControlFrom() in lcars_hypermedia_controls.h.
  String controlFrom;
  Vector2 position;
  Vector3 position3;
  float width, height;
  // ELEM_TEXT only: true means width/height are ignored and the element
  // is sized from its text instead — see make_text()/GetElementBoundingBox().
  bool autoSize;
  Color color;
  Color originalColor;
  int elbowOrientation; // Only used if kind == ELBOW
  String text;          // Text on button or just text elem
  int textLen;          // text lenght of chars.
  int textSize;         // Only used if kind == TEXT / TEXTBOX for display size

  // Only non-NULL if kind == ELEM_SPHERE — see SphereState.
  SphereState *sphere;

  float scrollY;
  float textHeight;
  float cursorY;
  int snapToCursor;
  GapBuffer gap;

  // ELEM_TEXT_EDITOR only: whether this editor's contents are the default
  // log entry, i.e. whether the debounced save writes them to the DB at all
  // (see FlushEntryContent in lcars_db.h). Opt-in via bind="log", because
  // the other thing documents use editors for is typed input - a URL bar, a
  // form field - and saving those over the newest journal entry is exactly
  // what used to happen. An entry list carries its own binding through
  // EntryListState.selectedEntryId and ignores this.
  bool bindsToLog;

  // Text editor state fields
  bool isFocused;
  int textSelectedFramesCounter;
  Selection selection;
  KeyRepeat deleteRepeat;
  KeyRepeat moveLeftRepeat;
  KeyRepeat moveRightRepeat;
  KeyRepeat moveUpRepeat;
  KeyRepeat moveDownRepeat;
  bool selectingText;
  bool draggingScrollbar;
  float dragStartY;
  float dragStartScrollY;
  bool isDragging;
  bool isResizing;
  float dragOffsetX;
  float dragOffsetY;

  // Only non-NULL if kind == ELEM_ENTRY_LIST — see EntryListState.
  EntryListState *entryList;

  // Debounced content save — see MarkContentDirty()/FlushEntryContent() in
  // lcars_db.h. contentDirty means the in-memory text differs from what's
  // persisted; lastEditTime is the GetTime() timestamp of the most recent
  // edit, used to detect CONTENT_SAVE_DEBOUNCE_SECONDS of idle time.
  bool contentDirty;
  float lastEditTime;
} Element;

typedef struct State {
  Element elements[MAX_ELEMENTS];
  int numElements;
  Color lcarsColor;
  float posX, posY, columnWidth, columnHeight, barWidth, barHeight, innerRadius;
  bool debug;
  bool is_editing;
  bool textBoxEditMode;
  Font font;
  String notification;
  int notificationOnElemIdx;
  float notificationTimer;
  sqlite3 *db;
  VoiceRecApi *voiceApi;
  double time_resource_download;
  double time_voice_init;
  double time_window_init;
  Arena doc_arena;
  Arena scratch_arena;
  Rectangle selection_rec;

  // Source (file://..., http://..., a path) of the document currently
  // displayed, as handed to LoadHypermediaDocument(). A fixed array rather
  // than a String because every load resets doc_arena, which is where any
  // String would live: this has to survive the reset to be re-loadable
  // afterwards (HYPER_SWAP_RELOAD). Empty until the first load.
  char currentDocument[512];
  // Bumped by every document load. Anything holding an Element * (or an
  // index into s->elements) across a call that can load a document compares
  // this before and after and bails out if it changed - the array, and
  // everything in doc_arena the old elements pointed at, is gone by then.
  // See UpdateElement()/Update() in liblcars.h.
  int documentGeneration;
} State;

#endif // LCARS_TYPES_H
