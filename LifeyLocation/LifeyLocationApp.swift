import SwiftUI

@main
struct LifeyLocationApp: App {
    @StateObject private var tracker = LocationTracker.shared

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(tracker)
        }
    }
}
