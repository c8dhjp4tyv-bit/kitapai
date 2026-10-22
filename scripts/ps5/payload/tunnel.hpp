// SSH ters tüneli (ssh -R eşdeğeri): PS5 dışarıya bağlanır, herkese açık adres yönlendirilir.
// CGNAT arkasında gelen bağlantı kabul edilemediği için tünel PS5'in kendisinden kurulur.
// libssh2 (mbedTLS arka ucu). SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <arpa/inet.h>
#include <fcntl.h>
#include <libssh2.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include <atomic>
#include "probe.hpp"
#include <chrono>
#include <cstring>
#include <functional>
#include <list>
#include <string>
#include <thread>
#include <vector>

namespace tun {

struct Config {
    std::string host = "localhost.run";
    int port = 22;
    std::string user = "nokey";
    std::string bind_host = "localhost";
    int bind_port = 80;
    std::string local_host = "127.0.0.1";
    int local_port = 8800;
    // DNS çözülemezse (konsolda çözümleyici yoksa) denenecek adresler: localhost.run'ın bilinen IP'leri.
    std::vector<std::string> fallback_ips = {"54.82.85.249", "35.171.254.69"};
};

using Logger = std::function<void(const std::string &)>;
using UrlSink = std::function<void(const std::string &)>;

namespace detail {

inline int tcp_connect(const std::string &host, int port, int timeout_s) {
    addrinfo hints{}, *res = nullptr;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host.c_str(), std::to_string(port).c_str(), &hints, &res) != 0 || !res) return -1;
    int fd = -1;
    for (addrinfo *p = res; p; p = p->ai_next) {
        fd = socket(p->ai_family, p->ai_socktype, p->ai_protocol);
        if (fd < 0) continue;
        timeval tv{timeout_s, 0};
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
        if (connect(fd, p->ai_addr, p->ai_addrlen) == 0) break;
        close(fd);
        fd = -1;
    }
    freeaddrinfo(res);
    return fd;
}

inline void set_nonblocking(int fd) { fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) | O_NONBLOCK); }

// "tunneled" geçen satırdaki https adresini çıkarır.
inline std::string url_from_banner(const std::string &text) {
    size_t pos = 0;
    while (pos < text.size()) {
        size_t nl = text.find('\n', pos);
        std::string line = text.substr(pos, nl == std::string::npos ? std::string::npos : nl - pos);
        pos = nl == std::string::npos ? text.size() : nl + 1;
        size_t h = line.find("https://");
        if (h == std::string::npos) continue;
        if (line.find("tunneled") == std::string::npos && line.find("forwarding") == std::string::npos) continue;
        size_t e = h;
        while (e < line.size() && !isspace((unsigned char)line[e]) && line[e] != '\r') e++;
        return line.substr(h, e - h);
    }
    return "";
}

// Bir yönlendirilmiş bağlantı: SSH kanalı <-> yerel soket.
struct Pair {
    LIBSSH2_CHANNEL *chan = nullptr;
    int fd = -1;
    std::string to_local, to_chan;
    bool chan_eof = false, local_eof = false;
};

inline void close_pair(Pair &p) {
    if (p.fd >= 0) close(p.fd);
    if (p.chan) { libssh2_channel_close(p.chan); libssh2_channel_free(p.chan); }
    p.fd = -1;
    p.chan = nullptr;
}

}  // namespace detail

