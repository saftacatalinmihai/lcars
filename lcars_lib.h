// #include <_locale_posix2008.h>
#include <stdio.h>
#include <stdlib.h>
#define _POSIX_C_SOURCE 200809L
#include <string.h>
#include "raygui.h"
#include "raylib.h"
#include "raymath.h"
#include "rlgl.h"
#include "sqlite3.h"
#include <time.h>

#define _ISOC99_SOURCE
#include <math.h>

#define LCARS_PURPLE (Color){ 206, 153, 205, 255 }
#define LCARS_RED_ORANGE (Color){ 204, 102, 102, 255 }
#define LCARS_ORANGE (Color){ 255, 154, 102, 255 }
#define LCARS_YELLOW (Color){ 255, 205, 154, 255 }
#define LCARS_BLUE (Color){ 155, 155, 255, 255 }
#define TODO exit(1)

#define MAX_ELEMENTS 100
#define MAX_INPUT_CHARS 1024

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
    iVec2 position;
    Vector3 position3;
    float width, height;
    Color color;
    Color originalColor;
    int elbowOrientation; // Only used if kind == ELBOW
    char* text; // Text on button or just text elem
    int textLen; // text lenght of chars.
    int textLineLen; // crt line len
    int textLines; 
    int textSize; // Only used if kind == TEXT / TEXTBOX for display size
    Model model;
    float rotation;
    RenderTexture renderTexture;
    Camera camera;
} Element;

typedef struct State {
    Element elements[MAX_ELEMENTS];
    char staticText[64][32 * 1024];
    int numElements;
    Color lcarsColor;
    float posX, posY, columnWidth, columnHeight, barWidth, barHeight, innerRadius;
    bool debug;
    bool hide_controlls;
    int controllsX;
    int controllsY;
    bool textBoxEditMode;
    Font font;
    char* notification;
    int notificationOnElemIdx;
    float notificationTimer;
    int mouseOnTextBox;
    int textSelectedFramesCounter;
    int selectTextStart;
    int selectTextLength; 
    int selectTextEnd;
    bool isDeletingText;
    float deletingTextStartTime;
    bool selectingText;
    Ray ray;                    // Picking line ray
    RayCollision collision;     // Ray collision hit info
    sqlite3 *db;
} State;

void UpdateDrawFrame(State *s);
void Init(State *s, bool firstInit);

#define NOTIFICATION_DURATION 3.0f
#define NOTIFICATION_MAX_LEN 48

void updateNotification(State* s, const char* notificationText) {
    snprintf(s->notification, NOTIFICATION_MAX_LEN, "%s", notificationText);
    s->notificationTimer = NOTIFICATION_DURATION;
}

// #ifndef NOTDEV // Used to allow the bellow 
// #define LCARS_IMPLEMENTATION // TEMP used for dev editing this file
// #endif // NOTDEV

#ifdef LCARS_IMPLEMENTATION

#define MAX(a,b) ((a) > (b) ? (a) : (b))
#define MIN(a,b) ((a) < (b) ? (a) : (b))

char* sprintf_static(State*s, int index, const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    vsnprintf(s->staticText[index], sizeof(s->staticText[index]), fmt, args);
    va_end(args);
    return s->staticText[index];
}

static void ReLayout(State *s);
// static void updateNotification(State* s, const char* notificationText);

static int sqlite_callback(void *NotUsed, int argc, char **argv, char **azColName) {
   int i;
   for(i = 0; i < argc; i++) {
      printf("%s = %s\n", azColName[i], argv[i] ? argv[i] : "NULL");
   }
   printf("\n");
   return 0;
}

static void InitDB(State* s, bool firstInit) {
    char *zErrMsg = 0;
    /* Create SQL statement */
    char * sql = "CREATE TABLE IF NOT EXISTS log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "text TEXT)";

    /* Execute SQL statement */
    int rc = sqlite3_exec(s->db, sql, sqlite_callback, 0, &zErrMsg);

    if(rc != SQLITE_OK){
        fprintf(stderr, "SQL error: %s\n", zErrMsg);
        updateNotification(s, "SQL error");
        // sqlite3_free(zErrMsg);
    } else {
        fprintf(stdout, "Table created successfully\n");
        updateNotification(s, "Table created successfully");
    }

    char datename[32];
    struct tm* to;
    time_t t;
    t = time(NULL);
    to = localtime(&t);
    strftime(datename, sizeof(datename), "%Y-%m-%d", to);

    // if (firstInit) {
        char * sql_insert = "INSERT OR IGNORE INTO log (id, text) VALUES (0, '%s Captain log')";
        char* sql_insert_full = malloc(strlen(sql_insert) + 11 + strlen(datename) + 1);
        snprintf(sql_insert_full, strlen(sql_insert) + 11, "INSERT OR IGNORE INTO log (id, text) VALUES (0, '%s Captain log')", datename);
        // printf("SQL to execute: %s\n", sql_insert_full);
        rc = sqlite3_exec(s->db, sql_insert_full, sqlite_callback, 0, &zErrMsg);

        if(rc != SQLITE_OK){
            fprintf(stderr, "SQL error: %s\n", zErrMsg);
            updateNotification(s, "SQL error");
            // sqlite3_free(zErrMsg);
        } else {
            fprintf(stdout, "Data inserted successfully\n");
            updateNotification(s, "Data inserted successfully");
        }
    // }
}

static char* GetLogFromDB(State* s) {
    char* output = malloc(MAX_INPUT_CHARS);
    sqlite3_stmt *stmt;
    //create prepared statement
    int rc = sqlite3_prepare_v2(s->db, "SELECT text FROM log where id=?1", -1, &stmt, 0);
    if (rc != SQLITE_OK)
        updateNotification(s, "failure fetching data");

    //bind values to parameters
    sqlite3_bind_text(stmt, 1, "0", -1, SQLITE_STATIC);

    //run the SQL
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        output = strdup((char*)sqlite3_column_text(stmt, 0));
    }

    //destroy the object to avoid resource leaks
    sqlite3_finalize(stmt);
    return output;
}

