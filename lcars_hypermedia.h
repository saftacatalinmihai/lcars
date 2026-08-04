#ifndef LCARS_HYPERMEDIA_H
#define LCARS_HYPERMEDIA_H

#include "lcars_net.h"
#include "lcars_types.h"
#include "raylib.h"

#include <ctype.h>

static bool GetAttributeValue(const char *tag, const char *attr, char *dest,
                              int max_len);
static ElemKind TagNameToElemKind(const char *tagName);
static Color ParseColor(String colorStr);
static ButtonAction ParseAction(String actionStr);
static HyperControl *ParseHyperControl(Arena *doc_arena, const char *tag);
static String LoadFromHTTP(String source, State *s);
static String LoadFromFile(String source, State *s);
static String LoadDocumentContent(String source, State *s);
static bool ParseElementTag(State *s, const char *tag, const char *tag_name,
                           const char *p, const char *tag_end,
                           Element *outElement);
void LoadHypermediaDocument(State *s, String source);
void LoadHypermediaDocumentFromString(State *s, String content,
                                      const char *source);

#ifdef LCARS_IMPLEMENTATION

// Finds attr="value" (or attr='value') in tag and copies value into dest
// (truncated to max_len - 1 bytes, always NUL-terminated). Returns whether
// it was found. A bare strstr(tag, "x=") would also match inside "max=" or
// a later attribute's value (e.g. an href containing "?x=1") - require the
// match to start right after whitespace (or the very start of tag) so it
// can only be a real attribute name. Unquoted values (attr=value, no
// quotes) are treated the same as a missing attribute: dest is left
// untouched and this returns false, since nothing in this document format
// writes unquoted values.
static bool GetAttributeValue(const char *tag, const char *attr, char *dest,
                              int max_len) {
  assert(tag != NULL);
  assert(attr != NULL);
  assert(dest != NULL);
  // dest[len] = '\0' runs with len bounded by max_len - 1, so a max_len of
  // 0 writes to dest[-1].
  assert(max_len > 0);

  char pattern[128];
  // Every attribute name in this format is a short literal; a truncated
  // pattern would silently match the wrong attribute.
  assert(strlen(attr) + 2 <= sizeof(pattern));
  snprintf(pattern, sizeof(pattern), "%s=", attr);
  size_t patternLen = strlen(pattern);

  const char *p = tag;
  while ((p = strstr(p, pattern)) != NULL) {
    if (p == tag || isspace((unsigned char)p[-1])) {
      break;
    }
    p += patternLen;
  }
  if (!p)
    return false;

  p += patternLen;
  char quote = *p;
  if (quote != '"' && quote != '\'')
    return false;

  p++;
  int len = 0;
  while (*p && *p != quote && len < max_len - 1) {
    dest[len++] = *p++;
  }
  dest[len] = '\0';

  assert(len >= 0 && len < max_len); // the terminator above must fit
  return true;
}

static const struct {
  const char *tagName;
  ElemKind kind;
} TAG_KIND_TABLE[] = {
    {"lcars-button", ELEM_BUTTON},
    {"lcars-rect", ELEM_RECTANGLE},
    {"lcars-rectangle", ELEM_RECTANGLE},
    {"lcars-text", ELEM_TEXT},
    {"lcars-elbow", ELEM_ELBOW},
    {"lcars-text-editor", ELEM_TEXT_EDITOR},
    {"lcars-entry-list", ELEM_ENTRY_LIST},
    {"lcars-sphere", ELEM_SPHERE},
};

static ElemKind TagNameToElemKind(const char *tagName) {
  assert(tagName != NULL);
  for (size_t i = 0; i < sizeof(TAG_KIND_TABLE) / sizeof(TAG_KIND_TABLE[0]);
      i++) {
    if (strcmp(tagName, TAG_KIND_TABLE[i].tagName) == 0) {
      // Every table entry must name a real, constructible kind - the
      // caller switches on the result to pick a make_* constructor.
      assert(TAG_KIND_TABLE[i].kind > ELEM_NOTHING &&
             TAG_KIND_TABLE[i].kind < ELEM_TOTAL_KINDS);
      return TAG_KIND_TABLE[i].kind;
    }
  }
  return ELEM_NOTHING;
}

