#ifndef LCARS_HYPERMEDIA_H
#define LCARS_HYPERMEDIA_H

#include "lcars_types.h"
#include "raylib.h"

#include <curl/curl.h>

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

static Color ParseColor(String colorStr) {
  if (colorStr.data == NULL)
    return LCARS_ORANGE;
  if (strcmp(colorStr.data, "purple") == 0)
    return LCARS_PURPLE;
  if (strcmp(colorStr.data, "red") == 0)
    return LCARS_RED_ORANGE;
  if (strcmp(colorStr.data, "orange") == 0)
    return LCARS_ORANGE;
  if (strcmp(colorStr.data, "yellow") == 0)
    return LCARS_YELLOW;
  if (strcmp(colorStr.data, "blue") == 0)
    return LCARS_BLUE;
  if (strcmp(colorStr.data, "white") == 0)
    return WHITE;
  if (strcmp(colorStr.data, "black") == 0)
    return BLACK;
  if (colorStr.len == 7 && colorStr.data[0] == '#') {
    unsigned int r, g, b;
    if (sscanf(colorStr.data + 1, "%02x%02x%02x", &r, &g, &b) == 3) {
      return (Color){(unsigned char)r, (unsigned char)g, (unsigned char)b, 255};
    }
  }
  return LCARS_ORANGE;
}

static ButtonAction ParseAction(String actionStr) {
  if (actionStr.data == NULL)
    return ACTION_NONE;
  if (strcmp(actionStr.data, "debug") == 0)
    return ACTION_DEBUG;
  if (strcmp(actionStr.data, "edit") == 0)
    return ACTION_EDIT;
  if (strcmp(actionStr.data, "reset") == 0)
    return ACTION_RESET;
  if (strcmp(actionStr.data, "voice_input") == 0)
    return ACTION_VOICE_INPUT;
  if (strcmp(actionStr.data, "print_db") == 0)
    return ACTION_PRINT_DB;
  if (strcmp(actionStr.data, "load_hypermedia") == 0)
    return ACTION_LOAD_HYPERMEDIA;
  return ACTION_NONE;
}

struct CurlMemoryBuffer {
  char *data;
  size_t size;
  Arena *arena;
};

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

    ElemKind kind = ELEM_NOTHING;
    if (strcmp(tag_name, "lcars-button") == 0)
      kind = ELEM_BUTTON;
    else if (strcmp(tag_name, "lcars-rect") == 0 ||
             strcmp(tag_name, "lcars-rectangle") == 0)
      kind = ELEM_RECTANGLE;
    else if (strcmp(tag_name, "lcars-text") == 0)
      kind = ELEM_TEXT;
    else if (strcmp(tag_name, "lcars-elbow") == 0)
      kind = ELEM_ELBOW;
    else if (strcmp(tag_name, "lcars-text-editor") == 0)
      kind = ELEM_TEXT_EDITOR;
    else if (strcmp(tag_name, "lcars-entry-list") == 0)
      kind = ELEM_ENTRY_LIST;
    else if (strcmp(tag_name, "lcars-sphere") == 0)
      kind = ELEM_SPHERE;

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
      if (GetAttributeValue(tag, "orientation", val, sizeof(val)))
        orientation = atoi(val);
      if (GetAttributeValue(tag, "size", val, sizeof(val))) {
        textSize = atoi(val);
        if (textSize < 20)
          textSize = 20;
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

      float *w_ptr = arena_alloc(&s->doc_arena, sizeof(float));
      if (w_ptr)
        *w_ptr = w_val;
      float *h_ptr = arena_alloc(&s->doc_arena, sizeof(float));
      if (h_ptr)
        *h_ptr = h_val;

      Element e = {0};
      e.position = (Vector2){x, y};
      e.width = w_ptr;
      e.height = h_ptr;
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

#endif // LCARS_HYPERMEDIA_H
