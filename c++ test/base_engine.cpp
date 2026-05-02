#include "base_engine.h"
#include "fuzzy.h"
#include <algorithm>
#include <filesystem>
#include <regex>
#include <sstream>
#include <set>
#include <map>
#include <unordered_map>

namespace fs = std::filesystem;

// ── Normalise for matching ────────────────────────────────────────────────────

std::string BaseEngine::normalizeForMatching(const std::string& title) const {
    std::string s = title;
    // Lowercase
    std::transform(s.begin(), s.end(), s.begin(), ::tolower);
    // Open/close brackets → space
    s = std::regex_replace(s, std::regex(R"([\(\[\{])"), " ");
    s = std::regex_replace(s, std::regex(R"([\)\]\}])"), " ");
    // Normalise featuring variants
    s = std::regex_replace(s,
        std::regex(R"(\b(featuring|feat\.?|ft\.?|with|w/)\s+)",
                   std::regex_constants::icase),
        " feat ");
    // Strip leading "the "
    s = std::regex_replace(s, std::regex(R"(\bthe\s+)"), " ");
    // Collapse whitespace
    s = std::regex_replace(s, std::regex(R"(\s+)"), " ");
    // Trim
    size_t start = s.find_first_not_of(' ');
    size_t end   = s.find_last_not_of(' ');
    if (start == std::string::npos) return "";
    return s.substr(start, end - start + 1);
}

// ── Subset sort ratio ─────────────────────────────────────────────────────────

int BaseEngine::subsetSortRatio(const std::string& s1, const std::string& s2) const {
    return fuzzy::subset_sort_ratio(s1, s2);
}

// ── Sanitize (illegal filesystem chars) ──────────────────────────────────────

std::string BaseEngine::sanitize(const std::string& title) const {
    static const std::string illegal = R"(\/*?:"<>|)";
    std::string out;
    out.reserve(title.size());
    for (char c : title)
        out += (illegal.find(c) != std::string::npos) ? ' ' : c;
    // Collapse double spaces
    out = std::regex_replace(out, std::regex(R"( {2,})"), " ");
    // Trim
    size_t s = out.find_first_not_of(' ');
    size_t e = out.find_last_not_of(' ');
    if (s == std::string::npos) return "";
    return out.substr(s, e - s + 1);
}

// ── Track filename ────────────────────────────────────────────────────────────

std::string BaseEngine::trackFilename(const Track& track, const std::string& ext) const {
    static const std::regex feat_in_title(
        R"(\(feat\.|\(ft\.|\(with\b|\bfeat\.|\bft\.|\bfeaturing\b)",
        std::regex_constants::icase);

    std::string name = sanitize(track.name);

    if (!track.featured.empty() &&
        !std::regex_search(track.name, feat_in_title))
    {
        // Only append artists not already mentioned in the title
        std::string title_lc = track.name;
        std::transform(title_lc.begin(), title_lc.end(), title_lc.begin(), ::tolower);

        std::vector<std::string> new_feats;
        for (auto& a : track.featured) {
            std::string a_lc = a;
            std::transform(a_lc.begin(), a_lc.end(), a_lc.begin(), ::tolower);
            if (title_lc.find(a_lc) == std::string::npos)
                new_feats.push_back(a);
        }
        if (!new_feats.empty()) {
            std::string feat_str;
            for (size_t i = 0; i < new_feats.size(); ++i) {
                if (i) feat_str += " & ";
                feat_str += sanitize(new_feats[i]);
            }
            name += " ft. " + feat_str;
        }
    }
    return name + ext;
}

// ── Numeric preview ───────────────────────────────────────────────────────────

std::pair<std::vector<MatchResult>, std::string>
BaseEngine::generatePreview(const std::string& folderPath,
                            const std::vector<Track>& tracks,
                            int fOffset)
{
    std::vector<std::string> files;
    try {
        for (auto& entry : fs::directory_iterator(folderPath))
            if (entry.is_regular_file())
                files.push_back(entry.path().filename().string());
    } catch (...) {
        return {{}, "Error reading folder.\n"};
    }
    std::sort(files.begin(), files.end());

    std::vector<MatchResult> results;
    std::string log = "NUMERIC MATCH:\n";

    for (int i = 0; i < (int)files.size(); ++i) {
        int idx = i + fOffset;
        if (idx < 0 || idx >= (int)tracks.size()) continue;
        const auto& t = tracks[idx];
        std::string ext = fs::path(files[i]).extension().string();
        std::string newName = trackFilename(t, ext);
        results.push_back({files[i], newName, t.num, t.disc, 100});
        log += "  " + files[i] + "\n  → " + newName + "\n\n";
    }
    return {results, log};
}

