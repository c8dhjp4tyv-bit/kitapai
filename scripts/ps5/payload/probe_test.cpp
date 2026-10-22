// Bekçi sınamasını dener: ./probe_test https://adres.lhr.life
#include <cstdio>
#include "probe.hpp"
int main(int argc, char **argv) {
    std::string why;
    bool ok = tun::probe_public(argc > 1 ? argv[1] : "https://yok.lhr.life", why);
    printf("%s %s\n", ok ? "CANLI" : "DÜŞMÜŞ", why.c_str());
    return ok ? 0 : 1;
}
