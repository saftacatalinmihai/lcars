#ifndef LCARS_CURL_CA_H
#define LCARS_CURL_CA_H

// Where a static build's libcurl finds the CA certificates.
//
// A libcurl built for the host knows its distro's CA bundle: Debian's
// libcurl was configured with /etc/ssl/certs/ca-certificates.crt, Fedora's
// with its own. The release binary (make lcars-static, linked against
// Alpine's static libcurl and musl) carries Alpine's path, and runs on any
// Linux: on Fedora or openSUSE that file does not exist, and every HTTPS
// call (Deepgram, Strava, the embedder, the CLI's server) would fail
// certificate verification. So under LCARS_STATIC each handle is pointed at
// the first bundle that exists here, as curl's own configure probes for one,
// with SSL_CERT_FILE (OpenSSL's variable, which a person behind a corporate
// proxy already sets) winning. None found: curl's built-in default stands,
// and its error names the problem.
//
// Every other build is a no-op: the VPS and the dynamic builds keep the
// default their libcurl was built with, exactly as before. Asked per handle
// (a handful of access() calls) rather than cached: there is no state to
// share between the server's threads, and a bundle installed while the
// server runs is found.
//
// Both programs include it (lcars_http.h, lcars_cli.h); in lcars-one each
// translation unit has its own copy, being static.

#include <curl/curl.h>

#ifdef LCARS_STATIC

#include <stdlib.h>
#include <unistd.h>

static const char *const g_ca_bundles[] = {
    "/etc/ssl/certs/ca-certificates.crt", // Debian, Ubuntu, Alpine, Arch
    "/etc/pki/tls/certs/ca-bundle.crt",   // Fedora, RHEL, CentOS
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem", // RHEL 7+, its source
    "/etc/ssl/ca-bundle.pem",                            // openSUSE, SLES
    "/etc/ssl/cert.pem",                                 // Alpine's other, Void
};

static void LcarsCurlCA(CURL *curl) {
  if (curl == NULL) {
    return;
  }
  const char *env = getenv("SSL_CERT_FILE");
  if (env != NULL && env[0] != '\0') {
    curl_easy_setopt(curl, CURLOPT_CAINFO, env);
    return;
  }
  for (size_t i = 0; i < sizeof(g_ca_bundles) / sizeof(g_ca_bundles[0]); i++) {
    if (access(g_ca_bundles[i], R_OK) == 0) {
      curl_easy_setopt(curl, CURLOPT_CAINFO, g_ca_bundles[i]);
      return;
    }
  }
}

#else
#define LcarsCurlCA(curl) ((void)(curl))
#endif

#endif // LCARS_CURL_CA_H
