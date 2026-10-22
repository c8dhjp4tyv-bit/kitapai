// Genel adresin gerçekten ayakta olduğunu dışarıdan sınar (HTTPS GET /health). Tünel sessizce
// düşerse (SSH bağlantısı açık görünür ama sunucu "no tunnel" döner) bekçi yeniden bağlanmayı tetikler.
// mbedTLS istemcisi; doğrulama yok: yalnızca canlılık sınaması, gizli veri göndermez.
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <mbedtls/ctr_drbg.h>
#include <mbedtls/entropy.h>
#include <mbedtls/net_sockets.h>
#include <mbedtls/ssl.h>
#include <psa/crypto.h>

#include <string>

namespace tun {

// https://ad.lhr.life adresindeki /health "status":"ok" dönüyor mu? Neden başarısızsa `why` dolar.
inline bool probe_public(const std::string &url, std::string &why) {
    static const std::string prefix = "https://";
    if (url.compare(0, prefix.size(), prefix) != 0) { why = "adres https ile başlamıyor"; return false; }
    std::string host = url.substr(prefix.size());
    size_t slash = host.find('/');
    if (slash != std::string::npos) host.resize(slash);

    static bool psa_ready = (psa_crypto_init() == PSA_SUCCESS);
    if (!psa_ready) { why = "psa_crypto_init başarısız"; return false; }

    mbedtls_net_context net;
    mbedtls_ssl_context ssl;
    mbedtls_ssl_config conf;
    mbedtls_entropy_context entropy;
    mbedtls_ctr_drbg_context drbg;
    mbedtls_net_init(&net); mbedtls_ssl_init(&ssl); mbedtls_ssl_config_init(&conf);
    mbedtls_entropy_init(&entropy); mbedtls_ctr_drbg_init(&drbg);
    bool ok = false;
    int rc;
    auto fail = [&](const char *step, int code) { why = std::string(step) + " hata " + std::to_string(code); };

    do {
        if ((rc = mbedtls_ctr_drbg_seed(&drbg, mbedtls_entropy_func, &entropy, (const unsigned char *)"kitapai", 7))) { fail("rng", rc); break; }
        if ((rc = mbedtls_net_connect(&net, host.c_str(), "443", MBEDTLS_NET_PROTO_TCP))) { fail("bağlantı", rc); break; }
        if ((rc = mbedtls_ssl_config_defaults(&conf, MBEDTLS_SSL_IS_CLIENT, MBEDTLS_SSL_TRANSPORT_STREAM, MBEDTLS_SSL_PRESET_DEFAULT))) { fail("ssl ayar", rc); break; }
        mbedtls_ssl_conf_authmode(&conf, MBEDTLS_SSL_VERIFY_NONE);
        mbedtls_ssl_conf_rng(&conf, mbedtls_ctr_drbg_random, &drbg);
        mbedtls_ssl_conf_read_timeout(&conf, 10000);
        if ((rc = mbedtls_ssl_setup(&ssl, &conf))) { fail("ssl kurulum", rc); break; }
        if ((rc = mbedtls_ssl_set_hostname(&ssl, host.c_str()))) { fail("sni", rc); break; }
        mbedtls_ssl_set_bio(&ssl, &net, mbedtls_net_send, mbedtls_net_recv, mbedtls_net_recv_timeout);
        while ((rc = mbedtls_ssl_handshake(&ssl)) != 0) {
            if (rc != MBEDTLS_ERR_SSL_WANT_READ && rc != MBEDTLS_ERR_SSL_WANT_WRITE) { fail("tls el sıkışma", rc); goto done; }
        }
        {
            std::string req = "GET /health HTTP/1.1\r\nHost: " + host + "\r\nConnection: close\r\nUser-Agent: kitapai-probe\r\n\r\n";
            size_t off = 0;
            while (off < req.size()) {
                rc = mbedtls_ssl_write(&ssl, (const unsigned char *)req.data() + off, req.size() - off);
                if (rc == MBEDTLS_ERR_SSL_WANT_READ || rc == MBEDTLS_ERR_SSL_WANT_WRITE) continue;
                if (rc < 0) { fail("yazma", rc); goto done; }
                off += (size_t)rc;
            }
            std::string resp;
            unsigned char buf[2048];
            while (resp.size() < 8192) {
                rc = mbedtls_ssl_read(&ssl, buf, sizeof buf);
                if (rc == MBEDTLS_ERR_SSL_WANT_READ || rc == MBEDTLS_ERR_SSL_WANT_WRITE) continue;
                if (rc <= 0) break;   // kapanış ya da zaman aşımı
                resp.append((char *)buf, (size_t)rc);
            }
            if (resp.compare(0, 12, "HTTP/1.1 200") == 0 && resp.find("\"status\":\"ok\"") != std::string::npos) ok = true;
            else why = "beklenmeyen yanıt: " + resp.substr(0, resp.find("\r\n"));
        }
    } while (false);
done:
    mbedtls_ssl_free(&ssl); mbedtls_ssl_config_free(&conf);
    mbedtls_ctr_drbg_free(&drbg); mbedtls_entropy_free(&entropy); mbedtls_net_free(&net);
    return ok;
}

}  // namespace tun