static Color ParseColor(String colorStr) {
  assert(StringValid(colorStr));
  if (colorStr.data == NULL)
    return LCARS_ORANGE;
  // Local (not file-scope static): raylib's color constants expand to
  // compound literals, which -pedantic rejects as file-scope static
  // initializers even though they're all-constant. A local const array is
  // rebuilt per call, but this only runs while parsing a hypermedia
  // document, not per-frame, so that's negligible.
  const struct {
    const char *name;
    Color color;
  } colorNameTable[] = {
      {"purple", LCARS_PURPLE}, {"red", LCARS_RED_ORANGE},
      {"orange", LCARS_ORANGE}, {"yellow", LCARS_YELLOW},
      {"blue", LCARS_BLUE},     {"white", WHITE},
      {"black", BLACK},
  };
  for (size_t i = 0; i < sizeof(colorNameTable) / sizeof(colorNameTable[0]);
      i++) {
    if (strcmp(colorStr.data, colorNameTable[i].name) == 0) {
      return colorNameTable[i].color;
    }
  }
  if (colorStr.len == 7 && colorStr.data[0] == '#') {
    unsigned int r, g, b;
    if (sscanf(colorStr.data + 1, "%02x%02x%02x", &r, &g, &b) == 3) {
      return (Color){(unsigned char)r, (unsigned char)g, (unsigned char)b, 255};
    }
  }
  return LCARS_ORANGE;
}

static const struct {
  const char *name;
  ButtonAction action;
} ACTION_NAME_TABLE[] = {
    {"debug", ACTION_DEBUG},
    {"edit", ACTION_EDIT},
    {"reset", ACTION_RESET},
    {"voice_input", ACTION_VOICE_INPUT},
    {"print_db", ACTION_PRINT_DB},
    {"load_hypermedia", ACTION_LOAD_HYPERMEDIA},
};

static ButtonAction ParseAction(String actionStr) {
  assert(StringValid(actionStr));
  if (actionStr.data == NULL)
    return ACTION_NONE;
  for (size_t i = 0;
      i < sizeof(ACTION_NAME_TABLE) / sizeof(ACTION_NAME_TABLE[0]); i++) {
    if (strcmp(actionStr.data, ACTION_NAME_TABLE[i].name) == 0) {
      return ACTION_NAME_TABLE[i].action;
    }
  }
  return ACTION_NONE;
}

// Which attribute carries the URL is also what picks the method - there is
// no separate lc-method attribute, exactly like HTMX's hx-get/hx-post.
static const struct {
  const char *attr;
  HyperMethod method;
} HYPER_METHOD_TABLE[] = {
    {"lc-get", HYPER_METHOD_GET},
    {"lc-post", HYPER_METHOD_POST},
    {"lc-put", HYPER_METHOD_PUT},
    {"lc-delete", HYPER_METHOD_DELETE},
};

