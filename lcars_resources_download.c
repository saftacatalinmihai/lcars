#include "lcars_resources_download.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

#ifdef __EMSCRIPTEN__
#include <emscripten/fetch.h>
#else
#include <curl/curl.h>
#endif

#define BASE_URL "https://public.mihai-safta.dev"

#ifdef __APPLE__
    #define VOSK_LIB_NAME "resources/libvosk.dylib"
#else
    #define VOSK_LIB_NAME "resources/libvosk.so"
#endif

#ifdef __EMSCRIPTEN__
static const char *required_files[] = {
    "resources/earth.png",
    "resources/earth.jpg",
    "resources/style_cyber.rgs",
};
#else
static const char *required_files[] = {
    "resources/earth.png",
    VOSK_LIB_NAME,
    "resources/earth.jpg",
    "resources/style_cyber.rgs",
    "resources/model/README",
    "resources/model/am/final.mdl",
    "resources/model/conf/mfcc.conf",
    "resources/model/conf/model.conf",
    "resources/model/graph/disambig_tid.int",
    "resources/model/graph/Gr.fst",
    "resources/model/graph/HCLr.fst",
    "resources/model/graph/phones/word_boundary.int",
    "resources/model/ivector/final.dubm",
    "resources/model/ivector/final.ie",
    "resources/model/ivector/final.mat",
    "resources/model/ivector/global_cmvn.stats",
    "resources/model/ivector/online_cmvn.conf",
    "resources/model/ivector/splice.conf",
};
#endif

#define NUM_FILES (sizeof(required_files) / sizeof(required_files[0]))

static void create_parent_dirs(const char *path) {
    char tmp[1024];
    size_t len = strlen(path);
    if (len >= sizeof(tmp)) return;
    memcpy(tmp, path, len + 1);

    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            mkdir(tmp, 0755);
            *p = '/';
        }
    }
}

#ifndef __EMSCRIPTEN__


static size_t write_callback(void *ptr, size_t size, size_t nmemb, void *stream) {
    return fwrite(ptr, size, nmemb, (FILE *)stream);
}
#endif

static bool download_file_from_url(const char *url, const char *path) {
    create_parent_dirs(path);

#ifdef __EMSCRIPTEN__
    emscripten_fetch_attr_t attr;
    emscripten_fetch_attr_init(&attr);
    strcpy(attr.requestMethod, "GET");
    attr.attributes = EMSCRIPTEN_FETCH_LOAD_TO_MEMORY | EMSCRIPTEN_FETCH_SYNCHRONOUS;

    emscripten_fetch_t *fetch = emscripten_fetch(&attr, url);
    if (!fetch) {
        printf("  [FAILED] %s - fetch failed\n", url);
        return false;
    }

    bool ok = false;
    if (fetch->status == 200) {
        FILE *f = fopen(path, "wb");
        if (f) {
            fwrite(fetch->data, 1, fetch->numBytes, f);
            fclose(f);
            ok = true;
        } else {
            printf("  [FAILED] cannot write %s\n", path);
        }
    } else {
        printf("  [FAILED] %s - HTTP %d\n", url, fetch->status);
    }

    emscripten_fetch_close(fetch);
    return ok;
#else
    CURL *curl = curl_easy_init();
    if (!curl) {
        printf("  [FAILED] curl_easy_init failed\n");
        return false;
    }

    FILE *fp = fopen(path, "wb");
    if (!fp) {
        printf("  [FAILED] cannot write %s\n", path);
        curl_easy_cleanup(curl);
        return false;
    }

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_callback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, fp);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_FAILONERROR, 1L);

    CURLcode res = curl_easy_perform(curl);

    fclose(fp);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK) {
        printf("  [FAILED] %s - %s\n", url, curl_easy_strerror(res));
        remove(path);
        return false;
    }

    return true;
#endif
}

#ifdef __APPLE__
static bool extract_vosk_dylib_from_jar(void) {
    printf("  [MACOS] Downloading Vosk Java JAR to extract libvosk.dylib...\n");
    const char *jar_url = "https://repo1.maven.org/maven2/com/alphacephei/vosk/0.3.45/vosk-0.3.45.jar";
    const char *jar_path = "resources/vosk-0.3.45.jar";

    if (!download_file_from_url(jar_url, jar_path)) {
        printf("  [FAILED] to download Vosk JAR from Maven Central\n");
        return false;
    }

    printf("  [MACOS] Extracting darwin/libvosk.dylib from JAR...\n");
    char cmd[1024];
    snprintf(cmd, sizeof(cmd), "unzip -o %s darwin/libvosk.dylib -d resources/", jar_path);
    int ret = system(cmd);
    if (ret != 0) {
        printf("  [FAILED] to unzip %s\n", jar_path);
        unlink(jar_path);
        return false;
    }

    // Move resources/darwin/libvosk.dylib to resources/libvosk.dylib
    ret = system("mv resources/darwin/libvosk.dylib resources/libvosk.dylib && rmdir resources/darwin");
    if (ret != 0) {
        printf("  [FAILED] to move libvosk.dylib and cleanup\n");
        unlink(jar_path);
        return false;
    }

    // Run install_name_tool to set dynamic library ID for rpath support on macOS
    printf("  [MACOS] Setting install name ID to @rpath/libvosk.dylib...\n");
    ret = system("install_name_tool -id @rpath/libvosk.dylib resources/libvosk.dylib");
    if (ret != 0) {
        printf("  [WARNING] install_name_tool failed, loading might fail if rpath is not set correctly\n");
    }

    unlink(jar_path);
    return true;
}
#endif

static bool download_file(const char *path) {
#ifdef __APPLE__
    if (strcmp(path, "resources/libvosk.dylib") == 0) {
        return extract_vosk_dylib_from_jar();
    }
#endif

    char url[2048];
    int n = snprintf(url, sizeof(url), BASE_URL "/%s", path);
    if (n < 0 || (size_t)n >= sizeof(url)) return false;

    return download_file_from_url(url, path);
}

bool CheckAndDownloadResources(void) {
    printf("Checking resources...\n");

    bool all_ok = true;

#ifndef __EMSCRIPTEN__
    curl_global_init(CURL_GLOBAL_DEFAULT);
#endif

    for (size_t i = 0; i < NUM_FILES; i++) {
        const char *path = required_files[i];

        if (access(path, F_OK) == 0) {
            printf("  [OK] %s\n", path);
            continue;
        }

        all_ok = false;
        printf("  [MISSING] %s\n", path);

        if (download_file(path)) {
            printf("  [DOWNLOADED] %s\n", path);
        } else {
            printf("  [FAILED] %s\n", path);
        }
    }

#ifndef __EMSCRIPTEN__
    curl_global_cleanup();
#endif

    if (all_ok) {
        printf("All resources present.\n");
    } else {
        printf("Resources checked - some may have been downloaded.\n");
    }

    return all_ok;
}
