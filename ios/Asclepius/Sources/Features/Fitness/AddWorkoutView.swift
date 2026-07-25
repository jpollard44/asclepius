import SwiftUI

/// Log a workout: strength gets an exercise/sets editor, cardio and other get
/// duration/distance/energy fields.
struct AddWorkoutView: View {
    var onSaved: () -> Void

    @Environment(\.dismiss) private var dismiss
    @Environment(AppState.self) private var appState

    @State private var type = "strength"
    @State private var activity = ""
    @State private var date = Date()
    @State private var durationMin: Double?
    @State private var distanceKm: Double?
    @State private var energyKcal: Double?
    @State private var notes = ""
    @State private var exercises: [Exercise] = [Exercise(name: "", sets: [ExerciseSet()])]
    @State private var saving = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker(L.Fitness.workoutType, selection: $type) {
                        ForEach(appState.workoutTypes, id: \.self) { t in
                            Text(t.capitalized).tag(t)
                        }
                    }
                    .pickerStyle(.segmented)
                    TextField(L.Fitness.activity, text: $activity)
                    DatePicker(L.Body.date, selection: $date, displayedComponents: .date)
                }

                if type == "strength" {
                    exercisesSection
                } else {
                    Section {
                        optionalNumberRow(L.Fitness.duration, value: $durationMin)
                        optionalNumberRow(L.Fitness.distance, value: $distanceKm)
                        optionalNumberRow(L.Fitness.energy, value: $energyKcal)
                    }
                }

                Section {
                    TextField(L.Fitness.notes, text: $notes, axis: .vertical)
                        .lineLimit(2 ... 4)
                }
            }
            .navigationTitle(L.Fitness.addWorkout)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(L.Common.cancel) { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L.Common.save) {
                        Task { await save() }
                    }
                    .disabled(saving || !isValid)
                }
            }
            .overlay {
                if saving { LoadingOverlay() }
            }
            .errorAlert(message: $errorMessage)
        }
    }

    private var isValid: Bool {
        if type == "strength" {
            return exercises.contains { !$0.name.trimmingCharacters(in: .whitespaces).isEmpty }
        }
        return !activity.trimmingCharacters(in: .whitespaces).isEmpty || durationMin != nil
    }

    // MARK: - Strength editor

    private var exercisesSection: some View {
        Section(L.Fitness.exercises) {
            ForEach($exercises) { $exercise in
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        TextField(L.Fitness.exerciseName, text: $exercise.name)
                            .font(.subheadline.weight(.semibold))
                        Button {
                            exercises.removeAll { $0.id == exercise.id }
                        } label: {
                            Image(systemName: "minus.circle")
                                .foregroundStyle(Theme.danger)
                        }
                        .buttonStyle(.plain)
                    }

                    ForEach($exercise.sets) { $set in
                        let index = exercise.sets.firstIndex { $0.id == set.id } ?? 0
                        HStack(spacing: 12) {
                            Text("\(L.Fitness.set) \(index + 1)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .frame(width: 46, alignment: .leading)
                            TextField(L.Fitness.reps, value: $set.reps, format: .number)
                                .keyboardType(.numberPad)
                                .textFieldStyle(.roundedBorder)
                                .frame(width: 70)
                            Text("×")
                                .foregroundStyle(.secondary)
                            TextField(L.Fitness.weight, value: $set.weight, format: .number)
                                .keyboardType(.decimalPad)
                                .textFieldStyle(.roundedBorder)
                                .frame(width: 84)
                            Spacer()
                            Button {
                                exercise.sets.removeAll { $0.id == set.id }
                            } label: {
                                Image(systemName: "xmark.circle")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            .buttonStyle(.plain)
                        }
                    }

                    Button {
                        let last = exercise.sets.last
                        exercise.sets.append(ExerciseSet(reps: last?.reps, weight: last?.weight))
                    } label: {
                        Label(L.Fitness.addSet, systemImage: "plus")
                            .font(.footnote)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(Theme.accent)
                }
                .padding(.vertical, 4)
            }

            Button {
                exercises.append(Exercise(name: "", sets: [ExerciseSet()]))
            } label: {
                Label(L.Fitness.addExercise, systemImage: "plus.circle.fill")
            }
        }
    }

    private func optionalNumberRow(_ label: String, value: Binding<Double?>) -> some View {
        HStack {
            Text(label)
            Spacer()
            TextField(L.Common.none, value: value, format: .number)
                .keyboardType(.decimalPad)
                .multilineTextAlignment(.trailing)
                .frame(width: 100)
        }
    }

    // MARK: - Save

    private func save() async {
        saving = true
        defer { saving = false }

        let cleanedExercises = exercises
            .filter { !$0.name.trimmingCharacters(in: .whitespaces).isEmpty }
            .map { exercise in
                Exercise(
                    name: exercise.name.trimmingCharacters(in: .whitespaces),
                    sets: exercise.sets.filter { ($0.reps ?? 0) > 0 || ($0.weight ?? 0) > 0 })
            }

        let fallbackActivity = type == "strength" ? "Strength Training" : "Workout"
        let body = NewWorkout(
            activity: activity.trimmingCharacters(in: .whitespaces).isEmpty
                ? fallbackActivity
                : activity.trimmingCharacters(in: .whitespaces),
            type: type,
            date: Day.string(from: date),
            durationMin: durationMin,
            distanceKm: type == "strength" ? nil : distanceKm,
            energyKcal: type == "strength" ? nil : energyKcal,
            exercises: type == "strength" && !cleanedExercises.isEmpty ? cleanedExercises : nil,
            notes: notes)

        do {
            _ = try await APIClient.shared.addWorkout(body)
            Haptics.success()
            onSaved()
            dismiss()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}
