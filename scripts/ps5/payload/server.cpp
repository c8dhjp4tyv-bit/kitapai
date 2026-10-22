// kitap.ai PS5 payload'u: statik site + /api/* + sunucu tarafı davet kodu, yerel llama-server'a bağlanır.
// Aynı kod PC'de de derlenir (g++), böylece PS5'e koymadan önce denenebilir.
// SPDX-License-Identifier: GPL-3.0-or-later
#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <ctime>
#include <fstream>
#include <mutex>
#include <sstream>
#include <thread>

#include "core.hpp"
#include "tunnel.hpp"

namespace {

struct Config {
    std::string dir = "/data/PS5LM/kitapai";
    std::string llama_host = "127.0.0.1";
    int llama_port = 8081;
    int port = 8800;
    std::string model_id = "llama-server@ps5";
};

Config cfg;
kc::Meta meta;
kc::Catalog catalog;
std::mutex llm_mu;
std::atomic<int> waiting{0};
std::atomic<int> connections{0};
const time_t started_at = time(nullptr);
std::mutex log_mu;
std::mutex url_mu;
std::string public_url;
std::mutex fail_mu;
std::vector<time_t> invite_failures;   // son bir dakikadaki başarısız davet denemeleri (genel sınır)

// Başarısız deneme çoksa (kaba kuvvet) davet doğrulamasını geçici olarak durdurur.
bool invite_rate_limited() {
    std::lock_guard<std::mutex> g(fail_mu);
    time_t now = time(nullptr);
    invite_failures.erase(std::remove_if(invite_failures.begin(), invite_failures.end(),
                                         [&](time_t t) { return now - t > 60; }), invite_failures.end());
    return invite_failures.size() >= 30;
}
void note_invite_failure() {
    std::lock_guard<std::mutex> g(fail_mu);
    invite_failures.push_back(time(nullptr));
}

std::string env_or(const char *k, const std::string &d) {
    const char *v = getenv(k);
    return v && *v ? v : d;
}

void logf(const std::string &line) {
    std::lock_guard<std::mutex> g(log_mu);
    std::string path = cfg.dir + "/server.log";
    struct stat st;
    if (stat(path.c_str(), &st) == 0 && st.st_size > 512 * 1024) rename(path.c_str(), (path + ".1").c_str());
    std::ofstream f(path, std::ios::app);
    char ts[32];
    time_t t = time(nullptr);
    strftime(ts, sizeof ts, "%m-%d %H:%M:%S", gmtime(&t));
    f << ts << " " << line << "\n";
    fprintf(stderr, "%s %s\n", ts, line.c_str());
}

std::string slurp(const std::string &path, bool *ok = nullptr) {
    std::ifstream f(path, std::ios::binary);
    if (ok) *ok = (bool)f;
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

// ── davet kodları ───────────────────────────────────────────────────────────

struct Invite { time_t expires = 0; std::string label; };
std::mutex codes_mu;
std::map<std::string, Invite> codes;
time_t codes_mtime = 0;

std::string normalize_code(const std::string &s) {
    std::string out;
    for (unsigned char c : s)
        if (isalnum(c)) out += (char)toupper(c);
    return out;
}

void reload_codes_locked() {
    std::string path = cfg.dir + "/codes.txt";
    struct stat st;
    if (stat(path.c_str(), &st) != 0) { codes.clear(); codes_mtime = 0; return; }
    if (st.st_mtime == codes_mtime && !codes.empty()) return;
    codes.clear();
    std::ifstream f(path);
    std::string line;
    while (std::getline(f, line)) {
        std::istringstream ls(line);
        std::string code, exp, label;
        if (!(ls >> code >> exp)) continue;
        std::getline(ls, label);
        while (!label.empty() && label.front() == ' ') label.erase(0, 1);
        std::string norm = normalize_code(code);
        if (norm.size() != 24) continue;
        codes[norm] = {(time_t)atoll(exp.c_str()), label};
    }
    codes_mtime = st.st_mtime;
}

enum class Auth { Ok, Missing, Invalid, Expired };

Auth check_code(const std::string &raw, Invite *out = nullptr) {
    std::string code = normalize_code(raw);
    if (code.empty()) return Auth::Missing;
    std::lock_guard<std::mutex> g(codes_mu);
    reload_codes_locked();
    auto it = codes.find(code);
    if (it == codes.end()) return Auth::Invalid;
    if (time(nullptr) >= it->second.expires) return Auth::Expired;
    if (out) *out = it->second;
    return Auth::Ok;
}

// ── HTTP yardımcıları ───────────────────────────────────────────────────────

struct HttpRequest {
    std::string method, path, query, body;
    std::map<std::string, std::string> headers;   // küçük harfli anahtarlar
};

struct HttpResponse {
    int status = 200;
    std::string type = "application/json; charset=utf-8", body;
    std::vector<std::pair<std::string, std::string>> extra;
};

const char *reason(int s) {
    switch (s) {
    case 200: return "OK"; case 204: return "No Content"; case 400: return "Bad Request";
    case 401: return "Unauthorized"; case 404: return "Not Found"; case 405: return "Method Not Allowed";
    case 413: return "Payload Too Large"; case 422: return "Unprocessable Entity";
    case 429: return "Too Many Requests"; case 503: return "Service Unavailable"; default: return "Error";
    }
}

bool send_all(int fd, const char *p, size_t n) {
    while (n) {
        ssize_t w = send(fd, p, n, MSG_NOSIGNAL);
        if (w <= 0) return false;
        p += w; n -= (size_t)w;
    }
    return true;
}

void write_response(int fd, const HttpResponse &r, bool head_only = false) {
    std::string h = "HTTP/1.1 " + std::to_string(r.status) + " " + reason(r.status) + "\r\n";
    h += "Content-Type: " + r.type + "\r\nContent-Length: " + std::to_string(r.body.size()) + "\r\n";
    h += "Connection: close\r\nAccess-Control-Allow-Origin: *\r\n";
    h += "Access-Control-Allow-Headers: content-type, x-api-key\r\nAccess-Control-Allow-Methods: GET, POST, OPTIONS\r\n";
    for (const auto &kv : r.extra) h += kv.first + ": " + kv.second + "\r\n";
    h += "\r\n";
    if (!send_all(fd, h.data(), h.size())) return;
    if (!head_only) send_all(fd, r.body.data(), r.body.size());
}

HttpResponse json_response(int status, const kj::Json &j) {
    HttpResponse r;
    r.status = status;
    r.body = kj::dump(j);
    return r;
}

HttpResponse error_response(int status, const std::string &error, const std::string &detail = "") {
    kj::Json j = kj::Json::object();
    j.set("error", kj::Json::str(error));
    if (!detail.empty()) j.set("detail", kj::Json::str(detail));
    return json_response(status, j);
}

std::string url_decode(const std::string &s) {
    std::string out;
    for (size_t i = 0; i < s.size(); i++) {
        if (s[i] == '%' && i + 2 < s.size() && isxdigit((unsigned char)s[i + 1]) && isxdigit((unsigned char)s[i + 2])) {
            out += (char)strtol(s.substr(i + 1, 2).c_str(), nullptr, 16);
            i += 2;
        } else if (s[i] == '+') out += ' ';
        else out += s[i];
    }
    return out;
}

std::map<std::string, std::string> parse_query(const std::string &q) {
    std::map<std::string, std::string> out;
    for (const auto &kv : kc::split(q, '&')) {
        size_t e = kv.find('=');
        if (e == std::string::npos) continue;
        out[url_decode(kv.substr(0, e))] = url_decode(kv.substr(e + 1));
    }
    return out;
}

bool read_request(int fd, HttpRequest &req, int &err_status) {
    std::string buf;
    char tmp[4096];
    size_t header_end = std::string::npos;
    while (header_end == std::string::npos) {
        ssize_t n = recv(fd, tmp, sizeof tmp, 0);
        if (n <= 0) return false;
        buf.append(tmp, (size_t)n);
        header_end = buf.find("\r\n\r\n");
        if (buf.size() > 16 * 1024 && header_end == std::string::npos) { err_status = 413; return false; }
    }
    std::string head = buf.substr(0, header_end);
    std::istringstream hs(head);
    std::string line;
    std::getline(hs, line);
    std::istringstream rl(line);
    std::string target, ver;
    rl >> req.method >> target >> ver;
    size_t qm = target.find('?');
    req.path = url_decode(target.substr(0, qm));
    if (qm != std::string::npos) req.query = target.substr(qm + 1);
    while (std::getline(hs, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        size_t c = line.find(':');
        if (c == std::string::npos) continue;
        std::string k = kt::lower(line.substr(0, c)), v = line.substr(c + 1);
        while (!v.empty() && v.front() == ' ') v.erase(0, 1);
        req.headers[k] = v;
    }
    size_t want = 0;
    auto cl = req.headers.find("content-length");
    if (cl != req.headers.end()) want = (size_t)atoll(cl->second.c_str());
    if (want > 64 * 1024) { err_status = 413; return false; }
    req.body = buf.substr(header_end + 4);
    while (req.body.size() < want) {
        ssize_t n = recv(fd, tmp, sizeof tmp, 0);
        if (n <= 0) return false;
        req.body.append(tmp, (size_t)n);
    }
    req.body.resize(want);
    return true;
}

// ── llama-server istemcisi ───────────────────────────────────────────────────

int connect_to(const std::string &host, int port, int timeout_s) {
    addrinfo hints{}, *res = nullptr;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host.c_str(), std::to_string(port).c_str(), &hints, &res) != 0 || !res) return -1;
    int fd = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    if (fd < 0) { freeaddrinfo(res); return -1; }
    timeval tv{timeout_s, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
    if (connect(fd, res->ai_addr, res->ai_addrlen) != 0) { close(fd); freeaddrinfo(res); return -1; }
    freeaddrinfo(res);
    return fd;
}

std::string dechunk(const std::string &b) {
    std::string out;
    size_t p = 0;
    while (p < b.size()) {
        size_t e = b.find("\r\n", p);
        if (e == std::string::npos) break;
        size_t len = (size_t)strtoul(b.substr(p, e - p).c_str(), nullptr, 16);
        if (len == 0) break;
        out += b.substr(e + 2, len);
        p = e + 2 + len + 2;
    }
    return out;
}

// İstekte ondalık sayı YOK: PS5LM v0.8.x JSON'daki her ondalık sayıda çöküyor.
bool llama_call(const std::string &prompt, int adapter, int n_predict, std::string &out, std::string &err) {
    kj::Json body = kj::Json::object();
    body.set("prompt", kj::Json::str(prompt));
    body.set("n_predict", kj::Json::integer(n_predict));
    body.set("cache_prompt", kj::Json::boolean(false));
    kj::Json lora = kj::Json::array();
    for (int id = 0; id < 2; id++) {
        kj::Json l = kj::Json::object();
        l.set("id", kj::Json::integer(id));
        l.set("scale", kj::Json::integer(id == adapter ? 1 : 0));
        lora.push(l);
    }
    body.set("lora", lora);
    if (adapter == 0) body.set("top_k", kj::Json::integer(1));   // açgözlü

    std::string payload = kj::dump(body);
    waiting++;
    std::lock_guard<std::mutex> g(llm_mu);
    waiting--;
    int fd = connect_to(cfg.llama_host, cfg.llama_port, 120);
    if (fd < 0) { err = "model sunucusuna bağlanılamadı"; return false; }
    std::string req = "POST /completion HTTP/1.1\r\nHost: " + cfg.llama_host + "\r\nContent-Type: application/json\r\n"
                      "Content-Length: " + std::to_string(payload.size()) + "\r\nConnection: close\r\n\r\n" + payload;
    if (!send_all(fd, req.data(), req.size())) { close(fd); err = "model sunucusuna yazılamadı"; return false; }
    std::string resp;
    char tmp[8192];
    ssize_t n;
    while ((n = recv(fd, tmp, sizeof tmp, 0)) > 0) resp.append(tmp, (size_t)n);
    close(fd);
    size_t he = resp.find("\r\n\r\n");
    if (he == std::string::npos) { err = "model sunucusu yanıt vermedi"; return false; }
    std::string head = resp.substr(0, he), data = resp.substr(he + 4);
    if (head.compare(0, 12, "HTTP/1.1 200") != 0 && head.compare(0, 12, "HTTP/1.0 200") != 0) {
        err = "model sunucusu hata döndü: " + head.substr(0, head.find("\r\n"));
        return false;
    }
    if (kt::lower(head).find("transfer-encoding: chunked") != std::string::npos) data = dechunk(data);
    auto j = kj::parse(data);
    if (!j || !j->is_obj() || !j->get("content")) { err = "model yanıtı çözülemedi"; return false; }
    out = j->str_or("content");
    return true;
}

// Model sunucusu hazır mı? Yüklenirken 503 döner; o sırada öneri vermek yerine açık bir hata ver.
bool llama_ready() {
    int fd = connect_to(cfg.llama_host, cfg.llama_port, 3);
    if (fd < 0) return false;
    std::string req = "GET /health HTTP/1.1\r\nHost: " + cfg.llama_host + "\r\nConnection: close\r\n\r\n";
    if (!send_all(fd, req.data(), req.size())) { close(fd); return false; }
    std::string resp;
    char tmp[1024];
    ssize_t n;
    while ((n = recv(fd, tmp, sizeof tmp, 0)) > 0 && resp.size() < 4096) resp.append(tmp, (size_t)n);
    close(fd);
    return resp.compare(0, 12, "HTTP/1.1 200") == 0;
}

// ── uç noktalar ─────────────────────────────────────────────────────────────

bool parse_recommend(const kj::Json &j, kc::Request &r, std::string &err) {
    if (!j.is_obj()) { err = "gövde bir nesne olmalı"; return false; }
    for (const auto &kv : j.o) {
        static const char *known[] = {"query", "genres", "moods", "languages", "era", "length", "audience",
                                      "exclude_work_keys", "limit", "strictness", "seed"};
        bool ok = false;
        for (auto k : known) if (kv.first == k) ok = true;
        if (!ok) { err = "bilinmeyen alan: " + kv.first; return false; }
    }
    r.query = j.str_or("query");
    size_t a = 0, b = r.query.size();
    while (a < b && isspace((unsigned char)r.query[a])) a++;
    while (b > a && isspace((unsigned char)r.query[b - 1])) b--;
    r.query = r.query.substr(a, b - a);
    if (kt::length(r.query) > 500) { err = "query en fazla 500 karakter"; return false; }
    r.genres = j.strings("genres"); r.moods = j.strings("moods");
    r.exclude = j.strings("exclude_work_keys");
    for (const auto &l : j.strings("languages")) {
        if (l != "tur" && l != "eng") { err = "geçersiz dil: " + l; return false; }
        r.languages.push_back(l);
    }
    auto opt = [&](const char *k, std::string &dst) {
        const kj::Json *v = j.get(k);
        if (v && v->is_str()) dst = v->s;
    };
    opt("era", r.era); opt("length", r.length); opt("audience", r.audience);
    if (r.genres.size() > 12 || r.moods.size() > 12 || r.exclude.size() > 500) { err = "liste çok uzun"; return false; }
    const kj::Json *lim = j.get("limit");
    if (lim) {
        if (!lim->is_num() || lim->n < 1 || lim->n > 10) { err = "limit 1-10 olmalı"; return false; }
        r.limit = (int)lim->n;
    }
    r.strict = j.str_or("strictness") == "strict";
    return true;
}

kj::Json search_json(const std::vector<int> &docs, long long ms, const char *engine, const std::string &id) {
    kj::Json books = kj::Json::array();
    for (int d : docs) books.push(kc::book_json(catalog.books[d]));
    kj::Json m = kj::Json::object();
    m.set("request_id", kj::Json::str(id)); m.set("model", kj::Json::str("-")); m.set("engine", kj::Json::str(engine));
    m.set("latency_ms", kj::Json::integer(ms)); m.set("retrieved", kj::Json::integer((long long)docs.size()));
    m.set("grounded_ratio", kj::Json::number(1.0)); m.set("degraded", kj::Json::boolean(false));
    m.set("notes", kj::Json::array());
    kj::Json r = kj::Json::object();
    r.set("books", books); r.set("total", kj::Json::integer((long long)docs.size())); r.set("meta", m);
    return r;
}

HttpResponse handle_api(const HttpRequest &req) {
    const std::string &p = req.path;
    if (p == "/health") {
        kj::Json j = kj::Json::object();
        j.set("status", kj::Json::str("ok"));
        j.set("version", kj::Json::str("ps5-1.0"));
        j.set("engine", kj::Json::str("llama"));
        j.set("model", kj::Json::str(cfg.model_id));
        j.set("catalog_books", kj::Json::integer((long long)catalog.books.size()));
        j.set("catalog_path", kj::Json::str("-"));
        j.set("vectors_loaded", kj::Json::boolean(false));
        j.set("device", kj::Json::str("ps5"));
        j.set("uptime_s", kj::Json::number((double)(time(nullptr) - started_at)));
        j.set("now", kj::Json::integer((long long)time(nullptr)));
        {
            std::lock_guard<std::mutex> g(url_mu);
            j.set("public_url", public_url.empty() ? kj::Json() : kj::Json::str(public_url));
        }
        return json_response(200, j);
    }
    if (p == "/api/taxonomy") return json_response(200, meta.taxonomy);
    if (p == "/api/invite") {
        if (req.method != "POST") return error_response(405, "method_not_allowed");
        if (invite_rate_limited())
            return error_response(429, "too_many_attempts", "Çok fazla hatalı deneme. Bir dakika sonra tekrar dene.");
        auto j = kj::parse(req.body);
        std::string code = j && j->is_obj() ? j->str_or("code") : "";
        Invite inv;
        Auth a = check_code(code, &inv);
        if (a == Auth::Ok) {
            kj::Json r = kj::Json::object();
            r.set("ok", kj::Json::boolean(true));
            r.set("expires_at", kj::Json::integer((long long)inv.expires));
            r.set("label", kj::Json::str(inv.label));
            return json_response(200, r);
        }
        note_invite_failure();
        logf("davet reddedildi: " + std::string(a == Auth::Expired ? "süresi dolmuş" : "geçersiz"));
        return error_response(401, a == Auth::Expired ? "invite_expired" : "invite_invalid",
                              a == Auth::Expired ? "Bu davet kodunun süresi dolmuş." : "Davet kodu geçersiz.");
    }

    // Aşağıdakiler davet kodu ister (X-API-Key başlığı, istemcinin mevcut apiKey alanı).
    auto key = req.headers.find("x-api-key");
    Auth a = check_code(key == req.headers.end() ? "" : key->second);
    if (a != Auth::Ok)
        return error_response(401, a == Auth::Expired ? "invite_expired" : (a == Auth::Missing ? "invite_required" : "invite_invalid"),
                              a == Auth::Expired ? "Bu davet kodunun süresi dolmuş." : "Geçerli bir davet kodu gerekli.");

    auto started = std::chrono::steady_clock::now();
    auto ms = [&] { return (long long)std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started).count(); };

    if (p == "/api/recommend") {
        if (req.method != "POST") return error_response(405, "method_not_allowed");
        auto j = kj::parse(req.body);
        if (!j) return error_response(422, "validation_error", "geçersiz JSON");
        kc::Request r;
        std::string err;
        if (!parse_recommend(*j, r, err)) return error_response(422, "validation_error", err);
        if (waiting.load() >= 6) return error_response(503, "overloaded", "Sunucu meşgul, birkaç saniye sonra tekrar dene.");
        if (!llama_ready())
            return error_response(503, "model_loading", "Model yükleniyor, yaklaşık bir dakika sonra tekrar dene.");
        kc::PipelineConfig pc;
        pc.model_id = cfg.model_id;
        kj::Json out = kc::recommend(catalog, meta, r, llama_call, pc);
        logf("öneri: \"" + kt::prefix(r.query, 60) + "\" " + std::to_string(ms()) + " ms");
        return json_response(200, out);
    }
    if (p == "/api/search") {
        auto q = parse_query(req.query);
        std::string text = q["q"];
        int limit = q.count("limit") ? std::max(1, std::min(50, atoi(q["limit"].c_str()))) : 20;
        if (text.empty() || kt::length(text) > 200) return error_response(422, "validation_error", "q 1-200 karakter olmalı");
        kc::Request r;
        kc::Expansion e = kc::expand(meta, text, {}, {});
        kc::Retriever retr(catalog, meta);
        kc::Target t;
        auto hits = retr.search(e.query_text, r, t, limit);
        std::vector<int> docs;
        for (auto &h : hits) docs.push_back(h.first);
        return json_response(200, search_json(docs, ms(), "lexical", "search"));
    }
    if (p.compare(0, 10, "/api/book/") == 0) {
        std::string id = p.substr(10);
        std::string key2 = id.compare(0, 7, "/works/") == 0 ? id : "/works/" + id;
        auto it = catalog.by_key.find(key2);
        if (it == catalog.by_key.end()) return error_response(404, "not_found", "kitap bulunamadı: " + key2);
        return json_response(200, kc::book_json(catalog.books[it->second]));
    }
    if (p.compare(0, 13, "/api/similar/") == 0) {
        std::string id = p.substr(13);
        std::string key2 = id.compare(0, 7, "/works/") == 0 ? id : "/works/" + id;
        auto it = catalog.by_key.find(key2);
        auto q = parse_query(req.query);
        int limit = q.count("limit") ? std::max(1, std::min(20, atoi(q["limit"].c_str()))) : 8;
        std::vector<int> docs;
        if (it != catalog.by_key.end()) {
            const kc::Book &base = catalog.books[it->second];
            std::vector<std::pair<std::pair<size_t, double>, int>> cand;
            for (size_t d = 0; d < catalog.books.size(); d++) {
                if ((int)d == it->second) continue;
                const kc::Book &b = catalog.books[d];
                if (!kc::has_any(b.genres, base.genres)) continue;
                cand.push_back({{kc::overlap(b.subjects, base.subjects), b.popularity}, (int)d});
            }
            size_t keep = std::min<size_t>(limit, cand.size());
            std::partial_sort(cand.begin(), cand.begin() + keep, cand.end(), [](const auto &x, const auto &y) { return x.first > y.first; });
            for (size_t i = 0; i < keep; i++) docs.push_back(cand[i].second);
        }
        return json_response(200, search_json(docs, ms(), "retrieval", "similar"));
    }
    return error_response(404, "not_found");
}

// ── statik dosyalar ─────────────────────────────────────────────────────────

const char *mime_for(const std::string &path) {
    static const std::pair<const char *, const char *> types[] = {
        {".html", "text/html; charset=utf-8"}, {".js", "text/javascript; charset=utf-8"},
        {".mjs", "text/javascript; charset=utf-8"}, {".css", "text/css; charset=utf-8"},
        {".json", "application/json"}, {".webmanifest", "application/manifest+json"},
        {".svg", "image/svg+xml"}, {".png", "image/png"}, {".jpg", "image/jpeg"}, {".jpeg", "image/jpeg"},
        {".ico", "image/x-icon"}, {".txt", "text/plain; charset=utf-8"}, {".woff2", "font/woff2"}, {".map", "application/json"}};
    for (const auto &t : types) {
        size_t n = strlen(t.first);
        if (path.size() >= n && path.compare(path.size() - n, n, t.first) == 0) return t.second;
    }
    return "application/octet-stream";
}

HttpResponse handle_static(const HttpRequest &req) {
    std::string rel = req.path == "/" ? "/index.html" : req.path;
    if (rel.find("..") != std::string::npos || rel.find('\0') != std::string::npos)
        return error_response(400, "bad_path");
    std::string root = cfg.dir + "/web";
    bool ok = false;
    std::string body = slurp(root + rel, &ok);
    struct stat st;
    if (!ok || stat((root + rel).c_str(), &st) != 0 || S_ISDIR(st.st_mode)) {
        // SPA: dosya uzantısı olmayan yollar index.html'e düşer.
        if (rel.find('.') == std::string::npos) { body = slurp(root + "/index.html", &ok); rel = "/index.html"; }
        if (!ok) return error_response(404, "not_found");
    }
    HttpResponse r;
    r.type = mime_for(rel);
    r.body = std::move(body);
    r.extra.emplace_back("Cache-Control", rel == "/index.html" ? "no-cache" : "public, max-age=3600");
    return r;
}

void serve_connection(int fd) {
    connections++;
    timeval tv{15, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    HttpRequest req;
    int err_status = 400;
    if (!read_request(fd, req, err_status)) {
        if (err_status == 413) write_response(fd, error_response(413, "too_large"));
    } else if (req.method == "OPTIONS") {
        HttpResponse r;
        r.status = 204;
        write_response(fd, r);
    } else if (req.path == "/health" || req.path.compare(0, 5, "/api/") == 0) {
        write_response(fd, handle_api(req));
    } else if (req.method == "GET" || req.method == "HEAD") {
        write_response(fd, handle_static(req), req.method == "HEAD");
    } else {
        write_response(fd, error_response(405, "method_not_allowed"));
    }
    close(fd);
    connections--;
}

}  // namespace

int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    cfg.dir = env_or("KITAPAI_DIR", cfg.dir);
    cfg.llama_host = env_or("KITAPAI_LLAMA_HOST", cfg.llama_host);
    cfg.llama_port = atoi(env_or("KITAPAI_LLAMA_PORT", std::to_string(cfg.llama_port)).c_str());
    cfg.port = atoi(env_or("KITAPAI_PORT", std::to_string(cfg.port)).c_str());
    cfg.model_id = env_or("KITAPAI_MODEL_ID", cfg.model_id);
    if (argc > 1) cfg.dir = argv[1];

