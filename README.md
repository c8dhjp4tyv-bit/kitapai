# kitap.ai

Open Library kataloğu üzerine kurulu, ince ayarlı bir Türkçe kitap öneri sistemi. Bir okurun
serbest cümlesinden ("yas ve kayıp üzerine sakin bir roman") gerçek kitaplar seçer ve her biri için
Türkçe, kişisel bir gerekçe yazar. Web, Android ve iOS istemcileri vardır. Sistem iki yerde
çalışabilir: bir bilgisayarda (Python/FastAPI) ya da **tamamen jailbreak'li bir PS5'in içinde**
(C++ payload, davet kodlu site ve internet tüneliyle).

## Ne yapıyor?

1. **Katalog**: Open Library dump'ları (eserler, baskılar, yazarlar, puanlar, okuma kayıtları) tek bir
   DuckDB dosyasına (≈2,4 milyon kitap) indirgenir. Her kitap Türkçe tür ve ruh hali etiketleriyle,
   dönem/uzunluk/okur kitlesi bilgisiyle, bilinirlik puanıyla ve varsa Türkçe baskı başlığıyla
   zenginleştirilir.
2. **Eğitim verisi**: Katalogdan sentetik ama gerçekçi Türkçe okur istekleri üretilir; her isteğe gerçek
   aday kitaplardan bir liste eşlik eder. Seçim etiketleri bir LLM hakemin notlarından, gerekçeler
   Gemini ile yeniden yazılarak üretilir (aşağıya bak).
3. **Model**: Qwen2.5-3B tabanı QLoRA ile ince ayarlanır; iki ayrı adaptör, tek taban model:
   **seçici** yalnızca kimlik döndürür, **yazıcı** seçilen kitaplar için gerekçe yazar. Model *kitap
   uydurmaz*; yalnızca verilen adaylardan seçim yapar.
4. **Servis**: İstek alınır, katalogdan aday getirilir (BM25 + anlamsal arama), modele sorulur, modelin
   seçtiği kimlikler katalog kayıtlarına geri çözülür ve tipli JSON döner.
5. **İstemciler**: Web (React), Android (React Native), iOS (SwiftUI, Linux'ta `iosbuild` ile derlenir).

### Eski sürümden temel fark

Önceki sürümde model markdown üretiyor, her istemci onu ayrı regex'lerle ayrıştırıyordu; uydurulmuş
kitaplar doğrudan ekrana düşüyordu. Burada sözleşme tiplidir ve **başlık, yazar, yıl, ISBN, kapak gibi
hiçbir bilgi modelden gelmez**: hepsi katalogdan okunur. Seçici yalnızca `{"ids":["a3","a1"]}` üretir;
listede olmayan bir kimlik uydurursa o seçim düşer.

```
istek ─▶ geri getirme ─▶ SEÇİCİ ─▶ zayıf eşleşme ─▶ YAZICI ─▶ katalog ─▶ yanıt
         (BM25+vektör)   (id'ler)  filtresi (kural)  (gerekçe)  (gerçek veri)
```

**Neden iki model?** Tek modelde kaybın çoğunu ~300 token'lık gerekçe metni taşır; seçim kararı (~17
token) sinyalini kaybeder. Ayrı seçicide kaybın tamamı seçimdedir ve çıktı çok kısa olduğundan hızlıdır.
Seçim başarısızsa kural tabanlı geri getirme sırası, yazım başarısızsa şablon gerekçe devreye girer
(yanıtta `degraded` ve bir not olarak işaretlenir). Güven puanı modelden değil, katalog verisine dayalı
kuraldan gelir.

## Kalite ölçümü: Gemini hakem

Referans-tabanlı isabet (`kitapai eval`) yalnızca eğitim hedefindeki kitapları "doğru" sayar; belirsiz
isteklerde bu hem iyi seçimleri cezalandırır hem de hedefin kendi hatalarını ödüllendirir. Gerçekte
hedefin kendisi gürültülüydü: Gemini hakeme göre hedef seçimlerin **%32'si isteğe hiç uymuyordu**. Bu
yüzden:

