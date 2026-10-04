# kitap.ai

Open Library'nin tam kataloğu üzerine kurulu, ince ayarlı bir Türkçe kitap
öneri sistemi. Web, Android ve iOS istemcileriyle birlikte gelir; bilgisayarla
telefon arasındaki bağlantı Tailscale üzerinden kurulur.

## Ne yapıyor?

1. **Katalog** — Open Library dump'ları (eserler, baskılar, yazarlar, puanlar,
   okuma kayıtları) tek bir DuckDB dosyasına indirgenir. Her kitap Türkçe tür
   ve ruh hali etiketleriyle, dönem/uzunluk/okur kitlesi bilgisiyle,
   bilinirlik puanıyla ve varsa Türkçe baskı başlığıyla zenginleştirilir.
2. **Eğitim verisi** — Katalogdan sentetik ama gerçekçi Türkçe okur istekleri
   üretilir; her isteğe gerçek aday kitaplardan oluşan bir liste ve doğru
   seçimi işaretleyen bir hedef JSON eşlik eder.
3. **Model** — Qwen2.5 tabanı QLoRA ile ince ayarlanır; iki ayrı adaptör, tek
   taban model: **seçici** yalnızca kimlik döndürür, **yazıcı** seçilen kitaplar
   için Türkçe gerekçe yazar. Model *kitap uydurmaz*; yalnızca verilen
   adaylardan seçim yapar.
4. **Servis** — FastAPI; isteği alır, katalogdan aday getirir (BM25 + anlamsal
   arama), modele sorar, modelin seçtiği kimlikleri katalog kayıtlarına geri
   çözer ve tipli JSON döner.
