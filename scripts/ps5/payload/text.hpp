// UTF-8, küçük harfe indirgeme, harf sadeleştirme, Porter kökleyici ve durak sözcükler.
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <cstdint>
#include <cstring>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace kt {

using U32 = std::u32string;

inline U32 decode(const std::string &s) {
    U32 out;
    out.reserve(s.size());
    for (size_t i = 0; i < s.size();) {
        unsigned char c = s[i];
        char32_t cp;
        int n;
        if (c < 0x80) { cp = c; n = 1; }
        else if ((c >> 5) == 6 && i + 1 < s.size()) { cp = ((c & 0x1F) << 6) | (s[i + 1] & 0x3F); n = 2; }
        else if ((c >> 4) == 14 && i + 2 < s.size()) {
            cp = ((c & 0x0F) << 12) | ((s[i + 1] & 0x3F) << 6) | (s[i + 2] & 0x3F); n = 3;
        } else if ((c >> 3) == 30 && i + 3 < s.size()) {
            cp = ((c & 0x07) << 18) | ((s[i + 1] & 0x3F) << 12) | ((s[i + 2] & 0x3F) << 6) | (s[i + 3] & 0x3F);
            n = 4;
        } else { cp = 0xFFFD; n = 1; }
        out += cp;
        i += n;
    }
    return out;
}

