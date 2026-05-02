#pragma once
#include "types.h"
#include <string>
#include <vector>
#include <tuple>

constexpr int TRACK_MATCH_THRESHOLD = 30;  // file → track name
constexpr int ALBUM_MATCH_THRESHOLD = 80;  // folder → release title (batch)

class BaseEngine {
public:
    virtual ~BaseEngine() = default;

    // ── Interface subclasses must implement ───────────────────────────────────
    virtual std::vector<Artist>  searchArtists(const std::string& query) = 0;
    virtual std::vector<Release> getReleases(const std::string& artistId) = 0;
    virtual std::vector<Track>   getTracks(const std::string& releaseId) = 0;
    virtual ReleaseMetadata      getReleaseMetadata(const std::string& releaseId) = 0;
    virtual std::vector<uint8_t> getCoverArtBytes(const std::string& releaseId) = 0;

    // ── Previews ──────────────────────────────────────────────────────────────
    // Numeric: match files (sorted alphabetically) to tracks in order
    std::pair<std::vector<MatchResult>, std::string>
    generatePreview(const std::string& folderPath,
                    const std::vector<Track>& tracks,
                    int fOffset = 0);

    // Fuzzy: match filenames to track names via token-sort-ratio
    std::pair<std::vector<MatchResult>, std::string>
    generateFuzzyPreview(const std::string& folderPath,
                         const std::vector<Track>& tracks,
                         int fOffset = 0);

    // Batch: walk artist folder, fuzzy-match each subfolder to a release
    std::vector<BatchResult>
    generateBatchPreview(const std::string& artistPath,
                         const std::string& artistId,
                         const std::string& matchMode = "Numeric",
                         int fOffset = 0);

    // ── Helpers (accessible to GUI for manual pairing) ────────────────────────
    std::string sanitize(const std::string& title) const;
    std::string trackFilename(const Track& track, const std::string& ext) const;

protected:
    std::string normalizeForMatching(const std::string& title) const;
    int         subsetSortRatio(const std::string& s1, const std::string& s2) const;
};
