// kitap.ai çekirdeği: katalog, BM25, sorgu genişletme, uyum puanı, istemler ve boru hattı.
// Python `src/kitapai` içindeki aynı adlı davranışın taşınmış hâlidir; PS5 payload'u ve yerel
// testler (golden) aynı kodu kullanır. SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <functional>
#include <map>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "json.hpp"
#include "text.hpp"

namespace kc {

using kj::Json;
using Strings = std::vector<std::string>;

// ── veri modeli ─────────────────────────────────────────────────────────────

struct Book {
    std::string work_key, title, subtitle, title_tr, description, era, length_bucket, audience, cover_url;
    Strings authors, subjects, languages, isbns, genres, moods, content_notes, hooks;
    int year = 0, pages = 0;
    double rating_avg = 0, popularity = 0;
    long long rating_count = 0, readers = 0;
    bool has_readers = false;
};

struct Target {
    Strings genres, moods, languages;
    std::string era, length, audience;
    bool any() const {
        return !genres.empty() || !moods.empty() || !era.empty() || !length.empty() || !audience.empty() ||
               !languages.empty();
    }
};

struct Request {
    std::string query;
    Strings genres, moods, languages, exclude;
    std::string era, length, audience;
    int limit = 3;
    bool strict = false;
};

struct Expansion {
    std::string original;
    Strings terms, detected_genres, detected_moods, detected_themes;
    std::set<std::string> consumed;
    Strings content_words;
    std::string query_text;
};

struct Meta {
    std::string select_prompt, write_prompt;
    int prompt_candidates = 12, description_chars = 170, write_base = 40, write_per_book = 90;
    std::map<std::string, std::string> genre_label, mood_label, era_label, length_label, audience_label;
    std::unordered_set<std::string> stopwords;
    std::vector<std::pair<std::string, std::string>> themes, genre_names, mood_adjs;
    std::map<std::string, Strings> genre_kw, mood_kw;
    Json taxonomy;
    std::unordered_map<int, std::string> fold;
    Strings columns;
};

// ── yardımcılar ─────────────────────────────────────────────────────────────

inline Strings split(const std::string &s, char sep) {
    Strings out;
    size_t st = 0;
    while (true) {
        size_t p = s.find(sep, st);
        if (p == std::string::npos) { out.push_back(s.substr(st)); break; }
        out.push_back(s.substr(st, p - st));
        st = p + 1;
    }
    return out;
}

inline Strings split_list(const std::string &s) {
    Strings out;
    if (s.empty()) return out;
    for (auto &x : split(s, '\x1f'))
        if (!x.empty()) out.push_back(x);
    return out;
}

inline bool has_any(const Strings &a, const Strings &b) {
    for (const auto &x : a)
        for (const auto &y : b)
            if (x == y) return true;
    return false;
}

inline size_t overlap(const Strings &a, const Strings &b) {
    std::set<std::string> sa(a.begin(), a.end());
    size_t n = 0;
    std::set<std::string> seen;
    for (const auto &y : b)
        if (sa.count(y) && seen.insert(y).second) n++;
    return n;
}

inline bool contains(const Strings &v, const std::string &x) { return std::find(v.begin(), v.end(), x) != v.end(); }

inline std::string join(const Strings &v, const std::string &sep) {
    std::string out;
    for (size_t i = 0; i < v.size(); i++) { if (i) out += sep; out += v[i]; }
    return out;
}

inline std::string join_and(Strings items) {
    items.erase(std::remove(items.begin(), items.end(), std::string()), items.end());
    if (items.empty()) return "";
    if (items.size() == 1) return items[0];
    Strings head(items.begin(), items.end() - 1);
    return join(head, ", ") + " ve " + items.back();
}

inline std::string fmt1(double v) {
    char buf[32];
    snprintf(buf, sizeof buf, "%.1f", v);
    return buf;
}

// ── meta.json ────────────────────────────────────────────────────────────────

inline std::map<std::string, std::string> str_map(const Json *j) {
    std::map<std::string, std::string> out;
    if (j && j->is_obj())
        for (const auto &kv : j->o)
            if (kv.second.is_str()) out[kv.first] = kv.second.s;
    return out;
}

inline bool load_meta(const std::string &text, Meta &m, std::string &err) {
    auto root = kj::parse(text);
    if (!root || !root->is_obj()) { err = "meta.json geçersiz"; return false; }
    const Json &r = *root;
    const Json *prompts = r.get("prompts");
    if (!prompts) { err = "meta.json: prompts yok"; return false; }
    m.select_prompt = prompts->str_or("select");
    m.write_prompt = prompts->str_or("write");
    if (const Json *c = r.get("constants")) {
        m.prompt_candidates = (int)c->num_or("prompt_candidates", 12);
        m.description_chars = (int)c->num_or("description_chars", 170);
        m.write_base = (int)c->num_or("write_base_tokens", 40);
        m.write_per_book = (int)c->num_or("write_tokens_per_book", 90);
    }
    if (const Json *l = r.get("labels")) {
        m.genre_label = str_map(l->get("genre"));
        m.mood_label = str_map(l->get("mood"));
        m.era_label = str_map(l->get("era"));
        m.length_label = str_map(l->get("length"));
        m.audience_label = str_map(l->get("audience"));
    }
    for (const auto &w : r.strings("stopwords")) m.stopwords.insert(w);
    if (const Json *e = r.get("expansion")) {
        auto pairs = [](const Json *v, std::vector<std::pair<std::string, std::string>> &out) {
            if (!v || !v->is_arr()) return;
            for (const auto &p : v->a)
                if (p.is_arr() && p.a.size() == 2) out.emplace_back(p.a[0].s, p.a[1].s);
        };
        pairs(e->get("themes"), m.themes);
        pairs(e->get("genre_names"), m.genre_names);
        pairs(e->get("mood_adjectives"), m.mood_adjs);
        auto kw = [](const Json *v, std::map<std::string, Strings> &out) {
            if (!v || !v->is_obj()) return;
            for (const auto &kv : v->o) out[kv.first] = kv.second.is_arr() ? [&] {
                Strings s; for (const auto &x : kv.second.a) s.push_back(x.s); return s; }() : Strings();
        };
        kw(e->get("genre_keywords"), m.genre_kw);
        kw(e->get("mood_keywords"), m.mood_kw);
    }
    if (const Json *t = r.get("taxonomy")) m.taxonomy = *t;
    if (const Json *f = r.get("fold"))
        if (f->is_obj())
            for (const auto &kv : f->o) m.fold[atoi(kv.first.c_str())] = kv.second.s;
    m.columns = r.strings("columns");
    return !m.select_prompt.empty() && !m.write_prompt.empty();
}

// ── katalog + BM25 ──────────────────────────────────────────────────────────

class Catalog {
public:
    std::vector<Book> books;
    std::unordered_map<std::string, int> by_key;

