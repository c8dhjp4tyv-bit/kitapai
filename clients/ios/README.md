# kitap.ai — iOS

SwiftUI uygulaması. macOS ve Xcode olmadan, Linux'ta
[`iosbuild`](https://github.com/c8dhjp4tyv-bit/iosbuild) ile derlenir.

## Hazırlık

```bash
git clone https://github.com/c8dhjp4tyv-bit/iosbuild ~/iosbuild
cd ~/iosbuild && ./bootstrap.sh
iosbuild sdk import /path/to/iPhoneOS26.5.sdk
iosbuild doctor          # 0 problem görmelisin
```

Gerekenler: `clang`/`ld64.lld`, iOS hedefli `swiftc`, `ldid`, kayıtlı bir
iPhoneOS SDK. Cihaza kurmak için ayrıca `pymobiledevice3`.

## Derleme

```bash
./build.sh                                          # build → bundle → sign → ipa
./build.sh --api https://makine.tailnet.ts.net      # varsayılan sunucuyu göm
./build.sh --allow-http                             # düz HTTP (Tailscale IP) izni
./build.sh --stage bundle                           # ara adımda dur
```

Çıktı: `build/KitapAI.ipa`

## Info.plist neden yamalanıyor?

`iosbuild bundle` sabit bir `Info.plist` üretir ve `iosbuild.json` özel anahtar
kabul etmez (bilinmeyen anahtarlar hata verir). Uygulama adı, sürüm, ekran yönü,
yerel ağ izni ve varsayılan API adresi bu yüzden `scripts/patch_plist.py` ile
**paketleme sonrası, imzalama öncesi** eklenir. Sıra önemlidir: imza
`CodeDirectory` karmalarını paketin son hâli üzerinden hesaplar, dolayısıyla
yama imzadan sonra yapılırsa imza geçersiz olur.

## Ağ: HTTP mi HTTPS mi?

iOS'ta App Transport Security düz HTTP'yi engeller. İki seçenek var:

1. **Önerilen — HTTPS.** Sunucu tarafında `./scripts/tailscale-serve.sh`
   çalıştır; `https://<makine>.<tailnet>.ts.net` adresi gerçek sertifikayla
   gelir, uygulamada hiçbir istisna gerekmez.
2. **Düz HTTP.** `./build.sh --allow-http` ile `NSAllowsLocalNetworking`
   istisnası eklenir ve `http://100.x.y.z:8000` gibi tailnet adresleri
   çalışır. Genel internete açık bir istisna (`NSAllowsArbitraryLoads`)
   bilinçli olarak eklenmez.

Sunucu adresi uygulama içinden de değiştirilebilir: üstteki "sunucu" düğmesi.

## Kaynak düzeni

| Dosya | İçerik |
|---|---|
| `Sources/Models.swift` | API sözleşmesi (`schemas.py` ile birebir; `test_contract.py` doğrular) |
| `Sources/ApiClient.swift` | URLSession + async/await, Türkçe hata eşlemesi |
| `Sources/RecommendStore.swift` | Ekran durumu (`@MainActor` ObservableObject) |
| `Sources/ContentView.swift` | Ana ekran: form, filtreler, sonuçlar |
| `Sources/BookCardView.swift` | Öneri kartı |
| `Sources/Settings.swift` | Sunucu adresi ve okunmuş kitaplar (UserDefaults) |
| `Sources/Theme.swift` | Web/Android ile ortak renk belirteçleri |

Yeni bir `.swift` dosyası eklersen `iosbuild.json` içindeki `sources` listesine
de eklemen gerekir — iosbuild dizini taramaz, listeyi okur.

## Cihaza kurma

```bash
iosbuild devices                      # bağlı cihazlar
iosbuild -C . install                 # geliştirme profili gerekir
```

Ad-hoc imza yalnızca jailbreak'li cihazlarda ya da geliştirici profiliyle
çalışır; App Store dağıtımı bu akışın kapsamında değil.
