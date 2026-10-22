// Küçük bir JSON değeri, ayrıştırıcı ve yazıcı. Nesne anahtar sırası korunur.
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace kj {

struct Json {
    enum Type { Null, Bool, Num, Str, Arr, Obj } type = Null;
    bool b = false;
    double n = 0;
    bool is_int = false;
    std::string s;
    std::vector<Json> a;
    std::vector<std::pair<std::string, Json>> o;

    Json() = default;
    static Json boolean(bool v) { Json j; j.type = Bool; j.b = v; return j; }
    static Json number(double v) { Json j; j.type = Num; j.n = v; return j; }
    static Json integer(long long v) { Json j; j.type = Num; j.n = (double)v; j.is_int = true; return j; }
    static Json str(std::string v) { Json j; j.type = Str; j.s = std::move(v); return j; }
    static Json array() { Json j; j.type = Arr; return j; }
    static Json object() { Json j; j.type = Obj; return j; }
    static Json str_array(const std::vector<std::string> &v) {
        Json j = array();
        for (const auto &x : v) j.a.push_back(str(x));
        return j;
    }

    bool is_obj() const { return type == Obj; }
    bool is_arr() const { return type == Arr; }
    bool is_str() const { return type == Str; }
    bool is_num() const { return type == Num; }

    Json &set(const std::string &k, Json v) {
        for (auto &kv : o)
            if (kv.first == k) { kv.second = std::move(v); return *this; }
        o.emplace_back(k, std::move(v));
        return *this;
    }
    Json &push(Json v) { a.push_back(std::move(v)); return *this; }

    const Json *get(const std::string &k) const {
        if (type != Obj) return nullptr;
        for (const auto &kv : o)
            if (kv.first == k) return &kv.second;
        return nullptr;
    }
    std::string str_or(const std::string &k, const std::string &def = "") const {
        const Json *v = get(k);
        return v && v->type == Str ? v->s : def;
    }
    double num_or(const std::string &k, double def) const {
        const Json *v = get(k);
        return v && v->type == Num ? v->n : def;
    }
    std::vector<std::string> strings(const std::string &k) const {
        std::vector<std::string> out;
        const Json *v = get(k);
        if (v && v->type == Arr)
            for (const auto &x : v->a)
                if (x.type == Str) out.push_back(x.s);
        return out;
    }
};

// ── yazıcı ──────────────────────────────────────────────────────────────────

inline void dump_string(const std::string &s, std::string &out) {
    out += '"';
    for (unsigned char c : s) {
        switch (c) {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (c < 0x20) {
                char buf[8];
                snprintf(buf, sizeof buf, "\\u%04x", c);
                out += buf;
            } else {
                out += (char)c;
            }
        }
    }
    out += '"';
}

inline void dump(const Json &j, std::string &out) {
    switch (j.type) {
    case Json::Null: out += "null"; break;
    case Json::Bool: out += j.b ? "true" : "false"; break;
    case Json::Num: {
        char buf[48];
        if (j.is_int || (std::floor(j.n) == j.n && std::fabs(j.n) < 1e15))
            snprintf(buf, sizeof buf, "%lld", (long long)j.n);
        else
            snprintf(buf, sizeof buf, "%.10g", j.n);
        out += buf;
        break;
    }
    case Json::Str: dump_string(j.s, out); break;
    case Json::Arr:
        out += '[';
        for (size_t i = 0; i < j.a.size(); i++) {
            if (i) out += ',';
            dump(j.a[i], out);
        }
        out += ']';
        break;
    case Json::Obj:
        out += '{';
        for (size_t i = 0; i < j.o.size(); i++) {
            if (i) out += ',';
            dump_string(j.o[i].first, out);
            out += ':';
            dump(j.o[i].second, out);
        }
        out += '}';
        break;
    }
}

inline std::string dump(const Json &j) {
    std::string s;
    dump(j, s);
    return s;
}

// ── ayrıştırıcı ─────────────────────────────────────────────────────────────

class Parser {
public:
    explicit Parser(const std::string &t) : t_(t) {}

    std::optional<Json> parse() {
        skip();
        auto v = value(0);
        if (!v) return std::nullopt;
        skip();
        if (p_ != t_.size()) return std::nullopt;
        return v;
    }

private:
    const std::string &t_;
    size_t p_ = 0;

    void skip() {
        while (p_ < t_.size() && (t_[p_] == ' ' || t_[p_] == '\t' || t_[p_] == '\n' || t_[p_] == '\r')) p_++;
    }
    bool lit(const char *w) {
        size_t n = strlen(w);
        if (t_.compare(p_, n, w) == 0) { p_ += n; return true; }
        return false;
    }
    static void put_utf8(unsigned cp, std::string &out) {
        if (cp < 0x80) out += (char)cp;
        else if (cp < 0x800) { out += (char)(0xC0 | (cp >> 6)); out += (char)(0x80 | (cp & 0x3F)); }
        else if (cp < 0x10000) {
            out += (char)(0xE0 | (cp >> 12)); out += (char)(0x80 | ((cp >> 6) & 0x3F));
            out += (char)(0x80 | (cp & 0x3F));
        } else {
            out += (char)(0xF0 | (cp >> 18)); out += (char)(0x80 | ((cp >> 12) & 0x3F));
            out += (char)(0x80 | ((cp >> 6) & 0x3F)); out += (char)(0x80 | (cp & 0x3F));
        }
    }
    bool hex4(unsigned &v) {
        if (p_ + 4 > t_.size()) return false;
        v = 0;
        for (int i = 0; i < 4; i++) {
            char c = t_[p_++];
            v <<= 4;
            if (c >= '0' && c <= '9') v |= c - '0';
            else if (c >= 'a' && c <= 'f') v |= c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') v |= c - 'A' + 10;
            else return false;
        }
        return true;
    }
    std::optional<std::string> string_() {
        if (p_ >= t_.size() || t_[p_] != '"') return std::nullopt;
        p_++;
        std::string out;
        while (p_ < t_.size()) {
            unsigned char c = t_[p_++];
            if (c == '"') return out;
            if (c < 0x20) return std::nullopt;
            if (c != '\\') { out += (char)c; continue; }
            if (p_ >= t_.size()) return std::nullopt;
            char e = t_[p_++];
            switch (e) {
            case '"': out += '"'; break;
            case '\\': out += '\\'; break;
            case '/': out += '/'; break;
            case 'b': out += '\b'; break;
            case 'f': out += '\f'; break;
            case 'n': out += '\n'; break;
            case 'r': out += '\r'; break;
            case 't': out += '\t'; break;
            case 'u': {
                unsigned cp;
                if (!hex4(cp)) return std::nullopt;
                if (cp >= 0xD800 && cp < 0xDC00 && t_.compare(p_, 2, "\\u") == 0) {
                    p_ += 2;
                    unsigned lo;
                    if (!hex4(lo)) return std::nullopt;
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                }
                put_utf8(cp, out);
                break;
            }
            default: return std::nullopt;
            }
        }
        return std::nullopt;
    }
    std::optional<Json> value(int depth) {
        if (depth > 64 || p_ >= t_.size()) return std::nullopt;
        char c = t_[p_];
        if (c == '{') {
            p_++;
            Json j = Json::object();
            skip();
            if (p_ < t_.size() && t_[p_] == '}') { p_++; return j; }
            while (true) {
                skip();
                auto k = string_();
                if (!k) return std::nullopt;
                skip();
                if (p_ >= t_.size() || t_[p_++] != ':') return std::nullopt;
                skip();
                auto v = value(depth + 1);
                if (!v) return std::nullopt;
                j.o.emplace_back(*k, std::move(*v));
                skip();
                if (p_ >= t_.size()) return std::nullopt;
                if (t_[p_] == ',') { p_++; continue; }
                if (t_[p_] == '}') { p_++; return j; }
                return std::nullopt;
            }
        }
        if (c == '[') {
            p_++;
            Json j = Json::array();
            skip();
            if (p_ < t_.size() && t_[p_] == ']') { p_++; return j; }
            while (true) {
                skip();
                auto v = value(depth + 1);
                if (!v) return std::nullopt;
                j.a.push_back(std::move(*v));
                skip();
                if (p_ >= t_.size()) return std::nullopt;
                if (t_[p_] == ',') { p_++; continue; }
                if (t_[p_] == ']') { p_++; return j; }
                return std::nullopt;
            }
        }
        if (c == '"') {
            auto s = string_();
            if (!s) return std::nullopt;
            return Json::str(std::move(*s));
        }
        if (lit("true")) return Json::boolean(true);
        if (lit("false")) return Json::boolean(false);
        if (lit("null")) return Json();
        // sayı
        size_t st = p_;
        if (p_ < t_.size() && (t_[p_] == '-' || t_[p_] == '+')) p_++;
        bool digits = false, frac = false;
        while (p_ < t_.size() && ((t_[p_] >= '0' && t_[p_] <= '9') || t_[p_] == '.' || t_[p_] == 'e' ||
                                  t_[p_] == 'E' || t_[p_] == '-' || t_[p_] == '+')) {
            if (t_[p_] >= '0' && t_[p_] <= '9') digits = true;
            if (t_[p_] == '.' || t_[p_] == 'e' || t_[p_] == 'E') frac = true;
            p_++;
        }
        if (!digits) return std::nullopt;
        std::string tok = t_.substr(st, p_ - st);
        Json j = Json::number(strtod(tok.c_str(), nullptr));
        j.is_int = !frac;
        return j;
    }
};

inline std::optional<Json> parse(const std::string &text) { return Parser(text).parse(); }

}  // namespace kj
