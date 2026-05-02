#pragma once
#include <string>
#include <vector>
#include <utility>
#include <cstdint>

namespace http {

using Headers = std::vector<std::pair<std::string, std::string>>;

// GET request — returns response body as string. Empty string on failure.
std::string get(const std::string& url,
                const Headers& headers = {},
                int timeout_sec = 15);

// GET request — returns raw bytes. Empty vector on failure.
std::vector<uint8_t> get_bytes(const std::string& url,
                               const Headers& headers = {},
                               int timeout_sec = 15);

// POST with form-encoded body — returns response body. Used for OAuth2.
std::string post_form(const std::string& url,
                      const std::string& body,
                      const Headers& headers = {},
                      int timeout_sec = 15);

} // namespace http