5. **İstemciler** — Web (React), Android (React Native) ve iOS (SwiftUI,
   Linux'ta `iosbuild` ile derlenir).

### Eski sürümden temel fark

Önceki sürümde model markdown üretiyor, her istemci onu ayrı regex'lerle
ayrıştırıyordu; uydurulmuş kitaplar doğrudan ekrana düşüyordu. Burada sözleşme
tiplidir ve **başlık, yazar, yıl, ISBN, kapak gibi hiçbir bilgi modelden
gelmez** — hepsi katalogdan okunur. Seçici yalnızca `{"ids":["a3","a1"]}`
üretir; listede olmayan bir kimlik uydurursa o seçim düşer.

```
istek ─▶ geri getirme ─▶ SEÇİCİ ─▶ zayıf eşleşme ─▶ YAZICI ─▶ katalog ─▶ yanıt
         (BM25+vektör)   (id'ler)  filtresi (kural)  (gerekçe)  (gerçek veri)
```

**Neden iki model?** Tek modelde kaybın çoğunu ~300 token'lık gerekçe metni taşır;
seçim kararı (~17 token) sinyalini kaybeder. Ayrı seçicide kaybın tamamı seçimdedir,
çıktı çok kısa olduğundan hızlıdır. Seçim başarısızsa kural tabanlı geri getirme sırası,
yazım başarısızsa şablon gerekçe devreye girer (yanıtta `degraded` ve bir not olarak
işaretlenir). Güven puanı modelden değil, katalog verisine dayalı kuraldan gelir.

### Kalite ölçümü: Gemini hakem

Referans-tabanlı isabet (`kitapai eval`) yalnızca eğitim hedefindeki kitapları "doğru"
sayar; belirsiz isteklerde bu hem iyi seçimleri cezalandırır hem de hedefin kendi
hatalarını ödüllendirir. Gerçekte hedefin kendisi gürültülüydü: Gemini hakeme göre
hedef seçimlerin **%32'si isteğe hiç uymuyordu**. Bu yüzden:

- `kitapai judge` her örnekteki tüm adayları 0–2 ile notlar (önbellekli, bir kez) ve
  modellerin seçimlerini rastgele (taban) ve ideal (tavan) seçimle birlikte puanlar.
- `kitapai judge-write` yazılan gerekçelerin kitap bilgisiyle desteklenip desteklenmediğini
  (uydurma oranı) ve yararını notlar.
- `kitapai dataset relabel` seçici eğitim etiketlerini bu notlardan yeniden üretir
  (önce 2'ler, sonra 1'ler, 0 asla).

Ölçülen sonuçlar (8 GB laptop GPU, Qwen2.5-3B QLoRA, 100 doğrulama örneği, hakem Gemini):

| | ort. not (0–2) | iyi | kötü | normalize* |
|---|---|---|---|---|
| eski tek model (v1–v3) | 1,01–1,06 | %34–37 | %31–33 | 0,43–0,49 |
| **seçici** | **1,38** | **%51** | **%13** | **0,86** |

\*0 = rastgele seçim, 1 = ideal seçim. Yazıcı: dayanak 1,81/2, uydurma gerekçe %4,3 (satır biçimli yazıcı; JSON'lu önceki sürüm 1,83 / %2,1).
Hakem ile etiket üreticisi aynı model olduğundan bu bağımsız bir doğrulama değildir.
Gecikme (uçtan uca, bu GPU'da): ~12–14 sn — geri getirme ~1 sn, seçici ~1 sn, yazıcı ~10 sn
(4-bit modelde 40–60 ms/token). Yazıcı çıktısı JSON yerine `a1: gerekçe` satırlarıdır (çengeller kural tabanlı), bu çıktıyı ~%40 kısaltır. llama.cpp/GGUF denendi ama QLoRA adaptörleri Q8 tabanda bozuk çalıştığı için kullanılmıyor.

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
| Eğitim (3B QLoRA) | 8 GiB VRAM yeter; 2048 token dizi uzunluğu |
| Eğitim (7B QLoRA) | 8 GiB VRAM'de sınırda — `configs/train-7b-8gb.yaml` |
| Servis (3B 4-bit) | ~3 GiB VRAM |

Diskin darsa iki çıkış yolu var:

```bash
# 1) Dump'ları hiç indirme, doğrudan akıtarak katalogu kur
kitapai data build --remote --temp-dir /baska/disk/tmp

# 2) Veri kökünü harici diske taşı
export KITAPAI_DATA_DIR=/mnt/disk2/kitapai-data
```

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

# 4b. Görev dosyaları (SEÇ / YAZ) ve — isteğe bağlı — Gemini ile iyileştirme
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

Modeli beklemeden denemek için `KITAPAI_ENGINE=stub` ile de çalışır; boru
hattının tamamı (geri getirme, kural tabanlı gerekçe, istemciler) çalışır,
yalnızca gerekçeler şablon olur.

Terminalden tek seferlik öneri:

```bash
kitapai ask "çölde geçen, ağır olmayan epik bir bilim kurgu"
```

## Telefon bağlantısı (Tailscale)

Sunucu `0.0.0.0`'a bağlanır; telefon tailnet üzerinden erişir.

```bash
# düz HTTP (Android ve web için yeterli)
kitapai serve                      # http://<tailscale-ip>:8000

# HTTPS (iOS için gerekli — ATS düz HTTP'yi engeller)
./scripts/tailscale-serve.sh       # https://<makine>.<tailnet>.ts.net
```

`tailscale serve` gerçek bir Let's Encrypt sertifikası verdiği için iOS
uygulamasında ek bir istisna tanımlamak gerekmez. Tailnet dışına açacaksan
`.env` içinde `KITAPAI_API_KEY` doldur; istemciler `X-API-Key` başlığı gönderir.

## API

| Uç nokta | Açıklama |
|---|---|
| `POST /api/recommend` | Asıl öneri uç noktası (tipli istek/yanıt) |
| `GET /api/search?q=` | Katalog araması (model çalıştırmaz) |
| `GET /api/book/{id}` | Tek kitap |
| `GET /api/similar/{id}` | Benzer kitaplar |
| `GET /api/taxonomy` | Tür/ruh/dönem listeleri — istemciler buradan okur |
| `GET /health` | Durum, model, katalog boyutu |
| `GET /api/meta` | Katalog künyesi (hangi dump, hangi seçenekler) |

```bash
curl -s localhost:8000/api/recommend -H 'content-type: application/json' \
  -d '{"query":"yas ve kayıp üzerine sakin bir roman","limit":3}' | jq
```

## İstemciler

### Web

```bash
cd clients/web
npm install
VITE_API_URL=http://localhost:8000 npm run dev
```

Telefondan açmak için `VITE_API_URL` yerine Tailscale adresini ver. Uygulama
PWA olarak kurulabilir (Ana Ekrana Ekle).

### Android

```bash
cd clients/android
npm install
npm run android          # geliştirme
npm run build:release    # imzalı APK için android/app/build.gradle içindeki notlara bak
```

### iOS — Linux'ta, Xcode olmadan

[`iosbuild`](https://github.com/c8dhjp4tyv-bit/iosbuild) ile derlenir:

```bash
cd clients/ios
./build.sh                       # build → bundle → Info.plist yaması → imza → .ipa
./build.sh --api https://makine.tailnet.ts.net
```

`iosbuild bundle` sabit bir `Info.plist` yazdığı için betik, imzalamadan önce
uygulama adını, sürümü ve ağ ayarlarını plist'e işler (`scripts/patch_plist.py`).
Ayrıntı: [`clients/ios/README.md`](clients/ios/README.md).

## Büyük dosyalar (modeller, veri, IPA)

Kod bu depoda; eğitilmiş adaptörler, katalog, eğitim verisi, Open Library dump'ları ve iOS IPA'sı
git'e sığmadığı için [Releases](../../releases) altında (`v2.0-artifacts`) duruyor. Hazır
modelle çalıştırmak için:

```bash
gh release download v2.0-artifacts -p 'kitapai-select.tar.zst' -p 'kitapai-write.tar.zst' \
  -p 'catalog.duckdb.part*' -p 'data-vectors.tar.zst'
mkdir -p models data
tar --zstd -xf kitapai-select.tar.zst -C models && tar --zstd -xf kitapai-write.tar.zst -C models
tar --zstd -xf data-vectors.tar.zst -C data
cat catalog.duckdb.part* > data/catalog.duckdb
kitapai serve --port 8765
```

Adaptörler `Qwen/Qwen2.5-3B-Instruct` tabanı üzerinedir; taban modelin lisansı (Qwen Research
License) geçerlidir. Ayrıntı ve sağlama toplamları release notlarında.

## Proje düzeni

```
src/kitapai/
  schemas.py        API sözleşmesi (tek kaynak)
  taxonomy.py       tür/ruh taksonomisi + Open Library konu eşlemesi
  prompting.py      eğitim ve servis için TEK istem biçimi
  matching.py       istek-kitap uyum puanı (eğitim ve servis ortak)
  turkish.py        Türkçe ek/biçim yardımcıları
  data/             dump indirme, DuckDB katalog kurulumu
  dataset/          sentetik istek üretimi, eğitim örnekleri
  retrieval/        BM25 + gömme + RRF füzyonu
  train/            QLoRA eğitimi, birleştirme, GGUF
  evaluation/       ölçütler (metrics), değerlendirme (run), Gemini hakem (judge)
  serve/            FastAPI, motorlar, boru hattı
clients/
  shared/           ortak TypeScript API istemcisi (web + Android)
  web/              Vite + React + TS
  android/          React Native
  ios/              SwiftUI + iosbuild
```

## Testler

```bash
uv pip install --python .venv/bin/python -e ".[dev]"
python tests/fixtures/make_mini_dump.py   # küçük sahte dump üretir
pytest -q
```

Testler gerçek dump olmadan çalışır: `tests/fixtures/mini_dump/` içindeki
küçük ama biçimi birebir aynı dosyalar üzerinden tüm boru hattı (ayrıştırma →
katalog → veri kümesi → geri getirme → API) uçtan uca koşturulur.

## Lisans

MIT. Katalog verisi Open Library'den gelir ve
[ODbL](https://openlibrary.org/developers/dumps) ile lisanslıdır; türetilmiş
veritabanını dağıtırsan aynı lisans geçerlidir.
