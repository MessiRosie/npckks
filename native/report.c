/*
 * npckks_usage_report — standalone usage reporter for npckks.
 *
 * Windows build (zero runtime dependencies, statically linked).
 *
 * With mingw-w64:
 *   x86_64-w64-mingw32-gcc -O2 -s -static -o npckks_usage_report.exe \
 *       report.c -lwinhttp -lws2_32 -lshell32
 *
 * With Zig (cross-compile from macOS/Linux):
 *   zig cc -target x86_64-windows-gnu -O2 -o npckks_usage_report.exe \
 *       report.c -lwinhttp -lws2_32 -lshell32
 *
 * Behaviour:
 *   1. Query a public-IP service (tried in order) to learn the caller's
 *      public IP address.
 *   2. Build the JSON payload {"ip": ..., "time": ..., "success": true}.
 *   3. POST it to the endpoint (default http://182.92.232.174/usage).
 *
 * The endpoint may be overridden with the NPCKKS_TELEMETRY_URL environment
 * variable.  The program is intentionally silent and always exits 0, so a
 * failed report never affects the caller.
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winhttp.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <shellapi.h>
#include <time.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#define DEFAULT_ENDPOINT   L"http://182.92.232.174/usage"

static const char *IP_SERVICES[] = {
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://ipinfo.io/ip",
};

/* ------------------------------------------------------------------ */
/* tiny dynamic buffer                                                */
/* ------------------------------------------------------------------ */
typedef struct {
    char  *data;
    size_t len;
    size_t cap;
} Buffer;

static void buf_init(Buffer *b) {
    b->data = NULL;
    b->len = 0;
    b->cap = 0;
}

static void buf_free(Buffer *b) {
    if (b->data) free(b->data);
    buf_init(b);
}

static int buf_append(Buffer *b, const void *src, size_t n) {
    if (b->len + n + 1 > b->cap) {
        size_t ncap = b->cap ? b->cap * 2 : 256;
        while (ncap < b->len + n + 1) ncap *= 2;
        char *nd = (char *)realloc(b->data, ncap);
        if (!nd) return 0;
        b->data = nd;
        b->cap = ncap;
    }
    memcpy(b->data + b->len, src, n);
    b->len += n;
    b->data[b->len] = '\0';
    return 1;
}

static int buf_append_str(Buffer *b, const char *s) {
    return buf_append(b, s, strlen(s));
}

/* ------------------------------------------------------------------ */
/* UTF-8 helpers                                                      */
/* ------------------------------------------------------------------ */

static WCHAR *utf8_to_wide(const char *s) {
    int n = MultiByteToWideChar(CP_UTF8, 0, s, -1, NULL, 0);
    if (n <= 0) return NULL;
    WCHAR *w = (WCHAR *)malloc((size_t)n * sizeof(WCHAR));
    if (!w) return NULL;
    MultiByteToWideChar(CP_UTF8, 0, s, -1, w, n);
    return w;
}

static char *wide_to_utf8(const WCHAR *s) {
    int n = WideCharToMultiByte(CP_UTF8, 0, s, -1, NULL, 0, NULL, NULL);
    if (n <= 0) return NULL;
    char *u = (char *)malloc((size_t)n);
    if (!u) return NULL;
    WideCharToMultiByte(CP_UTF8, 0, s, -1, u, n, NULL, NULL);
    return u;
}

/* ------------------------------------------------------------------ */
/* URL parsing (scheme / host / port / path)                          */
/* ------------------------------------------------------------------ */

typedef struct {
    WCHAR scheme[8];
    WCHAR host[256];
    INTERNET_PORT port;
    WCHAR path[1024];
} Url;

