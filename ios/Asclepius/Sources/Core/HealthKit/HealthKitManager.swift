import BackgroundTasks
import Foundation
import HealthKit
import Observation

/// Reads HealthKit, aggregates per local calendar day, and pushes the result
/// to POST /api/sync/healthkit.
///
/// Sync strategy:
/// - First run pulls the trailing 2 years of daily aggregates.
/// - Later runs are incremental from the last synced day, always re-syncing a
///   trailing 7-day overlap so late-arriving samples (watch syncs, overnight
///   sleep) are corrected.
/// - Uploads go in batches of ≤120 days.
/// - Background: HKObserverQuery + background delivery for steps/heart/sleep/
///   workouts, plus BGAppRefresh + BGProcessing tasks, plus a sync whenever
///   the app becomes active.
@MainActor
@Observable
final class HealthKitManager {
    static let shared = HealthKitManager()

    private let store = HKHealthStore()
    private let api = APIClient.shared
    private var observersStarted = false

    // Observable sync state for Settings and onboarding UI.
    private(set) var isSyncing = false
    private(set) var syncProgress: Double = 0
    private(set) var lastError: String?

    var isAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    /// True once the user has been through the permission sheet.
    private(set) var isEnabled: Bool = UserDefaults.standard.bool(forKey: DefaultsKey.healthKitEnabled)

    var lastSyncDate: Date? {
        get {
            let t = UserDefaults.standard.double(forKey: DefaultsKey.lastSyncDate)
            return t > 0 ? Date(timeIntervalSince1970: t) : nil
        }
        set {
            UserDefaults.standard.set(newValue?.timeIntervalSince1970 ?? 0,
                                      forKey: DefaultsKey.lastSyncDate)
        }
    }

    private var lastSyncedDay: String? {
        get { UserDefaults.standard.string(forKey: DefaultsKey.lastSyncedDay) }
        set { UserDefaults.standard.set(newValue, forKey: DefaultsKey.lastSyncedDay) }
    }

    // MARK: - Authorization

    /// Presents the HealthKit permission sheet for every type we read.
    /// Read-authorization status is intentionally opaque in HealthKit, so a
    /// completed request counts as enabled.
    func requestAuthorization() async -> Bool {
        guard isAvailable else { return false }
        do {
            try await store.requestAuthorization(toShare: [], read: HealthKitCatalog.readTypes)
            isEnabled = true
            UserDefaults.standard.set(true, forKey: DefaultsKey.healthKitEnabled)
            return true
        } catch {
            lastError = error.localizedDescription
            return false
        }
    }

    func resetSyncState() {
        let defaults = UserDefaults.standard
        defaults.removeObject(forKey: DefaultsKey.lastSyncedDay)
        defaults.removeObject(forKey: DefaultsKey.lastSyncDate)
        defaults.removeObject(forKey: DefaultsKey.healthKitEnabled)
        isEnabled = false
        syncProgress = 0
    }

    // MARK: - Sync pipeline

    /// Runs a full or incremental sync. Safe to call repeatedly; overlapping
    /// calls are coalesced.
    func syncNow(fullHistory: Bool = false) async {
        guard isAvailable, isEnabled, !isSyncing else { return }
        isSyncing = true
        syncProgress = 0
        lastError = nil
        defer { isSyncing = false }

        let calendar = Calendar.current
        let today = calendar.startOfDay(for: Date())
        guard let endExclusive = calendar.date(byAdding: .day, value: 1, to: today) else { return }

        var start: Date
        if !fullHistory,
           let lastDay = lastSyncedDay,
           let lastDate = Day.date(from: lastDay) {
            start = calendar.date(byAdding: .day,
                                  value: -AppConfig.resyncOverlapDays,
                                  to: calendar.startOfDay(for: lastDate)) ?? today
        } else {
            start = calendar.date(byAdding: .day,
                                  value: -AppConfig.initialSyncDays,
                                  to: today) ?? today
        }
        if start > today { start = today }

        let totalDays = max(1, calendar.dateComponents([.day], from: start, to: endExclusive).day ?? 1)
        var processedDays = 0
        var cursor = start

        while cursor < endExclusive {
            let proposedEnd = calendar.date(byAdding: .day, value: AppConfig.syncBatchDays, to: cursor) ?? endExclusive
            let chunkEnd = min(proposedEnd, endExclusive)
            do {
                let payload = await collectPayload(start: cursor, end: chunkEnd)
                if !payload.isEmpty {
                    _ = try await api.syncHealthKit(payload)
                }
                if let lastDayOfChunk = calendar.date(byAdding: .day, value: -1, to: chunkEnd) {
                    lastSyncedDay = Day.string(from: lastDayOfChunk)
                }
            } catch {
                lastError = (error as? APIError)?.errorDescription ?? error.localizedDescription
                return
            }
            processedDays += calendar.dateComponents([.day], from: cursor, to: chunkEnd).day ?? 0
            syncProgress = min(1, Double(processedDays) / Double(totalDays))
            cursor = chunkEnd
        }

        syncProgress = 1
        lastSyncDate = Date()
    }

