#ifndef LCARS_SAY_H
#define LCARS_SAY_H

// POST /say - text to speech, for the deck's crew: a voice of their own
// rather than the browser's speechSynthesis, which on Linux is a robot.
//
//   GET  /say                     {"provider":"deepgram"}, or 503 when off
//   POST /say {"text","voice"}    audio/mpeg, chunked, as the provider makes it
//   POST /say {...,"format":"pcm"} the same as raw 16-bit mono PCM at 24kHz,
//                                 little-endian, no header (audio/L16): what
//                                 the deck plays chunk by chunk as it comes
//   GET  /say/token               {"access_token","expires_in"}: a Deepgram
//                                 key good for about 30 seconds, for the
//                                 page's own listening socket; 503 with no
//                                 DEEPGRAM_API_KEY
//
// The speech is not made here. The request is relayed to a hosted
// text-to-speech service over curl, and its answer is passed on chunk by
// chunk as it arrives, so the first words play while the rest is still
// being spoken into being - the whole point, since a reply of five sentences
// made in one piece is two or three seconds of silence first. Which service
// is chosen by the server's environment:
//
//   LCARS_TTS=deepgram     Deepgram's Aura-2 (/v1/speak), DEEPGRAM_API_KEY.
//                          The default: unset, it is chosen whenever that
//                          key is there (the captain's choice of voice)
//   LCARS_TTS=elevenlabs   ElevenLabs' streaming endpoint with the
//                          low-latency Flash model, ELEVENLABS_API_KEY
//   LCARS_TTS=off, or      off: both routes answer 503, and the page speaks
//   no key                 with speechSynthesis as it always did
//
// The key never leaves this process: the page names a voice, this adds the
// key. `voice` is the provider's own name for one (an Aura-2 model such as
// aura-2-thalia-en, an ElevenLabs voice id) - which voices the page uses is
// the page's business, and GET /say tells it whose names to use. It goes into
// the provider's URL, so only [A-Za-z0-9_-] is accepted.
//
// Nothing the provider says is trusted: a refusal (a bad key, an unknown
// voice, a quota) is answered as a 502 with the provider's status and the
// start of its message, before any audio header has gone out. A failure
// after the audio has started can only end the stream short, which the page
// hears as the voice stopping. A client that hangs up (a new reply, the
// sheet closed) ends the relay at once, as /chat does: the socket is watched
// for POLLRDHUP between chunks, and from curl's progress callback while the
// provider is still thinking.
//
// POST /transcribe is the one exception to that (the G2 glasses' route,
// below): a voice note recorded whole and posted as raw PCM, relayed to
// Deepgram's pre-recorded /v1/listen with the same DEEPGRAM_API_KEY, and
// answered as text. One request, one answer - no stream to hold open.
//
// The other way round - the captain speaking to the crew - the audio does
// not come through here at all: the page streams it straight to Deepgram's
// /v1/listen over a WebSocket, which this server has no client for and
// should not relay (a held connection thread per press, and the latency of
// a second hop). What the page lacks is a key, and the long-lived one must
// not be in a browser. So GET /say/token asks Deepgram's /v1/auth/grant
// for a short-lived one (a JWT, SAY_GRANT_TTL_SECONDS) and hands that over:
// the page fetches one per press and opens its socket with it at once.
// The token only has to be good when the socket opens - an open stream
// outlives it. It is a key for spending money, so the limited logins may
// not have one (lcars_logins.h). It depends on DEEPGRAM_API_KEY alone, not
// on LCARS_TTS: which voice the crew speak in and whether the captain can be
// heard are separate choices.
//
// A module of lcars_http.h, after lcars_chat.h (POLLRDHUP), included from
// inside its LCARS_HTTP_IMPLEMENTATION block.

static void SayInit(void);
static int HandleSay(int client_fd, Arena *arena, const char *method,
                     const char *body, const char *content_type);
static int HandleSayToken(int client_fd, Arena *arena, const char *method);
static int HandleTranscribe(int client_fd, Arena *arena, const char *body,
                            int content_len, const char *content_type);

#ifdef LCARS_SAY_IMPLEMENTATION

#include <curl/curl.h>
#include <stdatomic.h>

