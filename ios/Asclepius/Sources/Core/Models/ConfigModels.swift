import Foundation

/// GET /api/status — server-side app state and the shared config catalogue.
struct AppStatus: Decodable {
    var hasData: Bool?
    var hasImport: Bool?
    var advisorReady: Bool?
    var dateRange: DateRange?
    var metrics: [MetricInfo]?
    var plan: Plan?
    var config: RemoteConfig?

    enum CodingKeys: String, CodingKey {
        case hasData = "has_data"
        case hasImport = "has_import"
        case advisorReady = "advisor_ready"
        case dateRange = "date_range"
        case metrics, plan, config
    }
}

/// The `config` block: catalogues shared between backend and clients.
struct RemoteConfig: Decodable {
    var meals: [String]?
    var workoutTypes: [String]?
    var goalCategories: [String: GoalCategory]?
    var manualMetrics: [String: ManualMetricInfo]?

    enum CodingKeys: String, CodingKey {
        case meals
        case workoutTypes = "workout_types"
        case goalCategories = "goal_categories"
        case manualMetrics = "manual_metrics"
    }
}

struct GoalCategory: Decodable {
    var label: String?
    var metric: String?
    var unit: String?
}

struct ManualMetricInfo: Decodable {
    var label: String?
    var unit: String?
    var area: String?
}

// MARK: - Daily goals

/// One personalized daily target from GET /api/daily-goals.
struct DailyGoal: Decodable, Identifiable {
    var key: String
    var label: String?
    var unit: String?
    var target: Double
    var defaultTarget: Double?
    var customized: Bool?
    var lowerBetter: Bool?

    var id: String { key }

    enum CodingKeys: String, CodingKey {
        case key, label, unit, target, customized
        case defaultTarget = "default"
        case lowerBetter = "lower_better"
    }
}

struct DailyGoalsResponse: Decodable {
    var goals: [String: DailyGoal]?
}

/// PUT /api/daily-goals. A nil value resets that key to its default.
struct DailyGoalsUpdate: Encodable {
    var goals: [String: Double?]
}

// MARK: - Dashboard

/// GET /api/dashboard — mirrors backend analytics.dashboard().
struct DashboardResponse: Decodable {
    var date: String?
    var nutrition: NutritionToday?
    var water: WaterStatus?
    var stepsToday: Double?
    var activeEnergyToday: Double?
    var weight: MetricLatest?
    var sleepLast: SleepNight?
    var workoutsWeek: Int?
    var streaks: Streaks?
    var goals: [Goal]?
    var headline: [MetricSummary]?

    enum CodingKeys: String, CodingKey {
        case date, nutrition, water, weight, streaks, goals, headline
        case stepsToday = "steps_today"
        case activeEnergyToday = "active_energy_today"
        case sleepLast = "sleep_last"
        case workoutsWeek = "workouts_week"
    }
}

/// Today's nutrition totals with the flattened `*_goal` targets.
struct NutritionToday: Decodable {
    var date: String?
    var items: Int?
    var kcal: Double?
    var protein: Double?
    var carbs: Double?
    var fat: Double?
    var fiber: Double?
    var sugar: Double?
    var sodium: Double?
    var kcalGoal: Double?
    var proteinGoal: Double?
    var carbsGoal: Double?
    var fatGoal: Double?
    var fiberGoal: Double?
    var sugarGoal: Double?
    var sodiumGoal: Double?

    enum CodingKeys: String, CodingKey {
        case date, items, kcal, protein, carbs, fat, fiber, sugar, sodium
        case kcalGoal = "kcal_goal"
        case proteinGoal = "protein_goal"
        case carbsGoal = "carbs_goal"
        case fatGoal = "fat_goal"
        case fiberGoal = "fiber_goal"
        case sugarGoal = "sugar_goal"
        case sodiumGoal = "sodium_goal"
    }
}

struct WaterStatus: Decodable {
    var totalMl: Double?
    var goalMl: Double?
    var pct: Double?

    enum CodingKeys: String, CodingKey {
        case totalMl = "total_ml"
        case goalMl = "goal_ml"
        case pct
    }
}

/// GET /api/streaks (also embedded in the dashboard).
struct Streaks: Decodable {
    var food: Int?
    var workout: Int?
    var water: Int?
    var foodDaysTotal: Int?
    var workoutDaysTotal: Int?

    enum CodingKeys: String, CodingKey {
        case food, workout, water
        case foodDaysTotal = "food_days_total"
        case workoutDaysTotal = "workout_days_total"
    }
}

// MARK: - Achievements & weekly report

struct Achievement: Decodable, Identifiable {
    var key: String
    var icon: String?
    var title: String?
    var desc: String?
    var unlocked: Bool?
    var unlockedAt: String?

    var id: String { key }

    enum CodingKeys: String, CodingKey {
        case key, icon, title, desc, unlocked
        case unlockedAt = "unlocked_at"
    }
}

struct AchievementsResponse: Decodable {
    var achievements: [Achievement]?
}

struct WeeklyReport: Decodable {
    var thisWeekStart: String?
    var metrics: [WeeklyMetric]?
    var nutrition: WeeklyNutrition?
    var workouts: Int?
    var sleep: SleepSummary?

    enum CodingKeys: String, CodingKey {
        case metrics, nutrition, workouts, sleep
        case thisWeekStart = "this_week_start"
    }
}

struct WeeklyMetric: Decodable, Identifiable {
    var key: String
    var label: String?
    var unit: String?
    var thisWeek: Double?
    var priorWeek: Double?
    var delta: Double?

    var id: String { key }

    enum CodingKeys: String, CodingKey {
        case key, label, unit, delta
        case thisWeek = "this_week"
        case priorWeek = "prior_week"
    }
}

struct WeeklyNutrition: Decodable {
    var daysLogged: Int?
    var avgKcal: Double?

    enum CodingKeys: String, CodingKey {
        case daysLogged = "days_logged"
        case avgKcal = "avg_kcal"
    }
}