// ── Fuzzy preview ─────────────────────────────────────────────────────────────

std::pair<std::vector<MatchResult>, std::string>
BaseEngine::generateFuzzyPreview(const std::string& folderPath,
                                 const std::vector<Track>& tracks,
                                 int fOffset)
{
    (void)fOffset;
    std::vector<std::string> files;
    try {
        for (auto& entry : fs::directory_iterator(folderPath))
            if (entry.is_regular_file())
                files.push_back(entry.path().filename().string());
    } catch (...) {
        return {{}, "Error reading folder.\n"};
    }

    // Build track maps
    std::map<std::string, const Track*> track_map;   // name → track
    std::vector<std::string> track_titles;
    for (auto& t : tracks) {
        if (track_map.find(t.name) == track_map.end()) {
            track_map[t.name] = &t;
            track_titles.push_back(t.name);
        }
    }

    // Count normalised track names to detect ambiguity (e.g. "War" on disc 1 and 2)
    std::map<std::string, int> norm_counts;
    for (auto& t : tracks)
        norm_counts[normalizeForMatching(t.name)]++;
    std::set<std::string> ambiguous_norms;
    for (auto& [n, c] : norm_counts)
        if (c > 1) ambiguous_norms.insert(n);

    // Pre-build normalised → original title map
    std::map<std::string, std::string> norm_map;
    std::vector<std::string> norm_titles;
    for (auto& title : track_titles) {
        std::string n = normalizeForMatching(title);
        norm_map[n] = title;
        norm_titles.push_back(n);
    }

    struct TempMatch {
        std::string old_name;
        int num, disc;
        std::string title;
        const Track* track;
        int score;
    };

    std::vector<TempMatch> temp_matches;
    std::set<std::string> used_tracks;
    std::string log = "FUZZY MATCH:\n";

    static const std::regex scene_tags(
        R"((1080p|720p|x264|x265|HEVC|WEB-DL|BluRay|\d{3}kbps))",
        std::regex_constants::icase);
    static const std::regex leading_num(R"(^\d+\s*[-\.]\s*)");

    for (auto& fname : files) {
        std::string fn_base = fs::path(fname).stem().string();
        // Replace . and _ with space
        std::replace(fn_base.begin(), fn_base.end(), '.', ' ');
        std::replace(fn_base.begin(), fn_base.end(), '_', ' ');
        fn_base = std::regex_replace(fn_base, scene_tags, "");
        fn_base = std::regex_replace(fn_base, leading_num, "");
        // Trim
        size_t s = fn_base.find_first_not_of(' ');
        if (s != std::string::npos) fn_base = fn_base.substr(s);

        std::string fn_norm = normalizeForMatching(fn_base);

        // Only consider unclaimed tracks
        std::vector<std::string> remaining;
        for (auto& n : norm_titles)
            if (used_tracks.find(norm_map.at(n)) == used_tracks.end())
                remaining.push_back(n);

        if (remaining.empty()) {
            log += "  SKIPPED (no tracks left): " + fname + "\n";
            continue;
        }

        auto scorer = [this](const std::string& a, const std::string& b) {
            return this->subsetSortRatio(a, b);
        };
        auto [best_norm, best_score] = fuzzy::extract_one(fn_norm, remaining, scorer);

        if (best_score > TRACK_MATCH_THRESHOLD) {
            if (ambiguous_norms.count(best_norm)) {
                log += "  AMBIGUOUS: " + fname +
                       "  (multiple tracks share this name — use manual pairing)\n";
                continue;
            }
            std::string orig_title = norm_map.at(best_norm);
            const Track* track = track_map.at(orig_title);
            used_tracks.insert(orig_title);
            temp_matches.push_back({fname, track->num, track->disc, track->name,
                                    track, best_score});
        } else {
            log += "  UNMATCHED: " + fname + "  (see manual pairing dialog)\n";
        }
    }

    // Sort by disc then track number
    std::sort(temp_matches.begin(), temp_matches.end(),
              [](const TempMatch& a, const TempMatch& b) {
                  if (a.disc != b.disc) return a.disc < b.disc;
                  return a.num < b.num;
              });

    // Duplicate output-name guard
    std::map<std::string, std::vector<int>> seen_names; // sanitized title → indices
    for (int i = 0; i < (int)temp_matches.size(); ++i) {
        std::string key = sanitize(temp_matches[i].title);
        std::transform(key.begin(), key.end(), key.begin(), ::tolower);
        seen_names[key].push_back(i);
    }
    std::set<int> needs_disambig;
    for (auto& [k, idxs] : seen_names)
        if (idxs.size() > 1)
            for (int i : idxs) needs_disambig.insert(i);

    std::vector<MatchResult> ep_data;
    for (int i = 0; i < (int)temp_matches.size(); ++i) {
        auto& m = temp_matches[i];
        std::string ext     = fs::path(m.old_name).extension().string();
        std::string base_nm = trackFilename(*m.track, ext);
        std::string new_name;
        std::string note;

        if (needs_disambig.count(i)) {
            std::string prefix = (m.disc > 1)
                ? "Disc " + std::to_string(m.disc) + " - "
                : (m.num < 10 ? "0" : "") + std::to_string(m.num) + " - ";
            std::string stem = fs::path(base_nm).stem().string();
            new_name = prefix + stem + ext;
            note = " [disambiguated: " + prefix + "]";
        } else {
            new_name = base_nm;
        }
        ep_data.push_back({m.old_name, new_name, m.num, m.disc, m.score});
        log += "  [" + std::to_string(m.score) + "%] " + m.old_name +
               "\n  → " + new_name + note + "\n\n";
    }
    return {ep_data, log};
}

