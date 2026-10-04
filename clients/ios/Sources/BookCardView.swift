import SwiftUI

/// Tek bir öneri kartı.
struct BookCardView: View {
    let recommendation: Recommendation
    let taxonomy: TaxonomyResponse?
    let isRead: Bool
    let onToggleRead: () -> Void
    let onPickSimilar: (Book) -> Void
    let loadSimilar: () async -> [Book]

    @Environment(\.isDarkTheme) private var dark
    @State private var similar: [Book] = []
    @State private var showSimilar = false
    @State private var loadingSimilar = false

    private var book: Book { recommendation.book }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            Text(recommendation.why)
                .font(.subheadline)
                .foregroundStyle(Palette.text(dark))

            if !recommendation.hooks.isEmpty {
                Text(recommendation.hooks.joined(separator: " · "))
                    .font(.caption)
                    .foregroundStyle(Palette.text2(dark))
            }

            if !recommendation.content_notes.isEmpty {
                Text("İçerik uyarısı: " + recommendation.content_notes.joined(separator: ", "))
                    .font(.caption)
                    .foregroundStyle(Palette.danger(dark))
            }

            confidenceBar
            actions

            if showSimilar {
                similarRow
            }
        }
        .padding(18)
        .background(Palette.surface(dark))
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .overlay(
            RoundedRectangle(cornerRadius: 16).stroke(Palette.border(dark), lineWidth: 1)
        )
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 14) {
            cover(url: book.cover_url, width: 70, height: 104)
            VStack(alignment: .leading, spacing: 3) {
                Text("ÖNERİ \(recommendation.rank)")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(Palette.accent(dark))
                Text(book.title)
                    .font(.headline)
                    .foregroundStyle(Palette.text(dark))
                Text(book.metaLine)
                    .font(.caption)
                    .foregroundStyle(Palette.text2(dark))
                tags
            }
            Spacer(minLength: 0)
        }
    }

    private var tags: some View {
        HStack(spacing: 6) {
            ForEach(book.genres.prefix(2), id: \.self) { slug in
                tag(text: label(slug, taxonomy?.genres),
                    background: Palette.tagBg(dark), foreground: Palette.tagText(dark))
            }
            ForEach(book.moods.prefix(1), id: \.self) { slug in
                tag(text: label(slug, taxonomy?.moods),
                    background: Palette.accent(dark).opacity(0.16),
                    foreground: Palette.accent(dark))
            }
        }
        .padding(.top, 4)
    }

    private func tag(text: String, background: Color, foreground: Color) -> some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .background(background)
            .foregroundStyle(foreground)
            .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    private var confidenceBar: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Palette.tagBg(dark))
                Capsule()
                    .fill(Palette.accent(dark))
                    .frame(width: geo.size.width * recommendation.confidence)
            }
        }
        .frame(height: 3)
    }

    private var actions: some View {
        HStack(spacing: 8) {
            if let url = URL(string: book.openlibrary_url) {
                Link("Open Library", destination: url)
                    .font(.footnote)
                    .buttonStyle(.plain)
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(Palette.border(dark)))
                    .foregroundStyle(Palette.text2(dark))
            }

            Button {
                Task { await toggleSimilar() }
            } label: {
                if loadingSimilar {
                    ProgressView().controlSize(.small)
                } else {
                    Text(showSimilar ? "Benzerleri gizle" : "Benzerleri").font(.footnote)
                }
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 12).padding(.vertical, 8)
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Palette.border(dark)))
            .foregroundStyle(Palette.text2(dark))

            Button(action: onToggleRead) {
                Text(isRead ? "✓ Okudum" : "Okudum").font(.footnote)
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 12).padding(.vertical, 8)
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(isRead ? Palette.accent(dark) : Palette.border(dark))
            )
            .foregroundStyle(isRead ? Palette.accent(dark) : Palette.text2(dark))
        }
    }

    private var similarRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(alignment: .top, spacing: 10) {
                ForEach(similar) { item in
                    Button { onPickSimilar(item) } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            cover(url: item.cover_url, width: 84, height: 122)
                            Text(item.title)
                                .font(.caption2)
                                .lineLimit(2)
                                .foregroundStyle(Palette.text2(dark))
                                .frame(width: 84, alignment: .leading)
                        }
                    }
                    .buttonStyle(.plain)
                }
                if similar.isEmpty {
                    Text("Benzer kitap bulunamadı.")
                        .font(.caption)
                        .foregroundStyle(Palette.text2(dark))
                }
            }
        }
    }

    private func cover(url: String?, width: CGFloat, height: CGFloat) -> some View {
        Group {
            if let url, let parsed = URL(string: url) {
                AsyncImage(url: parsed) { image in
                    image.resizable().scaledToFill()
                } placeholder: {
                    Palette.tagBg(dark)
                }
            } else {
                Palette.tagBg(dark).overlay(Text("📖"))
            }
        }
        .frame(width: width, height: height)
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    private func label(_ slug: String, _ entries: [TaxonomyEntry]?) -> String {
        entries?.first { $0.slug == slug }?.label ?? slug
    }

    private func toggleSimilar() async {
        if showSimilar {
            showSimilar = false
            return
        }
        loadingSimilar = true
        similar = await loadSimilar()
        loadingSimilar = false
        showSimilar = true
    }
}