    bool load(const std::string &tsv_text, const Meta &meta, std::string &err) {
        folder_.load(meta.fold);
        std::unordered_map<std::string, int> col;
        for (size_t i = 0; i < meta.columns.size(); i++) col[meta.columns[i]] = (int)i;
        for (const char *need : {"work_key", "title", "description", "popularity", "hooks"})
            if (!col.count(need)) { err = std::string("sütun yok: ") + need; return false; }
        size_t pos = 0;
        while (pos < tsv_text.size()) {
            size_t nl = tsv_text.find('\n', pos);
            if (nl == std::string::npos) nl = tsv_text.size();
            std::string line = tsv_text.substr(pos, nl - pos);
            pos = nl + 1;
            if (line.empty()) continue;
            Strings f = split(line, '\t');
            if (f.size() < meta.columns.size()) f.resize(meta.columns.size());
            auto g = [&](const char *n) -> const std::string & { return f[col.at(n)]; };
            Book b;
            b.work_key = g("work_key"); b.title = g("title"); b.subtitle = g("subtitle");
            b.title_tr = g("title_tr"); b.description = g("description");
            b.authors = split_list(g("authors")); b.subjects = split_list(g("subjects"));
            b.languages = split_list(g("languages")); b.isbns = split_list(g("isbns"));
            b.genres = split_list(g("genres")); b.moods = split_list(g("moods"));
            b.era = g("era"); b.length_bucket = g("length_bucket"); b.audience = g("audience");
            b.cover_url = g("cover_url");
            b.content_notes = split_list(g("content_notes")); b.hooks = split_list(g("hooks"));
            b.year = g("first_published").empty() ? 0 : atoi(g("first_published").c_str());
            b.pages = g("pages").empty() ? 0 : atoi(g("pages").c_str());
            b.rating_avg = g("rating_avg").empty() ? 0 : atof(g("rating_avg").c_str());
            b.rating_count = g("rating_count").empty() ? 0 : atoll(g("rating_count").c_str());
            b.has_readers = !g("readers").empty();
            b.readers = b.has_readers ? atoll(g("readers").c_str()) : 0;
            b.popularity = g("popularity").empty() ? 0 : atof(g("popularity").c_str());
            by_key[b.work_key] = (int)books.size();
            books.push_back(std::move(b));
        }
        build_index();
        return !books.empty();
    }

    // DuckDB FTS'in indekslediği alanlar: title, subtitle, title_tr, authors, subjects, description.
    const std::vector<std::pair<int, int>> *postings(const std::string &term) const {
        auto it = dict_.find(term);
        return it == dict_.end() ? nullptr : &post_[it->second];
    }
    size_t doc_count() const { return books.size(); }
    double avgdl() const { return avgdl_; }
    int doclen(int d) const { return dl_[d]; }
    Strings query_terms(const std::string &text) const {
        Strings out;
        std::unordered_set<std::string> seen;
        Porter p;
        for (const auto &t : folder_.tokens(text)) {
            if (kt::english_stopwords().count(t)) continue;
            std::string s = p.stem(t);
            if (seen.insert(s).second) out.push_back(s);
        }
        return out;
    }

private:
    kt::Folder folder_;
    using Porter = kt::Porter;
    std::unordered_map<std::string, int> dict_;
    std::vector<std::vector<std::pair<int, int>>> post_;   // (doc, tf)
    std::vector<int> dl_;
    double avgdl_ = 1;

