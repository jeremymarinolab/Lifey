import CoreLocation
import Foundation

private enum TrackerActivity: Equatable {
    case idle
    case capturing
    case syncing
}

@MainActor
final class LocationTracker: NSObject, ObservableObject {
    static let shared = LocationTracker()
    @Published private(set) var isTracking = UserDefaults.standard.bool(forKey: "trackingEnabled")
    @Published private(set) var lastSample: LocationSample?
    @Published private(set) var lastSyncMessage = "Not synced yet"
    @Published private(set) var isCapturing = false
    @Published private(set) var isSyncing = false
    @Published private(set) var pendingCount = SampleQueue.shared.samples.count
    @Published var serverURL = UserDefaults.standard.string(forKey: "serverURL") ?? ""
    @Published var token = SecureStore.value(for: "collectorToken")
    @Published private(set) var authorization: CLAuthorizationStatus
    @Published private(set) var accuracyAuthorization: CLAccuracyAuthorization
    @Published private(set) var lastLocationDetail = "No location fix yet"

    private let manager = CLLocationManager()
    private let queue = SampleQueue.shared
    private var managerConfigured = false
    private var captureAfterAuthorization = false
    private var captureTimeoutTask: Task<Void, Never>?
    private var captureEscalationTask: Task<Void, Never>?
    private var activity: TrackerActivity = .idle
    private var didResumeAfterLaunch = false
    private let captureTimeoutSeconds: UInt64 = 45

    private override init() {
        authorization = manager.authorizationStatus
        accuracyAuthorization = manager.accuracyAuthorization
        super.init()
        lastSample = queue.samples.last
    }

    private func refreshPendingCount() {
        pendingCount = queue.samples.count
    }

    private func setActivity(_ next: TrackerActivity) {
        activity = next
        isCapturing = next == .capturing
        isSyncing = next == .syncing
    }

    private func finishCapturing(_ message: String? = nil) {
        captureTimeoutTask?.cancel()
        captureTimeoutTask = nil
        captureEscalationTask?.cancel()
        captureEscalationTask = nil
        captureAfterAuthorization = false
        setActivity(.idle)
        restoreLocationMode()
        if let message { lastSyncMessage = message }
    }

