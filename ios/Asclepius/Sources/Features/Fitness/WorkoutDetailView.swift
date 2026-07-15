import Charts
import SwiftUI

/// Detail for one workout. Strength workouts list exercises with their sets
/// and link into the per-exercise progression view.
struct WorkoutDetailView: View {
    let workout: Workout
    var onDelete: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var confirmDelete = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header

                if let exercises = workout.exercises, !exercises.isEmpty {
                    exercisesSection(exercises)
                }

                if let notes = workout.notes, !notes.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        SectionHeader(title: L.Fitness.notes)
                        Text(notes)
                            .font(.body)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .cardStyle()
                    }
                }
            }
            .padding(.horizontal)
            .padding(.bottom, 24)
        }
        .background(Theme.background)
        .navigationTitle(workout.activity ?? "Workout")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if !workout.isFromHealthKit {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(role: .destructive) {
                        confirmDelete = true
                    } label: {
                        Image(systemName: "trash")
                    }
                }
            }
        }
        .confirmationDialog(L.Fitness.deleteWorkout, isPresented: $confirmDelete, titleVisibility: .visible) {
            Button(L.Common.delete, role: .destructive) {
                onDelete()
                dismiss()
            }
            Button(L.Common.cancel, role: .cancel) {}
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                if let date = workout.date {
                    Text(Day.display(date))
                        .font(.headline)
                }
                Spacer()
                if workout.isFromHealthKit {
                    Label(L.Fitness.fromHealthKit, systemImage: "heart.fill")
                        .font(.caption.weight(.medium))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(Theme.heart.opacity(0.12), in: Capsule())
                        .foregroundStyle(Theme.heart)
                }
            }
            HStack(spacing: 16) {
                if let duration = workout.durationMin, duration > 0 {
                    metric(value: "\(duration.intString)", unit: "min", icon: "clock")
                }
                if let distance = workout.distanceKm, distance > 0 {
                    metric(value: distance.compactString, unit: "km", icon: "point.topleft.down.curvedto.point.bottomright.up")
                }
                if let energy = workout.energyKcal, energy > 0 {
                    metric(value: energy.intString, unit: "kcal", icon: "flame.fill")
                }
            }
        }
        .cardStyle()
    }

    private func metric(value: String, unit: String, icon: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.footnote)
                .foregroundStyle(Theme.accent)
            Text(value)
                .font(.subheadline.bold())
            Text(unit)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func exercisesSection(_ exercises: [Exercise]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: L.Fitness.exercises)
            ForEach(exercises) { exercise in
                NavigationLink {
                    ExerciseHistoryView(exerciseName: exercise.name)
                } label: {
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text(exercise.name)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(.primary)
                            Spacer()
                            Image(systemName: "chart.line.uptrend.xyaxis")
                                .font(.caption)
                                .foregroundStyle(Theme.accent)
                        }
                        ForEach(Array(exercise.sets.enumerated()), id: \.element.id) { index, set in
                            HStack {
                                Text("\(L.Fitness.set) \(index + 1)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .frame(width: 48, alignment: .leading)
                                Text(setLine(set))
                                    .font(.caption.monospacedDigit())
                                Spacer()
                            }
                        }
                    }
                    .cardStyle()
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func setLine(_ set: ExerciseSet) -> String {
        let reps = set.reps.map { $0.compactString } ?? "—"
        if let weight = set.weight, weight > 0 {
            return "\(reps) × \(weight.compactString)"
        }
        return "\(reps) reps"
    }
}

// MARK: - Exercise progression

struct ExerciseHistoryView: View {
    let exerciseName: String

    @State private var sessions: [ExerciseSession] = []
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

                if sessions.count > 1 {
                    chartCard(
                        title: L.Fitness.est1RM,
                        values: sessions.map { ChartPoint(date: $0.date, value: $0.e1rm ?? 0) },
                        tint: Theme.accent)
                    chartCard(
                        title: L.Fitness.volume,
                        values: sessions.map { ChartPoint(date: $0.date, value: $0.volume ?? 0) },
                        tint: Theme.protein)
                }

                sessionList

                if sessions.isEmpty && !isLoading {
                    EmptyState(
                        icon: "chart.line.uptrend.xyaxis",
                        title: L.Common.noData,
                        message: L.Fitness.noPRs)
                }
            }
            .padding(.horizontal)
            .padding(.bottom, 24)
        }
        .background(Theme.background)
        .navigationTitle(exerciseName)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await load()
        }
    }

    private struct ChartPoint: Identifiable {
        let date: String
        let value: Double

        var id: String { date }
    }

    private func chartCard(title: String, values: [ChartPoint], tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: title)
            Chart(values) { point in
                LineMark(
                    x: .value("Date", Day.date(from: point.date) ?? Date()),
                    y: .value(title, point.value))
                .foregroundStyle(tint)
                PointMark(
                    x: .value("Date", Day.date(from: point.date) ?? Date()),
                    y: .value(title, point.value))
                .foregroundStyle(tint)
            }
            .frame(height: 150)
        }
        .cardStyle()
    }

    private var sessionList: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(sessions.reversed()) { session in
                HStack {
                    Text(Day.display(session.date))
                        .font(.subheadline.weight(.medium))
                    Spacer()
                    VStack(alignment: .trailing, spacing: 2) {
                        if let weight = session.topWeight, weight > 0 {
                            Text("\(L.Fitness.topSet): \(weight.compactString) × \((session.topReps ?? 0).compactString)")
                                .font(.caption)
                        }
                        HStack(spacing: 8) {
                            if let e1rm = session.e1rm, e1rm > 0 {
                                Text("1RM \(e1rm.compactString)")
                            }
                            if let volume = session.volume {
                                Text("Vol \(volume.intString)")
                            }
                        }
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    }
                }
                .cardStyle()
            }
        }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await APIClient.shared.exerciseHistory(name: exerciseName)
            sessions = response.sessions ?? []
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}

// MARK: - Personal records

struct PRsView: View {
    @State private var records: [PersonalRecord] = []
    @State private var isLoading = false
    @State private var errorMessage: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if let error = errorMessage {
                    ErrorBanner(message: error) {
                        errorMessage = nil
                        Task { await load() }
                    }
                }

                if records.isEmpty && !isLoading {
                    EmptyState(
                        icon: "trophy",
                        title: L.Common.noData,
                        message: L.Fitness.noPRs)
                }

                ForEach(records) { record in
                    NavigationLink {
                        ExerciseHistoryView(exerciseName: record.exercise)
                    } label: {
                        HStack {
                            Image(systemName: "trophy.fill")
                                .foregroundStyle(Theme.carbs)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(record.exercise)
                                    .font(.subheadline.weight(.semibold))
                                    .foregroundStyle(.primary)
                                if let date = record.date {
                                    Text(Day.display(date))
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            Spacer()
                            VStack(alignment: .trailing, spacing: 2) {
                                Text("\((record.weight ?? 0).compactString) × \((record.reps ?? 0).compactString)")
                                    .font(.subheadline.bold())
                                if let est = record.est1RM {
                                    Text("\(L.Fitness.est1RM) \(est.compactString)")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                        .cardStyle()
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal)
            .padding(.bottom, 24)
        }
        .background(Theme.background)
        .navigationTitle(L.Fitness.prs)
        .navigationBarTitleDisplayMode(.inline)
        .refreshable {
            await load()
        }
        .task {
            await load()
        }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await APIClient.shared.personalRecords()
            records = response.records ?? []
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}
