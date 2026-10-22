// Yerel deneme aracı: sorguları çalıştırıp ilk sonuçları yazdırır.  ./query_cli <bundle> "sorgu" ...
#include <fstream>
#include <iostream>
#include <sstream>
#include "core.hpp"
static std::string slurp(const std::string &p) { std::ifstream f(p, std::ios::binary); std::stringstream ss; ss << f.rdbuf(); return ss.str(); }
int main(int argc, char **argv) {
    std::string err; kc::Meta meta; kc::Catalog cat;
    if (!kc::load_meta(slurp(std::string(argv[1]) + "/meta.json"), meta, err) || !cat.load(slurp(std::string(argv[1]) + "/books.tsv"), meta, err)) { puts(err.c_str()); return 1; }
    kc::Retriever r(cat, meta);
    for (int i = 2; i < argc; i++) {
        kc::Request req; req.query = argv[i];
        kc::Retrieval res = r.retrieve(req, 40);
        printf("\n== %s\n   terimler: %s | tür: %s | ruh: %s%s\n", argv[i], kc::join(res.exp.terms, ", ").c_str(), kc::join(res.target.genres, ",").c_str(), kc::join(res.target.moods, ",").c_str(), res.used_browse ? " | GEZİNME" : "");
        for (size_t k = 0; k < res.books.size() && k < 6; k++) { const kc::Book &b = cat.books[res.books[k]]; printf("   %zu. %s — %s (%d) [%s] %.2f\n", k + 1, b.title.c_str(), kc::join(b.authors, ", ").c_str(), b.year, kc::join(b.genres, ",").c_str(), kc::match_score(b, res.target)); }
    }
}
