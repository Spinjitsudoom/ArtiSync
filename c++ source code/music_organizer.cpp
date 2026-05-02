#include "music_organizer.h"
#include "metadata_writer.h"
#include "fuzzy.h"

#include <QApplication>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QGridLayout>
#include <QLabel>
#include <QPushButton>
#include <QLineEdit>
#include <QComboBox>
#include <QCheckBox>
#include <QListWidget>
#include <QTabWidget>
#include <QTextEdit>
#include <QScrollArea>
#include <QProgressBar>
#include <QMenuBar>
#include <QMenu>
#include <QAction>
#include <QFileDialog>
#include <QMessageBox>
#include <QDialog>
#include <QFrame>
#include <QSplitter>
#include <QTimer>
#include <QThread>
#include <QPixmap>
#include <QImage>
#include <QPainter>
#include <QFontMetrics>
#include <QJsonDocument>
#include <QJsonObject>
#include <QDir>
#include <QFileInfo>
#include <QDirIterator>

#include <filesystem>
#include <thread>
#include <functional>

namespace fs = std::filesystem;

// ── Theme definitions ─────────────────────────────────────────────────────────

QMap<QString, ThemePalette> MusicManager::themes() {
    return {
        {"Dark",     {"#121212","#e0e0e0","#2d2d2d","#1e1e1e","#0078d4","#333333"}},
        {"Light",    {"#ffffff","#202124","#f1f3f4","#f8f9fa","#1a73e8","#dadce0"}},
        {"Midnight", {"#0b0e14","#8f9bb3","#1a212e","#151a23","#3366ff","#222b45"}},
        {"Emerald",  {"#061006","#a3b3a3","#102010","#0b160b","#009688","#1b301b"}},
        {"Amethyst", {"#120d1a","#b3a3cc","#1f162e","#181223","#9b59b6","#2d2245"}},
        {"Crimson",  {"#1a0a0a","#d6b4b4","#2e1616","#241212","#e74c3c","#452222"}},
        {"Forest",   {"#0d1a12","#b4d6c1","#162e1f","#12241a","#2ecc71","#22452d"}},
        {"Ocean",    {"#0a161a","#b4ccd6","#16282e","#122024","#3498db","#223a45"}},
        {"Slate",    {"#1c232b","#cbd5e0","#2d3748","#242d38","#a0aec0","#4a5568"}},
    };
}

// ── Constructor ───────────────────────────────────────────────────────────────

MusicManager::MusicManager(QWidget* parent)
    : QMainWindow(parent)
    , m_engine(new SpotifyEngine())
    , m_remux(new RemuxEngine())
{
    setWindowTitle("Music Manager Ultimate v2.1.0");
    resize(1400, 980);

    loadConfig();
    if (!m_spotifyId.isEmpty() && !m_spotifySecret.isEmpty())
        m_engine->configure(m_spotifyId.toStdString(), m_spotifySecret.toStdString());

    setupUI();
    setupMenuBar();
    applyTheme(m_currentTheme);

    if (!m_rootDir.isEmpty() && QDir(m_rootDir).exists()) {
        m_rootPathEdit->setText(m_rootDir);
        onArtistSelected(0);
    }
}

// ── UI Setup ──────────────────────────────────────────────────────────────────

void MusicManager::setupUI() {
    auto* central = new QWidget(this);
    setCentralWidget(central);
    auto* mainLayout = new QVBoxLayout(central);
    mainLayout->setSpacing(0);
    mainLayout->setContentsMargins(0, 0, 0, 0);

    // ── Toolbar row ───────────────────────────────────────────────────────────
    auto* toolbar = new QWidget;
    auto* tbLayout = new QHBoxLayout(toolbar);
    tbLayout->setContentsMargins(14, 8, 14, 8);

    auto* browseBtn = new QPushButton("Browse");
    browseBtn->setFixedWidth(80);
    connect(browseBtn, &QPushButton::clicked, this, &MusicManager::onBrowseRoot);
    tbLayout->addWidget(browseBtn);

    m_rootPathEdit = new QLineEdit;
    tbLayout->addWidget(m_rootPathEdit, 1);

    m_artistCombo = new QComboBox;
    m_artistCombo->setMinimumWidth(190);
    connect(m_artistCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, &MusicManager::onArtistSelected);
    tbLayout->addWidget(m_artistCombo);

    tbLayout->addWidget(new QLabel("›"));

    m_albumCombo = new QComboBox;
    m_albumCombo->setMinimumWidth(170);
    connect(m_albumCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, &MusicManager::onAlbumSelected);
    tbLayout->addWidget(m_albumCombo);

    auto* batchBtn = new QPushButton("Batch");
    batchBtn->setFixedWidth(60);
    connect(batchBtn, &QPushButton::clicked, this, &MusicManager::onBatchPreview);
    tbLayout->addWidget(batchBtn);

    mainLayout->addWidget(toolbar);

    // ── Status bar ────────────────────────────────────────────────────────────
    auto* statusBar = new QWidget;
    auto* statusLayout = new QHBoxLayout(statusBar);
    statusLayout->setContentsMargins(14, 2, 14, 2);

    m_statusDetect  = new QLabel("Ready");
    m_statusMatched = new QLabel("0 matched");
    m_statusMissing = new QLabel("0 missing");
    m_statusSpotify = new QLabel("Spotify");
    for (auto* l : {m_statusDetect, m_statusMatched, m_statusMissing, m_statusSpotify}) {
        l->setStyleSheet("color: #555; font-size: 9pt;");
        statusLayout->addWidget(l);
        statusLayout->addSpacing(14);
    }
    statusLayout->addStretch();
    mainLayout->addWidget(statusBar);

    auto* sepLine = new QFrame;
    sepLine->setFrameShape(QFrame::HLine);
    mainLayout->addWidget(sepLine);

    // ── Body ──────────────────────────────────────────────────────────────────
    auto* body = new QWidget;
    auto* bodyLayout = new QHBoxLayout(body);
    bodyLayout->setSpacing(0);
    bodyLayout->setContentsMargins(0, 0, 0, 0);

    buildSidebar(body);

    // Centre
    auto* centre = new QWidget;
    buildCentre(centre);
    bodyLayout->addWidget(centre, 1);

    buildArtPanel(body);

    mainLayout->addWidget(body, 1);

    // ── Footer ────────────────────────────────────────────────────────────────
    auto* footSep = new QFrame;
    footSep->setFrameShape(QFrame::HLine);
    mainLayout->addWidget(footSep);

    auto* footer = new QWidget;
    auto* footLayout = new QHBoxLayout(footer);
    footLayout->setContentsMargins(14, 8, 14, 8);

    auto* progWrap = new QWidget;
    auto* progLayout = new QVBoxLayout(progWrap);
    progLayout->setContentsMargins(0,0,0,0);
    m_progressBar = new QProgressBar;
    m_progressBar->setRange(0, 100);
    m_progressBar->setValue(0);
    m_progressBar->setTextVisible(false);
    m_progressBar->setFixedHeight(4);
    progLayout->addWidget(m_progressBar);
    m_progressLabel = new QLabel("No album loaded");
    m_progressLabel->setStyleSheet("color:#555; font-size:9pt;");
    progLayout->addWidget(m_progressLabel);
    footLayout->addWidget(progWrap, 1);

    auto* convertBtn = new QPushButton("Convert");
    convertBtn->setFixedWidth(70);
    connect(convertBtn, &QPushButton::clicked, this, &MusicManager::onShowConvertDialog);

    auto* execBtn = new QPushButton("Execute Rename + Tag");
    connect(execBtn, &QPushButton::clicked, this, &MusicManager::onExecuteRenameClicked);

    auto* refreshBtn = new QPushButton("Refresh");
    refreshBtn->setFixedWidth(70);
    connect(refreshBtn, &QPushButton::clicked, this, &MusicManager::onRefreshPreview);

    auto* undoBtn = new QPushButton("Undo");
    undoBtn->setFixedWidth(60);
    connect(undoBtn, &QPushButton::clicked, this, &MusicManager::onUndoRename);

    footLayout->addWidget(convertBtn);
    footLayout->addWidget(execBtn);
    footLayout->addWidget(refreshBtn);
    footLayout->addWidget(undoBtn);

    mainLayout->addWidget(footer);
}