inline void append(std::string &out, char32_t cp) {
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

inline std::string encode(const U32 &u) {
    std::string out;
    out.reserve(u.size());
    for (char32_t cp : u) append(out, cp);
    return out;
}

inline size_t length(const std::string &s) { return decode(s).size(); }

// Python'daki s[:n] gibi: ilk n KOD NOKTASI.
inline std::string prefix(const std::string &s, size_t n) {
    U32 u = decode(s);
    if (u.size() <= n) return s;
    u.resize(n);
    return encode(u);
}

inline bool is_space(char32_t c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == 0xA0 || c == 0x0B || c == 0x0C; }

// Python `str.lower()` (Türkçe dâhil: İ → i + U+0307, I → i).
inline void lower_cp(char32_t c, U32 &out) {
    if (c < 0x80) { out += (c >= 'A' && c <= 'Z') ? c + 32 : c; return; }
    if (c == 0x130) { out += U'i'; out += (char32_t)0x307; return; }
    if (c >= 0xC0 && c <= 0xDE && c != 0xD7) { out += c + 32; return; }
    if (c >= 0x100 && c <= 0x17F) {
        if (c == 0x131 || c == 0x138 || c == 0x149 || c == 0x17F) { out += c; return; }
        bool even_upper = (c <= 0x137) || (c >= 0x14A && c <= 0x177);
        bool odd_upper = (c >= 0x139 && c <= 0x148) || (c >= 0x179 && c <= 0x17E);
        if (even_upper && c % 2 == 0) { out += c + 1; return; }
        if (odd_upper && c % 2 == 1) { out += c + 1; return; }
        out += c;
        return;
    }
    if (c >= 0x391 && c <= 0x3A9) { out += c + 32; return; }
    if (c >= 0x410 && c <= 0x42F) { out += c + 32; return; }
    if (c >= 0x400 && c <= 0x40F) { out += c + 80; return; }
    out += c;
}

inline std::string lower(const std::string &s) {
    U32 in = decode(s), out;
    out.reserve(in.size());
    for (char32_t c : in) lower_cp(c, out);
    return encode(out);
}

// Beklenen `_fold`: küçük harf + âîû → aiu.
inline std::string fold(const std::string &s) {
    U32 in = decode(lower(s)), out;
    for (char32_t c : in) {
        if (c == 0xE2) out += U'a';
        else if (c == 0xEE) out += U'i';
        else if (c == 0xFB) out += U'u';
        else out += c;
    }
    return encode(out);
}

// Python `\w`: harf, rakam ve alt çizgi (yaklaşık Unicode kapsamı).
inline bool is_word(char32_t c) {
    if (c < 0x80) return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_';
    if (c < 0xC0) return c == 0xAA || c == 0xB5 || c == 0xBA;
    if (c == 0xD7 || c == 0xF7) return false;
    if (c >= 0x300 && c <= 0x36F) return false;      // birleşik işaretler (\w değil)
    if (c >= 0x2000 && c <= 0x2BFF) return false;   // noktalama ve simgeler
    if (c >= 0x3000 && c <= 0x303F) return false;
    return true;
}

// Metni boşluklara göre böler (Python `str.split()`).
inline std::vector<std::string> split_ws(const std::string &s) {
    std::vector<std::string> out;
    U32 u = decode(s), cur;
    for (char32_t c : u) {
        if (is_space(c)) {
            if (!cur.empty()) { out.push_back(encode(cur)); cur.clear(); }
        } else cur += c;
    }
    if (!cur.empty()) out.push_back(encode(cur));
    return out;
}

// `re.findall(r"[\w'’]+", text)`
inline std::vector<std::string> word_tokens(const std::string &s) {
    std::vector<std::string> out;
    U32 u = decode(s), cur;
    for (char32_t c : u) {
        if (is_word(c) || c == '\'' || c == 0x2019) cur += c;
        else if (!cur.empty()) { out.push_back(encode(cur)); cur.clear(); }
    }
    if (!cur.empty()) out.push_back(encode(cur));
    return out;
}

// ── BM25 için sadeleştirme: küçük harf, aksan at, yalnızca a-z ──────────────────

class Folder {
public:
    void load(const std::unordered_map<int, std::string> &table) { table_ = table; }

    // Aksanlı harfleri sadeleştirip a-z dışındakilerle bölünen sözcükler döndürür.
    std::vector<std::string> tokens(const std::string &text) const {
        std::vector<std::string> out;
        std::string cur;
        U32 u = decode(text);
        for (char32_t c : u) {
            U32 low;
            lower_cp(c, low);
            for (char32_t lc : low) {
                const std::string *base = nullptr;
                char ascii = 0;
                if (lc >= 'a' && lc <= 'z') ascii = (char)lc;
                else if (lc >= 0xC0 && lc < 0x250) {
                    auto it = table_.find((int)lc);
                    if (it != table_.end()) base = &it->second;
                    // Büyük harfin küçüğü de tabloda olmayabilir; sadeleştirilmiş küçük harf tablodadır.
                }
                if (ascii) cur += ascii;
                else if (base) cur += *base;
                else if (lc == 0x307) continue;          // birleşik nokta (İ → i̇)
                else if (!cur.empty()) { out.push_back(cur); cur.clear(); }
            }
        }
        if (!cur.empty()) out.push_back(cur);
        return out;
    }

private:
    std::unordered_map<int, std::string> table_;
};

// ── Porter kökleyici (klasik algoritma) ─────────────────────────────────────

class Porter {
public:
    std::string stem(const std::string &word) {
        if (word.size() <= 2) return word;
        b_ = word;
        k_ = (int)b_.size() - 1;
        j_ = 0;
        step1ab();
        if (k_ > 0) {
            step1c(); step2(); step3(); step4(); step5();
        }
        return b_.substr(0, k_ + 1);
    }

private:
    std::string b_;
    int k_ = 0, j_ = 0;

    bool cons(int i) {
        switch (b_[i]) {
        case 'a': case 'e': case 'i': case 'o': case 'u': return false;
        case 'y': return i == 0 ? true : !cons(i - 1);
        default: return true;
        }
    }
    int m() {
        int n = 0, i = 0;
        while (true) { if (i > j_) return n; if (!cons(i)) break; i++; }
        i++;
        while (true) {
            while (true) { if (i > j_) return n; if (cons(i)) break; i++; }
            i++; n++;
            while (true) { if (i > j_) return n; if (!cons(i)) break; i++; }
            i++;
        }
    }
    bool vowel_in_stem() { for (int i = 0; i <= j_; i++) if (!cons(i)) return true; return false; }
    bool doublec(int j) { return j >= 1 && b_[j] == b_[j - 1] && cons(j); }
    bool cvc(int i) {
        if (i < 2 || !cons(i) || cons(i - 1) || !cons(i - 2)) return false;
        char ch = b_[i];
        return !(ch == 'w' || ch == 'x' || ch == 'y');
    }
    bool ends(const char *s) {
        int l = (int)strlen(s);
        if (l > k_ + 1) return false;
        if (b_.compare(k_ - l + 1, l, s) != 0) return false;
        j_ = k_ - l;
        return true;
    }
    void setto(const char *s) {
        int l = (int)strlen(s);
        b_ = b_.substr(0, j_ + 1) + s;
        k_ = j_ + l;
    }
    void r(const char *s) { if (m() > 0) setto(s); }

    void step1ab() {
        if (b_[k_] == 's') {
            if (ends("sses")) k_ -= 2;
            else if (ends("ies")) setto("i");
            else if (k_ >= 1 && b_[k_ - 1] != 's') k_--;
        }
        if (ends("eed")) { if (m() > 0) k_--; }
        else if ((ends("ed") || ends("ing")) && vowel_in_stem()) {
            k_ = j_;
            b_.resize(k_ + 1);
            if (ends("at")) setto("ate");
            else if (ends("bl")) setto("ble");
            else if (ends("iz")) setto("ize");
            else if (doublec(k_)) {
                k_--;
                char ch = b_[k_];
                if (ch == 'l' || ch == 's' || ch == 'z') k_++;
            } else if (m() == 1 && cvc(k_)) setto("e");
        }
        b_.resize(k_ + 1);
    }
    void step1c() {
        if (ends("y") && vowel_in_stem()) b_[k_] = 'i';
    }
    void step2() {
        if (k_ < 1) return;
        switch (b_[k_ - 1]) {
        case 'a': if (ends("ational")) { r("ate"); break; } if (ends("tional")) { r("tion"); break; } break;
        case 'c': if (ends("enci")) { r("ence"); break; } if (ends("anci")) { r("ance"); break; } break;
        case 'e': if (ends("izer")) { r("ize"); break; } break;
        case 'l': if (ends("bli")) { r("ble"); break; } if (ends("alli")) { r("al"); break; }
                  if (ends("entli")) { r("ent"); break; } if (ends("eli")) { r("e"); break; }
                  if (ends("ousli")) { r("ous"); break; } break;
        case 'o': if (ends("ization")) { r("ize"); break; } if (ends("ation")) { r("ate"); break; }
                  if (ends("ator")) { r("ate"); break; } break;
        case 's': if (ends("alism")) { r("al"); break; } if (ends("iveness")) { r("ive"); break; }
                  if (ends("fulness")) { r("ful"); break; } if (ends("ousness")) { r("ous"); break; } break;
        case 't': if (ends("aliti")) { r("al"); break; } if (ends("iviti")) { r("ive"); break; }
                  if (ends("biliti")) { r("ble"); break; } break;
        }
        b_.resize(k_ + 1);
    }
    void step3() {
        switch (b_[k_]) {
        case 'e': if (ends("icate")) { r("ic"); break; } if (ends("ative")) { r(""); break; }
                  if (ends("alize")) { r("al"); break; } break;
        case 'i': if (ends("iciti")) { r("ic"); break; } break;
        case 'l': if (ends("ical")) { r("ic"); break; } if (ends("ful")) { r(""); break; } break;
        case 's': if (ends("ness")) { r(""); break; } break;
        }
        b_.resize(k_ + 1);
    }
    void step4() {
        if (k_ < 1) return;
        bool hit = false;
        switch (b_[k_ - 1]) {
        case 'a': hit = ends("al"); break;
        case 'c': hit = ends("ance") || ends("ence"); break;
        case 'e': hit = ends("er"); break;
        case 'i': hit = ends("ic"); break;
        case 'l': hit = ends("able") || ends("ible"); break;
        case 'n': hit = ends("ant") || ends("ement") || ends("ment") || ends("ent"); break;
        case 'o': hit = (ends("ion") && j_ >= 0 && (b_[j_] == 's' || b_[j_] == 't')) || ends("ou"); break;
        case 's': hit = ends("ism"); break;
        case 't': hit = ends("ate") || ends("iti"); break;
        case 'u': hit = ends("ous"); break;
        case 'v': hit = ends("ive"); break;
        case 'z': hit = ends("ize"); break;
        }
        if (hit && m() > 1) k_ = j_;
        b_.resize(k_ + 1);
    }
    void step5() {
        j_ = k_;
        if (b_[k_] == 'e') {
            int a = m();
            if (a > 1 || (a == 1 && !cvc(k_ - 1))) k_--;
        }
        if (b_[k_] == 'l' && doublec(k_) && m() > 1) k_--;
        b_.resize(k_ + 1);
    }
};

inline const std::unordered_set<std::string> &english_stopwords() {
    static const std::unordered_set<std::string> s = {
        "a","about","above","after","again","against","all","am","an","and","any","are","as","at","be","because",
        "been","before","being","below","between","both","but","by","can","did","do","does","doing","down","during",
        "each","few","for","from","further","had","has","have","having","he","her","here","hers","herself","him",
        "himself","his","how","i","if","in","into","is","it","its","itself","just","me","more","most","my","myself",
        "no","nor","not","now","of","off","on","once","only","or","other","our","ours","ourselves","out","over","own",
        "same","she","should","so","some","such","than","that","the","their","theirs","them","themselves","then",
        "there","these","they","this","those","through","to","too","under","until","up","very","was","we","were",
        "what","when","where","which","while","who","whom","why","will","with","you","your","yours","yourself",
        "yourselves","would","could","also","s","t","d","ll","m","o","re","ve","y"};
    return s;
}

}  // namespace kt
