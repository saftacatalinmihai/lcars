#define _POSIX_C_SOURCE 200809L
// #include <_locale_posix2008.h>
#include "raygui.h"
#include "raylib.h"
#include "raymath.h"
#include "rlgl.h"
#include "sqlite3.h"
#include "voice_rec.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define _ISOC99_SOURCE
#include <math.h>

#define LCARS_PURPLE (Color){206, 153, 205, 255}
#define LCARS_RED_ORANGE (Color){204, 102, 102, 255}
#define LCARS_ORANGE (Color){255, 154, 102, 255}
#define LCARS_YELLOW (Color){255, 205, 154, 255}
#define LCARS_BLUE (Color){155, 155, 255, 255}
#define TODO exit(1)

#define MAX_ELEMENTS 100
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
  ButtonAction action;
  iVec2 position;
  Vector3 position3;
  float *width, *height;
  Color color;
  Color originalColor;
  int elbowOrientation; // Only used if kind == ELBOW
  char *text;           // Text on button or just text elem
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
  char staticText[64][32 * 1024];
  int numElements;
  Color lcarsColor;
  float posX, posY, columnWidth, columnHeight, barWidth, barHeight, innerRadius;
  bool debug;
  bool is_editing;
  int controllsX;
  int controllsY;
  bool textBoxEditMode;
  Font font;
  char *notification;
  int notificationOnElemIdx;
  float notificationTimer;
  Ray ray;                // Picking line ray
  RayCollision collision; // Ray collision hit info
  sqlite3 *db;
  void *voiceApi;
} State;

void UpdateDrawFrame(State *s);
void Init(State *s, bool firstInit);

#define NOTIFICATION_DURATION 3.0f
#define NOTIFICATION_MAX_LEN 48

static inline void updateNotification(State *s, const char *notificationText) {
  snprintf(s->notification, NOTIFICATION_MAX_LEN, "%s", notificationText);
  s->notificationTimer = NOTIFICATION_DURATION;
}

#ifdef LCARS_IMPLEMENTATION

#define MAX(a, b) ((a) > (b) ? (a) : (b))
#define MIN(a, b) ((a) < (b) ? (a) : (b))

char *sprintf_static(State *s, int index, const char *fmt, ...) {
  va_list args;
  va_start(args, fmt);
  vsnprintf(s->staticText[index], sizeof(s->staticText[index]), fmt, args);
  va_end(args);
  return s->staticText[index];
}

static void ToggleVoiceRecording(State *s) {
  VoiceRecApi *vapi = (VoiceRecApi *)s->voiceApi;
  if (!vapi) {
    updateNotification(s, "VOICE ERROR");
    return;
  }

  // Find the Voice Input button
  Element *voiceBtn = NULL;
  for (int j = 0; j < s->numElements; j++) {
    if (s->elements[j].kind == ELEM_BUTTON &&
        s->elements[j].action == ACTION_VOICE_INPUT) {
      voiceBtn = &s->elements[j];
      break;
    }
  }

  if (vapi->IsRecording()) {
    vapi->StopRecording();
    if (voiceBtn) {
      voiceBtn->text = TEXT_VOICE_INPUT;
      voiceBtn->color = voiceBtn->originalColor;
    }
  } else {
    if (vapi->StartRecording()) {
      if (voiceBtn) {
        voiceBtn->text = TEXT_RECORDING;
        voiceBtn->color = RED;
      }
    } else {
      updateNotification(s, "Voice Recording failed to start");
    }
  }
}

static void ReLayout(State *s);

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
// static void updateNotification(State* s, const char* notificationText);

static int sqlite_callback(void *state, int argc, char **argv,
                           char **azColName) {
  State* s = (State*)state;
  int i;
  for (i = 0; i < argc; i++) {
    printf("%s = %s\n", azColName[i], argv[i] ? argv[i] : "NULL");
  }
  printf("\n");
  return 0;
}

static int ExecSQL(State *s, const char *sql, const char *successMsg) {
  char *zErrMsg = 0;
  int rc = sqlite3_exec(s->db, sql, sqlite_callback, s, &zErrMsg);
  if (rc != SQLITE_OK) {
    fprintf(stderr, "SQL error: %s\n", zErrMsg);
    updateNotification(s, "SQL error");
    sqlite3_free(zErrMsg);
  } else {
    if (successMsg) {
      fprintf(stdout, "%s\n", successMsg);
      updateNotification(s, successMsg);
    }
  }
  return rc;
}

static void InitDB(State *s, bool firstInit) {
  (void)firstInit;
  ExecSQL(s,
          "CREATE TABLE IF NOT EXISTS log (id INTEGER PRIMARY KEY "
          "AUTOINCREMENT, text TEXT);",
          "Table created successfully");
  char *sql_entry_create =
      "CREATE TABLE IF NOT EXISTS entries ("
      "id INTEGER PRIMARY KEY AUTOINCREMENT," // type of thing, 0=log, 1=task,
                                              // 2=event, etc. these are just
                                              // examples.
      "kind INTEGER DEFAULT 0,"
      "title TEXT,"
      "content TEXT,"
      "value_int INTEGER,"
      "value_float REAL,"
      "value_blob BLOB,"
      "done_bool INTEGER DEFAULT 0,"
      "created_at_utc TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc')),"
      "last_modified_at_utc TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', "
      "'utc'))"
      ");";
  ExecSQL(s, sql_entry_create, "Table Entry created successfully");

  char datename[32];
  struct tm *to;
  time_t t = time(NULL);
  to = localtime(&t);
  strftime(datename, sizeof(datename), "%Y-%m-%d", to);

  char *sql_insert_full = sqlite3_mprintf(
      "INSERT OR IGNORE INTO log (id, text) VALUES (0, '%q Captain log');",
      datename);
  if (sql_insert_full) {
    ExecSQL(s, sql_insert_full, "Data inserted successfully");
    sqlite3_free(sql_insert_full);
  }
}

static char *GetLogFromDB(State *s) {
  char *output = NULL;
  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(s->db, "SELECT text FROM log where id=?1", -1,
                              &stmt, 0);
  if (rc != SQLITE_OK) {
    updateNotification(s, "failure fetching data");
  } else {
    sqlite3_bind_text(stmt, 1, "0", -1, SQLITE_STATIC);
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
      output = strdup((char *)sqlite3_column_text(stmt, 0));
    }
    sqlite3_finalize(stmt);
  }
  if (!output) {
    output = strdup("");
  }
  return output;
}