void MusicManager::buildSidebar(QWidget* parent) {
    auto* sidebar = new QWidget(parent);
    sidebar->setFixedWidth(360);
    auto* layout = new QVBoxLayout(sidebar);
    layout->setSpacing(0);
    layout->setContentsMargins(0, 0, 0, 0);

    auto* hdr = new QLabel("  SPOTIFY RELEASES");
    hdr->setStyleSheet("background:#2d2d2d; color:#aaa; font-size:10pt; font-weight:bold; padding:6px;");
    layout->addWidget(hdr);

    m_sidebar = new QListWidget;
    m_sidebar->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_sidebar->setIconSize(QSize(64, 64));
    m_sidebar->setSpacing(1);
    connect(m_sidebar, &QListWidget::itemClicked,
            this, &MusicManager::onSidebarItemClicked);
    layout->addWidget(m_sidebar, 1);

    parent->layout()->addWidget(sidebar);
}

void MusicManager::buildCentre(QWidget* centre) {
    auto* layout = new QVBoxLayout(centre);
    layout->setSpacing(0);
    layout->setContentsMargins(0, 0, 0, 0);

    m_tabWidget = new QTabWidget;

    // Preview tab — scrollable visual rows
    auto* previewPage = new QWidget;
    auto* pvLayout = new QVBoxLayout(previewPage);
    pvLayout->setContentsMargins(0,0,0,0);

    m_previewScroll = new QScrollArea;
    m_previewScroll->setWidgetResizable(true);
    m_previewScroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_previewInner = new QWidget;
    m_previewInner->setLayout(new QVBoxLayout);
    m_previewInner->layout()->setAlignment(Qt::AlignTop);
    static_cast<QVBoxLayout*>(m_previewInner->layout())->setSpacing(2);
    m_previewScroll->setWidget(m_previewInner);
    pvLayout->addWidget(m_previewScroll, 1);

    // Also a plain text widget for batch mode
    m_previewText = new QTextEdit;
    m_previewText->setReadOnly(true);
    m_previewText->setFont(QFont("Courier", 10));
    m_previewText->hide();

    m_tabWidget->addTab(previewPage, "Preview");

    // Log tab
    m_logText = new QTextEdit;
    m_logText->setReadOnly(true);
    m_logText->setFont(QFont("Courier", 10));
    m_tabWidget->addTab(m_logText, "Log");

    layout->addWidget(m_tabWidget, 1);
}

void MusicManager::buildArtPanel(QWidget* parent) {
    auto* panel = new QWidget(parent);
    panel->setFixedWidth(220);
    auto* layout = new QVBoxLayout(panel);
    layout->setContentsMargins(8, 8, 8, 8);
    layout->setSpacing(6);

    m_artLabel = new QLabel;
    m_artLabel->setFixedSize(200, 200);
    m_artLabel->setAlignment(Qt::AlignCenter);
    m_artLabel->setText("♪\n\nNo artwork");
    m_artLabel->setStyleSheet("background:#1e1e1e; color:#333; border-radius:4px;");
    layout->addWidget(m_artLabel);

    // Metadata rows
    struct Row { QString label; QLabel** target; };
    QLabel *artistLbl = new QLabel("—");
    QLabel *albumLbl  = new QLabel("—");
    QLabel *yearLbl   = new QLabel("—");
    QLabel *genreLbl  = new QLabel("—");

    for (auto [txt, w] : {
            std::make_pair(QString("Artist"), artistLbl),
            std::make_pair(QString("Album"),  albumLbl),
            std::make_pair(QString("Year"),   yearLbl),
            std::make_pair(QString("Genre"),  genreLbl)})
    {
        auto* row = new QWidget;
        auto* rl  = new QHBoxLayout(row);
        rl->setContentsMargins(0,0,0,0);
        auto* key = new QLabel(txt);
        key->setStyleSheet("color:#555; font-size:8pt; font-weight:bold;");
        key->setFixedWidth(40);
        w->setWordWrap(true);
        w->setStyleSheet("font-size:9pt;");
        rl->addWidget(key);
        rl->addWidget(w, 1);
        layout->addWidget(row);
    }
    // Store pointers for later updates
    m_artLabel->setProperty("artistLbl", QVariant::fromValue<QObject*>(artistLbl));
    m_artLabel->setProperty("albumLbl",  QVariant::fromValue<QObject*>(albumLbl));
    m_artLabel->setProperty("yearLbl",   QVariant::fromValue<QObject*>(yearLbl));
    m_artLabel->setProperty("genreLbl",  QVariant::fromValue<QObject*>(genreLbl));

    layout->addWidget(new QFrame); // separator

    // Apply-to-files chip toggles
    auto* chipHdr = new QLabel("APPLY TO FILES");
    chipHdr->setStyleSheet("color:#555; font-size:8pt; font-weight:bold;");
    layout->addWidget(chipHdr);

    auto* chipRow = new QWidget;
    auto* chipLayout = new QHBoxLayout(chipRow);
    chipLayout->setContentsMargins(0,0,0,0);
    chipLayout->setSpacing(4);

    m_chipArt   = new QPushButton("Art");
    m_chipTags  = new QPushButton("Tags");
    m_chipGenre = new QPushButton("Genre");
    for (auto* btn : {m_chipArt, m_chipTags, m_chipGenre}) {
        btn->setCheckable(true);
        btn->setChecked(true);
        btn->setFixedHeight(26);
        chipLayout->addWidget(btn);
    }
    connect(m_chipArt,   &QPushButton::toggled, [this](bool v){ m_applyArt   = v; });
    connect(m_chipTags,  &QPushButton::toggled, [this](bool v){ m_applyTags  = v; });
    connect(m_chipGenre, &QPushButton::toggled, [this](bool v){ m_applyGenre = v; });
    layout->addWidget(chipRow);

    auto* fetchArtBtn = new QPushButton("Fetch Artwork");
    connect(fetchArtBtn, &QPushButton::clicked, this, &MusicManager::onFetchArt);
    layout->addWidget(fetchArtBtn);

    layout->addStretch();
    parent->layout()->addWidget(panel);
}

// ── Menu ──────────────────────────────────────────────────────────────────────

void MusicManager::setupMenuBar() {
    auto* mb   = menuBar();
    auto* file = mb->addMenu("File");

    file->addAction("Settings…", this, &MusicManager::onOpenSettings);

    auto* themeMenu = file->addMenu("Theme");
    for (auto& name : themes().keys())
        themeMenu->addAction(name, [this, name]{ onSwitchTheme(name); });

    file->addAction("Undo Last Rename", this, &MusicManager::onUndoRename);
    file->addSeparator();
    file->addAction("Exit", qApp, &QApplication::quit);
}

// ── Theme ─────────────────────────────────────────────────────────────────────

void MusicManager::applyTheme(const QString& name) {
    m_currentTheme = name;
    auto th = themes();
    if (!th.contains(name)) return;
    const auto& p = th[name];
    qApp->setStyleSheet(stylesheet(p));
    saveConfig();
}

