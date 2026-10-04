import SwiftUI

private let examples = [
    "çölde geçen, ağır olmayan epik bir bilim kurgu",
    "yas ve kayıp üzerine sakin bir roman",
    "metroda okumak için tırnak yediren bir polisiye",
]

struct ContentView: View {
    @EnvironmentObject private var settings: Settings
    @StateObject private var store: RecommendStore
    @Environment(\.colorScheme) private var colorScheme
    @State private var showSettings = false

    init(settings: Settings) {
        _store = StateObject(wrappedValue: RecommendStore(settings: settings))
    }

    private var dark: Bool { colorScheme == .dark }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                if showSettings { settingsCard }
                hero
                formCard
                if store.isLoading { ProgressView().frame(maxWidth: .infinity).padding() }
                if let result = store.result { results(result) }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 48)
        }
        .background(Palette.bg(dark).ignoresSafeArea())
        .environment(\.isDarkTheme, dark)
        .task { await store.connect() }
    }

    // ── başlık ─────────────────────────────────────────────────────────────

    private var header: some View {
        HStack {
            Text("📖 kitap.ai").font(.headline).foregroundStyle(Palette.text(dark))
            Spacer()
            Button {
                showSettings.toggle()
            } label: {
                Text(store.health.map { "\($0.catalog_books) kitap" } ?? "sunucu")
                    .font(.caption)
                    .padding(.horizontal, 12).padding(.vertical, 5)
                    .background(Palette.tagBg(dark))
                    .foregroundStyle(Palette.text2(dark))
                    .clipShape(Capsule())
            }
            .buttonStyle(.plain)
        }
        .padding(.top, 8)
    }

    private var settingsCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("API ADRESİ").font(.caption2.weight(.semibold))
                .foregroundStyle(Palette.text2(dark))
            TextField("https://makine.tailnet.ts.net", text: $settings.apiURL)
                .textFieldStyle(.plain)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                .padding(12)
                .background(Palette.surface2(dark))
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .foregroundStyle(Palette.text(dark))

            Text("iOS düz HTTP'yi engeller. `tailscale serve` ile HTTPS adresi kullan.")
                .font(.caption2)
                .foregroundStyle(Palette.text2(dark))

            if !settings.readKeys.isEmpty {
                Button("Okunmuş listesini temizle (\(settings.readKeys.count))") {
                    settings.clearRead()
                }
                .font(.caption)
                .foregroundStyle(Palette.accent(dark))
            }

            Button {
                Task { await store.connect(); showSettings = false }
            } label: {
                Text("Kaydet ve bağlan")
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity)
                    .padding(13)
                    .background(Palette.accent(dark))
                    .foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            }
            .buttonStyle(.plain)
        }
        .padding(18)
        .background(Palette.surface(dark))
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Palette.border(dark)))
    }

    private var hero: some View {
        VStack(spacing: 8) {
            Text("Sana özel").font(.largeTitle.weight(.bold))
            Text("kitap önerileri")
                .font(.largeTitle.weight(.bold).italic())
                .foregroundStyle(Palette.accent(dark))
            Text("Ne aradığını kendi cümlelerinle yaz.")
                .font(.subheadline)
                .foregroundStyle(Palette.text2(dark))
        }
        .frame(maxWidth: .infinity)
        .foregroundStyle(Palette.text(dark))
        .padding(.top, 16)
    }

    // ── form ───────────────────────────────────────────────────────────────

    private var formCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("NE ARIYORSUN?").font(.caption2.weight(.semibold))
                .foregroundStyle(Palette.text2(dark))

            TextField("Konu, his, durum ya da benzediği kitap…",
                      text: $store.query, axis: .vertical)
                .lineLimit(3...6)
                .textFieldStyle(.plain)
                .padding(12)
                .background(Palette.surface2(dark))
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .foregroundStyle(Palette.text(dark))

            VStack(alignment: .leading, spacing: 6) {
                ForEach(examples, id: \.self) { example in
                    Button { store.query = example } label: {
                        Text(example)
                            .font(.caption)
                            .padding(.horizontal, 12).padding(.vertical, 6)
                            .overlay(Capsule().stroke(Palette.border(dark)))
                            .foregroundStyle(Palette.text2(dark))
                    }
                    .buttonStyle(.plain)
                }
            }

            if let taxonomy = store.taxonomy {
                chipSection("TÜR", entries: taxonomy.genres,
                            selected: store.selectedGenres, toggle: store.toggleGenre)
                chipSection("RUH HALİ", entries: taxonomy.moods,
                            selected: store.selectedMoods, toggle: store.toggleMood)
            }

            if let error = store.errorMessage {
                Text(error).font(.footnote).foregroundStyle(Palette.danger(dark))
            }

            Button {
                Task { await store.recommend() }
            } label: {
                Text(store.isLoading ? "Kitaplık taranıyor…" : "Kitap Öner →")
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity)
                    .padding(15)
                    .background(Palette.accent(dark))
                    .foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            }
            .buttonStyle(.plain)
            .disabled(store.isLoading)

            if !settings.readKeys.isEmpty {
                Text("\(settings.readKeys.count) okunmuş kitap önerilerden çıkarılıyor")
                    .font(.caption2)
                    .foregroundStyle(Palette.text2(dark))
            }
        }
        .padding(18)
        .background(Palette.surface(dark))
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Palette.border(dark)))
    }

    private func chipSection(
        _ title: String,
        entries: [TaxonomyEntry],
        selected: Set<String>,
        toggle: @escaping (String) -> Void
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.caption2.weight(.semibold))
                .foregroundStyle(Palette.text2(dark))
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(entries) { entry in
                        let active = selected.contains(entry.slug)
                        Button { toggle(entry.slug) } label: {
                            Text(entry.label)
                                .font(.footnote)
                                .padding(.horizontal, 13).padding(.vertical, 7)
                                .background(active ? Palette.accent(dark) : Palette.tagBg(dark))
                                .foregroundStyle(active ? .white : Palette.tagText(dark))
                                .clipShape(Capsule())
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.vertical, 1)
            }
        }
    }

    // ── sonuçlar ───────────────────────────────────────────────────────────

    private func results(_ result: RecommendResponse) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                Text("Öneriler").font(.title3.weight(.bold))
                    .foregroundStyle(Palette.text(dark))
                Spacer()
                Text("\(result.meta.retrieved) aday · \(result.meta.latency_ms) ms")
                    .font(.caption2)
                    .foregroundStyle(Palette.text2(dark))
            }

            if result.recommendations.isEmpty {
                Text("Bu kısıtlara uyan kitap bulunamadı. Filtreleri gevşetmeyi dene.")
                    .font(.subheadline)
                    .foregroundStyle(Palette.text2(dark))
            }

            ForEach(result.recommendations) { recommendation in
                BookCardView(
                    recommendation: recommendation,
                    taxonomy: store.taxonomy,
                    isRead: settings.isRead(recommendation.book.work_key),
                    onToggleRead: { settings.toggleRead(recommendation.book.work_key) },
                    onPickSimilar: { book in
                        Task { await store.recommend(overrideQuery: "\(book.title) gibi bir kitap") }
                    },
                    loadSimilar: { await store.similar(to: recommendation.book) }
                )
            }

            ForEach(result.followups, id: \.self) { followup in
                Text(followup)
                    .font(.footnote.italic())
                    .foregroundStyle(Palette.text2(dark))
            }
        }
    }
}
