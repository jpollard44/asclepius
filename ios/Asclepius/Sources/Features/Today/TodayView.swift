import SwiftUI

/// Home tab: greeting, daily goal rings/cards, streaks, active goals,
/// weekly recap link, achievements grid.
struct TodayView: View {
    @Environment(AppState.self) private var appState
    @Environment(AuthManager.self) private var auth
    @Environment(AppRouter.self) private var router

    @State private var achievements: [Achievement] = []

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let error = appState.lastError {
                        ErrorBanner(message: error) {
                            Task { await appState.refreshAll() }
                        }
                    }

                    if let dashboard = appState.dashboard {
                        cards(dashboard)
                        streaksSection(dashboard.streaks)
                        goalsSection(dashboard.goals ?? [])
                        weeklyRecapLink
                        achievementsSection
                    } else if appState.isLoading {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 60)
                    } else {
                        EmptyState(
                            icon: "sun.max",
                            title: L.Today.emptyTitle,
                            message: L.Today.emptyBody)
                    }
                }
                .padding(.horizontal)
                .padding(.bottom, 24)
            }
            .background(Theme.background)
            .navigationTitle(greeting)
            .refreshable {
                await appState.refreshAll()
                await loadAchievements()
            }
            .task {
                if appState.dashboard == nil {
                    await appState.refreshAll()
                }
                await loadAchievements()
            }
        }
    }

    private var greeting: String {
        let base: String
        switch Calendar.current.component(.hour, from: Date()) {
        case 5 ..< 12: base = L.Today.goodMorning
        case 12 ..< 18: base = L.Today.goodAfternoon
        default: base = L.Today.goodEvening
        }
        if let first = auth.user?.name?.split(separator: " ").first {
            return "\(base), \(first)"
        }
        return base
    }

    // MARK: - Metric cards

    private func cards(_ dashboard: DashboardResponse) -> some View {
        let nutrition = dashboard.nutrition
        let kcal = nutrition?.kcal ?? 0
        let kcalGoal = nutrition?.kcalGoal ?? appState.dailyGoalTarget("calories")
        let protein = nutrition?.protein ?? 0
        let proteinGoal = nutrition?.proteinGoal ?? appState.dailyGoalTarget("protein")
        let waterMl = dashboard.water?.totalMl ?? 0
        let waterGoal = dashboard.water?.goalMl ?? appState.dailyGoalTarget("water")
        let steps = dashboard.stepsToday ?? 0
        let stepsGoal = appState.dailyGoalTarget("steps")
        let energy = dashboard.activeEnergyToday ?? 0
        let energyGoal = appState.dailyGoalTarget("active_energy")
        let sleepHours = dashboard.sleepLast?.asleepHours
        let sleepGoal = appState.dailyGoalTarget("sleep")

        return LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
            StatCard(
                title: L.Today.calories,
                value: "\(kcal.intString) kcal",
                subtitle: goalSubtitle(kcal, kcalGoal),
                systemImage: "flame.fill",
                tint: Theme.calories,
                progress: fraction(kcal, kcalGoal))
            StatCard(
                title: L.Today.protein,
                value: "\(protein.intString) g",
                subtitle: goalSubtitle(protein, proteinGoal),
                systemImage: "bolt.heart.fill",
                tint: Theme.protein,
                progress: fraction(protein, proteinGoal))
            StatCard(
                title: L.Today.water,
                value: WaterUnits.display(ml: waterMl),
                subtitle: goalSubtitle(waterMl, waterGoal),
                systemImage: "drop.fill",
                tint: Theme.water,
                progress: fraction(waterMl, waterGoal))
            StatCard(
                title: L.Today.steps,
                value: steps.intString,
                subtitle: goalSubtitle(steps, stepsGoal),
                systemImage: "figure.walk",
                tint: Theme.steps,
                progress: fraction(steps, stepsGoal))
            StatCard(
                title: L.Today.activeEnergy,
                value: "\(energy.intString) kcal",
                subtitle: goalSubtitle(energy, energyGoal),
                systemImage: "flame",
                tint: Theme.energy,
                progress: fraction(energy, energyGoal))
            StatCard(
                title: L.Today.sleep,
                value: sleepHours.map { "\($0.compactString) h" } ?? "—",
                subtitle: sleepHours.flatMap { goalSubtitle($0, sleepGoal) },
                systemImage: "moon.zzz.fill",
                tint: Theme.sleep,
                progress: sleepHours.flatMap { fraction($0, sleepGoal) })
        }
    }

    private func fraction(_ value: Double, _ goal: Double?) -> Double? {
        guard let goal, goal > 0 else { return nil }
        return value / goal
    }

    private func goalSubtitle(_ value: Double, _ goal: Double?) -> String? {
        guard let goal, goal > 0 else { return nil }
        return "\(Int((value / goal * 100).rounded()))% \(L.Water.ofGoal)"
    }

    // MARK: - Streaks

    @ViewBuilder
    private func streaksSection(_ streaks: Streaks?) -> some View {
        if let streaks {
            VStack(alignment: .leading, spacing: 10) {
                SectionHeader(title: L.Today.streaks)
                HStack(spacing: 10) {
                    streakBadge(count: streaks.food ?? 0, label: L.Today.foodStreak, icon: "fork.knife")
                    streakBadge(count: streaks.workout ?? 0, label: L.Today.workoutStreak, icon: "dumbbell.fill")
                    streakBadge(count: streaks.water ?? 0, label: L.Today.waterStreak, icon: "drop.fill")
                }
            }
        }
    }

    private func streakBadge(count: Int, label: String, icon: String) -> some View {
        VStack(spacing: 4) {
            HStack(spacing: 4) {
                Image(systemName: count > 0 ? "flame.fill" : icon)
                    .foregroundStyle(count > 0 ? Theme.calories : .secondary)
                Text("\(count)")
                    .font(.title3.bold())
            }
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .cardStyle()
    }

    // MARK: - Goals

    @ViewBuilder
    private func goalsSection(_ goals: [Goal]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: L.Today.goals, actionTitle: L.Common.seeAll) {
                router.open(.goals)
            }
            if goals.isEmpty {
                Text(L.Today.noGoals)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .cardStyle()
            } else {
                ForEach(goals.prefix(4)) { goal in
                    GoalProgressRow(goal: goal)
                }
            }
        }
    }

    // MARK: - Weekly recap

    private var weeklyRecapLink: some View {
        Button {
            router.open(.weeklyReport)
        } label: {
            HStack {
                Image(systemName: "chart.line.uptrend.xyaxis")
                    .foregroundStyle(Theme.accent)
                Text(L.Today.weeklyRecap)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .cardStyle()
        }
        .buttonStyle(.plain)
    }

    // MARK: - Achievements

    @ViewBuilder
    private var achievementsSection: some View {
        if !achievements.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                SectionHeader(title: L.Today.achievements, actionTitle: L.Common.seeAll) {
                    router.open(.achievements)
                }
                LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 4), spacing: 10) {
                    ForEach(achievements.prefix(8)) { achievement in
                        AchievementBadge(achievement: achievement, compact: true)
                    }
                }
            }
        }
    }

    private func loadAchievements() async {
        if let response = try? await APIClient.shared.achievements() {
            achievements = response.achievements ?? []
        }
    }
}

