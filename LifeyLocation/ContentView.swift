import CoreLocation
import SwiftUI
import UIKit

struct ContentView: View {
    @EnvironmentObject private var tracker: LocationTracker
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            List {
                Section("Tracking") {
                    Toggle("Automatic location tracking", isOn: Binding(get: { tracker.isTracking }, set: tracker.setTracking))
                    LabeledContent("Permission", value: permissionText)
                    LabeledContent("Accuracy", value: accuracyText)
                    LabeledContent("Location fix", value: tracker.lastLocationDetail)
                    LabeledContent("Pending points", value: "\(tracker.pendingCount)")
                    LabeledContent("Sync", value: tracker.lastSyncMessage)
                }
                Section("iPhone permission controls") {
                    Button {
                        openAppSettings()
                    } label: {
                        Label("Open Lifey in iPhone Settings", systemImage: "gearshape")
                    }
                    Text("If Lifey does not appear in Settings immediately, reinstall this build once. The included Settings bundle makes iOS create a dedicated Lifey Location page.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
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
                    Button { tracker.captureAndSyncNow() } label: {
                        if tracker.isCapturing {
                            HStack {
                                ProgressView()
                                Text("Capturing location...")
                            }
                        } else if tracker.isSyncing {
                            HStack {
                                ProgressView()
                                Text("Syncing...")
                            }
                        } else {
                            Label("Capture and sync now", systemImage: "location")
                        }
                    }
                    .disabled(tracker.isCapturing || tracker.isSyncing)
                    if tracker.isCapturing {
                        Button("Cancel capture", role: .cancel) {
                            tracker.cancelCurrentAction()
                        }
                    }
                    Button { Task { await tracker.flush() } } label: {
                        if tracker.isSyncing {
                            HStack {
                                ProgressView()
                                Text("Syncing queued points...")
                            }
                        } else {
                            Label("Retry queued points", systemImage: "arrow.clockwise")
                        }
                    }
                    .disabled(tracker.isSyncing)
                }
            }
            .navigationTitle("Lifey Location")
            .onAppear { tracker.resumeAfterLaunch() }
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

    private var accuracyText: String {
        switch tracker.accuracyAuthorization {
        case .fullAccuracy: return "Precise"
        case .reducedAccuracy: return "Reduced"
        @unknown default: return "Unknown"
        }
    }

    private func openAppSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
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