static void UpdateLogInDB(State* s, const char* newLog) {
    char *zErrMsg = 0;
    // char * sql_update = "UPDATE log SET text = '%s' WHERE id = 0";
    char* sql_update_full = sqlite3_mprintf("UPDATE log SET text = (%Q) WHERE id = 0;", newLog);
    if (!sql_update_full) {
        fprintf(stderr, "SQL error: %s\n", zErrMsg);
        updateNotification(s, "SQL error");
    }

    // char* sql_update_full = malloc(strlen(sql_update) + strlen(newLog) + 1);
    // snprintf(sql_update_full, strlen(sql_update) + strlen(newLog), "UPDATE log SET text = '%s' WHERE id = 0", newLog);
    // printf("SQL to execute: %s\n", sql_update_full);
    int rc = sqlite3_exec(s->db, sql_update_full, sqlite_callback, 0, &zErrMsg);

    if(rc != SQLITE_OK){
        fprintf(stderr, "SQL error: %s\n", zErrMsg);
        updateNotification(s, "SQL error");
    } else {
        // fprintf(stdout, "Data updated successfully\n");
        // updateNotification(s, "Data updated successfully");
    }
}

Vector2 V2fromiVec2(iVec2 v) {
    return (Vector2){ v.x, v.y };
}

// 2

void Init(State *s, bool firstInit) {
    s->debug = false;
    s->hide_controlls = true; 
    s->controllsX = 600;
    s->controllsY = 400;
    s->lcarsColor = (Color){ 204, 153, 204, 255 }; // Purple
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

    char* notificationText = (char*)malloc(NOTIFICATION_MAX_LEN);
    notificationText[0] = '\0';
    s->notification = notificationText;
    ReLayout(s);

    if (firstInit) {
        sqlite3 *db = malloc(sizeof(sqlite3*));
        int rc = sqlite3_open("lcars.db", &db);
        if(rc) {
            fprintf(stderr, "Can't open database: %s\n", sqlite3_errmsg(db));
        } else {
            fprintf(stderr, "Opened database successfully\n");
        }
        s->db = db;
    }
    InitDB(s, firstInit);

    char* text =  malloc(MAX_INPUT_CHARS + 1);
    strcpy(text, (const char*)GetLogFromDB(s));  
    // strcpy(text, "Insert text here");  

    printf("Loaded text from DB: %s\n", text);
    int textLen = strlen(text);
    printf("Text len: %d\n", textLen);
    text[MAX_INPUT_CHARS] = '\0';
    s->elements[s->numElements++] = (Element) {
        .kind=ELEM_TEXT_EDITOR,
        .position = { s->posX + s->columnWidth + s->innerRadius + 60, s->posY + s->barHeight + 80 },
        .width = 600,
        .height = 400,
        .color = LCARS_PURPLE,
        .originalColor = LCARS_PURPLE,
        .textSize = 20,
        .text=text,
        .textLen = textLen,
        .textLineLen = textLen
    };
    s->mouseOnTextBox = -1;
    s->selectTextStart = -1;
    s->selectTextLength = 0;
    s->selectTextEnd = -1;
    s->selectingText = false;

    s->font = GetFontDefault();
    // s->font = LoadFont("NotoColorEmoji-Regular.ttf");

    Image image;
    if (FileExists("resources/earth.png")) {
        image = LoadImage("resources/earth.png");
        // ImageToPOT(&image, BLACK);
        ImageFormat(&image, PIXELFORMAT_UNCOMPRESSED_R8G8B8A8); // Convert RGB to RGBA
        // PIXELFORMAT_UNCOMPRESSED_R8G8B8A8
        TraceLog(LOG_WARNING, "Texture ready!");
        s->elements[1].text = NULL;
        s->elements[1].textSize = 0;
    } else {
        TraceLog(LOG_WARNING, "Texture not ready yet!");
        s->elements[1].text = "Texture not ready!";
        s->elements[1].textSize=20;
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

    s->elements[s->numElements++] = (Element){
        .kind=ELEM_SPHERE,
        .position3 = {0,0,0},
        .position = {910, 310}, // Used to create the render texture area where the 3d element is inside.
        .width = 300,
        .height = 300,
        .color = WHITE,
        .originalColor = WHITE,
        .model = earthModel,
        .rotation = 0
    };

    GuiLoadStyle("style_cyber.rgs");

    for (int i=0; i<MAX_ELEMENTS; i++) {
        switch (s->elements[i].kind) {
            case ELEM_SPHERE: {
                // Element e = s->elements[i];
                Element *e = &s->elements[i];

                Camera camera = { 0 };
                camera.position = (Vector3){ 10.0f, -10.0f, 10.0f };
                camera.target = (Vector3){ 0.0f, 0.0f, 0.0f };
                camera.up = (Vector3){ 0.0f, 1.0f, -0.23f };
                camera.fovy = 45.0f;
                camera.projection = CAMERA_PERSPECTIVE;
                e->camera = camera;

                RenderTexture renderTexture = LoadRenderTexture(e->width, e->height);
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
    if (reset){
        Init(s, false);
    } else {
        GuiLoadStyle("style_cyber.rgs");
    }
}

void ReLayout(State *s) {
    s->numElements = 0; // Clear existing elements before re-adding them with new layout
    int gap = 6;

    float w[4] = {40, 140, 400, 40};

    // Upper elbow
    int yu = s->posY - s->columnHeight - s->innerRadius - s->barHeight;

    s->elements[s->numElements++] = (Element){ .kind = ELEM_ELBOW, .elbowOrientation = 3, .position = {s->posX, yu - gap}, .width = s->columnWidth, .height = s->columnHeight, .color = LCARS_BLUE }; yu -= gap;
    s->elements[s->numElements++] = (Element){ .kind = ELEM_RECTANGLE, .position = {s->posX, yu - 100 - gap}, .width = s->columnWidth, .height = 100, .color = LCARS_PURPLE, .text=s->elements[1].text, .textSize = s->elements[1].textSize}; yu -= 100;

    int xu = s->posX + s->columnWidth + s->barWidth;
    s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE, .position = {xu + gap, s->posY - s->barHeight - gap}, .width = w[0], .height = s->barHeight, .color = LCARS_ORANGE }; xu += 40 + gap;
    s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE, .position = {xu + gap, s->posY - s->barHeight - gap}, .width = w[1], .height = s->barHeight, .color = LCARS_PURPLE }; xu += 140 + gap;
    s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE, .position = {xu + gap, s->posY - s->barHeight - gap}, .width = w[2], .height = s->barHeight, .color = LCARS_PURPLE }; xu += 400 + gap;
    s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE, .position = {xu + gap, s->posY - s->barHeight - gap}, .width = w[3], .height = s->barHeight, .color = LCARS_RED_ORANGE }; xu += 40 + gap;

    // Lower elbow
    s->elements[s->numElements++] = (Element){ .kind = ELEM_ELBOW, .position = {s->posX, s->posY}, .width = s->columnWidth, .height = s->columnHeight, .color = LCARS_RED_ORANGE, .text="03-975883" , .textSize=20 };
    int y = s->posY + s->columnHeight + s->barHeight + s->innerRadius;
    s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE, .position = {s->posX, y + gap}, .width = s->columnWidth, .height = 200, .color = LCARS_RED_ORANGE, .text="04-785466", .textSize=20 }; y = y + 200 + gap;
    s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE, .position = {s->posX, y + gap}, .width = s->columnWidth, .height = 60, .color = LCARS_ORANGE, .text="05-423512", .textSize=20 }; y = y + 60 + gap;
    s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE, .position = {s->posX, y + gap}, .width = s->columnWidth, .height = 250, .color = LCARS_ORANGE, .text="06-572983", .textSize=20 }; y = y + 250 + gap;

    int x = s->posX + s->columnWidth + s->barWidth;
    s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE, .position = {x + gap, s->posY}, .width = w[0], .height = s->barHeight, .color = LCARS_YELLOW, }; x = x + 40 + gap;
    s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE, .position = {x + gap, s->posY}, .width = w[1], .height = s->barHeight / 2, .color = LCARS_YELLOW }; x = x + 140 + gap;
    s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE, .position = {x + gap, s->posY}, .width = w[2], .height = s->barHeight, .color = LCARS_PURPLE }; x = x + 400 + gap;
    s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE, .position = {x + gap, s->posY}, .width = w[3], .height = s->barHeight, .color = LCARS_ORANGE }; x = x + 40 + gap;

    int buttonHeight = 50;
    s->elements[s->numElements++] = (Element){ .kind=ELEM_BUTTON, .position = { x - 220      , s->posY - 20 - s->barHeight - 2 * buttonHeight - 10 }, .width = 210, .height = buttonHeight, .color = LCARS_ORANGE, .text="(LC+d)ebug 9888-24", .textSize=20 };
    s->elements[s->numElements++] = (Element){ .kind=ELEM_BUTTON, .position = { x - 220 - 220, s->posY - 20 - s->barHeight - 2 * buttonHeight - 10 }, .width = 210, .height = buttonHeight, .color = LCARS_BLUE, .text="(LC+e)dit 0129-86" ,.textSize=20};
    s->elements[s->numElements++] = (Element){ .kind=ELEM_BUTTON, .position = { x - 220      , s->posY - 20 - s->barHeight - buttonHeight  }, .width = 210, .height = buttonHeight, .color = LCARS_BLUE, .text="(LC+r)eset 7232-83", .textSize=20 };
    s->elements[s->numElements++] = (Element){ .kind=ELEM_BUTTON, .position = { x - 220 - 220, s->posY - 20 - s->barHeight - buttonHeight  }, .width = 210, .height = buttonHeight, .color = LCARS_ORANGE, .text="1014-819", .textSize=20 };

    s->elements[s->numElements++] = (Element){ .kind=ELEM_TEXT, .position = { x - 220 - 220 - 20, yu }, .color = LCARS_YELLOW, .textSize = 48, .text="LCARS ACCESS 441" };
    // s->elements[s->numElements++] = (Element){ .kind=ELEM_TEXT, .position = { s->posX + s->columnWidth + s->innerRadius, s->posY - 2 * s->columnHeight - s->barHeight - 40 - 10 }, .color = LCARS_YELLOW, .textSize = 20, .text="LShift to move camera perspective with mouse\nLShift + W,A,S,D to move object\n" };
}

