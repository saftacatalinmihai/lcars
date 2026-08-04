#ifndef LCARS_HYPERMEDIA_CONTROLS_H
#define LCARS_HYPERMEDIA_CONTROLS_H

// Hypermedia controls: the part of the document format that *does* something
// instead of only describing pixels. Until now a document could express
// exactly one interaction - "load that other document" (action=
// "load_hypermedia" + href), the equivalent of a GET link. This module adds
// the other verbs, in the spirit of HTMX/DataStar but without a scripting
// language: an element declares a request, where the answer goes, and what
// makes it fire.
//
//   <lcars-button lc-post="/entries"
//                 lc-vals="kind=architect_log,title=Away Team"
//                 lc-include="notes_editor">NEW LOG</lcars-button>
//
// Attribute reference (parsed in ParseHyperControl(), lcars_hypermedia.h):
//
//   lc-get|lc-post|lc-put|lc-delete="<url>"
//        The request. A url starting with '/' is served in-process from
//        lcars.db (this app is its own origin - see
//        HyperHandleLocalRequest); an http(s):// url goes out over the
//        network via lcars_net.h.
//   lc-target="<element id>"
//        Element a text/append swap writes into. A leading '#' is accepted
//        (HTMX habit) and ignored.
//   lc-swap="none|text|append|document|reload"
//        What to do with the response. Defaults, when unset: `text` if
//        lc-target is set, else `document` for GET, else `none`.
//   lc-trigger="click|load"
//        Defaults to click. `load` fires once, right after the document
//        that declares it has finished parsing.
//   lc-vals="name=value,name=value"
//        Literal request fields. NOT JSON like HTMX's hx-vals: a flat
//        name=value list needs a 20-line parser here instead of a real JSON
//        one, and nothing in this format needs nesting yet. Consequence: a
//        value cannot contain a comma or an '='.
//   lc-include="<id> <id>"
//        Fields taken from other elements' text. The element's `id` is the
//        field name - the id *is* the form-control name, which is why
//        elements the user types into want short, field-shaped ids.
//
// The local resource surface deliberately mirrors the HTTP API in
// lcars_http.h (POST /entries creates an entry), so the same document works
// against this app's own DB or against a remote LCARS server - the only
// difference is whether the url is a path or absolute.

#include "lcars_net.h"
#include "lcars_types.h"

#include <ctype.h>

static const char *HyperMethodName(HyperMethod method);
static HyperSwap ParseHyperSwap(String swapStr);
static HyperTrigger ParseHyperTrigger(String triggerStr);
// Issues e's control now, whatever its trigger says - the trigger is the
// caller's business (a click in HandleElementClick, document load in
// FireHyperLoadTriggers).
static void FireHyperControl(State *s, Element *e);
// Fires every HYPER_TRIGGER_LOAD control in the freshly parsed document.
static void FireHyperLoadTriggers(State *s);

#ifdef LCARS_IMPLEMENTATION

static const char *HyperMethodName(HyperMethod method) {
  // Indexed straight into the switch below; a NONE control should never have
  // reached a request in the first place.
  assert(method > HYPER_METHOD_NONE && method < HYPER_METHOD_TOTAL);
  switch (method) {
  case HYPER_METHOD_GET:
    return "GET";
  case HYPER_METHOD_POST:
    return "POST";
  case HYPER_METHOD_PUT:
    return "PUT";
  case HYPER_METHOD_DELETE:
    return "DELETE";
  default:
    assert(!"unreachable");
    return "GET";
  }
}

static const struct {
  const char *name;
  HyperSwap swap;
} HYPER_SWAP_TABLE[] = {
    {"none", HYPER_SWAP_NONE},     {"text", HYPER_SWAP_TEXT},
    {"append", HYPER_SWAP_APPEND}, {"document", HYPER_SWAP_DOCUMENT},
    {"reload", HYPER_SWAP_RELOAD},
};

