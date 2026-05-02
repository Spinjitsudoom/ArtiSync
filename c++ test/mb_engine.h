#pragma once
#include "base_engine.h"
#include <map>

class MBEngine : public BaseEngine {
public:
    MBEngine() = default;

    bool isConfigured() const { return true; }  // No credentials needed

    std::vector<Artist>  searchArtists(const std::string& query) override;
    std::vector<Release> getReleases(const std::string& artistId) override;
    std::vector<Track>   getTracks(const std::string& releaseGroupId) override;
    ReleaseMetadata      getReleaseMetadata(const std::string& releaseGroupId) override;
    std::vector<uint8_t> getCoverArtBytes(const std::string& releaseGroupId) override;

private:
    std::map<std::string, std::vector<Track>>  m_releaseCache;
    std::map<std::string, ReleaseMetadata>      m_metaCache;
    std::map<std::string, std::vector<uint8_t>> m_artCache;

    std::string mbGet(const std::string& endpoint);
};
