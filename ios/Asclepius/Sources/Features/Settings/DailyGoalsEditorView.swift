import SwiftUI

/// Edit every personalized daily target, with per-metric reset-to-default.
struct DailyGoalsEditorView: View {
    @Environment(AppState.self) private var appState

    /// Staged edits: key → new target. nil marks a reset-to-default.
    @State private var edits: [String: Double?] = [:]
    @State private var values: [String: Double] = [:]
    @State private var saving = false
    @State private var errorMessage: String?

    /// Stable display order matching the backend catalogue.
    private let order = [
        "calories", "protein", "carbs", "fat", "fiber", "sugar", "sodium",
        "water", "steps", "active_energy", "sleep",
    ]

    private var orderedGoals: [DailyGoal] {
        let goals = appState.dailyGoals
        let known = order.compactMap { goals[$0] }
        let extra = goals.values
            .filter { !order.contains($0.key) }
            .sorted { $0.key < $1.key }
        return known + extra
    }

    var body: some View {
        List {
            Section(footer: Text(L.Settings.dailyGoalsFooter)) {
                ForEach(orderedGoals) { goal in
                    goalRow(goal)
                }
            }
        }
        .navigationTitle(L.Settings.dailyGoals)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button(L.Common.save) {
                    Task { await save() }
                }
                .disabled(edits.isEmpty || saving)
            }
        }
        .overlay {
            if saving { LoadingOverlay() }
        }
        .errorAlert(message: $errorMessage)
        .task {
            await appState.refreshDailyGoals()
            syncLocalValues()
        }
    }

    private func goalRow(_ goal: DailyGoal) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(goal.label ?? goal.key)
                    .font(.subheadline)
                if isCustomized(goal) {
                    Text(L.Settings.customized)
                        .font(.caption2)
                        .foregroundStyle(Theme.accent)
                }
            }
            Spacer()
            TextField(
                L.Common.goal,
                value: Binding(
                    get: { values[goal.key] ?? goal.target },
                    set: { newValue in
                        values[goal.key] = newValue
                        edits[goal.key] = newValue
                    }),
                format: .number)
                .keyboardType(.decimalPad)
                .multilineTextAlignment(.trailing)
                .frame(width: 90)
            Text(goal.unit ?? "")
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 38, alignment: .leading)
        }
        .swipeActions(edge: .trailing) {
            if isCustomized(goal) {
                Button(L.Settings.resetToDefault) {
                    values[goal.key] = goal.defaultTarget ?? goal.target
                    edits.updateValue(nil, forKey: goal.key)
                }
                .tint(Theme.accent)
            }
        }
        .contextMenu {
            Button(L.Settings.resetToDefault, systemImage: "arrow.counterclockwise") {
                values[goal.key] = goal.defaultTarget ?? goal.target
                edits.updateValue(nil, forKey: goal.key)
            }
        }
    }

    private func isCustomized(_ goal: DailyGoal) -> Bool {
        if let staged = edits[goal.key] {
            return staged != nil
        }
        return goal.customized ?? false
    }

    private func syncLocalValues() {
        for goal in appState.dailyGoals.values {
            values[goal.key] = goal.target
        }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            try await appState.updateDailyGoals(edits)
            edits = [:]
            syncLocalValues()
            Haptics.success()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}