//  void updateNotification(State* s, const char* notificationText) {
//     snprintf(s->notification, NOTIFICATION_MAX_LEN, "%s...", notificationText);
//     s->notificationTimer = NOTIFICATION_DURATION;
// }

static void clickOrHoverNotification(State* s, int i, char* elem_pretty_name) {
    if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON)) {
        // printf("Clicked %s %d\n", elem_pretty_name, i);
        snprintf(s->notification, NOTIFICATION_MAX_LEN, "[Clicked %s %d] %s", elem_pretty_name, i, s->elements[i].text ? s->elements[i].text : "");
        s->notificationTimer = NOTIFICATION_DURATION;
        s->notificationOnElemIdx = i;
    } else if (s->notificationOnElemIdx != i) {
        snprintf(s->notification, NOTIFICATION_MAX_LEN, "[Hovering %s %d] %s", elem_pretty_name, i, s->elements[i].text ? s->elements[i].text : "");
        // printf("Hovering\n");
        s->notificationTimer = NOTIFICATION_DURATION;
        s->notificationOnElemIdx = i;
    }
}

// Helper function to find the character index under the mouse
int GetCharIndexAtMouse(const State* s, Font font, const char *text, Vector2 textPos, float fontSize, float spacing, Vector2 mousePos) {
    int len = strlen(text);
    float currentWidth = 0.0f;
    int lineNr = 0;

    float scaleFactor = fontSize/(float)font.baseSize;
    float textOffsetY = (font.baseSize + (float)font.baseSize/2)*scaleFactor;
    
    if (mousePos.x < textPos.x) return 0;
    if (mousePos.y < textPos.y) return 0;

    for (int i = 0; i < len; i++) {
        
        if (text[i] == '\n') {
            lineNr++;
            currentWidth = 0;
        }

        // Measure text up to the CURRENT character
        char subStr[2] = { text[i], '\0' };
        Vector2 textMeasure = MeasureTextEx(font, subStr, fontSize, spacing);
        float charWidth = textMeasure.x;
        // float charHeight = textMeasure.y;
        
        // If the mouse hits the left half or right half of the character
        if (s->debug) DrawRectangleLinesEx((Rectangle){ 
            .x = textPos.x + currentWidth + spacing, 
            .y = textPos.y + textOffsetY * lineNr, 
            .width = charWidth + spacing, 
            .height = textOffsetY 
        }, 1, RED);

        if (mousePos.y >= textPos.y + textOffsetY * lineNr && mousePos.y < textPos.y + textOffsetY * (lineNr + 1) && 
            mousePos.x >= textPos.x + currentWidth + spacing && mousePos.x < textPos.x + currentWidth + charWidth + spacing) {
            // printf("1\n");
            // Snap to the closest edge of the character
            if (s->debug) DrawRectangleLinesEx((Rectangle){ 
                .x = textPos.x + currentWidth + spacing, 
                .y = textPos.y + textOffsetY * lineNr, 
                .width = charWidth + spacing, 
                .height = textOffsetY 
            }, 2, GREEN);
            if (mousePos.x > textPos.x + currentWidth + (charWidth / 2.0f)) return i + 1;
            return i;
        }
        currentWidth += charWidth + spacing;
    }

    return 0;
}