// Reads the lc-* attributes off one tag. Returns NULL - and allocates
// nothing - for the overwhelmingly common case of an element that declares
// no request, which is why Element.control is a pointer: see HyperControl in
// lcars_types.h for the attribute reference.
static HyperControl *ParseHyperControl(Arena *doc_arena, const char *tag) {
  assert(doc_arena != NULL);
  assert(tag != NULL);

  // Wider than ParseElementTag's own scratch buffer: lc-vals holds a whole
  // field list, not a single number or color name.
  char val[512];

  HyperMethod method = HYPER_METHOD_NONE;
  String url = StringStatic("");
  for (size_t i = 0;
      i < sizeof(HYPER_METHOD_TABLE) / sizeof(HYPER_METHOD_TABLE[0]); i++) {
    if (!GetAttributeValue(tag, HYPER_METHOD_TABLE[i].attr, val, sizeof(val))) {
      continue;
    }
    if (method != HYPER_METHOD_NONE) {
      // Two verbs on one element has no meaning ("which one fires?"), and
      // guessing would be worse than picking the first deterministically.
      TraceLog(LOG_WARNING,
               "Element declares several lc-* methods; ignoring %s",
               HYPER_METHOD_TABLE[i].attr);
      continue;
    }
    method = HYPER_METHOD_TABLE[i].method;
    url = StringInit(doc_arena, val);
  }
  if (method == HYPER_METHOD_NONE) {
    return NULL;
  }

  HyperControl *ctl = arena_alloc(doc_arena, sizeof(HyperControl));
  ctl->method = method;
  ctl->url = url;
  ctl->target = StringStatic("");
  ctl->vals = StringStatic("");
  ctl->include = StringStatic("");
  ctl->swap = HYPER_SWAP_DEFAULT;
  ctl->trigger = HYPER_TRIGGER_CLICK;

  if (GetAttributeValue(tag, "lc-target", val, sizeof(val))) {
    // '#id' is what an HTMX user writes; ids in this format carry no sigil.
    const char *id = (val[0] == '#') ? val + 1 : val;
    ctl->target = StringInit(doc_arena, id);
  }
  if (GetAttributeValue(tag, "lc-swap", val, sizeof(val))) {
    ctl->swap = ParseHyperSwap(StringStatic(val));
  }
  if (GetAttributeValue(tag, "lc-trigger", val, sizeof(val))) {
    ctl->trigger = ParseHyperTrigger(StringStatic(val));
  }
  if (GetAttributeValue(tag, "lc-vals", val, sizeof(val))) {
    ctl->vals = StringInit(doc_arena, val);
  }
  if (GetAttributeValue(tag, "lc-include", val, sizeof(val))) {
    ctl->include = StringInit(doc_arena, val);
  }

  // A control that reached this point is dispatchable: a real method, and
  // every String either an arena copy or the empty literal.
  assert(ctl->method > HYPER_METHOD_NONE && ctl->method < HYPER_METHOD_TOTAL);
  assert(ctl->swap >= HYPER_SWAP_DEFAULT && ctl->swap < HYPER_SWAP_TOTAL);
  assert(ctl->trigger >= HYPER_TRIGGER_CLICK &&
         ctl->trigger < HYPER_TRIGGER_TOTAL);
  assert(StringValid(ctl->url) && StringValid(ctl->target) &&
         StringValid(ctl->vals) && StringValid(ctl->include));
  return ctl;
}

static String LoadFromHTTP(String source, State *s) {
  assert(s != NULL);
  assert(StringValid(source));
  assert(source.data != NULL); // handed to curl as CURLOPT_URL

  String body;
  long status = 0;
  bool ok = NetHttpRequest(&s->scratch_arena, "GET", source.data,
                           StringStatic(""), NULL, &body, &status);
  // NetHttpRequest only reports transport failures, so the status check is
  // what keeps the old CURLOPT_FAILONERROR behavior: an error page is not a
  // document, and parsing one would silently replace the UI with nothing.
  if (!ok || status >= 400) {
    if (ok) {
      printf("Document fetch failed: HTTP %ld for %s\n", status, source.data);
    }
    UpdateNotification(s, StringStatic("DOWNLOAD FAILED"));
    return StringInit(&s->scratch_arena, NULL);
  }

  assert(StringValid(body));
  return body;
}

static String LoadFromFile(String source, State *s) {
  assert(s != NULL);
  assert(StringValid(source));
  assert(source.data != NULL); // strncmp'd and fopen'd below

  const char *local_path = source.data;
  if (strncmp(source.data, "file://", 7) == 0) {
    local_path = source.data + 7;
  }

  FILE *f = fopen(local_path, "r");
  if (!f) {
    printf("Failed to open file: %s\n", local_path);
    UpdateNotification(s, StringStatic("FILE NOT FOUND"));
    return StringInit(&s->scratch_arena, NULL);
  }

  fseek(f, 0, SEEK_END);
  long size = ftell(f);
  fseek(f, 0, SEEK_SET);
  // A failed ftell returns -1, which would become a 0-byte allocation that
  // the terminator below immediately writes past.
  if (size < 0) {
    printf("Failed to size file: %s\n", local_path);
    UpdateNotification(s, StringStatic("FILE READ FAILED"));
    fclose(f);
    return StringInit(&s->scratch_arena, NULL);
  }

  char *buf = arena_alloc(&s->scratch_arena, size + 1);
  size_t read_bytes = fread(buf, 1, size, f);
  // fread can come up short (text-mode newline translation, a truncated
  // read) but must never exceed what we sized the buffer for.
  assert(read_bytes <= (size_t)size);
  buf[read_bytes] = '\0';
  fclose(f);

  String ret;
  ret.data = buf;
  ret.len = (int)read_bytes;
  ret.is_static = false;

  assert(StringValid(ret));
  return ret;
}

