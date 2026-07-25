import Charts
import SwiftUI

@MainActor
@Observable
final class FitnessViewModel {
    private let api = APIClient.shared

    private(set) var workouts: [Workout] = []
    private(set) var summary: WorkoutsSummary?
    private(set) var volume: WorkoutVolumeResponse?
    private(set) var isLoading = false
    var errorMessage: String?

    struct WorkoutGroup: Identifiable {
        let date: String
        let workouts: [Workout]

        var id: String { date }
    }

    /// Workouts grouped by date, newest first.
    var byDate: [WorkoutGroup] {
        let grouped = Dictionary(grouping: workouts) { $0.date ?? "" }
        return grouped
            .sorted { $0.key > $1.key }
            .map { WorkoutGroup(date: $0.key, workouts: $0.value) }
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        async let workoutsTask = try? api.workouts(days: 90)
        async let volumeTask = try? api.workoutVolume(days: 30)
        let (response, volume) = await (workoutsTask, volumeTask)
        if let response {
            workouts = response.workouts ?? []
            summary = response.summary
            errorMessage = nil
        } else {
            errorMessage = L.Common.error
        }
        if let volume {
            self.volume = volume
        }
    }

    func delete(_ workout: Workout) async {
        do {
            try await api.deleteWorkout(id: workout.id)
            Haptics.success()
            await load()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}

struct FitnessView: View {
    @State private var model = FitnessViewModel()
    @State private var showAdd = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let error = model.errorMessage {
                        ErrorBanner(message: error) {
                            model.errorMessage = nil
                            Task { await model.load() }
                        }
                    }

                    summaryRow
                    volumeChart

                    if model.workouts.isEmpty && !model.isLoading {
                        EmptyState(
                            icon: "dumbbell",
                            title: L.Fitness.emptyTitle,
                            message: L.Fitness.emptyBody,
                            actionTitle: L.Fitness.addWorkout
                        ) {
                            showAdd = true
                        }
                    } else {
                        workoutList
                    }
                }
                .padding(.horizontal)
                .padding(.bottom, 24)
            }
            .background(Theme.background)
            .navigationTitle(L.Fitness.title)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    NavigationLink {
                        PRsView()
                    } label: {
                        Label(L.Fitness.prs, systemImage: "trophy")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showAdd = true
                    } label: {
                        Image(systemName: "plus.circle.fill")
                            .font(.title3)
                    }
                }
            }
            .sheet(isPresented: $showAdd) {
                AddWorkoutView {
                    Task { await model.load() }
                }
            }
            .navigationDestination(for: Workout.self) { workout in
                WorkoutDetailView(workout: workout) {
                    Task { await model.delete(workout) }
                }
            }
            .refreshable {
                await model.load()
            }
            .task {
                if model.workouts.isEmpty {
                    await model.load()
                }
            }
        }
    }

    // MARK: - Summary

    @ViewBuilder
    private var summaryRow: some View {
        if let summary = model.summary, let total = summary.totalWorkouts, total > 0 {
            HStack(spacing: 12) {
                StatCard(
                    title: L.Fitness.sessions,
                    value: "\(total)",
                    subtitle: "\(summary.windowDays ?? 90)d",
                    systemImage: "figure.strengthtraining.traditional",
                    tint: Theme.accent,
                    progress: nil)
                if let volume = model.volume, let totalVolume = volume.totalVolume, totalVolume > 0 {
                    StatCard(
                        title: L.Fitness.volume,
                        value: totalVolume.intString,
                        subtitle: "30d",
                        systemImage: "scalemass",
                        tint: Theme.protein,
                        progress: nil)
                }
            }
        }
    }

    // MARK: - Volume chart

    @ViewBuilder
    private var volumeChart: some View {
        if let series = model.volume?.series, series.count > 1 {
            VStack(alignment: .leading, spacing: 8) {
                SectionHeader(title: L.Fitness.volume)
                Chart(series) { point in
                    BarMark(
                        x: .value("Date", Day.date(from: point.date) ?? Date(), unit: .day),
                        y: .value("Volume", point.volume ?? 0))
                    .foregroundStyle(Theme.accent)
                }
                .frame(height: 140)
            }
            .cardStyle()
        }
    }

    // MARK: - Workout list

    private var workoutList: some View {
        ForEach(model.byDate) { group in
            VStack(alignment: .leading, spacing: 8) {
                Text(Day.display(group.date))
                    .font(.headline)
                ForEach(group.workouts) { workout in
                    NavigationLink(value: workout) {
                        WorkoutRow(workout: workout)
                    }
                    .buttonStyle(.plain)
                    .contextMenu {
                        if !workout.isFromHealthKit {
                            Button(L.Fitness.deleteWorkout, systemImage: "trash", role: .destructive) {
                                Task { await model.delete(workout) }
                            }
                        }
                    }
                }
            }
        }
    }
}

extension Workout: Hashable {
    static func == (lhs: Workout, rhs: Workout) -> Bool {
        lhs.id == rhs.id && lhs.date == rhs.date
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }
}

struct WorkoutRow: View {
    let workout: Workout

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(Theme.accent)
                .frame(width: 34)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(workout.activity ?? "Workout")
                        .font(.subheadline.weight(.semibold))
                    if workout.isFromHealthKit {
                        Text(L.Fitness.fromHealthKit)
                            .font(.caption2.weight(.medium))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Theme.heart.opacity(0.12), in: Capsule())
                            .foregroundStyle(Theme.heart)
                    }
                }
                Text(detailLine)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Image(systemName: "chevron.right")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }
        .cardStyle()
    }

    private var icon: String {
        if workout.isStrength { return "dumbbell.fill" }
        if workout.type == "cardio" { return "figure.run" }
        return "figure.mixed.cardio"
    }

    private var detailLine: String {
        var parts: [String] = []
        if let duration = workout.durationMin, duration > 0 {
            parts.append("\(duration.intString) min")
        }
        if let distance = workout.distanceKm, distance > 0 {
            parts.append("\(distance.compactString) km")
        }
        if let energy = workout.energyKcal, energy > 0 {
            parts.append("\(energy.intString) kcal")
        }
        if let exercises = workout.exercises, !exercises.isEmpty {
            parts.append("\(exercises.count) \(L.Fitness.exercises.lowercased())")
        }
        return parts.isEmpty ? (workout.type ?? "") : parts.joined(separator: " · ")
    }
}