    private func startCaptureTimeout() {
        captureTimeoutTask?.cancel()
        captureTimeoutTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 45_000_000_000)
            await MainActor.run {
                guard let self, self.isCapturing else { return }
                if let cached = self.recentCachedLocation(maxAge: 600) {
                    self.acceptLocation(cached, source: "cached")
                    return
                }
                self.finishCapturing("Location timed out after \(self.captureTimeoutSeconds)s. iOS did not return a GPS/Wi-Fi fix.")
            }
        }
    }

    private func startCaptureEscalation() {
        captureEscalationTask?.cancel()
        captureEscalationTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            await MainActor.run {
                guard let self, self.isCapturing else { return }
                self.applyCaptureLocationSettings()
                self.manager.startUpdatingLocation()
                self.lastSyncMessage = "Still waiting; using active location updates..."
            }
        }
    }

    private func configureManagerIfNeeded() {
        guard !managerConfigured else { return }
        manager.delegate = self
        manager.activityType = .otherNavigation
        applySteadyLocationSettings()
        managerConfigured = true
    }

    private func applySteadyLocationSettings() {
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        manager.distanceFilter = 50
        manager.pausesLocationUpdatesAutomatically = true
        manager.allowsBackgroundLocationUpdates = true
    }

    private func applyOneShotLocationSettings() {
        manager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
        manager.distanceFilter = kCLDistanceFilterNone
        manager.pausesLocationUpdatesAutomatically = true
        manager.allowsBackgroundLocationUpdates = true
    }

    private func applyCaptureLocationSettings() {
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.distanceFilter = kCLDistanceFilterNone
        manager.pausesLocationUpdatesAutomatically = false
        manager.allowsBackgroundLocationUpdates = true
    }

    private func restoreLocationMode() {
        applySteadyLocationSettings()
        if isTracking && (authorization == .authorizedAlways || authorization == .authorizedWhenInUse) {
            beginUpdates()
        } else {
            manager.stopUpdatingLocation()
        }
    }

    private func recentCachedLocation(maxAge: TimeInterval) -> CLLocation? {
        guard let location = manager.location else { return nil }
        let age = abs(location.timestamp.timeIntervalSinceNow)
        guard age <= maxAge, location.horizontalAccuracy >= 0 else { return nil }
        return location
    }

    private func describe(_ location: CLLocation, source: String) -> String {
        let age = max(0, Int(abs(location.timestamp.timeIntervalSinceNow)))
        let accuracy = Int(location.horizontalAccuracy.rounded())
        return "\(source.capitalized) fix: \(accuracy)m accuracy, \(age)s old"
    }

    private func acceptLocation(_ location: CLLocation, source: String) {
        let sample = LocationSample(
            id: UUID(),
            latitude: location.coordinate.latitude,
            longitude: location.coordinate.longitude,
            accuracyMeters: location.horizontalAccuracy,
            capturedAt: location.timestamp
        )
        queue.append(sample)
        refreshPendingCount()
        lastSample = sample
        lastLocationDetail = describe(location, source: source)
        finishCapturing()
        lastSyncMessage = "Captured \(source) point; syncing..."
        Task { await flush() }
    }

    func resumeAfterLaunch() {
        guard !didResumeAfterLaunch else { return }
        didResumeAfterLaunch = true
        Task {
            await queue.loadIfNeeded()
            refreshPendingCount()
            lastSample = queue.samples.last
            if pendingCount > 0 {
                lastSyncMessage = "\(pendingCount) queued point\(pendingCount == 1 ? "" : "s") waiting to sync."
            } else {
                lastSyncMessage = "Ready."
            }
            startTrackingIfAllowed()
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            guard !isCapturing, !isSyncing, pendingCount > 0 else { return }
            await flush()
        }
    }

    private func startTrackingIfAllowed() {
        if isTracking {
            configureManagerIfNeeded()
            if authorization == .authorizedAlways || authorization == .authorizedWhenInUse {
                beginUpdates()
            } else if authorization == .notDetermined {
                lastSyncMessage = "Ready. Enable tracking to request location permission."
            }
        }
    }

    func saveConnection() {
        UserDefaults.standard.set(serverURL.trimmingCharacters(in: .whitespacesAndNewlines), forKey: "serverURL")
        SecureStore.set(token.trimmingCharacters(in: .whitespacesAndNewlines), for: "collectorToken")
    }

    func setTracking(_ enabled: Bool) {
        isTracking = enabled
        UserDefaults.standard.set(enabled, forKey: "trackingEnabled")
        configureManagerIfNeeded()
        guard enabled else {
            manager.stopUpdatingLocation()
            manager.stopMonitoringSignificantLocationChanges()
            return
        }
        if authorization == .notDetermined { manager.requestAlwaysAuthorization() }
        else { beginUpdates() }
    }

    func captureAndSyncNow() {
        saveConnection()
        configureManagerIfNeeded()
        switch authorization {
        case .denied, .restricted:
            lastSyncMessage = "Location permission is blocked. Enable it in iPhone Settings."
            return
        case .notDetermined:
            captureAfterAuthorization = true
            setActivity(.capturing)
            startCaptureTimeout()
            lastSyncMessage = "Requesting location permission..."
            manager.requestAlwaysAuthorization()
            return
        default:
            break
        }
        setActivity(.capturing)
        lastSyncMessage = "Requesting current location..."
        if let cached = recentCachedLocation(maxAge: 120) {
            lastLocationDetail = describe(cached, source: "cached")
            lastSyncMessage = "Using recent iOS location; syncing..."
            acceptLocation(cached, source: "cached")
            return
        }
        applyOneShotLocationSettings()
        startCaptureTimeout()
        startCaptureEscalation()
        manager.requestLocation()
    }

    func cancelCurrentAction() {
        if isCapturing {
            finishCapturing("Capture cancelled.")
        }
    }

    private func beginUpdates() {
        configureManagerIfNeeded()
        manager.startMonitoringSignificantLocationChanges()
        manager.startUpdatingLocation()
    }

    func flush() async {
        guard !isSyncing else { return }
        saveConnection()
        let base = serverURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard !base.isEmpty else {
            isSyncing = false
            lastSyncMessage = "Add your Lifey server URL."
            return
        }
        guard !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            isSyncing = false
            lastSyncMessage = "Add your collector token."
            return
        }
        guard let url = URL(string: base + "/api/location/mobile/ingest"), url.scheme != nil, url.host != nil else {
            isSyncing = false
            lastSyncMessage = "Server URL is invalid. Include http:// and port 4173."
            return
        }
        let batch = Array(queue.samples.prefix(250))
        guard !batch.isEmpty else {
            isSyncing = false
            lastSyncMessage = "No queued points to sync. Capture a point first."
            return
        }
        struct Payload: Encodable { let samples: [LocationSample] }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        guard let body = try? encoder.encode(Payload(samples: batch)) else {
            isSyncing = false
            lastSyncMessage = "Could not prepare the location batch."
            return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.httpBody = body
        request.timeoutInterval = 20
        setActivity(.syncing)
        lastSyncMessage = "Syncing \(batch.count) queued point\(batch.count == 1 ? "" : "s")..."
        defer { setActivity(.idle) }
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                let serverMessage = (try? JSONDecoder().decode(ServerError.self, from: data).error) ?? "HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)"
                lastSyncMessage = "Sync failed: \(serverMessage)"
                return
            }
            queue.remove(ids: Set(batch.map(\.id)))
            refreshPendingCount()
            lastSyncMessage = "Synced \(batch.count) point\(batch.count == 1 ? "" : "s")"
        } catch {
            lastSyncMessage = networkMessage(for: error)
        }
    }

    private func networkMessage(for error: Error) -> String {
        guard let urlError = error as? URLError else {
            return "Sync failed: \(error.localizedDescription)"
        }
        switch urlError.code {
        case .cannotFindHost:
            return "Sync failed: Mac host not found. Check the Tailscale URL."
        case .cannotConnectToHost, .networkConnectionLost:
            return "Sync failed: cannot reach Lifey on port 4173."
        case .timedOut:
            return "Sync timed out. Check that Lifey is running on the Mac."
        case .notConnectedToInternet:
            return "Sync failed: iPhone is offline."
        case .appTransportSecurityRequiresSecureConnection:
            return "Sync blocked by iOS network security."
        default:
            return "Sync failed: \(urlError.localizedDescription)"
        }
    }
}