// The text of one request, in bytes. Deepgram refuses more than 2000
// characters; a reply worth speaking is far shorter, and the page cuts a
// long one at a sentence before this.
#define SAY_TEXT_MAX 2000
#define SAY_VOICE_MAX 64
// Requests relayed at once. Each holds a connection thread, and each costs
// money: a page stops the one playing before asking for the next, so more
// than a few is a page gone wrong rather than a crew talking over each other.
#define SAY_MAX_CONCURRENT 3
// How much of a refusal's body is kept to quote back.
#define SAY_ERR_BODY_MAX 512
#define SAY_CONNECT_TIMEOUT_SECONDS 5L
// A whole answer. Speech streams several times faster than it plays, so
// two minutes is far past any text SAY_TEXT_MAX allows.
#define SAY_TIMEOUT_SECONDS 120L
// A provider that goes this long without a byte has stalled.
#define SAY_STALL_SECONDS 15L

#define SAY_DEEPGRAM_URL "https://api.deepgram.com/v1/speak"
#define SAY_DEEPGRAM_VOICE "aura-2-thalia-en"
#define SAY_ELEVENLABS_URL "https://api.elevenlabs.io/v1/text-to-speech/"
#define SAY_ELEVENLABS_MODEL "eleven_flash_v2_5"
#define SAY_ELEVENLABS_VOICE "EXAVITQu4vr4xnSDxMaL" // "Sarah", a premade
// The raw PCM of {"format":"pcm"}. mp3 cannot be played until it is whole
// (decodeAudioData wants a complete file, and MediaSource is missing on
// older iPhones), and Deepgram makes a sentence only two or three times
// faster than it plays: seven seconds of speech take 2.5s to arrive whole,
// where its first quarter second is in after 0.6s. PCM has no frames to
// wait for - any run of samples plays at once - at about 48KB a second,
// which any phone's link carries.
#define SAY_PCM_RATE 24000
#define SAY_PCM_TYPE "audio/L16;rate=24000;channels=1"
#define SAY_GRANT_URL "https://api.deepgram.com/v1/auth/grant"
// How long a minted listening token is good for. Deepgram's default is 30s,
// its ceiling an hour; it only has to last from the fetch to the socket's
// handshake, so the default is plenty and a leaked one is soon worthless.
#define SAY_GRANT_TTL_SECONDS 30
// Deepgram's answer to a grant: a JWT of a few hundred bytes and a number.
#define SAY_GRANT_BODY_MAX 8192
#define SAY_GRANT_TOKEN_MAX 4096
#define SAY_GRANT_TIMEOUT_SECONDS 10L
// POST /transcribe's model, and how it is asked: the body is headerless PCM,
// so its shape goes in the query. smart_format punctuates and capitalises,
// which a journal entry wants.
#define SAY_LISTEN_QUERY                                                       \
  "/v1/listen?model=nova-3&smart_format=true&encoding=linear16"                \
  "&sample_rate=16000&channels=1"
// Deepgram's answer to a voice note: the transcript plus a word list with a
// time and confidence each, ~150 bytes a word - 16 seconds of speech is well
// under this.
#define SAY_LISTEN_BODY_MAX (256 * 1024)
#define SAY_LISTEN_TIMEOUT_SECONDS 30L

typedef enum { SAY_OFF, SAY_DEEPGRAM, SAY_ELEVENLABS } SayProvider;

static struct {
  SayProvider provider;
  // The provider's auth header, whole ("Authorization: Token ..."), so the
  // key is formatted once and never again.
  char auth[256];
  // Deepgram's, for GET /say/token and POST /transcribe, set whenever
  // DEEPGRAM_API_KEY is usable - whatever LCARS_TTS chose to speak with.
  // Empty: no token, no transcription.
  char grant_auth[256];
  // Where /v1/listen is: https://api.deepgram.com, or $LCARS_DEEPGRAM_URL
  // (test/transcribe.py's stand-in).
  char listen_base[256];
  atomic_int live;
} g_say;

static const char *SayProviderName(SayProvider p) {
  return p == SAY_DEEPGRAM     ? "deepgram"
         : p == SAY_ELEVENLABS ? "elevenlabs"
                               : "off";
}