    void build_index() {
        Porter p;
        std::unordered_map<std::string, std::string> stem_cache;
        dl_.assign(books.size(), 0);
        double total = 0;
        for (size_t d = 0; d < books.size(); d++) {
            const Book &b = books[d];
            std::string doc = b.title + " " + b.subtitle + " " + b.title_tr + " " + join(b.authors, ", ") + " " +
                              join(b.subjects, ", ") + " " + b.description;
            std::unordered_map<int, int> tf;
            int len = 0;
            for (const auto &t : folder_.tokens(doc)) {
                if (kt::english_stopwords().count(t)) continue;
                auto sc = stem_cache.find(t);
                if (sc == stem_cache.end()) sc = stem_cache.emplace(t, p.stem(t)).first;
                auto di = dict_.find(sc->second);
                int id;
                if (di == dict_.end()) {
                    id = (int)post_.size();
                    dict_.emplace(sc->second, id);
                    post_.emplace_back();
                } else id = di->second;
                tf[id]++;
                len++;
            }
            dl_[d] = len;
            total += len;
            for (const auto &kv : tf) post_[kv.first].emplace_back((int)d, kv.second);
        }
        avgdl_ = books.empty() ? 1 : std::max(1.0, total / (double)books.size());
    }
};

// ── sorgu genişletme (retrieval/expand.py) ──────────────────────────────────

inline bool mentions(const std::string &needle, const std::string &hay) {
    if (needle.empty()) return false;
    size_t pos = 0;
    while ((pos = hay.find(needle, pos)) != std::string::npos) {
        if (pos == 0) return true;
        char c = hay[pos - 1];
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == ',' || c == '.' || c == ';' || c == ':' ||
            c == '!' || c == '?' || c == '(' || c == ')' || c == '-')
            return true;
        pos++;
    }
    return false;
}

inline Expansion expand(const Meta &m, const std::string &text, const Strings &genres, const Strings &moods) {
    Expansion e;
    e.original = text;
    std::string folded = kt::fold(text);

    for (const auto &[tr_name, subject] : m.themes) {
        if (kt::length(tr_name) >= 3 && mentions(kt::fold(tr_name), folded)) {
            e.terms.push_back(subject);
            e.detected_themes.push_back(tr_name);
            for (const auto &w : kt::split_ws(kt::fold(tr_name))) e.consumed.insert(w);
        }
    }
    for (const auto &[name, slug] : m.genre_names) {
        if (kt::length(name) >= 4 && mentions(kt::fold(name), folded) && !contains(e.detected_genres, slug)) {
            e.detected_genres.push_back(slug);
            for (const auto &w : kt::split_ws(kt::fold(name))) e.consumed.insert(w);
        }
    }
    for (const auto &[adj, slug] : m.mood_adjs) {
        if (kt::length(adj) >= 4 && mentions(kt::fold(adj), folded) && !contains(e.detected_moods, slug)) {
            e.detected_moods.push_back(slug);
            for (const auto &w : kt::split_ws(kt::fold(adj))) e.consumed.insert(w);
        }
    }
    Strings g = genres;
    g.insert(g.end(), e.detected_genres.begin(), e.detected_genres.end());
    for (const auto &slug : g) {
        auto it = m.genre_kw.find(slug);
        if (it != m.genre_kw.end()) e.terms.insert(e.terms.end(), it->second.begin(), it->second.end());
    }
    Strings mo = moods;
    mo.insert(mo.end(), e.detected_moods.begin(), e.detected_moods.end());
    for (const auto &slug : mo) {
        auto it = m.mood_kw.find(slug);
        if (it != m.mood_kw.end()) e.terms.insert(e.terms.end(), it->second.begin(), it->second.end());
    }
    std::set<std::string> seen;
    Strings uniq;
    for (const auto &t : e.terms)
        if (seen.insert(t).second) uniq.push_back(t);
    if (uniq.size() > 24) uniq.resize(24);
    e.terms = uniq;

    for (const auto &w : kt::word_tokens(kt::lower(text)))
        if (!m.stopwords.count(w) && kt::length(w) > 2 && !e.consumed.count(w)) e.content_words.push_back(w);
    Strings all = e.content_words;
    all.insert(all.end(), e.terms.begin(), e.terms.end());
    e.query_text = join(all, " ");
    // Python: " ".join(...).strip()
    while (!e.query_text.empty() && e.query_text.back() == ' ') e.query_text.pop_back();
    return e;
}

// ── uyum puanı (matching.py) ────────────────────────────────────────────────

