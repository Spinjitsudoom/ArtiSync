#include "metadata_writer.h"
#include <filesystem>
#include <algorithm>
#include <cctype>

// TagLib includes (paths match CMakeLists.txt include_directories)
#include <mpegfile.h>
#include <id3v2tag.h>
#include <id3v2frame.h>
#include <textidentificationframe.h>
#include <attachedpictureframe.h>
#include <flacfile.h>
#include <xiphcomment.h>
#include <flacpicture.h>
#include <mp4file.h>
#include <mp4tag.h>
#include <mp4coverart.h>
#include <vorbisfile.h>
#include <tpropertymap.h>
#include <tbytevector.h>

namespace fs = std::filesystem;

// ── Extension normaliser ──────────────────────────────────────────────────────

static std::string normalizeExt(const std::string& raw) {
    std::string ext = raw;
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    // Handle compound extensions like ".audio aac" → ".aac"
    size_t space = ext.find(' ');
    if (space != std::string::npos)
        ext = "." + ext.substr(space + 1);
    return ext;
}

// ── MIME detection from magic bytes ──────────────────────────────────────────

static std::string detectMime(const std::vector<uint8_t>& data) {
    if (data.size() >= 4 &&
        data[0] == 0x89 && data[1] == 'P' && data[2] == 'N' && data[3] == 'G')
        return "image/png";
    if (data.size() >= 3 &&
        data[0] == 'G' && data[1] == 'I' && data[2] == 'F')
        return "image/gif";
    return "image/jpeg";
}

// ── Per-format writers ────────────────────────────────────────────────────────

static std::string writeMp3(const std::string& path, const ReleaseMetadata& meta,
                             bool applyArt, bool applyTags, bool applyGenre)
{
    TagLib::MPEG::File file(path.c_str());
    if (!file.isValid()) return "Cannot open file";

    TagLib::ID3v2::Tag* tag = file.ID3v2Tag(true);

    auto setText = [&](const TagLib::ByteVector& id, const std::string& val) {
        tag->removeFrames(id);
        if (val.empty()) return;
        auto* frame = new TagLib::ID3v2::TextIdentificationFrame(id,
                          TagLib::String::UTF8);
        frame->setText(TagLib::String(val, TagLib::String::UTF8));
        tag->addFrame(frame);
    };

    if (applyTags) {
        if (!meta.title.empty())  setText("TIT2", meta.title);
        if (!meta.artist.empty()) setText("TPE1", meta.artist);
        if (!meta.album.empty())  setText("TALB", meta.album);
        if (!meta.year.empty())   setText("TDRC", meta.year);

        if (meta.track_number > 0) {
            std::string trck = std::to_string(meta.track_number);
            if (meta.total_tracks > 0)
                trck += "/" + std::to_string(meta.total_tracks);
            setText("TRCK", trck);
        }
        if (meta.disc_number > 1)
            setText("TPOS", std::to_string(meta.disc_number));
    }
    if (applyGenre && !meta.genre.empty())
        setText("TCON", meta.genre);

    if (applyArt && !meta.cover_art_bytes.empty()) {
        tag->removeFrames("APIC");
        auto* apic = new TagLib::ID3v2::AttachedPictureFrame;
        apic->setMimeType(detectMime(meta.cover_art_bytes));
        apic->setType(TagLib::ID3v2::AttachedPictureFrame::FrontCover);
        apic->setDescription("Cover");
        apic->setPicture(TagLib::ByteVector(
            reinterpret_cast<const char*>(meta.cover_art_bytes.data()),
            (unsigned int)meta.cover_art_bytes.size()));
        tag->addFrame(apic);
    }

    if (!file.save()) return "Failed to save";
    return "";
}