static void UpdateLogInDB(State *s, const char *newLog) {
  char *sql_update_full =
      sqlite3_mprintf("UPDATE log SET text = (%Q) WHERE id = 0;", newLog);
  if (!sql_update_full) {
    updateNotification(s, "SQL error");
    return;
  }
  ExecSQL(s, sql_update_full, NULL);
  sqlite3_free(sql_update_full);
}

static bool IsWordChar(char c) {
  return ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '_');
}

static void MoveGap(Element *e, int index) {
  if (index < 0)
    index = 0;
  int currentLen = e->gapStart + (e->textCapacity - e->gapEnd);
  if (index > currentLen)
    index = currentLen;

  while (e->gapStart < index) {
    e->gapBuffer[e->gapStart] = e->gapBuffer[e->gapEnd];
    e->gapStart++;
    e->gapEnd++;
  }
  while (e->gapStart > index) {
    e->gapStart--;
    e->gapEnd--;
    e->gapBuffer[e->gapEnd] = e->gapBuffer[e->gapStart];
  }
}

static void GapInsertChar(Element *e, char c) {
  if (e->gapStart == e->gapEnd) {
    int newCapacity = e->textCapacity * 2;
    if (newCapacity < 1024)
      newCapacity = 1024;
    char *newBuf = malloc(newCapacity + 1);

    memcpy(newBuf, e->gapBuffer, e->gapStart);
    int afterGapLen = e->textCapacity - e->gapEnd;
    int newGapEnd = newCapacity - afterGapLen;
    memcpy(newBuf + newGapEnd, e->gapBuffer + e->gapEnd, afterGapLen);

    free(e->gapBuffer);
    e->gapBuffer = newBuf;
    e->gapEnd = newGapEnd;
    e->textCapacity = newCapacity;
  }

  e->gapBuffer[e->gapStart] = c;
  e->gapStart++;
}

static void GapDeleteBack(Element *e) {
  if (e->gapStart > 0) {
    e->gapStart--;
  }
}

static void GapDeleteForward(Element *e) {
  if (e->gapEnd < e->textCapacity) {
    e->gapEnd++;
  }
}

static void ReconstructText(Element *e) {
  int beforeLen = e->gapStart;
  int afterLen = e->textCapacity - e->gapEnd;
  int totalLen = beforeLen + afterLen;

  e->text = realloc(e->text, totalLen + 1);
  memcpy(e->text, e->gapBuffer, beforeLen);
  memcpy(e->text + beforeLen, e->gapBuffer + e->gapEnd, afterLen);
  e->text[totalLen] = '\0';
  e->textLen = totalLen;
}

static bool DeleteSelection(Element *e) {
  if (e->selectTextStart >= 0 && e->selectTextEnd != e->selectTextStart) {
    int selStart = e->selectTextLength > 0
                       ? e->selectTextStart
                       : e->selectTextStart + e->selectTextLength;
    int selLength =
        e->selectTextLength > 0 ? e->selectTextLength : -e->selectTextLength;
    MoveGap(e, selStart);
    e->gapEnd += selLength;
    e->selectTextLength = 0;
    e->selectTextStart = -1;
    e->selectTextEnd = -1;
    return true;
  }
  return false;
}

static void StartTextSelection(Element *e, bool shiftDown) {
  if (shiftDown) {
    if (e->selectTextStart == -1) {
      e->selectTextStart = e->gapStart;
    }
  } else {
    e->selectTextStart = -1;
    e->selectTextEnd = -1;
    e->selectTextLength = 0;
  }
}

static void EndTextSelection(Element *e, bool shiftDown) {
  if (shiftDown) {
    e->selectTextEnd = e->gapStart;
    e->selectTextLength = e->selectTextEnd - e->selectTextStart;
  }
  e->snapToCursor = 2;
}

static void ClampScrollY(Element *e) {
  if (e->scrollY < 0.0f)
    e->scrollY = 0.0f;
  float maxScroll = e->textHeight - *e->height;
  if (maxScroll < 0.0f)
    maxScroll = 0.0f;
  if (e->scrollY > maxScroll)
    e->scrollY = maxScroll;
}

static int GetLines(const char *text, int *lineStarts, int maxLines) {
  int count = 0;
  lineStarts[count++] = 0;
  int len = strlen(text);
  for (int i = 0; i < len; i++) {
    if (text[i] == '\n') {
      if (count < maxLines) {
        lineStarts[count++] = i + 1;
      }
    }
  }
  return count;
}

static int GetLineForIndex(int index, const int *lineStarts, int numLines) {
  for (int i = 0; i < numLines - 1; i++) {
    if (index >= lineStarts[i] && index < lineStarts[i + 1]) {
      return i;
    }
  }
  return numLines - 1;
}

Vector2 V2fromiVec2(iVec2 v) { return (Vector2){v.x, v.y}; }

// 2

