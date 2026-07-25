import Foundation

// MARK: - Sleep

/// One night of sleep. Attributed to the date the sleep ended.
struct SleepNight: Decodable, Identifiable {
    var date: String
    var asleepHours: Double?
    var inBedHours: Double?
    var remHours: Double?
    var deepHours: Double?
    var coreHours: Double?
    var awakeHours: Double?

    var id: String { date }

    enum CodingKeys: String, CodingKey {
        case date
        case asleepHours = "asleep_hours"
        case inBedHours = "in_bed_hours"
        case remHours = "rem_hours"
        case deepHours = "deep_hours"
        case coreHours = "core_hours"
        case awakeHours = "awake_hours"
    }
}

struct SleepSummary: Decodable {
    var available: Bool?
    var windowDays: Int?
    var nightsRecorded: Int?
    var avgAsleepHours: Double?
    var minAsleepHours: Double?
    var maxAsleepHours: Double?
    var consistencyStdHours: Double?
    var avgRemHours: Double?
    var avgDeepHours: Double?
    var latest: SleepNight?
    var trend: Trend?

    enum CodingKeys: String, CodingKey {
        case available, latest, trend
        case windowDays = "window_days"
        case nightsRecorded = "nights_recorded"
        case avgAsleepHours = "avg_asleep_hours"
        case minAsleepHours = "min_asleep_hours"
        case maxAsleepHours = "max_asleep_hours"
        case consistencyStdHours = "consistency_std_hours"
        case avgRemHours = "avg_rem_hours"
        case avgDeepHours = "avg_deep_hours"
    }
}

struct SleepResponse: Decodable {
    var summary: SleepSummary?
    var series: [SleepNight]?
}

/// POST /api/sleep — manual sleep log.
struct NewSleepEntry: Encodable {
    var date: String?
    var asleepHours: Double
    var inBedHours: Double?
    var remHours: Double?
    var deepHours: Double?

    enum CodingKeys: String, CodingKey {
        case date
        case asleepHours = "asleep_hours"
        case inBedHours = "in_bed_hours"
        case remHours = "rem_hours"
        case deepHours = "deep_hours"
    }
}

// MARK: - Body

struct BodyMetric: Decodable, Identifiable {
    var key: String
    var label: String?
    var unit: String?
    var area: String?
    var summary: MetricSummary?
    var series: [MetricPoint]?

    var id: String { key }
}

struct BodyResponse: Decodable {
    var metrics: [BodyMetric]?
}

/// POST /api/body — manual measurement.
struct NewBodyEntry: Encodable {
    var metric: String
    var value: Double
    var date: String?
}

// MARK: - HealthKit sync payloads

/// One daily aggregate for one metric.
struct MetricSample: Encodable {
    var metric: String
    var date: String
    var value: Double
    var min: Double? = nil
    var max: Double? = nil
    var count: Int? = nil
    var unit: String? = nil
}

/// One night of sleep, aggregated from HKCategoryTypeIdentifierSleepAnalysis.
struct SleepNightPayload: Encodable {
    var date: String
    var asleepHours: Double
    var inBedHours: Double?
    var remHours: Double?
    var deepHours: Double?
    var coreHours: Double?
    var awakeHours: Double?

    enum CodingKeys: String, CodingKey {
        case date
        case asleepHours = "asleep_hours"
        case inBedHours = "in_bed_hours"
        case remHours = "rem_hours"
        case deepHours = "deep_hours"
        case coreHours = "core_hours"
        case awakeHours = "awake_hours"
    }
}

/// One HKWorkout, keyed by its UUID so re-syncs upsert instead of duplicating.
struct WorkoutSample: Encodable {
    var externalId: String
    var date: String
    var activity: String
    var durationMin: Double?
    var distanceKm: Double?
    var energyKcal: Double?

    enum CodingKeys: String, CodingKey {
        case date, activity
        case externalId = "external_id"
        case durationMin = "duration_min"
        case distanceKm = "distance_km"
        case energyKcal = "energy_kcal"
    }
}

/// POST /api/sync/healthkit body.
struct HealthSyncPayload: Encodable {
    var metrics: [MetricSample]
    var sleep: [SleepNightPayload]
    var workouts: [WorkoutSample]

    var isEmpty: Bool { metrics.isEmpty && sleep.isEmpty && workouts.isEmpty }
}

struct SyncUpserted: Decodable {
    var metrics: Int?
    var sleep: Int?
    var workouts: Int?
}

struct SyncResponse: Decodable {
    var status: String?
    var upserted: SyncUpserted?
}

// MARK: - Goals

/// A long-term goal, annotated with current value + progress when active.
struct Goal: Decodable, Identifiable {
    var id: Int
    var category: String?
    var label: String?
    var target: Double?
    var baseline: Double?
    var unit: String?
    var direction: String?
    var targetDate: String?
    var status: String?
    var notes: String?
    var createdAt: String?
    var current: Double?
    var progressPct: Double?

    enum CodingKeys: String, CodingKey {
        case id, category, label, target, baseline, unit, direction
        case status, notes, current
        case targetDate = "target_date"
        case createdAt = "created_at"
        case progress
        case progressPct = "progress_pct"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decode(Int.self, forKey: .id)) ?? 0
        category = try? c.decodeIfPresent(String.self, forKey: .category)
        label = try? c.decodeIfPresent(String.self, forKey: .label)
        target = try? c.decodeIfPresent(Double.self, forKey: .target)
        baseline = try? c.decodeIfPresent(Double.self, forKey: .baseline)
        unit = try? c.decodeIfPresent(String.self, forKey: .unit)
        direction = try? c.decodeIfPresent(String.self, forKey: .direction)
        targetDate = try? c.decodeIfPresent(String.self, forKey: .targetDate)
        status = try? c.decodeIfPresent(String.self, forKey: .status)
        notes = try? c.decodeIfPresent(String.self, forKey: .notes)
        createdAt = try? c.decodeIfPresent(String.self, forKey: .createdAt)
        current = try? c.decodeIfPresent(Double.self, forKey: .current)
        // The backend emits `progress`; the published contract calls it
        // `progress_pct`. Accept either.
        progressPct = (try? c.decodeIfPresent(Double.self, forKey: .progress))
            ?? (try? c.decodeIfPresent(Double.self, forKey: .progressPct))
    }
}

struct GoalsResponse: Decodable {
    var goals: [Goal]?
}

struct NewGoal: Encodable {
    var category: String
    var label: String = ""
    var target: Double?
    var baseline: Double?
    var unit: String = ""
    var direction: String = "increase"
    var targetDate: String?
    var notes: String = ""

    enum CodingKeys: String, CodingKey {
        case category, label, target, baseline, unit, direction, notes
        case targetDate = "target_date"
    }
}

struct GoalUpdate: Encodable {
    var label: String? = nil
    var target: Double? = nil
    var baseline: Double? = nil
    var unit: String? = nil
    var direction: String? = nil
    var targetDate: String? = nil
    var status: String? = nil
    var notes: String? = nil

    enum CodingKeys: String, CodingKey {
        case label, target, baseline, unit, direction, status, notes
        case targetDate = "target_date"
    }
}
