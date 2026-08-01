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
#define MAX_INPUT_CHARS 1024
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
} GapBuffer;

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
} State;

#endif // LCARS_TYPES_H
