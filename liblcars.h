#ifndef LIBLCARS_H
#define LIBLCARS_H
#define _POSIX_C_SOURCE 200809L
#include "lcars_voice_rec.h"
#include "raylib.h"
#include "raymath.h"
#include "rlgl.h"
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wunused-but-set-variable"
#endif
#include "vendor/raygui.h"
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic pop
#endif
#include "vendor/sqlite3.h"
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "lcars_arena.h"
#include "lcars_base.h"
#include "lcars_string.h"

#include <math.h>

#include "lcars_types.h"

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
static inline bool KeyRepeatFired(KeyRepeat *repeat, int key, float delay,
                                  int frameCounter, int frameModulo);

#ifdef LCARS_IMPLEMENTATION
static void ToggleVoiceRecording(State *s);
static void ClampScrollY(Element *e);
static void NavigateEntryList(State *s, Element *e, int direction);
#endif // LCARS_IMPLEMENTATION

// -----------------------------------------------------------------------------
// Inline Utility Function Implementations
// -----------------------------------------------------------------------------
static inline void updateNotification(State *s, String notificationText) {
  StringAssign(&s->doc_arena, &s->notification, notificationText);
  s->notificationTimer = NOTIFICATION_DURATION;
}

// Tracks a held key and reports whether its action should fire this frame,
// covering both the initial press and the auto-repeat while held down.
// `frameModulo` throttles the repeat rate once `delay` seconds have passed.
static inline bool KeyRepeatFired(KeyRepeat *repeat, int key, float delay,
                                  int frameCounter, int frameModulo) {
  if (!IsKeyDown(key)) {
    repeat->isHeld = false;
    return false;
  }
  if (!repeat->isHeld) {
    repeat->startTime = GetTime();
  }
  repeat->isHeld = true;
  return IsKeyPressed(key) || (GetTime() - repeat->startTime > delay &&
                               frameCounter % frameModulo == 0);
}
// 1
// -----------------------------------------------------------------------------
// Element constructors (In-place)
// -----------------------------------------------------------------------------
static inline void make_rectangle(Element *e) {
  e->kind = ELEM_RECTANGLE;
  e->textLen = e->text.len;
}

static inline void make_elbow(Element *e, int orientation) {
  e->kind = ELEM_ELBOW;
  e->elbowOrientation = orientation;
  e->textLen = e->text.len;
}

static inline void make_button(Element *e) {
  e->kind = ELEM_BUTTON;
  e->textLen = e->text.len;
}

static inline void make_text(Element *e) {
  e->kind = ELEM_TEXT;
  e->width = NULL;
  e->height = NULL;
  e->textLen = e->text.len;
}

static inline void make_text_editor(Arena *doc_arena, Element *e,
                                    String initText) {
  e->kind = ELEM_TEXT_EDITOR;
  if (initText.len == 0 && e->text.len > 0) {
    initText = e->text;
  }

  int textLen = initText.data ? (int)strlen(initText.data) : 0;
  int textCapacity = 4096;
  char *gapBuffer = (char *)arena_alloc(doc_arena, textCapacity + 1);
  if (gapBuffer && initText.data) {
    memcpy(gapBuffer, initText.data, textLen);
  }
  e->gapBuffer = gapBuffer;
  e->gapStart = textLen;
  e->gapEnd = textCapacity;
  e->textCapacity = textCapacity;

  char *textAlloc = (char *)arena_alloc(doc_arena, textLen + 1);
  if (textAlloc && initText.data) {
    memcpy(textAlloc, initText.data, textLen);
    textAlloc[textLen] = '\0';
  }
  e->text.data = textAlloc;
  e->text.len = textLen;
  e->text.is_static = false;

  e->textLen = textLen;
}

