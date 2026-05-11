#pragma once
#include "types.h"
#include "spotify_engine.h"
#include "remux_engine.h"

#include <QMainWindow>
#include <QMap>
#include <QVector>
#include <QPair>
#include <QString>
#include <QByteArray>
#include <QColor>
#include <atomic>

// Forward declarations
class QComboBox;
class QLineEdit;
class QListWidget;
class QListWidgetItem;
class QTabWidget;
class QTextEdit;
class QLabel;
class QProgressBar;
class QScrollArea;
class QWidget;
class QFrame;
class QCheckBox;
class QPushButton;

// ── Theme palette ─────────────────────────────────────────────────────────────

struct ThemePalette {
    QString bg, fg, btn, entry, accent, border;
};

// ── Main window ───────────────────────────────────────────────────────────────

class ArtiSync : public QMainWindow {
    Q_OBJECT

public:
    explicit ArtiSync(QWidget* parent = nullptr);
    ~ArtiSync() override = default;

    static QMap<QString, ThemePalette> themes();

private slots:
    void onBrowseRoot();
    void onArtistSelected(int index);
    void onAlbumSelected(int index);
    void onBatchPreview();
    void onRefreshPreview();
    void onExecuteRenameClicked();
    void onUndoRename();
    void onShowConvertDialog();
    void onOpenSettings();
    void onSidebarItemClicked(QListWidgetItem* item);
    void onSwitchTheme(const QString& name);
    void onFetchArt();

    // Called from worker threads via Qt::QueuedConnection
    void onArtistDetectDone(const QString& artistId, const QString& artistName,
                            const QVector<Release>& releases);
    void onAlbumDetectDone(const QString& releaseId);
    void onMetaLoaded(const ReleaseMetadata& meta);
    void onArtLoaded(const QByteArray& artBytes);
    void onBatchDone(const QVector<BatchResult>& results);

private:
    // ── Backend ───────────────────────────────────────────────────────────────
    SpotifyEngine* m_engine;
    RemuxEngine*   m_remux;

    // ── App state ─────────────────────────────────────────────────────────────
    QString m_rootDir;
    QString m_currentArtistId;
    QString m_currentReleaseId;
    QVector<Track>       m_currentTracks;
    ReleaseMetadata      m_currentMeta;
    QByteArray           m_currentArtBytes;
    QVector<MatchResult> m_episodesData;
    QVector<BatchResult> m_batchData;
    QVector<QPair<QString,QString>> m_renameHistory;
    QVector<Release>     m_knownReleases;
    QString              m_currentTheme = "Dark";
    bool                 m_previewTextMode = false;

    // Settings state
    QString m_spotifyId, m_spotifySecret;
    bool    m_autoRemux         = false;
    QString m_autoRemuxTarget   = ".flac";
    QString m_autoRemuxQuality  = "best";
    bool    m_autoRemuxDelSrc   = true;
    bool    m_applyArt          = true;
    bool    m_applyTags         = true;
    bool    m_applyGenre        = true;

    // ── UI Widgets ────────────────────────────────────────────────────────────
    QComboBox*   m_artistCombo;
    QComboBox*   m_albumCombo;
    QLineEdit*   m_rootPathEdit;
    QListWidget* m_sidebar;
    QTabWidget*  m_tabWidget;
    QTextEdit*   m_previewText;
    QTextEdit*   m_logText;
    QScrollArea* m_previewScroll;
    QWidget*     m_previewInner;
    QLabel*      m_artLabel;
    QProgressBar* m_progressBar;
    QLabel*      m_progressLabel;

    // Status dots (simple QLabel used as indicator)
    QLabel* m_statusDetect;
    QLabel* m_statusMatched;
    QLabel* m_statusMissing;
    QLabel* m_statusSpotify;

    // Chip toggles
    QPushButton* m_chipArt;
    QPushButton* m_chipTags;
    QPushButton* m_chipGenre;

    // Sidebar item data (release id → index in m_knownReleases)
    QMap<QString, int> m_sidebarMap;
    std::atomic<int>   m_sidebarGeneration{0};

    // ── UI builder helpers ────────────────────────────────────────────────────
    void setupUI();
    void setupMenuBar();
    void buildStatusBar(QWidget* parent);
    void buildSidebar(QWidget* parent);
    void buildCentre(QWidget* parent);
    void buildArtPanel(QWidget* parent);
    void buildFooter(QWidget* parent);

    void applyTheme(const QString& name);
    QString stylesheet(const ThemePalette& p) const;

    void updateStatusDot(QLabel* lbl, const QString& text, const QString& color = "");
    void showToast(const QString& text);
    void setProgress(int matched, int total);
    void updateArtPanel(const QByteArray& bytes);
    void updateMetaPanel(const ReleaseMetadata& meta);
    void rebuildTrackRows(const QVector<MatchResult>& epData,
                          const QVector<Track>& missing);
    void addTrackRow(const Track& track, const MatchResult* match);

    void populateSidebar(const QVector<Release>& releases);
    void highlightSidebarRow(const QString& releaseId);
    void loadSidebarThumbs(QVector<Release> releases, int generation);

    void showReviewDialog();
    void executeRename();
    QPair<QVector<std::tuple<QString,QString,QString,int,int>>, int>
        runPreRemux(QVector<std::tuple<QString,QString,QString,int,int>>& pairs);

    void saveConfig();
    void loadConfig();

    // Async launchers
    void autoDetectArtist(const QString& name);
    void autoDetectAlbum(const QString& name);
    void loadMetaAndArt(const QString& releaseId);
};