// A key with a newline or a quote in it would split the header; no
// provider issues one, so it is refused rather than escaped.
static bool SayKeyOk(const char *key) {
  bool ok = key && key[0] && strlen(key) < 200;
  for (const char *c = key; ok && *c; c++) {
    ok = *c > ' ' && *c < 127;
  }
  return ok;
}

// Reads the environment once, at startup, before any connection exists.
static void SayInit(void) {
  const char *which = getenv("LCARS_TTS");
  g_say.provider = SAY_OFF;
  g_say.auth[0] = '\0';
  g_say.grant_auth[0] = '\0';
  atomic_init(&g_say.live, 0);
  const char *base = getenv("LCARS_DEEPGRAM_URL");
  snprintf(g_say.listen_base, sizeof(g_say.listen_base), "%s",
           base && base[0] ? base : "https://api.deepgram.com");
  const char *grant = getenv("DEEPGRAM_API_KEY");
  if (SayKeyOk(grant)) {
    int n = snprintf(g_say.grant_auth, sizeof(g_say.grant_auth),
                     "Authorization: Token %s", grant);
    assert(n > 0 && (size_t)n < sizeof(g_say.grant_auth));
    (void)n;
    // Before any connection thread can call curl_easy_init, which would
    // otherwise do this lazily (and, in older libcurl, not thread-safely).
    curl_global_init(CURL_GLOBAL_DEFAULT);
    printf("Say: listening tokens and transcription from deepgram\n");
  }
  if (!which || !which[0]) {
    const char *dg = getenv("DEEPGRAM_API_KEY");
    if (!dg || !dg[0]) {
      printf("Say: off (no DEEPGRAM_API_KEY, LCARS_TTS unset)\n");
      return;
    }
    which = "deepgram";
  }
  if (strcmp(which, "off") == 0) {
    printf("Say: off (LCARS_TTS=off)\n");
    return;
  }
  SayProvider p = strcmp(which, "deepgram") == 0     ? SAY_DEEPGRAM
                  : strcmp(which, "elevenlabs") == 0 ? SAY_ELEVENLABS
                                                     : SAY_OFF;
  if (p == SAY_OFF) {
    printf("Say: off (LCARS_TTS=%s is neither deepgram nor elevenlabs)\n",
           which);
    return;
  }
  const char *env =
      p == SAY_DEEPGRAM ? "DEEPGRAM_API_KEY" : "ELEVENLABS_API_KEY";
  const char *key = getenv(env);
  if (!SayKeyOk(key)) {
    printf("Say: off (LCARS_TTS=%s but no usable %s)\n", which, env);
    return;
  }
  int n = p == SAY_DEEPGRAM
              ? snprintf(g_say.auth, sizeof(g_say.auth),
                         "Authorization: Token %s", key)
              : snprintf(g_say.auth, sizeof(g_say.auth), "xi-api-key: %s", key);
  assert(n > 0 && (size_t)n < sizeof(g_say.auth));
  (void)n;
  // See above; a second call only counts up.
  curl_global_init(CURL_GLOBAL_DEFAULT);
  g_say.provider = p;
  printf("Say: speaking with %s\n", SayProviderName(p));
}

// One relay, shared by curl's callbacks.
typedef struct SayRelay {
  CURL *curl;
  int client_fd;
  bool started;     // the 200 and its headers have gone to the client
  bool refused;     // the provider answered something other than 200
  bool client_gone; // the client hung up, or a send to it failed
  long http;
  const char *type; // what the audio goes out as
  HTTPBodyStream *s;
  char err[SAY_ERR_BODY_MAX + 1];
  size_t err_len;
} SayRelay;

// Whether the client has hung up. The request is fully read, so anything
// on its half of the socket now is it going away. See lcars_chat.h on
// POLLRDHUP without glibc.
static bool SayClientGone(int fd) {
  struct pollfd p = {fd, POLLRDHUP, 0};
  return poll(&p, 1, 0) > 0 && (p.revents & (POLLRDHUP | POLLHUP | POLLERR));
}

