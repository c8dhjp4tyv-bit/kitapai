import Foundation

/// API sözleşmesi — `src/kitapai/schemas.py` ile birebir aynı.
/// Alan adları sunucuyla aynı olduğu için `CodingKeys` gerekmez; yalnızca
/// snake_case adlar Swift tarafında da korunur.

struct Rating: Codable, Sendable, Hashable {
    let average: Double
    let count: Int
}

struct Book: Codable, Sendable, Hashable, Identifiable {
    let work_key: String
    let title: String
    let subtitle: String?
    let authors: [String]
    let first_published: Int?
    let description: String?
    let genres: [String]
    let moods: [String]
    let subjects: [String]
    let languages: [String]
    let pages: Int?
    let isbns: [String]
    let cover_url: String?
    let openlibrary_url: String
    let rating: Rating?
    let readers: Int?
    let popularity: Double

    var id: String { work_key }

    /// Kart başlığının altındaki tek satırlık künye.
    var metaLine: String {
        var parts: [String] = []
        if !authors.isEmpty { parts.append(authors.joined(separator: ", ")) }
        if let year = first_published { parts.append(String(year)) }
        if let pages { parts.append("\(pages) sayfa") }
        if let rating { parts.append(String(format: "★ %.1f (%d)", rating.average, rating.count)) }
        return parts.joined(separator: " · ")
    }
}

struct Recommendation: Codable, Sendable, Hashable, Identifiable {
    let rank: Int
    let book: Book
    let why: String
    let hooks: [String]
    let content_notes: [String]
    let confidence: Double
    let grounded: Bool
    let match_reasons: [String]

    var id: String { book.work_key }
}

struct ResponseMeta: Codable, Sendable, Hashable {
    let request_id: String
    let model: String
    let engine: String
    let latency_ms: Int
    let retrieved: Int
    let grounded_ratio: Double
    let degraded: Bool
    let notes: [String]
}

struct RecommendResponse: Codable, Sendable, Hashable {
    let recommendations: [Recommendation]
    let followups: [String]
    let meta: ResponseMeta
}

struct SearchResponse: Codable, Sendable, Hashable {
    let books: [Book]
    let total: Int
    let meta: ResponseMeta
}

struct HealthResponse: Codable, Sendable, Hashable {
    let status: String
    let version: String
    let engine: String
    let model: String
    let catalog_books: Int
    let catalog_path: String
    let vectors_loaded: Bool
    let device: String
    let uptime_s: Double
}

struct TaxonomyEntry: Codable, Sendable, Hashable, Identifiable {
    let slug: String
    let label: String
    let description: String

    var id: String { slug }
}

struct TaxonomyResponse: Codable, Sendable, Hashable {
    let genres: [TaxonomyEntry]
    let moods: [TaxonomyEntry]
    let eras: [TaxonomyEntry]
    let lengths: [TaxonomyEntry]
    let audiences: [TaxonomyEntry]
}

struct RecommendRequest: Codable, Sendable {
    var query: String = ""
    var genres: [String] = []
    var moods: [String] = []
    var languages: [String] = []
    var era: String?
    var length: String?
    var audience: String?
    var exclude_work_keys: [String] = []
    var limit: Int = 3
    var strictness: String = "soft"
    var seed: Int?
}

struct ErrorResponse: Codable, Sendable {
    let error: String
    let detail: String?
    let request_id: String?
}