    /// Gathers all metric/sleep/workout aggregates for [start, end).
    private func collectPayload(start: Date, end: Date) async -> HealthSyncPayload {
        var metrics: [MetricSample] = []
        for metric in HealthKitCatalog.quantityMetrics {
            let samples = await collectQuantity(metric, start: start, end: end)
            metrics.append(contentsOf: samples)
        }
        let sleep = await collectSleep(start: start, end: end)
        let workouts = await collectWorkouts(start: start, end: end)
        return HealthSyncPayload(metrics: metrics, sleep: sleep, workouts: workouts)
    }

    // MARK: - Quantity metrics

    private func collectQuantity(
        _ metric: SyncedQuantityMetric,
        start: Date,
        end: Date
    ) async -> [MetricSample] {
        guard let type = metric.quantityType else { return [] }
        let predicate = HKQuery.predicateForSamples(withStart: start, end: end,
                                                    options: .strictStartDate)
        let anchor = Calendar.current.startOfDay(for: start)

        return await withCheckedContinuation { continuation in
            let query = HKStatisticsCollectionQuery(
                quantityType: type,
                quantitySamplePredicate: predicate,
                options: metric.aggregation.statisticsOptions,
                anchorDate: anchor,
                intervalComponents: DateComponents(day: 1))
            query.initialResultsHandler = { _, collection, _ in
                var samples: [MetricSample] = []
                collection?.enumerateStatistics(from: start, to: end.addingTimeInterval(-1)) { stats, _ in
                    if let sample = Self.sample(from: stats, metric: metric) {
                        samples.append(sample)
                    }
                }
                continuation.resume(returning: samples)
            }
            self.store.execute(query)
        }
    }

    private nonisolated static func sample(
        from stats: HKStatistics,
        metric: SyncedQuantityMetric
    ) -> MetricSample? {
        let day = Day.string(from: stats.startDate)
        switch metric.aggregation {
        case .sum:
            guard let sum = stats.sumQuantity() else { return nil }
            let value = sum.doubleValue(for: metric.unit) * metric.scale
            guard value > 0 else { return nil }
            return MetricSample(metric: metric.key, date: day, value: value,
                                unit: metric.unitLabel)
        case .average(let includeMinMax):
            guard let avg = stats.averageQuantity() else { return nil }
            var sample = MetricSample(
                metric: metric.key, date: day,
                value: avg.doubleValue(for: metric.unit) * metric.scale,
                unit: metric.unitLabel)
            if includeMinMax {
                if let minQ = stats.minimumQuantity() {
                    sample.min = minQ.doubleValue(for: metric.unit) * metric.scale
                }
                if let maxQ = stats.maximumQuantity() {
                    sample.max = maxQ.doubleValue(for: metric.unit) * metric.scale
                }
            }
            return sample
        }
    }

    // MARK: - Sleep

    private struct NightAggregate {
        var asleepUnspecified = 0.0
        var core = 0.0
        var deep = 0.0
        var rem = 0.0
        var inBed = 0.0
        var awake = 0.0

        var asleepTotal: Double { asleepUnspecified + core + deep + rem }
    }

    /// Buckets sleepAnalysis samples into nights. A night is attributed to
    /// the local calendar day the sleep ENDS on, matching the backend.
    private func collectSleep(start: Date, end: Date) async -> [SleepNightPayload] {
        guard let type = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) else { return [] }
        let samples: [HKCategorySample] = await fetchSamples(type: type, start: start, end: end)

        var nights: [String: NightAggregate] = [:]
        for sample in samples {
            guard let value = HKCategoryValueSleepAnalysis(rawValue: sample.value) else { continue }
            let day = Day.string(from: sample.endDate)
            let hours = sample.endDate.timeIntervalSince(sample.startDate) / 3600
            guard hours > 0 else { continue }
            var night = nights[day] ?? NightAggregate()
            switch value {
            case .inBed:
                night.inBed += hours
            case .awake:
                night.awake += hours
            case .asleepCore:
                night.core += hours
            case .asleepDeep:
                night.deep += hours
            case .asleepREM:
                night.rem += hours
            case .asleepUnspecified:
                night.asleepUnspecified += hours
            @unknown default:
                night.asleepUnspecified += hours
            }
            nights[day] = night
        }

