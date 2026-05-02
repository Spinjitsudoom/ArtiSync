#pragma once
#include <string>
#include <vector>
#include <cstdint>

struct Track {
    std::string name;
    int         num  = 1;
    int         disc = 1;
    std::vector<std::string> featured;
};

struct Release {
    std::string title;
    std::string id;
    std::string year;
    std::string type;
    int         track_count = 0;
};

struct Artist {
    std::string name;
    std::string id;
    std::string disambiguation;
};

struct ReleaseMetadata {
    std::string artist;
    std::string album;
    std::string year;
    std::string genre;
    std::vector<std::string>  genres;
    std::vector<uint8_t>      cover_art_bytes;
    // Per-file fields populated during execute
    std::string title;
    int         track_number = 0;
    int         disc_number  = 1;
    int         total_tracks = 0;
};

struct MatchResult {
    std::string old_name;
    std::string new_name;
    int         track_num = 0;
    int         disc_num  = 1;
    int         score     = 0;
};

struct BatchResult {
    std::string folder;
    std::string path;
    bool        has_release = false;
    Release     release;
    int         score = 0;
    std::vector<MatchResult> ep_data;
    std::string log;
};
