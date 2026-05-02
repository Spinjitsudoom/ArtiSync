#include "http_client.h"
#include <curl/curl.h>
#include <cstring>

namespace http {

// ── libcurl write callback ────────────────────────────────────────────────────

static size_t write_str(void* ptr, size_t size, size_t nmemb, void* ud) {
    auto* buf = static_cast<std::string*>(ud);
    buf->append(static_cast<char*>(ptr), size * nmemb);
    return size * nmemb;
}

static size_t write_bytes(void* ptr, size_t size, size_t nmemb, void* ud) {
    auto* buf = static_cast<std::vector<uint8_t>*>(ud);
    auto* data = static_cast<uint8_t*>(ptr);
    buf->insert(buf->end(), data, data + size * nmemb);
    return size * nmemb;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

static curl_slist* build_headers(CURL* curl, const Headers& headers) {
    curl_slist* list = nullptr;
    // Always set a User-Agent
    list = curl_slist_append(list, "User-Agent: MusicOrganizerApp/2.1");
    for (auto& [k, v] : headers) {
        std::string hdr = k + ": " + v;
        list = curl_slist_append(list, hdr.c_str());
    }
    (void)curl;
    return list;
}

// ── Public API ────────────────────────────────────────────────────────────────

std::string get(const std::string& url, const Headers& headers, int timeout_sec) {
    CURL* curl = curl_easy_init();
    if (!curl) return "";
    std::string body;
    curl_slist* hdrs = build_headers(curl, headers);
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_str);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &body);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, (long)timeout_sec);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);
    CURLcode res = curl_easy_perform(curl);
    curl_slist_free_all(hdrs);
    curl_easy_cleanup(curl);
    return (res == CURLE_OK) ? body : "";
}

std::vector<uint8_t> get_bytes(const std::string& url, const Headers& headers,
                               int timeout_sec) {
    CURL* curl = curl_easy_init();
    if (!curl) return {};
    std::vector<uint8_t> body;
    curl_slist* hdrs = build_headers(curl, headers);
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_bytes);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &body);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, (long)timeout_sec);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);
    CURLcode res = curl_easy_perform(curl);
    curl_slist_free_all(hdrs);
    curl_easy_cleanup(curl);
    return (res == CURLE_OK) ? body : std::vector<uint8_t>{};
}

std::string post_form(const std::string& url, const std::string& body,
                      const Headers& headers, int timeout_sec) {
    CURL* curl = curl_easy_init();
    if (!curl) return "";
    std::string resp;
    curl_slist* hdrs = build_headers(curl, headers);
    hdrs = curl_slist_append(hdrs, "Content-Type: application/x-www-form-urlencoded");
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_str);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, (long)timeout_sec);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);
    CURLcode res = curl_easy_perform(curl);
    curl_slist_free_all(hdrs);
    curl_easy_cleanup(curl);
    return (res == CURLE_OK) ? resp : "";
}

} // namespace http