static size_t SayCurlWrite(char *data, size_t size, size_t nmemb, void *user) {
  SayRelay *r = (SayRelay *)user;
  assert(r != NULL && r->s != NULL);
  size_t n = size * nmemb;
  if (!r->started && !r->refused) {
    // The first bytes of the body: the provider's status is known now, and
    // decides whether this is audio to pass on or an error to quote.
    curl_easy_getinfo(r->curl, CURLINFO_RESPONSE_CODE, &r->http);
    if (r->http == 200) {
      HTTPStreamBegin(r->s, r->client_fd, 200, r->type,
                      "Cache-Control: no-store\r\n", false, NULL, 0);
      r->started = true;
    } else {
      r->refused = true;
    }
  }
  if (r->refused) {
    size_t take =
        n < SAY_ERR_BODY_MAX - r->err_len ? n : SAY_ERR_BODY_MAX - r->err_len;
    memcpy(r->err + r->err_len, data, take);
    r->err_len += take;
    r->err[r->err_len] = '\0';
    return n;
  }
  if (SayClientGone(r->client_fd)) {
    r->client_gone = true;
    return 0; // curl ends the transfer with CURLE_WRITE_ERROR
  }
  // Straight to the wire, not through HTTPStreamWrite: that coalesces into
  // 64KB chunks, and the first 64KB of speech is several seconds of it.
  HTTPStreamSendChunk(r->s, (const unsigned char *)data, n);
  r->s->raw_bytes += n;
  if (r->s->failed) {
    r->client_gone = true;
    return 0;
  }
  return n;
}

// Called by curl about once a second even while nothing arrives - so a
// client that leaves before the first audio ends the request too.
static int SayCurlProgress(void *user, curl_off_t dltotal, curl_off_t dlnow,
                           curl_off_t ultotal, curl_off_t ulnow) {
  (void)dltotal;
  (void)dlnow;
  (void)ultotal;
  (void)ulnow;
  SayRelay *r = (SayRelay *)user;
  assert(r != NULL);
  if (SayClientGone(r->client_fd)) {
    r->client_gone = true;
    return 1; // abort: CURLE_ABORTED_BY_CALLBACK
  }
  return 0;
}

// Whether a voice name can go into the provider's URL as it is.
static bool SayVoiceOk(const char *v) {
  size_t n = strlen(v);
  if (n == 0 || n > SAY_VOICE_MAX) {
    return false;
  }
  for (const char *c = v; *c; c++) {
    if (!isalnum((unsigned char)*c) && *c != '-' && *c != '_') {
      return false;
    }
  }
  return true;
}

