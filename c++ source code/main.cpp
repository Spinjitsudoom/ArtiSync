#include "music_organizer.h"
#include <QApplication>
#include <QIcon>
#include <curl/curl.h>

int main(int argc, char* argv[]) {
    curl_global_init(CURL_GLOBAL_DEFAULT);

    QApplication app(argc, argv);
    app.setApplicationName("ArtiSync");
    app.setApplicationVersion("2.1.0");
    app.setDesktopFileName("com.artisync.ArtiSync");
    app.setWindowIcon(QIcon(":/ArtiSync.png"));

    ArtiSync window;
    window.show();

    int ret = app.exec();
    curl_global_cleanup();
    return ret;
}
