#define _POSIX_C_SOURCE 200809L
#include "raylib.h"
#include "raymath.h"
#include "rlgl.h"
#include "vendor/raygui.h"
#include "vendor/sqlite3.h"
#include "voice_rec.h"
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "lcars_arena.h"
#include "lcars_string.h"

static inline double GetTimeSeconds(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

#define _ISOC99_SOURCE
#include <math.h>

#define LCARS_PURPLE (Color){206, 153, 205, 255}
#define LCARS_RED_ORANGE (Color){204, 102, 102, 255}
#define LCARS_ORANGE (Color){255, 154, 102, 255}
#define LCARS_YELLOW (Color){255, 205, 154, 255}
#define LCARS_BLUE (Color){155, 155, 255, 255}
#define TODO exit(1)

#define MAX_ELEMENTS 10000
#define MAX_INPUT_CHARS 1024

#define TEXT_VOICE_INPUT "Voice Input"
#define TEXT_RECORDING "RECORDING..."

typedef enum ButtonAction {
  ACTION_NONE = 0,
  ACTION_DEBUG,
  ACTION_EDIT,
  ACTION_RESET,
  ACTION_VOICE_INPUT,
  ACTION_PRINT_DB,
  ACTION_LOAD_HYPERMEDIA,
} ButtonAction;

typedef struct iVec2 {
  int x, y;
} iVec2;

typedef enum ElemKind {
  ELEM_NOTHING = 0,
  ELEM_RECTANGLE,
  ELEM_ELBOW,
  ELEM_BUTTON,
  ELEM_TEXT,
  ELEM_TEXT_EDITOR,
  ELEM_SPHERE,
  ELEM_TOTAL_KINDS
} ElemKind;

typedef struct Element {
  ElemKind kind;
  ButtonAction on_click;
  iVec2 position;
  Vector3 position3;
  float *width, *height;
  Color color;
  Color originalColor;
  int elbowOrientation; // Only used if kind == ELBOW
  String text;          // Text on button or just text elem
  int textLen;          // text lenght of chars.
  int textLineLen;      // crt line len
  int textLines;
  int textSize; // Only used if kind == TEXT / TEXTBOX for display size
  Model model;
  float rotation;
  RenderTexture renderTexture;
  Camera camera;
  float scrollY;
  float textHeight;
  float cursorY;
  int snapToCursor;
  char *gapBuffer;
  int gapStart;
  int gapEnd;
  int textCapacity;

  // Text editor state fields
  bool isFocused;
  int textSelectedFramesCounter;
  int selectTextStart;
  int selectTextLength;
  int selectTextEnd;
  bool isDeletingText;
  float deletingTextStartTime;
  bool isMovingCursorLeft;
  float moveCursorLeftStartTime;
  bool isMovingCursorRight;
  float moveCursorRightStartTime;
  bool isMovingCursorUp;
  float moveCursorUpStartTime;
  bool isMovingCursorDown;
  float moveCursorDownStartTime;
  bool selectingText;
  bool draggingScrollbar;
  float dragStartY;
  float dragStartScrollY;
  bool isDragging;
  bool isResizing;
  float dragOffsetX;
  float dragOffsetY;
} Element;

typedef struct State {
  Element elements[MAX_ELEMENTS];
  int numElements;
  Color lcarsColor;
  float posX, posY, columnWidth, columnHeight, barWidth, barHeight, innerRadius;
  bool debug;
  bool is_editing;
  int controllsX;
  int controllsY;
  bool textBoxEditMode;
  Font font;
  String notification;
  int notificationOnElemIdx;
  float notificationTimer;
  Ray ray;                // Picking line ray
  RayCollision collision; // Ray collision hit info
  sqlite3 *db;
  void *voiceApi;
  double time_resource_download;
  double time_voice_init;
  double time_window_init;
  Arena doc_arena;
  Arena scratch_arena;
} State;

#define NOTIFICATION_DURATION 3.0f
#define NOTIFICATION_MAX_LEN 48

// -----------------------------------------------------------------------------
// Public API Function Declarations
// -----------------------------------------------------------------------------
void Init(State *s, bool firstInit);
void Reload(State *s, bool reset);
void Update(State *s);
void UpdateDrawFrame(State *s);
void LoadHypermediaDocument(State *s, String filename);

// -----------------------------------------------------------------------------
// Inline Utility Function Declarations
// -----------------------------------------------------------------------------
static inline void updateNotification(State *s, String notificationText);

#ifdef LCARS_IMPLEMENTATION

// -----------------------------------------------------------------------------
// Internal Helper Declarations
// -----------------------------------------------------------------------------
static void ToggleVoiceRecording(State *s);
#ifndef HYPERMEDIA
static void ReLayout(State *s);
#endif
static int sqlite_callback(void *state, int argc, char **argv,
                           char **azColName);
static int ExecSQL(State *s, String sql, String successMsg);
static void InitDB(State *s, bool firstInit);
static String GetLogFromDB(State *s);
static void UpdateLogInDB(State *s, String newLog);
static bool IsWordChar(char c);
static void MoveGap(Element *e, int index);
static void GapInsertChar(Arena *arena, Element *e, char c);
static void GapDeleteBack(Element *e);
static void GapDeleteForward(Element *e);
static void ReconstructText(Arena *arena, Element *e);
static bool DeleteSelection(Element *e);
static void StartTextSelection(Element *e, bool shiftDown);
static void EndTextSelection(Element *e, bool shiftDown);
static void ClampScrollY(Element *e);
static int GetLines(String text, int *lineStarts, int maxLines);
static int GetLineForIndex(int index, const int *lineStarts, int numLines);
#ifndef HYPERMEDIA
static void AddBarSegment(State *s, int *x_cursor, int y, float *width,
                          float *height, Color color, int gap);
#endif
static void clickOrHoverNotification(State *s, int i, String elem_pretty_name);
static Rectangle GetElementBoundingBox(const Element *e);
static void DrawTextBoxedSelectable(State *s, Element *e, Font font,
                                    String text, Rectangle rec, float fontSize,
                                    float spacing, bool wordWrap, Color tint,
                                    int selectStart, int selectLength,
                                    Color selectTint, Color selectBackTint,
                                    float *outTextHeight, float *outCursorY,
                                    int cursorIndex);
static void DrawTextBoxed(State *s, Element *e, Font font, String text,
                          Rectangle rec, float fontSize, float spacing,
                          bool wordWrap, Color tint, float *outTextHeight,
                          float *outCursorY, int cursorIndex);
static void DrawElbow(int posX, int posY, int columnWidth, int columnHeight,
                      int barWidth, int barHeight, int innerRadius, Color color,
                      int orientation, bool debug);
static int GetCharIndexAtMouse(const State *s, Font font, String text,
                               Vector2 textPos, float fontSize, float spacing,
                               Vector2 mousePos, float recWidth);

#endif // LCARS_IMPLEMENTATION

// -----------------------------------------------------------------------------
// Inline Utility Function Implementations
// -----------------------------------------------------------------------------
static inline void updateNotification(State *s, String notificationText) {
  StringAssign(&s->doc_arena, &s->notification, notificationText);
  s->notificationTimer = NOTIFICATION_DURATION;
}

#ifdef LCARS_IMPLEMENTATION

#include <curl/curl.h>

#define MAX(a, b) ((a) > (b) ? (a) : (b))
#define MIN(a, b) ((a) < (b) ? (a) : (b))

static void ToggleVoiceRecording(State *s) {
  VoiceRecApi *vapi = (VoiceRecApi *)s->voiceApi;
  if (!vapi) {
    updateNotification(s, StringStatic("VOICE ERROR"));
    return;
  }

  // Find the Voice Input button
  Element *voiceBtn = NULL;
  for (int j = 0; j < s->numElements; j++) {
    if (s->elements[j].kind == ELEM_BUTTON &&
        s->elements[j].on_click == ACTION_VOICE_INPUT) {
      voiceBtn = &s->elements[j];
      break;
    }
  }

  if (vapi->IsRecording()) {
    vapi->StopRecording();
    if (voiceBtn) {
      StringAssignStatic(&voiceBtn->text, TEXT_VOICE_INPUT);
      voiceBtn->color = voiceBtn->originalColor;
    }
  } else {
    if (vapi->StartRecording()) {
      if (voiceBtn) {
        StringAssignStatic(&voiceBtn->text, TEXT_RECORDING);
        voiceBtn->color = RED;
      }
    } else {
      updateNotification(s, StringStatic("Voice Recording failed to start"));
    }
  }
}

#ifndef HYPERMEDIA
// Shared layout static variables
static float w600 = 600;
static float h400 = 400;
static float w300 = 300;
static float h300 = 300;

static float w[4];
static float h100;
static float h200_60_250[3];
static float halfBarHeight;
static float buttonHeight;
static float w210;
#endif

#include "lcars_db.h"
#include "lcars_gap_buffer.h"
#include "lcars_text.h"
#include "lcars_ui.h"

static void ClampScrollY(Element *e) {
  if (e->scrollY < 0.0f)
    e->scrollY = 0.0f;
  float maxScroll = e->textHeight - *e->height;
  if (maxScroll < 0.0f)
    maxScroll = 0.0f;
  if (e->scrollY > maxScroll)
    e->scrollY = maxScroll;
}



void Init(State *s, bool firstInit) {
  double t_init_start = GetTimeSeconds();

#ifndef HYPERMEDIA
  double t_layout_start = GetTimeSeconds();
#endif
  s->debug = false;
  s->is_editing = false;
  s->controllsX = 600;
  s->controllsY = 400;
  s->lcarsColor = (Color){204, 153, 204, 255}; // Purple
  s->posX = 0;
  s->posY = 210;
  s->columnWidth = 200;
  s->columnHeight = 40;
  s->barWidth = 400;
  s->barHeight = 20;
  s->innerRadius = 40;
  s->numElements = 0;

  s->notification = StringInit(&s->doc_arena, "");
#ifdef HYPERMEDIA
  LoadHypermediaDocument(s, StringStatic("file://main.html"));
#else
  ReLayout(s);
#endif
#ifndef HYPERMEDIA
  double t_layout_end = GetTimeSeconds();

  double t_db_start = GetTimeSeconds();
#endif
  if (firstInit) {
    sqlite3 *db = NULL;
    int rc = sqlite3_open("lcars.db", &db);
    if (rc) {
      fprintf(stderr, "Can't open database: %s\n", sqlite3_errmsg(db));
    } else {
      fprintf(stderr, "Opened database successfully\n");
    }
    s->db = db;
  }

  InitDB(s, firstInit);

#ifdef HYPERMEDIA
  s->font = GetFontDefault();
  GuiLoadStyle("resources/style_cyber.rgs");
#endif

  double t_init_end = GetTimeSeconds();

#ifndef HYPERMEDIA
  printf(
      "\n=================== STARTUP PERFORMANCE TIMING ===================\n");
  if (firstInit) {
    printf("1. Resource Download:     %8.2f ms\n",
           s->time_resource_download * 1000.0);
    printf("2. Voice Rec Init (Lazy):  %8.2f ms\n",
           s->time_voice_init * 1000.0);
    printf("3. Window Initialization:  %8.2f ms\n",
           s->time_window_init * 1000.0);
  }
  printf("4. Basic Layout Setup:     %8.2f ms\n",
         (t_layout_end - t_layout_start) * 1000.0);
  printf("5. DB Open & Init:         %8.2f ms\n",
         (t_db_end - t_db_start) * 1000.0);
  printf("6. Text Editor Setup:      %8.2f ms\n",
         (t_editor_end - t_editor_start) * 1000.0);
  printf("7. Font & Image Loading:   %8.2f ms\n",
         (t_media_end - t_media_start) * 1000.0);
  printf("8. 3D Model Generation:    %8.2f ms\n",
         (t_model_end - t_model_start) * 1000.0);
  printf("9. GUI Style Loading:      %8.2f ms\n",
         (t_style_end - t_style_start) * 1000.0);
  printf("10. RenderTexture Setup:   %8.2f ms\n",
         (t_render_texture_end - t_render_texture_start) * 1000.0);
  printf("-----------------------------------------------------------------\n");
  double total_init_time = (t_init_end - t_init_start);
  printf("Total Init() Time:         %8.2f ms\n", total_init_time * 1000.0);
  if (firstInit) {
    double total_startup_time = s->time_resource_download + s->time_voice_init +
                                s->time_window_init + total_init_time;
    printf("Total App Startup Time:    %8.2f ms\n",
           total_startup_time * 1000.0);
  }
  printf(
      "==================================================================\n\n");
#else
  printf(
      "\n=================== STARTUP PERFORMANCE TIMING ===================\n");
  if (firstInit) {
    printf("1. Resource Download:     %8.2f ms\n",
           s->time_resource_download * 1000.0);
    printf("2. Voice Rec Init (Lazy):  %8.2f ms\n",
           s->time_voice_init * 1000.0);
    printf("3. Window Initialization:  %8.2f ms\n",
           s->time_window_init * 1000.0);
  }
  double total_init_time = (t_init_end - t_init_start);
  printf("Total Init() Time:         %8.2f ms\n", total_init_time * 1000.0);
  if (firstInit) {
    double total_startup_time = s->time_resource_download + s->time_voice_init +
                                s->time_window_init + total_init_time;
    printf("Total App Startup Time:    %8.2f ms\n",
           total_startup_time * 1000.0);
  }
  printf(
      "==================================================================\n\n");
#endif
}

void Reload(State *s, bool reset) {
  if (reset) {
    Init(s, false);
  } else {
    GuiLoadStyle("resources/style_cyber.rgs");
  }
}



void Update(State *s) {
  // Voice recognition updates
  VoiceRecApi *vapi = (VoiceRecApi *)s->voiceApi;
  if (vapi) {
    if (vapi->IsRecording()) {
      char partialBuf[256];
      if (vapi->PollPartial(partialBuf, sizeof(partialBuf))) {
        if (strlen(partialBuf) > 0) {
          char fullNotify[300];
          snprintf(fullNotify, sizeof(fullNotify), "[Voice: \"%s\"]",
                   partialBuf);
          updateNotification(s, StringStatic(fullNotify));
        }
      }
    }

    char voiceBuf[256];
    if (vapi->PollResult(voiceBuf, sizeof(voiceBuf))) {
      Element *editor = NULL;
      for (int j = 0; j < s->numElements; j++) {
        if (s->elements[j].kind == ELEM_TEXT_EDITOR) {
          editor = &s->elements[j];
          break;
        }
      }

      if (editor) {
        bool textChanged = false;
        int voiceBufLen = strlen(voiceBuf);
        for (int k = 0; k < voiceBufLen; k++) {
          GapInsertChar(&s->doc_arena, editor, voiceBuf[k]);
          textChanged = true;
        }

        if (textChanged) {
          ReconstructText(&s->doc_arena, editor);
          UpdateLogInDB(s, editor->text);
          editor->snapToCursor = 2;
        }
      }
    }
  } else {
    updateNotification(s, StringStatic("VOICE ERROR"));
  }

  Vector2 mPos = GetMousePosition();
  SetMouseCursor(MOUSE_CURSOR_DEFAULT);

  // Handle element dragging and resizing
  int draggingIdx = -1;
  int resizingIdx = -1;
  for (int i = 0; i < MAX_ELEMENTS; i++) {
    if (s->elements[i].kind == ELEM_NOTHING)
      continue;
    if (s->elements[i].isDragging)
      draggingIdx = i;
    if (s->elements[i].isResizing)
      resizingIdx = i;
  }

  if (draggingIdx != -1) {
    Element *e = &s->elements[draggingIdx];
    SetMouseCursor(MOUSE_CURSOR_RESIZE_ALL);
    if (IsMouseButtonDown(MOUSE_BUTTON_LEFT)) {
      e->position.x = (int)(mPos.x - e->dragOffsetX);
      e->position.y = (int)(mPos.y - e->dragOffsetY);
    } else {
      e->isDragging = false;
    }
  } else if (resizingIdx != -1) {
    Element *e = &s->elements[resizingIdx];
    SetMouseCursor(MOUSE_CURSOR_RESIZE_NWSE);
    if (IsMouseButtonDown(MOUSE_BUTTON_LEFT)) {
      float newWidth = mPos.x - e->position.x - e->dragOffsetX;
      float newHeight = mPos.y - e->position.y - e->dragOffsetY;
      if (newWidth < 20.0f)
        newWidth = 20.0f;
      if (newHeight < 20.0f)
        newHeight = 20.0f;

      // Recreate render texture for sphere if dimensions changed
      if (e->kind == ELEM_SPHERE && ((int)newWidth != (int)*e->width ||
                                     (int)newHeight != (int)*e->height)) {
        UnloadRenderTexture(e->renderTexture);
        e->renderTexture = LoadRenderTexture((int)newWidth, (int)newHeight);
      }

      *e->width = newWidth;
      *e->height = newHeight;
    } else {
      e->isResizing = false;
    }
  } else {
    // Find which element to interact with (reverse order for top-most)
    if (s->is_editing) {
      for (int i = MAX_ELEMENTS - 1; i >= 0; i--) {
        Element *e = &s->elements[i];
        if (e->kind == ELEM_NOTHING)
          continue;

        Rectangle r = GetElementBoundingBox(e);

        // Drag handle at top-left
        Rectangle dragHandle = {r.x - 8, r.y - 8, 16, 16};
        // Resize handle at bottom-right
        Rectangle resizeHandle = {r.x + r.width - 8, r.y + r.height - 8, 16,
                                  16};

        if (CheckCollisionPointRec(mPos, resizeHandle)) {
          SetMouseCursor(MOUSE_CURSOR_RESIZE_NWSE);
          if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT)) {
            e->isResizing = true;
            e->dragOffsetX = mPos.x - (e->position.x + *e->width);
            e->dragOffsetY = mPos.y - (e->position.y + *e->height);
            break;
          }
        } else if (CheckCollisionPointRec(mPos, dragHandle)) {
          SetMouseCursor(MOUSE_CURSOR_RESIZE_ALL);
          if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT)) {
            e->isDragging = true;
            e->dragOffsetX = mPos.x - e->position.x;
            e->dragOffsetY = mPos.y - e->position.y;
            break;
          }
        }
      }
    }
  }
  for (int i = 0; i < MAX_ELEMENTS; i++) {
    Element *e = &s->elements[i];
    bool isHovering =
        CheckCollisionPointRec(GetMousePosition(), GetElementBoundingBox(e));
    if (isHovering) {
      if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON)) {
        switch (e->on_click) {
        case ACTION_DEBUG:
          s->debug = !s->debug;
          break;
        case ACTION_EDIT:
          s->is_editing = !s->is_editing;
          break;
        case ACTION_RESET:
          Reload(s, true);
          break;
        case ACTION_VOICE_INPUT:
          ToggleVoiceRecording(s);
          break;
        case ACTION_PRINT_DB:
          printf("Executing SQL query to print database entries...\n");
          ExecSQL(s, StringStatic("SELECT * FROM entries;"),
                  StringStatic("Done"));
          break;
        case ACTION_LOAD_HYPERMEDIA:
          if (e->text.data && (strncmp(e->text.data, "http://", 7) == 0 ||
                               strncmp(e->text.data, "https://", 8) == 0 ||
                               strncmp(e->text.data, "file://", 7) == 0 ||
                               strstr(e->text.data, ".html") != NULL)) {
            LoadHypermediaDocument(s, e->text);
          } else {
            LoadHypermediaDocument(s, StringStatic("file://document.html"));
          }
          break;
        default:
          break;
        }
      }
    }

    switch (s->elements[i].kind) {
    case ELEM_RECTANGLE:
      if (isHovering) {
        s->elements[i].color =
            ColorBrightness(s->elements[i].originalColor, 0.2f);
        clickOrHoverNotification(s, i, StringStatic("element"));
      } else {
        s->elements[i].color = s->elements[i].originalColor;
      }
      break;
    case ELEM_ELBOW:
      switch (s->elements[i].elbowOrientation) {
      case 0:
        if (CheckCollisionPointRec(
                GetMousePosition(),
                (Rectangle){.x = s->elements[i].position.x,
                            .y = s->elements[i].position.y,
                            .width = *(s->elements[i].width),
                            .height = *(s->elements[i].height) + s->barHeight +
                                      s->innerRadius}) ||
            CheckCollisionPointRec(
                GetMousePosition(),
                (Rectangle){.x = s->elements[i].position.x,
                            .y = s->elements[i].position.y,
                            .width = s->columnWidth + s->barWidth,
                            .height = s->barHeight})) {
          s->elements[i].color =
              ColorBrightness(s->elements[i].originalColor, 0.2f);
          clickOrHoverNotification(s, i, StringStatic("elbow element"));
        } else {
          s->elements[i].color = s->elements[i].originalColor;
        }
        break;
      case 1:
        TODO;
        break;
      case 2:
        break;
      case 3:
        if (CheckCollisionPointRec(
                GetMousePosition(),
                (Rectangle){.x = s->elements[i].position.x,
                            .y = s->elements[i].position.y,
                            .width = *(s->elements[i].width),
                            .height = *(s->elements[i].height) + s->barHeight +
                                      s->innerRadius}) ||
            CheckCollisionPointRec(
                GetMousePosition(),
                (Rectangle){.x = s->elements[i].position.x,
                            .y = s->elements[i].position.y + s->columnHeight +
                                 s->innerRadius,
                            .width = s->columnWidth + s->barWidth,
                            .height = s->barHeight})) {
          s->elements[i].color =
              ColorBrightness(s->elements[i].originalColor, 0.2f);
          clickOrHoverNotification(s, i, StringStatic("elbow element"));
        } else {
          s->elements[i].color = s->elements[i].originalColor;
        }
        break;
      }
      break;
    case ELEM_BUTTON: {
      VoiceRecApi *vapi = (VoiceRecApi *)s->voiceApi;
      bool isRecording =
          (vapi && vapi->IsRecording() && e->on_click == ACTION_VOICE_INPUT);
      if (isHovering) {
        if (isRecording) {
          s->elements[i].color = (Color){255, 100, 100, 255};
        } else {
          s->elements[i].color =
              ColorBrightness(s->elements[i].originalColor, 0.2f);
        }
        clickOrHoverNotification(s, i, StringStatic("button element"));
      } else {
        if (isRecording) {
          s->elements[i].color = RED;
        } else {
          s->elements[i].color = s->elements[i].originalColor;
        }
      }
    } break;

    case ELEM_TEXT:
      break;
    case ELEM_TEXT_EDITOR: {
      float scrollbarX = e->position.x + *e->width + 25;
      float scrollbarY = e->position.y;
      float scrollbarWidth = 18.0f;
      float scrollbarHeight = *e->height;
      Rectangle activeRec = (Rectangle){.x = e->position.x,
                                        .y = e->position.y,
                                        .width = *e->width + 55,
                                        .height = *e->height};

      if (CheckCollisionPointRec(GetMousePosition(), activeRec)) {
        clickOrHoverNotification(s, i, StringStatic("text box element"));
        if (!e->isFocused)
          e->color = ColorBrightness(e->originalColor, 0.2f);
        e->isFocused = true;

        // Mouse wheel scrolling
        float wheelMove = GetMouseWheelMove();
        if (wheelMove != 0.0f) {
          e->scrollY -=
              wheelMove * 30.0f; // Scroll speed: 30 pixels per wheel tick
          ClampScrollY(e);
        }

        // Click handling
        if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT)) {
          Rectangle upButton = (Rectangle){scrollbarX, scrollbarY,
                                           scrollbarWidth, scrollbarWidth};
          Rectangle downButton = (Rectangle){
              scrollbarX, scrollbarY + scrollbarHeight - scrollbarWidth,
              scrollbarWidth, scrollbarWidth};
          Rectangle track = (Rectangle){
              scrollbarX, scrollbarY + scrollbarWidth + 5, scrollbarWidth,
              scrollbarHeight - 2 * scrollbarWidth - 10};
          Vector2 mPos = GetMousePosition();

          if (CheckCollisionPointRec(mPos, upButton)) {
            e->scrollY -= 30.0f;
            ClampScrollY(e);
          } else if (CheckCollisionPointRec(mPos, downButton)) {
            e->scrollY += 30.0f;
            ClampScrollY(e);
          } else if (CheckCollisionPointRec(mPos, track)) {
            float visibleRatio = *e->height / e->textHeight;
            if (visibleRatio > 1.0f)
              visibleRatio = 1.0f;
            float handleHeight = visibleRatio * track.height;
            if (handleHeight < 20.0f)
              handleHeight = 20.0f;

            float scrollRange = e->textHeight - *e->height;
            float handleY = track.y;
            if (scrollRange > 0.0f) {
              handleY +=
                  (e->scrollY / scrollRange) * (track.height - handleHeight);
            }
            Rectangle handle =
                (Rectangle){scrollbarX, handleY, scrollbarWidth, handleHeight};

            if (CheckCollisionPointRec(mPos, handle)) {
              e->draggingScrollbar = true;
              e->dragStartY = mPos.y;
              e->dragStartScrollY = e->scrollY;
            } else {
              // Jump scroll handle to clicked position
              float clickY = mPos.y;
              float relativeY = clickY - track.y - handleHeight / 2.0f;
              float pct = relativeY / (track.height - handleHeight);
              if (pct < 0.0f)
                pct = 0.0f;
              if (pct > 1.0f)
                pct = 1.0f;
              if (scrollRange > 0.0f) {
                e->scrollY = pct * scrollRange;
              } else {
                e->scrollY = 0.0f;
              }

              e->draggingScrollbar = true;
              e->dragStartY = clickY;
              e->dragStartScrollY = e->scrollY;
            }
          }
        }
      } else {
        if (!e->draggingScrollbar) {
          e->isFocused = false;
          e->color = e->originalColor;
        }
      }

      // Active dragging logic (independent of mouse hovering over activeRec)
      if (e->draggingScrollbar) {
        if (IsMouseButtonDown(MOUSE_BUTTON_LEFT)) {
          float trackHeight = *e->height - 2 * scrollbarWidth - 10;
          float visibleRatio = *e->height / e->textHeight;
          if (visibleRatio > 1.0f)
            visibleRatio = 1.0f;
          float handleHeight = visibleRatio * trackHeight;
          if (handleHeight < 20.0f)
            handleHeight = 20.0f;

          float dragRange = trackHeight - handleHeight;
          if (dragRange > 0.0f) {
            float deltaY = GetMousePosition().y - e->dragStartY;
            float scrollRange = e->textHeight - *e->height;
            float deltaScrollY = (deltaY / dragRange) * scrollRange;
            e->scrollY = e->dragStartScrollY + deltaScrollY;

            // Clamp
            ClampScrollY(e);
          }
        } else {
          e->draggingScrollbar = false;
        }
      }

      // Keyboard input & editing logic
      if (e->isFocused) {
        e->textSelectedFramesCounter++;
        Rectangle scrollbarRec = (Rectangle){scrollbarX, scrollbarY,
                                             scrollbarWidth, scrollbarHeight};

        if (CheckCollisionPointRec(mPos, scrollbarRec)) {
          SetMouseCursor(MOUSE_CURSOR_DEFAULT);
        } else if (draggingIdx == -1 && resizingIdx == -1) {
          SetMouseCursor(MOUSE_CURSOR_IBEAM);
        }

        bool shiftDown =
            IsKeyDown(KEY_LEFT_SHIFT) || IsKeyDown(KEY_RIGHT_SHIFT);

        // Get char pressed (unicode character) on the queue
        int key = GetCharPressed();
        bool textChanged = false;

        // Check if more characters have been pressed on the same frame
        while (key > 0) {
          // NOTE: Only allow keys in range [32..125]
          if ((key >= 32) && (key <= 125) && (e->textLen < MAX_INPUT_CHARS)) {
            if (DeleteSelection(e)) {
              textChanged = true;
            }
            GapInsertChar(&s->doc_arena, e, (char)key);
            textChanged = true;
            e->snapToCursor = 2;
          }

          key = GetCharPressed(); // Check next character in the queue
        }

        if ((IsKeyDown(KEY_LEFT_CONTROL) || IsKeyDown(KEY_LEFT_SUPER)) &&
            IsKeyPressed(KEY_C)) {
          if (e->selectTextLength <= 0) {
            SetClipboardText(e->text.data ? e->text.data : "");
            updateNotification(s, StringStatic("All text copied to clipboard"));
            printf("Copied all text to clipboard: |%s|\n",
                   e->text.data ? e->text.data : "");
          } else {
            int selStart = e->selectTextLength > 0
                               ? e->selectTextStart
                               : e->selectTextStart + e->selectTextLength;
            int selLength = e->selectTextLength > 0 ? e->selectTextLength
                                                    : -e->selectTextLength;
            char *selectedText = (char *)arena_alloc(&s->scratch_arena, selLength + 1);
            memcpy(selectedText, e->text.data + selStart, selLength);
            selectedText[selLength] = '\0';
            SetClipboardText(selectedText);
            printf("Copied to clipboard: |%s|\n", selectedText);
            updateNotification(
                s, StringStatic("Selected text copied to clipboard"));
          }
        }
        if ((IsKeyDown(KEY_LEFT_CONTROL) || IsKeyDown(KEY_LEFT_SUPER)) &&
            IsKeyPressed(KEY_V)) {
          const char *clipboardText = GetClipboardText();
          if (clipboardText) {
            if (DeleteSelection(e)) {
              textChanged = true;
            }
            int clipboardTextLen = strlen(clipboardText);
            printf("Clipboard text length: %d\n", clipboardTextLen);
            for (int j = 0; j < clipboardTextLen; j++) {
              GapInsertChar(&s->doc_arena, e, clipboardText[j]);
            }
            textChanged = true;
            e->snapToCursor = 2;
            printf("Pasted from clipboard: |%s|\n", clipboardText);
            updateNotification(s, StringStatic("Clipboard text pasted"));
          }
        }

        if (IsKeyPressed(KEY_ENTER)) {
          if (DeleteSelection(e)) {
            textChanged = true;
          }
          GapInsertChar(&s->doc_arena, e, '\n');
          textChanged = true;
          e->snapToCursor = 2;
        }

        // Cursor movements
        if (IsKeyDown(KEY_LEFT)) {
          if (!e->isMovingCursorLeft)
            e->moveCursorLeftStartTime = GetTime();
          e->isMovingCursorLeft = true;
          if (IsKeyPressed(KEY_LEFT) ||
              (GetTime() - e->moveCursorLeftStartTime > 0.4f &&
               e->textSelectedFramesCounter % 2 == 0)) {
            StartTextSelection(e, shiftDown);
            bool isWordJump =
                IsKeyDown(KEY_LEFT_CONTROL) || IsKeyDown(KEY_RIGHT_CONTROL) ||
                IsKeyDown(KEY_LEFT_SUPER) || IsKeyDown(KEY_RIGHT_SUPER);
            if (isWordJump) {
              int target = e->gapStart;
              if (target > 0) {
                if (e->text.data[target - 1] == '\n') {
                  target--;
                } else {
                  while (target > 0 && !IsWordChar(e->text.data[target - 1]) &&
                         e->text.data[target - 1] != '\n') {
                    target--;
                  }
                  while (target > 0 && IsWordChar(e->text.data[target - 1])) {
                    target--;
                  }
                }
              }
              MoveGap(e, target);
            } else {
              MoveGap(e, e->gapStart - 1);
            }
            EndTextSelection(e, shiftDown);
          }
        } else {
          e->isMovingCursorLeft = false;
        }

        if (IsKeyDown(KEY_RIGHT)) {
          if (!e->isMovingCursorRight)
            e->moveCursorRightStartTime = GetTime();
          e->isMovingCursorRight = true;
          if (IsKeyPressed(KEY_RIGHT) ||
              (GetTime() - e->moveCursorRightStartTime > 0.4f &&
               e->textSelectedFramesCounter % 2 == 0)) {
            StartTextSelection(e, shiftDown);
            bool isWordJump =
                IsKeyDown(KEY_LEFT_CONTROL) || IsKeyDown(KEY_RIGHT_CONTROL) ||
                IsKeyDown(KEY_LEFT_SUPER) || IsKeyDown(KEY_RIGHT_SUPER);
            if (isWordJump) {
              int target = e->gapStart;
              if (target < e->textLen) {
                if (e->text.data[target] == '\n') {
                  target++;
                } else {
                  while (target < e->textLen &&
                         !IsWordChar(e->text.data[target]) &&
                         e->text.data[target] != '\n') {
                    target++;
                  }
                  while (target < e->textLen &&
                         IsWordChar(e->text.data[target])) {
                    target++;
                  }
                }
              }
              MoveGap(e, target);
            } else {
              MoveGap(e, e->gapStart + 1);
            }
            EndTextSelection(e, shiftDown);
          }
        } else {
          e->isMovingCursorRight = false;
        }
        bool triggerMoveUp = false;
        if (IsKeyDown(KEY_UP)) {
          if (!e->isMovingCursorUp)
            e->moveCursorUpStartTime = GetTime();
          e->isMovingCursorUp = true;
          if (IsKeyPressed(KEY_UP) ||
              (GetTime() - e->moveCursorUpStartTime > 0.4f &&
               e->textSelectedFramesCounter % 2 == 0)) {
            triggerMoveUp = true;
          }
        } else {
          e->isMovingCursorUp = false;
        }

        bool triggerMoveDown = false;
        if (IsKeyDown(KEY_DOWN)) {
          if (!e->isMovingCursorDown)
            e->moveCursorDownStartTime = GetTime();
          e->isMovingCursorDown = true;
          if (IsKeyPressed(KEY_DOWN) ||
              (GetTime() - e->moveCursorDownStartTime > 0.4f &&
               e->textSelectedFramesCounter % 2 == 0)) {
            triggerMoveDown = true;
          }
        } else {
          e->isMovingCursorDown = false;
        }

        if (triggerMoveUp || triggerMoveDown) {
          int lineStarts[1024];
          int numLines = GetLines(e->text, lineStarts, 1024);
          int currLine = GetLineForIndex(e->gapStart, lineStarts, numLines);
          int col = e->gapStart - lineStarts[currLine];

          StartTextSelection(e, shiftDown);

          if (triggerMoveUp) {
            if (currLine > 0) {
              int targetLineLen =
                  lineStarts[currLine] - 1 - lineStarts[currLine - 1];
              int targetCol = col < targetLineLen ? col : targetLineLen;
              MoveGap(e, lineStarts[currLine - 1] + targetCol);
            }
          } else if (triggerMoveDown) {
            if (currLine < numLines - 1) {
              int targetLineLen = 0;
              if (currLine + 1 < numLines - 1) {
                targetLineLen =
                    lineStarts[currLine + 2] - 1 - lineStarts[currLine + 1];
              } else {
                targetLineLen = e->textLen - lineStarts[currLine + 1];
              }
              int targetCol = col < targetLineLen ? col : targetLineLen;
              MoveGap(e, lineStarts[currLine + 1] + targetCol);
            }
          }

          EndTextSelection(e, shiftDown);
        }
        if (IsKeyPressed(KEY_HOME)) {
          StartTextSelection(e, shiftDown);
          int lineStarts[1024];
          int numLines = GetLines(e->text, lineStarts, 1024);
          int currLine = GetLineForIndex(e->gapStart, lineStarts, numLines);
          MoveGap(e, lineStarts[currLine]);
          EndTextSelection(e, shiftDown);
        }
        if (IsKeyPressed(KEY_END)) {
          StartTextSelection(e, shiftDown);
          int lineStarts[1024];
          int numLines = GetLines(e->text, lineStarts, 1024);
          int currLine = GetLineForIndex(e->gapStart, lineStarts, numLines);
          int targetIndex = (currLine < numLines - 1)
                                ? lineStarts[currLine + 1] - 1
                                : e->textLen;
          MoveGap(e, targetIndex);
          EndTextSelection(e, shiftDown);
        }

        if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT) &&
            !CheckCollisionPointRec(mPos, scrollbarRec)) {
          e->selectingText = true;
          int clickedIndex = GetCharIndexAtMouse(
              s, s->font, e->text,
              (Vector2){e->position.x + 5, e->position.y + 5 - e->scrollY},
              e->textSize, 2.0, mPos, *e->width);
          if (shiftDown) {
            if (e->selectTextStart == -1) {
              e->selectTextStart = e->gapStart;
            }
          } else {
            e->selectTextStart = clickedIndex;
          }
          e->selectTextEnd = clickedIndex;
          e->selectTextLength = e->selectTextEnd - e->selectTextStart;
          MoveGap(e, clickedIndex);
          e->snapToCursor = 2;
        }

        if (IsKeyDown(KEY_LEFT_CONTROL) && IsKeyPressed(KEY_A)) {
          e->selectingText = true;
          e->selectTextStart = 0;
          e->selectTextEnd = e->textLen;
          e->selectTextLength = e->textLen;
        }

        if (e->selectingText) {
          int textEnd = GetCharIndexAtMouse(
              s, s->font, e->text,
              (Vector2){e->position.x + 5, e->position.y + 5 - e->scrollY},
              e->textSize, 2.0, mPos, *e->width);
          e->selectTextEnd = textEnd;
          e->selectTextLength = e->selectTextEnd - e->selectTextStart;

          if (IsMouseButtonReleased(MOUSE_BUTTON_LEFT)) {
            e->selectingText = false;
          }
        }

        if (e->selectTextStart >= 0 && e->selectTextEnd != e->selectTextStart &&
            (IsKeyPressed(KEY_DELETE) || IsKeyPressed(KEY_BACKSPACE))) {
          DeleteSelection(e);
          textChanged = true;
          e->snapToCursor = 2;
        } else if (IsKeyDown(KEY_BACKSPACE)) {
          if (!e->isDeletingText)
            e->deletingTextStartTime = GetTime();
          e->isDeletingText = true;
          if (IsKeyPressed(KEY_BACKSPACE) ||
              (GetTime() - e->deletingTextStartTime > 0.5f &&
               e->textSelectedFramesCounter % 10 == 0)) {
            GapDeleteBack(e);
            textChanged = true;
            e->snapToCursor = 2;
          }
        } else if (IsKeyDown(KEY_DELETE)) {
          if (!e->isDeletingText)
            e->deletingTextStartTime = GetTime();
          e->isDeletingText = true;
          if (IsKeyPressed(KEY_DELETE) ||
              (GetTime() - e->deletingTextStartTime > 0.5f &&
               e->textSelectedFramesCounter % 10 == 0)) {
            GapDeleteForward(e);
            textChanged = true;
            e->snapToCursor = 2;
          }
        }

        if (IsKeyUp(KEY_BACKSPACE) && IsKeyUp(KEY_DELETE)) {
          e->isDeletingText = false;
          e->deletingTextStartTime = 0;
        }

        if (textChanged) {
          ReconstructText(&s->doc_arena, e);
          UpdateLogInDB(s, e->text);
        }

        // Auto-scroll to cursor
        if (e->snapToCursor > 0) {
          e->snapToCursor--;
          float lineHeight = (s->font.baseSize + (float)s->font.baseSize / 2) *
                             (e->textSize / (float)s->font.baseSize);
          if (e->cursorY > e->scrollY + *e->height - lineHeight) {
            e->scrollY = e->cursorY - *e->height + lineHeight;
          } else if (e->cursorY < e->scrollY) {
            e->scrollY = e->cursorY;
          }
        }

        // Clamp scrollY to valid range
        ClampScrollY(e);
      } else {
        e->textSelectedFramesCounter = 0;
      }
      break;
    }
    case ELEM_SPHERE: {
      if (isHovering) {
        e->color = ColorBrightness(GREEN, 0.8f);
        clickOrHoverNotification(s, i, StringStatic("sphere element"));
        if (IsMouseButtonDown(MOUSE_BUTTON_LEFT)) {
          UpdateCamera(&e->camera, CAMERA_THIRD_PERSON);
        } else {
          e->rotation += 0.05f;
        }
      } else {
        e->color = e->originalColor;
        e->rotation += 0.1f;
      }
      e->rotation = fmodf(e->rotation, 360.0f);
    }
    case ELEM_NOTHING:
    case ELEM_TOTAL_KINDS:
      break;
    }
  }
}