static std::string writeFlac(const std::string& path, const ReleaseMetadata& meta,
                              bool applyArt, bool applyTags, bool applyGenre)
{
    TagLib::FLAC::File file(path.c_str());
    if (!file.isValid()) return "Cannot open file";

    TagLib::Ogg::XiphComment* tag = file.xiphComment(true);

    auto setField = [&](const TagLib::String& key, const std::string& val) {
        tag->removeFields(key);
        if (!val.empty())
            tag->addField(key, TagLib::String(val, TagLib::String::UTF8));
    };

    if (applyTags) {
        if (!meta.title.empty())  setField("TITLE",       meta.title);
        if (!meta.artist.empty()) setField("ARTIST",      meta.artist);
        if (!meta.album.empty())  setField("ALBUM",       meta.album);
        if (!meta.year.empty())   setField("DATE",        meta.year);
        if (meta.track_number > 0)
            setField("TRACKNUMBER", std::to_string(meta.track_number));
        if (meta.disc_number > 1)
            setField("DISCNUMBER", std::to_string(meta.disc_number));
    }
    if (applyGenre && !meta.genre.empty())
        setField("GENRE", meta.genre);

    if (applyArt && !meta.cover_art_bytes.empty()) {
        file.removePictures();
        auto* pic = new TagLib::FLAC::Picture;
        pic->setType(TagLib::FLAC::Picture::FrontCover);
        pic->setMimeType(detectMime(meta.cover_art_bytes));
        pic->setDescription("Cover");
        pic->setData(TagLib::ByteVector(
            reinterpret_cast<const char*>(meta.cover_art_bytes.data()),
            (unsigned int)meta.cover_art_bytes.size()));
        file.addPicture(pic);
    }

    if (!file.save()) return "Failed to save";
    return "";
}

static std::string writeMp4(const std::string& path, const ReleaseMetadata& meta,
                             bool applyArt, bool applyTags, bool applyGenre)
{
    TagLib::MP4::File file(path.c_str());
    if (!file.isValid()) return "Cannot open file";

    TagLib::MP4::Tag* tag = file.tag();

    if (applyTags) {
        if (!meta.title.empty())
            tag->setItem("©nam",
                TagLib::MP4::Item(TagLib::StringList(
                    TagLib::String(meta.title, TagLib::String::UTF8))));
        if (!meta.artist.empty())
            tag->setItem("©ART",
                TagLib::MP4::Item(TagLib::StringList(
                    TagLib::String(meta.artist, TagLib::String::UTF8))));
        if (!meta.album.empty())
            tag->setItem("©alb",
                TagLib::MP4::Item(TagLib::StringList(
                    TagLib::String(meta.album, TagLib::String::UTF8))));
        if (!meta.year.empty())
            tag->setItem("©day",
                TagLib::MP4::Item(TagLib::StringList(
                    TagLib::String(meta.year, TagLib::String::UTF8))));
        if (meta.track_number > 0)
            tag->setItem("trkn",
                TagLib::MP4::Item(meta.track_number,
                                  meta.total_tracks));
        if (meta.disc_number > 1)
            tag->setItem("disk",
                TagLib::MP4::Item(meta.disc_number, 0));
    }
    if (applyGenre && !meta.genre.empty())
        tag->setItem("©gen",
            TagLib::MP4::Item(TagLib::StringList(
                TagLib::String(meta.genre, TagLib::String::UTF8))));

    if (applyArt && !meta.cover_art_bytes.empty()) {
        TagLib::MP4::CoverArt::Format fmt =
            (meta.cover_art_bytes.size() >= 4 &&
             meta.cover_art_bytes[0] == 0x89 && meta.cover_art_bytes[1] == 'P')
            ? TagLib::MP4::CoverArt::PNG
            : TagLib::MP4::CoverArt::JPEG;

        TagLib::MP4::CoverArtList covers;
        covers.append(TagLib::MP4::CoverArt(fmt,
            TagLib::ByteVector(
                reinterpret_cast<const char*>(meta.cover_art_bytes.data()),
                (unsigned int)meta.cover_art_bytes.size())));
        tag->setItem("covr", covers);
    }

    if (!file.save()) return "Failed to save";
    return "";
}