        return nights
            .filter { $0.value.asleepTotal > 0 || $0.value.inBed > 0 }
            .sorted { $0.key < $1.key }
            .map { day, night in
                SleepNightPayload(
                    date: day,
                    asleepHours: round100(night.asleepTotal),
                    inBedHours: night.inBed > 0 ? round100(night.inBed) : nil,
                    remHours: night.rem > 0 ? round100(night.rem) : nil,
                    deepHours: night.deep > 0 ? round100(night.deep) : nil,
                    coreHours: night.core > 0 ? round100(night.core) : nil,
                    awakeHours: night.awake > 0 ? round100(night.awake) : nil)
            }
    }

    private nonisolated func round100(_ value: Double) -> Double {
        (value * 100).rounded() / 100
    }

    // MARK: - Workouts

    private func collectWorkouts(start: Date, end: Date) async -> [WorkoutSample] {
        let workouts: [HKWorkout] = await fetchSamples(
            type: HKObjectType.workoutType(), start: start, end: end)
        return workouts.map { workout in
            let energy = workout.statistics(for: HKQuantityType(.activeEnergyBurned))?
                .sumQuantity()?
                .doubleValue(for: .kilocalorie())
            let distanceKm = workout.totalDistance?.doubleValue(for: .meterUnit(with: .kilo))
            return WorkoutSample(
                externalId: workout.uuid.uuidString,
                date: Day.string(from: workout.endDate),
                activity: HealthKitCatalog.activityName(for: workout.workoutActivityType),
                durationMin: round100(workout.duration / 60),
                distanceKm: distanceKm.map { round100($0) },
                energyKcal: energy.map { round100($0) })
        }
    }

    private func fetchSamples<T: HKSample>(type: HKSampleType, start: Date, end: Date) async -> [T] {
        let predicate = HKQuery.predicateForSamples(withStart: start, end: end, options: [])
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: true)
        return await withCheckedContinuation { continuation in
            let query = HKSampleQuery(
                sampleType: type,
                predicate: predicate,
                limit: HKObjectQueryNoLimit,
                sortDescriptors: [sort]
            ) { _, samples, _ in
                continuation.resume(returning: (samples as? [T]) ?? [])
            }
            self.store.execute(query)
        }
    }

    // MARK: - Background delivery

    /// Starts long-lived observer queries so new samples trigger a sync even
    /// when the app is backgrounded. Call once per launch after sign-in.
    func startObserving() {
        guard isAvailable, isEnabled, !observersStarted else { return }
        observersStarted = true
        for type in HealthKitCatalog.observedTypes {
            let query = HKObserverQuery(sampleType: type, predicate: nil) { _, completion, _ in
                Task { @MainActor in
                    await HealthKitManager.shared.syncNow()
                    completion()
                }
            }
            store.execute(query)
            store.enableBackgroundDelivery(for: type, frequency: .hourly) { _, _ in }
        }
    }

    // MARK: - BGTaskScheduler

    /// Must be called before the app finishes launching (AppDelegate).
    nonisolated static func registerBackgroundTasks() {
        BGTaskScheduler.shared.register(
            forTaskWithIdentifier: AppConfig.backgroundRefreshTaskID, using: nil
        ) { task in
            Self.run(task)
        }
        BGTaskScheduler.shared.register(
            forTaskWithIdentifier: AppConfig.backgroundSyncTaskID, using: nil
        ) { task in
            Self.run(task)
        }
    }

    private nonisolated static func run(_ task: BGTask) {
        let work = Task { @MainActor in
            HealthKitManager.shared.scheduleBackgroundTasks()
            await HealthKitManager.shared.syncNow()
            task.setTaskCompleted(success: true)
        }
        task.expirationHandler = {
            work.cancel()
            task.setTaskCompleted(success: false)
        }
    }

    /// (Re)schedules both background tasks; call whenever the app backgrounds.
    func scheduleBackgroundTasks() {
        let refresh = BGAppRefreshTaskRequest(identifier: AppConfig.backgroundRefreshTaskID)
        refresh.earliestBeginDate = Date(timeIntervalSinceNow: 4 * 3600)
        try? BGTaskScheduler.shared.submit(refresh)

        let processing = BGProcessingTaskRequest(identifier: AppConfig.backgroundSyncTaskID)
        processing.requiresNetworkConnectivity = true
        processing.requiresExternalPower = false
        processing.earliestBeginDate = Date(timeIntervalSinceNow: 12 * 3600)
        try? BGTaskScheduler.shared.submit(processing)
    }
}
