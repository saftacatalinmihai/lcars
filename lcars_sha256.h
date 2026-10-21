#ifndef LCARS_SHA256_H
#define LCARS_SHA256_H

// SHA-256 (FIPS 180-4), for the vault's write guard (lcars_vault.h): the
// server keeps the hash of the vault token, never the token. The server has
// no crypto library of its own - libcurl's OpenSSL is in the static link but
// not in the dynamic one's, and one hash is not worth a new dependency for
// the release build - so this is the standard's algorithm, written out.
// test/classified.py compiles this file alone and checks it against the
// NIST vectors (the empty string, "abc", the 448-bit message and a million
// 'a's, which crosses many blocks and the length's high byte).
//
// Header-only like the rest: declarations always, bodies under
// LCARS_SHA256_IMPLEMENTATION (defined by lcars_http.h's implementation
// block, or by the test's harness).

#include <stddef.h>
#include <stdint.h>

#define SHA256_DIGEST_BYTES 32

typedef struct Sha256 {
  uint32_t h[8];
  uint64_t len; // bytes hashed so far
  uint8_t block[64];
  size_t used; // bytes waiting in block
} Sha256;

static void Sha256Init(Sha256 *s);
static void Sha256Update(Sha256 *s, const void *data, size_t n);
static void Sha256Final(Sha256 *s, uint8_t out[SHA256_DIGEST_BYTES]);
// The digest of n bytes as 64 lowercase hex characters and a terminator.
static void Sha256Hex(const void *data, size_t n, char out[65]);

#ifdef LCARS_SHA256_IMPLEMENTATION

#include <assert.h>
#include <string.h>

static const uint32_t sha256_k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

static uint32_t sha256_rotr(uint32_t x, int n) {
  return (x >> n) | (x << (32 - n));
}

static void Sha256Block(Sha256 *s, const uint8_t *p) {
  uint32_t w[64];
  for (int i = 0; i < 16; i++) {
    w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 |
           (uint32_t)p[4 * i + 2] << 8 | (uint32_t)p[4 * i + 3];
  }
  for (int i = 16; i < 64; i++) {
    uint32_t s0 = sha256_rotr(w[i - 15], 7) ^ sha256_rotr(w[i - 15], 18) ^
                  (w[i - 15] >> 3);
    uint32_t s1 = sha256_rotr(w[i - 2], 17) ^ sha256_rotr(w[i - 2], 19) ^
                  (w[i - 2] >> 10);
    w[i] = w[i - 16] + s0 + w[i - 7] + s1;
  }
  uint32_t a = s->h[0], b = s->h[1], c = s->h[2], d = s->h[3];
  uint32_t e = s->h[4], f = s->h[5], g = s->h[6], h = s->h[7];
  for (int i = 0; i < 64; i++) {
    uint32_t S1 = sha256_rotr(e, 6) ^ sha256_rotr(e, 11) ^ sha256_rotr(e, 25);
    uint32_t ch = (e & f) ^ (~e & g);
    uint32_t t1 = h + S1 + ch + sha256_k[i] + w[i];
    uint32_t S0 = sha256_rotr(a, 2) ^ sha256_rotr(a, 13) ^ sha256_rotr(a, 22);
    uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
    uint32_t t2 = S0 + maj;
    h = g;
    g = f;
    f = e;
    e = d + t1;
    d = c;
    c = b;
    b = a;
    a = t1 + t2;
  }
  s->h[0] += a;
  s->h[1] += b;
  s->h[2] += c;
  s->h[3] += d;
  s->h[4] += e;
  s->h[5] += f;
  s->h[6] += g;
  s->h[7] += h;
}

static void Sha256Init(Sha256 *s) {
  assert(s != NULL);
  static const uint32_t iv[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372,
                                 0xa54ff53a, 0x510e527f, 0x9b05688c,
                                 0x1f83d9ab, 0x5be0cd19};
  memcpy(s->h, iv, sizeof(iv));
  s->len = 0;
  s->used = 0;
}

static void Sha256Update(Sha256 *s, const void *data, size_t n) {
  assert(s != NULL);
  assert(data != NULL || n == 0);
  const uint8_t *p = (const uint8_t *)data;
  s->len += n;
  while (n > 0) {
    size_t take = 64 - s->used;
    if (take > n) {
      take = n;
    }
    memcpy(s->block + s->used, p, take);
    s->used += take;
    p += take;
    n -= take;
    if (s->used == 64) {
      Sha256Block(s, s->block);
      s->used = 0;
    }
  }
}

static void Sha256Final(Sha256 *s, uint8_t out[SHA256_DIGEST_BYTES]) {
  assert(s != NULL && out != NULL);
  uint64_t bits = s->len * 8;
  // The 0x80 marker, zeros to 56 mod 64, the length as 64 bits big-endian:
  // a second block when the marker leaves no room for the length.
  s->block[s->used++] = 0x80;
  if (s->used > 56) {
    memset(s->block + s->used, 0, 64 - s->used);
    Sha256Block(s, s->block);
    s->used = 0;
  }
  memset(s->block + s->used, 0, 56 - s->used);
  for (int i = 0; i < 8; i++) {
    s->block[56 + i] = (uint8_t)(bits >> (56 - 8 * i));
  }
  Sha256Block(s, s->block);
  for (int i = 0; i < 8; i++) {
    out[4 * i] = (uint8_t)(s->h[i] >> 24);
    out[4 * i + 1] = (uint8_t)(s->h[i] >> 16);
    out[4 * i + 2] = (uint8_t)(s->h[i] >> 8);
    out[4 * i + 3] = (uint8_t)s->h[i];
  }
}

static void Sha256Hex(const void *data, size_t n, char out[65]) {
  assert(out != NULL);
  Sha256 s;
  uint8_t d[SHA256_DIGEST_BYTES];
  Sha256Init(&s);
  Sha256Update(&s, data, n);
  Sha256Final(&s, d);
  static const char hex[] = "0123456789abcdef";
  for (int i = 0; i < SHA256_DIGEST_BYTES; i++) {
    out[2 * i] = hex[d[i] >> 4];
    out[2 * i + 1] = hex[d[i] & 15];
  }
  out[64] = '\0';
}

#endif // LCARS_SHA256_IMPLEMENTATION

#endif // LCARS_SHA256_H