static String LoadDocumentContent(String source, State *s) {
  assert(s != NULL);
  assert(StringValid(source));
  if (source.data == NULL) {
    return StringInit(&s->scratch_arena, NULL);
  }
  if (IsHttpURL(source.data)) {
    return LoadFromHTTP(source, s);
  }
  return LoadFromFile(source, s);
}

// Parses one hypermedia tag ("<lcars-button ...>", already extracted into
// `tag`) plus its inner text (if not self-closing) into *outElement.
// `tag_name` is the tag's already-extracted element name; `p`/`tag_end`
// bound where the tag starts/ends within the document, used to find the
// inner text and closing tag. Returns false (leaving *outElement
// untouched) if tag_name doesn't name a known element kind.
static bool ParseElementTag(State *s, const char *tag, const char *tag_name,
                           const char *p, const char *tag_end,
                           Element *outElement) {
  assert(s != NULL);
  assert(tag != NULL);
  assert(tag_name != NULL);
  assert(p != NULL && tag_end != NULL);
  assert(tag_end >= p); // both point into the same document buffer
  assert(outElement != NULL);

  ElemKind kind = TagNameToElemKind(tag_name);
  if (kind == ELEM_NOTHING) {
    return false;
  }

  char val[256];
  int x = 0, y = 0;
  float w_val = 100.0f;
  float h_val = 50.0f;
  Color color = LCARS_ORANGE;
  ButtonAction action = ACTION_NONE;
  int orientation = 0;
  int textSize = 20;

  if (GetAttributeValue(tag, "x", val, sizeof(val)))
    x = atoi(val);
  if (GetAttributeValue(tag, "y", val, sizeof(val)))
    y = atoi(val);
  if (GetAttributeValue(tag, "w", val, sizeof(val)))
    w_val = atof(val);
  if (GetAttributeValue(tag, "h", val, sizeof(val)))
    h_val = atof(val);
  if (GetAttributeValue(tag, "color", val, sizeof(val)))
    color = ParseColor(StringStatic(val));
  if (GetAttributeValue(tag, "action", val, sizeof(val)))
    action = ParseAction(StringStatic(val));
  if (GetAttributeValue(tag, "orientation", val, sizeof(val))) {
    orientation = atoi(val);
    // Only 0 (top-left corner) and 3 (bottom-left corner) are actually
    // drawn/hit-tested (see DrawElbow()/IsHoveringElement() in
    // lcars_ui.h) - the other two corners were never implemented. Reject
    // anything else here rather than let a bad value reach those
    // switches.
    if (orientation != 0 && orientation != 3) {
      TraceLog(LOG_WARNING,
               "Unsupported elbow orientation %d, defaulting to 0",
               orientation);
      orientation = 0;
    }
  }
  if (GetAttributeValue(tag, "size", val, sizeof(val))) {
    textSize = atoi(val);
    if (textSize < 20)
      textSize = 20;
  }
  String id = StringStatic(NULL);
  if (GetAttributeValue(tag, "id", val, sizeof(val))) {
    id = StringInit(&s->doc_arena, val);
  }
  String href = StringStatic(NULL);
  if (GetAttributeValue(tag, "href", val, sizeof(val))) {
    href = StringInit(&s->doc_arena, val);
  }
  // bind="log" opts a plain <lcars-text-editor> into being the default log
  // entry's editor, i.e. into having its contents saved to the DB. Without
  // it an editor is just typed text the document owns - see
  // Element.bindsToLog.
  bool bindsToLog = false;
  if (GetAttributeValue(tag, "bind", val, sizeof(val))) {
    if (strcmp(val, "log") == 0) {
      bindsToLog = (kind == ELEM_TEXT_EDITOR);
      if (!bindsToLog) {
        TraceLog(LOG_WARNING,
                 "bind=\"log\" only applies to <lcars-text-editor>, ignoring");
      }
    } else {
      TraceLog(LOG_WARNING, "Unknown bind value '%s', ignoring", val);
    }
  }

  char *innerText = NULL;
  bool self_closing = (tag_end > p && *(tag_end - 1) == '/');
  if (!self_closing) {
    char closing_tag[128];
    snprintf(closing_tag, sizeof(closing_tag), "</%s>", tag_name);
    const char *close_tag_p = strstr(tag_end + 1, closing_tag);
    if (close_tag_p) {
      int text_len = close_tag_p - (tag_end + 1);
      // strstr searched forward from tag_end + 1, so the closing tag can
      // only be at or after it.
      assert(text_len >= 0);
      if (text_len > 0) {
        innerText = arena_alloc(&s->scratch_arena, text_len + 1);
        strncpy(innerText, tag_end + 1, text_len);
        innerText[text_len] = '\0';
      }
    }
  }

  Element e = {0};
  e.id = id;
  e.href = href;
  e.control = ParseHyperControl(&s->doc_arena, tag);
  e.bindsToLog = bindsToLog;
  e.position = (Vector2){x, y};
  e.width = w_val;
  e.height = h_val;
  e.color = color;
  e.originalColor = color;
  e.on_click = action;
  e.textSize = textSize;
  if (innerText) {
    e.text = StringInit(&s->doc_arena, innerText);
  } else {
    e.text = StringStatic(NULL);
  }

  if (kind == ELEM_RECTANGLE) {
    make_rectangle(&e);
  } else if (kind == ELEM_ELBOW) {
    make_elbow(&e, orientation);
  } else if (kind == ELEM_BUTTON) {
    make_button(&e);
  } else if (kind == ELEM_TEXT) {
    make_text(&e);
  } else if (kind == ELEM_TEXT_EDITOR) {
    make_text_editor(&s->doc_arena, &e, StringStatic(""));
  } else if (kind == ELEM_ENTRY_LIST) {
    make_entry_list(&s->doc_arena, &e, s);
  } else if (kind == ELEM_SPHERE) {
    char src_path[256] = {0};
    GetAttributeValue(tag, "src", src_path, sizeof(src_path));
    make_sphere(s, &e, src_path[0] ? src_path : NULL);
  }

  // Whatever kind it turned out to be, it is fully constructed: a real
  // kind, valid strings, and its side struct allocated if it needs one.
  assert(e.kind == kind);
  assert(e.kind > ELEM_NOTHING && e.kind < ELEM_TOTAL_KINDS);
  assert(StringValid(e.text) && StringValid(e.id) && StringValid(e.href));
  assert(e.kind != ELEM_ENTRY_LIST || e.entryList != NULL);
  assert(e.kind != ELEM_SPHERE || e.sphere != NULL);
  assert((e.kind != ELEM_TEXT_EDITOR && e.kind != ELEM_ENTRY_LIST) ||
         GapBufferValid(&e.gap));
  // Either no control at all, or one with a real method - the dispatcher
  // switches on Element.control being non-NULL and never re-checks.
  assert(e.control == NULL || (e.control->method > HYPER_METHOD_NONE &&
                               e.control->method < HYPER_METHOD_TOTAL));

  *outElement = e;
  return true;
}

