import SwiftUI

struct SettingsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(HealthKitManager.self) private var healthKit

    @State private var confirmSignOut = false
    @State private var confirmDelete = false
    @State private var deleting = false
    @State private var waterInOunces = WaterUnits.preferOunces
    @State private var errorMessage: String?

    var body: some View {
        List {
            accountSection

            Section {
                NavigationLink(L.Settings.dailyGoals) {
                    DailyGoalsEditorView()
                }
                NavigationLink(L.Settings.notifications) {
                    NotificationPrefsView()
                }
            }

            healthSection
            unitsSection
            aboutSection

            Section {
                Button(L.Settings.signOut, role: .destructive) {
                    confirmSignOut = true
                }
                Button(L.Settings.deleteAccount, role: .destructive) {
                    confirmDelete = true
                }
            }
        }
        .navigationTitle(L.Settings.title)
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog(L.Settings.signOutConfirm, isPresented: $confirmSignOut, titleVisibility: .visible) {
            Button(L.Settings.signOut, role: .destructive) {
                Task { await auth.signOut() }
            }
            Button(L.Common.cancel, role: .cancel) {}
        }
        .alert(L.Settings.deleteConfirmTitle, isPresented: $confirmDelete) {
            Button(L.Settings.deleteConfirmAction, role: .destructive) {
                Task { await deleteAccount() }
            }
            Button(L.Common.cancel, role: .cancel) {}
        } message: {
            Text(L.Settings.deleteConfirmBody)
        }
        .overlay {
            if deleting { LoadingOverlay() }
        }
        .errorAlert(message: $errorMessage)
        .onChange(of: waterInOunces) { _, newValue in
            WaterUnits.preferOunces = newValue
        }
    }

    // MARK: - Sections

    private var accountSection: some View {
        Section(L.Settings.account) {
            HStack(spacing: 12) {
                Image(systemName: "person.crop.circle.fill")
                    .font(.system(size: 38))
                    .foregroundStyle(Theme.accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(auth.user?.name ?? "—")
                        .font(.subheadline.weight(.semibold))
                    Text(auth.user?.email ?? "")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.vertical, 4)
        }
    }

    private var healthSection: some View {
        Section(L.Settings.healthSync) {
            HStack {
                Text(L.Settings.lastSync)
                Spacer()
                Text(healthKit.lastSyncDate.map {
                    $0.formatted(date: .abbreviated, time: .shortened)
                } ?? L.Settings.neverSynced)
                    .foregroundStyle(.secondary)
            }
            if healthKit.isSyncing {
                HStack {
                    ProgressView(value: healthKit.syncProgress)
                    Text(L.Settings.syncing)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } else {
                Button(L.Settings.syncNow) {
                    Task { await healthKit.syncNow() }
                }
                .disabled(!healthKit.isEnabled)
            }
            if let error = healthKit.lastError {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(Theme.danger)
            }
        }
    }

    private var unitsSection: some View {
        Section(L.Settings.units) {
            Toggle(L.Settings.waterInOz, isOn: $waterInOunces)
        }
    }

    private var aboutSection: some View {
        Section(L.Settings.about) {
            Link(L.Settings.privacyPolicy, destination: AppConfig.privacyPolicyURL)
            Link(L.Settings.website, destination: AppConfig.websiteURL)
            HStack {
                Text(L.Settings.version)
                Spacer()
                Text(appVersion)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var appVersion: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "1"
        return "\(version) (\(build))"
    }

    private func deleteAccount() async {
        deleting = true
        defer { deleting = false }
        do {
            try await auth.deleteAccount()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}
