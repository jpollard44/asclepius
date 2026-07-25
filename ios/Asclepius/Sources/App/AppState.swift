import Foundation
import Observation

/// Shared server-derived state: the config catalogue from /api/status, the
/// personalized daily goals, and the Today dashboard snapshot.
@MainActor
@Observable
final class AppState {
    static let shared = AppState()

    private let api = APIClient.shared

    private(set) var status: AppStatus?
    private(set) var dashboard: DashboardResponse?
    private(set) var dailyGoals: [String: DailyGoal] = [:]
    private(set) var isLoading = false
    var lastError: String?

    // MARK: - Config accessors (with safe fallbacks)

    var meals: [String] {
        status?.config?.meals ?? ["breakfast", "lunch", "dinner", "snack"]
    }

    var workoutTypes: [String] {
        status?.config?.workoutTypes ?? ["strength", "cardio", "other"]
    }

    var goalCategories: [String: GoalCategory] {
        status?.config?.goalCategories ?? [:]
    }

    var manualMetrics: [String: ManualMetricInfo] {
        status?.config?.manualMetrics ?? [:]
    }

    var hasData: Bool { status?.hasData ?? false }

    /// The live numeric target for one daily-goal key, if configured.
    func dailyGoalTarget(_ key: String) -> Double? {
        dailyGoals[key]?.target
    }

    /// A sensible default meal slot for the current time of day.
    var suggestedMeal: String {
        let hour = Calendar.current.component(.hour, from: Date())
        switch hour {
        case ..<11: return "breakfast"
        case ..<15: return "lunch"
        case 17 ..< 21: return "dinner"
        default: return "snack"
        }
    }

    // MARK: - Loading

    /// Full refresh: status + daily goals + dashboard.
    func refreshAll() async {
        isLoading = true
        defer { isLoading = false }
        async let statusTask = try? api.status()
        async let goalsTask = try? api.dailyGoals()
        async let dashboardTask = try? api.dashboard()
        let (status, goals, dashboard) = await (statusTask, goalsTask, dashboardTask)
        if let status {
            self.status = status
        }
        if let goals = goals?.goals {
            self.dailyGoals = goals
        }
        if let dashboard {
            self.dashboard = dashboard
        }
        if status == nil, dashboard == nil {
            lastError = L.Common.error
        } else {
            lastError = nil
        }
    }

    func refreshDashboard() async {
        do {
            dashboard = try await api.dashboard()
            lastError = nil
        } catch {
            lastError = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }

    func refreshDailyGoals() async {
        if let goals = try? await api.dailyGoals().goals {
            dailyGoals = goals
        }
    }

    /// Applies a partial daily-goals update and stores the returned state.
    func updateDailyGoals(_ patch: [String: Double?]) async throws {
        let response = try await api.updateDailyGoals(patch)
        if let goals = response.goals {
            dailyGoals = goals
        }
    }
}
