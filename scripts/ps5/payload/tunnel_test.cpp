// Tüneli tek başına dener: ./tunnel_test <yerel_port> [host]. Adresi ekrana yazar.
#include <cstdio>
#include <cstdlib>
#include "tunnel.hpp"
int main(int argc, char **argv) {
    tun::Config cfg;
    cfg.local_port = argc > 1 ? atoi(argv[1]) : 8800;
    if (argc > 2) cfg.host = argv[2];
    std::atomic<bool> stop{false};
    tun::run_forever(cfg, [](const std::string &s) { fprintf(stderr, "%s\n", s.c_str()); },
                     [](const std::string &u) { printf("ADRES %s\n", u.c_str()); fflush(stdout); }, stop);
}
