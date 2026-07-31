#ifndef LCARS_TYPES_H
#define LCARS_TYPES_H

#include "raylib.h"
#include "vendor/sqlite3.h"
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

#include "lcars_arena.h"
#include "lcars_string.h"

#define LCARS_PURPLE (Color){206, 153, 205, 255}
#define LCARS_RED_ORANGE (Color){204, 102, 102, 255}
#define LCARS_ORANGE (Color){255, 154, 102, 255}
#define LCARS_YELLOW (Color){255, 205, 154, 255}
#define LCARS_BLUE (Color){155, 155, 255, 255}
#define LCARS_GREEN (Color){153, 204, 153, 255}
#define TODO                                                                   \
  printf("Exiting %s:%d", __FILE__, __LINE__);                                 \
  exit(1)

#define WINDOW_WIDTH 1600
#define WINDOW_HEIGHT 900

#define MAX_ELEMENTS 10000
#define MAX_INPUT_CHARS 1024
#define MAX_KINDS 32

#define TEXT_VOICE_INPUT "Voice Input"
#define TEXT_RECORDING "RECORDING..."

#define NOTIFICATION_DURATION 3.0f
#define NOTIFICATION_MAX_LEN 48

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

typedef struct Element {
  ElemKind kind;
  ButtonAction on_click;
  Vector2 position;
  Vector3 position3;
  float *width, *height;
  Color color;
  Color originalColor;
  int elbowOrientation; // Only used if kind == ELBOW
  String text;          // Text on button or just text elem
  int textLen;          // text lenght of chars.
  int textSize;         // Only used if kind == TEXT / TEXTBOX for display size
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
  bool listCollapsed;
  float listScrollY;
  int selectedEntryId;

  KindList kindList;
  String selectedKind;
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
  void *voiceApi;
  double time_resource_download;
  double time_voice_init;
  double time_window_init;
  Arena doc_arena;
  Arena scratch_arena;
  Rectangle selection_rec;
} State;

typedef struct EntryListItem {
  int id;
  char title[128];
  char created_at[32];
  char last_modified[32];
} EntryListItem;

#endif // LCARS_TYPES_H