// Unknown values fall back to HYPER_SWAP_DEFAULT (i.e. "the document didn't
// say"), with a warning: a typo in a document is runtime input, not a
// programmer error, and silently doing nothing would be harder to debug than
// doing the default thing loudly.
static HyperSwap ParseHyperSwap(String swapStr) {
  assert(StringValid(swapStr));
  if (swapStr.data == NULL || swapStr.len == 0)
    return HYPER_SWAP_DEFAULT;
  for (size_t i = 0; i < sizeof(HYPER_SWAP_TABLE) / sizeof(HYPER_SWAP_TABLE[0]);
       i++) {
    if (strcmp(swapStr.data, HYPER_SWAP_TABLE[i].name) == 0) {
      return HYPER_SWAP_TABLE[i].swap;
    }
  }
  TraceLog(LOG_WARNING, "Unknown lc-swap value '%s', using the default",
           swapStr.data);
  return HYPER_SWAP_DEFAULT;
}

static HyperTrigger ParseHyperTrigger(String triggerStr) {
  assert(StringValid(triggerStr));
  if (triggerStr.data == NULL || triggerStr.len == 0)
    return HYPER_TRIGGER_CLICK;
  if (strcmp(triggerStr.data, "load") == 0)
    return HYPER_TRIGGER_LOAD;
  if (strcmp(triggerStr.data, "click") != 0) {
    TraceLog(LOG_WARNING, "Unknown lc-trigger value '%s', using click",
             triggerStr.data);
  }
  return HYPER_TRIGGER_CLICK;
}

// What the document meant when it left lc-swap out. Kept in one place
// because both the dispatcher and the "did this swap replace the document?"
// check have to agree about it.
static HyperSwap ResolveHyperSwap(const HyperControl *ctl) {
  assert(ctl != NULL);
  assert(ctl->swap >= HYPER_SWAP_DEFAULT && ctl->swap < HYPER_SWAP_TOTAL);

  if (ctl->swap != HYPER_SWAP_DEFAULT)
    return ctl->swap;
  if (ctl->target.len > 0)
    return HYPER_SWAP_TEXT;
  if (ctl->method == HYPER_METHOD_GET)
    return HYPER_SWAP_DOCUMENT;
  return HYPER_SWAP_NONE;
}

// -----------------------------------------------------------------------------
// Request fields
// -----------------------------------------------------------------------------

// Copies [begin, end) into `arena` with leading/trailing ASCII whitespace
// removed. Both bounds point into the same NUL-terminated buffer.
static String HyperTrimmedSlice(Arena *arena, const char *begin,
                                const char *end) {
  assert(arena != NULL);
  assert(begin != NULL && end != NULL);
  assert(end >= begin);

  while (begin < end && isspace((unsigned char)*begin))
    begin++;
  while (end > begin && isspace((unsigned char)*(end - 1)))
    end--;

  assert(end >= begin);
  return StringInitLen(arena, begin, (int)(end - begin));
}

static Element *FindEntryListElement(State *s) {
  assert(s != NULL);
  assert(s->numElements >= 0 && s->numElements <= MAX_ELEMENTS);
  for (int i = 0; i < s->numElements; i++) {
    if (s->elements[i].kind == ELEM_ENTRY_LIST) {
      assert(s->elements[i].entryList != NULL);
      return &s->elements[i];
    }
  }
  return NULL;
}