inline double match_score(const Book &b, const Target &q) {
    double score = 0, weight = 0;
    if (!q.genres.empty()) {
        weight += 3.0;
        score += 3.0 * std::min(1.0, (double)overlap(q.genres, b.genres) / (double)q.genres.size());
    }
    if (!q.moods.empty()) {
        weight += 2.0;
        score += 2.0 * std::min(1.0, (double)overlap(q.moods, b.moods) / (double)q.moods.size());
    }
    if (!q.era.empty()) { weight += 1.5; if (b.era == q.era) score += 1.5; }
    if (!q.length.empty()) { weight += 1.5; if (b.length_bucket == q.length) score += 1.5; }
    if (!q.audience.empty()) { weight += 1.0; if (b.audience == q.audience) score += 1.0; }
    if (!q.languages.empty()) { weight += 1.0; if (has_any(q.languages, b.languages)) score += 1.0; }
    if (weight == 0) return 0.45 + 0.45 * b.popularity;
    double base = score / weight;
    return std::max(0.0, std::min(1.0, 0.85 * base + 0.15 * b.popularity));
}

inline Strings match_reasons(const Book &b, const Target &q) {
    Strings out;
    std::set<std::string> gs(q.genres.begin(), q.genres.end()), ms(q.moods.begin(), q.moods.end());
    for (const auto &s : gs) if (contains(b.genres, s)) out.push_back("tür:" + s);
    for (const auto &s : ms) if (contains(b.moods, s)) out.push_back("ruh:" + s);
    if (!q.era.empty() && b.era == q.era) out.push_back("dönem:" + q.era);
    if (!q.length.empty() && b.length_bucket == q.length) out.push_back("uzunluk:" + q.length);
    std::set<std::string> common;
    for (const auto &l : q.languages) if (contains(b.languages, l)) common.insert(l);
    if (!common.empty()) out.push_back("dil:" + join(Strings(common.begin(), common.end()), ","));
    return out;
}

// ── geri getirme (retrieval/hybrid.py, yalnızca sözcüksel) ──────────────────

struct Retrieval {
    Target target;
    std::vector<int> books;   // katalog dizinleri, nihai sırayla
    Expansion exp;
    bool used_browse = false;
};

constexpr int RRF_K = 60;

class Retriever {
public:
    Retriever(const Catalog &c, const Meta &m) : cat_(c), meta_(m) {}

    static bool passes(const Book &b, const Request &r, const Target &t, bool strict) {
        if (!t.languages.empty() && !has_any(t.languages, b.languages)) return false;
        if (!r.era.empty() && b.era != r.era) return false;
        if (!r.length.empty() && b.length_bucket != r.length) return false;
        if (!r.audience.empty() && b.audience != r.audience) return false;
        if (strict) {
            if (!t.genres.empty() && !has_any(t.genres, b.genres)) return false;
            if (!t.moods.empty() && !has_any(t.moods, b.moods)) return false;
        }
        return true;
    }

    // BM25 (k1=1.2, b=0.75), DuckDB FTS ile aynı idf: ln((N - df + 0.5) / (df + 0.5)).
    std::vector<std::pair<int, double>> search(const std::string &text, const Request &r, const Target &t,
                                               int limit) const {
        std::vector<std::pair<int, double>> out;
        Strings terms = cat_.query_terms(text);
        if (terms.empty()) return out;
        const double N = (double)cat_.doc_count(), k1 = 1.2, b = 0.75;
        std::unordered_map<int, double> acc;
        for (const auto &term : terms) {
            const auto *p = cat_.postings(term);
            if (!p) continue;
            double df = (double)p->size();
            double idf = std::log((N - df + 0.5) / (df + 0.5));
            for (const auto &[doc, tf] : *p) {
                double norm = tf + k1 * (1 - b + b * cat_.doclen(doc) / cat_.avgdl());
                acc[doc] += idf * (tf * (k1 + 1)) / norm;
            }
        }
        for (const auto &[doc, sc] : acc)
            if (sc > 0 && passes(cat_.books[doc], r, t, r.strict)) out.emplace_back(doc, sc);
        size_t keep = std::min<size_t>(limit, out.size());
        std::partial_sort(out.begin(), out.begin() + keep, out.end(), [](const auto &x, const auto &y) {
            return x.second != y.second ? x.second > y.second : x.first < y.first;
        });
        out.resize(keep);
        return out;
    }