// Draw text using font inside rectangle limits with support for text selection


// --- Scripted demo driver (only runs when the LCARS_DEMO env var is set). ---
// Drives the three headline features for a screen recording: voice dictation,
// dragging an element, and resizing the editor. Called AFTER Update() so the
// drag/resize flags it sets survive the real input pass (which clears them).
static void DemoTick(State *s) {
  Element *editor = NULL, *voiceBtn = NULL, *earth = NULL;
  for (int i = 0; i < s->numElements; i++) {
    Element *e = &s->elements[i];
    if (!editor && e->kind == ELEM_TEXT_EDITOR)
      editor = e;
    if (!voiceBtn && e->kind == ELEM_BUTTON &&
        e->on_click == ACTION_VOICE_INPUT)
      voiceBtn = e;
    if (!earth && e->kind == ELEM_SPHERE)
      earth = e;
  }

  static bool cleared = false;
  if (!cleared && editor) {
    editor->gapStart = 0;
    editor->gapEnd = editor->textCapacity;
    editor->selectTextStart = -1;
    editor->selectTextEnd = -1;
    editor->selectTextLength = 0;
    ReconstructText(&s->doc_arena, editor);
    cleared = true;
  }

  // Idle (showing the clean initial frame) until the capture script drops the
  // "go" sentinel, so the recording starts exactly when the action does.
  static double t0 = -1.0;
  if (t0 < 0.0) {
    FILE *gof = fopen("/tmp/lcars_go", "r");
    if (!gof)
      return;
    fclose(gof);
    t0 = GetTime();
  }
  double t = GetTime() - t0;

  static const char *logLine =
      "CAPTAIN'S LOG, STARDATE 79341.2. WE HAVE ENTERED THE NEUTRAL ZONE. ";
  int L = (int)strlen(logLine);
  static int typed = 0;
  static iVec2 earthHome;
  static bool earthHomeSet = false;
  static float edW0 = 0, edH0 = 0, demoEdW = 0, demoEdH = 0;
  static bool edSized = false;

  const double TYPE_START = 0.6, CPS = 24.0;
  double typeDone = TYPE_START + (double)L / CPS;
  double tEdit = typeDone + 0.6;
  double tDrag = tEdit + 0.2, dragDur = 1.8;
  double tResize = tDrag + dragDur + 0.3, resizeDur = 1.6;

  // Phase 1: voice dictation - button lights up red, text streams in.
  if (t > 0.4 && t < typeDone + 0.3 && voiceBtn) {
    StringAssignStatic(&voiceBtn->text, TEXT_RECORDING);
    voiceBtn->color = RED;
  }
  if (t > TYPE_START && editor) {
    int target = (int)((t - TYPE_START) * CPS);
    if (target > L)
      target = L;
    bool changed = false;
    while (typed < target) {
      GapInsertChar(&s->doc_arena, editor, logLine[typed]);
      typed++;
      changed = true;
    }
    if (changed) {
      ReconstructText(&s->doc_arena, editor);
      editor->snapToCursor = 2;
      int s0 = typed > 22 ? typed - 22 : 0;
      char note[80];
      snprintf(note, sizeof(note), "[Voice: \"...%.*s\"]", typed - s0,
               logLine + s0);
      updateNotification(s, StringStatic(note));
    }
  }
  if (t > typeDone + 0.3 && voiceBtn) {
    StringAssignStatic(&voiceBtn->text, TEXT_VOICE_INPUT);
    voiceBtn->color = voiceBtn->originalColor;
  }

  // Phase 2: enter edit mode, then drag the Earth to a new spot.
  if (t > tEdit) {
    s->is_editing = true;
    updateNotification(s, StringStatic("EDIT MODE: drag + resize"));
  }
  if (earth) {
    if (!earthHomeSet) {
      earthHome = earth->position;
      earthHomeSet = true;
    }
    if (t > tDrag && t < tDrag + dragDur) {
      double p = (t - tDrag) / dragDur;
      double e = p * p * (3.0 - 2.0 * p); // smoothstep ease
      earth->isDragging = true;
      earth->position.x = (int)(earthHome.x - 330.0 * e);
      earth->position.y = (int)(earthHome.y + 30.0 * e);
    } else if (t >= tDrag + dragDur) {
      earth->isDragging = false;
    }
  }

  // Phase 3: resize the editor panel via its bottom-right handle.
  if (editor && t > tResize) {
    if (!edSized) {
      edW0 = *editor->width;
      edH0 = *editor->height;
      demoEdW = edW0;
      demoEdH = edH0;
      editor->width = &demoEdW;
      editor->height = &demoEdH;
      edSized = true;
    }
    if (t < tResize + resizeDur) {
      double p = (t - tResize) / resizeDur;
      double e = p * p * (3.0 - 2.0 * p);
      editor->isResizing = true;
      demoEdW = edW0 + 140.0f * (float)e;
      demoEdH = edH0 + 80.0f * (float)e;
    } else {
      editor->isResizing = false;
    }
  }
}

