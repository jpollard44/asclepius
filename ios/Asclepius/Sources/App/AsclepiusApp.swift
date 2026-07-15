import SwiftUI
import UIKit

final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        // BGTask handlers must be registered before launch completes.
        HealthKitManager.registerBackgroundTasks()
        Task { @MainActor in
            PushManager.shared.configure()
        }
        return true
    }

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        Task { @MainActor in
            PushManager.shared.handleDeviceToken(deviceToken)
        }
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        Task { @MainActor in
            PushManager.shared.handleRegistrationError(error)
        }
    }
}

@main
struct AsclepiusApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase

    @State private var auth = AuthManager.shared
    @State private var appState = AppState.shared
    @State private var router = AppRouter.shared
    @State private var healthKit = HealthKitManager.shared
    @State private var push = PushManager.shared

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(auth)
                .environment(appState)
                .environment(router)
                .environment(healthKit)
                .environment(push)
                .tint(Theme.accent)
                .task {
                    await auth.bootstrap()
                }
                .onChange(of: scenePhase) { _, phase in
                    handleScenePhase(phase)
                }
        }
    }

    private func handleScenePhase(_ phase: ScenePhase) {
        switch phase {
        case .active:
            guard auth.state == .signedIn else { return }
            Task {
                await appState.refreshAll()
                healthKit.startObserving()
                await healthKit.syncNow()
                await push.refreshAuthorizationStatus()
                if push.authorizationStatus == .authorized {
                    push.registerForRemoteNotifications()
                }
            }
        case .background:
            if auth.state == .signedIn {
                healthKit.scheduleBackgroundTasks()
            }
        default:
            break
        }
    }
}
