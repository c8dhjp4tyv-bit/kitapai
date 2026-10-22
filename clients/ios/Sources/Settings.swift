import Foundation

/// Sunucu adresi ve okunmuş kitap listesi — `UserDefaults` üzerinde kalıcı.
///
/// iOS'ta düz HTTP varsayılan olarak engellenir (App Transport Security);
/// derleme sırasında gömülen adres HTTPS'tir (örn. serveo tüneli ya da `tailscale serve`).
/// Düz HTTP gerekiyorsa `scripts/patch_plist.py --allow-http` ile istisna tanımlanır.
///
/// `apiKey` davet kodudur: sunucu `X-API-Key` başlığında denetler.
@MainActor
final class Settings: ObservableObject {
    private enum Keys {
        static let apiURL = "kitapai.apiURL"
        static let apiKey = "kitapai.apiKey"
        static let read = "kitapai.read"
        static let inviteExpiry = "kitapai.inviteExpiry"
        static let lastDefaultURL = "kitapai.lastDefaultURL"
    }

    static let codeLength = 24

    /// Harf ve rakam dışını atar, büyük harfe çevirir, 24 haneye kırpar.
    static func normalizeCode(_ raw: String) -> String {
        String(raw.uppercased().filter { $0.isASCII && ($0.isLetter || $0.isNumber) }.prefix(codeLength))
    }

    /// Yazarken tire koyar: ABCDEF-GHJKMN-...
    static func formatCode(_ raw: String) -> String {
        let n = Array(normalizeCode(raw))
        return stride(from: 0, to: n.count, by: 6)
            .map { String(n[$0..<min($0 + 6, n.count)]) }
            .joined(separator: "-")
    }

    /// Derleme sırasında `build.sh --api ...` ile Info.plist'e yazılan adres;
    /// yoksa kullanıcı uygulama içinden girer.
    static var defaultURL: String {
        let value = Bundle.main.object(forInfoDictionaryKey: "KitapAIDefaultAPIURL") as? String
        return value?.isEmpty == false ? value! : "https://kitapai-sunum.serveousercontent.com"
    }

    @Published var apiURL: String {
        didSet { UserDefaults.standard.set(apiURL, forKey: Keys.apiURL) }
    }

    @Published var apiKey: String {
        didSet { UserDefaults.standard.set(apiKey, forKey: Keys.apiKey) }
    }

    /// Davet kodunun bitiş zamanı (epoch saniye); 0 = bilinmiyor.
    @Published var inviteExpiry: Double {
        didSet { UserDefaults.standard.set(inviteExpiry, forKey: Keys.inviteExpiry) }
    }

    /// Kapıda gösterilecek mesaj (örn. "süresi dolmuş"); kod geçerli olunca silinir.
    @Published var inviteNotice: String?

    /// Okunmuş kitaplar; sunucuya `exclude_work_keys` olarak gönderilir.
    @Published private(set) var readKeys: [String] {
        didSet { UserDefaults.standard.set(readKeys, forKey: Keys.read) }
    }

    init() {
        let defaults = UserDefaults.standard
        // Derleme adresi değiştiyse (yeni IPA) eski kayıtlı adres yeni varsayılana yerini bırakır.
        if defaults.string(forKey: Keys.lastDefaultURL) != Settings.defaultURL {
            defaults.removeObject(forKey: Keys.apiURL)
            defaults.set(Settings.defaultURL, forKey: Keys.lastDefaultURL)
        }
        apiURL = defaults.string(forKey: Keys.apiURL) ?? Settings.defaultURL
        apiKey = defaults.string(forKey: Keys.apiKey) ?? ""
        inviteExpiry = defaults.double(forKey: Keys.inviteExpiry)
        readKeys = defaults.stringArray(forKey: Keys.read) ?? []
    }

    func saveInvite(code: String, expiresAt: Double) {
        inviteNotice = nil
        inviteExpiry = expiresAt
        apiKey = code
    }

    /// Kodu siler; ekran davet kapısına döner.
    func clearInvite(notice: String? = nil) {
        apiKey = ""
        inviteExpiry = 0
        inviteNotice = notice
    }

    /// "71 sa 20 dk" / "45 dk"; süre bilinmiyorsa nil.
    var inviteRemaining: String? {
        guard inviteExpiry > 0 else { return nil }
        let seconds = max(0, Int(inviteExpiry - Date().timeIntervalSince1970))
        let hours = seconds / 3600, minutes = (seconds % 3600) / 60
        return hours > 0 ? "\(hours) sa \(minutes) dk" : "\(minutes) dk"
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