    Retrieval retrieve(const Request &req, int pool) const {
        Retrieval res;
        Expansion exp = expand(meta_, req.query, req.genres, req.moods);
        Strings eg = req.genres, em = req.moods;
        if (eg.empty()) { eg = exp.detected_genres; if (eg.size() > 2) eg.resize(2); }
        if (em.empty()) { em = exp.detected_moods; if (em.size() > 2) em.resize(2); }
        Target t;
        t.genres = eg; t.moods = em; t.era = req.era; t.length = req.length; t.audience = req.audience;
        t.languages = req.languages;
        res.target = t;
        res.exp = exp;

        std::unordered_set<std::string> exclude(req.exclude.begin(), req.exclude.end());
        auto hits = search(exp.query_text, req, t, pool);
        // exclude_keys SQL'de de uygulanır; havuz dolmadan elenenler için arama genişletilir.
        if (!exclude.empty()) {
            auto wide = search(exp.query_text, req, t, pool + (int)exclude.size());
            hits.clear();
            for (auto &h : wide)
                if (!exclude.count(cat_.books[h.first].work_key)) hits.push_back(h);
            if ((int)hits.size() > pool) hits.resize(pool);
        }

        std::vector<std::pair<int, double>> fused;   // (doc, rrf puanı)
        for (size_t i = 0; i < hits.size(); i++) fused.emplace_back(hits[i].first, 1.0 / (RRF_K + (double)(i + 1)));
        if (fused.empty()) {
            res.used_browse = true;
            for (size_t d = 0; d < cat_.books.size() && (int)fused.size() < pool; d++) {
                const Book &b = cat_.books[d];
                if (exclude.count(b.work_key) || !passes(b, req, t, req.strict)) continue;
                fused.emplace_back((int)d, b.popularity);
            }
        }
        std::vector<std::pair<double, int>> scored;
        for (const auto &[doc, fusion] : fused) {
            const Book &b = cat_.books[doc];
            if (exclude.count(b.work_key)) continue;
            if (req.strict && !passes(b, req, t, true)) continue;
            double total = std::min(1.0, fusion * RRF_K) + 1.2 * match_score(b, t) + 0.35 * b.popularity;
            scored.emplace_back(total, doc);
        }
        std::stable_sort(scored.begin(), scored.end(), [](const auto &x, const auto &y) { return x.first > y.first; });
        for (size_t i = 0; i < scored.size() && (int)i < pool; i++) res.books.push_back(scored[i].second);
        return res;
    }

private:
    const Catalog &cat_;
    const Meta &meta_;
};

// ── istemler (prompting.py) ─────────────────────────────────────────────────

inline std::string labels(const Strings &slugs, const std::map<std::string, std::string> &table) {
    Strings out;
    for (const auto &s : slugs) {
        auto it = table.find(s);
        if (it != table.end()) out.push_back(it->second);
    }
    return join(out, ", ");
}

inline std::string render_candidate(const Meta &m, const Book &c, const std::string &cid) {
    std::string head = "[" + cid + "] " + c.title;
    if (!c.title_tr.empty() && kt::lower(c.title_tr) != kt::lower(c.title)) head += " (TR: " + c.title_tr + ")";
    if (!c.authors.empty()) {
        Strings a(c.authors.begin(), c.authors.begin() + std::min<size_t>(2, c.authors.size()));
        head += " — " + join_and(a);
    }
    if (c.year) head += " · " + std::to_string(c.year);

    Strings facts;
    std::string genres = labels(c.genres, m.genre_label), moods = labels(c.moods, m.mood_label);
    if (!genres.empty()) facts.push_back("tür: " + genres);
    if (!moods.empty()) facts.push_back("ruh: " + moods);
    if (c.pages) facts.push_back(std::to_string(c.pages) + " sf.");
    if (c.rating_avg != 0 && c.rating_count != 0)
        facts.push_back("puan " + fmt1(c.rating_avg) + "/5 (" + std::to_string(c.rating_count) + " oy)");
    if (contains(c.languages, "tur")) facts.push_back("Türkçe baskısı var");

    std::string out = head;
    if (!facts.empty()) out += "\n     " + join(facts, " | ");
    if (!c.subjects.empty()) {
        Strings s(c.subjects.begin(), c.subjects.begin() + std::min<size_t>(6, c.subjects.size()));
        out += "\n     konular: " + join(s, ", ");
    }
    if (!c.description.empty()) {
        std::string desc = join(kt::split_ws(c.description), " ");
        if ((int)kt::length(desc) > m.description_chars) {
            desc = kt::prefix(desc, m.description_chars);
            size_t sp = desc.rfind(' ');
            if (sp != std::string::npos) desc = desc.substr(0, sp);
            desc += "…";
        }
        out += "\n     özet: " + desc;
    }
    return out;
}

inline std::string render_request(const Meta &m, const Request &r) {
    std::string out = r.query.empty() ? "Okurun sözleri: (belirtmedi)" : "Okurun sözleri: " + r.query;
    Strings filters;
    if (!r.genres.empty()) filters.push_back("tür: " + labels(r.genres, m.genre_label));
    if (!r.moods.empty()) filters.push_back("ruh hali: " + labels(r.moods, m.mood_label));
    auto lookup = [](const std::map<std::string, std::string> &t, const std::string &k) {
        auto it = t.find(k);
        return it == t.end() ? k : it->second;
    };
    if (!r.era.empty()) filters.push_back("dönem: " + lookup(m.era_label, r.era));
    if (!r.length.empty()) filters.push_back("uzunluk: " + lookup(m.length_label, r.length));
    if (!r.audience.empty()) filters.push_back("okur: " + lookup(m.audience_label, r.audience));
    if (!r.languages.empty()) filters.push_back("dil: " + join(r.languages, ", "));
    if (!filters.empty()) out += "\nFiltreler: " + join(filters, " | ");
    out += "\nİstenen öneri sayısı: " + std::to_string(r.limit);
    return out;
}

inline std::string chatml(const std::string &system, const std::string &user) {
    return "<|im_start|>system\n" + system + "<|im_end|>\n<|im_start|>user\n" + user +
           "<|im_end|>\n<|im_start|>assistant\n";
}

inline std::string select_prompt(const Meta &m, const std::string &request_block, const Strings &candidates) {
    std::string user = "İSTEK\n" + request_block + "\n\nADAYLAR\n" + join(candidates, "\n") +
                       "\n\nYanıtı yalnızca JSON olarak ver.";
    return chatml(m.select_prompt, user);
}

