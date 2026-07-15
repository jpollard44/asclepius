import Foundation

/// Typed wrappers for every backend endpoint the app uses.
extension APIClient {
    // MARK: - Auth & account

    func signInWithApple(identityToken: String, fullName: String?, email: String?) async throws -> TokenResponse {
        let tokens: TokenResponse = try await request(
            .post, "/api/auth/apple",
            body: AppleSignInRequest(identityToken: identityToken, fullName: fullName, email: email),
            authenticated: false)
        storeTokens(tokens)
        return tokens
    }

    func logout() async {
        guard let token = refreshTokenValue else { return }
        _ = try? await send(.post, "/api/auth/logout", body: LogoutRequest(refreshToken: token))
    }

    func account() async throws -> AccountResponse {
        try await request(.get, "/api/account")
    }

    func deleteAccount() async throws -> SimpleStatus {
        try await send(.delete, "/api/account")
    }

    // MARK: - Devices

    func registerDevice(token: String) async throws {
        try await send(.post, "/api/devices",
                       body: DeviceRegistration(token: token, environment: AppConfig.apnsEnvironment))
    }

    func unregisterDevice(token: String) async {
        _ = try? await send(.delete, "/api/devices/\(token)")
    }

    // MARK: - HealthKit sync

    func syncHealthKit(_ payload: HealthSyncPayload) async throws -> SyncResponse {
        try await request(.post, "/api/sync/healthkit", body: payload, longRunning: true)
    }

    // MARK: - Status, dashboard, metrics

    func status() async throws -> AppStatus {
        try await request(.get, "/api/status")
    }

    func dashboard() async throws -> DashboardResponse {
        try await request(.get, "/api/dashboard")
    }

    func metrics() async throws -> MetricsListResponse {
        try await request(.get, "/api/metrics")
    }

    func metricDetail(key: String, days: Int = 365) async throws -> MetricDetailResponse {
        try await request(.get, "/api/metric/\(key)",
                          query: [URLQueryItem(name: "days", value: String(days))])
    }

    func sleep(days: Int = 90) async throws -> SleepResponse {
        try await request(.get, "/api/sleep",
                          query: [URLQueryItem(name: "days", value: String(days))])
    }

    // MARK: - Coach

    func chatHistory(limit: Int = 50, before: Int? = nil) async throws -> ChatHistoryResponse {
        var query = [URLQueryItem(name: "limit", value: String(limit))]
        if let before {
            query.append(URLQueryItem(name: "before", value: String(before)))
        }
        return try await request(.get, "/api/chat/history", query: query)
    }

    func sendChat(_ text: String) async throws -> ChatReply {
        try await request(.post, "/api/chat",
                          body: ChatRequest(messages: [.init(role: "user", content: text)]),
                          longRunning: true)
    }

    func clearChatHistory() async throws {
        try await send(.delete, "/api/chat/history")
    }

    func briefing() async throws -> ChatReply {
        try await request(.post, "/api/briefing", longRunning: true)
    }

    func recommend(topic: String, label: String?) async throws -> RecommendReply {
        try await request(.post, "/api/recommend",
                          body: RecommendRequest(topic: topic, label: label),
                          longRunning: true)
    }

    func plan() async throws -> PlanResponse {
        try await request(.get, "/api/plan")
    }

    // MARK: - Food

    func foodLog(date: String?) async throws -> FoodLogResponse {
        var query: [URLQueryItem] = []
        if let date {
            query.append(URLQueryItem(name: "date", value: date))
        }
        return try await request(.get, "/api/food", query: query)
    }

    func addFood(_ entry: NewFoodEntry) async throws -> FoodEntry {
        try await request(.post, "/api/food", body: entry)
    }

    func deleteFood(id: Int) async throws {
        try await send(.delete, "/api/food/\(id)")
    }

    func moveFood(id: Int, meal: String) async throws -> FoodEntry {
        try await request(.put, "/api/food/\(id)/meal", body: MealUpdate(meal: meal))
    }

    func searchFoods(_ q: String, limit: Int = 30) async throws -> FoodSearchResponse {
        try await request(.get, "/api/foods", query: [
            URLQueryItem(name: "q", value: q),
            URLQueryItem(name: "limit", value: String(limit)),
        ])
    }

    func createCustomFood(_ food: NewCustomFood) async throws -> FoodItem {
        try await request(.post, "/api/foods", body: food)
    }

    func analyzeFoodPhoto(_ imageData: Data) async throws -> FoodAnalyzeResponse {
        try await uploadImage("/api/food/analyze", imageData: imageData)
    }

    // MARK: - Favorites

    func favorites() async throws -> FavoritesResponse {
        try await request(.get, "/api/favorites")
    }

    func createFavorite(_ favorite: NewFavorite) async throws -> Favorite {
        try await request(.post, "/api/favorites", body: favorite)
    }

