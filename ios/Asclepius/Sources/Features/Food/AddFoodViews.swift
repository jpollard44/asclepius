import SwiftUI

// MARK: - Shared form data

/// Editable state for the add/review food form, prefillable from a database
/// item or an AI photo estimate.
struct FoodFormData {
    var name = ""
    var meal: String
    var qty: Double = 1
    var serving = ""
    var kcal: Double = 0
    var protein: Double = 0
    var carbs: Double = 0
    var fat: Double = 0
    var fiber: Double?
    var sugar: Double?
    var sodium: Double?
    var date: String
    var foodId: Int?
    var aiNotes: String?

    init(meal: String, date: String) {
        self.meal = meal
        self.date = date
    }

    init(item: FoodItem, meal: String, date: String) {
        self.init(meal: meal, date: date)
        name = item.name
        serving = item.serving ?? ""
        kcal = item.kcal ?? 0
        protein = item.protein ?? 0
        carbs = item.carbs ?? 0
        fat = item.fat ?? 0
        foodId = item.id
    }

    init(estimate: FoodEstimate, meal: String, date: String) {
        self.init(meal: meal, date: date)
        name = estimate.name ?? ""
        serving = estimate.serving ?? ""
        kcal = estimate.kcal ?? 0
        protein = estimate.protein ?? 0
        carbs = estimate.carbs ?? 0
        fat = estimate.fat ?? 0
        fiber = estimate.fiber
        sugar = estimate.sugar
        sodium = estimate.sodium
        var notes: [String] = []
        if let confidence = estimate.confidence {
            notes.append(confidence)
        }
        if let extra = estimate.notes, !extra.isEmpty {
            notes.append(extra)
        }
        aiNotes = notes.isEmpty ? nil : notes.joined(separator: " — ")
    }

    var request: NewFoodEntry {
        NewFoodEntry(
            name: name.trimmingCharacters(in: .whitespaces),
            kcal: kcal,
            protein: protein,
            carbs: carbs,
            fat: fat,
            meal: meal,
            qty: qty,
            serving: serving,
            date: date,
            foodId: foodId,
            fiber: fiber,
            sugar: sugar,
            sodium: sodium)
    }

    var isValid: Bool {
        !name.trimmingCharacters(in: .whitespaces).isEmpty
    }
}

// MARK: - Add/review form

struct AddFoodFormView: View {
    @State var form: FoodFormData
    var onSaved: () -> Void

    @Environment(\.dismiss) private var dismiss
    @Environment(AppState.self) private var appState
    @State private var saving = false
    @State private var saveAsCustom = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                if let notes = form.aiNotes {
                    Section {
                        Label {
                            Text("\(L.Food.analysisNote) \(notes)")
                                .font(.footnote)
                        } icon: {
                            Image(systemName: "sparkles")
                                .foregroundStyle(Theme.accent)
                        }
                    }
                }

                Section {
                    TextField(L.Food.name, text: $form.name)
                    Picker(L.Food.meal, selection: $form.meal) {
                        ForEach(appState.meals, id: \.self) { meal in
                            Text(meal.capitalized).tag(meal)
                        }
                    }
                    HStack {
                        Text(L.Food.quantity)
                        Spacer()
                        TextField(L.Food.quantity, value: $form.qty, format: .number)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .frame(width: 80)
                        Stepper("", value: $form.qty, in: 0.25 ... 20, step: 0.25)
                            .labelsHidden()
                    }
                    TextField(L.Food.serving, text: $form.serving)
                }

                Section {
                    numberRow(L.Food.kcal, value: $form.kcal)
                    numberRow(L.Food.proteinG, value: $form.protein)
                    numberRow(L.Food.carbsG, value: $form.carbs)
                    numberRow(L.Food.fatG, value: $form.fat)
                }

                Section(L.Common.optional) {
                    optionalNumberRow(L.Food.fiberG, value: $form.fiber)
                    optionalNumberRow(L.Food.sugarG, value: $form.sugar)
                    optionalNumberRow(L.Food.sodiumMg, value: $form.sodium)
                }

                if form.foodId == nil {
                    Section {
                        Toggle(L.Food.saveAsCustomFood, isOn: $saveAsCustom)
                    }
                }
            }
            .navigationTitle(form.aiNotes == nil ? L.Food.addFood : L.Food.editEntry)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(L.Common.cancel) { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L.Common.save) {
                        Task { await save() }
                    }
                    .disabled(!form.isValid || saving)
                }
            }
            .overlay {
                if saving { LoadingOverlay() }
            }
            .errorAlert(message: $errorMessage)
        }
    }

    private func numberRow(_ label: String, value: Binding<Double>) -> some View {
        HStack {
            Text(label)
            Spacer()
            TextField(label, value: value, format: .number)
                .keyboardType(.decimalPad)
                .multilineTextAlignment(.trailing)
                .frame(width: 100)
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

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            _ = try await APIClient.shared.addFood(form.request)
            if saveAsCustom {
                _ = try? await APIClient.shared.createCustomFood(NewCustomFood(
                    name: form.name,
                    kcal: form.kcal,
                    protein: form.protein,
                    carbs: form.carbs,
                    fat: form.fat,
                    serving: form.serving))
            }
            Haptics.success()
            onSaved()
            dismiss()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}

// MARK: - Search

struct FoodSearchView: View {
    let date: String
    let defaultMeal: String
    var onLogged: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var results: [FoodItem] = []
    @State private var searching = false
    @State private var selected: FoodItem?
    @State private var searchTask: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            List {
                if results.isEmpty && !query.isEmpty && !searching {
                    Text(L.Food.noResults)
                        .foregroundStyle(.secondary)
                }
                ForEach(results) { item in
                    Button {
                        selected = item
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.name)
                                .font(.subheadline.weight(.medium))
                                .foregroundStyle(.primary)
                            HStack(spacing: 8) {
                                if let serving = item.serving, !serving.isEmpty {
                                    Text(serving)
                                }
                                Text("\((item.kcal ?? 0).intString) kcal")
                                Text("P \((item.protein ?? 0).compactString)g")
                            }
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .searchable(text: $query, prompt: L.Food.searchPrompt)
            .onChange(of: query) { _, newValue in
                scheduleSearch(newValue)
            }
            .navigationTitle(L.Food.searchFoods)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(L.Common.cancel) { dismiss() }
                }
            }
            .overlay {
                if searching { ProgressView() }
            }
            .sheet(item: $selected) { item in
                AddFoodFormView(
                    form: FoodFormData(item: item, meal: defaultMeal, date: date)
                ) {
                    onLogged()
                    dismiss()
                }
            }
            .task {
                scheduleSearch("")
            }
        }
    }

    private func scheduleSearch(_ text: String) {
        searchTask?.cancel()
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard !Task.isCancelled else { return }
            searching = true
            defer { searching = false }
            if let response = try? await APIClient.shared.searchFoods(text) {
                if !Task.isCancelled {
                    results = response.foods ?? []
                }
            }
        }
    }
}