inline std::string write_prompt(const Meta &m, const std::string &request_block,
                                const std::vector<std::pair<std::string, std::string>> &books) {
    Strings parts;
    for (const auto &[block, strength] : books) parts.push_back(block + "\n     uyum: " + strength);
    std::string user = "OKURUN İSTEĞİ\n" + request_block + "\n\nSEÇİLEN KİTAPLAR\n" + join(parts, "\n\n");
    return chatml(m.write_prompt, user);
}

inline std::string match_strength(double c) { return c >= 0.75 ? "güçlü" : (c >= 0.5 ? "orta" : "zayıf"); }

// ── model çıktısı (serve/decode.py) ─────────────────────────────────────────

inline std::optional<std::string> first_object(const std::string &t) {
    size_t start = t.find('{');
    if (start == std::string::npos) return std::nullopt;
    int depth = 0;
    bool in_str = false, esc = false;
    for (size_t i = start; i < t.size(); i++) {
        char c = t[i];
        if (in_str) {
            if (esc) esc = false;
            else if (c == '\\') esc = true;
            else if (c == '"') in_str = false;
            continue;
        }
        if (c == '"') in_str = true;
        else if (c == '{') depth++;
        else if (c == '}') { depth--; if (depth == 0) return t.substr(start, i - start + 1); }
    }
    return std::nullopt;
}

inline std::string close_truncated(const std::string &t) {
    std::string out = t, stack;
    bool in_str = false, esc = false;
    for (char c : t) {
        if (in_str) {
            if (esc) esc = false;
            else if (c == '\\') esc = true;
            else if (c == '"') in_str = false;
            continue;
        }
        if (c == '"') in_str = true;
        else if (c == '{') stack += '}';
        else if (c == '[') stack += ']';
        else if ((c == '}' || c == ']') && !stack.empty()) stack.pop_back();
    }
    if (in_str) out += '"';
    while (!out.empty() && (out.back() == ',' || out.back() == ' ')) out.pop_back();
    return out + std::string(stack.rbegin(), stack.rend());   // en son açılan önce kapanır
}

inline std::string strip_trailing_commas(const std::string &s) {
    std::string out;
    bool in_str = false, esc = false;
    for (size_t i = 0; i < s.size(); i++) {
        char c = s[i];
        if (in_str) {
            out += c;
            if (esc) esc = false;
            else if (c == '\\') esc = true;
            else if (c == '"') in_str = false;
            continue;
        }
        if (c == '"') { in_str = true; out += c; continue; }
        if (c == ',') {
            size_t j = i + 1;
            while (j < s.size() && isspace((unsigned char)s[j])) j++;
            if (j < s.size() && (s[j] == '}' || s[j] == ']')) continue;
        }
        out += c;
    }
    return out;
}

inline std::optional<Json> parse_object(const std::string &raw, std::string &err) {
    std::string trimmed = raw;
    while (!trimmed.empty() && isspace((unsigned char)trimmed.back())) trimmed.pop_back();
    size_t b = 0;
    while (b < trimmed.size() && isspace((unsigned char)trimmed[b])) b++;
    trimmed = trimmed.substr(b);
    if (trimmed.empty()) { err = "boş çıktı"; return std::nullopt; }
    size_t f = trimmed.find("```");
    if (f != std::string::npos) {
        size_t e = trimmed.find("```", f + 3);
        if (e != std::string::npos) {
            std::string inner = trimmed.substr(f + 3, e - f - 3);
            if (inner.compare(0, 4, "json") == 0) inner = inner.substr(4);
            trimmed = inner;
        }
    }
    auto cand = first_object(trimmed);
    std::string base = cand ? *cand : close_truncated(trimmed.find('{') == std::string::npos ? trimmed
                                                                                            : trimmed.substr(trimmed.find('{')));
    for (const std::string &payload : {base, strip_trailing_commas(base), close_truncated(base)}) {
        auto j = kj::parse(payload);
        if (j && j->is_obj()) return j;
    }
    err = "geçersiz JSON";
    return std::nullopt;
}

inline bool decode_select(const std::string &raw, Strings &ids, std::string &err) {
    auto j = parse_object(raw, err);
    if (!j) return false;
    const Json *v = j->get("ids");
    if (!v || !v->is_arr()) { err = "'ids' listesi yok"; return false; }
    ids.clear();
    for (const auto &x : v->a)
        if (x.is_str() && !contains(ids, x.s)) ids.push_back(x.s);
    return true;
}