void Init(State *s, bool firstInit) {
  s->debug = false;
  s->is_editing = false;
  s->controllsX = 600;
  s->controllsY = 400;
  s->lcarsColor = (Color){204, 153, 204, 255}; // Purple
  // s->posX = 40;
  s->posX = 0;
  s->posY = 210;
  // s->posY = 0;
  s->columnWidth = 200;
  s->columnHeight = 40;
  s->barWidth = 400;
  s->barHeight = 20;
  s->innerRadius = 40;
  s->numElements = 0;

  char *notificationText = (char *)malloc(NOTIFICATION_MAX_LEN);
  notificationText[0] = '\0';
  s->notification = notificationText;
  ReLayout(s);

  if (firstInit) {
    sqlite3 *db = malloc(sizeof(sqlite3 *));
    int rc = sqlite3_open("lcars.db", &db);
    if (rc) {
      fprintf(stderr, "Can't open database: %s\n", sqlite3_errmsg(db));
    } else {
      fprintf(stderr, "Opened database successfully\n");
    }
    s->db = db;
  }
  InitDB(s, firstInit);

  char *dbLog = GetLogFromDB(s);
  char *text = malloc(MAX_INPUT_CHARS + 1);
  strncpy(text, dbLog, MAX_INPUT_CHARS);
  text[MAX_INPUT_CHARS] = '\0';
  free(dbLog);
  // strcpy(text, "Insert text here");

  printf("Loaded text from DB: %s\n", text);
  int textLen = strlen(text);
  printf("Text len: %d\n", textLen);
  text[MAX_INPUT_CHARS] = '\0';

  int textCapacity = 4096;
  char *gapBuffer = malloc(textCapacity + 1);
  memcpy(gapBuffer, text, textLen);
  int gapStart = textLen;
  int gapEnd = textCapacity;

  s->elements[s->numElements++] =
      (Element){.kind = ELEM_TEXT_EDITOR,
                .position = {s->posX + s->columnWidth + s->innerRadius + 60,
                             s->posY + s->barHeight + 80},
                .width = &w600,
                .height = &h400,
                .color = LCARS_PURPLE,
                .originalColor = LCARS_PURPLE,
                .textSize = 20,
                .text = text,
                .textLen = textLen,
                .textLineLen = textLen,
                .gapBuffer = gapBuffer,
                .gapStart = gapStart,
                .gapEnd = gapEnd,
                .textCapacity = textCapacity,
                .isFocused = false,
                .textSelectedFramesCounter = 0,
                .selectTextStart = -1,
                .selectTextLength = 0,
                .selectTextEnd = -1,
                .isDeletingText = false,
                .deletingTextStartTime = 0.0f,
                .isMovingCursorLeft = false,
                .moveCursorLeftStartTime = 0.0f,
                .isMovingCursorRight = false,
                .moveCursorRightStartTime = 0.0f,
                .isMovingCursorUp = false,
                .moveCursorUpStartTime = 0.0f,
                .isMovingCursorDown = false,
                .moveCursorDownStartTime = 0.0f,
                .selectingText = false,
                .draggingScrollbar = false,
                .dragStartY = 0.0f,
                .dragStartScrollY = 0.0f};

  s->font = GetFontDefault();
  // s->font = LoadFont("NotoColorEmoji-Regular.ttf");

  Image image;
  if (FileExists("resources/earth.png")) {
    image = LoadImage("resources/earth.png");
    // ImageToPOT(&image, BLACK);
    ImageFormat(&image,
                PIXELFORMAT_UNCOMPRESSED_R8G8B8A8); // Convert RGB to RGBA
    // PIXELFORMAT_UNCOMPRESSED_R8G8B8A8
    TraceLog(LOG_WARNING, "Texture ready!");
    s->elements[1].text = NULL;
    s->elements[1].textSize = 0;
  } else {
    TraceLog(LOG_WARNING, "Texture not ready yet!");
    s->elements[1].text = "Texture not ready!";
    s->elements[1].textSize = 20;
  }
  if (image.data == NULL) {
    s->notification = "Failed to load image";
    // s->elements[1].text = "Failed to load image";
  }
  ImageRotateCW(&image);
  ImageFlipVertical(&image);
  ImageFlipHorizontal(&image);
  Texture2D texture = LoadTextureFromImage(image);
  // GenTextureMipmaps(&texture);
  // SetTextureFilter(texture, TEXTURE_FILTER_BILINEAR);
  if (!IsTextureValid(texture)) {
    TraceLog(LOG_ERROR, "Texture is invalid!");
    s->elements[1].text = "Texture is invalid!";
  }

  // Texture2D texture = LoadTexture("resources/earth.jpg");
  // UnloadImage(image);
  Model earthModel = LoadModelFromMesh(GenMeshSphere(3.0f, 32, 32));
  earthModel.materials[0].maps[MATERIAL_MAP_DIFFUSE].texture = texture;
  earthModel.transform = MatrixRotateX(DEG2RAD * 90.0f);
  // earthModel.transform = MatrixRotateY(DEG2RAD * 40.0f);
  // earthModel.transform = MatrixRotateZ(DEG2RAD * 90.0f);

  s->elements[s->numElements++] =
      (Element){.kind = ELEM_SPHERE,
                .position3 = {0, 0, 0},
                .position = {950, 310}, // Used to create the render texture
                                        // area where the 3d element is inside.
                .width = &w300,
                .height = &h300,
                .color = WHITE,
                .originalColor = WHITE,
                .model = earthModel,
                .rotation = 0};

  GuiLoadStyle("resources/style_cyber.rgs");

  for (int i = 0; i < MAX_ELEMENTS; i++) {
    Element e = s->elements[i];
    if (ColorIsEqual(e.originalColor, (Color){0, 0, 0, 0})) {
      s->elements[i].originalColor = e.color;
    }

    switch (s->elements[i].kind) {
    case ELEM_SPHERE: {
      // Element e = s->elements[i];
      Element *e = &s->elements[i];

      Camera camera = {0};
      camera.position = (Vector3){10.0f, -10.0f, 10.0f};
      camera.target = (Vector3){0.0f, 0.0f, 0.0f};
      camera.up = (Vector3){0.0f, 1.0f, -0.23f};
      camera.fovy = 45.0f;
      camera.projection = CAMERA_PERSPECTIVE;
      e->camera = camera;

      RenderTexture renderTexture = LoadRenderTexture(*e->width, *e->height);
      e->renderTexture = renderTexture;
      break;
    }
    case ELEM_TEXT:
    case ELEM_RECTANGLE:
    case ELEM_ELBOW:
    case ELEM_BUTTON:
    case ELEM_TEXT_EDITOR:
    case ELEM_NOTHING:
    case ELEM_TOTAL_KINDS:
      break;
    }
  }
}

void Reload(State *s, bool reset) {
  if (reset) {
    Init(s, false);
  } else {
    GuiLoadStyle("resources/style_cyber.rgs");
  }
}

static void AddBarSegment(State *s, int *x_cursor, int y, float *width,
                          float *height, Color color, int gap) {
  s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE,
                                            .position = {*x_cursor + gap, y},
                                            .width = width,
                                            .height = height,
                                            .color = color,
                                            .originalColor = color};
  *x_cursor += (int)*width + gap;
}

