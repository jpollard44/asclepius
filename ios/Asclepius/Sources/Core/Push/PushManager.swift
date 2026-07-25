import Foundation
import Observation
import UIKit
import UserNotifications

/// Handles APNs registration and notification routing.
///
/// The backend includes an `ntype` key in each push's userInfo; taps route to
/// the matching tab (meal/water → Food, workout → Fitness, sleep → More/Sleep,
/// coach/weekly → Coach).
@MainActor
@Observable
final class PushManager: NSObject {
    static let shared = PushManager()

    private let api = APIClient.shared

    private(set) var authorizationStatus: UNAuthorizationStatus = .notDetermined
    private(set) var deviceToken: String?

    /// Call once at launch to become the notification-center delegate.
    func configure() {
        UNUserNotificationCenter.current().delegate = self
        Task { await refreshAuthorizationStatus() }
    }

    func refreshAuthorizationStatus() async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        authorizationStatus = settings.authorizationStatus
    }

    /// Requests permission and, if granted, registers with APNs.
    @discardableResult
    func requestAuthorization() async -> Bool {
        do {
            let granted = try await UNUserNotificationCenter.current()
                .requestAuthorization(options: [.alert, .badge, .sound])
            await refreshAuthorizationStatus()
            if granted {
                registerForRemoteNotifications()
            }
            return granted
        } catch {
            return false
        }
    }

    func registerForRemoteNotifications() {
        UIApplication.shared.registerForRemoteNotifications()
    }

    // MARK: - APNs token plumbing (called from AppDelegate)

    func handleDeviceToken(_ tokenData: Data) {
        let token = tokenData.map { String(format: "%02x", $0) }.joined()
        deviceToken = token
        Task {
            do {
                try await api.registerDevice(token: token)
                UserDefaults.standard.set(token, forKey: DefaultsKey.registeredPushToken)
            } catch {
                // Registration retries on the next launch.
            }
        }
    }

    func handleRegistrationError(_ error: Error) {
        // Simulator or entitlement issue: nothing actionable for the user.
        deviceToken = nil
    }

    /// Removes this device from the backend (sign-out path).
    func unregisterFromBackend() async {
        let stored = UserDefaults.standard.string(forKey: DefaultsKey.registeredPushToken)
        guard let token = deviceToken ?? stored else { return }
        await api.unregisterDevice(token: token)
        UserDefaults.standard.removeObject(forKey: DefaultsKey.registeredPushToken)
    }

    // MARK: - Routing

    private func route(userInfo: [AnyHashable: Any]) {
        guard let ntype = userInfo["ntype"] as? String else { return }
        AppRouter.shared.handleNotification(type: ntype)
    }
}

extension PushManager: UNUserNotificationCenterDelegate {
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        // Show reminders even while the app is open.
        completionHandler([.banner, .sound, .badge])
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let userInfo = response.notification.request.content.userInfo
        Task { @MainActor in
            self.route(userInfo: userInfo)
            completionHandler()
        }
    }
}
