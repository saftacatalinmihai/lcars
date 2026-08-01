#ifndef LCARS_HYPERMEDIA_H
#define LCARS_HYPERMEDIA_H

#include "lcars_types.h"
#include "raylib.h"

#include <curl/curl.h>

struct CurlMemoryBuffer {
  char *data;
  size_t size;
  Arena *arena;
};

static const char *GetAttributeValue(const char *tag, const char *attr,
                                     char *dest, int max_len);
static ElemKind TagNameToElemKind(const char *tagName);
static Color ParseColor(String colorStr);
static ButtonAction ParseAction(String actionStr);
static size_t CurlWriteMemoryCallback(void *contents, size_t size, size_t nmemb,
                                      void *userp);
static String LoadDocumentContent(String source, State *s);
void LoadHypermediaDocument(State *s, String source);

#ifdef LCARS_IMPLEMENTATION

static const char *GetAttributeValue(const char *tag, const char *attr,
                                     char *dest, int max_len) {
  char pattern[128];
  snprintf(pattern, sizeof(pattern), "%s=", attr);
  const char *p = strstr(tag, pattern);
  if (!p)
    return NULL;
  p += strlen(pattern);
  char quote = *p;
  if (quote == '"' || quote == '\'') {
    p++;
    int len = 0;
    while (*p && *p != quote && len < max_len - 1) {
      dest[len++] = *p++;
    }
    dest[len] = '\0';
    return p;
  }
  return NULL;
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
  for (size_t i = 0; i < sizeof(TAG_KIND_TABLE) / sizeof(TAG_KIND_TABLE[0]);
      i++) {
    if (strcmp(tagName, TAG_KIND_TABLE[i].tagName) == 0) {
      return TAG_KIND_TABLE[i].kind;
    }
  }
  return ELEM_NOTHING;
}

static Color ParseColor(String colorStr) {
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

  char *ptr =
      arena_realloc(mem->arena, mem->data, mem->size, mem->size + realsize + 1);
  if (!ptr) {
    return 0;
  }

  mem->data = ptr;
  memcpy(&(mem->data[mem->size]), contents, realsize);
  mem->size += realsize;
  mem->data[mem->size] = 0;

  return realsize;
}

static String LoadDocumentContent(String source, State *s) {
  if (source.data == NULL) {
    return StringInit(&s->scratch_arena, NULL);
  }
  if (strncmp(source.data, "http://", 7) == 0 ||
      strncmp(source.data, "https://", 8) == 0) {
    CURL *curl = curl_easy_init();
    if (!curl) {
      updateNotification(s, StringStatic("CURL INIT FAILED"));
      return StringInit(&s->scratch_arena, NULL);
    }

    struct CurlMemoryBuffer chunk;
    chunk.arena = &s->scratch_arena;
    chunk.data = arena_alloc(chunk.arena, 1);
    if (!chunk.data) {
      curl_easy_cleanup(curl);
      return StringInit(&s->scratch_arena, NULL);
    }
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
      updateNotification(s, StringStatic("DOWNLOAD FAILED"));
      return StringInit(&s->scratch_arena, NULL);
    }

    String ret;
    ret.data = chunk.data;
    ret.len = (int)chunk.size;
    ret.is_static = false;
    return ret;
  } else {
    const char *local_path = source.data;
    if (strncmp(source.data, "file://", 7) == 0) {
      local_path = source.data + 7;
    }

    FILE *f = fopen(local_path, "r");
    if (!f) {
      printf("Failed to open file: %s\n", local_path);
      updateNotification(s, StringStatic("FILE NOT FOUND"));
      return StringInit(&s->scratch_arena, NULL);
    }

    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);

    char *buf = arena_alloc(&s->scratch_arena, size + 1);
    if (!buf) {
      fclose(f);
      return StringInit(&s->scratch_arena, NULL);
    }
    size_t read_bytes = fread(buf, 1, size, f);
    buf[read_bytes] = '\0';
    fclose(f);

    String ret;
    ret.data = buf;
    ret.len = (int)read_bytes;
    ret.is_static = false;
    return ret;
  }
}

void LoadHypermediaDocument(State *s, String source) {
  // Reset the document arena to reclaim all memory from the previous document
  arena_reset(&s->doc_arena);
  s->numElements = 0;

  String buf = LoadDocumentContent(source, s);
  if (!buf.data) {
    return;
  }

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
    char *tag = arena_alloc(&s->scratch_arena, tag_len + 1);
    if (tag) {
      strncpy(tag, p, tag_len);
      tag[tag_len] = '\0';
    }

    char tag_name[64] = {0};
    int i = 1;
    while (p[i] && p[i] != ' ' && p[i] != '>' && p[i] != '/' && i < 63) {
      tag_name[i - 1] = p[i];
      i++;
    }
    tag_name[i - 1] = '\0';

    ElemKind kind = TagNameToElemKind(tag_name);

    if (kind != ELEM_NOTHING && s->numElements < MAX_ELEMENTS) {
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
        // lcars_ui.h) - the other two corners were never implemented.
        // Reject anything else here rather than let a bad value reach
        // those switches.
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

      char *innerText = NULL;
      bool self_closing = false;
      if (tag_end > p && *(tag_end - 1) == '/') {
        self_closing = true;
      }

      if (!self_closing) {
        char closing_tag[128];
        snprintf(closing_tag, sizeof(closing_tag), "</%s>", tag_name);
        const char *close_tag_p = strstr(tag_end + 1, closing_tag);
        if (close_tag_p) {
          int text_len = close_tag_p - (tag_end + 1);
          if (text_len > 0) {
            innerText = arena_alloc(&s->scratch_arena, text_len + 1);
            if (innerText) {
              strncpy(innerText, tag_end + 1, text_len);
              innerText[text_len] = '\0';
            }
          }
        }
      }

      Element e = {0};
      e.id = id;
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

      s->elements[s->numElements++] = e;
    }

    p = tag_end + 1;
  }

  StringFree(&buf);
  updateNotification(s, StringStatic("HYPERMEDIA LOADED"));

  // Reset scratch arena immediately after loading is complete
  arena_reset(&s->scratch_arena);
}

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_HYPERMEDIA_H