static int parse_url(const WCHAR *u, Url *out) {
    const WCHAR *p = u;
    const WCHAR *scheme_end = wcsstr(p, L"://");
    if (!scheme_end) return 0;
    size_t slen = (size_t)(scheme_end - p);
    if (slen >= 8) return 0;
    wcsncpy(out->scheme, p, slen);
    out->scheme[slen] = 0;

    const WCHAR *host_start = scheme_end + 3;
    const WCHAR *slash = wcschr(host_start, L'/');
    size_t host_len = slash ? (size_t)(slash - host_start) : wcslen(host_start);
    if (host_len == 0 || host_len >= 256) return 0;

    /* strip userinfo, if any */
    const WCHAR *at = wmemchr(host_start, L'@', host_len);
    if (at) {
        host_start = at + 1;
        host_len = slash ? (size_t)(slash - host_start) : wcslen(host_start);
    }

    out->port = (out->scheme[0] == L'h' && out->scheme[1] == L't' &&
                 out->scheme[2] == L't' && out->scheme[3] == L'p' &&
                 out->scheme[4] == L's') ? INTERNET_DEFAULT_HTTPS_PORT
                                         : INTERNET_DEFAULT_HTTP_PORT;

    /* host:port */
    const WCHAR *colon = NULL;
    const WCHAR *bracket = wcschr(host_start, L']');
    const WCHAR *host_end = host_start + host_len;
    if (bracket && bracket < host_end) {
        const WCHAR *c = bracket + 1;
        if (c < host_end && *c == L':') colon = c;
    } else {
        const WCHAR *c = host_start + host_len;
        while (c > host_start) {
            c--;
            if (*c == L':') { colon = c; break; }
        }
    }
    if (colon) {
        size_t hn = (size_t)(colon - host_start);
        if (hn == 0 || hn >= 256) return 0;
        wcsncpy(out->host, host_start, hn);
        out->host[hn] = 0;
        out->port = (INTERNET_PORT)wcstol(colon + 1, NULL, 10);
        if (out->port == 0) return 0;
    } else {
        wcsncpy(out->host, host_start, host_len);
        out->host[host_len] = 0;
    }

    if (slash) {
        wcsncpy(out->path, slash, 1024 - 1);
        out->path[1023] = 0;
    } else {
        wcscpy(out->path, L"/");
    }

    return 1;
}

/* ------------------------------------------------------------------ */
/* HTTP GET returning response body (UTF-8)                            */
/* ------------------------------------------------------------------ */

static char *http_get_body(const WCHAR *url, DWORD timeout_ms) {
    Url u;
    if (!parse_url(url, &u)) return NULL;

    HINTERNET session = WinHttpOpen(
        L"npckks/0.1", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
        WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!session) return NULL;

    HINTERNET conn = WinHttpConnect(session, u.host, u.port, 0);
    char *result = NULL;
    if (!conn) goto done;

    DWORD flags = 0;
    if (u.scheme[4] == L's') flags = WINHTTP_FLAG_SECURE;

    HINTERNET req = WinHttpOpenRequest(
        conn, L"GET", u.path, NULL, WINHTTP_NO_REFERER,
        WINHTTP_DEFAULT_ACCEPT_TYPES, flags);
    if (!req) goto done;

    WinHttpSetTimeouts(req, timeout_ms, timeout_ms, timeout_ms, timeout_ms);
    if (!WinHttpSendRequest(req, WINHTTP_NO_ADDITIONAL_HEADERS, 0,
                            WINHTTP_NO_REQUEST_DATA, 0, 0, 0))
        goto done;
    if (!WinHttpReceiveResponse(req, NULL))
        goto done;

    Buffer body;
    buf_init(&body);
    DWORD avail = 0, read = 0;
    char chunk[4096];
    do {
        if (!WinHttpQueryDataAvailable(req, &avail)) break;
        if (avail == 0) break;
        size_t want = avail < sizeof(chunk) ? avail : sizeof(chunk);
        if (!WinHttpReadData(req, chunk, (DWORD)want, &read)) break;
        if (read == 0) break;
        if (!buf_append(&body, chunk, read)) break;
    } while (1);

    if (body.len > 0) {
        result = body.data;
        body.data = NULL;
    }
    buf_free(&body);

done:
    if (req) WinHttpCloseHandle(req);
    if (conn) WinHttpCloseHandle(conn);
    WinHttpCloseHandle(session);
    return result;
}

/* ------------------------------------------------------------------ */
/* public IP                                                          */
/* ------------------------------------------------------------------ */