QString MusicManager::stylesheet(const ThemePalette& p) const {
    return QString(R"(
QMainWindow, QWidget {
    background: %1; color: %2;
}
QPushButton {
    background: %3; color: %2; border: 1px solid %6;
    border-radius: 4px; padding: 4px 10px;
}
QPushButton:hover  { background: %5; color: #fff; }
QPushButton:checked { background: %5; color: #fff; border-color: %5; }
QPushButton#execBtn { background: %5; color: #fff; border-color: %5; }
QLineEdit, QComboBox, QTextEdit, QListWidget {
    background: %4; color: %2; border: 1px solid %6;
    border-radius: 4px; padding: 3px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { background: %4; color: %2; selection-background-color: %5; }
QTabWidget::pane   { border: 1px solid %6; }
QTabBar::tab       { background: %1; color: #555; padding: 6px 14px; border: none; }
QTabBar::tab:selected { color: %5; border-bottom: 2px solid %5; }
QScrollBar:vertical   { background: %1; width: 8px; }
QScrollBar::handle:vertical { background: %3; border-radius: 4px; }
QScrollBar:horizontal { background: %1; height: 8px; }
QScrollBar::handle:horizontal { background: %3; border-radius: 4px; }
QMenuBar { background: %1; color: %2; }
QMenuBar::item:selected { background: %5; }
QMenu { background: %4; color: %2; border: 1px solid %6; }
QMenu::item:selected { background: %5; color: #fff; }
QProgressBar { background: %3; border: none; border-radius: 2px; }
QProgressBar::chunk { background: %5; border-radius: 2px; }
QCheckBox { color: %2; }
QCheckBox::indicator { background: %4; border: 1px solid %6; width:12px; height:12px; }
QCheckBox::indicator:checked { background: %5; border-color: %5; }
QLabel#statusLabel { color: #555; font-size: 9pt; }
QFrame[frameShape="4"], QFrame[frameShape="5"] { color: %6; }
    )").arg(p.bg, p.fg, p.btn, p.entry, p.accent, p.border);
}

// ── Status helpers ────────────────────────────────────────────────────────────

void MusicManager::updateStatusDot(QLabel* lbl, const QString& text,
                                    const QString& color)
{
    lbl->setText(text);
    if (!color.isEmpty())
        lbl->setStyleSheet("color:" + color + "; font-size:9pt;");
}

void MusicManager::setProgress(int matched, int total) {
    int pct = total > 0 ? (100 * matched / total) : 0;
    m_progressBar->setValue(pct);
    m_progressLabel->setText(
        total > 0 ? QString("%1 / %2 tracks matched").arg(matched).arg(total)
                  : "No album loaded");
}

// ── Art panel helpers ─────────────────────────────────────────────────────────

void MusicManager::updateArtPanel(const QByteArray& bytes) {
    m_currentArtBytes = bytes;
    if (bytes.isEmpty()) {
        m_artLabel->setPixmap({});
        m_artLabel->setText("♪\n\nNo artwork");
        return;
    }
    QImage img;
    img.loadFromData(reinterpret_cast<const uchar*>(bytes.data()),
                     (int)bytes.size());
    if (img.isNull()) {
        m_artLabel->setText("Decode error");
        return;
    }
    m_artLabel->setPixmap(
        QPixmap::fromImage(img).scaled(200, 200, Qt::KeepAspectRatio,
                                        Qt::SmoothTransformation));
    m_artLabel->setText("");
}

void MusicManager::updateMetaPanel(const ReleaseMetadata& meta) {
    m_currentMeta = meta;
    auto set = [&](const char* prop, const std::string& val) {
        if (auto* lbl = qobject_cast<QLabel*>(
                m_artLabel->property(prop).value<QObject*>()))
            lbl->setText(val.empty() ? "—" : QString::fromStdString(val));
    };
    set("artistLbl", meta.artist);
    set("albumLbl",  meta.album);
    set("yearLbl",   meta.year);
    set("genreLbl",  meta.genre);
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

void MusicManager::populateSidebar(const QVector<Release>& releases) {
    m_sidebar->clear();
    m_sidebarMap.clear();
    m_knownReleases = releases;

    // Placeholder: dark square with faint music note
    QPixmap ph(64, 64);
    ph.fill(QColor("#1e1e1e"));
    {
        QPainter p(&ph);
        p.setPen(QColor("#333333"));
        p.setFont(QFont("sans-serif", 22));
        p.drawText(QRect(0, 0, 64, 64), Qt::AlignCenter, QStringLiteral("♪"));
    }
    QIcon phIcon(ph);

    for (int i = 0; i < releases.size(); ++i) {
        const auto& r = releases[i];
        QString text = QString::fromStdString(r.title) + "\n" +
                       QString::fromStdString(r.year) + "  " +
                       QString::fromStdString(r.type);
        auto* item = new QListWidgetItem(text, m_sidebar);
        item->setIcon(phIcon);
        item->setSizeHint(QSize(0, 78));
        item->setData(Qt::UserRole, QString::fromStdString(r.id));
        m_sidebarMap[QString::fromStdString(r.id)] = i;
    }

    // Load thumbnails in background; generation guards against stale updates
    int gen = ++m_sidebarGeneration;
    std::thread([this, releases, gen]() {
        loadSidebarThumbs(releases, gen);
    }).detach();
}

void MusicManager::highlightSidebarRow(const QString& releaseId) {
    for (int i = 0; i < m_sidebar->count(); ++i) {
        auto* item = m_sidebar->item(i);
        bool sel = item->data(Qt::UserRole).toString() == releaseId;
        item->setSelected(sel);
    }
}

void MusicManager::loadSidebarThumbs(QVector<Release> releases, int generation) {
    for (int i = 0; i < releases.size(); ++i) {
        if (m_sidebarGeneration.load() != generation) return;

        if (i > 0)
            std::this_thread::sleep_for(std::chrono::milliseconds(30));

        if (m_sidebarGeneration.load() != generation) return;

        auto bytes = m_engine->getCoverArtBytes(releases[i].id);
        if (bytes.empty()) continue;

        if (m_sidebarGeneration.load() != generation) return;

        QByteArray qbytes(reinterpret_cast<const char*>(bytes.data()), (int)bytes.size());

        QMetaObject::invokeMethod(this, [this, qbytes, i, generation]() {
            if (m_sidebarGeneration.load() != generation) return;
            auto* item = m_sidebar->item(i);
            if (!item) return;

            QImage img;
            img.loadFromData(reinterpret_cast<const uchar*>(qbytes.constData()),
                             qbytes.size());
            if (img.isNull()) return;

            // Scale to fill 64×64 and crop from centre
            QPixmap pm = QPixmap::fromImage(img).scaled(
                64, 64, Qt::KeepAspectRatioByExpanding, Qt::SmoothTransformation);
            if (pm.width() > 64 || pm.height() > 64)
                pm = pm.copy((pm.width() - 64) / 2, (pm.height() - 64) / 2, 64, 64);

            item->setIcon(QIcon(pm));
        }, Qt::QueuedConnection);
    }
}

void MusicManager::onSidebarItemClicked(QListWidgetItem* item) {
    QString rid = item->data(Qt::UserRole).toString();
    m_currentReleaseId = rid;
    updateStatusDot(m_statusDetect,
        "Loading " + item->text().split('\n').first() + "…", "#0078d4");

    std::thread([this, rid]() {
        auto tracks = m_engine->getTracks(rid.toStdString());
        QVector<Track> qtracks(tracks.begin(), tracks.end());
        QMetaObject::invokeMethod(this, [this, rid, qtracks]() {
            m_currentTracks = qtracks;
            onRefreshPreview();
        }, Qt::QueuedConnection);
        loadMetaAndArt(rid);
    }).detach();
}

// ── Artist / Album selection ──────────────────────────────────────────────────

void MusicManager::onBrowseRoot() {
    QString path = QFileDialog::getExistingDirectory(this, "Select Music Root");
    if (path.isEmpty()) return;
    m_rootDir = path;
    m_rootPathEdit->setText(path);
    saveConfig();
    // Refresh artist list
    QDir d(path);
    QStringList dirs = d.entryList(QDir::Dirs | QDir::NoDotAndDotDot, QDir::Name);
    m_artistCombo->clear();
    m_artistCombo->addItems(dirs);
    if (!dirs.isEmpty()) onArtistSelected(0);
}

void MusicManager::onArtistSelected(int /*index*/) {
    QString artist = m_artistCombo->currentText();
    if (artist.isEmpty()) return;
    QString artistPath = m_rootDir + "/" + artist;
    // Populate album combo
    QDir d(artistPath);
    QStringList albums = d.entryList(QDir::Dirs | QDir::NoDotAndDotDot, QDir::Name);
    m_albumCombo->clear();
    m_albumCombo->addItems(albums);
    if (!albums.isEmpty()) onAlbumSelected(0);
    autoDetectArtist(artist);
}

void MusicManager::onAlbumSelected(int /*index*/) {
    QString album = m_albumCombo->currentText();
    if (album.isEmpty() || m_artistCombo->currentText().isEmpty()) return;
    if (!m_knownReleases.isEmpty())
        autoDetectAlbum(album);
}

// ── Auto-detect ───────────────────────────────────────────────────────────────

void MusicManager::autoDetectArtist(const QString& name) {
    if (!m_engine->isConfigured()) {
        updateStatusDot(m_statusDetect, "Add Spotify creds in Settings", "#e74c3c");
        return;
    }
    updateStatusDot(m_statusDetect, "Searching '" + name + "'…", "#0078d4");

    std::thread([this, name]() {
        auto artists = m_engine->searchArtists(name.toStdString());
        if (artists.empty()) {
            QMetaObject::invokeMethod(this, [this, name](){
                updateStatusDot(m_statusDetect,
                    "No results for '" + name + "'", "#e67e22");
            }, Qt::QueuedConnection);
            return;
        }

        // Fuzzy-pick best artist
        std::vector<std::string> names;
        for (auto& a : artists) names.push_back(a.name);
        auto [bestName, score] = fuzzy::extract_one(
            name.toStdString(), names, fuzzy::token_set_ratio);
        std::string bestId;
        for (auto& a : artists)
            if (a.name == bestName) { bestId = a.id; break; }
        if (bestId.empty()) bestId = artists[0].id;

        auto releases = m_engine->getReleases(bestId);
        QVector<Release> qreleases(releases.begin(), releases.end());
        QString qBestId   = QString::fromStdString(bestId);
        QString qBestName = QString::fromStdString(bestName);

        QMetaObject::invokeMethod(this, [this, qBestId, qBestName, qreleases](){
            onArtistDetectDone(qBestId, qBestName, qreleases);
        }, Qt::QueuedConnection);

        // Now auto-detect album
        QString album = m_albumCombo->currentText();
        if (!album.isEmpty()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            QMetaObject::invokeMethod(this, [this, album](){
                autoDetectAlbum(album);
            }, Qt::QueuedConnection);
        }
    }).detach();
}

void MusicManager::onArtistDetectDone(const QString& artistId,
                                       const QString& artistName,
                                       const QVector<Release>& releases)
{
    m_currentArtistId = artistId;
    updateStatusDot(m_statusDetect, "✓ " + artistName, "#2ecc71");
    updateStatusDot(m_statusSpotify,
        m_engine->isConfigured() ? "Spotify connected" : "Spotify",
        m_engine->isConfigured() ? "#2ecc71" : "#555");
    populateSidebar(releases);
}

void MusicManager::autoDetectAlbum(const QString& name) {
    if (m_knownReleases.isEmpty()) return;

    std::vector<std::string> titles;
    for (auto& r : m_knownReleases) titles.push_back(r.title);

    auto [bestTitle, score] = fuzzy::extract_one(
        name.toStdString(), titles, fuzzy::token_set_ratio);
    if (score < 40) {
        updateStatusDot(m_statusDetect, "No match for '" + name + "'", "#e67e22");
        return;
    }

    for (auto& r : m_knownReleases) {
        if (r.title == bestTitle) {
            m_currentReleaseId = QString::fromStdString(r.id);
            highlightSidebarRow(m_currentReleaseId);
            updateStatusDot(m_statusDetect,
                "✓ " + QString::fromStdString(r.title) + " (" +
                QString::fromStdString(r.year) + ")", "#2ecc71");

            std::thread([this, id = r.id]() {
                auto tracks = m_engine->getTracks(id);
                QVector<Track> qt(tracks.begin(), tracks.end());
                QMetaObject::invokeMethod(this, [this, qt](){
                    m_currentTracks = qt;
                    onRefreshPreview();
                }, Qt::QueuedConnection);
                loadMetaAndArt(QString::fromStdString(id));
            }).detach();
            return;
        }
    }
}

void MusicManager::onAlbumDetectDone(const QString& /*releaseId*/) {}

void MusicManager::loadMetaAndArt(const QString& releaseId) {
    std::thread([this, rid = releaseId.toStdString()]() {
        auto meta = m_engine->getReleaseMetadata(rid);
        auto art  = m_engine->getCoverArtBytes(rid);
        QByteArray qart(reinterpret_cast<const char*>(art.data()), (int)art.size());
        QMetaObject::invokeMethod(this, [this, meta, qart](){
            onMetaLoaded(meta);
            onArtLoaded(qart);
        }, Qt::QueuedConnection);
    }).detach();
}

void MusicManager::onMetaLoaded(const ReleaseMetadata& meta) {
    updateMetaPanel(meta);
}

void MusicManager::onArtLoaded(const QByteArray& bytes) {
    updateArtPanel(bytes);
}

void MusicManager::onFetchArt() {
    if (m_currentReleaseId.isEmpty()) {
        QMessageBox::warning(this, "No Release", "Select a release first.");
        return;
    }
    updateStatusDot(m_statusDetect, "Fetching artwork…", "#0078d4");
    std::thread([this, rid = m_currentReleaseId.toStdString()](){
        auto art = m_engine->getCoverArtBytes(rid);
        QByteArray qart(reinterpret_cast<const char*>(art.data()), (int)art.size());
        QMetaObject::invokeMethod(this, [this, qart](){ onArtLoaded(qart); },
                                  Qt::QueuedConnection);
    }).detach();
}

// ── Preview ───────────────────────────────────────────────────────────────────

void MusicManager::onRefreshPreview() {
    if (m_currentTracks.isEmpty()) return;
    QString albumPath = m_rootDir + "/" + m_artistCombo->currentText() +
                        "/" + m_albumCombo->currentText();
    if (!QDir(albumPath).exists()) return;

    std::vector<Track> tracks;
    for (auto& t : m_currentTracks) tracks.push_back(t);

    auto [epData, log] = m_engine->generateFuzzyPreview(
        albumPath.toStdString(), tracks);

    m_episodesData.clear();
    for (auto& m : epData)
        m_episodesData.push_back(m);

    // Count matched/missing
    std::set<std::pair<int,int>> matchedKeys;
    for (auto& m : m_episodesData)
        matchedKeys.insert({m.disc_num, m.track_num});

    QVector<Track> missing;
    for (auto& t : m_currentTracks)
        if (!matchedKeys.count({t.disc, t.num}))
            missing.append(t);

    setProgress((int)m_episodesData.size(), (int)m_currentTracks.size());
    updateStatusDot(m_statusMatched,
        QString("%1 / %2 matched").arg(m_episodesData.size()).arg(m_currentTracks.size()),
        m_episodesData.size() == m_currentTracks.size() ? "#2ecc71" : "#0078d4");
    updateStatusDot(m_statusMissing,
        QString("%1 missing").arg(missing.size()),
        missing.isEmpty() ? "#555" : "#e74c3c");

    // Populate log
    m_logText->setPlainText(QString::fromStdString(log));

    // Rebuild track rows
    m_previewText->hide();
    if (m_tabWidget->currentIndex() == 0)
        m_previewScroll->show();
    rebuildTrackRows(m_episodesData, missing);

    m_batchData.clear();
}

void MusicManager::rebuildTrackRows(const QVector<MatchResult>& epData,
                                     const QVector<Track>& missing)
{
    // Clear old rows
    QLayoutItem* item;
    while ((item = m_previewInner->layout()->takeAt(0)) != nullptr) {
        delete item->widget();
        delete item;
    }

    int total   = m_currentTracks.size();
    int matched = epData.size();
    int miss    = missing.size();

    auto* hdr = new QLabel(
        QString("  %1 matched  ·  %2 unmatched  ·  %3 total")
            .arg(matched).arg(miss).arg(total));
    hdr->setStyleSheet("color:#888; font-size:9pt; padding:6px;");
    m_previewInner->layout()->addWidget(hdr);

    // Build lookup: (disc, num) → MatchResult*
    QMap<QPair<int,int>, const MatchResult*> lookup;
    for (auto& m : epData)
        lookup[{m.disc_num, m.track_num}] = &m;

    for (auto& track : m_currentTracks) {
        auto key = QPair<int,int>{track.disc, track.num};
        addTrackRow(track, lookup.value(key, nullptr));
    }
}

void MusicManager::addTrackRow(const Track& track, const MatchResult* match) {
    bool unmatched = (match == nullptr);
    bool warning   = (!unmatched) && match->score < 80;

    QString rowBg  = unmatched ? "#2a0d0d" : (warning ? "#291d09" : "#2d2d2d");
    QString border = unmatched ? "#6b1f1f" : (warning ? "#6b4a0d" : "#333333");

    auto* outer = new QFrame;
    outer->setStyleSheet("QFrame { background:" + border +
                         "; border-radius:3px; padding:1px; }");
    auto* row = new QWidget(outer);
    row->setStyleSheet("background:" + rowBg + "; border-radius:2px;");
    auto* rl = new QHBoxLayout(row);
    rl->setContentsMargins(8, 7, 8, 7);

    auto* numLbl = new QLabel(QString("%1").arg(track.num, 2));
    numLbl->setStyleSheet("color:#555; font-size:9pt; min-width:18px;");
    rl->addWidget(numLbl);

    auto* info = new QWidget;
    auto* il   = new QVBoxLayout(info);
    il->setContentsMargins(0,0,0,0);
    il->setSpacing(1);

    QString nameTxt = QString::fromStdString(track.name);
    if (track.disc > 1) nameTxt += "  [Disc " + QString::number(track.disc) + "]";
    auto* nameLbl = new QLabel(nameTxt);
    nameLbl->setStyleSheet("color:" + QString(unmatched ? "#884444" : "#e0e0e0") +
                            "; font-size:10pt;");
    il->addWidget(nameLbl);

    auto* fileLbl = new QLabel(
        unmatched ? "— no file found"
                  : QString::fromStdString(match->old_name));
    fileLbl->setStyleSheet("color:#555; font-size:8pt;");
    il->addWidget(fileLbl);
    rl->addWidget(info, 1);

    if (!unmatched) {
        auto* arrow = new QLabel("→");
        arrow->setStyleSheet("color:#555;");
        rl->addWidget(arrow);

        // Confidence percentage
        auto* confLbl = new QLabel(
            QString("%1%").arg(match->score));
        confLbl->setStyleSheet(
            match->score >= 80 ? "color:#2ecc71; font-size:9pt;"
            : match->score >= 55 ? "color:#e67e22; font-size:9pt;"
                                 : "color:#e74c3c; font-size:9pt;");
        rl->addWidget(confLbl);
    } else {
        auto* badge = new QLabel("unmatched");
        badge->setStyleSheet(
            "background:#6b1f1f; color:#ffaaaa; font-size:8pt; padding:2px 6px;");
        rl->addWidget(badge);
    }

    auto* outerL = new QVBoxLayout(outer);
    outerL->setContentsMargins(0,0,0,0);
    outerL->addWidget(row);

    m_previewInner->layout()->addWidget(outer);
}

// ── Batch ─────────────────────────────────────────────────────────────────────

void MusicManager::onBatchPreview() {
    if (m_currentArtistId.isEmpty()) {
        QMessageBox::warning(this, "No Artist", "Select an artist first.");
        return;
    }
    QString artistPath = m_rootDir + "/" + m_artistCombo->currentText();
    if (!QDir(artistPath).exists()) {
        QMessageBox::warning(this, "No Folder", "Artist folder not found.");
        return;
    }
    updateStatusDot(m_statusDetect, "Running batch preview…", "#e67e22");
    m_previewText->setPlainText("Running batch preview — please wait…\n");
    m_previewText->show();
    m_previewScroll->hide();

    std::thread([this, ap = artistPath.toStdString(),
                       aid = m_currentArtistId.toStdString()]() {
        auto results = m_engine->generateBatchPreview(ap, aid, "Fuzzy");
        QVector<BatchResult> qr(results.begin(), results.end());
        QMetaObject::invokeMethod(this, [this, qr](){
            onBatchDone(qr);
        }, Qt::QueuedConnection);
    }).detach();
}

void MusicManager::onBatchDone(const QVector<BatchResult>& results) {
    m_batchData     = results;
    m_episodesData.clear();

    int totalFiles   = 0, totalMatches = 0;
    for (auto& r : results) {
        if (QDir(QString::fromStdString(r.path)).exists()) {
            QDir d(QString::fromStdString(r.path));
            totalFiles += d.entryList(QDir::Files).size();
        }
        totalMatches += (int)r.ep_data.size();
    }

    QString header =
        "BATCH PREVIEW  ─  " + m_artistCombo->currentText() + "\n" +
        QString("═").repeated(55) + "\n" +
        QString("Albums: %1  ·  Files: %2  ·  Matches: %3\n")
            .arg(results.size()).arg(totalFiles).arg(totalMatches) +
        QString("═").repeated(55) + "\n\n";

    QString body;
    for (auto& r : results) body += QString::fromStdString(r.log) + "\n";
    m_previewText->setPlainText(header + body);

    setProgress(totalMatches, totalFiles);
    updateStatusDot(m_statusDetect,
        QString("Batch: %1 albums").arg(results.size()), "#2ecc71");
}

// ── Execute ───────────────────────────────────────────────────────────────────

void MusicManager::onExecuteRenameClicked() {
    if (m_episodesData.isEmpty() && m_batchData.isEmpty()) {
        QMessageBox::information(this, "Nothing to do", "Run a preview first.");
        return;
    }
    showReviewDialog();
}

void MusicManager::showReviewDialog() {
    // Collect unmatched files
    QString albumPath = m_rootDir + "/" + m_artistCombo->currentText() +
                        "/" + m_albumCombo->currentText();
    QStringList matchedOld;
    for (auto& e : m_episodesData) matchedOld << QString::fromStdString(e.old_name);

    QStringList unmatchedFiles;
    if (!m_batchData.isEmpty()) {
        // Batch mode: skip review, go straight to execute
        executeRename();
        return;
    }
    if (QDir(albumPath).exists()) {
        for (auto& f : QDir(albumPath).entryList(QDir::Files))
            if (!matchedOld.contains(f)) unmatchedFiles << f;
    }
    if (unmatchedFiles.isEmpty()) { executeRename(); return; }

    // Build pairing dialog
    auto* dlg = new QDialog(this);
    dlg->setWindowTitle("Unmatched Files");
    dlg->resize(680, 480);
    auto* lay = new QVBoxLayout(dlg);

    auto* hint = new QLabel("Click a file → click a Spotify track → they'll be paired below.");
    hint->setStyleSheet("color:#555; font-size:9pt; padding:8px;");
    lay->addWidget(hint);

    auto* body = new QWidget;
    auto* bodyL = new QHBoxLayout(body);

    // Left list
    auto* fileList = new QListWidget;
    for (auto& f : unmatchedFiles) fileList->addItem(f);
    bodyL->addWidget(fileList, 1);

    // Right list
    auto* trackList = new QListWidget;
    for (auto& t : m_currentTracks) {
        QString txt = QString("%1. %2").arg(t.num, 2)
                          .arg(QString::fromStdString(t.name));
        if (t.disc > 1) txt += " [Disc " + QString::number(t.disc) + "]";
        auto* item = new QListWidgetItem(txt, trackList);
        item->setData(Qt::UserRole, QVariant::fromValue(t));
    }
    bodyL->addWidget(trackList, 1);
    lay->addWidget(body, 1);

    auto* pairedLbl = new QLabel("MANUALLY PAIRED (0)");
    pairedLbl->setStyleSheet("background:#090f09; color:#2ecc71; font-weight:bold; padding:5px 10px;");
    lay->addWidget(pairedLbl);

    auto* pairedText = new QTextEdit;
    pairedText->setReadOnly(true);
    pairedText->setFixedHeight(60);
    lay->addWidget(pairedText);

    struct PairEntry { QString file; Track track; };
    QVector<PairEntry> manualPairs;

    // Pair on track click
    connect(trackList, &QListWidget::itemClicked, [&](QListWidgetItem* tItem) {
        auto* fItem = fileList->currentItem();
        if (!fItem) return;
        QString fname = fItem->text();
        Track  track  = tItem->data(Qt::UserRole).value<Track>();

        for (auto& p : manualPairs)
            if (p.file == fname) return;

        manualPairs.push_back({fname, track});
        pairedLbl->setText("MANUALLY PAIRED (" + QString::number(manualPairs.size()) + ")");
        QString ptext;
        for (auto& p : manualPairs)
            ptext += "  " + p.file + "  →  " + QString::fromStdString(p.track.name) + "\n";
        pairedText->setPlainText(ptext);

        // Remove from file list
        delete fileList->takeItem(fileList->row(fItem));
    });

    auto* foot = new QWidget;
    auto* footL = new QHBoxLayout(foot);
    footL->addStretch();
    auto* cancelBtn  = new QPushButton("Cancel");
    auto* confirmBtn = new QPushButton("Confirm & Execute");
    connect(cancelBtn, &QPushButton::clicked, dlg, &QDialog::reject);
    connect(confirmBtn, &QPushButton::clicked, dlg, &QDialog::accept);
    footL->addWidget(cancelBtn);
    footL->addWidget(confirmBtn);
    lay->addWidget(foot);

    if (dlg->exec() == QDialog::Accepted) {
        // Inject manual pairs
        for (auto& pair : manualPairs) {
            QString ext = QFileInfo(pair.file).suffix();
            if (!ext.isEmpty()) ext = "." + ext;
            MatchResult mr;
            mr.old_name  = pair.file.toStdString();
            mr.new_name  = m_engine->trackFilename(pair.track, ext.toStdString());
            mr.track_num = pair.track.num;
            mr.disc_num  = pair.track.disc;
            mr.score     = 100;
            m_episodesData.append(mr);
        }
        executeRename();
    }
}

void MusicManager::executeRename() {
    using PairTuple = std::tuple<QString,QString,QString,int,int>;
    QVector<PairTuple> pairs;

    if (!m_batchData.isEmpty()) {
        for (auto& r : m_batchData)
            for (auto& e : r.ep_data)
                pairs.push_back({
                    QString::fromStdString(r.path),
                    QString::fromStdString(e.old_name),
                    QString::fromStdString(e.new_name),
                    e.track_num, e.disc_num
                });
    } else {
        QString albumPath = m_rootDir + "/" + m_artistCombo->currentText() +
                            "/" + m_albumCombo->currentText();
        for (auto& e : m_episodesData)
            pairs.push_back({albumPath,
                             QString::fromStdString(e.old_name),
                             QString::fromStdString(e.new_name),
                             e.track_num, e.disc_num});
    }
    if (pairs.isEmpty()) {
        QMessageBox::information(this, "Nothing to do", "Run a preview first.");
        return;
    }

    // ── Pre-execution remux ───────────────────────────────────────────────────
    int remuxed = 0;
    if (m_autoRemux && m_remux->isAvailable()) {
        auto [updated, n] = runPreRemux(pairs);
        pairs   = updated;
        remuxed = n;
    }

    // ── Collision guard ───────────────────────────────────────────────────────
    QMap<QPair<QString,QString>, int> nameCounts;
    for (auto& [folder, old, newn, tnum, dnum] : pairs)
        nameCounts[{folder, newn}]++;

    QMap<QPair<QString,QString>, int> seen;
    QVector<PairTuple> resolved;
    for (auto& [folder, old, newn, tnum, dnum] : pairs) {
        auto key = QPair<QString,QString>{folder, newn};
        if (nameCounts[key] > 1) {
            seen[key]++;
            QFileInfo fi(newn);
            QString prefix = dnum > 1
                ? QString("Disc %1 - ").arg(dnum)
                : QString("%1 - ").arg(tnum, 2, 10, QChar('0'));
            newn = prefix + fi.baseName() + "." + fi.suffix();
        }
        resolved.push_back({folder, old, newn, tnum, dnum});
    }
    pairs = resolved;

    // ── Rename files ──────────────────────────────────────────────────────────
    int renamed = 0;
    m_renameHistory.clear();
    QStringList renameErrors;
    for (auto& [folder, old, newn, tnum, dnum] : pairs) {
        if (old == newn) continue;
        QString oldP = folder + "/" + old;
        QString newP = folder + "/" + newn;
        if (QFile::exists(oldP)) {
            if (!QFile::rename(oldP, newP)) {
                renameErrors << "Failed to rename: " + old;
            } else {
                m_renameHistory.append({newP, oldP});
                ++renamed;
            }
        }
    }
    if (!renameErrors.isEmpty()) {
        QMessageBox::critical(this, "Rename Error", renameErrors.join("\n"));
        return;
    }

    // ── Tag files ─────────────────────────────────────────────────────────────
    int tagged = 0;
    QStringList tagErrors;

    if ((m_applyArt || m_applyTags || m_applyGenre) && !m_currentMeta.artist.empty()) {
        // Build per-folder metadata map
        QMap<QString, ReleaseMetadata> folderMeta;
        if (!m_batchData.isEmpty()) {
            for (auto& r : m_batchData) {
                if (!r.has_release) continue;
                auto m = m_engine->getReleaseMetadata(r.release.id);
                auto art = m_engine->getCoverArtBytes(r.release.id);
                m.cover_art_bytes = art;
                folderMeta[QString::fromStdString(r.path)] = m;
            }
        } else {
            ReleaseMetadata m = m_currentMeta;
            m.cover_art_bytes.assign(
                m_currentArtBytes.begin(), m_currentArtBytes.end());
            QString albumPath = m_rootDir + "/" + m_artistCombo->currentText() +
                                "/" + m_albumCombo->currentText();
            folderMeta[albumPath] = m;
        }

        for (auto& [folder, old, newn, tnum, dnum] : pairs) {
            if (!folderMeta.contains(folder)) continue;
            QString finalPath = folder + "/" + newn;
            if (!QFile::exists(finalPath)) continue;
            ReleaseMetadata tm = folderMeta[folder];
            tm.title        = QFileInfo(newn).baseName().toStdString();
            tm.track_number = tnum;
            tm.disc_number  = dnum;
            std::string err = writeMetadata(finalPath.toStdString(), tm,
                                            m_applyArt, m_applyTags, m_applyGenre);
            if (err.empty()) ++tagged;
            else tagErrors << (newn + ": " + QString::fromStdString(err));
        }
        if (!tagErrors.isEmpty())
            QMessageBox::warning(this, "Tag Warnings",
                QString("%1 error(s):\n").arg(tagErrors.size()) +
                tagErrors.mid(0, 10).join("\n"));
    }

    QStringList msg;
    if (remuxed) msg << QString("Converted: %1 files").arg(remuxed);
    if (renamed) msg << QString("Renamed:   %1 files").arg(renamed);
    if (tagged)  msg << QString("Tagged:    %1 files").arg(tagged);
    QMessageBox::information(this, "Done",
        msg.isEmpty() ? "No changes needed." : msg.join("\n"));

    if (m_batchData.isEmpty()) onRefreshPreview();
}

// ── Pre-remux helper ──────────────────────────────────────────────────────────

QPair<QVector<std::tuple<QString,QString,QString,int,int>>, int>
MusicManager::runPreRemux(
    QVector<std::tuple<QString,QString,QString,int,int>>& pairs)
{
    static const QStringList skip = {".mp3", ".flac"};
    int remuxed = 0;
    QStringList errors;
    QVector<std::tuple<QString,QString,QString,int,int>> updated;

    for (auto& [folder, old, newn, tnum, dnum] : pairs) {
        QString srcExt = QFileInfo(old).suffix().toLower();
        if (!srcExt.startsWith('.')) srcExt = "." + srcExt;

        if (!skip.contains(srcExt)) {
            QString srcPath = folder + "/" + old;
            QString dstName = QFileInfo(old).baseName() + m_autoRemuxTarget;
            QString dstPath = folder + "/" + dstName;
            if (QFile::exists(srcPath)) {
                std::string res = m_remux->convert(
                    srcPath.toStdString(), dstPath.toStdString(),
                    m_autoRemuxQuality.toStdString(), m_autoRemuxDelSrc);
                if (res.empty()) {
                    old  = dstName;
                    newn = QFileInfo(newn).baseName() + m_autoRemuxTarget;
                    ++remuxed;
                } else {
                    errors << old + ": " + QString::fromStdString(res);
                }
            }
        }
        updated.push_back({folder, old, newn, tnum, dnum});
    }
    if (!errors.isEmpty())
        QMessageBox::warning(this, "Pre-remux Warnings",
            QString("%1 file(s) could not be converted:\n").arg(errors.size()) +
            errors.mid(0, 10).join("\n"));
    return {updated, remuxed};
}

// ── Undo ──────────────────────────────────────────────────────────────────────

void MusicManager::onUndoRename() {
    if (m_renameHistory.isEmpty()) return;
    for (auto& [newp, oldp] : m_renameHistory)
        if (QFile::exists(newp)) QFile::rename(newp, oldp);
    m_renameHistory.clear();
    QMessageBox::information(this, "Undo", "Reverted!");
}

// ── Convert dialog ────────────────────────────────────────────────────────────

void MusicManager::onShowConvertDialog() {
    QString albumPath = m_rootDir + "/" + m_artistCombo->currentText() +
                        "/" + m_albumCombo->currentText();
    if (!QDir(albumPath).exists()) {
        QMessageBox::warning(this, "No Folder", "Select an album folder first.");
        return;
    }
    if (!m_remux->isAvailable()) {
        QMessageBox::critical(this, "FFmpeg Missing",
            "FFmpeg is not installed or not on PATH.\n"
            "Download it from ffmpeg.org and add it to your PATH.");
        return;
    }

    static const QStringList audioExts =
        {".mp3",".flac",".m4a",".aac",".mp4",".ogg",".oga",".wav",".opus",".wma"};
    QStringList files;
    for (auto& f : QDir(albumPath).entryList(QDir::Files)) {
        QString ext = "." + QFileInfo(f).suffix().toLower();
        if (audioExts.contains(ext)) files << f;
    }
    if (files.isEmpty()) {
        QMessageBox::information(this, "No Audio Files",
            "No supported audio files found.");
        return;
    }

    auto* dlg = new QDialog(this);
    dlg->setWindowTitle("Convert Files");
    dlg->resize(560, 520);
    auto* lay = new QVBoxLayout(dlg);
    lay->setContentsMargins(16, 14, 16, 14);

    // Format + quality row
    auto* optsRow = new QWidget;
    auto* optsL   = new QHBoxLayout(optsRow);
    optsL->setContentsMargins(0,0,0,0);
    optsL->addWidget(new QLabel("Convert to:"));
    auto* fmtCb = new QComboBox;
    QStringList fmts;
    for (auto& f : RemuxEngine::SUPPORTED_OUTPUT) fmts << QString::fromStdString(f);
    fmts.sort();
    fmtCb->addItems(fmts);
    fmtCb->setCurrentText(".flac");
    optsL->addWidget(fmtCb);
    optsL->addSpacing(20);
    optsL->addWidget(new QLabel("Quality:"));
    auto* qualCb = new QComboBox;
    qualCb->addItems({"low","medium","high","best"});
    qualCb->setCurrentText("best");
    optsL->addWidget(qualCb);
    optsL->addStretch();
    lay->addWidget(optsRow);

    auto* delChk = new QCheckBox("Delete source files after conversion");
    lay->addWidget(delChk);

    // Header with Select All/None toggle
    auto* listHdr = new QWidget;
    auto* lhL     = new QHBoxLayout(listHdr);
    lhL->setContentsMargins(0,0,0,0);
    lhL->addWidget(new QLabel("Files to convert:"));
    lhL->addStretch();
    auto* selBtn = new QPushButton("Select None");
    selBtn->setFixedWidth(90);
    lhL->addWidget(selBtn);
    lay->addWidget(listHdr);

    auto* scroll = new QScrollArea;
    scroll->setWidgetResizable(true);
    auto* checkInner = new QWidget;
    auto* checkL     = new QVBoxLayout(checkInner);
    checkL->setAlignment(Qt::AlignTop);
    scroll->setWidget(checkInner);
    lay->addWidget(scroll, 1);

    QVector<QCheckBox*> checkBoxes;
    for (auto& f : files) {
        auto* cb = new QCheckBox(f);
        cb->setChecked(true);
        checkL->addWidget(cb);
        checkBoxes << cb;
    }

    bool allSelected = true;
    connect(selBtn, &QPushButton::clicked, [&]() {
        allSelected = !allSelected;
        for (auto* cb : checkBoxes) cb->setChecked(allSelected);
        selBtn->setText(allSelected ? "Select None" : "Select All");
    });

    // Progress
    auto* progBar = new QProgressBar;
    progBar->setRange(0, 100);
    progBar->setValue(0);
    progBar->setFixedHeight(4);
    progBar->setTextVisible(false);
    lay->addWidget(progBar);
    auto* statusLbl = new QLabel("Ready");
    statusLbl->setStyleSheet("color:#555; font-size:9pt;");
    lay->addWidget(statusLbl);

    auto* foot = new QWidget;
    auto* footL = new QHBoxLayout(foot);
    footL->addStretch();
    auto* cancelBtn  = new QPushButton("Cancel");
    auto* convertBtn = new QPushButton("Convert");
    connect(cancelBtn, &QPushButton::clicked, dlg, &QDialog::reject);
    footL->addWidget(cancelBtn);
    footL->addWidget(convertBtn);
    lay->addWidget(foot);

    connect(convertBtn, &QPushButton::clicked, [&]() {
        QStringList selected;
        for (auto* cb : checkBoxes)
            if (cb->isChecked()) selected << cb->text();
        if (selected.isEmpty()) {
            QMessageBox::warning(dlg, "Nothing selected", "Check at least one file.");
            return;
        }
        convertBtn->setEnabled(false);
        QString fmt   = fmtCb->currentText();
        QString qual  = qualCb->currentText();
        bool    delSrc = delChk->isChecked();
        int total = selected.size(), done = 0;
        QStringList errors;
        for (auto& fname : selected) {
            ++done;
            statusLbl->setText(QString("Converting %1/%2: %3").arg(done).arg(total).arg(fname));
            progBar->setValue(100 * (done-1) / total);
            QApplication::processEvents();
            QString src = albumPath + "/" + fname;
            QString dst = QString::fromStdString(
                m_remux->suggestedOutputPath(src.toStdString(), fmt.toStdString()));
            std::string res = m_remux->convert(src.toStdString(), dst.toStdString(),
                                               qual.toStdString(), delSrc);
            if (!res.empty()) errors << fname + ": " + QString::fromStdString(res);
        }
        progBar->setValue(100);
        int ok = total - errors.size();
        if (errors.isEmpty())
            QMessageBox::information(dlg, "Convert Complete",
                QString("All %1 file(s) converted successfully.").arg(total));
        else
            QMessageBox::warning(dlg, "Convert Complete",
                QString("%1/%2 converted.\n\n").arg(ok).arg(total) +
                errors.mid(0,10).join("\n"));
        dlg->accept();
    });

    dlg->exec();
}

// ── Settings ──────────────────────────────────────────────────────────────────

void MusicManager::onOpenSettings() {
    auto* dlg = new QDialog(this);
    dlg->setWindowTitle("Settings");
    dlg->setFixedSize(480, 580);
    auto* lay = new QVBoxLayout(dlg);
    lay->setContentsMargins(28, 24, 28, 24);

    auto* title = new QLabel("Spotify API Credentials");
    title->setStyleSheet("font-size:14pt; font-weight:bold;");
    lay->addWidget(title);
    auto* sub = new QLabel("Get a free Client ID + Secret at developer.spotify.com/dashboard");
    sub->setWordWrap(true);
    lay->addWidget(sub);
    lay->addSpacing(8);

    auto* idLbl = new QLabel("Client ID");
    auto* idEdit = new QLineEdit(m_spotifyId);
    lay->addWidget(idLbl);
    lay->addWidget(idEdit);
    lay->addSpacing(8);

    auto* secretLbl  = new QLabel("Client Secret");
    auto* secretEdit = new QLineEdit(m_spotifySecret);
    secretEdit->setEchoMode(QLineEdit::Password);
    lay->addWidget(secretLbl);
    lay->addWidget(secretEdit);
    lay->addSpacing(8);

    auto* sep1 = new QFrame; sep1->setFrameShape(QFrame::HLine);
    lay->addWidget(sep1);

    auto* pathLbl = new QLabel("Default media path");
    lay->addWidget(pathLbl);
    auto* pathRow = new QWidget;
    auto* prl     = new QHBoxLayout(pathRow);
    prl->setContentsMargins(0,0,0,0);
    auto* pathEdit = new QLineEdit(m_rootDir);
    auto* browseBtn = new QPushButton("Browse");
    connect(browseBtn, &QPushButton::clicked, [&](){
        QString d = QFileDialog::getExistingDirectory(dlg, "Select path");
        if (!d.isEmpty()) pathEdit->setText(d);
    });
    prl->addWidget(pathEdit, 1);
    prl->addWidget(browseBtn);
    lay->addWidget(pathRow);

    auto* sep2 = new QFrame; sep2->setFrameShape(QFrame::HLine);
    lay->addWidget(sep2);

    auto* autoTitle = new QLabel("Pre-execution Automation");
    autoTitle->setStyleSheet("font-size:12pt; font-weight:bold;");
    lay->addWidget(autoTitle);

    auto* remuxChk = new QCheckBox(
        "Auto-remux non-MP3/FLAC files before rename");
    remuxChk->setChecked(m_autoRemux);
    lay->addWidget(remuxChk);

    auto* optsWidget = new QWidget;
    auto* optsL = new QHBoxLayout(optsWidget);
    optsL->setContentsMargins(20, 0, 0, 0);
    optsL->addWidget(new QLabel("Target:"));
    auto* tgtCb = new QComboBox;
    QStringList fmts;
    for (auto& f : RemuxEngine::SUPPORTED_OUTPUT) fmts << QString::fromStdString(f);
    fmts.sort();
    tgtCb->addItems(fmts);
    tgtCb->setCurrentText(m_autoRemuxTarget);
    optsL->addWidget(tgtCb);
    optsL->addSpacing(10);
    optsL->addWidget(new QLabel("Quality:"));
    auto* qualCb = new QComboBox;
    qualCb->addItems({"low","medium","high","best"});
    qualCb->setCurrentText(m_autoRemuxQuality);
    optsL->addWidget(qualCb);
    optsL->addStretch();
    lay->addWidget(optsWidget);

    auto* delChk = new QCheckBox("Delete source file after conversion");
    delChk->setChecked(m_autoRemuxDelSrc);
    delChk->setContentsMargins(20,0,0,0);
    lay->addWidget(delChk);

    auto toggleOpts = [&](){
        bool en = remuxChk->isChecked();
        optsWidget->setEnabled(en);
        delChk->setEnabled(en);
    };
    connect(remuxChk, &QCheckBox::toggled, toggleOpts);
    toggleOpts();

    auto* saveBtn = new QPushButton("Save");
    saveBtn->setObjectName("execBtn");
    lay->addStretch();
    lay->addWidget(saveBtn, 0, Qt::AlignRight);

    connect(saveBtn, &QPushButton::clicked, [&]() {
        QString id  = idEdit->text().trimmed();
        QString sec = secretEdit->text().trimmed();
        if (!id.isEmpty() && !sec.isEmpty()) {
            m_engine->configure(id.toStdString(), sec.toStdString());
            if (!m_engine->isConfigured()) {
                QMessageBox::critical(dlg, "Invalid credentials",
                    "Spotify rejected the credentials.");
                return;
            }
            updateStatusDot(m_statusSpotify, "Spotify connected", "#2ecc71");
        }
        m_spotifyId           = id;
        m_spotifySecret       = sec;
        m_rootDir             = pathEdit->text();
        m_rootPathEdit->setText(m_rootDir);
        m_autoRemux           = remuxChk->isChecked();
        m_autoRemuxTarget     = tgtCb->currentText();
        m_autoRemuxQuality    = qualCb->currentText();
        m_autoRemuxDelSrc     = delChk->isChecked();
        saveConfig();
        QMessageBox::information(dlg, "Saved", "Settings saved.");
        dlg->accept();
    });

    dlg->exec();
}

void MusicManager::onSwitchTheme(const QString& name) {
    applyTheme(name);
}

// ── Config persistence ────────────────────────────────────────────────────────

void MusicManager::saveConfig() {
    QJsonObject obj;
    obj["path"]                   = m_rootDir;
    obj["theme"]                  = m_currentTheme;
    obj["spotify_id"]             = m_spotifyId;
    obj["spotify_secret"]         = m_spotifySecret;
    obj["auto_remux"]             = m_autoRemux;
    obj["auto_remux_target"]      = m_autoRemuxTarget;
    obj["auto_remux_quality"]     = m_autoRemuxQuality;
    obj["auto_remux_delete_source"] = m_autoRemuxDelSrc;
    QFile f("music_config.json");
    if (f.open(QIODevice::WriteOnly))
        f.write(QJsonDocument(obj).toJson(QJsonDocument::Indented));
}

void MusicManager::loadConfig() {
    QFile f("music_config.json");
    if (!f.open(QIODevice::ReadOnly)) return;
    auto obj = QJsonDocument::fromJson(f.readAll()).object();
    m_rootDir             = obj.value("path").toString();
    m_currentTheme        = obj.value("theme").toString("Dark");
    m_spotifyId           = obj.value("spotify_id").toString();
    m_spotifySecret       = obj.value("spotify_secret").toString();
    m_autoRemux           = obj.value("auto_remux").toBool(false);
    m_autoRemuxTarget     = obj.value("auto_remux_target").toString(".flac");
    m_autoRemuxQuality    = obj.value("auto_remux_quality").toString("best");
    m_autoRemuxDelSrc     = obj.value("auto_remux_delete_source").toBool(true);
}
