# PS5'te çalıştırma (PS5LM)

Jailbreak'li PS5'te [PS5LM](https://github.com/cobanov/PS5LM) llama.cpp'yi konsolun GPU'sunda çalıştırır.
Bu klasör, seçici ve yazıcı modelleri **tek taban + iki LoRA** olarak oraya koymak için gerekenleri içerir.
PS5LM aynı anda tek model yükler ve model değiştirmek uygulamayı yeniden başlatır, bu yüzden iki ayrı
model yerine LoRA'lar istek başına açılıp kapatılır.

1. **Taban**: LoRA'sız, eğitimde kullanılan 4-bit tabanın *açılmış* hâli. LoRA'lar bu tabana göre öğrendi;
   gerçek fp16 tabana uygulanınca çıktı bozuluyordu.
   `python dequant_base.py models/kitapai-select base-deq-fp16` →
   `convert_hf_to_gguf.py base-deq-fp16 --outtype q8_0`
2. **LoRA'lar**: `convert_lora_to_gguf.py --base base-deq-fp16 models/kitapai-select` (ve `-write`). rsLoRA
   ölçeği llama.cpp'de alpha/r = 1 olarak uygulanır; gerçeği `sqrt(r)` (5,657). PS5LM v0.8.x JSON'daki her
   ondalık sayıda çöktüğü için ölçeği dosyaya gömün: `gguf_set_metadata.py lora-*.gguf adapter.lora.alpha
   181.01933598375618 --force`. İstekte ölçek `1` ya da `0` olur.
3. **Konsola**: `/data/PS5LM/kitapai/` altına taban + iki LoRA (FTP, çoğu kurulumda port 1337), `app-args.txt`'yi
   `/data/PS5LM/app-args.txt` olarak koyun (bu dosya varken uygulama her açılışta bunu yükler; silince eski
   davranış döner). `--log-disable` v0.8.3'teki log kuyruğu donmasını önler; v0.9.1+ ile gerekmez.
4. **Sunucu**: `KITAPAI_ENGINE=llama KITAPAI_LLAMA_URL=http://<konsol>:8081 kitapai serve`
   (`serve/engine.py::LlamaServerEngine`; isteklerde ondalık sayı yoktur).
5. **Ölçüm**: `eval_ps5.py <konsol>:8081 200 runs/picks-ps5.jsonl`, sonra `kitapai judge`'ın önbellek notlarıyla
   puanlayın (API gerekmez).

Ölçülen (200 örnek): PS5'te hakem puanı PC ile aynı (normalize 0,888); seçici ~2 sn, yazıcı ~3 sn,
uçtan uca öneri 5–8 sn.