    func updateFavorite(id: Int, _ favorite: NewFavorite) async throws -> Favorite {
        try await request(.put, "/api/favorites/\(id)", body: favorite)
    }

    func deleteFavorite(id: Int) async throws {
        try await send(.delete, "/api/favorites/\(id)")
    }

    func logFavorite(id: Int, date: String?, meal: String?) async throws -> FavoriteLogResponse {
        try await request(.post, "/api/favorites/\(id)/log",
                          body: FavoriteLogRequest(date: date, meal: meal))
    }

    // MARK: - Water

    func water(date: String?) async throws -> WaterLogResponse {
        var query: [URLQueryItem] = []
        if let date {
            query.append(URLQueryItem(name: "date", value: date))
        }
        return try await request(.get, "/api/water", query: query)
    }

    func addWater(amountMl: Double, date: String?) async throws -> WaterLogResponse {
        try await request(.post, "/api/water", body: NewWaterEntry(amountMl: amountMl, date: date))
    }

    func deleteWater(id: Int) async throws {
        try await send(.delete, "/api/water/\(id)")
    }

    func waterSeries(days: Int = 30) async throws -> WaterSeriesResponse {
        try await request(.get, "/api/water/series",
                          query: [URLQueryItem(name: "days", value: String(days))])
    }

    // MARK: - Nutrition analytics

    func nutrition(days: Int = 30) async throws -> NutritionSummaryResponse {
        try await request(.get, "/api/nutrition",
                          query: [URLQueryItem(name: "days", value: String(days))])
    }

    func nutritionDetail(days: Int = 30) async throws -> NutritionDetailResponse {
        try await request(.get, "/api/nutrition/detail",
                          query: [URLQueryItem(name: "days", value: String(days))])
    }

    // MARK: - Workouts

    func workouts(days: Int = 90) async throws -> WorkoutsResponse {
        try await request(.get, "/api/workouts",
                          query: [URLQueryItem(name: "days", value: String(days))])
    }

    func addWorkout(_ workout: NewWorkout) async throws -> Workout {
        try await request(.post, "/api/workouts", body: workout)
    }

    func deleteWorkout(id: Int) async throws {
        try await send(.delete, "/api/workouts/\(id)")
    }

    func workoutVolume(days: Int = 30) async throws -> WorkoutVolumeResponse {
        try await request(.get, "/api/workouts/volume",
                          query: [URLQueryItem(name: "days", value: String(days))])
    }

    func personalRecords() async throws -> PersonalRecordsResponse {
        try await request(.get, "/api/workouts/prs")
    }

    func exerciseHistory(name: String, days: Int = 365) async throws -> ExerciseHistoryResponse {
        try await request(.get, "/api/workouts/exercise", query: [
            URLQueryItem(name: "name", value: name),
            URLQueryItem(name: "days", value: String(days)),
        ])
    }

    // MARK: - Body & manual logs

    func bodyMetrics(days: Int = 365) async throws -> BodyResponse {
        try await request(.get, "/api/body",
                          query: [URLQueryItem(name: "days", value: String(days))])
    }

    func logBody(_ entry: NewBodyEntry) async throws {
        try await send(.post, "/api/body", body: entry)
    }

    func logSleep(_ entry: NewSleepEntry) async throws {
        try await send(.post, "/api/sleep", body: entry)
    }

    // MARK: - Goals

    func goals(status: String = "active") async throws -> GoalsResponse {
        try await request(.get, "/api/goals",
                          query: [URLQueryItem(name: "status", value: status)])
    }

    func createGoal(_ goal: NewGoal) async throws -> Goal {
        try await request(.post, "/api/goals", body: goal)
    }

    func updateGoal(id: Int, _ update: GoalUpdate) async throws -> Goal {
        try await request(.put, "/api/goals/\(id)", body: update)
    }

    func deleteGoal(id: Int) async throws {
        try await send(.delete, "/api/goals/\(id)")
    }

    // MARK: - Daily goals

    func dailyGoals() async throws -> DailyGoalsResponse {
        try await request(.get, "/api/daily-goals")
    }

    func updateDailyGoals(_ patch: [String: Double?]) async throws -> DailyGoalsResponse {
        try await request(.put, "/api/daily-goals", body: DailyGoalsUpdate(goals: patch))
    }

    // MARK: - Insights

    func streaks() async throws -> Streaks {
        try await request(.get, "/api/streaks")
    }

    func achievements() async throws -> AchievementsResponse {
        try await request(.get, "/api/achievements")
    }

    func weeklyReport() async throws -> WeeklyReport {
        try await request(.get, "/api/report/weekly")
    }

    // MARK: - Push preferences

    func pushPrefs() async throws -> PushPrefsResponse {
        try await request(.get, "/api/push/prefs")
    }

    func updatePushPrefs(_ update: PushPrefsUpdate) async throws -> PushPrefsResponse {
        try await request(.put, "/api/push/prefs", body: update)
    }
}