static int SayRelayText(int client_fd, Arena *arena, const char *text,
                        const char *voice, bool pcm) {
  assert(client_fd >= 0);
  assert(text != NULL && voice != NULL);
  assert(g_say.provider != SAY_OFF);

  char url[256];
  JSONBuf req;
  jsonbuf_init(&req, arena);
  jsonbuf_append(&req, "{\"text\":");
  jsonbuf_append_json_string(&req, text);
  if (g_say.provider == SAY_DEEPGRAM) {
    // mp3, so every browser plays it as it is; Deepgram's default would be
    // too, but saying so keeps a change of default from breaking the page.
    // PCM bare: container=none, or a WAV header leads the stream.
    if (pcm) {
      snprintf(url, sizeof(url),
               "%s?model=%s&encoding=linear16&container=none&sample_rate=%d",
               SAY_DEEPGRAM_URL, voice, SAY_PCM_RATE);
    } else {
      snprintf(url, sizeof(url), "%s?model=%s&encoding=mp3", SAY_DEEPGRAM_URL,
               voice);
    }
  } else {
    // optimize_streaming_latency is deprecated; Flash is the low-latency
    // model, and 44.1kHz/128k mp3 the format every browser plays.
    snprintf(url, sizeof(url), "%s%s/stream?output_format=%s",
             SAY_ELEVENLABS_URL, voice, pcm ? "pcm_24000" : "mp3_44100_128");
    jsonbuf_append(&req, ",\"model_id\":\"" SAY_ELEVENLABS_MODEL "\"");
  }
  jsonbuf_append(&req, "}");
  if (req.overflow) {
    return SendJSONError(client_fd, 413, "Text does not fit");
  }

  CURL *curl = curl_easy_init();
  if (!curl) {
    return SendJSONError(client_fd, 503, "curl_easy_init failed");
  }
  LcarsCurlCA(curl); // a static build's CA bundle (lcars_curl_ca.h)
  HTTPBodyStream s;
  SayRelay r;
  memset(&r, 0, sizeof(r));
  r.curl = curl;
  r.client_fd = client_fd;
  r.s = &s;
  r.type = pcm ? SAY_PCM_TYPE : "audio/mpeg";
  struct curl_slist *headers =
      curl_slist_append(NULL, "Content-Type: application/json");
  headers =
      curl_slist_append(headers, pcm ? "Accept: */*" : "Accept: audio/mpeg");
  headers = curl_slist_append(headers, g_say.auth);
  curl_easy_setopt(curl, CURLOPT_URL, url);
  curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDS, req.data);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)req.len);
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, SayCurlWrite);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, &r);
  curl_easy_setopt(curl, CURLOPT_XFERINFOFUNCTION, SayCurlProgress);
  curl_easy_setopt(curl, CURLOPT_XFERINFODATA, &r);
  curl_easy_setopt(curl, CURLOPT_NOPROGRESS, 0L);
  curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, SAY_CONNECT_TIMEOUT_SECONDS);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, SAY_TIMEOUT_SECONDS);
  curl_easy_setopt(curl, CURLOPT_LOW_SPEED_LIMIT, 1L);
  curl_easy_setopt(curl, CURLOPT_LOW_SPEED_TIME, SAY_STALL_SECONDS);
  // Off the main thread: no SIGALRM for DNS timeouts (see lcars_embed.h).
  curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
  CURLcode rc = curl_easy_perform(curl);
  if (r.http == 0) {
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &r.http);
  }
  curl_slist_free_all(headers);
  curl_easy_cleanup(curl);

  if (r.started) {
    // The audio has begun, so a failure can only cut it short: no final
    // chunk, and the client sees a truncated transfer.
    bool complete = rc == CURLE_OK && !r.client_gone;
    if (!complete && !r.client_gone) {
      printf("Say: %s stopped mid-speech: %s\n",
             SayProviderName(g_say.provider), curl_easy_strerror(rc));
    }
    HTTPStreamEnd(&s, complete);
    return 200;
  }
  if (r.client_gone) {
    g_conn_keep_alive = false;
    return 499; // nginx's "client closed request"; only ever logged
  }
  if (r.refused || (rc == CURLE_OK && r.http != 200)) {
    // The provider's message is quoted back, since "401" alone does not say
    // whether the key or the voice was wrong. Sanitised to printable ASCII:
    // it goes into a JSON string by way of a format.
    for (size_t i = 0; i < r.err_len; i++) {
      if (r.err[i] < ' ' || r.err[i] > '~' || r.err[i] == '"' ||
          r.err[i] == '\\') {
        r.err[i] = ' ';
      }
    }
    printf("Say: %s refused (HTTP %ld): %.200s\n",
           SayProviderName(g_say.provider), r.http, r.err);
    return SendJSONError(client_fd, 502, "%s answered HTTP %ld: %.200s",
                         SayProviderName(g_say.provider), r.http, r.err);
  }
  if (rc == CURLE_OK) {
    // 200 with an empty body: nothing to say, said.
    return SendHTTPResponse(client_fd, 200, r.type, "", 0);
  }
  printf("Say: %s unreachable: %s\n", SayProviderName(g_say.provider),
         curl_easy_strerror(rc));
  return SendJSONError(client_fd, 502, "%s unreachable: %s",
                       SayProviderName(g_say.provider), curl_easy_strerror(rc));
}

