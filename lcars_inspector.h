#ifndef LCARS_INSPECTOR_H
#define LCARS_INSPECTOR_H

#include "lcars_types.h"

// -----------------------------------------------------------------------------
// State editor / inspector — the edit-mode property panel
// -----------------------------------------------------------------------------
// A Unity/Unreal-style inspector: in edit mode, clicking an element selects it
// (State.selectedElementIdx) and this panel shows its authored Element fields
// and lets them be edited live with raygui widgets.
//
// Scope: this edits the *live* State. Only x/y/w/h persist back to the .html
// (through the existing MarkLayoutDirty()/lcars_doc_writer.h machinery, exactly
// as a drag does); every other field is a session-only edit until the document
// writer learns to patch non-geometry attributes (the "Real-time hypermedia
// document editor — the rest of it" item in TODO.md). The runtime-only Element
// fields (gap buffer, focus/selection, KeyRepeat timers, the DB caches) are not
// shown: they aren't authored properties and editing them by hand would only
// corrupt the editor/list state, so the panel deliberately stops at the fields
// a document can express.

// Which inspector widget currently owns raygui's single edit-mode focus. Stored
// in State.inspectorActiveField; -1 (INSP_FIELD_NONE) means none. raygui is
// immediate-mode with one active edit control at a time, so a single integer is
// the whole "which box is being typed into" state.
enum {
  INSP_FIELD_NONE = -1,
  INSP_KIND = 0,
  INSP_ID,
  INSP_X,
  INSP_Y,
  INSP_W,
  INSP_H,
  INSP_COLOR,
  INSP_TEXTSIZE,
  INSP_ORIENT,
  INSP_ACTION,
  INSP_HREF,
  INSP_TEXT,
};

// Screen rectangle the inspector panel occupies, or a zero rect when it isn't
// shown. Callers use it to keep an edit-mode click that landed on the panel
// from also selecting/activating an element behind it. Safe to call every
// frame; depends only on the current screen size and whether a valid element
// is selected.
static Rectangle InspectorPanelBounds(State *s);

// Draws and services the inspector panel (both render and input, raygui-style)
// for State.selectedElementIdx. No-op unless edit mode is on and a valid
// element is selected. Call inside the draw pass, after the main elements.
static void DrawInspector(State *s);

#ifdef LCARS_IMPLEMENTATION

#define INSPECTOR_PANEL_WIDTH 340.0f
#define INSPECTOR_MARGIN 12.0f
#define INSPECTOR_LABEL_W 96.0f
#define INSPECTOR_ROW_H 22.0f
#define INSPECTOR_ROW_GAP 6.0f

// Indexed by ElemKind / ButtonAction respectively — plain string literals, so
// unlike the color table below these are fine at file scope under -pedantic.
static const char *INSPECTOR_KIND_NAMES[] = {
    "nothing", "rectangle",   "elbow",      "button",
    "text",    "text_editor", "entry_list", "sphere",
};
static const char *INSPECTOR_ACTION_NAMES[] = {
    "none",     "debug",           "edit", "reset", "voice_input",
    "print_db", "load_hypermedia",
};

// Whether this kind needs a heavy side struct that only its make_* constructor
// builds (gap buffer, EntryListState, SphereState). The inspector allows a kind
// change only when the target either doesn't need one or already has it — the
// alternative is running a constructor mid-frame against an element that may
// not carry the inputs it wants (a sphere's texture path, an editor's DB
// entry), which is the kind of thing that corrupts lcars.db rather than merely
// looking wrong.
static bool InspectorKindReady(const Element *e, ElemKind kind) {
  assert(e != NULL);
  switch (kind) {
  case ELEM_TEXT_EDITOR:
    return e->gap.buffer != NULL;
  case ELEM_ENTRY_LIST:
    return e->entryList != NULL;
  case ELEM_SPHERE:
    return e->sphere != NULL;
  default:
    // rectangle/elbow/button/text share Element's flat fields and need no
    // side allocation, so they are always a safe target.
    return true;
  }
}

static bool InspectorColorEq(Color a, Color b) {
  return a.r == b.r && a.g == b.g && a.b == b.b && a.a == b.a;
}

static Rectangle InspectorPanelBounds(State *s) {
  assert(s != NULL);
  bool shown = s->is_editing && s->selectedElementIdx >= 0 &&
               s->selectedElementIdx < s->numElements;
  if (!shown) {
    return (Rectangle){0, 0, 0, 0};
  }
  float w = INSPECTOR_PANEL_WIDTH;
  return (Rectangle){(float)GetScreenWidth() - w, 0.0f, w,
                     (float)GetScreenHeight()};
}

