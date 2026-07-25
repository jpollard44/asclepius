import Foundation

// MARK: - Workouts

struct ExerciseSet: Codable, Identifiable, Equatable {
    var reps: Double?
    var weight: Double?

    // Local identity for SwiftUI editors; never sent to the server.
    var id = UUID()

    enum CodingKeys: String, CodingKey {
        case reps, weight
    }

    init(reps: Double? = nil, weight: Double? = nil) {
        self.reps = reps
        self.weight = weight
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        // Reps/weight may arrive as numbers or numeric strings.
        reps = Self.flexibleNumber(c, .reps)
        weight = Self.flexibleNumber(c, .weight)
    }

    private static func flexibleNumber(_ c: KeyedDecodingContainer<CodingKeys>, _ key: CodingKeys) -> Double? {
        if let d = try? c.decodeIfPresent(Double.self, forKey: key) { return d }
        if let s = try? c.decodeIfPresent(String.self, forKey: key) { return Double(s) }
        return nil
    }
}

struct Exercise: Codable, Identifiable, Equatable {
    var name: String
    var sets: [ExerciseSet]

    var id = UUID()

    enum CodingKeys: String, CodingKey {
        case name, sets
    }

    init(name: String = "", sets: [ExerciseSet] = []) {
        self.name = name
        self.sets = sets
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? "Exercise"
        sets = (try? c.decodeIfPresent([ExerciseSet].self, forKey: .sets)) ?? []
    }
}

struct Workout: Decodable, Identifiable {
    var id: Int
    var date: String?
    var activity: String?
    var type: String?
    var durationMin: Double?
    var distanceKm: Double?
    var energyKcal: Double?
    var exercises: [Exercise]?
    var notes: String?
    var source: String?
    var externalId: String?

    enum CodingKeys: String, CodingKey {
        case id, date, activity, type, exercises, notes, source
        case durationMin = "duration_min"
        case distanceKm = "distance_km"
        case energyKcal = "energy_kcal"
        case externalId = "external_id"
    }

    /// Workouts synced from HealthKit are read-only in the app.
    var isFromHealthKit: Bool {
        if let source, source != "manual" { return true }
        return externalId != nil
    }

    var isStrength: Bool {
        type == "strength" || !(exercises ?? []).isEmpty
    }
}

struct ActivityTally: Decodable, Identifiable {
    var activity: String
    var n: Int?
    var totalMin: Double?
    var totalKm: Double?
    var totalKcal: Double?

    var id: String { activity }

    enum CodingKeys: String, CodingKey {
        case activity, n
        case totalMin = "total_min"
        case totalKm = "total_km"
        case totalKcal = "total_kcal"
    }
}

struct WorkoutsSummary: Decodable {
    var windowDays: Int?
    var totalWorkouts: Int?
    var byActivity: [ActivityTally]?

    enum CodingKeys: String, CodingKey {
        case windowDays = "window_days"
        case totalWorkouts = "total_workouts"
        case byActivity = "by_activity"
    }
}

struct WorkoutsResponse: Decodable {
    var workouts: [Workout]?
    var summary: WorkoutsSummary?
}

/// POST /api/workouts request body.
struct NewWorkout: Encodable {
    var activity: String
    var type: String = "other"
    var date: String?
    var durationMin: Double?
    var distanceKm: Double?
    var energyKcal: Double?
    var exercises: [Exercise]?
    var notes: String = ""

    enum CodingKeys: String, CodingKey {
        case activity, type, date, exercises, notes
        case durationMin = "duration_min"
        case distanceKm = "distance_km"
        case energyKcal = "energy_kcal"
    }
}

// MARK: - Volume & records

struct VolumePoint: Decodable, Identifiable {
    var date: String
    var volume: Double?

    var id: String { date }
}

struct ExerciseVolume: Decodable, Identifiable {
    var name: String
    var volume: Double?

    var id: String { name }
}

struct WorkoutVolumeResponse: Decodable {
    var windowDays: Int?
    var totalVolume: Double?
    var sessions: Int?
    var series: [VolumePoint]?
    var byExercise: [ExerciseVolume]?

    enum CodingKeys: String, CodingKey {
        case series, sessions
        case windowDays = "window_days"
        case totalVolume = "total_volume"
        case byExercise = "by_exercise"
    }
}

/// One all-time personal record. Decoded tolerantly: the backend uses
/// `name`/`e1rm` while the published contract says `exercise`/`est_1rm`.
struct PersonalRecord: Decodable, Identifiable {
    var exercise: String
    var weight: Double?
    var reps: Double?
    var est1RM: Double?
    var date: String?

    var id: String { exercise }

    enum CodingKeys: String, CodingKey {
        case exercise, name, weight, reps, date
        case e1rm
        case est1rm = "est_1rm"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        exercise = (try? c.decodeIfPresent(String.self, forKey: .exercise))
            ?? (try? c.decodeIfPresent(String.self, forKey: .name))
            ?? "Exercise"
        weight = try? c.decodeIfPresent(Double.self, forKey: .weight)
        reps = try? c.decodeIfPresent(Double.self, forKey: .reps)
        est1RM = (try? c.decodeIfPresent(Double.self, forKey: .e1rm))
            ?? (try? c.decodeIfPresent(Double.self, forKey: .est1rm))
        date = try? c.decodeIfPresent(String.self, forKey: .date)
    }
}

struct PersonalRecordsResponse: Decodable {
    var records: [PersonalRecord]?
}

// MARK: - Exercise history

struct ExerciseSession: Decodable, Identifiable {
    var date: String
    var volume: Double?
    var topWeight: Double?
    var topReps: Double?
    var e1rm: Double?
    var sets: Int?

    var id: String { date }

    enum CodingKeys: String, CodingKey {
        case date, volume, e1rm, sets
        case topWeight = "top_weight"
        case topReps = "top_reps"
    }
}

struct ExerciseHistoryResponse: Decodable {
    var name: String?
    var sessions: [ExerciseSession]?
}
