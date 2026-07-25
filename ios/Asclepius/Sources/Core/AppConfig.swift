import Foundation

/// Build-time configuration. The API base URL is injected through the
/// `AsclepiusAPIBaseURL` Info.plist key, which project.yml sets per build
/// configuration (Debug → http://localhost:8765, Release →
/// https://api.asclepius.health).
enum AppConfig {
    /// The backend base URL. Falls back to the production host if the
    /// Info.plist key is missing or malformed so the app never crashes on a
    /// misconfigured build.
    static let baseURL: URL = {
        if let raw = Bundle.main.object(forInfoDictionaryKey: "AsclepiusAPIBaseURL") as? String,
           !raw.isEmpty,
           let url = URL(string: raw.trimmingCharacters(in: .whitespacesAndNewlines)) {
            return url
        }
        #if DEBUG
        return URL(string: "http://localhost:8765")!
        #else
        return URL(string: "https://api.asclepius.health")!
        #endif
    }()

    /// Standard request timeout.
    static let requestTimeout: TimeInterval = 30

    /// Coach replies can take 30–120 s while the model reasons over the
    /// user's data, so chat calls use a much longer timeout.
    static let chatTimeout: TimeInterval = 180

    /// Keychain service used for token storage.
    static let keychainService = "com.asclepius.app"

    /// Background task identifiers (must match BGTaskSchedulerPermittedIdentifiers).
    static let backgroundRefreshTaskID = "com.asclepius.app.refresh"
    static let backgroundSyncTaskID = "com.asclepius.app.sync"

    /// How far back the initial HealthKit sync reaches (2 years).
    static let initialSyncDays = 730

    /// Trailing window re-synced on every run so late-arriving HealthKit
    /// samples (watch syncs, overnight sleep) are picked up.
    static let resyncOverlapDays = 7

    /// Maximum days of aggregates per sync POST.
    static let syncBatchDays = 120

    static let privacyPolicyURL = URL(string: "https://asclepius.health/privacy")!
    static let websiteURL = URL(string: "https://asclepius.health")!

    /// APNs environment reported to the backend when registering the device.
    static var apnsEnvironment: String {
        #if DEBUG
        return "sandbox"
        #else
        return "production"
        #endif
    }
}

/// UserDefaults keys, centralized so the privacy manifest reason stays honest.
enum DefaultsKey {
    static let onboardingComplete = "onboarding.complete"
    static let lastSyncedDay = "healthkit.lastSyncedDay"
    static let lastSyncDate = "healthkit.lastSyncDate"
    static let healthKitEnabled = "healthkit.enabled"
    static let waterInFluidOunces = "units.waterFlOz"
    static let registeredPushToken = "push.registeredToken"
}
