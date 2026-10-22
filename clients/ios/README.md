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
./build.sh --api https://kitapai-sunum.serveousercontent.com   # varsayılan sunucuyu göm (HTTPS)
./build.sh --allow-http                             # düz HTTP izni (yalnızca kişisel kurulum)
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

## Davet kodu

Uygulama açılışta 24 haneli davet kodunu sorar (`Sources/InviteGateView.swift`). Kod sunucuda doğrulanır
(`POST /api/invite`) ve `X-API-Key` olarak saklanır. Sunucu kodu reddederse (süresi dolmuş ya da geçersiz)
kod silinir ve kapı yeniden gösterilir; altbilgide kalan süre ve "Çıkış" vardır. Derlemeyle gömülen adres
değişirse, eski kayıtlı adres yeni varsayılana yerini bırakır.

## Ağ: HTTP mi HTTPS mi?

iOS'ta App Transport Security düz HTTP'yi engeller. İki seçenek var:

1. **Önerilen: HTTPS.** Serveo tüneli (`https://kitapai-sunum.serveousercontent.com`) ya da sunucu tarafında
   `./scripts/tailscale-serve.sh` (`https://<makine>.<tailnet>.ts.net`) gerçek sertifikayla gelir; uygulamada
   hiçbir istisna gerekmez. IPA bu şekilde derlenir.
2. **Düz HTTP.** `./build.sh --allow-http` Info.plist'e `NSAllowsArbitraryLoads` ekler. `NSAllowsLocalNetworking`
   yetmez: o yalnızca `.local` ve özel ağ adreslerini kapsar, Tailscale adresleri (100.64.0.0/10) kapsam
   dışında kalır. Bu bayrak yalnızca kişisel yan yükleme için kullanılmalı; mağaza sürümü için HTTPS gerekir.

Sunucu adresi uygulama içinden de değiştirilebilir: üstteki "sunucu" düğmesi.

## Kaynak düzeni

| Dosya | İçerik |
|---|---|
| `Sources/Models.swift` | API sözleşmesi (`schemas.py` ile birebir; `test_contract.py` doğrular) |
| `Sources/ApiClient.swift` | URLSession + async/await, Türkçe hata eşlemesi, davet kodu doğrulama |
| `Sources/InviteGateView.swift` | Davet kodu ekranı (24 hane, sunucuda doğrulanır) |
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
