import Foundation

struct LocationSample: Codable, Identifiable, Hashable {
    let id: UUID
    let latitude: Double
    let longitude: Double
    let accuracyMeters: Double
    let capturedAt: Date
}

private actor SampleStore {
    private let fileURL: URL

    init() {
        let directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        fileURL = directory.appendingPathComponent("lifey-location-queue.json")
    }

    func load() -> [LocationSample] {
        guard let data = try? Data(contentsOf: fileURL) else { return [] }
        return (try? JSONDecoder().decode([LocationSample].self, from: data)) ?? []
    }

    func save(_ samples: [LocationSample]) {
        guard let data = try? JSONEncoder().encode(samples) else { return }
        try? data.write(to: fileURL, options: .atomic)
    }
}

@MainActor
final class SampleQueue: ObservableObject {
    static let shared = SampleQueue()
    @Published private(set) var samples: [LocationSample] = []
    private let store = SampleStore()
    private var didLoad = false
    private var loadTask: Task<[LocationSample], Never>?
    private var saveTask: Task<Void, Never>?

    private init() {}

    func loadIfNeeded() async {
        guard !didLoad else { return }
        if loadTask == nil {
            loadTask = Task { [store] in await store.load() }
        }
        guard let loadTask else { return }
        let loaded = await loadTask.value
        self.loadTask = nil
        didLoad = true
        guard !loaded.isEmpty else { return }
        if samples.isEmpty {
            samples = loaded
            return
        }
        let loadedIDs = Set(loaded.map(\.id))
        samples = (loaded + samples.filter { !loadedIDs.contains($0.id) }).suffixArray(20_000)
    }

    func append(_ sample: LocationSample) {
        guard didLoad else {
            Task {
                await loadIfNeeded()
                append(sample)
            }
            return
        }
        samples.append(sample)
        samples = samples.suffixArray(20_000)
        schedulePersist()
    }

    func remove(ids: Set<UUID>) {
        guard didLoad else {
            Task {
                await loadIfNeeded()
                remove(ids: ids)
            }
            return
        }
        samples.removeAll { ids.contains($0.id) }
        schedulePersist()
    }

    private func schedulePersist() {
        let snapshot = samples
        saveTask?.cancel()
        saveTask = Task { [store, snapshot] in
            try? await Task.sleep(nanoseconds: 350_000_000)
            guard !Task.isCancelled else { return }
            await store.save(snapshot)
        }
    }
}

private extension Array {
    func suffixArray(_ maxLength: Int) -> [Element] {
        Array(suffix(maxLength))
    }
}
