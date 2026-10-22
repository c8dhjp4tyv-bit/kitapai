#!/usr/bin/env bash
# PS5 için mbedtls (3.6.7) ve libssh2 (1.11.1, mbedTLS arka ucu) statik kütüphanelerini derler.
# Kaynaklar indirilmiş ve SHA-256 ile doğrulanmış olmalı: <deps>/src/{mbedtls-3.6.7,libssh2-1.11.1}.
# Kullanım: SDK=<ps5-payload-sdk> ./build_deps.sh <deps-dizini>
set -euo pipefail
deps=$(realpath "${1:?deps dizini}")
sdk=${SDK:?SDK=<ps5-payload-sdk dizini>}
export PS5_PAYLOAD_SDK="$sdk" PATH="$sdk/bin:$PATH"
out="$deps/ps5"
mkdir -p "$out"

src="$deps/src/mbedtls-3.6.7"
python3 "$src/scripts/config.py" -f "$src/include/mbedtls/mbedtls_config.h" set MBEDTLS_THREADING_C
python3 "$src/scripts/config.py" -f "$src/include/mbedtls/mbedtls_config.h" set MBEDTLS_THREADING_PTHREAD
prospero-cmake -S "$src" -B "$deps/build-mbedtls-ps5" -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$out" -DENABLE_PROGRAMS=OFF -DENABLE_TESTING=OFF \
    -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON -DMBEDTLS_FATAL_WARNINGS=OFF
cmake --build "$deps/build-mbedtls-ps5"
cmake --install "$deps/build-mbedtls-ps5" > /dev/null
echo "mbedtls tamam: $out"

prospero-cmake -S "$deps/src/libssh2-1.11.1" -B "$deps/build-libssh2-ps5" -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$out" -DCRYPTO_BACKEND=mbedTLS -DCMAKE_PREFIX_PATH="$out" \
    -DMBEDTLS_INCLUDE_DIR="$out/include" -DMBEDTLS_LIBRARY="$out/lib/libmbedtls.a" \
    -DMBEDX509_LIBRARY="$out/lib/libmbedx509.a" -DMBEDCRYPTO_LIBRARY="$out/lib/libmbedcrypto.a" \
    -DBUILD_SHARED_LIBS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_TESTING=OFF -DENABLE_ZLIB_COMPRESSION=OFF
cmake --build "$deps/build-libssh2-ps5"
cmake --install "$deps/build-libssh2-ps5" > /dev/null
echo "libssh2 tamam: $out"
