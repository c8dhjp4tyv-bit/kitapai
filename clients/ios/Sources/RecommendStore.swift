import Foundation

/// Ekranın durumu. Ağ çağrıları burada toplanır; görünümler yalnızca çizer.
@MainActor
final class RecommendStore: ObservableObject {
    @Published var query: String = ""
    @Published var selectedGenres: Set<String> = []
    @Published var selectedMoods: Set<String> = []
    @Published var limit: Int = 3

    @Published private(set) var taxonomy: TaxonomyResponse?
    @Published private(set) var result: RecommendResponse?
    @Published private(set) var health: HealthResponse?
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?

    private let settings: Settings

    init(settings: Settings) {
        self.settings = settings
    }

    private var client: ApiClient? {
        ApiClient(base: settings.apiURL, apiKey: settings.apiKey)
    }

    func label(for slug: String, in entries: [TaxonomyEntry]?) -> String {
        entries?.first { $0.slug == slug }?.label ?? slug
    }

    func connect() async {
        guard let client else {
            errorMessage = "API adresi geçersiz."
            return
        }
        do {
            async let taxonomyTask = client.taxonomy()
            async let healthTask = client.health()
            taxonomy = try await taxonomyTask
            health = try? await healthTask
            errorMessage = nil
        } catch {
            errorMessage = (error as? ApiError)?.errorDescription ?? error.localizedDescription
        }
    }

    func recommend(overrideQuery: String? = nil) async {
        guard let client else {
            errorMessage = "API adresi geçersiz."
            return
        }
        if let overrideQuery { query = overrideQuery }

        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        var request = RecommendRequest()
        request.query = query
        request.genres = Array(selectedGenres)
        request.moods = Array(selectedMoods)
        request.exclude_work_keys = settings.readKeys
        request.limit = limit

        do {
            result = try await client.recommend(request)
        } catch {
            result = nil
            errorMessage = (error as? ApiError)?.errorDescription ?? error.localizedDescription
        }
    }

    func similar(to book: Book) async -> [Book] {
        guard let client else { return [] }
        return (try? await client.similar(workKey: book.work_key))?.books ?? []
    }

    func toggleGenre(_ slug: String) {
        if selectedGenres.contains(slug) { selectedGenres.remove(slug) } else { selectedGenres.insert(slug) }
    }

    func toggleMood(_ slug: String) {
        if selectedMoods.contains(slug) { selectedMoods.remove(slug) } else { selectedMoods.insert(slug) }
    }
}