// ── Batch preview ─────────────────────────────────────────────────────────────

std::vector<BatchResult>
BaseEngine::generateBatchPreview(const std::string& artistPath,
                                 const std::string& artistId,
                                 const std::string& matchMode,
                                 int fOffset)
{
    std::vector<std::string> folders;
    try {
        for (auto& entry : fs::directory_iterator(artistPath))
            if (entry.is_directory())
                folders.push_back(entry.path().filename().string());
    } catch (...) {
        return {};
    }
    std::sort(folders.begin(), folders.end());

    auto releases = getReleases(artistId);
    if (releases.empty()) return {};

    std::map<std::string, const Release*> release_map;
    std::vector<std::string> release_titles;
    for (auto& r : releases) {
        release_map[r.title] = &r;
        release_titles.push_back(r.title);
    }

    static const std::regex year_prefix(R"(^\d{4}\s*[-\.]\s*)");
    std::vector<BatchResult> results;

    for (auto& folder : folders) {
        std::string album_path = artistPath + "/" + folder;
        std::string clean = std::regex_replace(folder, year_prefix, "");
        // Trim
        size_t s = clean.find_first_not_of(' ');
        if (s != std::string::npos) clean = clean.substr(s);

        auto [best_title, score] = fuzzy::extract_one(clean, release_titles,
                                                       fuzzy::token_set_ratio);

        if (!best_title.empty() && score >= ALBUM_MATCH_THRESHOLD) {
            const Release* rel = release_map.at(best_title);
            auto tracks = getTracks(rel->id);
            if (!tracks.empty()) {
                std::pair<std::vector<MatchResult>, std::string> pv;
                if (matchMode == "Numeric")
                    pv = generatePreview(album_path, tracks, fOffset);
                else
                    pv = generateFuzzyPreview(album_path, tracks, fOffset);

                std::string header =
                    "📁 " + folder + "\n"
                    "   ↳ " + rel->title + " (" + rel->year + ")  [" +
                    std::to_string(score) + "% match]\n"
                    "   " + std::to_string(pv.first.size()) + " files matched\n";

                results.push_back({folder, album_path, true, *rel, score,
                                   pv.first, header + pv.second});
            } else {
                results.push_back({folder, album_path, true, *rel, score, {},
                    "📁 " + folder + "\n   ↳ " + rel->title + " — no tracks found.\n"});
            }
        } else {
            results.push_back({folder, album_path, false, {}, score, {},
                "📁 " + folder + "\n   ✗ No match found (best score: " +
                std::to_string(score) + "%)\n"});
        }
    }
    return results;
}