static int HandleSay(int client_fd, Arena *arena, const char *method,
                     const char *body, const char *content_type) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(method != NULL);

  bool get = strcmp(method, "GET") == 0;
  if (!get && strcmp(method, "POST") != 0) {
    return SendJSONError(client_fd, 405, "Method %s not allowed on /say",
                         method);
  }
  if (g_say.provider == SAY_OFF) {
    return SendJSONError(client_fd, 503,
                         "No voice on this server (LCARS_TTS and its key)");
  }
  if (get) {
    char out[64];
    int n = snprintf(out, sizeof(out), "{\"provider\":\"%s\"}",
                     SayProviderName(g_say.provider));
    assert(n > 0 && (size_t)n < sizeof(out));
    return SendJSON(client_fd, 200, out, (size_t)n);
  }
  if (!content_type || strncmp(content_type, "application/json", 16) != 0) {
    return SendJSONError(client_fd, 415,
                         "POST /say takes JSON: {\"text\",\"voice\"}");
  }
  char *text = NULL, *voice = NULL, *format = NULL;
  if (!body || !json_get_string_arena(arena, body, "text", &text) || !text ||
      !text[0]) {
    return SendJSONError(client_fd, 400, "Missing 'text'");
  }
  if (strlen(text) > SAY_TEXT_MAX) {
    return SendJSONError(client_fd, 413, "'text' is over %d bytes",
                         SAY_TEXT_MAX);
  }
  if (!json_get_string_arena(arena, body, "voice", &voice) || !voice ||
      !voice[0]) {
    voice = g_say.provider == SAY_DEEPGRAM ? SAY_DEEPGRAM_VOICE
                                           : SAY_ELEVENLABS_VOICE;
  }
  if (!SayVoiceOk(voice)) {
    return SendJSONError(client_fd, 400,
                         "'voice' is a provider's voice name: [A-Za-z0-9_-], "
                         "at most %d",
                         SAY_VOICE_MAX);
  }
  bool pcm = false;
  if (json_get_string_arena(arena, body, "format", &format) && format &&
      format[0]) {
    pcm = strcmp(format, "pcm") == 0;
    if (!pcm && strcmp(format, "mp3") != 0) {
      return SendJSONError(client_fd, 400, "'format' is mp3 or pcm");
    }
  }
  if (atomic_fetch_add(&g_say.live, 1) >= SAY_MAX_CONCURRENT) {
    atomic_fetch_sub(&g_say.live, 1);
    return SendJSONError(client_fd, 429, "Already speaking %d replies",
                         SAY_MAX_CONCURRENT);
  }
  int status = SayRelayText(client_fd, arena, text, voice, pcm);
  atomic_fetch_sub(&g_say.live, 1);
  return status;
}

// A provider's whole answer (a grant, a transcript): small, and parsed only
// once complete. In the connection's arena, `cap` bytes plus a terminator.
typedef struct SayAnswer {
  char *body;
  size_t len;
  size_t cap;
  bool overflow;
} SayAnswer;

static void SayAnswerInit(SayAnswer *a, Arena *arena, size_t cap) {
  assert(a != NULL);
  assert(arena_valid(arena));
  a->body = (char *)arena_alloc(arena, cap + 1);
  a->body[0] = '\0';
  a->len = 0;
  a->cap = cap;
  a->overflow = false;
}

static size_t SayAnswerWrite(char *data, size_t size, size_t nmemb,
                             void *user) {
  SayAnswer *a = (SayAnswer *)user;
  assert(a != NULL);
  assert(a->len <= a->cap);
  size_t n = size * nmemb;
  size_t take = n < a->cap - a->len ? n : a->cap - a->len;
  if (take < n) {
    a->overflow = true;
  }
  memcpy(a->body + a->len, data, take);
  a->len += take;
  a->body[a->len] = '\0';
  return n;
}

// A provider's refusal, made fit to quote back inside a JSON error: Deepgram's
// error bodies do not carry the key sent, but may carry anything else.
static void SayAnswerSanitize(SayAnswer *a) {
  for (size_t i = 0; i < a->len; i++) {
    if (a->body[i] < ' ' || a->body[i] > '~' || a->body[i] == '"' ||
        a->body[i] == '\\') {
      a->body[i] = ' ';
    }
  }
}

// Whether a token can go into the answer's JSON string as it is. A JWT is
// three base64url parts joined by dots; anything else is not what was asked
// for, and is not passed on.
static bool SayTokenOk(const char *t) {
  size_t n = strlen(t);
  if (n < 16 || n >= SAY_GRANT_TOKEN_MAX) {
    return false;
  }
  for (const char *c = t; *c; c++) {
    if (!isalnum((unsigned char)*c) && *c != '-' && *c != '_' && *c != '.') {
      return false;
    }
  }
  return true;
}