void ReLayout(State *s) {
  // Clone elements to preserve manually adjusted layouts and other elements
  Element temp[MAX_ELEMENTS];
  for (int i = 0; i < MAX_ELEMENTS; i++) {
    temp[i] = s->elements[i];
  }

  s->numElements =
      0; // Clear existing elements before re-adding them with new layout
  int gap = 6;

  w[0] = 40;
  w[1] = 140;
  w[2] = 400;
  w[3] = 40;

  // Upper elbow
  int yu = s->posY - s->columnHeight - s->innerRadius - s->barHeight;

  h100 = 100;
  s->elements[s->numElements++] = (Element){.kind = ELEM_ELBOW,
                                            .elbowOrientation = 3,
                                            .position = {s->posX, yu - gap},
                                            .width = &s->columnWidth,
                                            .height = &s->columnHeight,
                                            .color = LCARS_BLUE};
  yu -= gap;
  s->elements[s->numElements++] =
      (Element){.kind = ELEM_RECTANGLE,
                .position = {s->posX, yu - 100 - gap},
                .width = &s->columnWidth,
                .height = &h100,
                .color = LCARS_PURPLE,
                .text = temp[1].text,
                .textSize = temp[1].textSize};
  yu -= 100;

  int xu = s->posX + s->columnWidth + s->barWidth;
  int yu_bar = s->posY - s->barHeight - gap;
  AddBarSegment(s, &xu, yu_bar, &w[0], &s->barHeight, LCARS_ORANGE, gap);
  AddBarSegment(s, &xu, yu_bar, &w[1], &s->barHeight, LCARS_PURPLE, gap);
  AddBarSegment(s, &xu, yu_bar, &w[2], &s->barHeight, LCARS_PURPLE, gap);
  AddBarSegment(s, &xu, yu_bar, &w[3], &s->barHeight, LCARS_RED_ORANGE, gap);

  // Lower elbo
  s->elements[s->numElements++] = (Element){.kind = ELEM_ELBOW,
                                            .position = {s->posX, s->posY},
                                            .width = &s->columnWidth,
                                            .height = &s->columnHeight,
                                            .color = LCARS_RED_ORANGE,
                                            .text = "03-975883",
                                            .textSize = 20};
  int y = s->posY + s->columnHeight + s->barHeight + s->innerRadius;

  h200_60_250[0] = 200;
  h200_60_250[1] = 60;
  h200_60_250[2] = 250;

  s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE,
                                            .position = {s->posX, y + gap},
                                            .width = &s->columnWidth,
                                            .height = &h200_60_250[0],
                                            .color = LCARS_RED_ORANGE,
                                            .text = "04-785466",
                                            .action = ACTION_PRINT_DB,
                                            .textSize = 20};
  y = y + 200 + gap;
  s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE,
                                            .position = {s->posX, y + gap},
                                            .width = &s->columnWidth,
                                            .height = &h200_60_250[1],
                                            .color = LCARS_ORANGE,
                                            .text = "05-423512",
                                            .textSize = 20};
  y = y + 60 + gap;
  s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE,
                                            .position = {s->posX, y + gap},
                                            .width = &s->columnWidth,
                                            .height = &h200_60_250[2],
                                            .color = LCARS_ORANGE,
                                            .text = "06-572983",
                                            .textSize = 20};
  y = y + 250 + gap;

  int x = s->posX + s->columnWidth + s->barWidth;
  halfBarHeight = s->barHeight / 2;
  AddBarSegment(s, &x, s->posY, &w[0], &s->barHeight, LCARS_YELLOW, gap);
  AddBarSegment(s, &x, s->posY, &w[1], &halfBarHeight, LCARS_YELLOW, gap);
  AddBarSegment(s, &x, s->posY, &w[2], &s->barHeight, LCARS_PURPLE, gap);
  AddBarSegment(s, &x, s->posY, &w[3], &s->barHeight, LCARS_ORANGE, gap);

  buttonHeight = 50;
  w210 = 210;
  s->elements[s->numElements++] =
      (Element){.kind = ELEM_BUTTON,
                .action = ACTION_DEBUG,
                .position = {x - 220, s->posY - 20 - s->barHeight -
                                          2 * buttonHeight - 10},
                .width = &w210,
                .height = &buttonHeight,
                .color = LCARS_ORANGE,
                .text = "(LC+d)ebug 9888-24",
                .textSize = 20};
  s->elements[s->numElements++] =
      (Element){.kind = ELEM_BUTTON,
                .action = ACTION_EDIT,
                .position = {x - 220 - 220, s->posY - 20 - s->barHeight -
                                                2 * buttonHeight - 10},
                .width = &w210,
                .height = &buttonHeight,
                .color = LCARS_BLUE,
                .text = "(LC+e)edit 0129-86",
                .textSize = 20};
  s->elements[s->numElements++] = (Element){
      .kind = ELEM_BUTTON,
      .action = ACTION_RESET,
      .position = {x - 220, s->posY - 20 - s->barHeight - buttonHeight},
      .width = &w210,
      .height = &buttonHeight,
      .color = LCARS_BLUE,
      .text = "(LC+r)eset 7232-83",
      .textSize = 20};

  VoiceRecApi *vapi = (VoiceRecApi *)s->voiceApi;
  bool isRecording = (vapi && vapi->IsRecording());
  s->elements[s->numElements++] = (Element){
      .kind = ELEM_BUTTON,
      .action = ACTION_VOICE_INPUT,
      .position = {x - 220 - 220, s->posY - 20 - s->barHeight - buttonHeight},
      .width = &w210,
      .height = &buttonHeight,
      .color = isRecording ? RED : LCARS_BLUE,
      .originalColor = LCARS_BLUE,
      .text = isRecording ? TEXT_RECORDING : TEXT_VOICE_INPUT,
      .textSize = 20};

  s->elements[s->numElements++] =
      (Element){.kind = ELEM_TEXT,
                .position = {x - 220 - 220 - 20, yu},
                .color = LCARS_YELLOW,
                .textSize = 48,
                .text = "LCARS ACCESS 441"};
  // s->elements[s->numElements++] = (Element){ .kind=ELEM_TEXT, .position = {
  // s->posX + s->columnWidth + s->innerRadius, s->posY - 2 * s->columnHeight -
  // s->barHeight - 40 - 10 }, .color = LCARS_YELLOW, .textSize = 20,
  // .text="LShift to move camera perspective with mouse\nLShift + W,A,S,D to
  // move object\n" };
}

//  void updateNotification(State* s, const char* notificationText) {
//     snprintf(s->notification, NOTIFICATION_MAX_LEN, "%s...",
//     notificationText); s->notificationTimer = NOTIFICATION_DURATION;
// }

static void clickOrHoverNotification(State *s, int i, char *elem_pretty_name) {
  if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON) ||
      s->notificationOnElemIdx != i) {
    char buf[NOTIFICATION_MAX_LEN];
    const char *action =
        IsMouseButtonPressed(MOUSE_LEFT_BUTTON) ? "Clicked" : "Hovering";
    snprintf(buf, sizeof(buf), "[%s %s %d] %s", action, elem_pretty_name, i,
             s->elements[i].text ? s->elements[i].text : "");
    updateNotification(s, buf);
    s->notificationOnElemIdx = i;
  }
}