// Builds the request's name=value fields from lc-vals and lc-include. Values
// are copied into scratch_arena rather than aliased from the source elements
// because a document-replacing swap later in the same dispatch resets
// doc_arena, and the body may still be needed to build the request. Returns
// how many fields were collected (never more than maxFields).
static int CollectHyperFields(State *s, const HyperControl *ctl,
                              HyperField *out, int maxFields) {
  assert(s != NULL);
  assert(ctl != NULL);
  assert(out != NULL);
  assert(maxFields > 0);
  assert(StringValid(ctl->vals) && StringValid(ctl->include));

  int count = 0;

  if (ctl->vals.len > 0) {
    const char *p = ctl->vals.data;
    while (*p != '\0') {
      const char *pairEnd = strchr(p, ',');
      if (pairEnd == NULL) {
        pairEnd = p + strlen(p);
      }
      const char *eq = (const char *)memchr(p, '=', (size_t)(pairEnd - p));
      if (eq == NULL) {
        TraceLog(LOG_WARNING, "lc-vals: ignoring pair without '=' in '%s'",
                 ctl->vals.data);
      } else if (count >= maxFields) {
        TraceLog(LOG_WARNING, "lc-vals: more than %d fields, dropping the rest",
                 maxFields);
        break;
      } else {
        String name = HyperTrimmedSlice(&s->scratch_arena, p, eq);
        String value = HyperTrimmedSlice(&s->scratch_arena, eq + 1, pairEnd);
        if (name.len > 0) {
          out[count].name = name;
          out[count].value = value;
          count++;
        }
      }
      p = (*pairEnd == ',') ? pairEnd + 1 : pairEnd;
    }
  }

  if (ctl->include.len > 0) {
    const char *p = ctl->include.data;
    while (*p != '\0') {
      while (*p == ' ' || *p == ',' || *p == '\t' || *p == '\n')
        p++;
      if (*p == '\0')
        break;
      const char *idEnd = p;
      while (*idEnd != '\0' && *idEnd != ' ' && *idEnd != ',' &&
             *idEnd != '\t' && *idEnd != '\n')
        idEnd++;
      // A leading '#' is what an HTMX user's fingers type; ids in this
      // format have no sigil.
      const char *idStart = (*p == '#') ? p + 1 : p;
      String id = HyperTrimmedSlice(&s->scratch_arena, idStart, idEnd);
      p = idEnd;
      if (id.len == 0)
        continue;

      Element *src = FindElementById(s, id.data);
      if (src == NULL) {
        TraceLog(LOG_WARNING, "lc-include: no element with id '%s'", id.data);
        continue;
      }
      if (count >= maxFields) {
        TraceLog(LOG_WARNING,
                 "lc-include: more than %d fields, dropping the rest",
                 maxFields);
        break;
      }
      assert(StringValid(src->text));
      out[count].name = id;
      out[count].value =
          StringInitLen(&s->scratch_arena, src->text.data, src->text.len);
      count++;
    }
  }

  assert(count >= 0 && count <= maxFields);
  return count;
}

static String HyperFieldValue(const HyperField *fields, int count,
                              const char *name, String fallback) {
  assert(fields != NULL || count == 0);
  assert(count >= 0);
  assert(name != NULL);
  assert(StringValid(fallback));

  for (int i = 0; i < count; i++) {
    assert(StringValid(fields[i].name) && StringValid(fields[i].value));
    if (StringEqC(fields[i].name, name)) {
      return fields[i].value;
    }
  }
  return fallback;
}

static bool HyperHasField(const HyperField *fields, int count,
                          const char *name) {
  assert(fields != NULL || count == 0);
  assert(name != NULL);
  for (int i = 0; i < count; i++) {
    if (StringEqC(fields[i].name, name))
      return true;
  }
  return false;
}

