import SwiftUI

struct FoodView: View {
    @Environment(AppState.self) private var appState

    @State private var model = FoodViewModel()
    @State private var addSheet: AddFoodSheet?
    @State private var showDatePicker = false

    enum AddFoodSheet: Identifiable {
        case search
        case favorites
        case manual
        case photo

        var id: Int {
            switch self {
            case .search: return 0
            case .favorites: return 1
            case .manual: return 2
            case .photo: return 3
            }
        }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    dayNavigator

                    if let error = model.errorMessage {
                        ErrorBanner(message: error) {
                            model.errorMessage = nil
                            Task { await model.load() }
                        }
                    }

                    totalsCard
                    WaterCard(model: model)
                    mealSections
                }
                .padding(.horizontal)
                .padding(.bottom, 24)
            }
            .background(Theme.background)
            .navigationTitle(L.Food.title)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button(L.Food.searchFoods, systemImage: "magnifyingglass") {
                            addSheet = .search
                        }
                        Button(L.Food.favorites, systemImage: "star.fill") {
                            addSheet = .favorites
                        }
                        Button(L.Food.photo, systemImage: "camera.fill") {
                            addSheet = .photo
                        }
                        Button(L.Food.manualEntry, systemImage: "square.and.pencil") {
                            addSheet = .manual
                        }
                    } label: {
                        Image(systemName: "plus.circle.fill")
                            .font(.title3)
                    }
                }
            }
            .sheet(item: $addSheet) { sheet in
                switch sheet {
                case .search:
                    FoodSearchView(date: model.dateString, defaultMeal: appState.suggestedMeal) {
                        Task { await model.load() }
                    }
                case .favorites:
                    FavoritesSheet(model: model, defaultMeal: appState.suggestedMeal)
                case .manual:
                    AddFoodFormView(
                        form: FoodFormData(meal: appState.suggestedMeal, date: model.dateString)
                    ) {
                        Task { await model.load() }
                    }
                case .photo:
                    PhotoAnalysisView(date: model.dateString, defaultMeal: appState.suggestedMeal) {
                        Task { await model.load() }
                    }
                }
            }
            .refreshable {
                await model.load()
            }
            .task {
                if model.log == nil {
                    await model.load()
                }
            }
        }
    }

    // MARK: - Day navigation

    private var dayNavigator: some View {
        HStack {
            Button {
                model.changeDay(by: -1)
            } label: {
                Image(systemName: "chevron.left.circle.fill")
                    .font(.title2)
                    .foregroundStyle(Theme.accent)
            }
            Spacer()
            Button {
                showDatePicker = true
            } label: {
                Text(Day.display(model.date))
                    .font(.headline)
            }
            .popover(isPresented: $showDatePicker) {
                DatePicker(
                    L.Body.date,
                    selection: Binding(
                        get: { model.date },
                        set: { newValue in
                            model.date = newValue
                            showDatePicker = false
                            Task { await model.load() }
                        }),
                    displayedComponents: .date)
                .datePickerStyle(.graphical)
                .frame(minWidth: 320)
                .presentationCompactAdaptation(.sheet)
            }
            Spacer()
            Button {
                model.changeDay(by: 1)
            } label: {
                Image(systemName: "chevron.right.circle.fill")
                    .font(.title2)
                    .foregroundStyle(model.isToday ? Color.secondary : Theme.accent)
            }
            .disabled(model.isToday)
        }
        .padding(.top, 4)
    }

    // MARK: - Totals

    private var totalsCard: some View {
        let totals = model.log?.totals
        return VStack(spacing: 10) {
            MacroBar(
                label: L.Today.calories,
                value: totals?.kcal ?? 0,
                goal: appState.dailyGoalTarget("calories"),
                unit: "kcal",
                tint: Theme.calories)
            MacroBar(
                label: L.Today.protein,
                value: totals?.protein ?? 0,
                goal: appState.dailyGoalTarget("protein"),
                unit: "g",
                tint: Theme.protein)
            MacroBar(
                label: L.Food.carbs,
                value: totals?.carbs ?? 0,
                goal: appState.dailyGoalTarget("carbs"),
                unit: "g",
                tint: Theme.carbs)
            MacroBar(
                label: L.Food.fat,
                value: totals?.fat ?? 0,
                goal: appState.dailyGoalTarget("fat"),
                unit: "g",
                tint: Theme.fat)
        }
        .cardStyle()
    }

    // MARK: - Meals

    private var mealSections: some View {
        ForEach(appState.meals, id: \.self) { meal in
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text(meal.capitalized)
                        .font(.headline)
                    Spacer()
                    let entries = model.entries(for: meal)
                    if !entries.isEmpty {
                        Text("\((entries.reduce(0) { $0 + ($1.kcal ?? 0) }).intString) kcal")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }
                let entries = model.entries(for: meal)
                if entries.isEmpty {
                    Text(L.Food.emptyMeal)
                        .font(.footnote)
                        .foregroundStyle(.tertiary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .cardStyle()
                } else {
                    ForEach(entries) { entry in
                        FoodEntryRow(entry: entry)
                            .contextMenu {
                                moveMenu(for: entry, currentMeal: meal)
                                Button(L.Food.deleteEntry, systemImage: "trash", role: .destructive) {
                                    Task { await model.delete(entry) }
                                }
                            }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func moveMenu(for entry: FoodEntry, currentMeal: String) -> some View {
        Menu(L.Food.moveTo) {
            ForEach(appState.meals.filter { $0 != currentMeal }, id: \.self) { meal in
                Button(meal.capitalized) {
                    Task { await model.move(entry, to: meal) }
                }
            }
        }
    }
}

// MARK: - Rows

struct FoodEntryRow: View {
    let entry: FoodEntry

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(entry.name)
                    .font(.subheadline.weight(.medium))
                HStack(spacing: 6) {
                    if let qty = entry.qty, qty != 1 {
                        Text("×\(qty.compactString)")
                    }
                    if let serving = entry.serving, !serving.isEmpty {
                        Text(serving)
                    }
                    Text("P \( (entry.protein ?? 0).intString ) · C \( (entry.carbs ?? 0).intString ) · F \( (entry.fat ?? 0).intString )")
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            Spacer()
            Text("\((entry.kcal ?? 0).intString) kcal")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.calories)
        }
        .cardStyle()
    }
}

// MARK: - Water card

struct WaterCard: View {
    @Bindable var model: FoodViewModel
    @State private var showCustom = false
    @State private var customAmount: Double = 500
    @State private var showEntries = false

    private var total: Double { model.water?.totalMl ?? 0 }
    private var goal: Double { model.water?.goalMl ?? 0 }

    var body: some View {
        VStack(spacing: 12) {
            HStack(spacing: 16) {
                ProgressRing(
                    progress: goal > 0 ? total / goal : 0,
                    color: Theme.water,
                    lineWidth: 8
                ) {
                    Image(systemName: "drop.fill")
                        .foregroundStyle(Theme.water)
                }
                .frame(width: 54, height: 54)

                VStack(alignment: .leading, spacing: 2) {
                    Text(L.Water.title)
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(.secondary)
                    Text(WaterUnits.display(ml: total))
                        .font(.title3.bold())
                    if goal > 0 {
                        Text("\(Int((total / goal * 100).rounded()))% \(L.Water.ofGoal) (\(WaterUnits.display(ml: goal)))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
            }

            HStack(spacing: 8) {
                waterButton(L.Water.add8oz, ml: 237)
                waterButton(L.Water.add16oz, ml: 473)
                Button {
                    showCustom = true
                } label: {
                    Text(L.Water.custom)
                        .font(.footnote.weight(.semibold))
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .tint(Theme.water)
            }

            if let entries = model.water?.entries, !entries.isEmpty {
                DisclosureGroup(L.Water.history, isExpanded: $showEntries) {
                    ForEach(entries) { entry in
                        HStack {
                            Text(WaterUnits.display(ml: entry.amountMl))
                                .font(.subheadline)
                            Spacer()
                            if let created = entry.createdAt {
                                Text(Timestamp.display(created))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Button {
                                Task { await model.deleteWater(entry) }
                            } label: {
                                Image(systemName: "trash")
                                    .font(.caption)
                                    .foregroundStyle(Theme.danger)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }
                .font(.footnote)
            }
        }
        .cardStyle()
        .alert(L.Water.customTitle, isPresented: $showCustom) {
            TextField(
                WaterUnits.preferOunces ? L.Water.amountOz : L.Water.amountMl,
                value: $customAmount,
                format: .number)
                .keyboardType(.decimalPad)
            Button(L.Common.add) {
                let ml = WaterUnits.preferOunces ? customAmount * WaterUnits.mlPerFlOz : customAmount
                Task { await model.addWater(ml: ml) }
            }
            Button(L.Common.cancel, role: .cancel) {}
        }
    }

    private func waterButton(_ label: String, ml: Double) -> some View {
        Button {
            Task { await model.addWater(ml: ml) }
        } label: {
            Text(label)
                .font(.footnote.weight(.semibold))
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .tint(Theme.water)
    }
}
