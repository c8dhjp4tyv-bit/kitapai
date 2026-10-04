# kitap.ai v2.0 — veri, modeller, IPA

Kod depoda; büyük dosyalar buraya yüklendi. Doğrulama için `SHA256SUMS.txt`.

| Dosya | İçerik |
|---|---|
| `kitapai-select.tar.zst` | **Seçici** LoRA adaptörü (Gemini hakem etiketleriyle eğitildi) → `models/kitapai-select` |
| `kitapai-write.tar.zst` | **Yazıcı** LoRA adaptörü (satır biçimi) → `models/kitapai-write` |
| `kitapai-lora*.tar.zst` | Eski tek model sürümleri v1, v2, v3 (karşılaştırma için) |
| `data-dataset.tar.zst` | Eğitim verisi (SEÇ/YAZ, damıtılmış, hakem etiketli) → `data/dataset` |
| `data-dataset_eski.tar.zst` | İlk sürüm eğitim verisi |
| `data-vectors.tar.zst` | Anlamsal arama indeksi (300 bin vektör) |
| `data-dumps.tar.zst` | Open Library dump'ları (yazarlar, puanlar, okuma kayıtları) |
| `catalog.duckdb.part00`, `part01` | Katalog (2,4 milyon kitap). Birleştir: `cat catalog.duckdb.part* > data/catalog.duckdb` |
| `KitapAI.ipa` | iOS uygulaması (ad-hoc imzalı, sideload) |

Açma: `tar --zstd -xf <dosya> -C models/` (modeller) ya da `-C data/` (veri).

**Lisans notu:** Adaptörler `Qwen/Qwen2.5-3B-Instruct` tabanı üzerine eğitildi; taban modelin
lisansı (Qwen Research License) geçerlidir, ticari kullanım için kontrol edin. Open Library verisi
kamu malı/CC0'dır. Eğitim gerekçeleri Gemini ile üretildi.
