#pragma once
#include "base_engine.h"
#include <string>
#include <map>
#include <vector>

class SpotifyEngine : public BaseEngine {
public:
    SpotifyEngine() = default;
    explicit SpotifyEngine(const std::string& clientId,
                           const std::string& clientSecret);

    // (Re-)initialise credentials and fetch an access token.
    void configure(const std::string& clientId, const std::string& clientSecret);

    bool isConfigured() const;

    // ── BaseEngine interface ──────────────────────────────────────────────────
    std::vector<Artist>  searchArtists(const std::string& query) override;
    std::vector<Release> getReleases(const std::string& artistId) override;
    std::vector<Track>   getTracks(const std::string& albumId) override;
    ReleaseMetadata      getReleaseMetadata(const std::string& albumId) override;
    std::vector<uint8_t> getCoverArtBytes(const std::string& albumId) override;

private:
    std::string m_clientId, m_clientSecret, m_accessToken;
    bool        m_configured = false;

    // Caches
    std::map<std::string, std::vector<Track>>   m_releaseCache;
    std::map<std::string, ReleaseMetadata>       m_metaCache;
    std::map<std::string, std::vector<uint8_t>>  m_artCache;

    // Return response JSON string; re-fetches token if expired.
    std::string apiGet(const std::string& endpoint);
    bool        refreshToken();
};
