cmake_minimum_required(VERSION 3.16)
project(MusicManager VERSION 2.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

include(FetchContent)
find_package(PkgConfig QUIET)

# ── Qt6 ───────────────────────────────────────────────────────────────────────
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)

# ── nlohmann/json ─────────────────────────────────────────────────────────────
# Prefer a system/installed copy (e.g. from a Flatpak module); fetch otherwise.
find_package(nlohmann_json QUIET)
if(NOT nlohmann_json_FOUND)
    FetchContent_Declare(nlohmann_json
        GIT_REPOSITORY https://github.com/nlohmann/json.git
        GIT_TAG        v3.11.3
        GIT_SHALLOW    TRUE
    )
    set(JSON_BuildTests OFF CACHE BOOL "" FORCE)
    set(JSON_Install    OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(nlohmann_json)
endif()

# ── libcurl ───────────────────────────────────────────────────────────────────
# Prefer system curl (available in KDE SDK); fetch a static build otherwise.
find_package(CURL QUIET)
if(CURL_FOUND)
    set(CURL_LINK_TARGET CURL::libcurl)
else()
    FetchContent_Declare(curl
        GIT_REPOSITORY https://github.com/curl/curl.git
        GIT_TAG        curl-8_7_1
        GIT_SHALLOW    TRUE
    )
    set(BUILD_CURL_EXE       OFF CACHE BOOL "" FORCE)
    set(BUILD_SHARED_LIBS    OFF CACHE BOOL "" FORCE)
    set(CURL_STATICLIB       ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_DICT    ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_FILE    ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_FTP     ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_GOPHER  ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_IMAP    ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_LDAP    ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_LDAPS   ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_MQTT    ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_POP3    ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_RTSP    ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_SMB     ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_SMTP    ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_TELNET  ON  CACHE BOOL "" FORCE)
    set(CURL_DISABLE_TFTP    ON  CACHE BOOL "" FORCE)
    set(CURL_USE_LIBPSL      OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(curl)
    set(CURL_LINK_TARGET libcurl)
endif()

# ── TagLib ────────────────────────────────────────────────────────────────────
# Prefer system taglib via pkg-config (available in KDE SDK); fetch otherwise.
if(PKG_CONFIG_FOUND)
    pkg_check_modules(TAGLIB QUIET IMPORTED_TARGET taglib)
endif()
if(TAGLIB_FOUND)
    set(TAGLIB_LINK_TARGET PkgConfig::TAGLIB)
    set(TAGLIB_EXTRA_INCLUDES "")
else()
    FetchContent_Declare(taglib
        GIT_REPOSITORY https://github.com/taglib/taglib.git
        GIT_TAG        v2.0.2
        GIT_SHALLOW    TRUE
    )
    set(BUILD_SHARED_LIBS     OFF CACHE BOOL "" FORCE)
    set(TAGLIB_BUILD_TESTS    OFF CACHE BOOL "" FORCE)
    set(TAGLIB_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(taglib)
    set(TAGLIB_LINK_TARGET tag)
    set(TAGLIB_EXTRA_INCLUDES
        ${taglib_SOURCE_DIR}
        ${taglib_SOURCE_DIR}/taglib
        ${taglib_SOURCE_DIR}/taglib/toolkit
        ${taglib_SOURCE_DIR}/taglib/mpeg
        ${taglib_SOURCE_DIR}/taglib/mpeg/id3v2
        ${taglib_SOURCE_DIR}/taglib/mpeg/id3v2/frames
        ${taglib_SOURCE_DIR}/taglib/flac
        ${taglib_SOURCE_DIR}/taglib/mp4
        ${taglib_SOURCE_DIR}/taglib/ogg
        ${taglib_SOURCE_DIR}/taglib/ogg/vorbis
    )
endif()

# ── Qt resources ──────────────────────────────────────────────────────────────
qt_add_resources(RESOURCES resources/resources.qrc)

# ── Sources ───────────────────────────────────────────────────────────────────
set(SOURCES
    main.cpp
    fuzzy.cpp
    http_client.cpp
    base_engine.cpp
    metadata_writer.cpp
    remux_engine.cpp
    spotify_engine.cpp
    music_organizer.cpp
)

add_executable(${PROJECT_NAME} ${SOURCES} ${RESOURCES})

if(NOT CURL_FOUND)
    target_compile_definitions(${PROJECT_NAME} PRIVATE CURL_STATICLIB)
endif()

target_link_libraries(${PROJECT_NAME}
    PRIVATE
        Qt6::Core
        Qt6::Gui
        Qt6::Widgets
        ${CURL_LINK_TARGET}
        ${TAGLIB_LINK_TARGET}
        nlohmann_json::nlohmann_json
)

target_include_directories(${PROJECT_NAME}
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        $<$<NOT:$<BOOL:${CURL_FOUND}>>:${curl_SOURCE_DIR}/include>
        $<$<NOT:$<BOOL:${CURL_FOUND}>>:${curl_BINARY_DIR}/include/curl>
        ${TAGLIB_EXTRA_INCLUDES}
)

if(UNIX AND NOT APPLE)
    find_package(OpenSSL REQUIRED)
    target_link_libraries(${PROJECT_NAME} PRIVATE OpenSSL::SSL OpenSSL::Crypto)
endif()

install(TARGETS ${PROJECT_NAME} RUNTIME DESTINATION bin)
install(DIRECTORY DESTINATION share/applications)
install(DIRECTORY DESTINATION share/icons)