static std::string writeOgg(const std::string& path, const ReleaseMetadata& meta,
                             bool applyArt, bool applyTags, bool applyGenre)
{
    TagLib::Ogg::Vorbis::File file(path.c_str());
    if (!file.isValid()) return "Cannot open file";

    TagLib::Ogg::XiphComment* tag = file.tag();

    auto setField = [&](const TagLib::String& key, const std::string& val) {
        tag->removeFields(key);
        if (!val.empty())
            tag->addField(key, TagLib::String(val, TagLib::String::UTF8));
    };

    if (applyTags) {
        if (!meta.title.empty())  setField("TITLE",       meta.title);
        if (!meta.artist.empty()) setField("ARTIST",      meta.artist);
        if (!meta.album.empty())  setField("ALBUM",       meta.album);
        if (!meta.year.empty())   setField("DATE",        meta.year);
        if (meta.track_number > 0)
            setField("TRACKNUMBER", std::to_string(meta.track_number));
        if (meta.disc_number > 1)
            setField("DISCNUMBER", std::to_string(meta.disc_number));
    }
    if (applyGenre && !meta.genre.empty())
        setField("GENRE", meta.genre);

    // OGG art via METADATA_BLOCK_PICTURE (base64-encoded FLAC Picture block)
    if (applyArt && !meta.cover_art_bytes.empty()) {
        // Build a minimal FLAC Picture block manually
        // Picture type (4 bytes BE) + MIME length (4) + MIME + desc length (4) +
        // desc + width(4) + height(4) + depth(4) + indexed_colors(4) +
        // data length(4) + data
        std::string mime = detectMime(meta.cover_art_bytes);
        std::vector<uint8_t> block;
        auto push_be32 = [&](uint32_t v) {
            block.push_back((v >> 24) & 0xFF);
            block.push_back((v >> 16) & 0xFF);
            block.push_back((v >>  8) & 0xFF);
            block.push_back( v        & 0xFF);
        };
        push_be32(3);               // Front cover
        push_be32((uint32_t)mime.size());
        for (char c : mime) block.push_back((uint8_t)c);
        push_be32(0);               // Description length = 0
        push_be32(0); push_be32(0); // width, height (unknown)
        push_be32(0); push_be32(0); // depth, indexed colours
        push_be32((uint32_t)meta.cover_art_bytes.size());
        block.insert(block.end(),
                     meta.cover_art_bytes.begin(), meta.cover_art_bytes.end());

        // Base64 encode
        static const char b64[] =
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        std::string encoded;
        size_t i = 0;
        while (i + 2 < block.size()) {
            uint32_t tri = ((uint32_t)block[i] << 16) |
                           ((uint32_t)block[i+1] << 8) | block[i+2];
            encoded += b64[(tri >> 18) & 63];
            encoded += b64[(tri >> 12) & 63];
            encoded += b64[(tri >>  6) & 63];
            encoded += b64[ tri        & 63];
            i += 3;
        }
        if (i < block.size()) {
            uint32_t tri = (uint32_t)block[i] << 16;
            if (i + 1 < block.size()) tri |= (uint32_t)block[i+1] << 8;
            encoded += b64[(tri >> 18) & 63];
            encoded += b64[(tri >> 12) & 63];
            encoded += (i + 1 < block.size()) ? b64[(tri >> 6) & 63] : '=';
            encoded += '=';
        }
        tag->removeFields("METADATA_BLOCK_PICTURE");
        tag->addField("METADATA_BLOCK_PICTURE",
                      TagLib::String(encoded, TagLib::String::UTF8));
    }

    if (!file.save()) return "Failed to save";
    return "";
}

// ── Public API ────────────────────────────────────────────────────────────────

std::string writeMetadata(const std::string& filePath,
                          const ReleaseMetadata& meta,
                          bool applyArt, bool applyTags, bool applyGenre)
{
    std::string ext = normalizeExt(fs::path(filePath).extension().string());
    try {
        if (ext == ".mp3")
            return writeMp3(filePath, meta, applyArt, applyTags, applyGenre);
        if (ext == ".flac")
            return writeFlac(filePath, meta, applyArt, applyTags, applyGenre);
        if (ext == ".m4a" || ext == ".mp4" || ext == ".aac")
            return writeMp4(filePath, meta, applyArt, applyTags, applyGenre);
        if (ext == ".ogg" || ext == ".oga")
            return writeOgg(filePath, meta, applyArt, applyTags, applyGenre);
        return "Unsupported format: " + ext;
    } catch (const std::exception& e) {
        return std::string(e.what());
    }
}