// Parses `buf` into s->elements. The caller owns the surrounding lifecycle
// (resetting doc_arena, zeroing numElements, bumping the generation), which
// is what lets a document come either from a source URL or straight from a
// response body - see LoadHypermediaDocument /
// LoadHypermediaDocumentFromString below.
static void ParseHypermediaElements(State *s, String buf) {
  assert(s != NULL);
  assert(StringValid(buf));
  assert(buf.data != NULL);
  assert(s->numElements == 0); // the caller cleared the previous document

  const char *p = buf.data;
  while (*p) {
    p = strchr(p, '<');
    if (!p)
      break;

    if (strncmp(p, "<!--", 4) == 0) {
      p = strstr(p, "-->");
      if (p)
        p += 3;
      else
        break;
      continue;
    }

    const char *tag_end = strchr(p, '>');
    if (!tag_end)
      break;

    int tag_len = tag_end - p + 1;
    assert(tag_len > 0); // strchr found '>' at or after p
    char *tag = arena_alloc(&s->scratch_arena, tag_len + 1);
    strncpy(tag, p, tag_len);
    tag[tag_len] = '\0';

    char tag_name[64] = {0};
    int i = 1;
    while (p[i] && p[i] != ' ' && p[i] != '>' && p[i] != '/' && i < 63) {
      tag_name[i - 1] = p[i];
      i++;
    }
    // The loop bound is what keeps this terminator inside tag_name.
    assert(i >= 1 && i - 1 < (int)sizeof(tag_name));
    tag_name[i - 1] = '\0';

    if (s->numElements < MAX_ELEMENTS) {
      Element e;
      if (ParseElementTag(s, tag, tag_name, p, tag_end, &e)) {
        s->elements[s->numElements++] = e;
        assert(s->numElements <= MAX_ELEMENTS);
      }
    }

    p = tag_end + 1;
  }

  assert(s->numElements >= 0 && s->numElements <= MAX_ELEMENTS);
}