void Update(State *s) {
    Vector2 mPos = GetMousePosition();
    // UpdateCamera(&s->camera, CAMERA_ORBITAL);

    ReLayout(s);
    int textBoxIdx = -1;
    for (int i = 0; i < MAX_ELEMENTS; i++) {
        Element *e = &s->elements[i];
        switch (s->elements[i].kind) {
            case ELEM_RECTANGLE:
                if (CheckCollisionPointRec(GetMousePosition(), (Rectangle){.x=s->elements[i].position.x, .y=s->elements[i].position.y, .width = s->elements[i].width ? s->elements[i].width : 0, .height = s->elements[i].height})) {
                    s->elements[i].color = ColorBrightness(s->elements[i].color, 0.2f);
                    clickOrHoverNotification(s, i, "element");
                }
                break;
            case ELEM_ELBOW:
                switch (s->elements[i].elbowOrientation) {
                    case 0: 
                        if (
                            CheckCollisionPointRec(GetMousePosition(), (Rectangle){.x=s->elements[i].position.x, .y=s->elements[i].position.y, .width = s->elements[i].width, .height = s->elements[i].height + s->barHeight + s->innerRadius}) ||
                            CheckCollisionPointRec(GetMousePosition(), (Rectangle){.x=s->elements[i].position.x, .y=s->elements[i].position.y, .width = s->columnWidth + s->barWidth, .height = s->barHeight})
                        ) {
                            s->elements[i].color = ColorBrightness(s->elements[i].color, 0.2f);
                            clickOrHoverNotification(s, i, "elbow element");
                        }
                        break;
                    case 1: 
                        TODO;
                        break;
                    case 2: break;
                    case 3: 
                        if (
                            CheckCollisionPointRec(GetMousePosition(), (Rectangle){.x=s->elements[i].position.x, .y=s->elements[i].position.y, .width = s->elements[i].width, .height = s->elements[i].height + s->barHeight + s->innerRadius}) ||
                            CheckCollisionPointRec(GetMousePosition(), (Rectangle){.x=s->elements[i].position.x, .y=s->elements[i].position.y + s->columnHeight + s->innerRadius, .width = s->columnWidth + s->barWidth, .height = s->barHeight})
                        ) {
                            s->elements[i].color = ColorBrightness(s->elements[i].color, 0.2f);
                            clickOrHoverNotification(s, i, "elbow element");
                        }
                        break;
                }
                break;
            case ELEM_BUTTON:
                if (CheckCollisionPointRec(GetMousePosition(), (Rectangle){.x=s->elements[i].position.x, .y=s->elements[i].position.y, .width = s->elements[i].width, .height = s->elements[i].height})) {
                    s->elements[i].color = ColorBrightness(s->elements[i].color, 0.2f);
                    clickOrHoverNotification(s, i, "button element");
                    if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON)) {
                        if (e->text) {
                            if (strstr(e->text, "(LC+d)ebug")) {
                                s->debug = !s->debug;
                            }
                            if (strstr(e->text, "(LC+e)dit")) {
                                s->hide_controlls = !s->hide_controlls;
                            }
                            if (strstr(e->text, "(LC+r)eset")) {
                                Reload(s, true);
                            }
                        }
                    }
                }
                break;

            case ELEM_TEXT: break;
            case ELEM_TEXT_EDITOR:
                // s->elements[i].width = MeasureText(s->elements[i].text, s->elements[i].textSize) + 10;
                if (CheckCollisionPointRec(GetMousePosition(), (Rectangle){.x=s->elements[i].position.x, .y=s->elements[i].position.y, .width = s->elements[i].width, .height = s->elements[i].height})) { 
                    clickOrHoverNotification(s, i, "text box element");
                    if (s->mouseOnTextBox != i ) s->elements[i].color = ColorBrightness(s->elements[i].color, 0.2f);
                    s->mouseOnTextBox = i;
                    textBoxIdx = i;
                } else {
                    s->mouseOnTextBox = -1;
                    s->elements[i].color = s->elements[i].originalColor;
                    textBoxIdx = -1;
                }
                break;
            case ELEM_SPHERE: {
                // Element e = s->elements[i];
                // s->ray = GetScreenToWorldRay(GetMousePosition(), e->camera);
                // s->collision = GetRayCollisionSphere(s->ray, e->position3, 3);
                bool isHovering = CheckCollisionPointRec(GetMousePosition(), (Rectangle){.x=s->elements[i].position.x, .y=s->elements[i].position.y, .width = s->elements[i].width, .height = s->elements[i].height});

                if (isHovering) {
                // if (s->collision.hit) {
                    // printf("Hit sphere element %d\n", i);
                    e->color = ColorBrightness(GREEN, 0.8f);
                    // if (!(memcmp(&e->color, &e->originalColor, sizeof(Color)) == 0)) e->color = BLUE;
                    clickOrHoverNotification(s, i, "sphere element");
                    if (IsMouseButtonDown(MOUSE_BUTTON_LEFT)){
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
                //     MatrixRotateX(DEG2RAD * 90.0f)        // Initial tilt to fix JPG orientation
                // );
            }
            case ELEM_NOTHING:
            case ELEM_TOTAL_KINDS:
                break;
        }
    }
    if (s->mouseOnTextBox != -1) s->textSelectedFramesCounter++;
    else s->textSelectedFramesCounter = 0;

    if (s->mouseOnTextBox != -1) {
        Element *e = &s->elements[textBoxIdx];
        // Set the window's cursor to the I-Beam
        SetMouseCursor(MOUSE_CURSOR_IBEAM);

        // Get char pressed (unicode character) on the queue
        int key = GetCharPressed();

        // Check if more characters have been pressed on the same frame
        while (key > 0)
        {
            // printf("Char: %c\n", key);
            // NOTE: Only allow keys in range [32..125]
            if ((key >= 32) && (key <= 125) && (s->elements[textBoxIdx].textLen  < MAX_INPUT_CHARS))
            {
                // printf("Mouse on text box element %d\n", textBoxIdx);
                // printf("Text box %d: %s\n", textBoxIdx, e->text);
                e->text[e->textLen] = (char)key;
                e->text[e->textLen + 1] = '\0'; // Add null terminator at the end of the string
                e->textLen++;
                e->textLineLen++;
                UpdateLogInDB(s, e->text); // Inefficient ... 
                // printf("Text Line Len: %d\n", e->textLineLen);
                // printf("Text box %d: %s\n", textBoxIdx, e->text);
            }

            key = GetCharPressed();  // Check next character in the queue
        }



        if ((IsKeyDown(KEY_LEFT_CONTROL) || IsKeyDown(KEY_LEFT_SUPER)) && IsKeyPressed(KEY_C)) {
            if (s->selectTextLength <= 0) {
                SetClipboardText(e->text);
                updateNotification(s, "All text copied to clipboard");
                printf("Copied all text to clipboard: |%s|\n", e->text);
            } else {
                char* selectedText = (char*)malloc(s->selectTextLength + 1);
                selectedText[s->selectTextLength] = '\0'; // Null-terminate the selected text
                SetClipboardText(strncpy(selectedText, e->text + s->selectTextStart, s->selectTextLength));
                printf("Copied to clipboard: |%s|\n", selectedText);
                updateNotification(s, "Selected text copied to clipboard");
                free(selectedText);
            }
        }
        if ((IsKeyDown(KEY_LEFT_CONTROL) || IsKeyDown(KEY_LEFT_SUPER)) && IsKeyPressed(KEY_V)) {
            const char* clipboardText = GetClipboardText();
            int clipboardTextLen = strlen(clipboardText);
            printf("Clipboard text length: %d\n", clipboardTextLen);
            snprintf(e->text + e->textLen, clipboardTextLen + 1, "%s", clipboardText);
            e->textLen += clipboardTextLen;
            e->textLineLen += clipboardTextLen;
            e->text[e->textLen] = '\0'; // Add null terminator at the end of the string
            printf("Pasted from clipboard: |%s|\n", clipboardText);
            updateNotification(s, "Clipboard text pasted");
        }
        // Saving on every keystroke so the save controll is not needed.
        // if ((IsKeyDown(KEY_LEFT_CONTROL) || IsKeyDown(KEY_LEFT_SUPER)) && IsKeyPressed(KEY_S)) {
        //     UpdateLogInDB(s, e->text);
        //     updateNotification(s, "Saved to LCARS database");
        // }

        if (IsKeyPressed(KEY_ENTER)) {
            e->text[e->textLen] = (char)'\n';
            e->text[e->textLen + 1] = '\0'; // Add null terminator at the end of the string
            e->textLen++;
            e->textLines++;
            e->textLineLen = 0;
            UpdateLogInDB(s, e->text); // Inefficient ...
        }

        if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT)) {
            s->selectingText = true;
            s->selectTextStart = GetCharIndexAtMouse(s, s->font, e->text, V2fromiVec2(e->position), e->textSize, 2.0, mPos);
            s->selectTextEnd = s->selectTextStart;
            s->selectTextLength = 0;
        }

        if (IsKeyDown(KEY_LEFT_CONTROL) && IsKeyPressed(KEY_A)) {
            s->selectingText = true;
            s->selectTextStart = 0;
            s->selectTextEnd = e->textLen;
            s->selectTextLength = e->textLen;
        }

        if (s->selectingText) {
            int textEnd = GetCharIndexAtMouse(s, s->font, e->text, V2fromiVec2(e->position), e->textSize, 2.0, mPos);
            if (textEnd == 0) {
                
            } else {
                s->selectTextEnd = textEnd;
                s->selectTextLength = s->selectTextEnd - s->selectTextStart;
            }

            if (IsMouseButtonReleased(MOUSE_BUTTON_LEFT)) {
                s->selectingText = false;
            }
        }

        if (s->selectTextStart >= 0 && s->selectTextEnd != s->selectTextStart && (IsKeyPressed(KEY_DELETE) || IsKeyPressed(KEY_BACKSPACE))) {
            int selStart = s->selectTextLength > 0 ? s->selectTextStart : s->selectTextStart + s->selectTextLength;
            int selLength = s->selectTextLength > 0 ? s->selectTextLength : -s->selectTextLength;
            int selEnd = selStart + selLength;
            memmove(e->text + selStart, e->text + selEnd, e->textLen - selLength + 1);
            e->textLen -= selLength;
            e->textLineLen -= selLength;
            e->text[e->textLen] = '\0'; // Add null terminator at the end of the string
            s->selectTextLength = 0;
            s->selectTextStart = -1;
        } else if (IsKeyDown(KEY_BACKSPACE)) {
            if (!s->isDeletingText) s->deletingTextStartTime = GetTime();
            s->isDeletingText = true;
            if (IsKeyPressed(KEY_BACKSPACE) || ( GetTime() - s->deletingTextStartTime > 0.5f  && s->textSelectedFramesCounter % 10 == 0) ) {
                if (e->textLen > 0 && e->text[e->textLen - 1] == '\n') {
                    e->textLines--;
                    e->textLineLen = 0;
                    e->textLen -= 2 ;
                    e->text[e->textLen] = '\0'; 
                } else {
                    e->textLen--;
                    e->textLineLen--;
                    if (e->textLen < 0) e->textLen  = 0;
                    e->text[e->textLen] = '\0'; 
                }
            }
            UpdateLogInDB(s, e->text); // Inefficient ...
        } if (IsKeyUp(KEY_BACKSPACE)) {
            s->isDeletingText = false;
            s->deletingTextStartTime = 0;
        }
   
    }
    else {
        SetMouseCursor(MOUSE_CURSOR_DEFAULT);
    }

}

