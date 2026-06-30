import CoreLocation
import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var tracker: LocationTracker
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            List {
                Section("Tracking") {
                    Toggle("Automatic location tracking", isOn: Binding(get: { tracker.isTracking }, set: tracker.setTracking))
                    LabeledContent("Permission", value: permissionText)
                    LabeledContent("Pending points", value: "\(SampleQueue.shared.samples.count)")
                    LabeledContent("Sync", value: tracker.lastSyncMessage)
                }
                Section("Latest location") {
                    if let sample = tracker.lastSample {
                        Text(sample.capturedAt.formatted(date: .abbreviated, time: .shortened))
                        Text("\(sample.latitude.formatted(.number.precision(.fractionLength(5)))), \(sample.longitude.formatted(.number.precision(.fractionLength(5))))")
                            .font(.caption.monospaced())
                    } else {
                        Text("No location captured yet.")
                            .foregroundStyle(.secondary)
                    }
                }
                Section {
                    Button("Capture and sync now") { tracker.requestLocationNow() }
                    Button("Retry queued points") { Task { await tracker.flush() } }
                }
            }
            .navigationTitle("Lifey Location")
            .toolbar {
                Button { showSettings = true } label: {
                    Label("Settings", systemImage: "gear")
                }
            }
            .sheet(isPresented: $showSettings) { SettingsView() }
        }
    }

    private var permissionText: String {
        switch tracker.authorization {
        case .authorizedAlways: return "Always allowed"
        case .authorizedWhenInUse: return "Change to Always Allow"
        case .denied, .restricted: return "Blocked"
        default: return "Not requested"
        }
    }
}

private struct SettingsView: View {
    @EnvironmentObject private var tracker: LocationTracker
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            Form {
                Section("Lifey connection") {
                    TextField("http://your-mac.tailnet.ts.net:4173", text: $tracker.serverURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                    SecureField("Collector token", text: $tracker.token)
                }
                Section {
                    Text("Use your Mac's Tailscale DNS name. The app retains unsent points and retries automatically when the server returns.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Connection")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { tracker.saveConnection(); dismiss() } }
            }
        }
    }
}
