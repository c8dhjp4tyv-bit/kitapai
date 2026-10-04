import Foundation

/// Sunucudan dönen hatayı kullanıcıya gösterilebilir Türkçe mesaja çevirir.
enum ApiError: Error, LocalizedError {
    case network(String)
    case timeout
    case unauthorized
    case server(status: Int, body: ErrorResponse?)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .network:
            return "Sunucuya ulaşılamadı. Tailscale bağlı mı, sunucu çalışıyor mu?"
        case .timeout:
            return "İstek zaman aşımına uğradı."
        case .unauthorized:
            return "API anahtarı geçersiz."
        case let .server(status, body):
            if body?.error == "katalog_yok" { return "Sunucuda katalog kurulu değil." }
            if status == 503 { return "Sunucu şu an meşgul, birkaç saniye sonra tekrar dene." }
            return body?.detail ?? "Sunucu hatası (\(status))."
        case let .decoding(detail):
            return "Yanıt çözümlenemedi: \(detail)"
        }
    }
}

/// kitap.ai HTTP istemcisi.
struct ApiClient: Sendable {
    let baseURL: URL
    let apiKey: String

    /// Model üretimi uzun sürebildiği için zaman aşımı geniş tutulur.
    private static let timeout: TimeInterval = 120

    init?(base: String, apiKey: String = "") {
        guard let url = URL(string: base.trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))) else { return nil }
        self.baseURL = url
        self.apiKey = apiKey
    }

    private func request(_ path: String, method: String = "GET", body: Data? = nil) -> URLRequest {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.timeoutInterval = Self.timeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !apiKey.isEmpty {
            request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        }
        request.httpBody = body
        return request
    }

    private func send<T: Decodable>(_ request: URLRequest, as type: T.Type) async throws -> T {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch let error as URLError where error.code == .timedOut {
            throw ApiError.timeout
        } catch {
            throw ApiError.network(error.localizedDescription)
        }

        guard let http = response as? HTTPURLResponse else {
            throw ApiError.network("geçersiz yanıt")
        }
        guard (200..<300).contains(http.statusCode) else {
            if http.statusCode == 401 { throw ApiError.unauthorized }
            let body = try? JSONDecoder().decode(ErrorResponse.self, from: data)
            throw ApiError.server(status: http.statusCode, body: body)
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw ApiError.decoding(String(describing: error))
        }
    }

    func taxonomy() async throws -> TaxonomyResponse {
        try await send(request("api/taxonomy"), as: TaxonomyResponse.self)
    }

    func health() async throws -> HealthResponse {
        try await send(request("health"), as: HealthResponse.self)
    }

    func recommend(_ body: RecommendRequest) async throws -> RecommendResponse {
        let payload = try JSONEncoder().encode(body)
        return try await send(
            request("api/recommend", method: "POST", body: payload),
            as: RecommendResponse.self
        )
    }

    func similar(workKey: String, limit: Int = 6) async throws -> SearchResponse {
        let id = workKey.replacingOccurrences(of: "/works/", with: "")
        return try await send(request("api/similar/\(id)?limit=\(limit)"), as: SearchResponse.self)
    }
}