static int HandleSayToken(int client_fd, Arena *arena, const char *method) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(method != NULL);

  if (strcmp(method, "GET") != 0) {
    return SendJSONError(client_fd, 405, "Method %s not allowed on /say/token",
                         method);
  }
  if (!g_say.grant_auth[0]) {
    return SendJSONError(client_fd, 503,
                         "No listening on this server (DEEPGRAM_API_KEY)");
  }
  CURL *curl = curl_easy_init();
  if (!curl) {
    return SendJSONError(client_fd, 503, "curl_easy_init failed");
  }
  LcarsCurlCA(curl); // a static build's CA bundle (lcars_curl_ca.h)
  SayAnswer answer;
  SayAnswer *g = &answer;
  SayAnswerInit(g, arena, SAY_GRANT_BODY_MAX);
  char req[64];
  int rn =
      snprintf(req, sizeof(req), "{\"ttl_seconds\":%d}", SAY_GRANT_TTL_SECONDS);
  assert(rn > 0 && (size_t)rn < sizeof(req));
  struct curl_slist *headers =
      curl_slist_append(NULL, "Content-Type: application/json");
  headers = curl_slist_append(headers, "Accept: application/json");
  headers = curl_slist_append(headers, g_say.grant_auth);
  curl_easy_setopt(curl, CURLOPT_URL, SAY_GRANT_URL);
  curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDS, req);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)rn);
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, SayAnswerWrite);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, g);
  curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, SAY_CONNECT_TIMEOUT_SECONDS);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, SAY_GRANT_TIMEOUT_SECONDS);
  curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
  CURLcode rc = curl_easy_perform(curl);
  long http = 0;
  curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http);
  curl_slist_free_all(headers);
  curl_easy_cleanup(curl);

  if (rc != CURLE_OK) {
    printf("Say: deepgram grant unreachable: %s\n", curl_easy_strerror(rc));
    return SendJSONError(client_fd, 502, "deepgram unreachable: %s",
                         curl_easy_strerror(rc));
  }
  if (http != 200) {
    // Quoted back as /say quotes a refusal.
    SayAnswerSanitize(g);
    printf("Say: deepgram grant refused (HTTP %ld): %.200s\n", http, g->body);
    return SendJSONError(client_fd, 502, "deepgram answered HTTP %ld: %.200s",
                         http, g->body);
  }
  // Rebuilt rather than passed through: only the two fields the page uses,
  // each checked, so nothing else Deepgram might add reaches the browser.
  char *token = NULL;
  float expires = 0;
  if (g->overflow ||
      !json_get_string_arena(arena, g->body, "access_token", &token) ||
      !token || !SayTokenOk(token)) {
    printf("Say: deepgram grant answered without a usable access_token\n");
    return SendJSONError(client_fd, 502,
                         "deepgram answered without a usable access_token");
  }
  if (!json_get_float(g->body, "expires_in", &expires) || expires <= 0) {
    expires = SAY_GRANT_TTL_SECONDS;
  }
  JSONBuf out;
  jsonbuf_init(&out, arena);
  jsonbuf_append(&out, "{\"access_token\":");
  jsonbuf_append_json_string(&out, token);
  char tail[48];
  snprintf(tail, sizeof(tail), ",\"expires_in\":%d}", (int)expires);
  jsonbuf_append(&out, tail);
  assert(!out.overflow);
  // a credential: no cache, the browser's or a proxy's, may keep it
  return SendHTTPResponseEx(client_fd, 200, "application/json",
                            "Cache-Control: no-store\r\n", out.data, out.len);
}