static inline void make_sphere(State *s, Element *e, const char *imagePath) {
  e->kind = ELEM_SPHERE;

  Image image = {0};
  if (imagePath && FileExists(imagePath)) {
    image = LoadImage(imagePath);
    ImageFormat(&image, PIXELFORMAT_UNCOMPRESSED_R8G8B8A8);
  }

  int textureStatusIdx = -1;
  for (int i = 0; i < s->numElements; i++) {
    if (s->elements[i].kind == ELEM_RECTANGLE &&
        s->elements[i].position.x == 0 && s->elements[i].position.y == 4) {
      textureStatusIdx = i;
      break;
    }
  }

  if (image.data != NULL) {
    TraceLog(LOG_WARNING, "Texture ready!");
    if (textureStatusIdx != -1) {
      s->elements[textureStatusIdx].text = StringStatic(NULL);
      s->elements[textureStatusIdx].textSize = 0;
    }
    ImageRotateCW(&image);
    ImageFlipVertical(&image);
    ImageFlipHorizontal(&image);
    Texture2D texture = LoadTextureFromImage(image);
    if (!IsTextureValid(texture)) {
      TraceLog(LOG_ERROR, "Texture is invalid!");
      if (textureStatusIdx != -1) {
        s->elements[textureStatusIdx].text =
            StringStatic("Texture is invalid!");
      }
    } else {
      Model model = LoadModelFromMesh(GenMeshSphere(3.0f, 32, 32));
      model.materials[0].maps[MATERIAL_MAP_DIFFUSE].texture = texture;
      model.transform = MatrixRotateX(DEG2RAD * 90.0f);
      e->model = model;
    }
  } else {
    TraceLog(LOG_WARNING, "Texture not ready yet!");
    if (textureStatusIdx != -1) {
      s->elements[textureStatusIdx].text = StringStatic("Texture not ready!");
      s->elements[textureStatusIdx].textSize = 20;
    }
    s->notification = StringStatic("Failed to load image");
  }

  Camera camera = {0};
  camera.position = (Vector3){10.0f, -10.0f, 10.0f};
  camera.target = (Vector3){0.0f, 0.0f, 0.0f};
  camera.up = (Vector3){0.0f, 1.0f, -0.23f};
  camera.fovy = 45.0f;
  camera.projection = CAMERA_PERSPECTIVE;
  e->camera = camera;

  if (e->width && e->height) {
    e->renderTexture = LoadRenderTexture((int)*e->width, (int)*e->height);
  }
}

#ifdef LCARS_IMPLEMENTATION

#include <curl/curl.h>

#define MAX(a, b) ((a) > (b) ? (a) : (b))
#define MIN(a, b) ((a) < (b) ? (a) : (b))