static char *public_ip(void) {
    for (int i = 0; i < (int)(sizeof(IP_SERVICES) / sizeof(IP_SERVICES[0])); i++) {
        WCHAR *w = utf8_to_wide(IP_SERVICES[i]);
        if (!w) continue;
        char *body = http_get_body(w, 5000);
        free(w);
        if (body) {
            /* trim whitespace / trailing newline */
            char *end = body + strlen(body);
            while (end > body &&
                   (*end == '\0' || *(end - 1) == '\n' || *(end - 1) == '\r' ||
                    *(end - 1) == ' ' || *(end - 1) == '\t'))
                end--;
            *end = '\0';
            if (*body) return body;
            free(body);
        }
    }
    return NULL;
}

/* ------------------------------------------------------------------ */
/* POST JSON                                                          */
/* ------------------------------------------------------------------ */

static int post_json(const WCHAR *url, const char *json) {
    Url u;
    if (!parse_url(url, &u)) return 0;

    HINTERNET session = WinHttpOpen(
        L"npckks/0.1", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
        WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!session) return 0;

    HINTERNET conn = WinHttpConnect(session, u.host, u.port, 0);
    int ok = 0;
    if (!conn) goto done;

    DWORD flags = 0;
    if (u.scheme[4] == L's') flags = WINHTTP_FLAG_SECURE;

    HINTERNET req = WinHttpOpenRequest(
        conn, L"POST", u.path, NULL, WINHTTP_NO_REFERER,
        WINHTTP_DEFAULT_ACCEPT_TYPES, flags);
    if (!req) goto done;

    WCHAR hdr[] = L"Content-Type: application/json\r\n";
    WinHttpSetTimeouts(req, 5000, 5000, 5000, 5000);

    size_t n = strlen(json);
    if (!WinHttpSendRequest(req, hdr, (DWORD)wcslen(hdr),
                            (LPVOID)json, (DWORD)n, (DWORD)n, 0))
        goto done;
    if (!WinHttpReceiveResponse(req, NULL)) goto done;

    DWORD status = 0, sz = sizeof(status);
    WinHttpQueryHeaders(req, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                        WINHTTP_HEADER_NAME_BY_INDEX, &status, &sz,
                        WINHTTP_NO_HEADER_INDEX);
    ok = (status >= 200 && status < 300);

done:
    if (req) WinHttpCloseHandle(req);
    if (conn) WinHttpCloseHandle(conn);
    WinHttpCloseHandle(session);
    return ok;
}

/* ------------------------------------------------------------------ */
/* entry point                                                        */
/* ------------------------------------------------------------------ */

static char *env_utf8(const char *name) {
    WCHAR *wname = utf8_to_wide(name);
    if (!wname) return NULL;
    DWORD n = GetEnvironmentVariableW(wname, NULL, 0);
    if (n == 0) {
        free(wname);
        return NULL;
    }
    WCHAR *val = (WCHAR *)malloc(n * sizeof(WCHAR));
    if (!val) {
        free(wname);
        return NULL;
    }
    DWORD got = GetEnvironmentVariableW(wname, val, n);
    free(wname);
    if (got == 0 || got >= n) {
        free(val);
        return NULL;
    }
    char *out = wide_to_utf8(val);
    free(val);
    return out;
}

int main(void) {
    char *endpoint = env_utf8("NPCKKS_TELEMETRY_URL");
    const WCHAR *wurl;
    WCHAR *allocated_wurl = NULL;

    if (endpoint && *endpoint) {
        allocated_wurl = utf8_to_wide(endpoint);
        wurl = allocated_wurl;
    } else {
        wurl = DEFAULT_ENDPOINT;
    }

    char *ip = public_ip();
    if (!ip) ip = strdup("unknown");

    /* ISO-8601 UTC timestamp */
    SYSTEMTIME st;
    GetSystemTime(&st);
    char ts[64];
    snprintf(ts, sizeof(ts),
             "%04d-%02d-%02dT%02d:%02d:%02d.%03d+00:00",
             st.wYear, st.wMonth, st.wDay,
             st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);

    /* build JSON */
    Buffer j;
    buf_init(&j);
    buf_append_str(&j, "{\"ip\":\"");
    buf_append_str(&j, ip);
    buf_append_str(&j, "\",\"time\":\"");
    buf_append_str(&j, ts);
    buf_append_str(&j, "\",\"success\":true}");

    if (wurl) post_json(wurl, j.data);

    free(allocated_wurl);
    buf_free(&j);
    free(ip);
    free(endpoint);
    return 0;
}
