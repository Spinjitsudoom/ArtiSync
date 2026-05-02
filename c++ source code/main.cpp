#include "music_organizer.h"
#include <QApplication>
#include <QIcon>
#include <curl/curl.h>

int main(int argc, char* argv[]) {
    curl_global_init(CURL_GLOBAL_DEFAULT);

    QApplication app(argc, argv);
    app.setApplicationName("Music Manager Ultimate");
    app.setApplicationVersion("2.1.0");
    app.setDesktopFileName("com.musicmanager.MusicManager");
    app.setWindowIcon(QIcon(":/MusicManager.png"));

    MusicManager window;
    window.show();

    int ret = app.exec();
    curl_global_cleanup();
    return ret;
}