// Escapes `in` for use inside a JSON string literal. Measures first, then
// writes, so the allocation is exact - the two passes must stay in sync,
// which the postcondition asserts.
static String HyperJsonEscape(Arena *arena, String in) {
  assert(arena != NULL);
  assert(StringValid(in));

  size_t needed = 0;
  for (int i = 0; i < in.len; i++) {
    unsigned char c = (unsigned char)in.data[i];
    if (c == '"' || c == '\\' || c == '\b' || c == '\f' || c == '\n' ||
        c == '\r' || c == '\t') {
      needed += 2;
    } else if (c < 0x20) {
      needed += 6; // \u00XX
    } else {
      needed += 1;
    }
  }

  char *outBuf = arena_alloc(arena, needed + 1);
  char *dst = outBuf;
  for (int i = 0; i < in.len; i++) {
    unsigned char c = (unsigned char)in.data[i];
    switch (c) {
    case '"':
      *dst++ = '\\';
      *dst++ = '"';
      break;
    case '\\':
      *dst++ = '\\';
      *dst++ = '\\';
      break;
    case '\b':
      *dst++ = '\\';
      *dst++ = 'b';
      break;
    case '\f':
      *dst++ = '\\';
      *dst++ = 'f';
      break;
    case '\n':
      *dst++ = '\\';
      *dst++ = 'n';
      break;
    case '\r':
      *dst++ = '\\';
      *dst++ = 'r';
      break;
    case '\t':
      *dst++ = '\\';
      *dst++ = 't';
      break;
    default:
      if (c < 0x20) {
        // Every other control byte is invalid raw inside a JSON string.
        snprintf(dst, 7, "\\u%04x", c);
        dst += 6;
      } else {
        *dst++ = (char)c;
      }
      break;
    }
  }
  *dst = '\0';

  String out;
  out.data = outBuf;
  out.len = (int)(dst - outBuf);
  out.is_static = false;
  // The writing pass must land exactly where the measuring pass said it
  // would; anything else means the two switch statements have drifted apart
  // and the terminator went outside the allocation.
  assert((size_t)out.len == needed);
  assert(StringValid(out));
  return out;
}

// Serializes the collected fields as a flat JSON object - the same shape
// lcars_http.h's POST /entries parses, so a control aimed at a remote LCARS
// server speaks that server's language without any per-endpoint knowledge.
static String HyperJsonBody(Arena *arena, const HyperField *fields, int count) {
  assert(arena != NULL);
  assert(fields != NULL || count == 0);
  assert(count >= 0);

  String out = StringInit(arena, "{");
  for (int i = 0; i < count; i++) {
    if (i > 0) {
      StringConcatC(arena, &out, ",");
    }
    StringConcatC(arena, &out, "\"");
    StringConcat(arena, &out, HyperJsonEscape(arena, fields[i].name));
    StringConcatC(arena, &out, "\":\"");
    StringConcat(arena, &out, HyperJsonEscape(arena, fields[i].value));
    StringConcatC(arena, &out, "\"");
  }
  StringConcatC(arena, &out, "}");

  assert(StringValid(out));
  assert(out.len >= 2); // at least "{}"
  return out;
}

// -----------------------------------------------------------------------------
// Local (in-process) requests
// -----------------------------------------------------------------------------

// Marks every entry-list element's cached DB reads stale. Any local route
// that writes to the entries table has to call this, exactly like the UI's
// own write paths do - the list is drawn from the cache, not from the DB.
static void InvalidateAllEntryCaches(State *s) {
  assert(s != NULL);
  for (int i = 0; i < s->numElements; i++) {
    if (s->elements[i].kind == ELEM_ENTRY_LIST) {
      assert(s->elements[i].entryList != NULL);
      InvalidateEntryListCache(&s->elements[i]);
      InvalidateKindListCache(&s->elements[i]);
    }
  }
}

// Re-reads `entryId` from the DB into any entry list currently displaying
// it, so a control that rewrote an entry doesn't leave a stale editor
// showing (and later re-saving) the pre-request text. `entryId` of 0 means
// the entry is gone: the list moves to the newest remaining entry of its
// kind, or to nothing at all if the kind is now empty.
static void ResyncEntryListsFor(State *s, int entryId, bool deleted) {
  assert(s != NULL);
  assert(entryId > 0);

  for (int i = 0; i < s->numElements; i++) {
    Element *e = &s->elements[i];
    if (e->kind != ELEM_ENTRY_LIST)
      continue;
    assert(e->entryList != NULL);
    if (e->entryList->selectedEntryId != entryId)
      continue;

    // The request is the newer truth: whatever the editor was holding for
    // this entry is discarded rather than flushed, or the debounced save
    // would immediately undo the write we just performed.
    e->contentDirty = false;
    if (deleted) {
      EnsureEntryListCache(s, e);
      int nextEntryId = e->entryList->cachedEntryCount > 0
                            ? e->entryList->cachedEntries[0].id
                            : 0;
      SwitchToEntry(s, e, nextEntryId);
    } else {
      SwitchToEntry(s, e, entryId);
    }
    assert(!e->contentDirty);
  }
}

