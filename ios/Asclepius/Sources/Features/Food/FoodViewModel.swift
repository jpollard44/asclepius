import Foundation
import Observation

@MainActor
@Observable
final class FoodViewModel {
    private let api = APIClient.shared

    var date = Date()
    private(set) var log: FoodLogResponse?
    private(set) var water: WaterLogResponse?
    private(set) var favorites: [Favorite] = []
    private(set) var isLoading = false
    var errorMessage: String?

    var dateString: String { Day.string(from: date) }
    var isToday: Bool { Calendar.current.isDateInToday(date) }

    func entries(for meal: String) -> [FoodEntry] {
        log?.byMeal?[meal] ?? []
    }

    // MARK: - Loading

    func load() async {
        isLoading = true
        defer { isLoading = false }
        async let foodTask = try? api.foodLog(date: dateString)
        async let waterTask = try? api.water(date: dateString)
        let (food, water) = await (foodTask, waterTask)
        if food == nil, water == nil {
            errorMessage = L.Common.error
        }
        if let food { log = food }
        if let water { self.water = water }
    }

    func loadFavorites() async {
        if let response = try? await api.favorites() {
            favorites = response.favorites ?? []
        }
    }

    func changeDay(by days: Int) {
        date = Day.adding(days, to: date)
        Task { await load() }
    }

    // MARK: - Entries

    func delete(_ entry: FoodEntry) async {
        do {
            try await api.deleteFood(id: entry.id)
            Haptics.success()
            await load()
        } catch {
            errorMessage = describe(error)
        }
    }

    func move(_ entry: FoodEntry, to meal: String) async {
        do {
            _ = try await api.moveFood(id: entry.id, meal: meal)
            Haptics.tap()
            await load()
        } catch {
            errorMessage = describe(error)
        }
    }

    /// Logs a favorite in one tap. Uses the current date and a sensible meal.
    func logFavorite(_ favorite: Favorite, meal: String) async {
        do {
            _ = try await api.logFavorite(id: favorite.id, date: dateString, meal: meal)
            Haptics.success()
            await load()
        } catch {
            errorMessage = describe(error)
        }
    }

    // MARK: - Water

    func addWater(ml: Double) async {
        do {
            water = try await api.addWater(amountMl: ml, date: dateString)
            Haptics.success()
        } catch {
            errorMessage = describe(error)
        }
    }

    func deleteWater(_ entry: WaterEntry) async {
        do {
            try await api.deleteWater(id: entry.id)
            water = try await api.water(date: dateString)
        } catch {
            errorMessage = describe(error)
        }
    }

    private func describe(_ error: Error) -> String {
        (error as? APIError)?.errorDescription ?? L.Common.error
    }
}
