import Foundation

/// Sunucu adresi ve okunmuş kitap listesi — `UserDefaults` üzerinde kalıcı.
///
/// iOS'ta düz HTTP varsayılan olarak engellenir (App Transport Security).
/// Bu yüzden önerilen adres `tailscale serve` ile üretilen HTTPS adresidir:
///   https://<makine>.<tailnet>.ts.net
/// Düz HTTP kullanmak istersen `scripts/patch_plist.py --allow-http` ile
/// derleme sırasında istisna tanımlanır.
@MainActor
final class Settings: ObservableObject {
    private enum Keys {
        static let apiURL = "kitapai.apiURL"
        static let apiKey = "kitapai.apiKey"
        static let read = "kitapai.read"
    }

    /// Derleme sırasında `build.sh --api ...` ile Info.plist'e yazılan adres;
    /// yoksa kullanıcı uygulama içinden girer.
    static var defaultURL: String {
        let value = Bundle.main.object(forInfoDictionaryKey: "KitapAIDefaultAPIURL") as? String
        return value?.isEmpty == false ? value! : "https://makine.tailnet.ts.net"
    }

    @Published var apiURL: String {
        didSet { UserDefaults.standard.set(apiURL, forKey: Keys.apiURL) }
    }

    @Published var apiKey: String {
        didSet { UserDefaults.standard.set(apiKey, forKey: Keys.apiKey) }
    }

    /// Okunmuş kitaplar; sunucuya `exclude_work_keys` olarak gönderilir.
    @Published private(set) var readKeys: [String] {
        didSet { UserDefaults.standard.set(readKeys, forKey: Keys.read) }
    }

    init() {
        let defaults = UserDefaults.standard
        apiURL = defaults.string(forKey: Keys.apiURL) ?? Settings.defaultURL
        apiKey = defaults.string(forKey: Keys.apiKey) ?? ""
        readKeys = defaults.stringArray(forKey: Keys.read) ?? []
    }

    func isRead(_ workKey: String) -> Bool {
        readKeys.contains(workKey)
    }

    func toggleRead(_ workKey: String) {
        if let index = readKeys.firstIndex(of: workKey) {
            readKeys.remove(at: index)
        } else {
            readKeys.append(workKey)
        }
    }

    func clearRead() {
        readKeys = []
    }
}
