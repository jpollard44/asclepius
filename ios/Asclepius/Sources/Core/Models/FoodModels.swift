import Foundation

// MARK: - Food log

/// One logged food entry (macros already scaled by qty on the server).
struct FoodEntry: Decodable, Identifiable, Equatable {
    var id: Int
    var date: String?
    var meal: String?
    var name: String
    var qty: Double?
    var serving: String?
    var kcal: Double?
    var protein: Double?
    var carbs: Double?
    var fat: Double?
    var fiber: Double?
    var sugar: Double?
    var sodium: Double?
    var source: String?
    var createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, date, meal, name, qty, serving, kcal, protein, carbs, fat
        case fiber, sugar, sodium, source
        case createdAt = "created_at"
    }
}

struct MacroTotals: Decodable, Equatable {
    var kcal: Double?
    var protein: Double?
    var carbs: Double?
    var fat: Double?
}

/// GET /api/food?date= — a day's log grouped by meal.
struct FoodLogResponse: Decodable {
    var date: String?
    var entries: [FoodEntry]?
    var byMeal: [String: [FoodEntry]]?
    var totals: MacroTotals?

    enum CodingKeys: String, CodingKey {
        case date, entries, totals
        case byMeal = "by_meal"
    }
}

/// POST /api/food request body. Macros are per serving; qty scales server-side.
struct NewFoodEntry: Encodable {
    var name: String
    var kcal: Double
    var protein: Double = 0
    var carbs: Double = 0
    var fat: Double = 0
    var meal: String = "snack"
    var qty: Double = 1
    var serving: String = ""
    var date: String?
    var foodId: Int?
    var fiber: Double?
    var sugar: Double?
    var sodium: Double?

    enum CodingKeys: String, CodingKey {
        case name, kcal, protein, carbs, fat, meal, qty, serving, date
        case foodId = "food_id"
        case fiber, sugar, sodium
    }
}

struct MealUpdate: Encodable {
    var meal: String
}

// MARK: - Food database

/// Search result from GET /api/foods?q=.
struct FoodItem: Decodable, Identifiable {
    var id: Int
    var name: String
    var serving: String?
    var kcal: Double?
    var protein: Double?
    var carbs: Double?
    var fat: Double?
    var category: String?
}

struct FoodSearchResponse: Decodable {
    var foods: [FoodItem]?
}

/// POST /api/foods — create a custom food.
struct NewCustomFood: Encodable {
    var name: String
    var kcal: Double = 0
    var protein: Double = 0
    var carbs: Double = 0
    var fat: Double = 0
    var serving: String = ""
    var category: String = "custom"
}

// MARK: - Photo analysis

struct FoodAnalyzeResponse: Decodable {
    var estimate: FoodEstimate?
}

struct FoodEstimate: Decodable {
    var name: String?
    var kcal: Double?
    var protein: Double?
    var carbs: Double?
    var fat: Double?
    var fiber: Double?
    var sugar: Double?
    var sodium: Double?
    var serving: String?
    var confidence: String?
    var notes: String?

    enum CodingKeys: String, CodingKey {
        case name, kcal, protein, carbs, fat, fiber, sugar, sodium
        case serving, confidence, notes
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decodeIfPresent(String.self, forKey: .name)
        kcal = Self.number(c, .kcal)
        protein = Self.number(c, .protein)
        carbs = Self.number(c, .carbs)
        fat = Self.number(c, .fat)
        fiber = Self.number(c, .fiber)
        sugar = Self.number(c, .sugar)
        sodium = Self.number(c, .sodium)
        serving = try c.decodeIfPresent(String.self, forKey: .serving)
        notes = try c.decodeIfPresent(String.self, forKey: .notes)
        // The model may return confidence as a string ("medium") or a number.
        if let s = try? c.decodeIfPresent(String.self, forKey: .confidence) {
            confidence = s
        } else if let d = try? c.decodeIfPresent(Double.self, forKey: .confidence) {
            confidence = "\(Int((d <= 1 ? d * 100 : d).rounded()))%"
        } else {
            confidence = nil
        }
    }

    /// AI output is occasionally a numeric string; accept both.
    private static func number(_ c: KeyedDecodingContainer<CodingKeys>, _ key: CodingKeys) -> Double? {
        if let d = try? c.decodeIfPresent(Double.self, forKey: key) { return d }
        if let s = try? c.decodeIfPresent(String.self, forKey: key) { return Double(s) }
        return nil
    }
}

// MARK: - Favorites

struct Favorite: Decodable, Identifiable {
    var id: Int
    var name: String
    var description: String?
    var calories: Double?
    var proteinG: Double?
    var carbsG: Double?
    var fatG: Double?
    var fiberG: Double?
    var sugarG: Double?
    var sodiumMg: Double?
    var category: String?
    var sortOrder: Int?

