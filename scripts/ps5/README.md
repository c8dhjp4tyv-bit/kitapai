# PS5'te çalıştırma (sunum sürümü)

Jailbreak'li bir PS5'te her şey konsolun içinde çalışır: model, arama, site, davet kodu denetimi ve internet
tüneli. Başka bir bilgisayar gerekmez.

```
 tarayıcı ──HTTPS──▶ serveo (röle) ◀──SSH ters tüneli── kitapai-server.elf (payload, :8800)
                                                         ├─ statik site (web/) + davet kapısı
                                                         ├─ /api/*: C++ BM25 arama, istemler, çözücüler
                                                         └─ 127.0.0.1:8081 ─▶ PS5LM llama-server
                                                              tek taban Q8 + seçici/yazıcı LoRA
```

Ön koşullar: PS5 firmware'i PS5LM'in desteklediği aralıkta (7.00–13.60), jailbreak'li, etaHEN ve
[PS5LM](https://github.com/cobanov/PS5LM) kurulu, FTP erişimi (bu kurulumda port 1337). PS5'te `elfldr`
(9021) ve telnet yoktu; payload'lar etaHEN'in payload menüsünden başlatılır
(`/data/etaHEN/payloads/` klasörüne konan ELF'ler).

## 1. Model: tek taban + iki LoRA

PS5LM aynı anda tek model yükler ve model değiştirmek uygulamayı yeniden başlatır; bu yüzden seçici ve
yazıcı iki ayrı model yerine **tek tabanın iki LoRA'sı** olarak yüklenir ve her istek `lora` alanıyla
hangisinin açık olacağını seçer.

1. **Taban**: LoRA'sız, eğitimde kullanılan 4-bit tabanın *açılmış* hâli. LoRA'lar bu tabana göre öğrendi;
   gerçek fp16 tabana uygulanınca çıktı bozuluyordu.
   `python dequant_base.py models/kitapai-select base-deq-fp16` →
   `convert_hf_to_gguf.py base-deq-fp16 --outtype q8_0` (llama.cpp'nin dönüştürücüleri)
2. **LoRA'lar**: `convert_lora_to_gguf.py --base base-deq-fp16 models/kitapai-select` (ve `-write`).
   rsLoRA ölçeği llama.cpp'de `alpha/r = 1` olarak uygulanır; gerçeği `√r` (5,657). PS5LM v0.8.x JSON'daki
   her ondalık sayıda çöktüğü için ölçeği dosyaya gömün:
   `gguf_set_metadata.py lora-*.gguf adapter.lora.alpha 181.01933598375618 --force`. İstekte ölçek `1`
   ya da `0` olur.
3. **Konsola** (FTP): `/data/PS5LM/kitapai/` altına taban + iki LoRA; `app-args.txt`'yi
   `/data/PS5LM/app-args.txt` olarak koyun (örnek: bu klasörde). Bu dosya varken uygulama her açılışta onu
   yükler; silince eski davranış döner. `--lora-init-without-apply` LoRA'ları kapalı yükler, `--temp 0.3`
   yazıcının sıcaklığıdır (istekte ondalık sayı gönderilemediği için sunucu bayrağıyla verilir),
   `--log-disable` v0.8.3'teki log kuyruğu donmasını önler (v0.9.1+ ile gerekmez).

Ölçülen (200 örnek): PS5'te seçici hakem puanı PC ile aynı (normalize 0,888); seçici ~2 sn, yazıcı ~3 sn.

## 2. Veri paketi (PC'de, bir kez)

PS5'te Python/DuckDB yoktur; payload yalnızca algoritmayı taşır, veri hazır gelir:

```bash
python scripts/ps5/export_bundle.py bundle    # books.tsv (88 bin kitap, ~56 MB) + meta.json
```

`meta.json` istem metinlerini, taksonomiyi, sorgu genişletme tablolarını ve etiket sözlüklerini içerir; C++
yalnızca algoritmayı taşır. Kitap başına içerik uyarıları ve çengeller önceden hesaplanır.

## 3. Payload (C++)

`payload/` dosyaları: `server.cpp` (HTTP, API, davet kodları, llama istemcisi), `core.hpp` (katalog, BM25,
sorgu genişletme, uyum puanı, istemler, çözücüler, boru hattı), `text.hpp` (UTF-8, Porter kökleyici),
`json.hpp`, `tunnel.hpp` (SSH ters tüneli), `probe.hpp` (bekçi).

```bash
# bağımlılıklar: PS5 payload SDK (v0.42) kurulu olmalı
SDK=<ps5-payload-sdk> payload/build_deps.sh <deps-dizini>   # mbedtls 3.6.7 + libssh2 1.11.1 (SHA-256 doğrulanmış kaynaklar)
cd payload && PATH=$SDK/bin:$PATH PS5_PAYLOAD_SDK=$SDK \
  $SDK/bin/prospero-clang++ -O2 -std=c++17 -pthread server.cpp \
  -I<deps>/ps5/include -L<deps>/ps5/lib -lssh2 -lmbedtls -lmbedx509 -lmbedcrypto -o kitapai-server.elf
```

Aynı kod `g++` ile PC'de de derlenir (yerel deneme ve testler). Konsola yükleme: `books.tsv`, `meta.json`,
`codes.txt`, `web/` (web istemcisinin `npm run build` çıktısı, `.map` dosyaları hariç) →
`/data/PS5LM/kitapai/`; `kitapai-server.elf` → `/data/etaHEN/payloads/`, sonra etaHEN menüsünden başlat.
Eski bir kopya portu tutuyorsa yeni sürüm `8801–8809` arasında ilk boş porta bağlanır (`port.txt`).

Testler: `payload/test_core.cpp` C++ çekirdeğini Python'un ürettiği değerlerle karşılaştırır (sorgu
genişletme, istem biçimi, uyum puanı, çözücüler: 2249 kontrol).

## 4. Davet kodları

```bash
python scripts/ps5/make_codes.py codes.txt --count 10 --hours 72 --label "grup"
```

Kodlar 24 hanedir (31 simgelik karışmayan alfabe, `secrets` ile ≈120 bit), `codes.txt` içinde `KOD
bitiş_epoch etiket` olarak durur ve PS5'e yüklenir; dosya değişince payload yeniden okur. Doğrulama
**sunucuda** yapılır (`X-API-Key` başlığı, her istekte; bitiş zamanı PS5'in saatine göre). Hatalı denemeler
genel olarak sınırlıdır (dakikada 30). Kodlar depoya girmez (`.gitignore`).

## 5. İnternete açma (CGNAT arkasında, PS5'in kendisinden)

Payload kendi SSH ters tünelini kurar (`tunnel.hpp`, libssh2): bir röle servisine bağlanır, `80` portunu
PS5'teki siteye yönlendirir, açılış metninden genel adresi okur ve `public_url.txt`'ye ve `/health`
yanıtına (`public_url`) yazar. Varsayılan `nokey@localhost.run` (anonim, **adres her başlatmada değişir**).

**Sabit adres için serveo**: `tunnel.conf.example` dosyasını `/data/PS5LM/kitapai/tunnel.conf` olarak koyun.
Kalıcı alt alan adı için bir RSA anahtarı üretip (`ssh-keygen -t rsa -b 3072 -m PEM`) serveo hesabınıza
tarayıcıda kaydetmeniz gerekir (`https://console.serveo.net/ssh/keys?add=SHA256%3A…`; Google/GitHub girişi).
Özel anahtar PS5'te `key=` ile gösterilen yola konur ve **depoya girmez**.

- **Bekçi** (`probe.hpp`): 45 sn'de bir genel adrese HTTPS ile `/health` isteği atılır; üst üste iki
  başarısızlıkta (ilk 3 dakikada dört) tünel yeniden kurulur. Soket/protokol hataları da oturumu bitirir.
- **Yanıt akıtma**: Serveo gibi aracılar yanıt başlığını ~5 sn içinde bekler; öneri 4–6 sn sürdüğünden
  `/api/recommend` 1,5 sn'den uzun sürerse başlığı hemen gönderip gövdeyi parça parça yazar. Hata durum
  kodları (401, 422, 503) işten önce döndüğü için korunur.
- `tunnel.off` dosyası ya da `KITAPAI_TUNNEL=0` tüneli kapatır.
- libssh2/mbedtls ile uyumluluk notları: sunucu `shell` isteğine yanıt vermez (3 sn zaman aşımı normaldir),
  PTY istenmemeli, stderr akışı birleştirilmeli. Serveo'da anahtarla kimlik doğrulama bu birleşimde `-18`
  ile reddedilir; anonim klavye-etkileşimli yol ve `bind=<ad>` ile yine de sabit ad alınır (nedeni
  bilinmiyor, serveo davranışı değişirse adres rastgeleye düşebilir). DNS çözülemezse `ips=` yedek adresleri
  denenir.
- Güvenlik: röle HTTPS'i sonlandırır, trafiği görür. Serveo'nun ücretsiz katmanı ilk ziyarette bir uyarı
  sayfası gösterir ("Continue to Site").

## 6. Bilinen sınırlar ve tuzaklar

- **PS5LM v0.8.x**: JSON'daki **her ondalık sayı** sunucuyu çökertir (v0.9.0'da düzeldi); payload ve LoRA
  ölçeği bu yüzden yalnızca tam sayı gönderir. Log kuyruğu dolunca `/completion` ve `/slots` yanıtsız kalıp
  yalnızca `/health` yanıt verebilir (v0.9.1'de düzeldi); `--log-disable` bunu önler.
- **PS5LM yeniden açılınca** model ~45 sn yüklenir; o sırada `/api/recommend` `503 model_loading` döner.
- **Arama**: yalnızca sözcüksel (BM25) ve 88 bin kitap; anlamsal arama ve yazım farkları ("Dostoyevski" /
  "Dostoievski") zayıf. Arayüzdeki tür/ruh/dönem filtreleri sonuçları belirgin iyileştirir.
- **Payload'u konsoldan durdurmak**: bu kurulumda bir yol yok; etaHEN/PS5LM yeniden başlatılınca ölür.
- **Saat**: davet bitişleri PS5'in saatine göre denetlenir (bu kurulumda PC'den ~2 dk ileriydi).