// `a1: gerekçe` satırları; kimlik tekrarlanırsa ilki geçerli.
inline bool decode_write(const std::string &raw, std::map<std::string, std::string> &out, std::string &err) {
    out.clear();
    std::istringstream in(raw);
    std::string line;
    while (std::getline(in, line)) {
        size_t i = 0;
        while (i < line.size() && isspace((unsigned char)line[i])) i++;
        if (i < line.size() && (line[i] == '-' || line[i] == '*')) i++;
        while (i < line.size() && isspace((unsigned char)line[i])) i++;
        while (i < line.size() && line[i] == '*') i++;
        if (i >= line.size() || line[i] != 'a') continue;
        size_t d = i + 1;
        while (d < line.size() && isdigit((unsigned char)line[d])) d++;
        if (d == i + 1) continue;
        std::string id = line.substr(i, d - i);
        while (d < line.size() && line[d] == '*') d++;
        while (d < line.size() && isspace((unsigned char)line[d])) d++;
        if (d >= line.size()) continue;
        size_t colon_len = 0;
        if (line[d] == ':') colon_len = 1;
        else if (line.compare(d, 3, "\xEF\xBC\x9A") == 0) colon_len = 3;   // tam genişlikli ':'
        else continue;
        std::string why = line.substr(d + colon_len);
        size_t a = 0;
        while (a < why.size() && isspace((unsigned char)why[a])) a++;
        while (!why.empty() && isspace((unsigned char)why.back())) why.pop_back();
        why = why.substr(std::min(a, why.size()));
        if (why.empty()) continue;
        out.emplace(id, why);
    }
    if (out.empty()) { err = "gerekçe satırı yok (beklenen: 'a1: ...')"; return false; }
    return true;
}

// ── boru hattı (serve/pipeline.py) ──────────────────────────────────────────

// adapter: 0 = seçici (açgözlü), 1 = yazıcı. Başarılıysa true ve `out` dolu.
using LlmFn = std::function<bool(const std::string &prompt, int adapter, int n_predict, std::string &out,
                                 std::string &err)>;

inline std::string random_hex(size_t n) {
    static std::mt19937_64 rng(std::random_device{}() ^ (uint64_t)std::chrono::steady_clock::now().time_since_epoch().count());
    static const char *h = "0123456789abcdef";
    std::string s;
    for (size_t i = 0; i < n; i++) s += h[rng() % 16];
    return s;
}

inline Json book_json(const Book &b) {
    Json j = Json::object();
    j.set("work_key", Json::str(b.work_key));
    j.set("title", Json::str(!b.title_tr.empty() ? b.title_tr : b.title));
    j.set("subtitle", b.subtitle.empty() ? Json() : Json::str(b.subtitle));
    j.set("authors", Json::str_array(b.authors));
    j.set("first_published", b.year ? Json::integer(b.year) : Json());
    j.set("description", b.description.empty() ? Json() : Json::str(b.description));
    j.set("genres", Json::str_array(b.genres));
    j.set("moods", Json::str_array(b.moods));
    Strings subj(b.subjects.begin(), b.subjects.begin() + std::min<size_t>(12, b.subjects.size()));
    j.set("subjects", Json::str_array(subj));
    j.set("languages", Json::str_array(b.languages));
    j.set("pages", b.pages ? Json::integer(b.pages) : Json());
    Strings isbns(b.isbns.begin(), b.isbns.begin() + std::min<size_t>(4, b.isbns.size()));
    j.set("isbns", Json::str_array(isbns));
    j.set("cover_url", b.cover_url.empty() ? Json() : Json::str(b.cover_url));
    j.set("openlibrary_url", Json::str("https://openlibrary.org" + b.work_key));
    if (b.rating_avg != 0 && b.rating_count != 0) {
        Json r = Json::object();
        r.set("average", Json::number(b.rating_avg));
        r.set("count", Json::integer(b.rating_count));
        j.set("rating", r);
    } else j.set("rating", Json());
    j.set("readers", b.has_readers ? Json::integer(b.readers) : Json());
    j.set("popularity", Json::number(b.popularity));
    return j;
}

struct PipelineConfig {
    int pool = 40;
    double min_confidence = 0.5;
    std::string model_id = "llama-server@ps5";
    std::string engine = "llama";
};

