#pragma once
#include "types.h"
#include <string>
#include <vector>
#include <utility>

// Write metadata tags to a single audio file.
// Returns true on success, or a descriptive error string on failure.
std::string writeMetadata(const std::string& filePath,
                          const ReleaseMetadata& meta,
                          bool applyArt   = true,
                          bool applyTags  = true,
                          bool applyGenre = true);

// Write the same metadata to multiple files.
// Returns a list of (file_path, "" on success | error string).
std::vector<std::pair<std::string, std::string>>
writeMetadataBatch(const std::vector<std::string>& filePaths,
                   const ReleaseMetadata& meta,
                   bool applyArt   = true,
                   bool applyTags  = true,
                   bool applyGenre = true);

// Read basic metadata from a file. Returns empty struct on failure.
struct ReadMetadata {
    std::string title, artist, album, year, genre;
    bool has_art = false;
};
ReadMetadata readMetadata(const std::string& filePath);
