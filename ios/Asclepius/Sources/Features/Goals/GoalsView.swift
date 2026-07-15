import SwiftUI

struct GoalsView: View {
    @Environment(AppState.self) private var appState

    @State private var goals: [Goal] = []
    @State private var isLoading = false
    @State private var showEditor = false
    @State private var editingGoal: Goal?
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

                if goals.isEmpty && !isLoading {
                    EmptyState(
                        icon: "target",
                        title: L.Goals.emptyTitle,
                        message: L.Goals.emptyBody,
                        actionTitle: L.Goals.newGoal
                    ) {
                        showEditor = true
                    }
                }

                ForEach(goals) { goal in
                    GoalProgressRow(goal: goal)
                        .contextMenu {
                            Button(L.Common.edit, systemImage: "pencil") {
                                editingGoal = goal
                            }
                            Button(L.Goals.markComplete, systemImage: "checkmark.circle") {
                                Task { await complete(goal) }
                            }
                            Button(L.Common.delete, systemImage: "trash", role: .destructive) {
                                Task { await delete(goal) }
                            }
                        }
                }
            }
            .padding(.horizontal)
            .padding(.bottom, 24)
        }
        .background(Theme.background)
        .navigationTitle(L.Goals.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    showEditor = true
                } label: {
                    Image(systemName: "plus.circle.fill")
                }
            }
        }
        .sheet(isPresented: $showEditor) {
            GoalEditorView(goal: nil, categories: appState.goalCategories) {
                Task { await load() }
            }
        }
        .sheet(item: $editingGoal) { goal in
            GoalEditorView(goal: goal, categories: appState.goalCategories) {
                Task { await load() }
            }
        }
        .refreshable {
            await load()
        }
        .task {
            if goals.isEmpty {
                await load()
            }
        }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await APIClient.shared.goals(status: "active")
            goals = response.goals ?? []
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }

    private func complete(_ goal: Goal) async {
        do {
            _ = try await APIClient.shared.updateGoal(id: goal.id, GoalUpdate(status: "completed"))
            Haptics.success()
            await load()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }

    private func delete(_ goal: Goal) async {
        do {
            try await APIClient.shared.deleteGoal(id: goal.id)
            await load()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}

// MARK: - Editor

struct GoalEditorView: View {
    let goal: Goal?
    let categories: [String: GoalCategory]
    var onSaved: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var category = "weight"
    @State private var label = ""
    @State private var target: Double?
    @State private var baseline: Double?
    @State private var unit = ""
    @State private var direction = "increase"
    @State private var hasTargetDate = false
    @State private var targetDate = Day.adding(30, to: Date())
    @State private var notes = ""
    @State private var saving = false
    @State private var errorMessage: String?

    private struct CategoryOption: Identifiable {
        let key: String
        let label: String

        var id: String { key }
    }

    private var categoryOptions: [CategoryOption] {
        let source = categories.isEmpty
            ? ["weight": GoalCategory(label: "Weight", metric: "body_mass", unit: "kg"),
               "steps": GoalCategory(label: "Daily steps", metric: "steps", unit: "steps"),
               "custom": GoalCategory(label: "Custom", metric: nil, unit: "")]
            : categories
        return source
            .map { CategoryOption(key: $0.key, label: $0.value.label ?? $0.key) }
            .sorted { $0.label < $1.label }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker(L.Goals.category, selection: $category) {
                        ForEach(categoryOptions) { option in
                            Text(option.label).tag(option.key)
                        }
                    }
                    .disabled(goal != nil)
                    .onChange(of: category) { _, newValue in
                        if unit.isEmpty || goal == nil {
                            unit = categories[newValue]?.unit ?? ""
                        }
                    }
                    TextField(L.Goals.label, text: $label)
                }

                Section {
                    numberRow(L.Goals.target, value: $target)
                    numberRow(L.Goals.baseline, value: $baseline)
                    TextField(L.Goals.unit, text: $unit)
                    Picker(L.Goals.direction, selection: $direction) {
                        Text(L.Goals.increase).tag("increase")
                        Text(L.Goals.decrease).tag("decrease")
                        Text(L.Goals.maintain).tag("maintain")
                    }
                }

                Section {
                    Toggle(L.Goals.targetDate, isOn: $hasTargetDate)
                    if hasTargetDate {
                        DatePicker(L.Goals.targetDate, selection: $targetDate, displayedComponents: .date)
                    }
                    TextField(L.Goals.notes, text: $notes, axis: .vertical)
                        .lineLimit(2 ... 4)
                }
            }
            .navigationTitle(goal == nil ? L.Goals.newGoal : L.Goals.editGoal)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(L.Common.cancel) { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L.Common.save) {
                        Task { await save() }
                    }
                    .disabled(saving)
                }
            }
            .errorAlert(message: $errorMessage)
            .onAppear {
                if let goal {
                    category = goal.category ?? "custom"
                    label = goal.label ?? ""
                    target = goal.target
                    baseline = goal.baseline
                    unit = goal.unit ?? ""
                    direction = goal.direction ?? "increase"
                    notes = goal.notes ?? ""
                    if let dateString = goal.targetDate, let date = Day.date(from: dateString) {
                        hasTargetDate = true
                        targetDate = date
                    }
                } else {
                    unit = categories[category]?.unit ?? ""
                }
            }
        }
    }

    private func numberRow(_ label: String, value: Binding<Double?>) -> some View {
        HStack {
            Text(label)
            Spacer()
            TextField(L.Common.none, value: value, format: .number)
                .keyboardType(.decimalPad)
                .multilineTextAlignment(.trailing)
                .frame(width: 100)
        }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            if let goal {
                _ = try await APIClient.shared.updateGoal(id: goal.id, GoalUpdate(
                    label: label,
                    target: target,
                    baseline: baseline,
                    unit: unit,
                    direction: direction,
                    targetDate: hasTargetDate ? Day.string(from: targetDate) : nil,
                    notes: notes))
            } else {
                _ = try await APIClient.shared.createGoal(NewGoal(
                    category: category,
                    label: label,
                    target: target,
                    baseline: baseline,
                    unit: unit,
                    direction: direction,
                    targetDate: hasTargetDate ? Day.string(from: targetDate) : nil,
                    notes: notes))
            }
            Haptics.success()
            onSaved()
            dismiss()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}
