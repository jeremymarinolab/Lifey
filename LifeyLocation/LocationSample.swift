import Foundation

struct LocationSample: Codable, Identifiable, Hashable {
    let id: UUID
    let latitude: Double
    let longitude: Double
    let accuracyMeters: Double
    let capturedAt: Date
}

@MainActor
final class SampleQueue: ObservableObject {
    static let shared = SampleQueue()
    @Published private(set) var samples: [LocationSample] = []
    private let fileURL: URL

    private init() {
        let directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        fileURL = directory.appendingPathComponent("lifey-location-queue.json")
        samples = (try? JSONDecoder().decode([LocationSample].self, from: Data(contentsOf: fileURL))) ?? []
    }

    func append(_ sample: LocationSample) {
        samples.append(sample)
        samples = Array(samples.suffix(20_000))
        persist()
    }

    func remove(ids: Set<UUID>) {
        samples.removeAll { ids.contains($0.id) }
        persist()
    }

    private func persist() {
        guard let data = try? JSONEncoder().encode(samples) else { return }
        try? data.write(to: fileURL, options: .atomic)
    }
}
