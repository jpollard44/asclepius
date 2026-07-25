import SwiftUI

/// Reminder preferences: master toggle, per-type toggles with time pickers,
/// and the do-not-disturb window. Changes save immediately.
struct NotificationPrefsView: View {
    @Environment(PushManager.self) private var push

    @State private var prefs: PushPrefsResponse?
    @State private var isLoading = false
    @State private var errorMessage: String?

    /// Preferred order matching the backend catalogue; unknown types follow.
    private let typeOrder = ["breakfast", "lunch", "dinner", "water", "workout", "sleep", "coach", "weekly"]

    private struct TypeEntry: Identifiable {
        let key: String
        let pref: PushTypePref

        var id: String { key }
    }

    private var orderedTypes: [TypeEntry] {
        guard let types = prefs?.types else { return [] }
        let known = typeOrder.compactMap { key in
            types[key].map { TypeEntry(key: key, pref: $0) }
        }
        let extra = types
            .filter { !typeOrder.contains($0.key) }
            .sorted { $0.key < $1.key }
            .map { TypeEntry(key: $0.key, pref: $0.value) }
        return known + extra
    }

    var body: some View {
        List {
            if push.authorizationStatus == .denied {
                Section {
                    Label(L.Push.notificationsDisabled, systemImage: "bell.slash")
                        .font(.footnote)
                        .foregroundStyle(Theme.warning)
                }
            }

            Section {
                Toggle(L.Settings.notifMaster, isOn: Binding(
                    get: { prefs?.enabled ?? false },
                    set: { newValue in
                        prefs?.enabled = newValue
                        save(PushPrefsUpdate(enabled: newValue))
                        if newValue {
                            Task { await push.requestAuthorization() }
                        }
                    }))
            }

            if prefs?.enabled == true {
                Section(L.Settings.dnd) {
                    dndPicker(L.Settings.dndStart, keyPath: \.dndStart) { update, time in
                        update.dndStart = time
                    }
                    dndPicker(L.Settings.dndEnd, keyPath: \.dndEnd) { update, time in
                        update.dndEnd = time
                    }
                }

                Section {
                    ForEach(orderedTypes) { entry in
                        typeRow(key: entry.key, pref: entry.pref)
                    }
                }
            }
        }
        .navigationTitle(L.Settings.notifications)
        .navigationBarTitleDisplayMode(.inline)
        .overlay {
            if isLoading && prefs == nil { ProgressView() }
        }
        .errorAlert(message: $errorMessage) {
            Task { await load() }
        }
        .task {
            await load()
            await push.refreshAuthorizationStatus()
        }
    }

    // MARK: - Rows

    private func dndPicker(
        _ label: String,
        keyPath: KeyPath<PushPrefsResponse, String?>,
        apply: @escaping (inout PushPrefsUpdate, String) -> Void
    ) -> some View {
        DatePicker(
            label,
            selection: Binding(
                get: { TimeOfDay.date(from: prefs?[keyPath: keyPath] ?? "22:00") },
                set: { newDate in
                    let time = TimeOfDay.string(from: newDate)
                    var update = PushPrefsUpdate()
                    apply(&update, time)
                    save(update)
                }),
            displayedComponents: .hourAndMinute)
    }

    private func typeRow(key: String, pref: PushTypePref) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Toggle(isOn: Binding(
                get: { pref.enabled ?? true },
                set: { newValue in
                    save(PushPrefsUpdate(types: [key: .init(enabled: newValue)]))
                })) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(pref.label ?? key.capitalized)
                        .font(.subheadline)
                    if let desc = pref.desc {
                        Text(desc)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            if pref.editableTime == true, pref.enabled ?? true, let time = pref.time {
                DatePicker(
                    L.Settings.time,
                    selection: Binding(
                        get: { TimeOfDay.date(from: time) },
                        set: { newDate in
                            save(PushPrefsUpdate(types: [key: .init(time: TimeOfDay.string(from: newDate))]))
                        }),
                    displayedComponents: .hourAndMinute)
                .font(.caption)
            }
        }
        .padding(.vertical, 2)
    }

    // MARK: - IO

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            prefs = try await APIClient.shared.pushPrefs()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }

    private func save(_ update: PushPrefsUpdate) {
        Task {
            do {
                prefs = try await APIClient.shared.updatePushPrefs(update)
            } catch {
                errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
                await load()
            }
        }
    }
}
