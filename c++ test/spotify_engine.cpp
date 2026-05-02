#include "spotify_engine.h"
#include "http_client.h"

// nlohmann/json — header-only JSON library
#include <nlohmann/json.hpp>
using json = nlohmann::json;

#include <algorithm>
#include <set>
#include <sstream>

// ── Base64 encode for Basic auth ──────────────────────────────────────────────
static std::string base64_encode(const std::string& in) {
    static const char tbl[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;
    size_t i = 0;
    while (i + 2 < in.size()) {
        uint32_t t = ((uint8_t)in[i]   << 16) |
                     ((uint8_t)in[i+1] <<  8) |
                      (uint8_t)in[i+2];
        out += tbl[(t>>18)&63]; out += tbl[(t>>12)&63];
        out += tbl[(t>> 6)&63]; out += tbl[ t     &63];
        i += 3;
    }
    if (i < in.size()) {
        uint32_t t = (uint8_t)in[i] << 16;
        if (i+1 < in.size()) t |= (uint8_t)in[i+1] << 8;
        out += tbl[(t>>18)&63];
        out += tbl[(t>>12)&63];
        out += (i+1 < in.size()) ? tbl[(t>>6)&63] : '=';
        out += '=';
    }
    return out;
}

// ── Constructor ───────────────────────────────────────────────────────────────

SpotifyEngine::SpotifyEngine(const std::string& id, const std::string& secret) {
    configure(id, secret);
}

// ── Auth ──────────────────────────────────────────────────────────────────────

bool SpotifyEngine::refreshToken() {
    if (m_clientId.empty() || m_clientSecret.empty()) return false;
    std::string creds = base64_encode(m_clientId + ":" + m_clientSecret);
    std::string resp  = http::post_form(
        "https://accounts.spotify.com/api/token",
        "grant_type=client_credentials",
        {{"Authorization", "Basic " + creds}});
    if (resp.empty()) return false;
    try {
        auto j = json::parse(resp);
        m_accessToken = j.value("access_token", "");
        return !m_accessToken.empty();
    } catch (...) { return false; }
}

void SpotifyEngine::configure(const std::string& id, const std::string& secret) {
    m_clientId     = id;
    m_clientSecret = secret;
    m_configured   = false;
    m_accessToken.clear();
    // Attempt a warm-up search
    if (refreshToken()) {
        std::string resp = apiGet("/search?q=test&type=artist&limit=1");
        m_configured = !resp.empty();
    }
}

bool SpotifyEngine::isConfigured() const { return m_configured; }

std::string SpotifyEngine::apiGet(const std::string& endpoint) {
    if (m_accessToken.empty() && !refreshToken()) return "";
    std::string url = "https://api.spotify.com/v1" + endpoint;
    std::string resp = http::get(url, {{"Authorization", "Bearer " + m_accessToken}});
    // If 401, refresh and retry once
    if (resp.find("\"status\":401") != std::string::npos ||
        resp.find("\"error\"")      != std::string::npos)
    {
        if (refreshToken()) {
            resp = http::get(url, {{"Authorization", "Bearer " + m_accessToken}});
        }
    }
    return resp;
}

// ── Artist search ─────────────────────────────────────────────────────────────

std::vector<Artist> SpotifyEngine::searchArtists(const std::string& query) {
    if (!m_configured) return {};
    // URL-encode query (basic version: replace spaces)
    std::string q = query;
    for (auto& c : q) if (c == ' ') c = '+';

    std::string resp = apiGet("/search?q=" + q + "&type=artist&limit=10");
    if (resp.empty()) return {};
    try {
        auto j   = json::parse(resp);
        auto& items = j["artists"]["items"];
        std::vector<Artist> result;
        for (auto& a : items) {
            int followers = a.value("followers", json::object()).value("total", 0);
            int pop       = a.value("popularity", 0);
            result.push_back({
                a.value("name", ""),
                a.value("id",   ""),
                std::to_string(followers) + " followers · popularity " +
                    std::to_string(pop)
            });
        }
        return result;
    } catch (...) { return {}; }
}

// ── Releases ──────────────────────────────────────────────────────────────────

std::vector<Release> SpotifyEngine::getReleases(const std::string& artistId) {
    if (!m_configured) return {};
    std::set<std::pair<std::string,std::string>> seen;
    std::vector<Release> releases;

    for (auto& album_type : {"album", "single", "compilation"}) {
        int offset = 0;
        while (true) {
            std::string ep =
                "/artists/" + artistId + "/albums?include_groups=" +
                album_type + "&limit=50&offset=" + std::to_string(offset);
            std::string resp = apiGet(ep);
            if (resp.empty()) break;
            try {
                auto j = json::parse(resp);
                for (auto& a : j["items"]) {
                    std::string rd = a.value("release_date", "N/A");
                    std::string year = rd.size() >= 4 ? rd.substr(0, 4) : "N/A";
                    std::string name = a.value("name", "");
                    auto key = std::make_pair(name, year);
                    // Simple lowercase for dedup key
                    std::string lname = name;
                    std::transform(lname.begin(), lname.end(), lname.begin(), ::tolower);
                    auto lkey = std::make_pair(lname, year);
                    if (seen.count(lkey)) continue;
                    seen.insert(lkey);
                    std::string at = a.value("album_type", "album");
                    at[0] = (char)std::toupper(at[0]);
                    releases.push_back({name, a.value("id",""), year, at,
                                        a.value("total_tracks", 0)});
                }
                if (!j.contains("next") || j["next"].is_null()) break;
                offset += 50;
            } catch (...) { break; }
        }
    }
    std::sort(releases.begin(), releases.end(),
              [](const Release& a, const Release& b){ return a.year < b.year; });
    return releases;
}

// ── Tracks ────────────────────────────────────────────────────────────────────

std::vector<Track> SpotifyEngine::getTracks(const std::string& albumId) {
    auto it = m_releaseCache.find(albumId);
    if (it != m_releaseCache.end()) return it->second;
    if (!m_configured) return {};

    // Get album artists for exclusion
    std::set<std::string> primary_artists;
    {
        std::string resp = apiGet("/albums/" + albumId);
        if (!resp.empty()) {
            try {
                auto j = json::parse(resp);
                for (auto& a : j.value("artists", json::array()))
                {
                    std::string n = a.value("name","");
                    std::transform(n.begin(), n.end(), n.begin(), ::tolower);
                    primary_artists.insert(n);
                }
            } catch (...) {}
        }
    }

    std::vector<Track> tracks;
    int offset = 0;
    while (true) {
        std::string resp = apiGet(
            "/albums/" + albumId + "/tracks?limit=50&offset=" + std::to_string(offset));
        if (resp.empty()) break;
        try {
            auto j = json::parse(resp);
            for (auto& t : j["items"]) {
                std::vector<std::string> featured;
                for (auto& a : t.value("artists", json::array())) {
                    std::string n = a.value("name","");
                    std::string nl = n;
                    std::transform(nl.begin(), nl.end(), nl.begin(), ::tolower);
                    if (!primary_artists.count(nl))
                        featured.push_back(n);
                }
                tracks.push_back({
                    t.value("name", ""),
                    t.value("track_number", (int)tracks.size() + 1),
                    t.value("disc_number", 1),
                    featured
                });
            }
            if (!j.contains("next") || j["next"].is_null()) break;
            offset += 50;
        } catch (...) { break; }
    }
    m_releaseCache[albumId] = tracks;
    return tracks;
}

// ── Metadata ──────────────────────────────────────────────────────────────────

ReleaseMetadata SpotifyEngine::getReleaseMetadata(const std::string& albumId) {
    auto it = m_metaCache.find(albumId);
    if (it != m_metaCache.end()) return it->second;
    if (!m_configured) return {};

    std::string resp = apiGet("/albums/" + albumId);
    if (resp.empty()) return {};
    try {
        auto j = json::parse(resp);
        std::string artists_str;
        for (auto& a : j.value("artists", json::array())) {
            if (!artists_str.empty()) artists_str += ", ";
            artists_str += a.value("name","");
        }
        std::vector<std::string> genres;
        for (auto& g : j.value("genres", json::array()))
            genres.push_back(g.get<std::string>());

        // Fall back to artist genres
        if (genres.empty() && !j["artists"].empty()) {
            std::string ar_resp = apiGet("/artists/" +
                j["artists"][0].value("id",""));
            if (!ar_resp.empty()) {
                try {
                    auto aj = json::parse(ar_resp);
                    for (auto& g : aj.value("genres", json::array()))
                        genres.push_back(g.get<std::string>());
                } catch (...) {}
            }
        }
        // Title-case genres
        for (auto& g : genres)
            if (!g.empty()) g[0] = (char)std::toupper(g[0]);

        std::string rd = j.value("release_date","N/A");
        ReleaseMetadata m;
        m.artist = artists_str;
        m.album  = j.value("name","");
        m.year   = rd.size() >= 4 ? rd.substr(0,4) : "N/A";
        m.genres = genres;
        m.genre  = genres.empty() ? "" : genres[0];
        m_metaCache[albumId] = m;
        return m;
    } catch (...) { return {}; }
}

// ── Cover art ─────────────────────────────────────────────────────────────────

std::vector<uint8_t> SpotifyEngine::getCoverArtBytes(const std::string& albumId) {
    auto it = m_artCache.find(albumId);
    if (it != m_artCache.end()) return it->second;
    if (!m_configured) return {};

    std::string resp = apiGet("/albums/" + albumId);
    if (resp.empty()) { m_artCache[albumId] = {}; return {}; }
    try {
        auto j = json::parse(resp);
        auto& images = j["images"];
        if (images.empty()) { m_artCache[albumId] = {}; return {}; }
        // Pick the largest
        std::string url = images[0].value("url","");
        int max_w = images[0].value("width", 0);
        for (auto& img : images) {
            int w = img.value("width", 0);
            if (w > max_w) { max_w = w; url = img.value("url",""); }
        }
        auto bytes = http::get_bytes(url);
        m_artCache[albumId] = bytes;
        return bytes;
    } catch (...) { m_artCache[albumId] = {}; return {}; }
}
