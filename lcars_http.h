#ifndef LCARS_HTTP_H
#define LCARS_HTTP_H

// Starts the HTTP server on the specified port in a separate thread.
void StartHTTPServer(int port);
// Runs the HTTP server on the specified port, blocking the current thread.
void RunHTTPServer(int port);
// Configures Basic Auth credentials.
void SetHTTPServerCredentials(const char *username, const char *password);

#ifdef LCARS_HTTP_IMPLEMENTATION

#define _GNU_SOURCE 1
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <pthread.h>
#include <sqlite3.h>
#include <strings.h>

#include "lcars_arena.h"

static char g_auth_user[128] = {0};
static char g_auth_pass[128] = {0};
static bool g_auth_enabled = false;

void SetHTTPServerCredentials(const char *username, const char *password) {
    if (username) {
        strncpy(g_auth_user, username, sizeof(g_auth_user) - 1);
        g_auth_user[sizeof(g_auth_user) - 1] = '\0';
    }
    if (password) {
        strncpy(g_auth_pass, password, sizeof(g_auth_pass) - 1);
        g_auth_pass[sizeof(g_auth_pass) - 1] = '\0';
    }
    g_auth_enabled = true;
}

static int base64_decode(const char *in, char *out, int out_max) {
    static const int table[] = {
        -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,
        -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,
        -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, 62, -1, -1, -1, 63,
        52, 53, 54, 55, 56, 57, 58, 59, 60, 61, -1, -1, -1,  0, -1, -1,
        -1,  0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13, 14,
        15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, -1, -1, -1, -1, -1,
        -1, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40,
        41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, -1, -1, -1, -1, -1
    };
    int len = 0;
    int val = 0;
    int valb = -8;
    for (int i = 0; in[i] != '\0'; i++) {
        unsigned char c = in[i];
        if (c > 127 || table[c] == -1) {
            if (c == '=') break;
            continue;
        }
        val = (val << 6) + table[c];
        valb += 6;
        if (valb >= 0) {
            if (len < out_max - 1) {
                out[len++] = (char)((val >> valb) & 0xFF);
            }
            valb -= 8;
        }
        if (valb == -8) {
            val = 0;
        }
    }
    out[len] = '\0';
    return len;
}

// Simple JSON extraction helpers
static bool json_get_string(const char *json, const char *key, char *out_val, size_t max_len) {
    char pattern[128];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char *p = strstr(json, pattern);
    if (!p) return false;
    p += strlen(pattern);
    while (*p && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n' || *p == ':')) {
        p++;
    }
    if (*p == '"') {
        p++;
        size_t len = 0;
        while (*p && *p != '"' && len < max_len - 1) {
            if (*p == '\\' && *(p+1)) {
                p++;
            }
            out_val[len++] = *p++;
        }
        out_val[len] = '\0';
        return true;
    }
    return false;
}

static bool json_get_int(const char *json, const char *key, int *out_val) {
    char pattern[128];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char *p = strstr(json, pattern);
    if (!p) return false;
    p += strlen(pattern);
    while (*p && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n' || *p == ':')) {
        p++;
    }
    char *endptr;
    long val = strtol(p, &endptr, 10);
    if (p == endptr) return false;
    *out_val = (int)val;
    return true;
}

static bool json_get_float(const char *json, const char *key, float *out_val) {
    char pattern[128];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char *p = strstr(json, pattern);
    if (!p) return false;
    p += strlen(pattern);
    while (*p && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n' || *p == ':')) {
        p++;
    }
    char *endptr;
    float val = strtof(p, &endptr);
    if (p == endptr) return false;
    *out_val = val;
    return true;
}

static const char *find_header_value(const char *headers, const char *header_name) {
    size_t name_len = strlen(header_name);
    const char *p = headers;
    while (p && *p) {
        if (strncasecmp(p, header_name, name_len) == 0) {
            const char *val = p + name_len;
            while (*val == ' ' || *val == '\t') val++;
            return val;
        }
        p = strstr(p, "\r\n");
        if (p) p += 2;
    }
    return NULL;
}

