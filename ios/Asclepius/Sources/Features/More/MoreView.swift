import SwiftUI

/// The More tab: Sleep, Body, Goals, Achievements, Weekly report, Settings.
struct MoreView: View {
    @Environment(AppRouter.self) private var router

    var body: some View {
        @Bindable var router = router
        NavigationStack(path: $router.morePath) {
            List {
                Section(L.More.tracking) {
                    NavigationLink(value: MoreRoute.sleep) {
                        Label(L.Sleep.title, systemImage: "moon.zzz.fill")
                    }
                    NavigationLink(value: MoreRoute.body) {
                        Label(L.Body.title, systemImage: "figure.arms.open")
                    }
                    NavigationLink(value: MoreRoute.goals) {
                        Label(L.Goals.title, systemImage: "target")
                    }
                }
                Section(L.More.insights) {
                    NavigationLink(value: MoreRoute.achievements) {
                        Label(L.Achievements.title, systemImage: "rosette")
                    }
                    NavigationLink(value: MoreRoute.weeklyReport) {
                        Label(L.Weekly.title, systemImage: "chart.line.uptrend.xyaxis")
                    }
                }
                Section {
                    NavigationLink(value: MoreRoute.settings) {
                        Label(L.Settings.title, systemImage: "gearshape.fill")
                    }
                }
            }
            .navigationTitle(L.Tabs.more)
            .navigationDestination(for: MoreRoute.self) { route in
                switch route {
                case .sleep: SleepView()
                case .body: BodyView()
                case .goals: GoalsView()
                case .achievements: AchievementsView()
                case .weeklyReport: WeeklyReportView()
                case .settings: SettingsView()
                }
            }
        }
    }
}

// MARK: - Achievements

struct AchievementsView: View {
    @State private var achievements: [Achievement] = []
    @State private var isLoading = false
    @State private var errorMessage: String?

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                if let error = errorMessage {
                    ErrorBanner(message: error) {
                        errorMessage = nil
                        Task { await load() }
                    }
                }

                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                    ForEach(achievements) { achievement in
                        VStack(spacing: 6) {
                            AchievementBadge(achievement: achievement)
                            if achievement.unlocked == true, let at = achievement.unlockedAt {
                                Text("\(L.Achievements.unlockedOn) \(Timestamp.display(at))")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            } else if achievement.unlocked != true {
                                Text(L.Achievements.locked)
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                            }
                        }
                    }
                }
            }
            .padding(.horizontal)
            .padding(.bottom, 24)
        }
        .background(Theme.background)
        .navigationTitle(L.Achievements.title)
        .navigationBarTitleDisplayMode(.inline)
        .refreshable {
            await load()
        }
        .task {
            if achievements.isEmpty {
                await load()
            }
        }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await APIClient.shared.achievements()
            achievements = response.achievements ?? []
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}

// MARK: - Weekly report

struct WeeklyReportView: View {
    @State private var report: WeeklyReport?
    @State private var isLoading = false
    @State private var errorMessage: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let error = errorMessage {
                    ErrorBanner(message: error) {
                        errorMessage = nil
                        Task { await load() }
                    }
                }

                if let report {
                    reportBody(report)
                } else if isLoading {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 60)
                } else {
                    EmptyState(
                        icon: "chart.line.uptrend.xyaxis",
                        title: L.Common.noData,
                        message: L.Weekly.emptyBody)
                }
            }
            .padding(.horizontal)
            .padding(.bottom, 24)
        }
        .background(Theme.background)
        .navigationTitle(L.Weekly.title)
        .navigationBarTitleDisplayMode(.inline)
        .refreshable {
            await load()
        }
        .task {
            if report == nil {
                await load()
            }
        }
    }

    @ViewBuilder
    private func reportBody(_ report: WeeklyReport) -> some View {
        // Headline metric deltas vs the prior week.
        if let metrics = report.metrics, !metrics.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(metrics) { metric in
                    HStack {
                        Text(metric.label ?? metric.key)
                            .font(.subheadline.weight(.medium))
                        Spacer()
                        VStack(alignment: .trailing, spacing: 2) {
                            Text(metric.thisWeek.map { "\($0.compactString) \(metric.unit ?? "")" } ?? "—")
                                .font(.subheadline.bold())
                            if let delta = metric.delta {
                                HStack(spacing: 2) {
                                    Image(systemName: delta >= 0 ? "arrow.up.right" : "arrow.down.right")
                                    Text("\(abs(delta).compactString) \(L.Weekly.vsPrior)")
                                }
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .cardStyle()
                }
            }
        }

        // Nutrition, workouts, sleep tallies.
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
            StatCard(
                title: L.Weekly.daysLogged,
                value: "\(report.nutrition?.daysLogged ?? 0)/7",
                subtitle: nil,
                systemImage: "fork.knife",
                tint: Theme.calories,
                progress: Double(report.nutrition?.daysLogged ?? 0) / 7)
            StatCard(
                title: L.Weekly.avgCalories,
                value: (report.nutrition?.avgKcal).map { "\($0.intString) kcal" } ?? "—",
                subtitle: nil,
                systemImage: "flame.fill",
                tint: Theme.calories,
                progress: nil)
            StatCard(
                title: L.Weekly.workouts,
                value: "\(report.workouts ?? 0)",
                subtitle: nil,
                systemImage: "dumbbell.fill",
                tint: Theme.accent,
                progress: nil)
            StatCard(
                title: L.Weekly.sleepAvg,
                value: (report.sleep?.avgAsleepHours).map { "\($0.compactString) h" } ?? "—",
                subtitle: nil,
                systemImage: "moon.zzz.fill",
                tint: Theme.sleep,
                progress: nil)
        }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            report = try await APIClient.shared.weeklyReport()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}