    auto t0 = std::chrono::steady_clock::now();
    std::string err;
    bool ok = false;
    std::string meta_text = slurp(cfg.dir + "/meta.json", &ok);
    if (!ok || !kc::load_meta(meta_text, meta, err)) { logf("meta.json yüklenemedi: " + err); return 1; }
    std::string tsv = slurp(cfg.dir + "/books.tsv", &ok);
    if (!ok || !catalog.load(tsv, meta, err)) { logf("books.tsv yüklenemedi: " + err); return 1; }
    tsv.clear();
    tsv.shrink_to_fit();
    logf("katalog hazır: " + std::to_string(catalog.books.size()) + " kitap, " +
         std::to_string((int)std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count()) + " sn");

    // Eski bir kopya aynı portu tutuyor olabilir (payload'u konsoldan durduramıyoruz): ilk boş porta bağlan.
    int srv = -1, first_port = cfg.port;
    for (int attempt = 0; attempt < 10; attempt++) {
        srv = socket(AF_INET, SOCK_STREAM, 0);
        int one = 1;
        setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
        sockaddr_in a{};
        a.sin_family = AF_INET;
        a.sin_port = htons((uint16_t)(first_port + attempt));
        a.sin_addr.s_addr = htonl(INADDR_ANY);
        if (bind(srv, (sockaddr *)&a, sizeof a) == 0 && listen(srv, 32) == 0) { cfg.port = first_port + attempt; break; }
        close(srv);
        srv = -1;
    }
    if (srv < 0) { logf("bind/listen başarısız (" + std::to_string(first_port) + "-" + std::to_string(first_port + 9) + ")"); return 1; }
    logf("dinleniyor: " + std::to_string(cfg.port) + "  (model: " + cfg.llama_host + ":" + std::to_string(cfg.llama_port) + ")");
    {
        std::ofstream(cfg.dir + "/port.txt") << cfg.port << "\n";
    }
    static std::atomic<bool> tunnel_stop{false};
    struct stat tst;
    if (env_or("KITAPAI_TUNNEL", "1") != "0" && stat((cfg.dir + "/tunnel.off").c_str(), &tst) != 0) {
        tun::Config tc;
        tc.local_port = cfg.port;
        std::ifstream tf(cfg.dir + "/tunnel.conf");   // isteğe bağlı: host=, port=, user=
        std::string tl;
        while (std::getline(tf, tl)) {
            size_t eq = tl.find('=');
            if (eq == std::string::npos) continue;
            std::string k = tl.substr(0, eq), v = tl.substr(eq + 1);
            while (!v.empty() && isspace((unsigned char)v.back())) v.pop_back();
            if (k == "host") tc.host = v;
            else if (k == "port") tc.port = atoi(v.c_str());
            else if (k == "user") tc.user = v;
            else if (k == "key") tc.key_file = v;
            else if (k == "bind") tc.bind_host = v;
            else if (k == "ips") { tc.fallback_ips.clear(); for (auto &ip : kc::split(v, ',')) if (!ip.empty()) tc.fallback_ips.push_back(ip); }
        }
        std::thread([tc] {
            tun::run_forever(tc, [](const std::string &m) { logf(m); }, [](const std::string &u) {
                { std::lock_guard<std::mutex> g(url_mu); public_url = u; }
                std::ofstream(cfg.dir + "/public_url.txt") << u << "\n";
            }, tunnel_stop);
        }).detach();
    }
    for (;;) {
        int fd = accept(srv, nullptr, nullptr);
        if (fd < 0) continue;
        if (connections.load() >= 48) { close(fd); continue; }
        std::thread(serve_connection, fd).detach();
    }
}