static char *json_escape(Arena *arena, const char *str) {
    if (!str) return "";
    size_t len = 0;
    const char *p = str;
    while (*p) {
        if (*p == '"' || *p == '\\' || *p == '\b' || *p == '\f' || *p == '\n' || *p == '\r' || *p == '\t') {
            len += 2;
        } else {
            len++;
        }
        p++;
    }
    char *escaped = arena_alloc(arena, len + 1);
    if (!escaped) return "";
    char *dst = escaped;
    p = str;
    while (*p) {
        if (*p == '"' || *p == '\\') {
            *dst++ = '\\';
            *dst++ = *p;
        } else if (*p == '\n') {
            *dst++ = '\\';
            *dst++ = 'n';
        } else if (*p == '\r') {
            *dst++ = '\\';
            *dst++ = 'r';
        } else if (*p == '\t') {
            *dst++ = '\\';
            *dst++ = 't';
        } else {
            *dst++ = *p;
        }
        p++;
    }
    *dst = '\0';
    return escaped;
}

static void HandleHTTPConnection(int client_fd) {
    // Allocate 1 MB memory arena on the thread stack.
    // Extremely fast, safe, and avoids malloc fragmentation or memory leaks.
    uint8_t arena_backing[1024 * 1024];
    Arena arena;
    arena_init(&arena, arena_backing, sizeof(arena_backing));

    char req_buf[8192];
    int total_read = 0;
    while (total_read < (int)sizeof(req_buf) - 1) {
        int n = recv(client_fd, req_buf + total_read, sizeof(req_buf) - 1 - total_read, 0);
        if (n <= 0) break;
        total_read += n;
        req_buf[total_read] = '\0';
        if (strstr(req_buf, "\r\n\r\n")) {
            break;
        }
    }

    char *body_start = strstr(req_buf, "\r\n\r\n");
    if (!body_start) {
        printf("HTTP Connection Error: Missing end-of-header delimiter\n");
        close(client_fd);
        return;
    }
    body_start += 4;
    int headers_len = (int)(body_start - req_buf);

    char method[16] = {0};
    char path[256] = {0};
    if (sscanf(req_buf, "%15s %255s", method, path) != 2) {
        printf("HTTP Request Parsing Failure: Cannot parse HTTP method/path\n");
        close(client_fd);
        return;
    }

    printf("HTTP Request: %s %s\n", method, path);
    int status_code = 0;

    // Handle OPTIONS request for CORS preflight
    if (strcmp(method, "OPTIONS") == 0) {
        const char *resp = "HTTP/1.1 204 No Content\r\n"
                           "Access-Control-Allow-Origin: *\r\n"
                           "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
                           "Access-Control-Allow-Headers: Content-Type, Authorization\r\n"
                           "Content-Length: 0\r\n\r\n";
        send(client_fd, resp, strlen(resp), 0);
        status_code = 204;
        goto end;
    }

    // Initialize credentials if not already configured
    if (!g_auth_enabled) {
        const char *env_user = getenv("LCARS_AUTH_USER");
        const char *env_pass = getenv("LCARS_AUTH_PASS");
        if (env_user && env_pass) {
            strncpy(g_auth_user, env_user, sizeof(g_auth_user) - 1);
            g_auth_user[sizeof(g_auth_user) - 1] = '\0';
            strncpy(g_auth_pass, env_pass, sizeof(g_auth_pass) - 1);
            g_auth_pass[sizeof(g_auth_pass) - 1] = '\0';
        } else {
            strncpy(g_auth_user, "admin", sizeof(g_auth_user) - 1);
            g_auth_user[sizeof(g_auth_user) - 1] = '\0';
            strncpy(g_auth_pass, "admin", sizeof(g_auth_pass) - 1);
            g_auth_pass[sizeof(g_auth_pass) - 1] = '\0';
        }
        g_auth_enabled = true;
    }

    bool authenticated = false;
    const char *auth_val = find_header_value(req_buf, "Authorization:");
    if (auth_val) {
        char val_buf[512] = {0};
        size_t len = 0;
        while (auth_val[len] && auth_val[len] != '\r' && auth_val[len] != '\n' && len < sizeof(val_buf) - 1) {
            val_buf[len] = auth_val[len];
            len++;
        }
        val_buf[len] = '\0';
        while (len > 0 && (val_buf[len-1] == ' ' || val_buf[len-1] == '\t')) {
            val_buf[--len] = '\0';
        }
        if (strncasecmp(val_buf, "Basic ", 6) == 0) {
            char decoded[512] = {0};
            base64_decode(val_buf + 6, decoded, sizeof(decoded));
            char *colon = strchr(decoded, ':');
            if (colon) {
                *colon = '\0';
                char *user = decoded;
                char *pass = colon + 1;
                if (strcmp(user, g_auth_user) == 0 && strcmp(pass, g_auth_pass) == 0) {
                    authenticated = true;
                } else {
                    printf("HTTP Auth Failure: Username or password mismatch for user '%s'\n", user);
                }
            } else {
                printf("HTTP Auth Failure: Malformed credentials token (missing colon)\n");
            }
        } else {
            printf("HTTP Auth Failure: Unsupported auth method (expected Basic)\n");
        }
    } else {
        printf("HTTP Auth Failure: Missing Authorization header\n");
    }

    if (!authenticated) {
        const char *resp = "HTTP/1.1 401 Unauthorized\r\n"
                           "WWW-Authenticate: Basic realm=\"LCARS\"\r\n"
                           "Content-Type: text/plain\r\n"
                           "Access-Control-Allow-Origin: *\r\n"
                           "Content-Length: 12\r\n\r\n"
                           "Unauthorized";
        send(client_fd, resp, strlen(resp), 0);
        status_code = 401;
        goto end;
    }

    const char *cl_val = find_header_value(req_buf, "Content-Length:");
    int content_len = cl_val ? atoi(cl_val) : 0;

    char content_type[128] = {0};
    const char *ct_val = find_header_value(req_buf, "Content-Type:");
    if (ct_val) {
        size_t len = 0;
        while (ct_val[len] && ct_val[len] != '\r' && ct_val[len] != '\n' && ct_val[len] != ';' && len < sizeof(content_type) - 1) {
            content_type[len] = ct_val[len];
            len++;
        }
        content_type[len] = '\0';
        while (len > 0 && (content_type[len-1] == ' ' || content_type[len-1] == '\t')) {
            content_type[--len] = '\0';
        }
    }

    // Read full body if Content-Length is provided
    char *body = "";
    if (content_len > 0) {
        body = (char *)arena_alloc(&arena, content_len + 1);
        if (!body) {
            printf("HTTP Error: Failed to allocate %d bytes in memory arena for request body\n", content_len);
            status_code = 500;
            const char *resp = "HTTP/1.1 500 Internal Server Error\r\n"
                               "Content-Length: 0\r\n\r\n";
            send(client_fd, resp, strlen(resp), 0);
            goto end;
        }
        int body_already_read = total_read - headers_len;
        if (body_already_read > content_len) {
            body_already_read = content_len;
        }
        if (body_already_read > 0) {
            memcpy(body, body_start, body_already_read);
        }
        int body_to_read = content_len - body_already_read;
        while (body_to_read > 0) {
            int n = recv(client_fd, body + body_already_read, body_to_read, 0);
            if (n <= 0) break;
            body_already_read += n;
            body_to_read -= n;
        }
        body[content_len] = '\0';
    }

    // Router
    if ((strcmp(path, "/entries") == 0 || strcmp(path, "/entries/") == 0) && strcmp(method, "GET") == 0) {
        sqlite3 *db;
        int rc = sqlite3_open("lcars.db", &db);
        if (rc != SQLITE_OK) {
            printf("HTTP Database Error: Failed to open database 'lcars.db': %s\n", sqlite3_errstr(rc));
            const char *resp = "HTTP/1.1 500 Internal Server Error\r\n"
                               "Content-Type: application/json\r\n"
                               "Access-Control-Allow-Origin: *\r\n"
                               "Content-Length: 35\r\n\r\n"
                               "{\"error\":\"Failed to open database\"}";
            send(client_fd, resp, strlen(resp), 0);
            status_code = 500;
            goto end;
        }

        sqlite3_stmt *stmt;
        rc = sqlite3_prepare_v2(db, "SELECT id, kind, title, content, value_int, value_float, done_bool, created_at_utc, last_modified_at_utc FROM entries ORDER BY id DESC;", -1, &stmt, NULL);
        if (rc != SQLITE_OK) {
            const char *err_msg = sqlite3_errmsg(db);
            printf("HTTP Database Error: Failed to prepare SELECT query: %s\n", err_msg);
            char resp_body[512];
            int resp_len = snprintf(resp_body, sizeof(resp_body), "{\"error\":\"Failed to prepare query: %s\"}", err_msg);
            char header[512];
            int header_len = snprintf(header, sizeof(header),
                "HTTP/1.1 500 Internal Server Error\r\n"
                "Content-Type: application/json\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "Content-Length: %d\r\n\r\n", resp_len);
            send(client_fd, header, header_len, 0);
            send(client_fd, resp_body, resp_len, 0);
            sqlite3_close(db);
            status_code = 500;
            goto end;
        }

        size_t resp_cap = 4096;
        size_t resp_len = 0;
        char *resp_body = arena_alloc(&arena, resp_cap);
        if (resp_body) {
            resp_body[0] = '[';
            resp_len = 1;

            bool first = true;
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                if (!first) {
                    if (resp_len + 2 >= resp_cap) {
                        size_t old_cap = resp_cap;
                        resp_cap *= 2;
                        resp_body = arena_realloc(&arena, resp_body, old_cap, resp_cap);
                    }
                    resp_body[resp_len++] = ',';
                }
                first = false;

                int id = sqlite3_column_int(stmt, 0);
                const char *kind = (const char *)sqlite3_column_text(stmt, 1);
                const char *title = (const char *)sqlite3_column_text(stmt, 2);
                const char *content = (const char *)sqlite3_column_text(stmt, 3);
                int value_int = sqlite3_column_int(stmt, 4);
                double value_float = sqlite3_column_double(stmt, 5);
                int done_bool = sqlite3_column_int(stmt, 6);
                const char *created_at = (const char *)sqlite3_column_text(stmt, 7);
                const char *last_modified = (const char *)sqlite3_column_text(stmt, 8);

                if (!kind) kind = "";
                if (!title) title = "";
                if (!content) content = "";
                if (!created_at) created_at = "";
                if (!last_modified) last_modified = "";

                char *esc_kind = json_escape(&arena, kind);
                char *esc_title = json_escape(&arena, title);
                char *esc_content = json_escape(&arena, content);
                char *esc_created = json_escape(&arena, created_at);
                char *esc_modified = json_escape(&arena, last_modified);

                char row_buf[4096];
                int row_len = snprintf(row_buf, sizeof(row_buf),
                    "{\"id\":%d,\"kind\":\"%s\",\"title\":\"%s\",\"content\":\"%s\",\"value_int\":%d,\"value_float\":%f,\"done_bool\":%d,\"created_at_utc\":\"%s\",\"last_modified_at_utc\":\"%s\"}",
                    id, esc_kind, esc_title, esc_content, value_int, value_float, done_bool, esc_created, esc_modified);

                if (resp_len + row_len + 5 >= resp_cap) {
                    size_t old_cap = resp_cap;
                    resp_cap = (resp_cap + row_len) * 2;
                    resp_body = arena_realloc(&arena, resp_body, old_cap, resp_cap);
                }
                memcpy(resp_body + resp_len, row_buf, row_len);
                resp_len += row_len;
            }
            resp_body[resp_len++] = ']';
            resp_body[resp_len] = '\0';
        }

        sqlite3_finalize(stmt);
        sqlite3_close(db);

        char header[512];
        int header_len = snprintf(header, sizeof(header),
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/json\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "Content-Length: %zu\r\n\r\n", resp_len);
        send(client_fd, header, header_len, 0);
        if (resp_body && resp_len > 0) {
            send(client_fd, resp_body, resp_len, 0);
        }
        status_code = 200;
        goto end;
    } else if ((strcmp(path, "/entries") == 0 || strcmp(path, "/entries/") == 0) && strcmp(method, "POST") == 0) {
        bool is_json = (strstr(content_type, "application/json") != NULL);

        char kind[128] = {0};
        char title[512] = {0};
        char content[4096] = {0};
        int value_int = 0;
        float value_float = 0.0f;
        int done_bool = 0;

        if (is_json) {
            json_get_string(body, "kind", kind, sizeof(kind));
            json_get_string(body, "title", title, sizeof(title));
            json_get_string(body, "content", content, sizeof(content));
            json_get_int(body, "value_int", &value_int);
            json_get_float(body, "value_float", &value_float);
            json_get_int(body, "done_bool", &done_bool);
        } else {
            strncpy(content, body, sizeof(content) - 1);
            content[sizeof(content) - 1] = '\0';
            strcpy(title, "HTTP Text Entry");
        }

        if (title[0] == '\0') {
            strcpy(title, "HTTP Entry");
        }

        sqlite3 *db;
        int rc = sqlite3_open("lcars.db", &db);
        if (rc != SQLITE_OK) {
            printf("HTTP Database Error: Failed to open database 'lcars.db': %s\n", sqlite3_errstr(rc));
            const char *resp = "HTTP/1.1 500 Internal Server Error\r\n"
                               "Content-Type: application/json\r\n"
                               "Access-Control-Allow-Origin: *\r\n"
                               "Content-Length: 35\r\n\r\n"
                               "{\"error\":\"Failed to open database\"}";
            send(client_fd, resp, strlen(resp), 0);
            status_code = 500;
            goto end;
        }

        sqlite3_stmt *stmt;
        const char *sql = "INSERT INTO entries (kind, title, content, value_int, value_float, done_bool) VALUES (?, ?, ?, ?, ?, ?);";
        rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
        if (rc == SQLITE_OK) {
            sqlite3_bind_text(stmt, 1, kind, -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(stmt, 2, title, -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(stmt, 3, content, -1, SQLITE_TRANSIENT);
            sqlite3_bind_int(stmt, 4, value_int);
            sqlite3_bind_double(stmt, 5, value_float);
            sqlite3_bind_int(stmt, 6, done_bool);

            rc = sqlite3_step(stmt);
            if (rc == SQLITE_DONE) {
                sqlite3_int64 insert_id = sqlite3_last_insert_rowid(db);
                char resp_body[256];
                int resp_len = snprintf(resp_body, sizeof(resp_body), "{\"status\":\"success\",\"id\":%lld}", (long long)insert_id);
                char header[512];
                int header_len = snprintf(header, sizeof(header),
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Content-Length: %d\r\n\r\n", resp_len);
                send(client_fd, header, header_len, 0);
                send(client_fd, resp_body, resp_len, 0);
                status_code = 200;
            } else {
                const char *err_msg = sqlite3_errmsg(db);
                printf("HTTP Database Error: Query execution failed: %s\n", err_msg);
                char resp_body[512];
                int resp_len = snprintf(resp_body, sizeof(resp_body), "{\"status\":\"error\",\"message\":\"Execution failed: %s\"}", err_msg);
                char header[512];
                int header_len = snprintf(header, sizeof(header),
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Content-Type: application/json\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Content-Length: %d\r\n\r\n", resp_len);
                send(client_fd, header, header_len, 0);
                send(client_fd, resp_body, resp_len, 0);
                status_code = 400;
            }
            sqlite3_finalize(stmt);
        } else {
            const char *err_msg = sqlite3_errmsg(db);
            printf("HTTP Database Error: Failed to prepare INSERT query: %s\n", err_msg);
            char resp_body[512];
            int resp_len = snprintf(resp_body, sizeof(resp_body), "{\"status\":\"error\",\"message\":\"Preparation failed: %s\"}", err_msg);
            char header[512];
            int header_len = snprintf(header, sizeof(header),
                "HTTP/1.1 500 Internal Server Error\r\n"
                "Content-Type: application/json\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "Content-Length: %d\r\n\r\n", resp_len);
            send(client_fd, header, header_len, 0);
            send(client_fd, resp_body, resp_len, 0);
            status_code = 500;
        }
        sqlite3_close(db);
        goto end;
    } else {
        const char *resp = "HTTP/1.1 404 Not Found\r\n"
                           "Content-Type: text/plain\r\n"
                           "Access-Control-Allow-Origin: *\r\n"
                           "Content-Length: 9\r\n\r\n"
                           "Not Found";
        send(client_fd, resp, strlen(resp), 0);
        status_code = 404;
        goto end;
    }

end:
    if (status_code != 0) {
        printf("HTTP Reply: %d\n", status_code);
    }
    close(client_fd);
}

void RunHTTPServer(int port) {
    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) {
        perror("Failed to create HTTP socket");
        return;
    }

    int opt = 1;
    if (setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt)) < 0) {
        perror("setsockopt SO_REUSEADDR failed");
        close(server_fd);
        return;
    }

    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = INADDR_ANY;
    address.sin_port = htons(port);

    if (bind(server_fd, (struct sockaddr *)&address, sizeof(address)) < 0) {
        perror("HTTP bind failed");
        close(server_fd);
        return;
    }

    if (listen(server_fd, 10) < 0) {
        perror("HTTP listen failed");
        close(server_fd);
        return;
    }

    printf("HTTP Server running on port %d...\n", port);

    while (1) {
        int client_fd = accept(server_fd, NULL, NULL);
        if (client_fd >= 0) {
            HandleHTTPConnection(client_fd);
        }
    }

    close(server_fd);
}

static void *HTTPServerThread(void *arg) {
    int port = *(int *)arg;
    free(arg);
    RunHTTPServer(port);
    return NULL;
}

void StartHTTPServer(int port) {
    int *arg = malloc(sizeof(int));
    if (arg) {
        *arg = port;
        pthread_t thread;
        pthread_create(&thread, NULL, HTTPServerThread, arg);
        pthread_detach(thread);
    }
}

#endif // LCARS_HTTP_IMPLEMENTATION
#endif // LCARS_HTTP_H