// Toggles which widget holds raygui's edit focus. Called when a widget reports
// it was pressed: pressing the active one closes it, pressing another moves
// focus to it (and so implicitly closes whatever was active before).
static void InspectorToggleField(State *s, int field) {
  assert(s != NULL);
  s->inspectorActiveField =
      (s->inspectorActiveField == field) ? INSP_FIELD_NONE : field;
}

// One "label + widget" row. Draws the label and returns the rectangle the
// widget should fill, advancing *y past the row. Enum rows split the returned
// rect themselves (spinner on the left, a name label on the right).
static Rectangle InspectorRow(Rectangle panel, float *y, const char *label) {
  assert(y != NULL);
  GuiLabel((Rectangle){panel.x + INSPECTOR_MARGIN, *y, INSPECTOR_LABEL_W,
                       INSPECTOR_ROW_H},
           label);
  float wx = panel.x + INSPECTOR_MARGIN + INSPECTOR_LABEL_W + 4.0f;
  float ww = panel.width - 2.0f * INSPECTOR_MARGIN - INSPECTOR_LABEL_W - 4.0f;
  Rectangle widget = {wx, *y, ww, INSPECTOR_ROW_H};
  *y += INSPECTOR_ROW_H + INSPECTOR_ROW_GAP;
  return widget;
}

// A geometry value box bound to a float field. Writes back (and dirties the
// layout, so it persists to the document like a drag does) only when the shown
// integer actually changes, so an untouched fractional value survives. Returns
// true if the value changed this frame.
static bool InspectorFloatBox(State *s, Rectangle r, int field, float *value) {
  assert(s != NULL && value != NULL);
  int v = (int)(*value);
  if (GuiValueBox(r, NULL, &v, -100000, 100000,
                  s->inspectorActiveField == field)) {
    InspectorToggleField(s, field);
  }
  if (v != (int)(*value)) {
    *value = (float)v;
    return true;
  }
  return false;
}

// A text field bound to an Element String. The edit buffer lives in State
// (survives across frames); while this field isn't the active one the buffer
// tracks the current value, and while it is, the typed buffer is committed back
// into doc_arena on any change. These fields are short (id/href/label), so the
// per-keystroke reallocation is cheap and, like everything in doc_arena, is
// reclaimed at the next document load.
static void InspectorTextField(State *s, Rectangle r, int field, char *buf,
                               int bufSize, String *value) {
  assert(s != NULL && buf != NULL && value != NULL && bufSize > 0);
  bool active = (s->inspectorActiveField == field);
  if (!active) {
    snprintf(buf, (size_t)bufSize, "%s", value->data ? value->data : "");
  }
  if (GuiTextBox(r, buf, bufSize, active)) {
    InspectorToggleField(s, field);
  }
  if (s->inspectorActiveField == field) {
    if (value->data == NULL || strcmp(value->data, buf) != 0) {
      StringAssignC(&s->doc_arena, value, buf);
    }
  }
}

