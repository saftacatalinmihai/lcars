#ifndef LCARS_HYPERMEDIA_H
#define LCARS_HYPERMEDIA_H

#include "lcars_types.h"
#include "raylib.h"

#include <ctype.h>
#include <curl/curl.h>

struct CurlMemoryBuffer {
  char *data;
  size_t size;
  Arena *arena;
};

static bool GetAttributeValue(const char *tag, const char *attr, char *dest,
                              int max_len);
static ElemKind TagNameToElemKind(const char *tagName);
static Color ParseColor(String colorStr);
static ButtonAction ParseAction(String actionStr);
static size_t CurlWriteMemoryCallback(void *contents, size_t size, size_t nmemb,
                                      void *userp);
static String LoadFromHTTP(String source, State *s);
static String LoadFromFile(String source, State *s);
static String LoadDocumentContent(String source, State *s);
static bool ParseElementTag(State *s, const char *tag, const char *tag_name,
                           const char *p, const char *tag_end,
                           Element *outElement);
void LoadHypermediaDocument(State *s, String source);

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

static size_t CurlWriteMemoryCallback(void *contents, size_t size, size_t nmemb,
                                      void *userp) {
  size_t realsize = size * nmemb;
  struct CurlMemoryBuffer *mem = (struct CurlMemoryBuffer *)userp;
  assert(mem != NULL);
  assert(mem->arena != NULL);
  // LoadFromHTTP() seeds this with a 1-byte allocation before handing the
  // buffer to curl, so it is never NULL on the first callback either.
  assert(mem->data != NULL);
  assert(contents != NULL || realsize == 0);

  size_t oldSize = mem->size;
  (void)oldSize; // read only by the postcondition assert below
  char *ptr =
      arena_realloc(mem->arena, mem->data, mem->size, mem->size + realsize + 1);
  mem->data = ptr;
  memcpy(&(mem->data[mem->size]), contents, realsize);
  mem->size += realsize;
  mem->data[mem->size] = 0;

  assert(mem->size == oldSize + realsize);
  return realsize;
}

static String LoadFromHTTP(String source, State *s) {
  assert(s != NULL);
  assert(StringValid(source));
  assert(source.data != NULL); // handed to curl as CURLOPT_URL

  CURL *curl = curl_easy_init();
  if (!curl) {
    UpdateNotification(s, StringStatic("CURL INIT FAILED"));
    return StringInit(&s->scratch_arena, NULL);
  }

  struct CurlMemoryBuffer chunk;
  chunk.arena = &s->scratch_arena;
  chunk.data = arena_alloc(chunk.arena, 1);
  chunk.size = 0;
  chunk.data[0] = '\0';

  curl_easy_setopt(curl, CURLOPT_URL, source.data);
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, CurlWriteMemoryCallback);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
  curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
  curl_easy_setopt(curl, CURLOPT_FAILONERROR, 1L);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);

  CURLcode res = curl_easy_perform(curl);
  curl_easy_cleanup(curl);

  if (res != CURLE_OK) {
    printf("CURL download failed: %s\n", curl_easy_strerror(res));
    UpdateNotification(s, StringStatic("DOWNLOAD FAILED"));
    return StringInit(&s->scratch_arena, NULL);
  }

  String ret;
  ret.data = chunk.data;
  ret.len = (int)chunk.size;
  ret.is_static = false;
  return ret;
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

  *outElement = e;
  return true;
}

void LoadHypermediaDocument(State *s, String source) {
  assert(s != NULL);
  assert(StringValid(source));
  assert(arena_valid(&s->doc_arena) && arena_valid(&s->scratch_arena));

  // Reset the document arena to reclaim all memory from the previous document
  arena_reset(&s->doc_arena);
  s->numElements = 0;
  // Everything the old elements pointed at (text, ids, per-kind state) just
  // became reclaimable, so nothing may still be referring to them.
  assert(s->doc_arena.curr_offset == 0);

  String buf = LoadDocumentContent(source, s);
  if (!buf.data) {
    return;
  }
  assert(StringValid(buf));

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

  StringClear(&buf);
  UpdateNotification(s, StringStatic("HYPERMEDIA LOADED"));

  // Reset scratch arena immediately after loading is complete
  arena_reset(&s->scratch_arena);

  // Nothing on an Element may point into scratch_arena: parsing staged
  // inner text and tags there, and everything kept had to be copied into
  // doc_arena on the way past.
  assert(s->scratch_arena.curr_offset == 0);
  assert(s->numElements >= 0 && s->numElements <= MAX_ELEMENTS);
}

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_HYPERMEDIA_H