// Orientation: 0 - corner at top-left, 1 - corner at top-right, 2 - corner at bottom-right, 3 - corner at bottom-left
void DrawElbow(int posX, int posY, int columnWidth, int columnHeight, int barWidth, int barHeight, int innerRadius,  Color color, int orientation, bool debug) {
   switch (orientation) {
        case 0:
            if (columnWidth >= barHeight + innerRadius) {
                DrawRectangle(posX, posY + barHeight + innerRadius,columnWidth,columnHeight, color); // Vertical bar
                DrawRectangle(posX + columnWidth, posY, barWidth, barHeight, debug ? GREEN : color); // Horizontal bar
                Vector2 center = { posX + barHeight + innerRadius, posY + barHeight + innerRadius };
                DrawCircleSector(center, innerRadius + barHeight, 180, 270, 0, debug ? BLUE : color); // Elbow curve
                DrawRectangle(posX + barHeight + innerRadius, posY, columnWidth - barHeight - innerRadius, barHeight + innerRadius, debug ? ORANGE : color); // Fill the gap between the curve and the bars
                DrawRing((Vector2){ posX + columnWidth + innerRadius, posY + barHeight + innerRadius }, innerRadius, innerRadius + barHeight, 180, 270, 0, debug ? MAGENTA : color); // Decorative ring around the elbow
            }
            if (barHeight >= columnWidth + innerRadius) {
                DrawRectangle(posX, posY + barHeight ,columnWidth,columnHeight, color); // Vertical bar
                DrawRectangle(posX + columnWidth + innerRadius, posY, barWidth, barHeight, debug ? GREEN : color); // Horizontal bar
                Vector2 center = { posX + columnWidth + innerRadius, posY + columnWidth + innerRadius };
                DrawCircleSector(center, innerRadius + columnWidth, 180, 270, 0, debug ? BLUE : color); // Elbow curve
                DrawRectangle(posX, posY + columnWidth + innerRadius, columnWidth + innerRadius, barHeight - columnWidth -  innerRadius, debug ? ORANGE : color); // Fill the gap between the curve and the bars
                DrawRing((Vector2){ posX + columnWidth + innerRadius, posY + barHeight + innerRadius }, innerRadius, innerRadius + columnWidth, 180, 270, 0, debug ? MAGENTA : color); // Decorative ring around the elbow
            }
            break;
    case 1:
        break;
    case 2: 
        break;
    case 3:
        if (columnWidth >= barHeight + innerRadius) {
            DrawRectangle(posX, posY, columnWidth, columnHeight, color); // Vertical bar
            DrawRectangle(posX + columnWidth , posY + columnHeight + innerRadius, barWidth, barHeight, debug ? GREEN : color); // Horizontal bar
            Vector2 center = { posX + barHeight + innerRadius, posY + columnHeight };
            DrawCircleSector(center, innerRadius + barHeight, 90, 180, 0, debug ? BLUE : color); // Elbow curve
            DrawRectangle(posX + barHeight + innerRadius, posY + columnHeight, columnWidth - barHeight - innerRadius, barHeight + innerRadius, debug ? ORANGE : color); // Fill the gap between the curve and the bars
            DrawRing((Vector2){ posX + columnWidth + innerRadius, posY + columnHeight }, innerRadius, innerRadius + barHeight, 90, 180, 0, debug ? MAGENTA : color); // Decorative ring around the elbow
        }
        // if (barHeight >= columnWidth + innerRadius) {
        //     DrawRectangle(posX, posY,columnWidth,columnHeight, color); // Vertical bar
        //     DrawRectangle(posX + columnWidth - innerRadius - barHeight, posY + columnHeight, barWidth, barHeight, debug ? GREEN : color); // Horizontal bar
        //     Vector2 center = { posX + columnWidth - innerRadius - barHeight, posY + columnHeight - innerRadius - barHeight };
        //     DrawCircleSector(center, innerRadius + columnWidth, 90, 180, 0, debug ? BLUE : color); // Elbow curve
        //     DrawRectangle(posX + columnWidth - innerRadius - barHeight, posY + columnHeight - innerRadius - columnWidth, columnWidth + innerRadius - barHeight, barHeight - columnWidth - innerRadius, debug ? ORANGE : color); // Fill the gap between the curve and the bars
        //     DrawRing((Vector2){ posX + columnWidth - innerRadius - barHeight, posY + columnHeight - innerRadius }, innerRadius, innerRadius + columnWidth, 90, 180, 0, debug ? MAGENTA : color); // Decorative ring around the elbow
        // }
        break;
    }
}

