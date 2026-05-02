#include "remux_engine.h"
#include <filesystem>
#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <array>
#include <sstream>
#include <stdexcept>

#ifdef _WIN32
  #include <windows.h>
#else
  #include <unistd.h>
#endif

namespace fs = std::filesystem;

// ── Format tables ─────────────────────────────────────────────────────────────

const std::vector<std::string> RemuxEngine::SUPPORTED_OUTPUT =
    {".mp3", ".flac", ".m4a", ".ogg", ".wav"};

const std::vector<std::string> RemuxEngine::SUPPORTED_INPUT =
    {".mp3", ".flac", ".m4a", ".aac", ".mp4",
     ".ogg", ".oga", ".wav", ".opus", ".wma"};

static const std::vector<std::pair<std::string,std::string>> REMUX_PAIRS = {
    {".aac", ".m4a"}, {".mp4", ".m4a"}, {".m4a", ".mp4"},
};

static const std::map<std::string, std::vector<std::string>> MP3_QUALITY = {
    {"low",    {"-b:a", "128k"}},
    {"medium", {"-b:a", "192k"}},
    {"high",   {"-b:a", "320k"}},
    {"best",   {"-q:a", "0"}},
};
static const std::map<std::string, std::vector<std::string>> AAC_QUALITY = {
    {"low",    {"-b:a", "128k"}},
    {"medium", {"-b:a", "192k"}},
    {"high",   {"-b:a", "256k"}},
    {"best",   {"-b:a", "256k"}},
};

// ── Helpers ───────────────────────────────────────────────────────────────────

std::string RemuxEngine::normalizeExt(const std::string& raw) const {
    std::string ext = raw;
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    size_t space = ext.find(' ');
    if (space != std::string::npos)
        ext = "." + ext.substr(space + 1);
    return ext;
}

std::string RemuxEngine::findExecutable(const std::string& name) const {
#ifdef _WIN32
    // Search PATH on Windows
    char buf[MAX_PATH];
    if (SearchPathA(nullptr, name.c_str(), ".exe", MAX_PATH, buf, nullptr))
        return buf;
    return "";
#else
    std::string cmd = "which " + name + " 2>/dev/null";
    FILE* pipe = popen(cmd.c_str(), "r");
    if (!pipe) return "";
    char buf[512] = {};
    fgets(buf, sizeof(buf), pipe);
    pclose(pipe);
    std::string result(buf);
    // Trim newline
    if (!result.empty() && result.back() == '\n') result.pop_back();
    return result;
#endif
}

// ── Constructor ───────────────────────────────────────────────────────────────

RemuxEngine::RemuxEngine() {
    m_ffmpeg  = findExecutable("ffmpeg");
    m_ffprobe = findExecutable("ffprobe");
}

bool RemuxEngine::isAvailable() const { return !m_ffmpeg.empty(); }

// ── Command builder ───────────────────────────────────────────────────────────

std::vector<std::string> RemuxEngine::buildCommand(
    const std::string& src, const std::string& dst,
    const std::string& srcExt, const std::string& dstExt,
    const std::string& quality)
{
    std::vector<std::string> cmd = {m_ffmpeg, "-y", "-i", src};

    bool is_remux_pair = false;
    for (auto& [a, b] : REMUX_PAIRS)
        if (a == srcExt && b == dstExt) { is_remux_pair = true; break; }

    if (is_remux_pair) {
        cmd.insert(cmd.end(), {"-c", "copy", "-map", "0"});
    } else if (dstExt == ".mp3") {
        cmd.push_back("-c:a"); cmd.push_back("libmp3lame");
        auto it = MP3_QUALITY.find(quality);
        auto& q = (it != MP3_QUALITY.end()) ? it->second : MP3_QUALITY.at("medium");
        cmd.insert(cmd.end(), q.begin(), q.end());
        cmd.insert(cmd.end(),
            {"-map", "0:a", "-map", "0:v?", "-c:v", "mjpeg", "-disposition:v", "attached_pic"});
    } else if (dstExt == ".flac") {
        cmd.insert(cmd.end(),
            {"-c:a", "flac", "-map", "0:a", "-map", "0:v?", "-c:v", "copy"});
    } else if (dstExt == ".m4a" || dstExt == ".mp4") {
        cmd.push_back("-c:a"); cmd.push_back("aac");
        auto it = AAC_QUALITY.find(quality);
        auto& q = (it != AAC_QUALITY.end()) ? it->second : AAC_QUALITY.at("medium");
        cmd.insert(cmd.end(), q.begin(), q.end());
        cmd.insert(cmd.end(),
            {"-map", "0:a", "-map", "0:v?", "-c:v", "copy", "-disposition:v", "attached_pic"});
    } else if (dstExt == ".ogg") {
        cmd.insert(cmd.end(), {"-c:a", "libvorbis", "-q:a", "6", "-map", "0:a"});
    } else if (dstExt == ".wav") {
        cmd.insert(cmd.end(), {"-c:a", "pcm_s16le", "-map", "0:a"});
    }

    cmd.insert(cmd.end(), {"-map_metadata", "0"});
    cmd.push_back(dst);
    return cmd;
}

// ── Convert ───────────────────────────────────────────────────────────────────