static void ToggleVoiceRecording(State *s) {
  VoiceRecApi *vapi = s->voiceApi;
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

#include "lcars_db.h"
#include "lcars_gap_buffer.h"
#include "lcars_text.h"
#include "lcars_ui.h"

static inline float ClampScrollOffset(float scrollY, float contentHeight,
                                      float viewportHeight) {
  if (scrollY < 0.0f)
    scrollY = 0.0f;
  float maxScroll = contentHeight - viewportHeight;
  if (maxScroll < 0.0f)
    maxScroll = 0.0f;
  if (scrollY > maxScroll)
    scrollY = maxScroll;
  return scrollY;
}

static void ClampScrollY(Element *e) {
  e->scrollY = ClampScrollOffset(e->scrollY, e->textHeight, *e->height);
}

static void NavigateEntryList(State *s, Element *e, int direction) {
  EntryListItem items[32];
  int count = GetEntriesByKind(s, e->selectedKind.data, items, 32);
  int selectedIdx = -1;
  for (int j = 0; j < count; j++) {
    if (items[j].id == e->selectedEntryId) {
      selectedIdx = j;
      break;
    }
  }
  int newIdx = selectedIdx + direction;
  if (newIdx >= 0 && newIdx < count) {
    UpdateEntryContentInDB(s, e->selectedEntryId, e->text);
    e->selectedEntryId = items[newIdx].id;
    String newText = GetEntryContentFromDB(s, e->selectedEntryId);
    LoadEntryIntoEditor(e, newText);
    StringFree(&newText);

    float viewportHeight = *e->height - 45.0f;
    if (direction < 0) { // Up
      float itemTop = newIdx * 90.0f;
      if (itemTop < e->listScrollY) {
        e->listScrollY = itemTop;
      }
    } else { // Down
      float itemBottom = newIdx * 90.0f + 80.0f;
      if (itemBottom > e->listScrollY + viewportHeight) {
        e->listScrollY = itemBottom - viewportHeight;
      }
    }
    e->listScrollY =
        ClampScrollOffset(e->listScrollY, count * 90.0f, viewportHeight);
  }
}

void Init(State *s, bool firstInit) {
  double t_init_start = GetTimeSeconds();

  s->debug = false;
  s->is_editing = false;
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

  printf("Loading hypermedia\n");
  LoadHypermediaDocument(s, StringStatic("file://main.html"));

  s->font = GetFontDefault();
  GuiLoadStyle("resources/style_cyber.rgs");

  double t_init_end = GetTimeSeconds();

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
  VoiceRecApi *vapi = s->voiceApi;
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
        if (s->elements[j].kind == ELEM_TEXT_EDITOR ||
            s->elements[j].kind == ELEM_ENTRY_LIST) {
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
          if (editor->kind == ELEM_ENTRY_LIST) {
            UpdateEntryContentInDB(s, editor->selectedEntryId, editor->text);
          } else {

            UpdateLogInDB(s, editor->text);
          }
          editor->snapToCursor = 2;
        }
      }
    }
  } else {
    updateNotification(s, StringStatic("VOICE ERROR"));
  }

  Vector2 mPos = GetMousePosition();
  Vector2 mDelta = GetMouseDelta();
  SetMouseCursor(MOUSE_CURSOR_DEFAULT);

  // Handle element dragging and resizing
  int draggingIdx = -1;
  int resizingIdx = -1;
  for (int i = 0; i < s->numElements; i++) {
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
    if (IsMouseButtonDown(MOUSE_BUTTON_LEFT) ||
        IsMouseButtonDown(MOUSE_BUTTON_RIGHT)) {
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
      for (int i = s->numElements - 1; i >= 0; i--) {
        Element *e = &s->elements[i];
        if (e->kind == ELEM_NOTHING)
          continue;

        Rectangle r = GetElementBoundingBox(s, e);

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
    if (IsKeyDown(KEY_LEFT_SUPER) && IsMouseButtonDown(MOUSE_BUTTON_LEFT)) {
      if (mDelta.x != 0.0f || mDelta.y != 0.0f) {
        for (int i = 0; i < s->numElements; i++) {
          Element *e = &s->elements[i];
          e->position.x += mDelta.x;
          e->position.y += mDelta.y;
        }
      }
    }
  }

  if (IsKeyDown(KEY_LEFT_SUPER)) {
    for (int i = s->numElements - 1; i >= 0; i--) {
      Element *e = &s->elements[i];
      if (e->kind == ELEM_NOTHING)
        continue;

      Rectangle r = GetElementBoundingBox(s, e);
      if (CheckCollisionPointRec(mPos, r)) {
        if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT)) {
          e->isDragging = true;
          e->dragOffsetX = mPos.x - e->position.x;
          e->dragOffsetY = mPos.y - e->position.y;
          break;
        }
        if (IsMouseButtonPressed(MOUSE_BUTTON_RIGHT)) {
          e->isResizing = true;
          e->dragOffsetX = mPos.x - (e->position.x + *e->width);
          e->dragOffsetY = mPos.y - (e->position.y + *e->height);
          break;
        }
      }
    }
  }

  for (int i = 0; i < s->numElements; i++) {
    Element *e = &s->elements[i];
    bool isHovering = IsHoveringElement(s, e);
    if (isHovering && !e->isDragging && !e->isResizing) {
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
        case ACTION_LOAD_HYPERMEDIA: {
          // Hack: the first element doubles as the URL input for loading
          // hypermedia documents.
          Element *url_input = &s->elements[0];
          if (url_input->text.data &&
              (strncmp(url_input->text.data, "http://", 7) == 0 ||
               strncmp(url_input->text.data, "https://", 8) == 0 ||
               strncmp(url_input->text.data, "file://", 7) == 0 ||
               strstr(url_input->text.data, ".html") != NULL)) {
            LoadHypermediaDocument(s, url_input->text);
          } else {
            LoadHypermediaDocument(s, StringStatic("file://document.html"));
          }
          break;
        }
        default:
          break;
        }
      }
    }

    if (e->isDragging) {
      continue; // Skip hover effect if dragging
    }
    switch (s->elements[i].kind) {
    case ELEM_RECTANGLE:
    case ELEM_ELBOW:
      if (isHovering) {
        s->elements[i].color =
            ColorBrightness(s->elements[i].originalColor, 0.2f);
        clickOrHoverNotification(s, i, StringStatic("elbow element"));
      } else {
        s->elements[i].color = s->elements[i].originalColor;
      }
      break;
    case ELEM_BUTTON: {
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
    case ELEM_TEXT_EDITOR:
    case ELEM_ENTRY_LIST: {
      float listWidth = 0.0f;
      if (e->kind == ELEM_ENTRY_LIST) {
        listWidth = e->listCollapsed ? 30.0f : 350.0f;

        // Handle list selection panel interactions
        Rectangle listRec =
            (Rectangle){e->position.x, e->position.y, listWidth, *e->height};
        if (CheckCollisionPointRec(mPos, listRec)) {
          // Mouse wheel scrolling for list
          float wheelMove = GetMouseWheelMove();
          if (wheelMove != 0.0f) {
            EntryListItem items[32];
            int count = GetEntriesByKind(s, e->selectedKind.data, items, 32);
            float viewportHeight = *e->height - 45.0f;
            e->listScrollY -= wheelMove * 30.0f;
            e->listScrollY = ClampScrollOffset(e->listScrollY, count * 90.0f,
                                               viewportHeight);
          }

          if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT)) {
            Rectangle toggleBtn =
                (Rectangle){e->position.x, e->position.y, 30.0f, 30.0f};
            if (CheckCollisionPointRec(mPos, toggleBtn)) {
              e->listCollapsed = !e->listCollapsed;
            } else if (!e->listCollapsed) {
              Rectangle newEntryBtn =
                  (Rectangle){e->position.x + 35.0f, e->position.y,
                              listWidth - 50.0f, 30.0f};
              if (CheckCollisionPointRec(mPos, newEntryBtn)) {
                UpdateEntryContentInDB(s, e->selectedEntryId, e->text);

                char datename[32];
                struct tm *to;
                time_t t = time(NULL);
                to = localtime(&t);
                strftime(datename, sizeof(datename), "%Y-%m-%d", to);

                char *sql = sqlite3_mprintf(
                    "INSERT INTO entries (kind, title, content) VALUES "
                    "('%s', '%s', '%q');",
                    e->selectedKind.data, e->selectedKind.data, datename);
                if (sql) {
                  ExecSQL(s, StringStatic(sql),
                          StringStatic("New entry created"));
                  sqlite3_free(sql);
                }
                int newId = (int)sqlite3_last_insert_rowid(s->db);
                e->selectedEntryId = newId;
                String newText = GetEntryContentFromDB(s, newId);
                LoadEntryIntoEditor(e, newText);
                StringFree(&newText);
              } else {
                EntryListItem items[32];

                e->kindList = GetAllKindsFromDB(s);
                int count =
                    GetEntriesByKind(s, e->selectedKind.data, items, 32);
                float viewportHeight = *e->height - 45.0f;
                float maxItemWidth = listWidth - 15.0f;
                bool isScrollable = (count * 90.0f > viewportHeight);
                float itemWidth = maxItemWidth;
                if (isScrollable) {
                  itemWidth = maxItemWidth - 10.0f;
                }
                float itemY = e->position.y + 45.0f - e->listScrollY;
                Rectangle scrollableListRec =
                    (Rectangle){e->position.x, e->position.y + 45.0f,
                                listWidth - 5.0f, viewportHeight};
                if (CheckCollisionPointRec(mPos, scrollableListRec)) {
                  for (int j = 0; j < count; j++) {
                    Rectangle itemRec = (Rectangle){e->position.x + 5.0f, itemY,
                                                    itemWidth, 80.0f};
                    if (CheckCollisionPointRec(mPos, itemRec)) {
                      if (e->selectedEntryId != items[j].id) {
                        UpdateEntryContentInDB(s, e->selectedEntryId, e->text);
                        e->selectedEntryId = items[j].id;
                        String newText =
                            GetEntryContentFromDB(s, e->selectedEntryId);
                        LoadEntryIntoEditor(e, newText);
                        StringFree(&newText);
                      }
                      break;
                    }
                    itemY += 90.0f;
                  }
                }
              }
            }
          }
        }
      }

      float editorX = e->position.x + listWidth;
      float editorWidth = *e->width - listWidth;

      float scrollbarX = editorX + editorWidth + 25;
      float scrollbarY = e->position.y;
      float scrollbarWidth = 24.0f;
      float scrollbarHeight = *e->height;
      Rectangle activeRec = (Rectangle){.x = editorX,
                                        .y = e->position.y,
                                        .width = editorWidth + 55,
                                        .height = *e->height};
      Rectangle totalActiveRec = activeRec;
      if (e->kind == ELEM_ENTRY_LIST) {
        totalActiveRec.x = e->position.x;
        totalActiveRec.width = *e->width + 55;
        totalActiveRec.y = e->position.y - 25.0f;
        totalActiveRec.height = *e->height + 25.0f;
      }

      if (CheckCollisionPointRec(GetMousePosition(), totalActiveRec)) {
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
          bool deleteClicked = false;
          if (e->kind == ELEM_ENTRY_LIST && e->selectedEntryId != 0) {
            float btnSize = 18.0f;
            Rectangle deleteBtn =
                (Rectangle){editorX + editorWidth + 10.0f - btnSize - 8.0f,
                            e->position.y - btnSize - 4.0f, btnSize, btnSize};
            if (CheckCollisionPointRec(mPos, deleteBtn)) {
              DeleteEntryFromDB(s, e->selectedEntryId);
              EntryListItem remItems[32];
              int remCount = GetEntriesByKind(s, "personal_log", remItems, 32);
              if (remCount > 0) {
                e->selectedEntryId = remItems[0].id;
              } else {
                char datename[32];
                struct tm *to;
                time_t t = time(NULL);
                to = localtime(&t);
                strftime(datename, sizeof(datename), "%Y-%m-%d", to);

                char *sql = sqlite3_mprintf(
                    "INSERT INTO entries (kind, title, content) VALUES "
                    "('personal_log', 'Captain Log', '%q Captain log');",
                    datename);
                if (sql) {
                  ExecSQL(s, StringStatic(sql),
                          StringStatic("New entry created"));
                  sqlite3_free(sql);
                }
                e->selectedEntryId = (int)sqlite3_last_insert_rowid(s->db);
              }
              String newText = GetEntryContentFromDB(s, e->selectedEntryId);
              LoadEntryIntoEditor(e, newText);
              StringFree(&newText);
              deleteClicked = true;
            }
          }

          if (!deleteClicked) {
            Rectangle upButton = (Rectangle){scrollbarX, scrollbarY,
                                             scrollbarWidth, scrollbarWidth};
            Rectangle downButton = (Rectangle){
                scrollbarX, scrollbarY + scrollbarHeight - scrollbarWidth,
                scrollbarWidth, scrollbarWidth};
            Rectangle track = (Rectangle){
                scrollbarX, scrollbarY + scrollbarWidth + 5, scrollbarWidth,
                scrollbarHeight - 2 * scrollbarWidth - 10};

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
              Rectangle handle = (Rectangle){scrollbarX, handleY,
                                             scrollbarWidth, handleHeight};

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

        bool isMouseOverList = false;
        if (e->kind == ELEM_ENTRY_LIST) {
          Rectangle listRec =
              (Rectangle){e->position.x, e->position.y, listWidth, *e->height};
          isMouseOverList = CheckCollisionPointRec(mPos, listRec);
        }

        bool shiftDown =
            IsKeyDown(KEY_LEFT_SHIFT) || IsKeyDown(KEY_RIGHT_SHIFT);

        // Get char pressed (unicode character) on the queue
        int key = GetCharPressed();
        bool textChanged = false;

        if (isMouseOverList) {
          while (key > 0) {
            key = GetCharPressed();
          }
        } else {
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
        }

        if (!isMouseOverList) {
          if ((IsKeyDown(KEY_LEFT_CONTROL) || IsKeyDown(KEY_LEFT_SUPER)) &&
              IsKeyPressed(KEY_C)) {
            if (e->selectTextLength <= 0) {
              SetClipboardText(e->text.data ? e->text.data : "");
              updateNotification(s,
                                 StringStatic("All text copied to clipboard"));
            } else {
              int selStart = e->selectTextLength > 0
                                 ? e->selectTextStart
                                 : e->selectTextStart + e->selectTextLength;
              int selLength = e->selectTextLength > 0 ? e->selectTextLength
                                                      : -e->selectTextLength;
              char *selectedText =
                  (char *)arena_alloc(&s->scratch_arena, selLength + 1);
              memcpy(selectedText, e->text.data + selStart, selLength);
              selectedText[selLength] = '\0';
              SetClipboardText(selectedText);
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
              for (int j = 0; j < clipboardTextLen; j++) {
                GapInsertChar(&s->doc_arena, e, clipboardText[j]);
              }
              textChanged = true;
              e->snapToCursor = 2;
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
          if (KeyRepeatFired(&e->moveLeftRepeat, KEY_LEFT, 0.4f,
                             e->textSelectedFramesCounter, 2)) {
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
                  while (target > 0 &&
                         !IsWordChar(e->text.data[target - 1]) &&
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

          if (KeyRepeatFired(&e->moveRightRepeat, KEY_RIGHT, 0.4f,
                             e->textSelectedFramesCounter, 2)) {
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
          e->moveLeftRepeat.isHeld = false;
          e->moveRightRepeat.isHeld = false;
        }
        bool triggerMoveUp = false;
        if (e->kind == ELEM_ENTRY_LIST && isMouseOverList) {
          if (KeyRepeatFired(&e->moveUpRepeat, KEY_UP, 0.4f,
                             e->textSelectedFramesCounter, 10)) {
            NavigateEntryList(s, e, -1);
          }
        } else {
          if (KeyRepeatFired(&e->moveUpRepeat, KEY_UP, 0.4f,
                             e->textSelectedFramesCounter, 2)) {
            triggerMoveUp = true;
          }
        }

        bool triggerMoveDown = false;
        if (e->kind == ELEM_ENTRY_LIST && isMouseOverList) {
          if (KeyRepeatFired(&e->moveDownRepeat, KEY_DOWN, 0.4f,
                             e->textSelectedFramesCounter, 10)) {
            NavigateEntryList(s, e, 1);
          }
        } else {
          if (KeyRepeatFired(&e->moveDownRepeat, KEY_DOWN, 0.4f,
                             e->textSelectedFramesCounter, 2)) {
            triggerMoveDown = true;
          }
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
              (Vector2){editorX + 5, e->position.y + 5 - e->scrollY},
              e->textSize, 2.0, mPos, editorWidth);
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
              (Vector2){editorX + 5, e->position.y + 5 - e->scrollY},
              e->textSize, 2.0, mPos, editorWidth);
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
          if (KeyRepeatFired(&e->deleteRepeat, KEY_BACKSPACE, 0.5f,
                             e->textSelectedFramesCounter, 10)) {
            GapDeleteBack(e);
            textChanged = true;
            e->snapToCursor = 2;
          }
        } else if (IsKeyDown(KEY_DELETE)) {
          if (KeyRepeatFired(&e->deleteRepeat, KEY_DELETE, 0.5f,
                             e->textSelectedFramesCounter, 10)) {
            GapDeleteForward(e);
            textChanged = true;
            e->snapToCursor = 2;
          }
        }

        if (IsKeyUp(KEY_BACKSPACE) && IsKeyUp(KEY_DELETE)) {
          e->deleteRepeat.isHeld = false;
          e->deleteRepeat.startTime = 0;
        }

        if (textChanged) {
          ReconstructText(&s->doc_arena, e);
          if (e->kind == ELEM_ENTRY_LIST) {
            UpdateEntryContentInDB(s, e->selectedEntryId, e->text);
          } else {
            UpdateLogInDB(s, e->text);
          }
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
      break;
    }
    case ELEM_NOTHING:
    case ELEM_TOTAL_KINDS:
      break;
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

  if (IsKeyDown(KEY_LEFT_SUPER) && IsKeyPressed(KEY_S)) {
    system("./scripts/db-push.sh");
  }

  Update(s);
  Vector2 mPos = GetMousePosition();

  // Pre render on texture areas or any other requirements for first pass:
  for (int i = 0; i < s->numElements; i++) {
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
    case ELEM_ENTRY_LIST:
    case ELEM_ELBOW:
    case ELEM_NOTHING:
    case ELEM_TOTAL_KINDS:
      break;
    }
  }

  BeginDrawing();
  ClearBackground(BLACK);

  if (IsKeyDown(KEY_LEFT_SHIFT)) {
    if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT)) {
      s->selection_rec.x = mPos.x;
      s->selection_rec.y = mPos.y;
      s->selection_rec.width = 0;
      s->selection_rec.height = 0;
    } else if (IsMouseButtonDown(MOUSE_BUTTON_LEFT)) {
      // This only works when selecting from top-left to bottom-right. Need to
      // handle other directions.
      s->selection_rec.width = mPos.x - s->selection_rec.x;
      s->selection_rec.height = mPos.y - s->selection_rec.y;
      DrawRectangleLinesEx(s->selection_rec, 1, LCARS_GREEN);
    } else if (IsMouseButtonReleased(MOUSE_BUTTON_LEFT)) {
      s->selection_rec.width = 0;
      s->selection_rec.height = 0;
    }
  }

  for (int i = 0; i < s->numElements; i++) {
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
    case ELEM_TEXT_EDITOR:
    case ELEM_ENTRY_LIST: {
      float listWidth = 0.0f;
      Color listBorderColor = LCARS_ORANGE;
      Color editorBorderColor = LCARS_BLUE;
      bool isMouseOverList = false;

      if (e->kind == ELEM_ENTRY_LIST) {
        listWidth = e->listCollapsed ? 30.0f : 350.0f;
        Rectangle listRec =
            (Rectangle){e->position.x, e->position.y, listWidth, *e->height};
        isMouseOverList = CheckCollisionPointRec(mPos, listRec);

        if (isMouseOverList) {
          editorBorderColor = ColorAlpha(LCARS_BLUE, 0.4f);
        } else {
          listBorderColor = ColorAlpha(LCARS_ORANGE, 0.4f);
        }

        // Draw list panel background
        DrawRectangle(e->position.x, e->position.y, listWidth - 5.0f,
                      *e->height, (Color){15, 15, 15, 255});
        DrawRectangleLines(e->position.x, e->position.y, listWidth - 5.0f,
                           *e->height, listBorderColor);

        // Draw toggle button
        Rectangle toggleBtn =
            (Rectangle){e->position.x, e->position.y, 30.0f, 30.0f};
        DrawRectangleRounded(toggleBtn, 0.3f, 4, LCARS_BLUE);
        DrawText(e->listCollapsed ? ">" : "<",
                 toggleBtn.x + (toggleBtn.width -
                                MeasureText(e->listCollapsed ? ">" : "<", 20)) /
                                   2,
                 toggleBtn.y + (toggleBtn.height - 20) / 2, 20, BLACK);

        if (!e->listCollapsed) {
          // Draw "+ New Entry" button
          Rectangle newEntryBtn = (Rectangle){
              e->position.x + 35.0f, e->position.y, listWidth - 50.0f, 30.0f};
          DrawRectangleRounded(newEntryBtn, 0.3f, 4, LCARS_GREEN);
          DrawText("+ NEW ENTRY",
                   newEntryBtn.x +
                       (newEntryBtn.width - MeasureText("+ NEW ENTRY", 20)) / 2,
                   newEntryBtn.y + (newEntryBtn.height - 20) / 2, 20, BLACK);

          // Draw entries
          EntryListItem items[32];
          int count = GetEntriesByKind(s, e->selectedKind.data, items, 32);
          float viewportHeight = *e->height - 45.0f;
          float maxItemWidth = listWidth - 15.0f;
          bool isScrollable = (count * 90.0f > viewportHeight);
          float itemWidth = maxItemWidth;
          if (isScrollable) {
            itemWidth = maxItemWidth - 10.0f;
          }

          float itemY = e->position.y + 45.0f - e->listScrollY;
          Rectangle listClipRec =
              (Rectangle){e->position.x, e->position.y + 45.0f,
                          listWidth - 5.0f, viewportHeight};

          BeginScissorMode((int)listClipRec.x, (int)listClipRec.y,
                           (int)listClipRec.width, (int)listClipRec.height);
          for (int j = 0; j < count; j++) {
            Rectangle itemRec =
                (Rectangle){e->position.x + 5.0f, itemY, itemWidth, 80.0f};
            Color itemColor = (items[j].id == e->selectedEntryId)
                                  ? LCARS_YELLOW
                                  : (Color){40, 40, 40, 255};
            Color textColor =
                (items[j].id == e->selectedEntryId) ? BLACK : WHITE;
            Color subtextColor = (items[j].id == e->selectedEntryId)
                                     ? (Color){80, 80, 80, 255}
                                     : (Color){180, 180, 180, 255};

            DrawRectangleRounded(itemRec, 0.2f, 4, itemColor);

            // Draw entry title/id
            char label[256];
            snprintf(label, sizeof(label), "Entry #%d (%s)", items[j].id,
                     items[j].title);
            DrawText(label, itemRec.x + 10, itemRec.y + 7, 20, textColor);

            // Draw created and updated dates
            char dates[64];
            snprintf(dates, sizeof(dates), "U: %s",
                     items[j].last_modified[0] ? items[j].last_modified
                                               : items[j].created_at);
            DrawText(dates, itemRec.x + 10, itemRec.y + 31, 20, subtextColor);
            char createdDate[64];
            snprintf(createdDate, sizeof(createdDate), "C: %s",
                     items[j].created_at);
            DrawText(createdDate, itemRec.x + 10, itemRec.y + 55, 20,
                     subtextColor);

            itemY += 90.0f;
          }
          EndScissorMode();

          // Draw scrollbar if scrollable
          if (isScrollable) {
            float trackX = e->position.x + listWidth - 15.0f;
            float trackY = e->position.y + 45.0f;
            float trackWidth = 6.0f;
            float trackHeight = *e->height - 50.0f;

            float handleHeight =
                (viewportHeight / (count * 90.0f)) * trackHeight;
            if (handleHeight < 15.0f)
              handleHeight = 15.0f;

            float scrollRange = count * 90.0f - viewportHeight;
            float handleY = trackY;
            if (scrollRange > 0.0f) {
              handleY +=
                  (e->listScrollY / scrollRange) * (trackHeight - handleHeight);
            }

            // Draw track
            DrawRectangleRounded(
                (Rectangle){trackX, trackY, trackWidth, trackHeight}, 0.5f, 4,
                (Color){30, 30, 30, 255});
            // Draw handle
            Color handleColor =
                isMouseOverList ? LCARS_ORANGE : ColorAlpha(LCARS_ORANGE, 0.5f);
            DrawRectangleRounded(
                (Rectangle){trackX, handleY, trackWidth, handleHeight}, 0.5f, 4,
                handleColor);
          }
        }
      }

      float editorX = e->position.x + listWidth;
      float editorWidth = *e->width - listWidth;

      DrawRectangleLines(editorX, e->position.y, editorWidth + 10, *e->height,
                         editorBorderColor);

      if (e->kind == ELEM_ENTRY_LIST && e->selectedEntryId != 0) {
        float btnSize = 18.0f;
        Rectangle deleteBtn =
            (Rectangle){editorX + editorWidth + 10.0f - btnSize - 8.0f,
                        e->position.y - btnSize - 4.0f, btnSize, btnSize};

        bool isHovered = CheckCollisionPointRec(mPos, deleteBtn);
        Color btnColor = isHovered ? RED : LCARS_RED_ORANGE;
        DrawRectangleRounded(deleteBtn, 0.3f, 4, btnColor);

        int fontSize = 14;
        const char *btnText = "x";
        int textWidth = MeasureText(btnText, fontSize);
        DrawText(btnText, deleteBtn.x + (deleteBtn.width - textWidth) / 2.0f,
                 deleteBtn.y + (deleteBtn.height - fontSize) / 2.0f, fontSize,
                 BLACK);
        if (e->kindList.count > 0) {
          for (int k = 0; k < e->kindList.count; k++) {
            DrawText(e->kindList.kinds[k].data,
                     e->position.x + 50.0f + k * 200.0f + 12.0f,
                     e->position.y - 20.0f, 20, WHITE);
            if (StringEq(e->kindList.kinds[k], e->selectedKind)) {
              DrawRectangle(e->position.x + 50.0f + k * 200.0f,
                            e->position.y - 20.0f, 180.0f, 20.0f,
                            ColorAlpha(LCARS_BLUE, 0.5f));
            }
            if (CheckCollisionPointRec(
                    mPos, (Rectangle){e->position.x + 50.0f + k * 200.0f,
                                      e->position.y - 20.0f, 180.0f, 20.0f})) {
              DrawRectangle(e->position.x + 50.0f + k * 200.0f,
                            e->position.y - 20.0f, 180.0f, 20.0f,
                            ColorAlpha(LCARS_BLUE, 0.3f));
              if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT)) {
                e->selectedKind = e->kindList.kinds[k];
              }
            }
          }
        }
      }

      Rectangle r =
          (Rectangle){editorX + 5, e->position.y + 5, editorWidth, *e->height};
      BeginScissorMode((int)r.x, (int)r.y, (int)r.width, (int)r.height);
      DrawTextBoxed(s, e, s->font, e->text, r, e->textSize, 2.0f, false,
                    e->color, &e->textHeight, &e->cursorY, e->gapStart);
      EndScissorMode();

      // Render scrollbar
      float scrollbarX = editorX + editorWidth + 25;
      float scrollbarY = e->position.y;
      float scrollbarWidth = 24.0f;
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
      DrawText("^", upButton.x + (upButton.width - MeasureText("^", 20)) / 2,
               upButton.y + (upButton.height - 20) / 2, 20, BLACK);
      DrawText("v",
               downButton.x + (downButton.width - MeasureText("v", 20)) / 2,
               downButton.y + (downButton.height - 20) / 2, 20, BLACK);

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

    if (e->text.data && e->kind != ELEM_TEXT && e->kind != ELEM_TEXT_EDITOR &&
        e->kind != ELEM_ENTRY_LIST) {
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
    if (s->debug) {
      DrawText(s->notification.data, s->posX + s->columnWidth + s->innerRadius,
               s->posY - 2 * s->columnHeight - s->barHeight, 20, YELLOW);
    }
  } else {
    s->notificationOnElemIdx = -1;
  }

  if (s->debug) {
    DrawFPS(10, 10);
    DrawText(TextFormat("x:%.2f, y:%.2f", mPos.x, mPos.y), mPos.x + 20, mPos.y,
             20, GREEN);
    DrawLine(0, mPos.y, WINDOW_WIDTH, mPos.y, GREEN);
    DrawLine(mPos.x, 0, mPos.x, WINDOW_HEIGHT, GREEN);
  }

  // Draw interactive handles on top of all elements
  if (s->is_editing) {
    Vector2 mousePos = GetMousePosition();
    for (int i = 0; i < s->numElements; i++) {
      Element *e = &s->elements[i];
      if (e->kind == ELEM_NOTHING)
        break;

      Rectangle r = GetElementBoundingBox(s, e);
      bool isElementHovered = IsHoveringElement(s, e);
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

#endif // LIBLCARS_H