// Serves a control's request against lcars.db in-process, returning an
// HTTP-shaped status code and a response body in scratch_arena. Routes:
//
//   POST   /entries              create (fields: kind, title, content)
//   GET    /entries/<id>         the entry's content, as plain text
//   PUT    /entries/<id>         update (fields: content and/or title)
//   DELETE /entries/<id>         soft-delete
//
// <id> is a row id or the literal `selected`, which resolves to whatever
// entry the entry-list element is showing - the hypermedia way to say "this
// one" without a scripting language to compute it.
//
// Everything that can go wrong here (no such route, a malformed id, a DB
// that never opened) is a runtime condition and comes back as a status code
// and a message; only genuine programmer errors assert.
static int HyperHandleLocalRequest(State *s, HyperMethod method, String path,
                                   const HyperField *fields, int fieldCount,
                                   String *outBody) {
  assert(s != NULL);
  assert(method > HYPER_METHOD_NONE && method < HYPER_METHOD_TOTAL);
  assert(StringValid(path));
  assert(path.data != NULL && path.data[0] == '/');
  assert(outBody != NULL);

  *outBody = StringStatic("");

  if (s->db == NULL) {
    *outBody = StringStatic("{\"error\":\"no database\"}");
    return 500;
  }

  const char *p = path.data;
  if (strncmp(p, "/entries", 8) != 0) {
    *outBody = StringStatic("{\"error\":\"no such resource\"}");
    return 404;
  }
  p += 8;

  int entryId = 0;
  bool haveId = false;
  if (*p == '/' && p[1] != '\0') {
    const char *idStr = p + 1;
    if (strcmp(idStr, "selected") == 0) {
      Element *list = FindEntryListElement(s);
      if (list == NULL) {
        *outBody =
            StringStatic("{\"error\":\"no entry list in this document\"}");
        return 404;
      }
      entryId = list->entryList->selectedEntryId;
      haveId = true;
    } else if (isdigit((unsigned char)*idStr)) {
      entryId = atoi(idStr);
      haveId = true;
    } else {
      *outBody = StringStatic("{\"error\":\"bad entry id\"}");
      return 404;
    }
    if (entryId <= 0) {
      // Also covers `selected` before anything is selected, which is a real
      // state (an empty kind) rather than a bug.
      *outBody = StringStatic("{\"error\":\"no such entry\"}");
      return 404;
    }
    if (!EntryExistsInDB(s, entryId)) {
      // An UPDATE against a missing row is a no-op sqlite calls a success,
      // so without this check a document could delete entry 9999 forever and
      // be told it worked every time.
      *outBody = StringStatic("{\"error\":\"no such entry\"}");
      return 404;
    }
  } else if (*p != '\0' && !(*p == '/' && p[1] == '\0')) {
    *outBody = StringStatic("{\"error\":\"no such resource\"}");
    return 404;
  }

  if (method == HYPER_METHOD_POST && !haveId) {
    String kind = HyperFieldValue(fields, fieldCount, "kind",
                                  StringStatic(DEFAULT_ENTRY_KIND));
    String title = HyperFieldValue(fields, fieldCount, "title", kind);
    String content =
        HyperFieldValue(fields, fieldCount, "content", StringStatic(""));
    if (kind.len == 0) {
      kind = StringStatic(DEFAULT_ENTRY_KIND);
    }
    if (title.len == 0) {
      // An untitled entry is indistinguishable from every other untitled
      // entry in the list panel, which draws titles. The kind is at least
      // something to look at, and it is what the UI's own "+ NEW ENTRY"
      // button uses.
      title = kind;
    }
    int newId = CreateNewEntry(s, kind.data, title.data, content);
    if (newId <= 0) {
      *outBody = StringStatic("{\"error\":\"insert failed\"}");
      return 500;
    }
    InvalidateAllEntryCaches(s);
    StringFormat(&s->scratch_arena, outBody,
                 "{\"status\":\"created\",\"id\":%d}", newId);
    return 201;
  }

  if (method == HYPER_METHOD_GET && haveId) {
    // Plain text, not JSON: this is the response a text/append swap drops
    // straight into an editor or a label.
    *outBody = GetEntryContentFromDB(s, entryId);
    return 200;
  }

  if (method == HYPER_METHOD_PUT && haveId) {
    bool wroteSomething = false;
    if (HyperHasField(fields, fieldCount, "content")) {
      UpdateEntryContentInDB(
          s, entryId,
          HyperFieldValue(fields, fieldCount, "content", StringStatic("")));
      wroteSomething = true;
    }
    if (HyperHasField(fields, fieldCount, "title")) {
      UpdateEntryTitleInDB(
          s, entryId,
          HyperFieldValue(fields, fieldCount, "title", StringStatic("")));
      wroteSomething = true;
    }
    if (!wroteSomething) {
      *outBody = StringStatic("{\"error\":\"no content or title field\"}");
      return 400;
    }
    InvalidateAllEntryCaches(s);
    ResyncEntryListsFor(s, entryId, false);
    StringFormat(&s->scratch_arena, outBody,
                 "{\"status\":\"updated\",\"id\":%d}", entryId);
    return 200;
  }

  if (method == HYPER_METHOD_DELETE && haveId) {
    DeleteEntryFromDB(s, entryId);
    InvalidateAllEntryCaches(s);
    ResyncEntryListsFor(s, entryId, true);
    StringFormat(&s->scratch_arena, outBody,
                 "{\"status\":\"deleted\",\"id\":%d}", entryId);
    return 200;
  }

  *outBody = StringStatic("{\"error\":\"method not allowed for this path\"}");
  return 405;
}