// MARK: - Favorites

struct FavoritesSheet: View {
    @Bindable var model: FoodViewModel
    let defaultMeal: String

    @Environment(\.dismiss) private var dismiss
    @State private var editing: Favorite?
    @State private var creating = false
    @State private var justLoggedID: Int?

    var body: some View {
        NavigationStack {
            List {
                if model.favorites.isEmpty {
                    Text(L.Food.noFavorites)
                        .foregroundStyle(.secondary)
                }
                ForEach(model.favorites) { favorite in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(favorite.name)
                                .font(.subheadline.weight(.medium))
                            HStack(spacing: 8) {
                                Text("\((favorite.calories ?? 0).intString) kcal")
                                Text("P \((favorite.proteinG ?? 0).compactString)g")
                                if let desc = favorite.description, !desc.isEmpty {
                                    Text(desc).lineLimit(1)
                                }
                            }
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }
                        Spacer()
                        if justLoggedID == favorite.id {
                            Label(L.Food.favoriteLogged, systemImage: "checkmark.circle.fill")
                                .labelStyle(.iconOnly)
                                .foregroundStyle(Theme.green)
                        } else {
                            Button {
                                justLoggedID = favorite.id
                                Task {
                                    await model.logFavorite(favorite, meal: defaultMeal)
                                    try? await Task.sleep(nanoseconds: 1_200_000_000)
                                    justLoggedID = nil
                                }
                            } label: {
                                Image(systemName: "plus.circle.fill")
                                    .font(.title3)
                                    .foregroundStyle(Theme.accent)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .contentShape(Rectangle())
                    .contextMenu {
                        Button(L.Common.edit, systemImage: "pencil") {
                            editing = favorite
                        }
                        Button(L.Common.delete, systemImage: "trash", role: .destructive) {
                            Task {
                                try? await APIClient.shared.deleteFavorite(id: favorite.id)
                                await model.loadFavorites()
                            }
                        }
                    }
                }
            }
            .navigationTitle(L.Food.favorites)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(L.Common.done) { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        creating = true
                    } label: {
                        Image(systemName: "plus")
                    }
                }
            }
            .sheet(isPresented: $creating) {
                FavoriteEditorView(favorite: nil) {
                    Task { await model.loadFavorites() }
                }
            }
            .sheet(item: $editing) { favorite in
                FavoriteEditorView(favorite: favorite) {
                    Task { await model.loadFavorites() }
                }
            }
            .task {
                await model.loadFavorites()
            }
        }
    }
}

struct FavoriteEditorView: View {
    let favorite: Favorite?
    var onSaved: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var description = ""
    @State private var calories: Double = 0
    @State private var protein: Double = 0
    @State private var carbs: Double = 0
    @State private var fat: Double = 0
    @State private var category = "snack"
    @State private var saving = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(L.Food.name, text: $name)
                    TextField(L.Common.optional, text: $description)
                }
                Section {
                    row(L.Food.kcal, value: $calories)
                    row(L.Food.proteinG, value: $protein)
                    row(L.Food.carbsG, value: $carbs)
                    row(L.Food.fatG, value: $fat)
                }
            }
            .navigationTitle(favorite == nil ? L.Food.newFavorite : L.Food.editFavorite)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(L.Common.cancel) { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L.Common.save) {
                        Task { await save() }
                    }
                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || saving)
                }
            }
            .errorAlert(message: $errorMessage)
            .onAppear {
                if let favorite {
                    name = favorite.name
                    description = favorite.description ?? ""
                    calories = favorite.calories ?? 0
                    protein = favorite.proteinG ?? 0
                    carbs = favorite.carbsG ?? 0
                    fat = favorite.fatG ?? 0
                    category = favorite.category ?? "snack"
                }
            }
        }
    }

    private func row(_ label: String, value: Binding<Double>) -> some View {
        HStack {
            Text(label)
            Spacer()
            TextField(label, value: value, format: .number)
                .keyboardType(.decimalPad)
                .multilineTextAlignment(.trailing)
                .frame(width: 100)
        }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        let body = NewFavorite(
            name: name.trimmingCharacters(in: .whitespaces),
            description: description,
            calories: calories,
            proteinG: protein,
            carbsG: carbs,
            fatG: fat,
            category: category)
        do {
            if let favorite {
                _ = try await APIClient.shared.updateFavorite(id: favorite.id, body)
            } else {
                _ = try await APIClient.shared.createFavorite(body)
            }
            Haptics.success()
            onSaved()
            dismiss()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}
