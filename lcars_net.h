#ifndef LCARS_NET_H
#define LCARS_NET_H

// Blocking HTTP client, shared by the two things in this app that talk to a
// server: loading a hypermedia document over http(s) (lcars_hypermedia.h)
// and firing a hypermedia control at a remote URL
// (lcars_hypermedia_controls.h). Both run on the UI thread and both stall
// the frame until curl returns - acceptable for a single-user app clicking
// a link, and unchanged from how document loading always behaved, but it is
// why CURLOPT_TIMEOUT is set aggressively low.

#include "lcars_arena.h"
#include "lcars_string.h"

#include <curl/curl.h>

// Growable response buffer curl writes into. `arena` is where the growth
// comes from; `data` is always NUL-terminated at `size`.
struct CurlMemoryBuffer {
  char *data;
  size_t size;
  Arena *arena;
};

static size_t CurlWriteMemoryCallback(void *contents, size_t size, size_t nmemb,
                                      void *userp);
static bool NetHttpRequest(Arena *arena, const char *method, const char *url,
                           String body, const char *contentType,
                           String *outBody, long *outStatus);

#ifdef LCARS_IMPLEMENTATION

static size_t CurlWriteMemoryCallback(void *contents, size_t size, size_t nmemb,
                                      void *userp) {
  size_t realsize = size * nmemb;
  struct CurlMemoryBuffer *mem = (struct CurlMemoryBuffer *)userp;
  assert(mem != NULL);
  assert(mem->arena != NULL);
  // NetHttpRequest() seeds this with a 1-byte allocation before handing the
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

// Performs one blocking HTTP request and returns the response body in
// *outBody (allocated from `arena`) and the status code in *outStatus.
//
// The return value reports whether the *transport* worked, not whether the
// server was happy: a 404 or a 500 still returns true with the body and
// status filled in, because a control's error swap wants both. Only a curl
// failure (DNS, connect, timeout, TLS) returns false, with an empty body and
// a status of 0. Deliberately no CURLOPT_FAILONERROR for the same reason -
// callers that need the old "any 4xx/5xx is a failure" behavior check
// *outStatus themselves.
//
// `body` is sent as-is when non-empty (with `contentType`, if given); GET
// requests normally pass an empty body.
static bool NetHttpRequest(Arena *arena, const char *method, const char *url,
                           String body, const char *contentType,
                           String *outBody, long *outStatus) {
  assert(arena_valid(arena));
  assert(method != NULL);
  assert(url != NULL); // handed to curl as CURLOPT_URL
  assert(StringValid(body));
  assert(outBody != NULL);
  assert(outStatus != NULL);

  *outBody = StringInit(arena, "");
  *outStatus = 0;

  CURL *curl = curl_easy_init();
  if (!curl) {
    printf("HTTP request failed: curl_easy_init() returned NULL\n");
    return false;
  }

  struct CurlMemoryBuffer chunk;
  chunk.arena = arena;
  chunk.data = arena_alloc(arena, 1);
  chunk.size = 0;
  chunk.data[0] = '\0';

  struct curl_slist *headers = NULL;
  curl_easy_setopt(curl, CURLOPT_URL, url);
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, CurlWriteMemoryCallback);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
  curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);
  if (strcmp(method, "GET") != 0) {
    curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, method);
  }
  if (body.len > 0 && body.data != NULL) {
    // POSTFIELDS does not copy: `body` lives in the caller's arena and must
    // (and does) outlive curl_easy_perform below.
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.data);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)body.len);
    if (contentType != NULL) {
      char headerBuf[256];
      snprintf(headerBuf, sizeof(headerBuf), "Content-Type: %s", contentType);
      headers = curl_slist_append(headers, headerBuf);
    }
  }
  if (headers != NULL) {
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
  }

  CURLcode res = curl_easy_perform(curl);
  long status = 0;
  curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
  if (headers != NULL) {
    curl_slist_free_all(headers);
  }
  curl_easy_cleanup(curl);

  if (res != CURLE_OK) {
    printf("HTTP %s %s failed: %s\n", method, url, curl_easy_strerror(res));
    return false;
  }

  outBody->data = chunk.data;
  outBody->len = (int)chunk.size;
  outBody->is_static = false;
  *outStatus = status;

  assert(StringValid(*outBody));
  return true;
}

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_NET_H