// -----------------------------------------------------------------------------
// Applying the response
// -----------------------------------------------------------------------------

// Replaces (or extends) an element's text with `text`. Editor-backed kinds
// go through LoadEntryIntoEditor so the gap buffer, the cached length and
// the dropped selection all stay consistent with the new contents; anything
// else just carries a String.
//
// NOTE for the editor kinds: this loads text the DB doesn't know about into
// the buffer bound to the selected entry. It is not marked dirty, so nothing
// is written until the user edits - at which point the swapped-in text is
// what gets saved, which is exactly what a document asking for it wants.
static void SwapElementText(State *s, Element *target, String text,
                            bool append) {
  assert(s != NULL);
  assert(target != NULL);
  assert(StringValid(text));
  assert(StringValid(target->text));

  String newText = text;
  if (append && target->text.len > 0) {
    newText =
        StringInitLen(&s->scratch_arena, target->text.data, target->text.len);
    StringConcat(&s->scratch_arena, &newText, text);
  }

  if (target->kind == ELEM_TEXT_EDITOR || target->kind == ELEM_ENTRY_LIST) {
    assert(GapBufferValid(&target->gap));
    LoadEntryIntoEditor(&s->doc_arena, target, newText);
    assert(GapTextLen(&target->gap) == target->textLen);
  } else {
    StringAssign(&s->doc_arena, &target->text, newText);
    target->textLen = target->text.len;
  }

  assert(StringValid(target->text));
  assert(target->textLen == target->text.len);
}

