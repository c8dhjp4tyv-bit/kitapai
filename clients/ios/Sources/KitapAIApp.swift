import SwiftUI

@main
struct KitapAIApp: App {
    @StateObject private var settings = Settings()

    var body: some Scene {
        WindowGroup {
            ContentView(settings: settings)
                .environmentObject(settings)
        }
    }
}