// Draw text using font inside rectangle limits with support for text selection
static void DrawTextBoxedSelectable(State* s, Font font, const char *text, Rectangle rec, float fontSize, float spacing, bool wordWrap, Color tint, int selectStart, int selectLength, Color selectTint, Color selectBackTint) {
    int length = TextLength(text);  // Total length in bytes of the text, scanned by codepoints in loop

    float textOffsetY = 0;          // Offset between lines (on line break '\n')
    float textOffsetX = 0.0f;       // Offset X to next character to draw

    float scaleFactor = fontSize/(float)font.baseSize;     // Character rectangle scaling factor

    // Word/character wrapping mechanism variables
    enum { MEASURE_STATE = 0, DRAW_STATE = 1 };
    int state = wordWrap? MEASURE_STATE : DRAW_STATE;

    int startLine = -1;         // Index where to begin drawing (where a line begins)
    int endLine = -1;           // Index where to stop drawing (where a line ends)
    int lastk = -1;             // Holds last value of the character position

    for (int i = 0, k = 0; i < length; i++, k++) {
        // Get next codepoint from byte string and glyph index in font
        int codepointByteCount = 0;
        int codepoint = GetCodepoint(&text[i], &codepointByteCount);
        int index = GetGlyphIndex(font, codepoint);

        // NOTE: Normally we exit the decoding sequence as soon as a bad byte is found (and return 0x3f)
        // but we need to draw all of the bad bytes using the '?' symbol moving one byte
        if (codepoint == 0x3f) codepointByteCount = 1;
        i += (codepointByteCount - 1);

        float glyphWidth = 0;
        if (codepoint != '\n') {
            glyphWidth = (font.glyphs[index].advanceX == 0) ? font.recs[index].width*scaleFactor : font.glyphs[index].advanceX*scaleFactor;

            if (i + 1 < length) glyphWidth = glyphWidth + spacing;
        }

        // NOTE: When wordWrap is ON we first measure how much of the text we can draw before going outside of the rec container
        // We store this info in startLine and endLine, then we change states, draw the text between those two variables
        // and change states again and again recursively until the end of the text (or until we get outside of the container)
        // When wordWrap is OFF we don't need the measure state so we go to the drawing state immediately
        // and begin drawing on the next line before we can get outside the container
        if (state == MEASURE_STATE) {
            // TODO: There are multiple types of spaces in UNICODE, maybe it's a good idea to add support for more
            // Ref: http://jkorpela.fi/chars/spaces.html
            if ((codepoint == ' ') || (codepoint == '\t') || (codepoint == '\n')) endLine = i;

            if ((textOffsetX + glyphWidth) > rec.width) {
                endLine = (endLine < 1)? i : endLine;
                if (i == endLine) endLine -= codepointByteCount;
                if ((startLine + codepointByteCount) == endLine) endLine = (i - codepointByteCount);

                state = !state;
            }
            else if ((i + 1) == length) {
                endLine = i;
                state = !state;
            }
            else if (codepoint == '\n') state = !state;

            if (state == DRAW_STATE) {
                textOffsetX = 0;
                i = startLine;
                glyphWidth = 0;

                // Save character position when we switch states
                int tmp = lastk;
                lastk = k - 1;
                k = tmp;
            }
        }
        else {
            if (codepoint == '\n') {
                if (!wordWrap) {
                    textOffsetY += (font.baseSize + (float)font.baseSize/2)*scaleFactor;
                    textOffsetX = 0;
                }
                // if (s->textSelectedFramesCounter / 80 % 2 == 0) DrawTextCodepoint(font, '_', (Vector2){ rec.x + textOffsetX + glyphWidth, rec.y + textOffsetY }, fontSize, RED);
            }
            else {
                if (!wordWrap && ((textOffsetX + glyphWidth) > rec.width)) {
                    textOffsetY += (font.baseSize + (float)font.baseSize/2)*scaleFactor;
                    textOffsetX = 0;
                }

                // When text overflows rectangle height limit, just stop drawing
                if ((textOffsetY + font.baseSize*scaleFactor) > rec.height) break;

                // Draw selection background
                bool isGlyphSelected = false;
                if ((selectStart >= 0) && (k >= selectStart) && (k < (selectStart + selectLength))) {
                    DrawRectangleRec((Rectangle){ rec.x + textOffsetX - 1, rec.y + textOffsetY, glyphWidth, (float)font.baseSize*scaleFactor }, selectBackTint);
                    isGlyphSelected = true;
                }

                // Draw current character glyph
                if ((codepoint != ' ') && (codepoint != '\t')) {
                    if(isGlyphSelected && s->debug) {
                        // DrawText(TextFormat("%d", k),  rec.x + textOffsetX - 1, rec.y + textOffsetY, 10, GREEN);
                        // DrawText(TextFormat("Sel start %03d, Sel Len %03d", selectStart, selectLength), rec.x, rec.y - 30, 10, RED);
                    }
                    DrawTextCodepoint(font, codepoint, (Vector2){ rec.x + textOffsetX, rec.y + textOffsetY }, fontSize, isGlyphSelected? selectTint : tint);
                }
                if (i == length - 1) {
                    if (s->textSelectedFramesCounter / 80 % 2 == 0) DrawTextCodepoint(font, '_', (Vector2){ rec.x + textOffsetX + glyphWidth, rec.y + textOffsetY }, fontSize, RED);
                }
            }

            if (wordWrap && (i == endLine)) {
                textOffsetY += (font.baseSize + (float)font.baseSize/2)*scaleFactor;
                textOffsetX = 0;
                startLine = endLine;
                endLine = -1;
                glyphWidth = 0;
                selectStart += lastk - k;
                k = lastk;

                state = !state;
                // if (i == length - 1) {
                //     if (s->textSelectedFramesCounter / 80 % 2 == 0) DrawTextCodepoint(font, '_', (Vector2){ rec.x + textOffsetX + glyphWidth, rec.y + textOffsetY }, fontSize, RED);
                // }
            }
        }

        if ((textOffsetX != 0) || (codepoint != ' ')) textOffsetX += glyphWidth;  // avoid leading spaces
    }
    // if (s->debug) s->debug = false;
} 