// Tek bir bağlantı ömrü: kopana kadar çalışır, bağlantıyı yeniden kurmak çağıranın işidir.
inline bool run_once(const Config &cfg, const Logger &log, const UrlSink &sink, std::atomic<bool> &stop) {
    int sock = detail::tcp_connect(cfg.host, cfg.port, 20);
    if (sock < 0) {
        log("tünel: " + cfg.host + " çözülemedi ya da bağlanılamadı, yedek adresler deneniyor");
        for (const auto &ip : cfg.fallback_ips) {
            sock = detail::tcp_connect(ip, cfg.port, 20);
            if (sock >= 0) { log("tünel: yedek adres " + ip + " ile bağlanıldı"); break; }
        }
    }
    if (sock < 0) { log("tünel: sunucuya bağlanılamadı (" + cfg.host + ":" + std::to_string(cfg.port) + ")"); return false; }
    int one = 1;
    setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);

    LIBSSH2_SESSION *session = libssh2_session_init();
    if (!session) { close(sock); return false; }
    libssh2_session_set_blocking(session, 1);
    libssh2_session_set_timeout(session, 20000);
    LIBSSH2_LISTENER *listener = nullptr;
    LIBSSH2_CHANNEL *shell = nullptr;
    std::list<detail::Pair> pairs;
    bool ok = false;

    std::atomic<bool> watchdog_failed{false}, watchdog_stop{false};
    std::thread watchdog;
    auto cleanup = [&] {
        watchdog_stop = true;
        if (watchdog.joinable()) watchdog.join();
        for (auto &p : pairs) detail::close_pair(p);
        pairs.clear();
        if (listener) libssh2_channel_forward_cancel(listener);
        if (shell) { libssh2_channel_close(shell); libssh2_channel_free(shell); }
        libssh2_session_disconnect(session, "bye");
        libssh2_session_free(session);
        close(sock);
    };

    int rc = libssh2_session_handshake(session, sock);
    if (rc) { log("tünel: SSH el sıkışma hatası " + std::to_string(rc)); cleanup(); return false; }
    const char *fp = libssh2_hostkey_hash(session, LIBSSH2_HOSTKEY_HASH_SHA256);
    if (fp) {
        static const char *hex = "0123456789abcdef";
        std::string h;
        for (int i = 0; i < 32; i++) { h += hex[(unsigned char)fp[i] >> 4]; h += hex[(unsigned char)fp[i] & 15]; }
        log("tünel: sunucu anahtarı sha256 " + h);
    }
    char *methods = libssh2_userauth_list(session, cfg.user.c_str(), (unsigned)cfg.user.size());
    if (!libssh2_userauth_authenticated(session)) {
        log(std::string("tünel: kimlik doğrulama gerekli, yöntemler: ") + (methods ? methods : "?"));
        cleanup();
        return false;
    }

    int bound = 0;
    listener = libssh2_channel_forward_listen_ex(session, cfg.bind_host.c_str(), cfg.bind_port, &bound, 16);
    if (!listener) {
        char *msg = nullptr;
        libssh2_session_last_error(session, &msg, nullptr, 0);
        log(std::string("tünel: uzak yönlendirme reddedildi: ") + (msg ? msg : "?"));
        cleanup();
        return false;
    }
    log("tünel: yönlendirme hazır (uzak " + cfg.bind_host + ":" + std::to_string(bound) + " → " +
        cfg.local_host + ":" + std::to_string(cfg.local_port) + ")");

    // Sunucu adresi bu oturum kanalına yazar; OpenSSH gibi `shell` istemeye gerek yok.
    shell = libssh2_channel_open_session(session);
    if (!shell) { log("tünel: oturum kanalı açılamadı"); cleanup(); return false; }
    libssh2_channel_handle_extended_data2(shell, LIBSSH2_CHANNEL_EXTENDED_DATA_MERGE);   // stderr'i de oku
    {
        libssh2_session_set_timeout(session, 3000);   // sunucu shell isteğine yanıt vermiyor; adres yine gelir
        int src = libssh2_channel_shell(shell);   // OpenSSH gibi: pty yok, doğrudan shell
        libssh2_session_set_timeout(session, 20000);
        if (src) {
            char *emsg = nullptr;
            libssh2_session_last_error(session, &emsg, nullptr, 0);
            if (src != LIBSSH2_ERROR_TIMEOUT) log("tünel: shell isteği başarısız " + std::to_string(src) + " " + (emsg ? emsg : "?"));
        }
    }

    libssh2_session_set_blocking(session, 0);
    libssh2_keepalive_config(session, 1, 30);
    std::string banner;
    std::string last_url;
    auto last_activity = std::chrono::steady_clock::now();

    while (!stop.load()) {
        // 1) açılış metni (adres burada yazılır)
        char buf[16384];
        ssize_t n = libssh2_channel_read(shell, buf, sizeof buf);
        if (n > 0) {
            banner.append(buf, (size_t)n);
            if (banner.size() > 32768) banner.erase(0, banner.size() - 16384);
            std::string url = detail::url_from_banner(banner);
            if (!url.empty() && url != last_url) {
                last_url = url; log("tünel: genel adres " + url); sink(url);
                if (!watchdog.joinable()) {
                    watchdog = std::thread([url, &watchdog_failed, &watchdog_stop, &log] {
                        auto sleep_s = [&](int sec) {
                            for (int i = 0; i < sec * 10 && !watchdog_stop.load(); i++) std::this_thread::sleep_for(std::chrono::milliseconds(100));
                        };
                        sleep_s(25);   // yeni alt alan adının yayılması için bekle
                        int fails = 0;
                        auto first = std::chrono::steady_clock::now();
                        while (!watchdog_stop.load()) {
                            std::string why;
                            if (probe_public(url, why)) fails = 0;
                            else {
                                fails++;
                                log("tünel: bekçi sınaması başarısız (" + std::to_string(fails) + "): " + why);
                                bool grace = std::chrono::steady_clock::now() - first < std::chrono::minutes(3);
                                if (fails >= (grace ? 4 : 2)) { watchdog_failed = true; return; }
                            }
                            sleep_s(fails ? 10 : 45);
                        }
                    });
                }
            }
        } else if (n < 0 && n != LIBSSH2_ERROR_EAGAIN) {
            // EAGAIN dışındaki her hata oturumun bozulduğu anlamına gelir (soket koptu, protokol hatası...).
            char *emsg = nullptr;
            libssh2_session_last_error(session, &emsg, nullptr, 0);
            log("tünel: oturum bozuldu (okuma " + std::to_string((long long)n) + " " + (emsg ? emsg : "?") + ")");
            break;
        } else if (n == 0 && libssh2_channel_eof(shell)) { log("tünel: sunucu oturumu kapattı"); break; }
        if (watchdog_failed.load()) { log("tünel: bekçi genel adresin düştüğünü gördü, yeniden bağlanılıyor"); break; }
        // 2) yeni yönlendirilmiş bağlantılar
        for (int k = 0; k < 8; k++) {
            LIBSSH2_CHANNEL *c = libssh2_channel_forward_accept(listener);
            if (!c) break;
            int fd = detail::tcp_connect(cfg.local_host, cfg.local_port, 5);
            if (fd < 0) { libssh2_channel_free(c); continue; }
            detail::set_nonblocking(fd);
            detail::Pair p;
            p.chan = c;
            p.fd = fd;
            pairs.push_back(std::move(p));
            last_activity = std::chrono::steady_clock::now();
        }
        // 3) veri aktarımı
        bool any = false;
        for (auto it = pairs.begin(); it != pairs.end();) {
            auto &p = *it;
            if (p.to_local.empty() && !p.chan_eof) {
                ssize_t r = libssh2_channel_read(p.chan, buf, sizeof buf);
                if (r > 0) { p.to_local.assign(buf, (size_t)r); any = true; }
                else if (r == 0 || (r < 0 && r != LIBSSH2_ERROR_EAGAIN)) p.chan_eof = true;
                if (libssh2_channel_eof(p.chan)) p.chan_eof = p.to_local.empty() ? true : p.chan_eof;
            }
            if (!p.to_local.empty()) {
                ssize_t w = send(p.fd, p.to_local.data(), p.to_local.size(), MSG_NOSIGNAL);
                if (w > 0) { p.to_local.erase(0, (size_t)w); any = true; }
                else if (w < 0 && errno != EAGAIN && errno != EWOULDBLOCK) p.local_eof = true;
            }
            if (p.to_chan.empty() && !p.local_eof) {
                ssize_t r = recv(p.fd, buf, sizeof buf, 0);
                if (r > 0) { p.to_chan.assign(buf, (size_t)r); any = true; }
                else if (r == 0 || (r < 0 && errno != EAGAIN && errno != EWOULDBLOCK)) p.local_eof = true;
            }
            if (!p.to_chan.empty()) {
                ssize_t w = libssh2_channel_write(p.chan, p.to_chan.data(), p.to_chan.size());
                if (w > 0) { p.to_chan.erase(0, (size_t)w); any = true; }
                else if (w < 0 && w != LIBSSH2_ERROR_EAGAIN) p.chan_eof = true;
            }
            bool done = (p.chan_eof && p.to_local.empty()) || (p.local_eof && p.to_chan.empty());
            if (done) {
                if (p.local_eof) libssh2_channel_send_eof(p.chan);
                detail::close_pair(p);
                it = pairs.erase(it);
                any = true;
            } else ++it;
        }
        if (any) last_activity = std::chrono::steady_clock::now();
        // 4) canlı tutma; oturum ölmüşse çık
        int seconds_to_next = 0;
        int ka = libssh2_keepalive_send(session, &seconds_to_next);
        if (ka < 0 && ka != LIBSSH2_ERROR_EAGAIN) { log("tünel: bağlantı koptu (keepalive " + std::to_string(ka) + ")"); break; }
        if (std::chrono::steady_clock::now() - last_activity > std::chrono::minutes(30)) {
            // 30 dk hiç hareket yoksa da döngü sürer; yalnızca bağlantı kopması yeniden bağlanmayı tetikler.
            last_activity = std::chrono::steady_clock::now();
        }
        // uyku: oturum soketi veya yerel soketler hazır olunca uyan
        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(sock, &rfds);
        int maxfd = sock;
        for (auto &p : pairs) { FD_SET(p.fd, &rfds); if (p.fd > maxfd) maxfd = p.fd; }
        timeval tv{0, any ? 1000 : 25000};
        select(maxfd + 1, &rfds, nullptr, nullptr, &tv);
    }
    ok = true;
    cleanup();
    return ok;
}

// Bağlantı koptukça artan beklemeyle yeniden dener (en çok 60 sn).
inline void run_forever(const Config &cfg, const Logger &log, const UrlSink &sink, std::atomic<bool> &stop) {
    libssh2_init(0);
    int delay = 5;
    while (!stop.load()) {
        auto t0 = std::chrono::steady_clock::now();
        run_once(cfg, log, sink, stop);
        if (stop.load()) break;
        long alive = (long)std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now() - t0).count();
        delay = alive > 120 ? 5 : std::min(60, delay * 2);   // uzun yaşadıysa hızlı yeniden dene
        log("tünel: " + std::to_string(delay) + " sn sonra yeniden denenecek");
        for (int i = 0; i < delay * 10 && !stop.load(); i++) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
}

}  // namespace tun