// Helper function to find the character index under the mouse
int GetCharIndexAtMouse(const State *s, Font font, const char *text,
                        Vector2 textPos, float fontSize, float spacing,
                        Vector2 mousePos, float recWidth) {
  (void)s;
  if (text == NULL)
    return 0;
  int length = strlen(text);

  float textOffsetY = 0.0f;
  float textOffsetX = 0.0f;

  float scaleFactor = fontSize / (float)font.baseSize;
  float lineHeight = (font.baseSize + (float)font.baseSize / 2) * scaleFactor;

  int bestIndex = 0;
  float bestYDist = 1e30f;
  float bestXDist = 1e30f;

  // Evaluate initial position (before the first character)
  {
    float absX = textPos.x + textOffsetX;
    float absY = textPos.y + textOffsetY;

    float yDist = 0.0f;
    if (mousePos.y < absY) {
      yDist = absY - mousePos.y;
    } else if (mousePos.y > absY + lineHeight) {
      yDist = mousePos.y - (absY + lineHeight);
    } else {
      yDist = 0.0f;
    }

    float xDist = fabsf(mousePos.x - absX);
    bestYDist = yDist;
    bestXDist = xDist;
    bestIndex = 0;
  }

  for (int i = 0; i < length;) {
    int codepointByteCount = 0;
    int codepoint = GetCodepoint(&text[i], &codepointByteCount);
    int index = GetGlyphIndex(font, codepoint);

    if (codepoint == 0x3f)
      codepointByteCount = 1;

    float glyphWidth = 0.0f;
    if (codepoint != '\n') {
      glyphWidth = (font.glyphs[index].advanceX == 0)
                       ? font.recs[index].width * scaleFactor
                       : font.glyphs[index].advanceX * scaleFactor;
      if (i + codepointByteCount < length)
        glyphWidth = glyphWidth + spacing;
    }

    if (codepoint == '\n') {
      textOffsetY += lineHeight;
      textOffsetX = 0.0f;
    } else {
      if ((textOffsetX + glyphWidth) > recWidth) {
        textOffsetY += lineHeight;
        textOffsetX = 0.0f;
      }
      if ((textOffsetX != 0.0f) || (codepoint != ' ')) {
        textOffsetX += glyphWidth;
      }
    }

    i += codepointByteCount;

    // Evaluate candidate boundary position after the current codepoint
    {
      float absX = textPos.x + textOffsetX;
      float absY = textPos.y + textOffsetY;

      float yDist = 0.0f;
      if (mousePos.y < absY) {
        yDist = absY - mousePos.y;
      } else if (mousePos.y > absY + lineHeight) {
        yDist = mousePos.y - (absY + lineHeight);
      } else {
        yDist = 0.0f;
      }

      float xDist = fabsf(mousePos.x - absX);

      if (yDist < bestYDist) {
        bestYDist = yDist;
        bestXDist = xDist;
        bestIndex = i;
      } else if (yDist == bestYDist) {
        if (xDist < bestXDist) {
          bestXDist = xDist;
          bestIndex = i;
        }
      }
    }
  }

  return bestIndex;
}