static void DrawInspector(State *s) {
  assert(s != NULL);
  if (!s->is_editing || s->selectedElementIdx < 0 ||
      s->selectedElementIdx >= s->numElements) {
    return;
  }
  Element *e = &s->elements[s->selectedElementIdx];
  if (e->kind == ELEM_NOTHING) {
    s->selectedElementIdx = -1;
    return;
  }

  Rectangle panel = InspectorPanelBounds(s);
  // Opaque backing so the elements the panel overlaps don't bleed through the
  // widgets; raygui's own panel border on top of it.
  DrawRectangleRec(panel, (Color){20, 20, 28, 235});
  GuiPanel(panel, NULL);

  float y = panel.y + INSPECTOR_MARGIN;

  // Header: title + selected index, and a close button that clears selection.
  GuiLabel((Rectangle){panel.x + INSPECTOR_MARGIN, y, panel.width - 60.0f,
                       INSPECTOR_ROW_H},
           TextFormat("INSPECTOR  [%d]", s->selectedElementIdx));
  if (GuiButton((Rectangle){panel.x + panel.width - INSPECTOR_MARGIN - 24.0f, y,
                            24.0f, INSPECTOR_ROW_H},
                "X")) {
    s->selectedElementIdx = -1;
    s->inspectorActiveField = INSP_FIELD_NONE;
    return;
  }
  y += INSPECTOR_ROW_H + INSPECTOR_ROW_GAP;
  GuiLine((Rectangle){panel.x + INSPECTOR_MARGIN, y,
                      panel.width - 2.0f * INSPECTOR_MARGIN, 8.0f},
          NULL);
  y += 12.0f;

  // --- kind (with a live constructor-safety guard) ---
  {
    Rectangle wr = InspectorRow(panel, &y, "kind");
    Rectangle spin = {wr.x, wr.y, 70.0f, wr.height};
    Rectangle name = {wr.x + 76.0f, wr.y, wr.width - 76.0f, wr.height};
    int k = (int)e->kind;
    if (GuiSpinner(spin, NULL, &k, ELEM_RECTANGLE, ELEM_SPHERE,
                   s->inspectorActiveField == INSP_KIND)) {
      InspectorToggleField(s, INSP_KIND);
    }
    if (k != (int)e->kind) {
      ElemKind target = (ElemKind)k;
      if (InspectorKindReady(e, target)) {
        e->kind = target;
      } else {
        // Can't build the side struct here — leave the kind alone and say so.
        UpdateNotification(
            s, StringStatic("CANNOT SWITCH KIND: NEEDS CONSTRUCTOR"));
      }
    }
    const char *kn = (e->kind >= 0 && e->kind <= ELEM_SPHERE)
                         ? INSPECTOR_KIND_NAMES[e->kind]
                         : "?";
    GuiLabel(name, kn);
  }

  // --- id ---
  {
    Rectangle wr = InspectorRow(panel, &y, "id");
    InspectorTextField(s, wr, INSP_ID, s->inspId, (int)sizeof(s->inspId),
                       &e->id);
  }

  // --- geometry (persists to the document) ---
  if (InspectorFloatBox(s, InspectorRow(panel, &y, "x"), INSP_X,
                        &e->position.x)) {
    MarkLayoutDirty(s);
  }
  if (InspectorFloatBox(s, InspectorRow(panel, &y, "y"), INSP_Y,
                        &e->position.y)) {
    MarkLayoutDirty(s);
  }
  {
    float oldW = e->width, oldH = e->height;
    bool wChanged =
        InspectorFloatBox(s, InspectorRow(panel, &y, "w"), INSP_W, &e->width);
    bool hChanged =
        InspectorFloatBox(s, InspectorRow(panel, &y, "h"), INSP_H, &e->height);
    if (wChanged || hChanged) {
      if (e->width < 1.0f)
        e->width = 1.0f;
      if (e->height < 1.0f)
        e->height = 1.0f;
      // A sphere renders into a texture sized to its box — same recreation the
      // resize handle does when the dimensions change.
      if (e->kind == ELEM_SPHERE && e->sphere != NULL &&
          ((int)e->width != (int)oldW || (int)e->height != (int)oldH)) {
        UnloadRenderTexture(e->sphere->renderTexture);
        e->sphere->renderTexture =
            LoadRenderTexture((int)e->width, (int)e->height);
      }
      MarkLayoutDirty(s);
    }
  }

  // --- color (LCARS palette; a custom hex color shows as index 0 until
  // changed). Local array: raylib's Color compound literals can't initialise a
  // file-scope static under -pedantic (same reason as lcars_hypermedia.h). ---
  {
    const struct {
      const char *name;
      Color color;
    } palette[] = {
        {"purple", LCARS_PURPLE}, {"red", LCARS_RED_ORANGE},
        {"orange", LCARS_ORANGE}, {"yellow", LCARS_YELLOW},
        {"blue", LCARS_BLUE},     {"green", LCARS_GREEN},
        {"white", WHITE},         {"black", BLACK},
    };
    int paletteCount = (int)(sizeof(palette) / sizeof(palette[0]));
    // Match against originalColor, the authored base: e->color is the transient
    // value hover-brightening writes, so matching it would read as "custom"
    // whenever the selected element happens to be under the cursor.
    int curIdx = -1;
    for (int i = 0; i < paletteCount; i++) {
      if (InspectorColorEq(e->originalColor, palette[i].color)) {
        curIdx = i;
        break;
      }
    }
    Rectangle wr = InspectorRow(panel, &y, "color");
    Rectangle swatch = {wr.x, wr.y + 2.0f, 18.0f, wr.height - 4.0f};
    Rectangle spin = {wr.x + 24.0f, wr.y, 60.0f, wr.height};
    Rectangle name = {wr.x + 90.0f, wr.y, wr.width - 90.0f, wr.height};
    DrawRectangleRec(swatch, e->originalColor);
    DrawRectangleLinesEx(swatch, 1.0f, (Color){255, 255, 255, 120});
    int shown = curIdx < 0 ? 0 : curIdx;
    // Compare against the value the spinner started this frame with, not
    // against curIdx: a custom (hex) color has curIdx == -1 while shown starts
    // at 0, so a curIdx test would "change" the color to palette[0] with no
    // user action at all.
    int before = shown;
    if (GuiSpinner(spin, NULL, &shown, 0, paletteCount - 1,
                   s->inspectorActiveField == INSP_COLOR)) {
      InspectorToggleField(s, INSP_COLOR);
    }
    if (shown != before && shown >= 0 && shown < paletteCount) {
      e->color = palette[shown].color;
      // originalColor is what hover-out restores the element to, so a color
      // edit has to move both or the next mouse-out reverts it.
      e->originalColor = palette[shown].color;
    }
    GuiLabel(name, curIdx < 0 ? "custom" : palette[shown].name);
  }

  // --- textSize ---
  {
    Rectangle wr = InspectorRow(panel, &y, "textSize");
    int ts = e->textSize;
    if (GuiValueBox(wr, NULL, &ts, 0, 200,
                    s->inspectorActiveField == INSP_TEXTSIZE)) {
      InspectorToggleField(s, INSP_TEXTSIZE);
    }
    if (ts != e->textSize) {
      e->textSize = ts;
    }
  }

  // --- elbow orientation (only meaningful for an elbow) ---
  if (e->kind == ELEM_ELBOW) {
    Rectangle wr = InspectorRow(panel, &y, "orient");
    int o = e->elbowOrientation;
    if (GuiSpinner(wr, NULL, &o, 0, 3,
                   s->inspectorActiveField == INSP_ORIENT)) {
      InspectorToggleField(s, INSP_ORIENT);
    }
    if (o != e->elbowOrientation) {
      e->elbowOrientation = o;
    }
  }

  // --- on_click action (with a name label) ---
  {
    Rectangle wr = InspectorRow(panel, &y, "action");
    Rectangle spin = {wr.x, wr.y, 50.0f, wr.height};
    Rectangle name = {wr.x + 56.0f, wr.y, wr.width - 56.0f, wr.height};
    int a = (int)e->on_click;
    if (GuiSpinner(spin, NULL, &a, ACTION_NONE, ACTION_LOAD_HYPERMEDIA,
                   s->inspectorActiveField == INSP_ACTION)) {
      InspectorToggleField(s, INSP_ACTION);
    }
    if (a != (int)e->on_click) {
      e->on_click = (ButtonAction)a;
    }
    const char *an = (e->on_click >= 0 && e->on_click <= ACTION_LOAD_HYPERMEDIA)
                         ? INSPECTOR_ACTION_NAMES[e->on_click]
                         : "?";
    GuiLabel(name, an);
  }

  // --- href ---
  {
    Rectangle wr = InspectorRow(panel, &y, "href");
    InspectorTextField(s, wr, INSP_HREF, s->inspHref, (int)sizeof(s->inspHref),
                       &e->href);
  }

  // --- text label. Only for the label-bearing kinds: an editor/list owns its
  // own (possibly huge) text through the gap buffer / DB, and duplicating that
  // into a fixed inspector buffer would both truncate it and fight the editor.
  // ---
  if (e->kind == ELEM_RECTANGLE || e->kind == ELEM_ELBOW ||
      e->kind == ELEM_BUTTON || e->kind == ELEM_TEXT) {
    Rectangle wr = InspectorRow(panel, &y, "text");
    bool active = (s->inspectorActiveField == INSP_TEXT);
    if (!active) {
      snprintf(s->inspText, sizeof(s->inspText), "%s",
               e->text.data ? e->text.data : "");
    }
    if (GuiTextBox(wr, s->inspText, (int)sizeof(s->inspText), active)) {
      InspectorToggleField(s, INSP_TEXT);
    }
    if (s->inspectorActiveField == INSP_TEXT) {
      if (e->text.data == NULL || strcmp(e->text.data, s->inspText) != 0) {
        StringAssignC(&s->doc_arena, &e->text, s->inspText);
        e->textLen = e->text.len;
      }
    }
  }

  // --- toggles ---
  {
    Rectangle wr = InspectorRow(panel, &y, "autoSize");
    GuiCheckBox((Rectangle){wr.x, wr.y + 2.0f, 18.0f, INSPECTOR_ROW_H - 4.0f},
                NULL, &e->autoSize);
  }
  {
    Rectangle wr = InspectorRow(panel, &y, "bindsToLog");
    GuiCheckBox((Rectangle){wr.x, wr.y + 2.0f, 18.0f, INSPECTOR_ROW_H - 4.0f},
                NULL, &e->bindsToLog);
  }
}

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_INSPECTOR_H
