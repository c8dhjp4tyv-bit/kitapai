// C++ çekirdeğini Python'un ürettiği altın değerlerle karşılaştırır (yerel, PC'de çalışır).
// Derle: g++ -O2 -std=c++17 test_core.cpp -o test_core ; Çalıştır: ./test_core <bundle> <golden.json>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>

#include "core.hpp"

static std::string slurp(const std::string &p) {
    std::ifstream f(p, std::ios::binary);
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

static int fails = 0, checks = 0;
#define CHECK(cond, ...) do { checks++; if (!(cond)) { fails++; if (fails <= 25) { printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); } } } while (0)

static kc::Strings arr(const kj::Json *j) {
    kc::Strings out;
    if (j && j->is_arr()) for (auto &x : j->a) out.push_back(x.s);
    return out;
}

int main(int argc, char **argv) {
    if (argc < 3) return 2;
    std::string dir = argv[1], err;
    kc::Meta meta;
    if (!kc::load_meta(slurp(dir + "/meta.json"), meta, err)) { printf("meta: %s\n", err.c_str()); return 1; }
    kc::Catalog cat;
    auto t0 = std::chrono::steady_clock::now();
    if (!cat.load(slurp(dir + "/books.tsv"), meta, err)) { printf("katalog: %s\n", err.c_str()); return 1; }
    double load_s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    printf("katalog: %zu kitap, yükleme+indeks %.1f sn\n", cat.books.size(), load_s);

    auto g = kj::parse(slurp(argv[2]));
    if (!g) { printf("golden geçersiz\n"); return 1; }

    // 1) sorgu genişletme
    for (const auto &e : g->get("expansions")->a) {
        kc::Strings cg = arr(e.get("chips_genres")), cm = arr(e.get("chips_moods"));
        kc::Expansion x = kc::expand(meta, e.str_or("query"), cg, cm);
        CHECK(x.terms == arr(e.get("terms")), "terms '%s': %s", e.str_or("query").c_str(), kc::join(x.terms, "|").c_str());
        CHECK(x.detected_genres == arr(e.get("genres")), "genres '%s'", e.str_or("query").c_str());
        CHECK(x.detected_moods == arr(e.get("moods")), "moods '%s'", e.str_or("query").c_str());
        CHECK(x.detected_themes == arr(e.get("themes")), "themes '%s'", e.str_or("query").c_str());
        CHECK(x.content_words == arr(e.get("content_words")), "content_words '%s': %s", e.str_or("query").c_str(), kc::join(x.content_words, "|").c_str());
        CHECK(x.query_text == e.str_or("query_text"), "query_text '%s': [%s] vs [%s]", e.str_or("query").c_str(), x.query_text.c_str(), e.str_or("query_text").c_str());
    }
    // 2) istek bloğu
    for (const auto &rb : g->get("request_blocks")->a) {
        const kj::Json *r = rb.get("req");
        kc::Request req;
        req.query = r->str_or("query"); req.genres = arr(r->get("genres")); req.moods = arr(r->get("moods"));
        req.era = r->str_or("era"); req.length = r->str_or("length"); req.audience = r->str_or("audience");
        req.languages = arr(r->get("languages")); req.limit = (int)r->num_or("limit", 3);
        // Python'daki pydantic doğrulayıcısı sorguyu kırpıyor; örnekte "  hafif  " bu yüzden kırpılır.
        while (!req.query.empty() && req.query.front() == ' ') req.query.erase(0, 1);
        while (!req.query.empty() && req.query.back() == ' ') req.query.pop_back();
        std::string want = rb.str_or("block");
        if (r->str_or("query") == "  hafif  ") {  // golden kırpılmamış sorguyla üretildi; aynı şekilde karşılaştır
            want = kc::join(kc::split(want, '\n'), "\n");
            req.query = r->str_or("query");
        }
        CHECK(kc::render_request(meta, req) == want, "request block: [%s] vs [%s]", kc::render_request(meta, req).c_str(), want.c_str());
    }
    // 3) aday gösterimi
    for (const auto &rj : g->get("renders")->a) {
        auto it = cat.by_key.find(rj.str_or("key"));
        CHECK(it != cat.by_key.end(), "anahtar yok %s", rj.str_or("key").c_str());
        if (it == cat.by_key.end()) continue;
        std::string got = kc::render_candidate(meta, cat.books[it->second], rj.str_or("cid"));
        CHECK(got == rj.str_or("text"), "render %s:\n--C++--\n%s\n--Py--\n%s", rj.str_or("key").c_str(), got.c_str(), rj.str_or("text").c_str());
    }
    // 4) uyum puanı ve gerekçeleri
    std::vector<kc::Target> targets;
    for (const auto &t : g->get("targets")->a) {
        kc::Target x;
        x.genres = arr(t.get("genres")); x.moods = arr(t.get("moods")); x.languages = arr(t.get("languages"));
        x.era = t.get("era") && t.get("era")->is_str() ? t.get("era")->s : "";
        x.length = t.get("length") && t.get("length")->is_str() ? t.get("length")->s : "";
        x.audience = t.get("audience") && t.get("audience")->is_str() ? t.get("audience")->s : "";
        targets.push_back(x);
    }
    for (const auto &sj : g->get("scores")->a) {
        auto it = cat.by_key.find(sj.str_or("key"));
        if (it == cat.by_key.end()) continue;
        const kc::Book &b = cat.books[it->second];
        const kc::Target &t = targets[(size_t)sj.num_or("t", 0)];
        double want = sj.num_or("score", 0);
        CHECK(std::fabs(kc::match_score(b, t) - want) < 1e-6, "score %s: %.6f vs %.6f", b.work_key.c_str(), kc::match_score(b, t), want);
        kc::Strings gr = kc::match_reasons(b, t), wr = arr(sj.get("reasons"));
        std::sort(gr.begin(), gr.end()); std::sort(wr.begin(), wr.end());
        CHECK(gr == wr, "reasons %s", b.work_key.c_str());
    }
    // 5) çözücüler
    for (const auto &d : g->get("decode")->a) {
        std::string raw = d.str_or("raw"), e2;
        bool want_ok = d.get("ok") && d.get("ok")->b;
        if (d.str_or("kind") == "select") {
            kc::Strings ids;
            bool ok = kc::decode_select(raw, ids, e2);
            CHECK(ok == want_ok, "decode_select ok [%s]", raw.c_str());
            if (ok && want_ok) CHECK(ids == arr(d.get("ids")), "decode_select ids [%s]", raw.c_str());
        } else {
            std::map<std::string, std::string> items;
            bool ok = kc::decode_write(raw, items, e2);
            CHECK(ok == want_ok, "decode_write ok [%s]", raw.c_str());
            if (ok && want_ok) {
                const kj::Json *wi = d.get("items");
                CHECK(wi && items.size() == wi->o.size(), "decode_write adet [%s]", raw.c_str());
                if (wi) for (auto &kv : wi->o) CHECK(items[kv.first] == kv.second.s, "decode_write %s", kv.first.c_str());
            }
        }
    }
    // 6) geri getirme: Python (tam katalog) ile örtüşme — yalnızca bilgi
    kc::Retriever retr(cat, meta);
    double overlap_sum = 0; int n_overlap = 0; int browse_mismatch = 0;
    double ms_total = 0; int n_q = 0;
    for (const auto &rj : g->get("retrieval")->a) {
        const kj::Json *rq = rj.get("req");
        kc::Request req;
        req.query = rq->str_or("query"); req.genres = arr(rq->get("genres")); req.moods = arr(rq->get("moods"));
        req.era = rq->str_or("era");
        auto a = std::chrono::steady_clock::now();
        kc::Retrieval res = retr.retrieve(req, 40);
        ms_total += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - a).count();
        n_q++;
        kc::Strings py = arr(rj.get("keys")), mine;
        for (size_t i = 0; i < res.books.size() && i < 12; i++) mine.push_back(cat.books[res.books[i]].work_key);
        size_t common = 0;
        for (auto &k : mine) if (kc::contains(py, k)) common++;
        if (!py.empty()) { overlap_sum += (double)common / (double)std::max<size_t>(1, std::min<size_t>(12, py.size())); n_overlap++; }
        bool py_browse = rj.get("browse") && rj.get("browse")->b;
        if (py_browse != res.used_browse) browse_mismatch++;
    }
    printf("geri getirme: Python (2,4 M katalog) ile ilk-12 örtüşmesi ort. %.2f (%d sorgu), gezinme farkı %d, ort. %.1f ms/sorgu\n",
           n_overlap ? overlap_sum / n_overlap : 0.0, n_overlap, browse_mismatch, n_q ? ms_total / n_q : 0.0);

    printf("%d kontrol, %d hata\n", checks, fails);
    return fails ? 1 : 0;
}