// Applies `swap` to `body`. Returns true if the swap replaced the whole
// document, in which case every Element pointer the caller was holding (and
// everything in doc_arena) is gone and it must not touch them again.
//
// `target` is passed by value and must already be a scratch_arena copy for
// the same reason - it is read after the document may have been thrown away.
// `documentSource` is what a DOCUMENT swap should remember as the reloadable
// source of the new document (the request URL for a GET, NULL otherwise -
// re-issuing a POST on a refresh is not what anyone means by "reload").
static bool ApplyHyperSwap(State *s, HyperSwap swap, String target, String body,
                           const char *documentSource) {
  assert(s != NULL);
  assert(swap > HYPER_SWAP_DEFAULT && swap < HYPER_SWAP_TOTAL);
  assert(StringValid(target));
  assert(StringValid(body));

  switch (swap) {
  case HYPER_SWAP_NONE:
    return false;

  case HYPER_SWAP_TEXT:
  case HYPER_SWAP_APPEND: {
    if (target.len == 0) {
      UpdateNotification(s, StringStatic("SWAP: NO TARGET"));
      return false;
    }
    Element *targetElem = FindElementById(s, target.data);
    if (targetElem == NULL) {
      TraceLog(LOG_WARNING, "lc-target: no element with id '%s'", target.data);
      UpdateNotification(s, StringStatic("SWAP: TARGET NOT FOUND"));
      return false;
    }
    SwapElementText(s, targetElem, body, swap == HYPER_SWAP_APPEND);
    return false;
  }

  case HYPER_SWAP_DOCUMENT: {
    // A response that isn't a document would parse to zero elements and
    // leave a blank screen with no clue why - far more likely a JSON reply
    // aimed at the wrong swap than an actually empty document.
    if (body.data == NULL || strstr(body.data, "<lcars") == NULL) {
      UpdateNotification(s, StringStatic("SWAP: NOT A DOCUMENT"));
      return false;
    }
    LoadHypermediaDocumentFromString(s, body, documentSource);
    return true;
  }

  case HYPER_SWAP_RELOAD: {
    if (s->currentDocument[0] == '\0') {
      UpdateNotification(s, StringStatic("SWAP: NO DOCUMENT TO RELOAD"));
      return false;
    }
    // currentDocument lives in State, not doc_arena, precisely so it can be
    // read here - LoadHypermediaDocument resets doc_arena on the way in.
    LoadHypermediaDocument(s, StringStatic(s->currentDocument));
    return true;
  }

  default:
    assert(!"unreachable");
    return false;
  }
}

// -----------------------------------------------------------------------------
// Dispatch
// -----------------------------------------------------------------------------

// Depth guard for HYPER_TRIGGER_LOAD. A load-triggered control whose swap
// replaces the document would otherwise fire the new document's load
// triggers from inside the old document's, with no bound on the nesting; one
// level is all this needs. Resets to 0 on hot reload, which is harmless -
// it is only ever non-zero inside a single call stack.
static int g_hyperLoadDepth = 0;

