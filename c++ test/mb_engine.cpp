#include "mb_engine.h"
#include "http_client.h"
#include <nlohmann/json.hpp>
#include <thread>
#include <chrono>
#include <algorithm>

using json = nlohmann::json;

static constexpr const char* MB_API = "https://musicbrainz.org/ws/2";

std::string MBEngine::mbGet(const std::string& endpoint) {
    std::string url = std::string(MB_API) + endpoint +
                      (endpoint.find('?') == std::string::npos ? "?" : "&") +
                      "fmt=json";
    return http::get(url,
        {{"User-Agent", "MusicOrganizerApp/2.1 ( contact@example.com )"}});
}

// ── Artist search ─────────────────────────────────────────────────────────────

std::vector<Artist> MBEngine::searchArtists(const std::string& query) {
    // URL-encode (basic)
    std::string q = query;
    for (auto& c : q) if (c == ' ') c = '+';
    std::string resp = mbGet("/artist?query=" + q + "&limit=10");
    if (resp.empty()) return {};
    try {
        auto j = json::parse(resp);
        std::vector<Artist> result;
        for (auto& a : j.value("artists", json::array())) {
            result.push_back({
                a.value("name",           ""),
                a.value("id",             ""),
                a.value("disambiguation", "")
            });
        }
        return result;
    } catch (...) { return {}; }
}

// ── Releases ──────────────────────────────────────────────────────────────────

std::vector<Release> MBEngine::getReleases(const std::string& artistId) {
    std::string resp = mbGet(
        "/artist/" + artistId + "?inc=release-groups&type=album|ep|single");
    if (resp.empty()) return {};
    try {
        auto j = json::parse(resp);
        std::vector<Release> releases;
        for (auto& rg : j.value("release-groups", json::array())) {
            std::string rd = rg.value("first-release-date","N/A");
            releases.push_back({
                rg.value("title",""),
                rg.value("id",""),
                rd.size() >= 4 ? rd.substr(0,4) : "N/A",
                rg.value("primary-type","Album"),
                rg.value("release-count", 0)
            });
        }
        std::sort(releases.begin(), releases.end(),
                  [](const Release& a, const Release& b){ return a.year < b.year; });
        return releases;
    } catch (...) { return {}; }
}

// ── Tracks ────────────────────────────────────────────────────────────────────

std::vector<Track> MBEngine::getTracks(const std::string& releaseGroupId) {
    auto it = m_releaseCache.find(releaseGroupId);
    if (it != m_releaseCache.end()) return it->second;

    // Get first release ID from the release group
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    std::string rg_resp = mbGet("/release-group/" + releaseGroupId + "?inc=releases");
    if (rg_resp.empty()) return {};

    std::string release_id;
    try {
        auto j = json::parse(rg_resp);
        auto rl = j.value("releases", json::array());
        if (rl.empty()) return {};
        release_id = rl[0].value("id","");
    } catch (...) { return {}; }

    if (release_id.empty()) return {};

    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    std::string resp = mbGet("/release/" + release_id + "?inc=recordings+media");
    if (resp.empty()) return {};

    std::vector<Track> tracks;
    try {
        auto j = json::parse(resp);
        for (auto& medium : j.value("media", json::array())) {
            int disc = medium.value("position", 1);
            for (auto& t : medium.value("tracks", json::array())) {
                std::string title;
                auto rec = t.value("recording", json::object());
                title = rec.value("title", t.value("title","Unknown"));
                tracks.push_back({
                    title,
                    t.value("position", (int)tracks.size() + 1),
                    disc,
                    {}
                });
            }
        }
    } catch (...) {}

    m_releaseCache[releaseGroupId] = tracks;
    return tracks;
}

// ── Metadata ──────────────────────────────────────────────────────────────────

ReleaseMetadata MBEngine::getReleaseMetadata(const std::string& releaseGroupId) {
    auto it = m_metaCache.find(releaseGroupId);
    if (it != m_metaCache.end()) return it->second;

    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    std::string rg_resp = mbGet("/release-group/" + releaseGroupId + "?inc=releases");
    if (rg_resp.empty()) return {};

    std::string release_id;
    try {
        auto j = json::parse(rg_resp);
        auto rl = j.value("releases", json::array());
        if (rl.empty()) return {};
        release_id = rl[0].value("id","");
    } catch (...) { return {}; }

    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    std::string resp = mbGet(
        "/release/" + release_id + "?inc=artists+genres+tags+release-groups");
    if (resp.empty()) return {};

    try {
        auto r = json::parse(resp);
        std::string artists_str;
        for (auto& c : r.value("artist-credit", json::array())) {
            if (c.contains("artist")) {
                if (!artists_str.empty()) artists_str += ", ";
                artists_str += c["artist"].value("name","");
            }
        }
        std::vector<std::string> genres;
        for (auto& g : r.value("genres", json::array()))
            genres.push_back(g.value("name",""));
        if (genres.empty()) {
            // Fall back to tags sorted by count
            std::vector<std::pair<int,std::string>> tags;
            for (auto& t : r.value("tags", json::array()))
                tags.emplace_back(t.value("count",0), t.value("name",""));
            std::sort(tags.rbegin(), tags.rend());
            for (int i = 0; i < std::min((int)tags.size(), 5); ++i)
                genres.push_back(tags[i].second);
        }
        for (auto& g : genres)
            if (!g.empty()) g[0] = (char)std::toupper(g[0]);

        std::string rd = r.value("date","N/A");
        ReleaseMetadata m;
        m.artist = artists_str;
        m.album  = r.value("title","");
        m.year   = rd.size() >= 4 ? rd.substr(0,4) : "N/A";
        m.genres = genres;
        m.genre  = genres.empty() ? "" : genres[0];
        m_metaCache[releaseGroupId] = m;
        return m;
    } catch (...) { return {}; }
}

// ── Cover art ─────────────────────────────────────────────────────────────────

std::vector<uint8_t> MBEngine::getCoverArtBytes(const std::string& releaseGroupId) {
    auto it = m_artCache.find(releaseGroupId);
    if (it != m_artCache.end()) return it->second;

    for (auto& url : {
        "https://coverartarchive.org/release-group/" + releaseGroupId + "/front-500",
        "https://coverartarchive.org/release-group/" + releaseGroupId + "/front"
    }) {
        auto bytes = http::get_bytes(url);
        if (!bytes.empty()) {
            m_artCache[releaseGroupId] = bytes;
            return bytes;
        }
    }
    m_artCache[releaseGroupId] = {};
    return {};
}