inline Json recommend(const Catalog &cat, const Meta &meta, const Request &req, const LlmFn &llm,
                      const PipelineConfig &cfg) {
    auto started = std::chrono::steady_clock::now();
    Strings notes;
    Retriever retriever(cat, meta);
    Retrieval r = retriever.retrieve(req, cfg.pool);
    auto latency = [&] {
        return (long long)std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started)
            .count();
    };
    auto meta_json = [&](size_t retrieved, double grounded, bool degraded) {
        Json m = Json::object();
        m.set("request_id", Json::str(random_hex(12)));
        m.set("model", Json::str(cfg.model_id));
        m.set("engine", Json::str(cfg.engine));
        m.set("latency_ms", Json::integer(latency()));
        m.set("retrieved", Json::integer((long long)retrieved));
        m.set("grounded_ratio", Json::number(grounded));
        m.set("degraded", Json::boolean(degraded));
        m.set("notes", Json::str_array(notes));
        return m;
    };
    Json resp = Json::object();
    if (r.books.empty()) {
        notes.push_back("aday bulunamadı");
        resp.set("recommendations", Json::array());
        resp.set("followups", Json::str_array({"Filtreleri gevşetmeyi dener misin? Bu kısıtlara uyan kitap bulamadım."}));
        resp.set("meta", meta_json(0, 0.0, false));
        return resp;
    }
    if (r.used_browse) notes.push_back("metin eşleşmesi yok; bilinirliğe göre gezinme kullanıldı");
    if (!r.exp.detected_genres.empty() && req.genres.empty())
        notes.push_back("metinden çıkarılan tür: " + join(r.exp.detected_genres, ", "));

    size_t n_short = std::min<size_t>(meta.prompt_candidates, r.books.size());
    std::vector<std::string> cids;
    Strings blocks;
    std::map<std::string, int> by_id;
    for (size_t i = 0; i < n_short; i++) {
        std::string cid = "a" + std::to_string(i + 1);
        cids.push_back(cid);
        by_id[cid] = r.books[i];
        blocks.push_back(render_candidate(meta, cat.books[r.books[i]], cid));
    }
    std::string request_block = render_request(meta, req);

    bool degraded = false;
    Strings ids, errors;
    {
        std::string out, err;
        if (llm(select_prompt(meta, request_block, blocks), 0, 60, out, err)) {
            Strings decoded;
            if (!decode_select(out, decoded, err)) errors.push_back("seçici: " + err);
            else {
                for (const auto &i : decoded) if (by_id.count(i)) ids.push_back(i);
                if (ids.size() < decoded.size()) notes.push_back("bilinmeyen aday kimliği atlandı");
            }
        } else errors.push_back("seçici: " + err);
    }
    if ((int)ids.size() > req.limit) ids.resize(req.limit);
    if (ids.empty()) {
        degraded = true;
        for (size_t i = 0; i < cids.size() && (int)ids.size() < req.limit; i++) ids.push_back(cids[i]);
        notes.push_back("yedek sıralama kullanıldı (" + (errors.empty() ? std::string("boş seçim") : errors.back()) + ")");
    }

    struct Pick { std::string id; int doc; double conf; };
    std::vector<Pick> picked;
    for (const auto &id : ids) {
        double c = std::round(match_score(cat.books[by_id[id]], r.target) * 100.0) / 100.0;
        picked.push_back({id, by_id[id], c});
    }
    size_t dropped = 0;
    if (r.target.any() && !picked.empty()) {
        std::vector<Pick> kept;
        for (const auto &p : picked) if (p.conf >= cfg.min_confidence) kept.push_back(p);
        if (kept.empty()) {
            kept.push_back(*std::max_element(picked.begin(), picked.end(),
                                             [](const Pick &a, const Pick &b) { return a.conf < b.conf; }));
        }
        dropped = picked.size() - kept.size();
        picked = kept;
    }
    if (dropped) notes.push_back(std::to_string(dropped) + " zayıf eşleşme elendi");

    std::map<std::string, std::string> whys;
    {
        std::vector<std::pair<std::string, std::string>> books;
        for (const auto &p : picked) books.emplace_back(render_candidate(meta, cat.books[p.doc], p.id), match_strength(p.conf));
        std::string out, err;
        if (llm(write_prompt(meta, request_block, books), 1, meta.write_base + meta.write_per_book * (int)books.size(), out, err)) {
            if (!decode_write(out, whys, err)) errors.push_back("yazıcı: " + err);
        } else errors.push_back("yazıcı: " + err);
    }

    Json recs = Json::array();
    std::vector<double> confs;
    for (const auto &p : picked) {
        const Book &b = cat.books[p.doc];
        std::string why;
        auto it = whys.find(p.id);
        if (it != whys.end()) why = it->second;
        if (why.empty()) { why = "Bu kitap isteğindeki ölçütlere uyuyor."; degraded = true; }
        Json rec = Json::object();
        rec.set("rank", Json::integer((long long)recs.a.size() + 1));
        rec.set("book", book_json(b));
        rec.set("why", Json::str(why));
        Strings hooks(b.hooks.begin(), b.hooks.begin() + std::min<size_t>(2, b.hooks.size()));
        rec.set("hooks", Json::str_array(hooks));
        rec.set("content_notes", Json::str_array(b.content_notes));
        rec.set("confidence", Json::number(p.conf));
        rec.set("grounded", Json::boolean(true));
        rec.set("match_reasons", Json::str_array(match_reasons(b, r.target)));
        recs.push(rec);
        confs.push_back(p.conf);
    }
    bool shown_short = (int)recs.a.size() < req.limit;
    Strings followups;
    if (dropped || shown_short) followups.push_back("Filtreleri biraz gevşetmemi ister misin? Uyan kitap az çıktı.");
    else if (!confs.empty() && *std::min_element(confs.begin(), confs.end()) < 0.6)
        followups.push_back("Daha isabetli öneri için tür ya da ruh halini belirtir misin?");
    if (degraded) {
        bool has = false;
        for (const auto &n : notes) if (n.find("yedek") != std::string::npos) has = true;
        if (!has) notes.push_back("gerekçe şablonla yazıldı (yazıcı yanıtı kullanılamadı)");
    }
    resp.set("recommendations", recs);
    resp.set("followups", Json::str_array(followups));
    resp.set("meta", meta_json(r.books.size(), recs.a.empty() ? 0.0 : 1.0, degraded));
    return resp;
}

}  // namespace kc