static void FireHyperControl(State *s, Element *e) {
  assert(s != NULL);
  assert(e != NULL);
  assert(e->control != NULL); // callers check before dispatching
  assert(arena_valid(&s->scratch_arena));

  HyperControl *ctl = e->control;
  assert(ctl->method > HYPER_METHOD_NONE && ctl->method < HYPER_METHOD_TOTAL);
  assert(StringValid(ctl->url) && StringValid(ctl->target));

  if (ctl->url.len == 0) {
    UpdateNotification(s, StringStatic("CONTROL: NO URL"));
    return;
  }

  HyperField fields[MAX_HYPER_FIELDS];
  int fieldCount = CollectHyperFields(s, ctl, fields, MAX_HYPER_FIELDS);

  // Snapshot everything still needed after the request: a document/reload
  // swap resets doc_arena, and `e`, `ctl` and every String they own die with
  // it. scratch_arena survives until the end of the frame (and past the
  // load, which only resets it on the way out), so copies made here stay
  // readable exactly as long as this function needs them.
  HyperMethod method = ctl->method;
  HyperSwap swap = ResolveHyperSwap(ctl);
  String url = StringInitLen(&s->scratch_arena, ctl->url.data, ctl->url.len);
  String target =
      StringInitLen(&s->scratch_arena, ctl->target.data, ctl->target.len);
  ctl = NULL;
  e = NULL;

  String body = StringStatic("");
  long status = 0;
  bool transportOk = true;

  if (url.data[0] == '/') {
    status = HyperHandleLocalRequest(s, method, url, fields, fieldCount, &body);
  } else if (IsDocumentURL(url.data) && !IsHttpURL(url.data)) {
    // file://... (or a bare path ending in .html): the local-document case
    // that action="load_hypermedia" + href has always covered, now reachable
    // as lc-get="file://..." with the same defaults - which is what makes
    // lc-get a superset of the old GET-style link.
    if (method != HYPER_METHOD_GET) {
      TraceLog(LOG_WARNING, "hypermedia control: %s is not possible on '%s'",
               HyperMethodName(method), url.data);
      UpdateNotification(s, StringStatic("CONTROL: FILE IS GET-ONLY"));
      return;
    }
    body = LoadDocumentContent(url, s);
    // LoadDocumentContent already reported why (notification + stderr); a
    // NULL body just means there is nothing to swap.
    status = (body.data != NULL) ? 200 : 404;
    if (body.data == NULL) {
      body = StringStatic("");
    }
  } else if (IsHttpURL(url.data)) {
    // GET carries no body: fields belong in a query string, which this
    // format has no syntax for yet (see TODO.md). A fieldless request sends
    // nothing at all rather than an empty "{}" object - a DELETE with a
    // body is the kind of thing servers and proxies disagree about.
    String requestBody =
        (method == HYPER_METHOD_GET || fieldCount == 0)
            ? StringStatic("")
            : HyperJsonBody(&s->scratch_arena, fields, fieldCount);
    transportOk =
        NetHttpRequest(&s->scratch_arena, HyperMethodName(method), url.data,
                       requestBody, "application/json", &body, &status);
  } else {
    TraceLog(LOG_WARNING, "hypermedia control: unusable url '%s'", url.data);
    UpdateNotification(s, StringStatic("CONTROL: BAD URL"));
    return;
  }

  if (!transportOk) {
    UpdateNotification(s, StringStatic("CONTROL: REQUEST FAILED"));
    return;
  }

  assert(StringValid(body));
  printf("Hypermedia control: %s %s -> %ld (%d bytes)\n",
         HyperMethodName(method), url.data, status, body.len);

  // A failed request has no response worth swapping in - showing the error
  // body in place of the content would be worse than leaving what's there.
  if (status >= 400) {
    String msg;
    StringFormat(&s->scratch_arena, &msg, "%s %ld", HyperMethodName(method),
                 status);
    UpdateNotification(s, msg);
    return;
  }

  bool documentReplaced = ApplyHyperSwap(
      s, swap, target, body, (method == HYPER_METHOD_GET) ? url.data : NULL);
  if (documentReplaced) {
    // The load posts its own notification, and `url`/`body` point into a
    // scratch_arena that LoadHypermediaDocument* has already reset.
    return;
  }

  String msg;
  StringFormat(&s->scratch_arena, &msg, "%s %ld", HyperMethodName(method),
               status);
  UpdateNotification(s, msg);
}

static void FireHyperLoadTriggers(State *s) {
  assert(s != NULL);
  assert(s->numElements >= 0 && s->numElements <= MAX_ELEMENTS);
  assert(g_hyperLoadDepth >= 0);

  if (g_hyperLoadDepth > 0) {
    return;
  }
  g_hyperLoadDepth++;

  int generation = s->documentGeneration;
  for (int i = 0; i < s->numElements; i++) {
    Element *e = &s->elements[i];
    if (e->control == NULL || e->control->trigger != HYPER_TRIGGER_LOAD) {
      continue;
    }
    FireHyperControl(s, e);
    if (s->documentGeneration != generation) {
      // The control swapped in a different document: `s->elements` is a
      // different array of elements now and this loop's index means nothing.
      break;
    }
  }

  g_hyperLoadDepth--;
  assert(g_hyperLoadDepth == 0);
}

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_HYPERMEDIA_CONTROLS_H