private struct ServerError: Decodable {
    let error: String
}

extension LocationTracker: CLLocationManagerDelegate {
    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        Task { @MainActor in
            authorization = manager.authorizationStatus
            accuracyAuthorization = manager.accuracyAuthorization
            if captureAfterAuthorization {
                switch authorization {
                case .authorizedAlways, .authorizedWhenInUse:
                    captureAfterAuthorization = false
                    lastSyncMessage = "Permission granted; requesting current location..."
                    applyOneShotLocationSettings()
                    startCaptureTimeout()
                    startCaptureEscalation()
                    manager.requestLocation()
                case .denied, .restricted:
                    finishCapturing("Location permission is blocked. Enable it in iPhone Settings.")
                default:
                    break
                }
            }
            if isTracking && authorization == .authorizedAlways { beginUpdates() }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last, location.horizontalAccuracy >= 0 else { return }
        Task { @MainActor in
            lastLocationDetail = describe(location, source: "live")
            if isCapturing {
                acceptLocation(location, source: "live")
                return
            }
            let sample = LocationSample(id: UUID(), latitude: location.coordinate.latitude, longitude: location.coordinate.longitude, accuracyMeters: location.horizontalAccuracy, capturedAt: location.timestamp)
            queue.append(sample)
            refreshPendingCount()
            lastSample = sample
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in
            lastLocationDetail = "Location error: \(error.localizedDescription)"
            if let cached = recentCachedLocation(maxAge: 600), isCapturing {
                acceptLocation(cached, source: "cached")
                return
            }
            finishCapturing("Location error: \(error.localizedDescription)")
        }
    }
}
