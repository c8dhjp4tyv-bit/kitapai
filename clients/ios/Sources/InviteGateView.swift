import SwiftUI

/// Davet kodu ekranı. Doğrulama sunucuda yapılır; kod yalnızca geçerliyse saklanır.
struct InviteGateView: View {
    @EnvironmentObject private var settings: Settings
    @Environment(\.colorScheme) private var colorScheme
    @State private var text = ""
    @State private var error: String?
    @State private var busy = false

    private var dark: Bool { colorScheme == .dark }

    /// Yalnızca harf ve rakam, büyük harf, en çok 24 hane.
    private var normalized: String { Settings.normalizeCode(text) }
    private var ready: Bool { normalized.count == Settings.codeLength }

    var body: some View {
        VStack(spacing: 16) {
            Spacer(minLength: 40)
            VStack(spacing: 14) {
                Text("📖 kitap.ai").font(.headline)
                Text("Davet kodunu gir").font(.title2.weight(.bold))
                Text("Bu sürüm yalnızca davetliler içindir. Sana verilen 24 haneli kodu yaz.")
                    .font(.subheadline)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Palette.text2(dark))

                TextField("XXXXXX-XXXXXX-XXXXXX-XXXXXX", text: Binding(
                    get: { Settings.formatCode(text) },
                    set: { text = $0 }
                ))
                .font(.system(.body, design: .monospaced).weight(.semibold))
                .multilineTextAlignment(.center)
                .textInputAutocapitalization(.characters)
                .autocorrectionDisabled()
                .padding(14)
                .background(Palette.surface2(dark))
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Palette.border(dark)))
                .onSubmit { Task { await submit() } }

                if let message = error ?? settings.inviteNotice {
                    Text(message).font(.footnote).foregroundStyle(Palette.danger(dark))
                        .multilineTextAlignment(.center)
                }

                Button {
                    Task { await submit() }
                } label: {
                    Text(busy ? "Doğrulanıyor…" : "Giriş yap")
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity)
                        .padding(15)
                        .background(Palette.accent(dark).opacity(ready && !busy ? 1 : 0.45))
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain)
                .disabled(!ready || busy)
            }
            .padding(22)
            .background(Palette.surface(dark))
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Palette.border(dark)))
            .foregroundStyle(Palette.text(dark))
            Spacer()
        }
        .padding(.horizontal, 16)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.bg(dark).ignoresSafeArea())
    }

    private func submit() async {
        guard ready, !busy else { return }
        busy = true
        error = nil
        settings.inviteNotice = nil
        defer { busy = false }
        guard let client = ApiClient(base: settings.apiURL) else {
            error = "API adresi geçersiz."
            return
        }
        do {
            let response = try await client.invite(code: normalized)
            settings.saveInvite(code: normalized, expiresAt: response.expires_at)
        } catch {
            self.error = (error as? ApiError)?.errorDescription ?? error.localizedDescription
        }
    }
}