std::vector<std::pair<std::string, std::string>>
writeMetadataBatch(const std::vector<std::string>& filePaths,
                   const ReleaseMetadata& meta,
                   bool applyArt, bool applyTags, bool applyGenre)
{
    std::vector<std::pair<std::string, std::string>> results;
    results.reserve(filePaths.size());
    for (auto& p : filePaths)
        results.emplace_back(p, writeMetadata(p, meta, applyArt, applyTags, applyGenre));
    return results;
}

ReadMetadata readMetadata(const std::string& filePath) {
    ReadMetadata rm;
    std::string ext = normalizeExt(fs::path(filePath).extension().string());
    try {
        if (ext == ".mp3") {
            TagLib::MPEG::File f(filePath.c_str());
            if (!f.isValid()) return rm;
            auto* tag = f.ID3v2Tag();
            if (!tag) return rm;
            auto get = [&](const TagLib::ByteVector& id) -> std::string {
                auto frames = tag->frameListMap()[id];
                if (frames.isEmpty()) return "";
                return frames.front()->toString().to8Bit(true);
            };
            rm.title  = get("TIT2");
            rm.artist = get("TPE1");
            rm.album  = get("TALB");
            rm.year   = get("TDRC");
            rm.genre  = get("TCON");
            rm.has_art = !tag->frameListMap()["APIC"].isEmpty();
        } else if (ext == ".flac") {
            TagLib::FLAC::File f(filePath.c_str());
            if (!f.isValid()) return rm;
            auto* tag = f.xiphComment();
            if (!tag) return rm;
            auto get = [&](const TagLib::String& k) -> std::string {
                auto it = tag->fieldListMap().find(k);
                if (it == tag->fieldListMap().end() || it->second.isEmpty())
                    return "";
                return it->second.front().to8Bit(true);
            };
            rm.title  = get("TITLE");
            rm.artist = get("ARTIST");
            rm.album  = get("ALBUM");
            rm.year   = get("DATE");
            rm.genre  = get("GENRE");
            rm.has_art = !f.pictureList().isEmpty();
        } else if (ext == ".m4a" || ext == ".mp4" || ext == ".aac") {
            TagLib::MP4::File f(filePath.c_str());
            if (!f.isValid()) return rm;
            auto* tag = f.tag();
            auto get = [&](const TagLib::String& k) -> std::string {
                auto it = tag->itemMap().find(k);
                if (it == tag->itemMap().end()) return "";
                auto sl = it->second.toStringList();
                return sl.isEmpty() ? "" : sl.front().to8Bit(true);
            };
            rm.title  = get("©nam");
            rm.artist = get("©ART");
            rm.album  = get("©alb");
            rm.year   = get("©day");
            rm.genre  = get("©gen");
            rm.has_art = tag->contains("covr");
        } else if (ext == ".ogg" || ext == ".oga") {
            TagLib::Ogg::Vorbis::File f(filePath.c_str());
            if (!f.isValid()) return rm;
            auto* tag = f.tag();
            auto get = [&](const TagLib::String& k) -> std::string {
                auto it = tag->fieldListMap().find(k);
                if (it == tag->fieldListMap().end() || it->second.isEmpty())
                    return "";
                return it->second.front().to8Bit(true);
            };
            rm.title  = get("TITLE");
            rm.artist = get("ARTIST");
            rm.album  = get("ALBUM");
            rm.year   = get("DATE");
            rm.genre  = get("GENRE");
            rm.has_art = tag->contains("METADATA_BLOCK_PICTURE");
        }
    } catch (...) {}
    return rm;
}