// Draw text using font inside rectangle limits
static void DrawTextBoxed(State* s, Font font, const char *text, Rectangle rec, float fontSize, float spacing, bool wordWrap, Color tint) {
    if (s->debug) DrawText(TextFormat("Selection start: %d, end: %d, length: %d", s->selectTextStart, s->selectTextEnd, s->selectTextLength), rec.x, rec.y - 20, 10, RED);

    int selStart = s->selectTextLength > 0 ? s->selectTextStart : s->selectTextStart + s->selectTextLength;
    int selLength = s->selectTextLength > 0 ? s->selectTextLength : -s->selectTextLength;
    DrawTextBoxedSelectable(s, font, text, rec, fontSize, spacing, wordWrap, tint, selStart, selLength, BLACK, LCARS_RED_ORANGE);
}

void UpdateDrawFrame(State *s) {
    if (IsKeyDown(KEY_LEFT_CONTROL) && IsKeyPressed(KEY_D)) {s->debug = !s->debug;}
    if (IsKeyDown(KEY_LEFT_CONTROL) && !IsKeyDown(KEY_LEFT_SHIFT) && IsKeyPressed(KEY_R)) { Init(s, false); }
    if (IsKeyDown(KEY_LEFT_CONTROL) && (IsKeyPressed(KEY_H) || IsKeyPressed(KEY_E))) {s->hide_controlls = !s->hide_controlls;}
    // if (IsKeyDown(KEY_LEFT_CONTROL)) { 
    //     if (s->notificationOnElemIdx != -2) {
    //         snprintf(s->notification, NOTIFICATION_MAX_LEN, "[Changing Perspective]");
    //         s->notificationTimer = NOTIFICATION_DURATION;
    //         s->notificationOnElemIdx = -2;
    //     } else {
    //         s->notificationTimer = NOTIFICATION_DURATION; // Reset timer while holding shift
    //     }
    //     // HideCursor();
    // }

    Update(s);
    Vector2 mPos = GetMousePosition();

    // Pre render on texture areas or any other requirements for first pass:
    for (int i = 0; i < MAX_ELEMENTS; i++) {
        Element *e = &s->elements[i];
        if (e->kind == ELEM_NOTHING) continue; // Skip uninitialized elements
        switch (e->kind) {
            case ELEM_SPHERE: {
                BeginTextureMode(e->renderTexture);
                    ClearBackground(BLACK);
                    BeginMode3D(e->camera);
                        // DrawSphere(e->position3, 2.0f, e->color);
                        // DrawModelWiresEx(e->model, 

                        DrawModelEx(e->model, 
                                    e->position3, 
                                    (Vector3){0.0f, 1.0f, 0.0f}, 
                                    e->rotation,
                                    (Vector3){2.0f, 2.0f, 2.0f}, 
                                    e->color);

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
            if (e->kind == ELEM_NOTHING) continue; // Skip uninitialized elements
            switch (e->kind) {
                case ELEM_RECTANGLE:
                    DrawRectangle(e->position.x, e->position.y, e->width, e->height, e->color);
                    break;
                case ELEM_ELBOW:
                    DrawElbow(e->position.x, e->position.y, e->width, e->height, s->barWidth, s->barHeight, s->innerRadius, e->color, e->elbowOrientation, s->debug);
                    break;
                case ELEM_BUTTON:
                    DrawRectangleRounded((Rectangle){.x=e->position.x, .y=e->position.y, .width=e->width, .height=e->height}, 0.9f, 4, e->color);
                    break;
                case ELEM_TEXT:
                    DrawText(e->text, e->position.x, e->position.y, e->textSize, e->color);
                    break;
                case ELEM_TEXT_EDITOR: {
                    DrawRectangleLines(e->position.x, e->position.y, e->width + 10, e->height, LCARS_BLUE);
                    // DrawText(e->text, e->position.x + 5, e->position.y+5, e->textSize, e->color);
                    Rectangle r = (Rectangle){e->position.x + 5, e->position.y + 5, e->width, e->height};
                    DrawTextBoxed(s, s->font, e->text, r, e->textSize, 2.0f, false, e->color);
                    break;
                }
                case ELEM_SPHERE: {
                    if (s->hide_controlls) {
                        DrawTextureRec(e->renderTexture.texture, (Rectangle){0,0, e->width, e->height}, (Vector2){ e->position.x, e->position.y }, WHITE);
                        
                        if (s->debug) {
                            // DrawRectangle(e->position.x- 5, e->position.y + 5, e->width + 10, e->height + 10, RED);
                            // Vector2 screenPos = GetWorldToScreen(e->position3, e->camera);
                            Vector2 screenPos = {e->position.x, e->position.y};

                            // Draw Text - position, rotation 
                            DrawText(TextFormat("Pos: (%.2f, %.2f, %.2f)", e->position3.x, e->position3.y, e->position3.z), screenPos.x, screenPos.y, 10, WHITE);
                            DrawText(TextFormat("Rot: (%.2f)", e->rotation), screenPos.x, screenPos.y + 20, 10, WHITE);

                            // Camera 
                            DrawText(TextFormat("Camera Pos: (%.2f, %.2f, %.2f)", e->camera.position.x, e->camera.position.y, e->camera.position.z), screenPos.x, screenPos.y + 40, 10, WHITE);
                            DrawText(TextFormat("Camera Target: (%.2f, %.2f, %.2f)", e->camera.target.x, e->camera.target.y, e->camera.target.z), screenPos.x, screenPos.y + 60, 10, WHITE);
                            DrawText(TextFormat("Camera Up: (%.2f, %.2f, %.2f)", e->camera.up.x, e->camera.up.y, e->camera.up.z), screenPos.x, screenPos.y + 80, 10, WHITE);
                            DrawText(TextFormat("Camera FOV: %.2f", e->camera.fovy), screenPos.x, screenPos.y + 100, 10, WHITE);
                            DrawText(TextFormat("Camera Projection: %s", e->camera.projection == CAMERA_PERSPECTIVE ? "Perspective" : "Orthographic"), screenPos.x, screenPos.y + 120, 10, WHITE);
                        }
                    }
                    break;
                }
                case ELEM_NOTHING:
                case ELEM_TOTAL_KINDS:
                    break;
            }

            if (e->text && e->kind != ELEM_TEXT && e->kind != ELEM_TEXT_EDITOR) {
                int textWidth = MeasureText(e->text, e->textSize);
                if (e->kind == ELEM_ELBOW) {
                    DrawText(e->text, e->position.x + 3 * (e->width - textWidth) / 4, e->position.y + s->barHeight + s->innerRadius + (e->height - e->textSize) / 2, e->textSize, BLACK);
                } else {
                    DrawText(e->text, e->position.x + 3 * (e->width - textWidth) / 4, e->position.y + (e->height - e->textSize) / 2 + 10, e->textSize, BLACK);
                }
            }

        }

        if (s->notification && s->notificationTimer > 0.0f) {
            s->notificationTimer -= GetFrameTime();
            DrawText(s->notification,  s->posX + s->columnWidth + s->innerRadius, s->posY - 2 * s->columnHeight - s->barHeight , 20, YELLOW);
        } else {
            s->notificationOnElemIdx = -1;
        }

        if (!s->hide_controlls) {
            int i = 0;
            GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i * 30, .width=120, .height=20}, "Col W ", sprintf_static(s, i, "%.0f", s->columnWidth) ,         &s->columnWidth , 0, 300); i++;
            GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i * 30, .width=120, .height=20}, "Bar H ", sprintf_static(s, i, "%.0f", s->barHeight)   , &s->barHeight   , 0, 300); i++;
            GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i * 30, .width=120, .height=20}, "Radius", sprintf_static(s, i, "%.0f", s->innerRadius) , &s->innerRadius , 0, 50 ); i++;
            GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i * 30, .width=120, .height=20}, "Col H ", sprintf_static(s, i, "%.0f", s->columnHeight), &s->columnHeight, 0, 600); i++;
            GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i * 30, .width=120, .height=20}, "Bar W ", sprintf_static(s, i, "%.0f", s->barWidth)    , &s->barWidth    , 0, 600); i++;
            GuiToggle(   (Rectangle){.x=s->controllsX,       .y=s->controllsY + i * 30, .width=120, .height=20}, "Debug (d)", &s->debug); i++;
            GuiToggle(   (Rectangle){.x=s->controllsX + 130, .y=s->controllsY + (i - 1) * 30, .width=120, .height=20}, "Hide controlls (h)",&s->hide_controlls);

            char* code = sprintf_static(s, 
                i, "DrawElbow(%.0f, %.0f, %.0f, %.0f, %.0f, %.0f, %.0f, lcarsColor, %s);", 
                s->posX, s->posY, s->columnWidth, s->columnHeight, s->barWidth, s->barHeight, s->innerRadius, s->debug ? "true" : "false"
            );

            if (GuiTextBox((Rectangle){.x=s->controllsX, .y=s->controllsY + i * 30, .width=500, .height=50},
                        code,
                        22,
                        0)) {s->textBoxEditMode = !s->textBoxEditMode;} 
            i+=2;
        }

        if (s->debug) {
            DrawFPS(10, 10);
            DrawText(TextFormat("x:%.2f, y:%.2f", mPos.x, mPos.y), mPos.x + 20, mPos.y, 10, GREEN);
        }
        // DrawText(TextFormat("Rotation: %.2f", s->elements[21].rotation), 10, 30, 10, WHITE);

    EndDrawing();
}

#endif // LCARS_IMPLEMENTATION

