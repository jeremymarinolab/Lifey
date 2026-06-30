import CoreLocation
import Foundation

@MainActor
final class LocationTracker: NSObject, ObservableObject {
    static let shared = LocationTracker()
    @Published private(set) var isTracking = UserDefaults.standard.bool(forKey: "trackingEnabled")
    @Published private(set) var lastSample: LocationSample?
    @Published private(set) var lastSyncMessage = "Not synced yet"
    @Published var serverURL = UserDefaults.standard.string(forKey: "serverURL") ?? ""
    @Published var token = SecureStore.value(for: "collectorToken")
    @Published private(set) var authorization: CLAuthorizationStatus

    private let manager = CLLocationManager()
    private let queue = SampleQueue.shared

    private override init() {
        authorization = manager.authorizationStatus
        super.init()
        manager.delegate = self
        manager.activityType = .otherNavigation
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        manager.distanceFilter = 50
        manager.pausesLocationUpdatesAutomatically = true
        manager.allowsBackgroundLocationUpdates = true
        lastSample = queue.samples.last
        if isTracking { beginUpdates() }
    }

    func saveConnection() {
        UserDefaults.standard.set(serverURL.trimmingCharacters(in: .whitespacesAndNewlines), forKey: "serverURL")
        SecureStore.set(token.trimmingCharacters(in: .whitespacesAndNewlines), for: "collectorToken")
    }

    func setTracking(_ enabled: Bool) {
        isTracking = enabled
        UserDefaults.standard.set(enabled, forKey: "trackingEnabled")
        guard enabled else {
            manager.stopUpdatingLocation()
            manager.stopMonitoringSignificantLocationChanges()
            return
        }
        if authorization == .notDetermined { manager.requestAlwaysAuthorization() }
        else { beginUpdates() }
    }

    func requestLocationNow() { manager.requestLocation() }

    private func beginUpdates() {
        guard CLLocationManager.locationServicesEnabled() else { return }
        manager.startMonitoringSignificantLocationChanges()
        manager.startUpdatingLocation()
    }

    func flush() async {
        saveConnection()
        let base = serverURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: base + "/api/location/mobile/ingest"), !token.isEmpty else {
            lastSyncMessage = "Add your Lifey server and collector token."
            return
        }
        let batch = Array(queue.samples.prefix(250))
        guard !batch.isEmpty else { return }
        struct Payload: Encodable { let samples: [LocationSample] }
        guard let body = try? JSONEncoder().encode(Payload(samples: batch)) else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.httpBody = body
        request.timeoutInterval = 20
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                lastSyncMessage = "Lifey rejected the batch; it remains queued."
                return
            }
            queue.remove(ids: Set(batch.map(\.id)))
            lastSyncMessage = "Synced \(batch.count) point\(batch.count == 1 ? "" : "s")"
        } catch {
            lastSyncMessage = "Queued — Lifey is unreachable."
        }
    }
}

extension LocationTracker: CLLocationManagerDelegate {
    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        Task { @MainActor in
            authorization = manager.authorizationStatus
            if isTracking && authorization == .authorizedAlways { beginUpdates() }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last, location.horizontalAccuracy >= 0 else { return }
        let sample = LocationSample(id: UUID(), latitude: location.coordinate.latitude, longitude: location.coordinate.longitude, accuracyMeters: location.horizontalAccuracy, capturedAt: location.timestamp)
        Task { @MainActor in
            queue.append(sample)
            lastSample = sample
            await flush()
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in lastSyncMessage = "Location error: \(error.localizedDescription)" }
    }
}
