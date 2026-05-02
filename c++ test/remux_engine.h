#pragma once
#include <string>
#include <vector>
#include <functional>
#include <tuple>
#include <map>

class RemuxEngine {
public:
    RemuxEngine();

    bool isAvailable() const;

    // Convert src → dst. Returns "" on success or error message.
    std::string convert(const std::string& srcPath,
                        const std::string& dstPath,
                        const std::string& quality    = "medium",
                        bool               deleteSource = false);

    // Batch convert. progress_callback(done, total) optional.
    // Returns vector of (src, dst, "" | error_string).
    std::vector<std::tuple<std::string, std::string, std::string>>
    convertBatch(const std::vector<std::pair<std::string, std::string>>& pairs,
                 const std::string& quality      = "medium",
                 bool               deleteSource = false,
                 std::function<void(int, int)>   progressCallback = nullptr);

    // Return basic audio info from ffprobe.
    // Keys: codec, bitrate_kbps, duration_s, sample_rate.
    std::map<std::string, std::string> probe(const std::string& path);

    // Return a destination path with changed extension. Avoids collisions.
    std::string suggestedOutputPath(const std::string& srcPath,
                                    const std::string& dstExt);

    // Supported format sets
    static const std::vector<std::string> SUPPORTED_OUTPUT;
    static const std::vector<std::string> SUPPORTED_INPUT;

private:
    std::string m_ffmpeg;
    std::string m_ffprobe;

    std::vector<std::string> buildCommand(const std::string& src,
                                          const std::string& dst,
                                          const std::string& srcExt,
                                          const std::string& dstExt,
                                          const std::string& quality);

    std::string normalizeExt(const std::string& raw) const;
    std::string findExecutable(const std::string& name) const;
};