/// One goal with its progress bar; shared by Today and the Goals screen.
struct GoalProgressRow: View {
    let goal: Goal

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(goal.label?.isEmpty == false ? goal.label! : (goal.category ?? "Goal").capitalized)
                    .font(.subheadline.weight(.semibold))
                Spacer()
                if let pct = goal.progressPct {
                    Text("\(Int(pct))%")
                        .font(.subheadline.bold())
                        .foregroundStyle(pct >= 100 ? Theme.green : Theme.accent)
                }
            }
            if let current = goal.current, let target = goal.target {
                Text("\(L.Goals.current): \(current.compactString) → \(target.compactString) \(goal.unit ?? "")")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Theme.accent.opacity(0.15))
                    Capsule()
                        .fill((goal.progressPct ?? 0) >= 100 ? Theme.green : Theme.accent)
                        .frame(width: geo.size.width * min(max((goal.progressPct ?? 0) / 100, 0), 1))
                }
            }
            .frame(height: 6)
        }
        .cardStyle()
    }
}

/// Achievement tile used in the Today grid and the full Achievements screen.
struct AchievementBadge: View {
    let achievement: Achievement
    var compact = false

    private var unlocked: Bool { achievement.unlocked ?? false }

    var body: some View {
        VStack(spacing: 4) {
            Text(achievement.icon ?? "🏅")
                .font(compact ? .title2 : .largeTitle)
                .grayscale(unlocked ? 0 : 1)
                .opacity(unlocked ? 1 : 0.35)
            if !compact {
                Text(achievement.title ?? achievement.key)
                    .font(.caption.weight(.semibold))
                    .multilineTextAlignment(.center)
                Text(achievement.desc ?? "")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            } else {
                Text(achievement.title ?? achievement.key)
                    .font(.caption2)
                    .foregroundStyle(unlocked ? .primary : .secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, compact ? 8 : 14)
        .padding(.horizontal, 4)
        .background(Theme.cardBackground, in: RoundedRectangle(cornerRadius: 12))
    }
}