static Rectangle GetElementBoundingBox(const Element *e) {
  // printf("Getting bounding box for element at position (%d, %d)\n",
  // e->position.x, e->position.y); printf("Element kind: %d\n", e->kind);
  float w = 0;
  float h = 0;
  if (e->kind == ELEM_TEXT) {
    if (e->width == NULL)
      w = MeasureText(e->text ? e->text : "", e->textSize);
    if (e->height == NULL)
      h = e->textSize;
  } else {

    w = e->width != NULL? *e->width : 0;
    h = e->height != NULL ? *e->height : 0;
  }
  return (Rectangle){(float)e->position.x, (float)e->position.y, w, h};
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
          updateNotification(s, fullNotify);
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
        int len = strlen(voiceBuf);
        bool textChanged = false;

        if (editor->selectTextStart >= 0 &&
            editor->selectTextEnd != editor->selectTextStart) {
          DeleteSelection(editor);
          textChanged = true;
        }

        for (int k = 0; k < len; k++) {
          GapInsertChar(editor, voiceBuf[k]);
          textChanged = true;
        }

        if (textChanged) {
          ReconstructText(editor);
          UpdateLogInDB(s, editor->text);
          editor->snapToCursor = 2;
        }
      }
    }
  } else {
    updateNotification(s, "VOICE ERROR");
  }

  Vector2 mPos = GetMousePosition();
  SetMouseCursor(MOUSE_CURSOR_DEFAULT);
  // UpdateCamera(&s->camera, CAMERA_ORBITAL);

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
            Rectangle resizeHandle = {r.x + r.width - 8, r.y + r.height - 8, 16, 16};

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
    bool isHovering = CheckCollisionPointRec(GetMousePosition(),
                                      GetElementBoundingBox(e));
    if (isHovering) {
        if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON)) {
            switch (e->action) {
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
                    ExecSQL(s, "SELECT * FROM entries;", "Done");
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
        clickOrHoverNotification(s, i, "element");
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
          clickOrHoverNotification(s, i, "elbow element");
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
          clickOrHoverNotification(s, i, "elbow element");
        } else {
          s->elements[i].color = s->elements[i].originalColor;
        }
        break;
      }
      break;
    case ELEM_BUTTON: {
      VoiceRecApi *vapi = (VoiceRecApi *)s->voiceApi;
      bool isRecording =
          (vapi && vapi->IsRecording() && e->action == ACTION_VOICE_INPUT);
      if (isHovering) {
        if (isRecording) {
          s->elements[i].color = (Color){255, 100, 100, 255};
        } else {
          s->elements[i].color =
              ColorBrightness(s->elements[i].originalColor, 0.2f);
        }
        clickOrHoverNotification(s, i, "button element");
        // if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON)) {
        //   switch (e->action) {
        //   case ACTION_DEBUG:
        //     s->debug = !s->debug;
        //     break;
        //   case ACTION_EDIT:
        //     s->is_editing = !s->is_editing;
        //     break;
        //   case ACTION_RESET:
        //     Reload(s, true);
        //     break;
        //   case ACTION_VOICE_INPUT:
        //     ToggleVoiceRecording(s);
        //     break;
        //   default:
        //     break;
        //   }
        // }
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
        clickOrHoverNotification(s, i, "text box element");
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
            GapInsertChar(e, (char)key);
            textChanged = true;
            e->snapToCursor = 2;
          }

          key = GetCharPressed(); // Check next character in the queue
        }

        if ((IsKeyDown(KEY_LEFT_CONTROL) || IsKeyDown(KEY_LEFT_SUPER)) &&
            IsKeyPressed(KEY_C)) {
          if (e->selectTextLength <= 0) {
            SetClipboardText(e->text);
            updateNotification(s, "All text copied to clipboard");
            printf("Copied all text to clipboard: |%s|\n", e->text);
          } else {
            int selStart = e->selectTextLength > 0
                               ? e->selectTextStart
                               : e->selectTextStart + e->selectTextLength;
            int selLength = e->selectTextLength > 0 ? e->selectTextLength
                                                    : -e->selectTextLength;
            char *selectedText = (char *)malloc(selLength + 1);
            memcpy(selectedText, e->text + selStart, selLength);
            selectedText[selLength] = '\0';
            SetClipboardText(selectedText);
            printf("Copied to clipboard: |%s|\n", selectedText);
            updateNotification(s, "Selected text copied to clipboard");
            free(selectedText);
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
              GapInsertChar(e, clipboardText[j]);
            }
            textChanged = true;
            e->snapToCursor = 2;
            printf("Pasted from clipboard: |%s|\n", clipboardText);
            updateNotification(s, "Clipboard text pasted");
          }
        }

        if (IsKeyPressed(KEY_ENTER)) {
          if (DeleteSelection(e)) {
            textChanged = true;
          }
          GapInsertChar(e, '\n');
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
                if (e->text[target - 1] == '\n') {
                  target--;
                } else {
                  while (target > 0 && !IsWordChar(e->text[target - 1]) &&
                         e->text[target - 1] != '\n') {
                    target--;
                  }
                  while (target > 0 && IsWordChar(e->text[target - 1])) {
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
                if (e->text[target] == '\n') {
                  target++;
                } else {
                  while (target < e->textLen && !IsWordChar(e->text[target]) &&
                         e->text[target] != '\n') {
                    target++;
                  }
                  while (target < e->textLen && IsWordChar(e->text[target])) {
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
          ReconstructText(e);
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
      // Element e = s->elements[i];
      // s->ray = GetScreenToWorldRay(GetMousePosition(), e->camera);
      // s->collision = GetRayCollisionSphere(s->ray, e->position3, 3);

      if (isHovering) {
        // if (s->collision.hit) {
        // printf("Hit sphere element %d\n", i);
        e->color = ColorBrightness(GREEN, 0.8f);
        // if (!(memcmp(&e->color, &e->originalColor, sizeof(Color)) == 0))
        // e->color = BLUE;
        clickOrHoverNotification(s, i, "sphere element");
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
      // UpdateCamera(&e->camera, CAMERA_ORBITAL);
      // e->model.transform = MatrixMultiply(
      //     MatrixRotateY(DEG2RAD * e->rotation), // Spin around poles
      //     MatrixRotateX(DEG2RAD * 90.0f)        // Initial tilt to fix JPG
      //     orientation
      // );
    }
    case ELEM_NOTHING:
    case ELEM_TOTAL_KINDS:
      break;
    }
  }
}

// Orientation: 0 - corner at top-left, 1 - corner at top-right, 2 - corner at
// bottom-right, 3 - corner at bottom-left
void DrawElbow(int posX, int posY, int columnWidth, int columnHeight,
               int barWidth, int barHeight, int innerRadius, Color color,
               int orientation, bool debug) {
  switch (orientation) {
  case 0:
    if (columnWidth >= barHeight + innerRadius) {
      DrawRectangle(posX, posY + barHeight + innerRadius, columnWidth,
                    columnHeight, color); // Vertical bar
      DrawRectangle(posX + columnWidth, posY, barWidth, barHeight,
                    debug ? GREEN : color); // Horizontal bar
      Vector2 center = {posX + barHeight + innerRadius,
                        posY + barHeight + innerRadius};
      DrawCircleSector(center, innerRadius + barHeight, 180, 270, 0,
                       debug ? BLUE : color); // Elbow curve
      DrawRectangle(
          posX + barHeight + innerRadius, posY,
          columnWidth - barHeight - innerRadius, barHeight + innerRadius,
          debug ? ORANGE
                : color); // Fill the gap between the curve and the bars
      DrawRing((Vector2){posX + columnWidth + innerRadius,
                         posY + barHeight + innerRadius},
               innerRadius, innerRadius + barHeight, 180, 270, 0,
               debug ? MAGENTA : color); // Decorative ring around the elbow
    }
    if (barHeight >= columnWidth + innerRadius) {
      DrawRectangle(posX, posY + barHeight, columnWidth, columnHeight,
                    color); // Vertical bar
      DrawRectangle(posX + columnWidth + innerRadius, posY, barWidth, barHeight,
                    debug ? GREEN : color); // Horizontal bar
      Vector2 center = {posX + columnWidth + innerRadius,
                        posY + columnWidth + innerRadius};
      DrawCircleSector(center, innerRadius + columnWidth, 180, 270, 0,
                       debug ? BLUE : color); // Elbow curve
      DrawRectangle(
          posX, posY + columnWidth + innerRadius, columnWidth + innerRadius,
          barHeight - columnWidth - innerRadius,
          debug ? ORANGE
                : color); // Fill the gap between the curve and the bars
      DrawRing((Vector2){posX + columnWidth + innerRadius,
                         posY + barHeight + innerRadius},
               innerRadius, innerRadius + columnWidth, 180, 270, 0,
               debug ? MAGENTA : color); // Decorative ring around the elbow
    }
    break;
  case 1:
    break;
  case 2:
    break;
  case 3:
    if (columnWidth >= barHeight + innerRadius) {
      DrawRectangle(posX, posY, columnWidth, columnHeight,
                    color); // Vertical bar
      DrawRectangle(posX + columnWidth, posY + columnHeight + innerRadius,
                    barWidth, barHeight,
                    debug ? GREEN : color); // Horizontal bar
      Vector2 center = {posX + barHeight + innerRadius, posY + columnHeight};
      DrawCircleSector(center, innerRadius + barHeight, 90, 180, 0,
                       debug ? BLUE : color); // Elbow curve
      DrawRectangle(
          posX + barHeight + innerRadius, posY + columnHeight,
          columnWidth - barHeight - innerRadius, barHeight + innerRadius,
          debug ? ORANGE
                : color); // Fill the gap between the curve and the bars
      DrawRing((Vector2){posX + columnWidth + innerRadius, posY + columnHeight},
               innerRadius, innerRadius + barHeight, 90, 180, 0,
               debug ? MAGENTA : color); // Decorative ring around the elbow
    }
    // if (barHeight >= columnWidth + innerRadius) {
    //     DrawRectangle(posX, posY,columnWidth,columnHeight, color); //
    //     Vertical bar DrawRectangle(posX + columnWidth - innerRadius -
    //     barHeight, posY + columnHeight, barWidth, barHeight, debug ? GREEN :
    //     color); // Horizontal bar Vector2 center = { posX + columnWidth -
    //     innerRadius - barHeight, posY + columnHeight - innerRadius -
    //     barHeight }; DrawCircleSector(center, innerRadius + columnWidth, 90,
    //     180, 0, debug ? BLUE : color); // Elbow curve DrawRectangle(posX +
    //     columnWidth - innerRadius - barHeight, posY + columnHeight -
    //     innerRadius - columnWidth, columnWidth + innerRadius - barHeight,
    //     barHeight - columnWidth - innerRadius, debug ? ORANGE : color); //
    //     Fill the gap between the curve and the bars DrawRing((Vector2){ posX
    //     + columnWidth - innerRadius - barHeight, posY + columnHeight -
    //     innerRadius }, innerRadius, innerRadius + columnWidth, 90, 180, 0,
    //     debug ? MAGENTA : color); // Decorative ring around the elbow
    // }
    break;
  }
}

// Draw text using font inside rectangle limits with support for text selection
static void DrawTextBoxedSelectable(State *s, Element *e, Font font,
                                    const char *text, Rectangle rec,
                                    float fontSize, float spacing,
                                    bool wordWrap, Color tint, int selectStart,
                                    int selectLength, Color selectTint,
                                    Color selectBackTint, float *outTextHeight,
                                    float *outCursorY, int cursorIndex) {
  int length = TextLength(
      text); // Total length in bytes of the text, scanned by codepoints in loop

  float textOffsetY = 0;    // Offset between lines (on line break '\n')
  float textOffsetX = 0.0f; // Offset X to next character to draw

  float scaleFactor =
      fontSize / (float)font.baseSize; // Character rectangle scaling factor
  float lineHeight = (font.baseSize + (float)font.baseSize / 2) * scaleFactor;

  // Word/character wrapping mechanism variables
  enum { MEASURE_STATE = 0, DRAW_STATE = 1 };
  int state = wordWrap ? MEASURE_STATE : DRAW_STATE;

  int startLine = -1; // Index where to begin drawing (where a line begins)
  int endLine = -1;   // Index where to stop drawing (where a line ends)
  int lastk = -1;     // Holds last value of the character position

  float maxTextOffsetY = 0.0f;
  float cursorY = 0.0f;

  float cursorX_screen = rec.x;
  float cursorY_screen = rec.y - e->scrollY;
  bool cursorPositionFound = false;

  for (int i = 0, k = 0; i < length; i++, k++) {
    int charByteIndex = i;
    // Track cursor position
    if (charByteIndex == cursorIndex) {
      cursorX_screen = rec.x + textOffsetX;
      cursorY_screen = rec.y + textOffsetY - e->scrollY;
      cursorY = textOffsetY;
      cursorPositionFound = true;
    }

    // Get next codepoint from byte string and glyph index in font
    int codepointByteCount = 0;
    int codepoint = GetCodepoint(&text[i], &codepointByteCount);
    int index = GetGlyphIndex(font, codepoint);

    // NOTE: Normally we exit the decoding sequence as soon as a bad byte is
    // found (and return 0x3f) but we need to draw all of the bad bytes using
    // the '?' symbol moving one byte
    if (codepoint == 0x3f)
      codepointByteCount = 1;
    i += (codepointByteCount - 1);

    float glyphWidth = 0;
    if (codepoint != '\n') {
      glyphWidth = (font.glyphs[index].advanceX == 0)
                       ? font.recs[index].width * scaleFactor
                       : font.glyphs[index].advanceX * scaleFactor;

      if (i + 1 < length)
        glyphWidth = glyphWidth + spacing;
    }

    // NOTE: When wordWrap is ON we first measure how much of the text we can
    // draw before going outside of the rec container We store this info in
    // startLine and endLine, then we change states, draw the text between those
    // two variables and change states again and again recursively until the end
    // of the text (or until we get outside of the container) When wordWrap is
    // OFF we don't need the measure state so we go to the drawing state
    // immediately and begin drawing on the next line before we can get outside
    // the container
    if (state == MEASURE_STATE) {
      // TODO: There are multiple types of spaces in UNICODE, maybe it's a good
      // idea to add support for more Ref: http://jkorpela.fi/chars/spaces.html
      if ((codepoint == ' ') || (codepoint == '\t') || (codepoint == '\n'))
        endLine = i;

      if ((textOffsetX + glyphWidth) > rec.width) {
        endLine = (endLine < 1) ? i : endLine;
        if (i == endLine)
          endLine -= codepointByteCount;
        if ((startLine + codepointByteCount) == endLine)
          endLine = (i - codepointByteCount);

        state = !state;
      } else if ((i + 1) == length) {
        endLine = i;
        state = !state;
      } else if (codepoint == '\n')
        state = !state;

      if (state == DRAW_STATE) {
        textOffsetX = 0;
        i = startLine;
        glyphWidth = 0;

        // Save character position when we switch states
        int tmp = lastk;
        lastk = k - 1;
        k = tmp;
      }
    } else {
      if (codepoint == '\n') {
        if (!wordWrap) {
          textOffsetY += lineHeight;
          textOffsetX = 0;
        }
      } else {
        if (!wordWrap && ((textOffsetX + glyphWidth) > rec.width)) {
          textOffsetY += lineHeight;
          textOffsetX = 0;
        }

        if (textOffsetY > maxTextOffsetY)
          maxTextOffsetY = textOffsetY;

        bool isVisible =
            (textOffsetY - e->scrollY + (float)font.baseSize * scaleFactor >=
             0) &&
            (textOffsetY - e->scrollY < rec.height);

        // Draw selection background
        bool isGlyphSelected = false;
        if ((selectStart >= 0) && (charByteIndex >= selectStart) &&
            (charByteIndex < (selectStart + selectLength))) {
          if (isVisible) {
            DrawRectangleRec((Rectangle){rec.x + textOffsetX - 1,
                                         rec.y + textOffsetY - e->scrollY,
                                         glyphWidth,
                                         (float)font.baseSize * scaleFactor},
                             selectBackTint);
          }
          isGlyphSelected = true;
        }

        // Draw current character glyph
        if ((codepoint != ' ') && (codepoint != '\t')) {
          if (isVisible) {
            DrawTextCodepoint(font, codepoint,
                              (Vector2){rec.x + textOffsetX,
                                        rec.y + textOffsetY - e->scrollY},
                              fontSize, isGlyphSelected ? selectTint : tint);
          }
        }
      }

      if (wordWrap && (i == endLine)) {
        textOffsetY += lineHeight;
        textOffsetX = 0;
        startLine = endLine;
        endLine = -1;
        glyphWidth = 0;
        selectStart += lastk - k;
        k = lastk;

        state = !state;
      }
    }

    if ((textOffsetX != 0) || (codepoint != ' '))
      textOffsetX += glyphWidth; // avoid leading spaces
  }

  if (textOffsetY > maxTextOffsetY)
    maxTextOffsetY = textOffsetY;

  if (!cursorPositionFound && cursorIndex >= length) {
    cursorX_screen = rec.x + textOffsetX;
    cursorY_screen = rec.y + textOffsetY - e->scrollY;
    cursorY = textOffsetY;
  }

  // Draw the cursor if focused
  if (e->isFocused) {
    if (e->textSelectedFramesCounter / 40 % 2 == 0) {
      DrawRectangleRec((Rectangle){cursorX_screen, cursorY_screen, 2.0f,
                                   (float)font.baseSize * scaleFactor},
                       RED);
    }
  }

  if (outTextHeight)
    *outTextHeight = maxTextOffsetY + lineHeight;
  if (outCursorY)
    *outCursorY = cursorY;
}

// Draw text using font inside rectangle limits
static void DrawTextBoxed(State *s, Element *e, Font font, const char *text,
                          Rectangle rec, float fontSize, float spacing,
                          bool wordWrap, Color tint, float *outTextHeight,
                          float *outCursorY, int cursorIndex) {
  if (s->debug)
    DrawText(TextFormat("Selection start: %d, end: %d, length: %d",
                        e->selectTextStart, e->selectTextEnd,
                        e->selectTextLength),
             rec.x, rec.y - 20, 10, RED);

  int selStart = e->selectTextLength > 0
                     ? e->selectTextStart
                     : e->selectTextStart + e->selectTextLength;
  int selLength =
      e->selectTextLength > 0 ? e->selectTextLength : -e->selectTextLength;
  DrawTextBoxedSelectable(s, e, font, text, rec, fontSize, spacing, wordWrap,
                          tint, selStart, selLength, BLACK, LCARS_RED_ORANGE,
                          outTextHeight, outCursorY, cursorIndex);
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
  // if (IsKeyDown(KEY_LEFT_CONTROL)) {
  //     if (s->notificationOnElemIdx != -2) {
  //         snprintf(s->notification, NOTIFICATION_MAX_LEN, "[Changing
  //         Perspective]"); s->notificationTimer = NOTIFICATION_DURATION;
  //         s->notificationOnElemIdx = -2;
  //     } else {
  //         s->notificationTimer = NOTIFICATION_DURATION; // Reset timer while
  //         holding shift
  //     }
  //     // HideCursor();
  // }

  Update(s);
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
      // DrawSphere(e->position3, 2.0f, e->color);
      // DrawModelWiresEx(e->model,

      DrawModelEx(e->model, e->position3, (Vector3){0.0f, 1.0f, 0.0f},
                  e->rotation, (Vector3){2.0f, 2.0f, 2.0f}, e->color);

      // DrawModel(e->model, e->position3, 1.0f, e->color);

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
      DrawText(e->text, e->position.x, e->position.y, e->textSize, e->color);
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
      // if (s->is_editing) {
      DrawTextureRec(e->renderTexture.texture,
                     (Rectangle){0, 0, *e->width, *e->height},
                     (Vector2){e->position.x, e->position.y}, WHITE);

      if (s->debug) {
        // DrawRectangle(e->position.x- 5, e->position.y + 5, e->width + 10,
        // e->height + 10, RED); Vector2 screenPos =
        // GetWorldToScreen(e->position3, e->camera);
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
      // }
      break;
    }
    case ELEM_NOTHING:
    case ELEM_TOTAL_KINDS:
      break;
    }

    if (e->text && e->kind != ELEM_TEXT && e->kind != ELEM_TEXT_EDITOR) {
      int textWidth = MeasureText(e->text, e->textSize);
      if (e->kind == ELEM_ELBOW) {
        DrawText(e->text, e->position.x + 3 * (*e->width - textWidth) / 4,
                 e->position.y + s->barHeight + s->innerRadius +
                     (*e->height - e->textSize) / 2,
                 e->textSize, BLACK);
      } else {
        DrawText(e->text, e->position.x + 3 * (*e->width - textWidth) / 4,
                 e->position.y + (*e->height - e->textSize) / 2 + 10,
                 e->textSize, BLACK);
      }
    }
  }

  if (s->notification && s->notificationTimer > 0.0f) {
    s->notificationTimer -= GetFrameTime();
    DrawText(s->notification, s->posX + s->columnWidth + s->innerRadius,
             s->posY - 2 * s->columnHeight - s->barHeight, 20, YELLOW);
  } else {
    s->notificationOnElemIdx = -1;
  }

  // if (!s->is_editing) {
  //     int i = 0;
  //     GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i *
  //     30, .width=120, .height=20}, "Col W ", sprintf_static(s, i, "%.0f",
  //     s->columnWidth) ,         &s->columnWidth , 0, 300); i++;
  //     GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i *
  //     30, .width=120, .height=20}, "Bar H ", sprintf_static(s, i, "%.0f",
  //     s->barHeight)   , &s->barHeight   , 0, 300); i++;
  //     GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i *
  //     30, .width=120, .height=20}, "Radius", sprintf_static(s, i, "%.0f",
  //     s->innerRadius) , &s->innerRadius , 0, 50 ); i++;
  //     GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i *
  //     30, .width=120, .height=20}, "Col H ", sprintf_static(s, i, "%.0f",
  //     s->columnHeight), &s->columnHeight, 0, 600); i++;
  //     GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i *
  //     30, .width=120, .height=20}, "Bar W ", sprintf_static(s, i, "%.0f",
  //     s->barWidth)    , &s->barWidth    , 0, 600); i++; GuiToggle(
  //     (Rectangle){.x=s->controllsX,       .y=s->controllsY + i * 30,
  //     .width=120, .height=20}, "Debug (d)", &s->debug); i++; GuiToggle(
  //     (Rectangle){.x=s->controllsX + 130, .y=s->controllsY + (i - 1) * 30,
  //     .width=120, .height=20}, "Hide controlls (h)",&s->is_editing);
  //
  //     char* code = sprintf_static(s,
  //         i, "DrawElbow(%.0f, %.0f, %.0f, %.0f, %.0f, %.0f, %.0f, lcarsColor,
  //         %s);", s->posX, s->posY, s->columnWidth, s->columnHeight,
  //         s->barWidth, s->barHeight, s->innerRadius, s->debug ? "true" :
  //         "false"
  //     );
  //
  //     if (GuiTextBox((Rectangle){.x=s->controllsX, .y=s->controllsY + i * 30,
  //     .width=500, .height=50},
  //                 code,
  //                 22,
  //                 0)) {s->textBoxEditMode = !s->textBoxEditMode;}
  //     i+=2;
  // }

  if (s->debug) {
    DrawFPS(10, 10);
    DrawText(TextFormat("x:%.2f, y:%.2f", mPos.x, mPos.y), mPos.x + 20, mPos.y,
             10, GREEN);
  }
  // DrawText(TextFormat("Rotation: %.2f", s->elements[21].rotation), 10, 30,
  // 10, WHITE);

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
}

#endif // LCARS_IMPLEMENTATION