void UpdateDrawFrame(State *s) {
  if (IsKeyDown(KEY_LEFT_CONTROL) && IsKeyPressed(KEY_D)) {
    s->debug = !s->debug;
  }
  if (IsKeyDown(KEY_LEFT_CONTROL) && !IsKeyDown(KEY_LEFT_SHIFT) &&
      IsKeyPressed(KEY_R)) {
    Init(s, false);
  }
  if (IsKeyDown(KEY_LEFT_CONTROL) &&
      (IsKeyPressed(KEY_H) || IsKeyPressed(KEY_E))) {
    s->is_editing = !s->is_editing;
  }

  // Toggle voice recognition via Ctrl+Space
  if (IsKeyDown(KEY_LEFT_CONTROL) && IsKeyPressed(KEY_SPACE)) {
    ToggleVoiceRecording(s);
  }

  Update(s);
  if (getenv("LCARS_DEMO"))
    DemoTick(s);
  Vector2 mPos = GetMousePosition();

  // Pre render on texture areas or any other requirements for first pass:
  for (int i = 0; i < MAX_ELEMENTS; i++) {
    Element *e = &s->elements[i];
    if (e->kind == ELEM_NOTHING)
      continue; // Skip uninitialized elements
    switch (e->kind) {
    case ELEM_SPHERE: {
      BeginTextureMode(e->renderTexture);
      ClearBackground(BLACK);
      BeginMode3D(e->camera);
      DrawModelEx(e->model, e->position3, (Vector3){0.0f, 1.0f, 0.0f},
                  e->rotation, (Vector3){2.0f, 2.0f, 2.0f}, e->color);

      if (s->debug) {
        DrawGrid(10, 2.0f);
      }
      EndMode3D();
      EndTextureMode();
      break;
    }
    case ELEM_RECTANGLE:
    case ELEM_BUTTON:
    case ELEM_TEXT:
    case ELEM_TEXT_EDITOR:
    case ELEM_ELBOW:
    case ELEM_NOTHING:
    case ELEM_TOTAL_KINDS:
      break;
    }
  }

  BeginDrawing();
  ClearBackground(BLACK);

  for (int i = 0; i < MAX_ELEMENTS; i++) {
    Element *e = &s->elements[i];
    if (e->kind == ELEM_NOTHING)
      continue; // Skip uninitialized elements
    switch (e->kind) {
    case ELEM_RECTANGLE:
      DrawRectangle(e->position.x, e->position.y, *e->width, *e->height,
                    e->color);
      break;
    case ELEM_ELBOW:
      DrawElbow(e->position.x, e->position.y, *e->width, *e->height,
                s->barWidth, s->barHeight, s->innerRadius, e->color,
                e->elbowOrientation, s->debug);
      break;
    case ELEM_BUTTON:
      // printf("Drawing button element %d at (%.2d, %.2d) with size (%.2f,
      // %.2f)\n", i, e->position.x, e->position.y, *e->width, *e->height);
      DrawRectangleRounded((Rectangle){.x = e->position.x,
                                       .y = e->position.y,
                                       .width = *e->width,
                                       .height = *e->height},
                           0.9f, 4, e->color);
      break;
    case ELEM_TEXT:
      DrawText(e->text.data ? e->text.data : "", e->position.x, e->position.y,
               e->textSize, e->color);
      break;
    case ELEM_TEXT_EDITOR: {
      DrawRectangleLines(e->position.x, e->position.y, *e->width + 10,
                         *e->height, LCARS_BLUE);
      Rectangle r = (Rectangle){e->position.x + 5, e->position.y + 5, *e->width,
                                *e->height};
      BeginScissorMode((int)r.x, (int)r.y, (int)r.width, (int)r.height);
      DrawTextBoxed(s, e, s->font, e->text, r, e->textSize, 2.0f, false,
                    e->color, &e->textHeight, &e->cursorY, e->gapStart);
      EndScissorMode();

      // Render scrollbar
      float scrollbarX = e->position.x + *e->width + 25;
      float scrollbarY = e->position.y;
      float scrollbarWidth = 18.0f;
      float scrollbarHeight = *e->height;

      Rectangle upButton =
          (Rectangle){scrollbarX, scrollbarY, scrollbarWidth, scrollbarWidth};
      Rectangle downButton =
          (Rectangle){scrollbarX, scrollbarY + scrollbarHeight - scrollbarWidth,
                      scrollbarWidth, scrollbarWidth};
      Rectangle track = (Rectangle){scrollbarX, scrollbarY + scrollbarWidth + 5,
                                    scrollbarWidth,
                                    scrollbarHeight - 2 * scrollbarWidth - 10};

      // Draw up/down buttons
      DrawRectangleRounded(upButton, 0.5f, 4, e->color);
      DrawRectangleRounded(downButton, 0.5f, 4, e->color);

      // Draw Up/Down arrow indicators
      DrawText("^", upButton.x + upButton.width / 2 - MeasureText("^", 12) / 2,
               upButton.y + upButton.height / 2 - 6, 12, BLACK);
      DrawText("v",
               downButton.x + downButton.width / 2 - MeasureText("v", 12) / 2,
               downButton.y + downButton.height / 2 - 6, 12, BLACK);

      // Draw track background
      DrawRectangleRounded(track, 0.5f, 4, (Color){30, 30, 30, 255});

      // Calculate and draw handle
      float visibleRatio = *e->height / e->textHeight;
      if (visibleRatio > 1.0f)
        visibleRatio = 1.0f;
      float handleHeight = visibleRatio * track.height;
      if (handleHeight < 20.0f)
        handleHeight = 20.0f;

      float scrollRange = e->textHeight - *e->height;
      float handleY = track.y;
      if (scrollRange > 0.0f) {
        handleY += (e->scrollY / scrollRange) * (track.height - handleHeight);
      }
      Rectangle handle =
          (Rectangle){scrollbarX, handleY, scrollbarWidth, handleHeight};

      bool hoverHandle = CheckCollisionPointRec(GetMousePosition(), handle);
      Color handleColor =
          (hoverHandle || e->draggingScrollbar) ? LCARS_YELLOW : LCARS_ORANGE;
      DrawRectangleRounded(handle, 0.5f, 4, handleColor);

      break;
    }
    case ELEM_SPHERE: {
      DrawTextureRec(e->renderTexture.texture,
                     (Rectangle){0, 0, *e->width, *e->height},
                     (Vector2){e->position.x, e->position.y}, WHITE);

      if (s->debug) {
        Vector2 screenPos = {e->position.x, e->position.y};

        // Draw Text - position, rotation
        DrawText(TextFormat("Pos: (%.2f, %.2f, %.2f)", e->position3.x,
                            e->position3.y, e->position3.z),
                 screenPos.x, screenPos.y, 10, WHITE);
        DrawText(TextFormat("Rot: (%.2f)", e->rotation), screenPos.x,
                 screenPos.y + 20, 10, WHITE);

        // Camera
        DrawText(TextFormat("Camera Pos: (%.2f, %.2f, %.2f)",
                            e->camera.position.x, e->camera.position.y,
                            e->camera.position.z),
                 screenPos.x, screenPos.y + 40, 10, WHITE);
        DrawText(TextFormat("Camera Target: (%.2f, %.2f, %.2f)",
                            e->camera.target.x, e->camera.target.y,
                            e->camera.target.z),
                 screenPos.x, screenPos.y + 60, 10, WHITE);
        DrawText(TextFormat("Camera Up: (%.2f, %.2f, %.2f)", e->camera.up.x,
                            e->camera.up.y, e->camera.up.z),
                 screenPos.x, screenPos.y + 80, 10, WHITE);
        DrawText(TextFormat("Camera FOV: %.2f", e->camera.fovy), screenPos.x,
                 screenPos.y + 100, 10, WHITE);
        DrawText(TextFormat("Camera Projection: %s",
                            e->camera.projection == CAMERA_PERSPECTIVE
                                ? "Perspective"
                                : "Orthographic"),
                 screenPos.x, screenPos.y + 120, 10, WHITE);
      }
      break;
    }
    case ELEM_NOTHING:
    case ELEM_TOTAL_KINDS:
      break;
    }

    if (e->text.data && e->kind != ELEM_TEXT && e->kind != ELEM_TEXT_EDITOR) {
      int textWidth = MeasureText(e->text.data, e->textSize);
      if (e->kind == ELEM_ELBOW) {
        DrawText(e->text.data, e->position.x + 3 * (*e->width - textWidth) / 4,
                 e->position.y + s->barHeight + s->innerRadius +
                     (*e->height - e->textSize) / 2,
                 e->textSize, BLACK);
      } else {
        DrawText(e->text.data, e->position.x + 3 * (*e->width - textWidth) / 4,
                 e->position.y + (*e->height - e->textSize) / 2 + 10,
                 e->textSize, BLACK);
      }
    }
  }

  if (s->notification.data && s->notificationTimer > 0.0f) {
    s->notificationTimer -= GetFrameTime();
    DrawText(s->notification.data, s->posX + s->columnWidth + s->innerRadius,
             s->posY - 2 * s->columnHeight - s->barHeight, 20, YELLOW);
  } else {
    s->notificationOnElemIdx = -1;
  }

  if (s->debug) {
    DrawFPS(10, 10);
    DrawText(TextFormat("x:%.2f, y:%.2f", mPos.x, mPos.y), mPos.x + 20, mPos.y,
             10, GREEN);
  }

  // Draw interactive handles on top of all elements
  if (s->is_editing) {
    Vector2 mousePos = GetMousePosition();
    for (int i = 0; i < MAX_ELEMENTS; i++) {
      Element *e = &s->elements[i];
      if (e->kind == ELEM_NOTHING)
        break;

      Rectangle r = GetElementBoundingBox(e);
      bool isElementHovered = CheckCollisionPointRec(mousePos, r);

      // Drag handle at top-left
      Rectangle dragHandle = {r.x - 8, r.y - 8, 16, 16};
      // Resize handle at bottom-right
      Rectangle resizeHandle = {r.x + r.width - 8, r.y + r.height - 8, 16, 16};

      bool isHoveredDrag = CheckCollisionPointRec(mousePos, dragHandle);
      bool isHoveredResize = CheckCollisionPointRec(mousePos, resizeHandle);

      // Show handles if hovering the element, or if dragging/resizing it
      if (isElementHovered || e->isDragging || e->isResizing || isHoveredDrag ||
          isHoveredResize) {
        // Draw outline around element
        DrawRectangleLinesEx(
            (Rectangle){r.x - 2, r.y - 2, r.width + 4, r.height + 4}, 1.0f,
            (Color){255, 255, 255, 128});

        // Draw drag handle (top-left circle)
        DrawCircle(r.x, r.y, 6,
                   (e->isDragging || isHoveredDrag)
                       ? LCARS_YELLOW
                       : (Color){155, 155, 255, 200});
        DrawCircleLines(r.x, r.y, 6, BLACK);

        // Draw resize handle (bottom-right triangle)
        DrawTriangle((Vector2){r.x + r.width - 10, r.y + r.height},
                     (Vector2){r.x + r.width, r.y + r.height},
                     (Vector2){r.x + r.width, r.y + r.height - 10},
                     (e->isResizing || isHoveredResize)
                         ? LCARS_YELLOW
                         : (Color){255, 154, 102, 200});
      }
    }
  }

  EndDrawing();
  arena_reset(&s->scratch_arena);
}

#include "lcars_hypermedia.h"



#endif // LCARS_IMPLEMENTATION