    enum CodingKeys: String, CodingKey {
        case id, name, description, calories, category
        case proteinG = "protein_g"
        case carbsG = "carbs_g"
        case fatG = "fat_g"
        case fiberG = "fiber_g"
        case sugarG = "sugar_g"
        case sodiumMg = "sodium_mg"
        case sortOrder = "sort_order"
    }
}

struct FavoritesResponse: Decodable {
    var favorites: [Favorite]?
}

struct NewFavorite: Encodable {
    var name: String
    var description: String = ""
    var calories: Double = 0
    var proteinG: Double = 0
    var carbsG: Double = 0
    var fatG: Double = 0
    var fiberG: Double? = nil
    var sugarG: Double? = nil
    var sodiumMg: Double? = nil
    var category: String = "snack"

    enum CodingKeys: String, CodingKey {
        case name, description, calories, category
        case proteinG = "protein_g"
        case carbsG = "carbs_g"
        case fatG = "fat_g"
        case fiberG = "fiber_g"
        case sugarG = "sugar_g"
        case sodiumMg = "sodium_mg"
    }
}

struct FavoriteLogRequest: Encodable {
    var date: String?
    var meal: String?
}

struct FavoriteLogResponse: Decodable {
    var status: String?
    var entry: FoodEntry?
}

// MARK: - Water

struct WaterEntry: Decodable, Identifiable {
    var id: Int
    var date: String?
    var amountMl: Double
    var createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, date
        case amountMl = "amount_ml"
        case createdAt = "created_at"
    }
}

/// GET /api/water?date=.
struct WaterLogResponse: Decodable {
    var date: String?
    var totalMl: Double?
    var goalMl: Double?
    var pct: Double?
    var entries: [WaterEntry]?

    enum CodingKeys: String, CodingKey {
        case date, pct, entries
        case totalMl = "total_ml"
        case goalMl = "goal_ml"
    }
}

struct NewWaterEntry: Encodable {
    var amountMl: Double
    var date: String?

    enum CodingKeys: String, CodingKey {
        case amountMl = "amount_ml"
        case date
    }
}

struct WaterDay: Decodable, Identifiable {
    var date: String
    var totalMl: Double?

    var id: String { date }

    enum CodingKeys: String, CodingKey {
        case date
        case totalMl = "total_ml"
    }
}

struct WaterSeriesResponse: Decodable {
    var series: [WaterDay]?
}

// MARK: - Nutrition analytics

struct NutritionDay: Decodable, Identifiable {
    var date: String
    var kcal: Double?
    var protein: Double?
    var carbs: Double?
    var fat: Double?
    var fiber: Double?
    var sugar: Double?
    var sodium: Double?
    var items: Int?

    var id: String { date }
}

/// GET /api/nutrition?days=.
struct NutritionSummaryResponse: Decodable {
    var available: Bool?
    var windowDays: Int?
    var daysLogged: Int?
    var series: [NutritionDay]?
    var avgKcal: Double?
    var avgProtein: Double?
    var avgCarbs: Double?
    var avgFat: Double?
    var trend: Trend?

    enum CodingKeys: String, CodingKey {
        case available, series, trend
        case windowDays = "window_days"
        case daysLogged = "days_logged"
        case avgKcal = "avg_kcal"
        case avgProtein = "avg_protein"
        case avgCarbs = "avg_carbs"
        case avgFat = "avg_fat"
    }
}

/// One meal's share of today (nutrition detail `by_meal`).
struct MealSplit: Decodable {
    var meal: String?
    var kcal: Double?
    var protein: Double?
    var carbs: Double?
    var fat: Double?
    var items: Int?
}

struct FoodSource: Decodable, Identifiable {
    var name: String
    var times: Int?
    var kcal: Double?
    var protein: Double?
    var carbs: Double?
    var fat: Double?

    var id: String { name }
}

/// GET /api/nutrition/detail?days=.
struct NutritionDetailResponse: Decodable {
    var available: Bool?
    var windowDays: Int?
    var daysLogged: Int?
    var series: [NutritionDay]?
    var byMeal: [String: MealSplit]?
    var today: NutritionToday?
    var sourcesByKcal: [FoodSource]?
    var sourcesByProtein: [FoodSource]?
    var trend: Trend?
    var proteinTrend: Trend?
    var avgKcal: Double?
    var avgProtein: Double?
    var avgCarbs: Double?
    var avgFat: Double?
    var kcalGoal: Double?
    var proteinGoal: Double?

    enum CodingKeys: String, CodingKey {
        case available, series, today, trend
        case windowDays = "window_days"
        case daysLogged = "days_logged"
        case byMeal = "by_meal"
        case sourcesByKcal = "sources_by_kcal"
        case sourcesByProtein = "sources_by_protein"
        case proteinTrend = "protein_trend"
        case avgKcal = "avg_kcal"
        case avgProtein = "avg_protein"
        case avgCarbs = "avg_carbs"
        case avgFat = "avg_fat"
        case kcalGoal = "kcal_goal"
        case proteinGoal = "protein_goal"
    }
}