std::string RemuxEngine::convert(const std::string& srcPath,
                                 const std::string& dstPath,
                                 const std::string& quality,
                                 bool deleteSource)
{
    if (!isAvailable()) return "FFmpeg not found — install it and add to PATH";

    std::string srcExt = normalizeExt(fs::path(srcPath).extension().string());
    std::string dstExt = normalizeExt(fs::path(dstPath).extension().string());

    bool src_ok = std::find(SUPPORTED_INPUT.begin(), SUPPORTED_INPUT.end(), srcExt)
                  != SUPPORTED_INPUT.end();
    bool dst_ok = std::find(SUPPORTED_OUTPUT.begin(), SUPPORTED_OUTPUT.end(), dstExt)
                  != SUPPORTED_OUTPUT.end();

    if (!src_ok) return "Unsupported input format: " + srcExt;
    if (!dst_ok) return "Unsupported output format: " + dstExt;
    if (!fs::exists(srcPath)) return "Source file not found: " + srcPath;

    auto args = buildCommand(srcPath, dstPath, srcExt, dstExt, quality);

    // Build shell command string
    std::string cmd;
    for (auto& a : args) {
#ifdef _WIN32
        cmd += "\"" + a + "\" ";
#else
        // Simple quoting — single-quote each argument
        cmd += "'";
        for (char c : a) {
            if (c == '\'') cmd += "'\\''";
            else           cmd += c;
        }
        cmd += "' ";
#endif
    }
    cmd += " 2>&1";  // redirect stderr so we can capture it

    // Run
    std::string output;
    FILE* pipe = popen(cmd.c_str(), "r");
    if (!pipe) return "Failed to launch FFmpeg";
    char buf[256];
    while (fgets(buf, sizeof(buf), pipe))
        output += buf;
    int ret = pclose(pipe);

    if (ret != 0) {
        // Return last ~200 chars of output
        if (output.size() > 200) output = output.substr(output.size() - 200);
        return output;
    }

    if (deleteSource && fs::exists(dstPath)) {
        std::error_code ec;
        fs::remove(srcPath, ec);
    }
    return "";
}

// ── Batch ─────────────────────────────────────────────────────────────────────

std::vector<std::tuple<std::string, std::string, std::string>>
RemuxEngine::convertBatch(
    const std::vector<std::pair<std::string, std::string>>& pairs,
    const std::string& quality, bool deleteSource,
    std::function<void(int, int)> progressCallback)
{
    std::vector<std::tuple<std::string, std::string, std::string>> results;
    int total = (int)pairs.size();
    for (int i = 0; i < total; ++i) {
        auto& [src, dst] = pairs[i];
        std::string res = convert(src, dst, quality, deleteSource);
        results.emplace_back(src, dst, res);
        if (progressCallback) progressCallback(i + 1, total);
    }
    return results;
}

// ── Probe ─────────────────────────────────────────────────────────────────────

std::map<std::string, std::string> RemuxEngine::probe(const std::string& path) {
    if (m_ffprobe.empty() || !fs::exists(path)) return {};
    std::string cmd =
        "'" + m_ffprobe + "' -v quiet -print_format json -show_streams -show_format "
        "'" + path + "' 2>/dev/null";
    std::string output;
    FILE* pipe = popen(cmd.c_str(), "r");
    if (!pipe) return {};
    char buf[256];
    while (fgets(buf, sizeof(buf), pipe)) output += buf;
    pclose(pipe);

    // Very simple JSON parsing for the fields we need
    auto extract = [&](const std::string& key) -> std::string {
        std::string search = "\"" + key + "\": \"";
        size_t pos = output.find(search);
        if (pos == std::string::npos) {
            search = "\"" + key + "\": ";
            pos = output.find(search);
            if (pos == std::string::npos) return "";
            pos += search.size();
            size_t end = output.find_first_of(",\n}", pos);
            return (end != std::string::npos) ? output.substr(pos, end - pos) : "";
        }
        pos += search.size();
        size_t end = output.find('"', pos);
        return (end != std::string::npos) ? output.substr(pos, end - pos) : "";
    };

    std::map<std::string, std::string> info;
    info["codec"]        = extract("codec_name");
    info["bitrate_kbps"] = extract("bit_rate");
    info["duration_s"]   = extract("duration");
    info["sample_rate"]  = extract("sample_rate");
    // Convert bit_rate from bps to kbps if numeric
    if (!info["bitrate_kbps"].empty()) {
        try {
            info["bitrate_kbps"] = std::to_string(
                std::stoi(info["bitrate_kbps"]) / 1000);
        } catch (...) {}
    }
    return info;
}

// ── Suggested output path ─────────────────────────────────────────────────────

std::string RemuxEngine::suggestedOutputPath(const std::string& srcPath,
                                             const std::string& dstExt)
{
    fs::path p(srcPath);
    std::string folder = p.parent_path().string();
    std::string stem   = p.stem().string();
    std::string rawExt = p.extension().string();

    // Strip compound extension junk (e.g. "song.audio" when ext was ".audio aac")
    if (rawExt.find(' ') != std::string::npos) {
        // stem already excludes the bad extension
    }

    fs::path dst = fs::path(folder) / (stem + dstExt);
    if (fs::exists(dst) && dst.string() != srcPath)
        dst = fs::path(folder) / (stem + "_converted" + dstExt);
    return dst.string();
}