// POST /transcribe - raw PCM in, text out.
//
// The body is audio, not JSON: 16 kHz, mono, signed 16-bit little-endian,
// which is what the Even Realities G2 microphone emits, so nothing resamples
// on either side. 32,000 bytes per second of speech; HTTP_MAX_BODY_BYTES
// therefore caps one request at about 16 seconds, which is a voice note
// rather than a dictation session.
//
// Deliberately does *not* create an entry. Transcription and creation are
// separate so this route composes with anything, so the insert path (with
// its backdating and validation) is not duplicated here, and - the practical
// reason - so a client can show the user what was heard before committing
// it. POST /entries with the returned text is the second half.
//
// Answers {"text","bytes","duration_ms"}; silence is a 200 with "" as text.
// 503 with no DEEPGRAM_API_KEY, 502 when Deepgram fails or refuses.
static int HandleTranscribe(int client_fd, Arena *arena, const char *body,
                            int content_len, const char *content_type) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(body != NULL || content_len == 0);
  assert(content_len >= 0);

  // Almost certainly a client that meant to post an entry, or one that wrapped
  // the audio in JSON. Saying so beats transcribing the bytes of a JSON
  // document into noise.
  if (content_type != NULL &&
      strncasecmp(content_type, "application/json", 16) == 0) {
    return SendJSONError(client_fd, 415,
                         "Body must be raw PCM (16kHz mono s16le), not JSON");
  }
  if (content_len <= 0) {
    return SendJSONError(client_fd, 400, "Empty body; expected raw PCM audio");
  }
  // Odd length means the client is not sending 16-bit frames, so whatever it
  // is would decode as noise. Runtime input, so checked and reported.
  if ((content_len % 2) != 0) {
    return SendJSONError(
        client_fd, 400, "PCM length %d is not a whole number of 16-bit samples",
        content_len);
  }
  if (!g_say.grant_auth[0]) {
    return SendJSONError(client_fd, 503,
                         "No transcription on this server (DEEPGRAM_API_KEY)");
  }

  CURL *curl = curl_easy_init();
  if (!curl) {
    return SendJSONError(client_fd, 503, "curl_easy_init failed");
  }
  LcarsCurlCA(curl); // a static build's CA bundle (lcars_curl_ca.h)
  SayAnswer a;
  SayAnswerInit(&a, arena, SAY_LISTEN_BODY_MAX);
  char url[sizeof(g_say.listen_base) + sizeof(SAY_LISTEN_QUERY)];
  snprintf(url, sizeof(url), "%s%s", g_say.listen_base, SAY_LISTEN_QUERY);
  struct curl_slist *headers =
      curl_slist_append(NULL, "Content-Type: application/octet-stream");
  headers = curl_slist_append(headers, "Accept: application/json");
  headers = curl_slist_append(headers, g_say.grant_auth);
  curl_easy_setopt(curl, CURLOPT_URL, url);
  curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)content_len);
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, SayAnswerWrite);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, &a);
  curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, SAY_CONNECT_TIMEOUT_SECONDS);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, SAY_LISTEN_TIMEOUT_SECONDS);
  curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
  CURLcode rc = curl_easy_perform(curl);
  long http = 0;
  curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http);
  curl_slist_free_all(headers);
  curl_easy_cleanup(curl);

  if (rc != CURLE_OK) {
    printf("Transcribe: deepgram unreachable: %s\n", curl_easy_strerror(rc));
    return SendJSONError(client_fd, 502, "deepgram unreachable: %s",
                         curl_easy_strerror(rc));
  }
  if (http != 200) {
    SayAnswerSanitize(&a);
    printf("Transcribe: deepgram refused (HTTP %ld): %.200s\n", http, a.body);
    return SendJSONError(client_fd, 502, "deepgram answered HTTP %ld: %.200s",
                         http, a.body);
  }
  // results.channels[0].alternatives[0].transcript; the rest (the words,
  // their times, the model's metadata) is not passed on.
  JsonSpan top = {a.body, a.len}, results, channels, ch, alts, alt, t;
  const char *c1 = NULL, *c2 = NULL;
  if (a.overflow || !json_member(top, "results", &results) ||
      !json_member(results, "channels", &channels) ||
      !json_array_next(channels, &c1, &ch) ||
      !json_member(ch, "alternatives", &alts) ||
      !json_array_next(alts, &c2, &alt) ||
      !json_member(alt, "transcript", &t) || t.len < 2 || t.data[0] != '"') {
    printf("Transcribe: deepgram answered without a transcript\n");
    return SendJSONError(client_fd, 502,
                         "deepgram answered without a transcript");
  }
  const char *text = json_span_string(arena, t);

  JSONBuf out;
  jsonbuf_init(&out, arena);
  jsonbuf_append(&out, "{\"text\":");
  jsonbuf_append_json_string(&out, text);
  // 2 bytes a sample at 16 kHz.
  char tail[64];
  snprintf(tail, sizeof(tail), ",\"bytes\":%d,\"duration_ms\":%d}", content_len,
           content_len / 32);
  jsonbuf_append(&out, tail);
  if (out.overflow) {
    return SendJSONError(client_fd, 500, "Transcript too long to encode");
  }
  return SendJSONBuf(client_fd, &out);
}

#endif // LCARS_SAY_IMPLEMENTATION
#endif // LCARS_SAY_H