// Replaces the running document with one already in memory (a response body
// swapped in by a hypermedia control, HYPER_SWAP_DOCUMENT). `source` records
// what to call the new document for a later HYPER_SWAP_RELOAD, or NULL to
// keep whatever was displayed before as the reloadable source - a response
// body has no URL of its own unless the request that produced it was a GET.
//
// `content` may live in scratch_arena; it is fully parsed before that arena
// is reset on the way out, but callers must not touch it afterwards.
void LoadHypermediaDocumentFromString(State *s, String content,
                                      const char *source) {
  assert(s != NULL);
  assert(StringValid(content));
  assert(arena_valid(&s->doc_arena) && arena_valid(&s->scratch_arena));

  // Reset the document arena to reclaim all memory from the previous document
  arena_reset(&s->doc_arena);
  s->numElements = 0;
  // Everything the old elements pointed at (text, ids, per-kind state, their
  // controls) just became reclaimable, so nothing may still be referring to
  // them.
  assert(s->doc_arena.curr_offset == 0);

  if (source != NULL) {
    snprintf(s->currentDocument, sizeof(s->currentDocument), "%s", source);
  }

  if (content.data != NULL) {
    ParseHypermediaElements(s, content);
  }

  // Bumped before anything can run app code again (load triggers below, or
  // the caller's element loop): everything that held an Element * across
  // this call detects the swap by comparing generations.
  s->documentGeneration++;
  UpdateNotification(s, StringStatic("HYPERMEDIA LOADED"));

  // Reset scratch arena immediately after loading is complete
  arena_reset(&s->scratch_arena);

  // Nothing on an Element may point into scratch_arena: parsing staged
  // inner text and tags there, and everything kept had to be copied into
  // doc_arena on the way past.
  assert(s->scratch_arena.curr_offset == 0);
  assert(s->numElements >= 0 && s->numElements <= MAX_ELEMENTS);

  // Runs last, on a fully built document with a clean scratch arena - a
  // load-triggered control is a request made *by* this document.
  FireHyperLoadTriggers(s);
}

void LoadHypermediaDocument(State *s, String source) {
  assert(s != NULL);
  assert(StringValid(source));
  assert(arena_valid(&s->doc_arena) && arena_valid(&s->scratch_arena));

  // `source` is usually an element's href or the URL bar's text, both of
  // which live in the doc_arena that loading is about to reset - copy it out
  // before that happens rather than fetching through freed (if not yet
  // overwritten) memory.
  char sourceBuf[sizeof(s->currentDocument)];
  snprintf(sourceBuf, sizeof(sourceBuf), "%s", source.data ? source.data : "");

  arena_reset(&s->doc_arena);
  s->numElements = 0;
  assert(s->doc_arena.curr_offset == 0);

  String buf = LoadDocumentContent(StringStatic(sourceBuf), s);
  if (!buf.data) {
    // The fetch failed and said so (notification + stderr). The old document
    // is already gone, but leaving numElements at 0 is the honest outcome -
    // and the generation still has to move, because the elements the caller
    // was iterating no longer exist.
    s->documentGeneration++;
    return;
  }
  assert(StringValid(buf));

  ParseHypermediaElements(s, buf);
  StringClear(&buf);

  snprintf(s->currentDocument, sizeof(s->currentDocument), "%s", sourceBuf);
  s->documentGeneration++;
  UpdateNotification(s, StringStatic("HYPERMEDIA LOADED"));

  arena_reset(&s->scratch_arena);

  assert(s->scratch_arena.curr_offset == 0);
  assert(s->numElements >= 0 && s->numElements <= MAX_ELEMENTS);

  FireHyperLoadTriggers(s);
}

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_HYPERMEDIA_H
