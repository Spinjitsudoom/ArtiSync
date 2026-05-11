#include "remux_engine.h"
#include <filesystem>
#include <algorithm>
#include <cctype>
#include <sstream>
#include <stdexcept>
#include <nlohmann/json.hpp>
#include <QProcess>
#include <QStringList>
#include <QStandardPaths>


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
    QString path = QStandardPaths::findExecutable(QString::fromStdString(name));
    return path.toStdString();
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
    if (args.empty()) return "Failed to build FFmpeg command";

    QString prog = QString::fromStdString(args[0]);
    QStringList qArgs;
    for (size_t i = 1; i < args.size(); ++i)
        qArgs << QString::fromStdString(args[i]);

    QProcess proc;
    proc.setProcessChannelMode(QProcess::MergedChannels);
    proc.start(prog, qArgs);

    if (!proc.waitForFinished(-1)) return "FFmpeg process timed out or failed";

    if (proc.exitCode() != 0) {
        std::string output = proc.readAll().toStdString();
        if (output.size() > 200) output = output.substr(output.size() - 200);
        return output.empty() ? "FFmpeg failed with exit code " + std::to_string(proc.exitCode()) : output;
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

    QStringList args;
    args << "-v" << "quiet"
         << "-print_format" << "json"
         << "-show_streams"
         << "-show_format"
         << QString::fromStdString(path);

    QProcess proc;
    proc.setProcessChannelMode(QProcess::MergedChannels);
    proc.start(QString::fromStdString(m_ffprobe), args);
    if (!proc.waitForFinished(30000)) return {};

    std::string output = proc.readAll().toStdString();

    std::map<std::string, std::string> info;
    try {
        auto data = nlohmann::json::parse(output);
        if (data.contains("streams") && data["streams"].is_array() && !data["streams"].empty()) {
            auto& stream = data["streams"][0];
            if (stream.contains("codec_name")) info["codec"] = stream["codec_name"];
            if (stream.contains("sample_rate")) info["sample_rate"] = stream["sample_rate"];
        }
        
        if (data.contains("format")) {
            auto& format = data["format"];
            if (format.contains("duration")) info["duration_s"] = format["duration"];
            if (format.contains("bit_rate")) {
                long long bps = std::stoll(format["bit_rate"].get<std::string>());
                info["bitrate_kbps"] = std::to_string(bps / 1000);
            }
        }
    } catch (const std::exception& e) {
        // Fallback or error logging could go here
        return {};
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