- `kitapai judge` her örnekteki tüm adayları 0–2 ile notlar (önbellekli, bir kez) ve modellerin
  seçimlerini rastgele (taban) ve ideal (tavan) seçimle birlikte puanlar.
- `kitapai judge-write` yazılan gerekçelerin kitap bilgisiyle desteklenip desteklenmediğini (uydurma oranı)
  ve yararını notlar.
- `kitapai dataset relabel` seçici eğitim etiketlerini bu notlardan yeniden üretir (önce 2'ler, sonra
  1'ler, 0 asla).

Önbellekteki notlar `runs/judge-ratings.jsonl` içindedir; yeni bir modeli puanlamak için Gemini'ye yeniden
gitmek gerekmez (`evaluation/judge.py` içindeki `score_records`).

Ölçülen sonuçlar (200 doğrulama örneğinin ortak 100'ü, hakem Gemini, 0–2 not):

| Model | ort. not | iyi | kötü | normalize* |
|---|---|---|---|---|
| eski tek model (v1–v3) | 1,01–1,06 | %34–37 | %31–33 | 0,43–0,49 |
| seçici, HF + bitsandbytes 4-bit | 1,38 | %51 | %13 | 0,86 |
| seçici, birleştirilmiş GGUF (Q8) | 1,40 | %52 | %12 | 0,883 |
| **seçici, tek taban + çalışma anı LoRA (PC ve PS5)** | **1,41** | **%52** | **%12** | **0,888** |

\*0 = rastgele seçim, 1 = ideal seçim. Yazıcı: dayanak 1,81/2, yarar 1,55/2, uydurma gerekçe %4,3.
**Hakem ile etiket üreticisi aynı model (Gemini) olduğundan bu bağımsız bir doğrulama değildir.**

### Gecikme

| Kurulum | Seçici | Yazıcı | Uçtan uca |
|---|---|---|---|
| PC, bitsandbytes 4-bit (RTX 5060 Laptop) | ~1 sn | ~7 sn | ~10 sn |
| **PS5, Q8 GGUF + çalışma anı LoRA** | ~2 sn | ~3 sn | **5–8 sn** (geri getirme ~2 sn dahil) |
| PS5 + serveo tüneli (internet) | | | ~8 sn |

Yazıcı çıktısı JSON yerine `a1: gerekçe` satırlarıdır (çengeller kural tabanlı); bu çıktıyı ~%40
kısaltır.

### GGUF ve llama.cpp: neden "açılmış taban"?

QLoRA adaptörleri eğitimde kullanılan **4-bit (nf4) tabanın açılmış (dequantize) hâline** göre
öğrendi. Gerçek fp16 tabana ya da onun Q8'ine uygulandığında çıktı bozuluyordu. Çözüm: tabanı
eğitimdeki gibi açıp (`scripts/ps5/dequant_base.py`) Q8 GGUF'a çevirmek ve LoRA'ları üzerine
çalışma anında uygulamak. rsLoRA ölçeği llama.cpp'de `alpha/r` olarak uygulanır, gerçeği `√r`'dir; bu
yüzden ölçek LoRA dosyasına gömülür (`adapter.lora.alpha = 32·√32`). peft'in `merge_and_unload`'ı 4-bit
katmanda toplamı tekrar nicemlediği için birleştirme elle yapılmalıdır.

## Kurulum

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[embed]"
cp .env.example .env
```

Eğitim ve yerel model çalıştırma için (CUDA gerekir):

```bash
uv pip install --python .venv/bin/python -e ".[train,serve-local]"
```

> **RTX 50xx (Blackwell) notu:** sm_120 için CUDA 12.8+ derlenmiş torch gerekir:
> `uv pip install --python .venv/bin/python torch --index-url https://download.pytorch.org/whl/cu128`

Ortamı denetle:

```bash
kitapai doctor
```

## Disk ve donanım

| Adım | Gereken |
|---|---|
| Dump indirme | ~17 GiB (gz, sıkıştırılmış hâlde kalır) |
| Katalog kurulumu | +3-6 GiB (DuckDB) + geçici taşma alanı |
| Gömme indeksi | 300 bin kitap için ~230 MiB |
| Eğitim (3B QLoRA) | 8 GiB VRAM yeter; 2048–3072 token dizi uzunluğu |
| Eğitim (7B QLoRA) | 8 GiB VRAM'de sınırda: `configs/train-7b-8gb.yaml` |
| Servis (3B 4-bit) | ~3 GiB VRAM |
| GGUF dışa aktarım | birleştirilmiş fp16 ara dosya ~6 GiB + Q8 çıktı ~3,3 GiB |

Diskin darsa iki çıkış yolu var:

```bash
# 1) Dump'ları hiç indirme, doğrudan akıtarak katalogu kur
kitapai data build --remote --temp-dir /baska/disk/tmp

# 2) Veri kökünü harici diske taşı
export KITAPAI_DATA_DIR=/mnt/disk2/kitapai-data
```

> btrfs + zstd kullanıyorsan `du` ve `df` gerçek kullanımı abartır; `btrfs filesystem usage` bak.

## Boru hattı

```bash
# 1. Dump'lar (kesilirse aynı komut kaldığı yerden devam eder)
kitapai data download

# 2. Katalog  (tam dump'ta ~30-90 dk; deneme için --limit 200000)
kitapai data build --dumps data/dumps --memory 6GB --threads 8
kitapai data stats

# 3. Eğitim verisi
kitapai dataset build --samples 40000
kitapai dataset preview --n 2

# 4. Anlamsal arama indeksi
kitapai index build --limit 300000

# 4b. Görev dosyaları (SEÇ / YAZ) ve, isteğe bağlı, Gemini ile iyileştirme
kitapai dataset stages
runs/gemini.sh dataset distill --n 8000      # gerekçeleri yeniden yazdır (YAZ verisi)
runs/gemini.sh dataset relabel --n 6000      # seçim etiketlerini hakem notlarıyla yaz

# 5. İnce ayar (8 GB GPU'da seçici ~2,8 sa, yazıcı ~1,3 sa)
kitapai train -c configs/train-select.yaml
kitapai train -c configs/train-write.yaml

# 6. Ölçüm
kitapai eval --mode select -n 200 --record runs/picks-select.jsonl
kitapai eval --mode write  -n 200
runs/gemini.sh judge yeni=runs/picks-select.jsonl -n 200

# 7. Servis
kitapai serve
```

`runs/gemini.sh` Gemini anahtarını çalışma anında `~/.zshrc`'den okur (`GCLOUD_API_KEY`); anahtar
hiçbir dosyaya yazılmaz. Gemini gerektirmeyen her adım onsuz çalışır.

Modeli beklemeden denemek için `KITAPAI_ENGINE=stub` ile de çalışır; boru hattının tamamı (geri
getirme, kural tabanlı gerekçe, istemciler) çalışır, yalnızca gerekçeler şablon olur.

Motorlar (`KITAPAI_ENGINE`): `transformers` (yerel 4-bit + LoRA), `llama` (llama-server, çalışma anı
LoRA: PS5LM ya da yerel), `openai` (OpenAI uyumlu uç nokta), `stub`.

Terminalden tek seferlik öneri:

```bash
kitapai ask "çölde geçen, ağır olmayan epik bir bilim kurgu"
```

## Telefon bağlantısı (Tailscale)

Sunucu `0.0.0.0`'a bağlanır; telefon tailnet üzerinden erişir.

```bash
# düz HTTP (Android ve web için yeterli)
kitapai serve                      # http://<tailscale-ip>:8000

# HTTPS (iOS için gerekli: ATS düz HTTP'yi engeller)
./scripts/tailscale-serve.sh       # https://<makine>.<tailnet>.ts.net
```

`tailscale serve` gerçek bir Let's Encrypt sertifikası verdiği için iOS uygulamasında ek bir istisna
tanımlamak gerekmez. Tailnet dışına açacaksan `.env` içinde `KITAPAI_API_KEY` doldur; istemciler
`X-API-Key` başlığı gönderir. Telefonda başka bir VPN'in "kill switch" özelliği açıksa yerel ve Tailscale
adreslerinin hiçbiri açılmaz (sunucuya paket bile gelmez); önce bunu kontrol et.

## API

| Uç nokta | Açıklama |
|---|---|
| `POST /api/recommend` | Asıl öneri uç noktası (tipli istek/yanıt) |
| `GET /api/search?q=` | Katalog araması (model çalıştırmaz) |
| `GET /api/book/{id}` | Tek kitap |
| `GET /api/similar/{id}` | Benzer kitaplar |
| `GET /api/taxonomy` | Tür/ruh/dönem listeleri; istemciler buradan okur |
| `POST /api/invite` | Davet kodunu doğrular (yalnızca PS5 sunucusu, aşağıya bak) |
| `GET /health` | Durum, model, katalog boyutu |
| `GET /api/meta` | Katalog künyesi (hangi dump, hangi seçenekler; yalnızca Python sunucusu) |

```bash
curl -s localhost:8000/api/recommend -H 'content-type: application/json' \
  -d '{"query":"yas ve kayıp üzerine sakin bir roman","limit":3}' | jq
```

Kimlik: Python sunucusunda `KITAPAI_API_KEY` doluysa `X-API-Key` zorunludur. PS5 sunucusunda aynı başlık
**davet kodunu** taşır ve her istekte sunucuda denetlenir.

## İstemciler

### Web

```bash
cd clients/web
npm install
VITE_API_URL=http://localhost:8000 npm run dev
npm run build            # dist/: PS5 payload'u bunu aynı adresten sunar
```

Telefondan açmak için `VITE_API_URL` yerine Tailscale adresini ver (ya da `?api=http://adres` ile bir
kez aç; adres tarayıcıda saklanır). PWA olarak kurulabilir. PS5 sürümünde açılışta **davet kodu**
ekranı gelir; kod sunucuda doğrulanır, süresi dolarsa uygulama kapıya döner.

### Android

```bash
cd clients/android
npm install
npm run android          # geliştirme
npm run build:release    # imzalı APK için android/app/build.gradle içindeki notlara bak
```

Davet kodlu bir sunucuya bağlanmak için kodu ayarlardaki **API anahtarı** alanına yaz; ayrı bir kapı
ekranı yok.

### iOS: Linux'ta, Xcode olmadan

[`iosbuild`](https://github.com/c8dhjp4tyv-bit/iosbuild) ile derlenir:

```bash
cd clients/ios
./build.sh                                          # build → bundle → Info.plist yaması → imza → .ipa
./build.sh --api https://kitapai-sunum.serveousercontent.com   # varsayılan sunucuyu göm (HTTPS)
./build.sh --api http://100.x.y.z:8000 --allow-http # düz HTTP (yalnızca kişisel kurulum)
```

Uygulama açılışta davet kodunu sorar (sunucuda doğrulanır, `X-API-Key` olarak saklanır); sunucu kodu
reddederse kapıya döner. `iosbuild bundle` sabit bir `Info.plist` yazdığı için betik, imzalamadan önce
uygulama adını, sürümü ve ağ ayarlarını plist'e işler (`scripts/patch_plist.py`). İmza ad-hoc'tur; kendi
yükleme yönteminle (sideload) kurulur. Ayrıntı: [`clients/ios/README.md`](clients/ios/README.md).

## PS5'te çalıştırma (sunum sürümü)

Her şey PS5'in içinde çalışır; bilgisayar gerekmez:

```
 telefon / tarayıcı ──HTTPS──▶ serveo (röle) ◀──SSH ters tüneli── PS5 payload'u (kitapai-server.elf)
                                                                    ├─ statik site + davet kapısı
                                                                    ├─ /api/* (C++ BM25 arama, istemler, çözücüler)
                                                                    └─ 127.0.0.1:8081 ─▶ PS5LM llama-server
                                                                         (tek taban Q8 + seçici/yazıcı LoRA)
```

- **Model**: [PS5LM](https://github.com/cobanov/PS5LM) llama.cpp'yi konsolun GPU'sunda çalıştırır. Tek
  taban model + iki LoRA yüklenir; her istek `lora` alanıyla hangisinin açık olacağını söyler.
- **Payload**: `scripts/ps5/payload/` altındaki C++ (PS5 payload SDK'sıyla derlenir) siteyi, API'yi ve
  davet kodlarını sunar. Arama Python'dan taşındı ve Python'la **birebir** karşılaştırıldı (golden test,
  2249 kontrol). Katalog PS5'e ≥15 okuyuculu 88 bin kitaplık bir alt küme olarak gider; **anlamsal
  (vektör) arama yoktur**, bu yüzden bazı sorgular Python sürümünden zayıftır.
- **Davet kodları**: 24 hane, sunucu tarafında ve bitiş zamanıyla denetlenir (`scripts/ps5/make_codes.py`).
  Kodlar depoya girmez.
- **İnternet**: CGNAT arkasında PS5 dışarıya bağlanır (libssh2 + mbedtls). Serveo ile **sabit alt alan adı**
  alınır; bir bekçi adresi periyodik sınar, düşerse yeniden bağlanır.
- Kurulum, derleme, dağıtım ve tuzaklar: [`scripts/ps5/README.md`](scripts/ps5/README.md).

> **Bilinen sınırlar:** serveo ücretsiz katmanı ilk ziyarette bir uyarı sayfası ("Continue to Site")
> gösterir ve yanıt başlığını ~5 sn içinde bekler (payload yanıtı bu yüzden akıtır). Röle trafiği görür.
> PS5LM v0.8.x JSON'daki ondalık sayılarda çöker ve log kuyruğu dolunca donabilir; payload isteklerde
> ondalık sayı göndermez ve `--log-disable` kullanılır. PS5 yeniden başlarsa model ~45 sn yüklenir.

## Büyük dosyalar (modeller, veri, IPA)

Kod bu depoda; eğitilmiş adaptörler, katalog, eğitim verisi, Open Library dump'ları ve iOS IPA'sı git'e
sığmadığı için [Releases](../../releases) altında (`v2.0-artifacts`) duruyor. Hazır modelle çalıştırmak
için:

```bash
gh release download v2.0-artifacts -p 'kitapai-select.tar.zst' -p 'kitapai-write.tar.zst' \
  -p 'catalog.duckdb.part*' -p 'data-vectors.tar.zst'
mkdir -p models data
tar --zstd -xf kitapai-select.tar.zst -C models && tar --zstd -xf kitapai-write.tar.zst -C models
tar --zstd -xf data-vectors.tar.zst -C data
cat catalog.duckdb.part* > data/catalog.duckdb
kitapai serve --port 8765
```

Release'te `KitapAI.ipa` en son (davet kapılı, HTTPS) sürümdür; sağlama toplamları `SHA256SUMS.txt`
içindedir. **Release'te olmayanlar**: GGUF dosyaları (taban Q8 ve LoRA'lar) ve PS5 veri paketi
(`books.tsv`, `meta.json`); bunlar `scripts/ps5/` betikleriyle yeniden üretilir.

Adaptörler `Qwen/Qwen2.5-3B-Instruct` tabanı üzerinedir; taban modelin lisansı (Qwen Research License)
geçerlidir.

## Proje düzeni

```
src/kitapai/
  schemas.py        API sözleşmesi (tek kaynak)
  taxonomy.py       tür/ruh taksonomisi + Open Library konu eşlemesi
  prompting.py      eğitim ve servis için TEK istem biçimi
  matching.py       istek-kitap uyum puanı (eğitim ve servis ortak)
  turkish.py        Türkçe ek/biçim yardımcıları
  data/             dump indirme, DuckDB katalog kurulumu
  dataset/          sentetik istek üretimi, eğitim örnekleri, Gemini damıtma
  retrieval/        BM25 + gömme + RRF füzyonu
  train/            QLoRA eğitimi, birleştirme, GGUF
  evaluation/       ölçütler (metrics), değerlendirme (run), Gemini hakem (judge)
  serve/            FastAPI, motorlar (transformers/llama/openai/stub), boru hattı
clients/
  shared/           ortak TypeScript API istemcisi (web + Android)
  web/              Vite + React + TS (davet kapısı dahil)
  android/          React Native
  ios/              SwiftUI + iosbuild (davet kapısı dahil)
scripts/
  tailscale-serve.sh  HTTPS için tailscale serve
  ps5/                PS5 sunum sürümü
    payload/          C++ payload: sunucu, arama çekirdeği, SSH tüneli, bekçi, testler
    export_bundle.py  PS5 veri paketini üretir (books.tsv, meta.json)
    make_codes.py     24 haneli davet kodları üretir
    dequant_base.py   açılmış 4-bit taban (GGUF için)
    eval_ps5.py       seçiciyi PS5 üzerinden ölçer
    gen_golden.py     C++ ↔ Python karşılaştırma değerleri
configs/            eğitim ayarları (seçici, yazıcı, eski sürümler)
runs/               çalıştırma betikleri, ölçüm sonuçları, Gemini hakem notları
```

## Testler

```bash
uv pip install --python .venv/bin/python -e ".[dev]"
python tests/fixtures/make_mini_dump.py   # küçük sahte dump üretir
pytest -q                                 # 203 test
ruff check src tests
```

Testler gerçek dump olmadan çalışır: `tests/fixtures/mini_dump/` içindeki küçük ama biçimi birebir aynı
dosyalar üzerinden tüm boru hattı (ayrıştırma → katalog → veri kümesi → geri getirme → API) uçtan uca
koşturulur. Testler GPU'ya dokunmaz (`CUDA_VISIBLE_DEVICES=""`).

C++ çekirdeği için (Python ile birebir karşılaştırma):

```bash
python scripts/ps5/export_bundle.py bundle && python scripts/ps5/gen_golden.py bundle golden.json
g++ -O2 -std=c++17 scripts/ps5/payload/test_core.cpp -o test_core && ./test_core bundle golden.json
```

## Güvenlik notları

- **Davet kodları** depoya ve geçmişe girmez (`.gitignore`, her push öncesi tarama). Doğrulama sunucudadır,
  sitede gizli anahtar yoktur. Hatalı denemeler genel olarak sınırlanır (dakikada 30).
- **Röle** (serveo) HTTPS'i sonlandırdığı için trafiği görür; davet kodları teknik olarak röleden geçer.
- **Serveo SSH anahtarı** (`serveo_rsa`) PS5'in `/data/PS5LM/kitapai/` klasöründedir ve PS5 FTP'si aynı
  ağda kimlik doğrulamasızdır; anahtar yalnızca o alt alan adını yönlendirmeye yarar. Depoda değildir.
- Gemini anahtarı hiçbir dosyada tutulmaz.

## Lisans

MIT (`pyproject.toml`; depoda henüz ayrı bir `LICENSE` dosyası yok). Katalog verisi Open Library'den gelir
ve [ODbL](https://openlibrary.org/developers/dumps) ile lisanslıdır; türetilmiş veritabanını dağıtırsan aynı
lisans geçerlidir. Üçüncü taraf bileşenler kendi lisanslarıyla gelir: Qwen2.5 (Qwen Research License),
llama.cpp (MIT), PS5LM (GPL-3.0), libssh2 (BSD), mbedTLS (Apache-2.0).
