import AuthenticationServices
import SwiftUI

/// Welcome pages → Sign in with Apple → HealthKit permission → initial sync
/// (with progress) → notifications → done.
struct OnboardingFlowView: View {
    enum Step: Int, CaseIterable {
        case welcome
        case signIn
        case health
        case sync
        case notifications
    }

    let startStep: Step

    @Environment(AuthManager.self) private var auth
    @Environment(HealthKitManager.self) private var healthKit
    @Environment(PushManager.self) private var push

    @State private var step: Step
    @State private var welcomePage = 0
    @State private var signingIn = false
    @State private var syncStarted = false
    @State private var syncFinished = false

    init(startStep: Step) {
        self.startStep = startStep
        _step = State(initialValue: startStep)
    }

    var body: some View {
        ZStack {
            Theme.background.ignoresSafeArea()
            VStack(spacing: 0) {
                stepIndicator
                    .padding(.top, 12)
                content
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .padding(.horizontal, 28)
            }
        }
        .animation(.easeInOut, value: step)
    }

    private var stepIndicator: some View {
        let visible: [Step] = [.signIn, .health, .sync, .notifications]
        return Group {
            if let index = visible.firstIndex(of: step) {
                Text(String(format: L.Onboarding.stepOf, index + 1, visible.count))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Color.clear.frame(height: 14)
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch step {
        case .welcome: welcomeStep
        case .signIn: signInStep
        case .health: healthStep
        case .sync: syncStep
        case .notifications: notificationsStep
        }
    }

    // MARK: - Welcome pages

    private var welcomeStep: some View {
        VStack(spacing: 24) {
            Spacer()
            TabView(selection: $welcomePage) {
                welcomeCard(icon: "staroflife.fill",
                            title: L.Onboarding.welcomeTitle,
                            body: L.Onboarding.welcomeSubtitle)
                    .tag(0)
                welcomeCard(icon: "bubble.left.and.text.bubble.right.fill",
                            title: L.Onboarding.pageCoachTitle,
                            body: L.Onboarding.pageCoachBody)
                    .tag(1)
                welcomeCard(icon: "fork.knife.circle.fill",
                            title: L.Onboarding.pageTrackTitle,
                            body: L.Onboarding.pageTrackBody)
                    .tag(2)
                welcomeCard(icon: "heart.text.square.fill",
                            title: L.Onboarding.pageHealthTitle,
                            body: L.Onboarding.pageHealthBody)
                    .tag(3)
            }
            .tabViewStyle(.page(indexDisplayMode: .always))
            .indexViewStyle(.page(backgroundDisplayMode: .always))
            .frame(height: 340)

            Button {
                Haptics.tap()
                step = .signIn
            } label: {
                Text(L.Onboarding.getStarted)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            Spacer()
        }
    }

    private func welcomeCard(icon: String, title: String, body: String) -> some View {
        VStack(spacing: 18) {
            Image(systemName: icon)
                .font(.system(size: 64))
                .foregroundStyle(Theme.accent)
            Text(title)
                .font(.title2.bold())
                .multilineTextAlignment(.center)
            Text(body)
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(.horizontal, 8)
    }

    // MARK: - Sign in

    private var signInStep: some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: "person.crop.circle.badge.checkmark")
                .font(.system(size: 56))
                .foregroundStyle(Theme.accent)
            Text(L.Onboarding.signInTitle)
                .font(.title2.bold())
            Text(L.Onboarding.signInBody)
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            if let error = auth.lastError {
                ErrorBanner(message: error)
            }

            SignInWithAppleButton(.signIn) { request in
                request.requestedScopes = [.fullName, .email]
            } onCompletion: { result in
                signingIn = true
                Task {
                    let ok = await auth.handleSignInWithApple(result)
                    signingIn = false
                    if ok {
                        Haptics.success()
                        step = .health
                    }
                }
            }
            .signInWithAppleButtonStyle(.black)
            .frame(height: 52)
            .disabled(signingIn)
            .overlay {
                if signingIn { ProgressView() }
            }
            Spacer()
        }
    }

    // MARK: - HealthKit

    private var healthStep: some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: "heart.text.square.fill")
                .font(.system(size: 56))
                .foregroundStyle(Theme.heart)
            Text(L.Onboarding.healthTitle)
                .font(.title2.bold())
            Text(L.Onboarding.healthBody)
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            Button {
                Task {
                    let granted = await healthKit.requestAuthorization()
                    if granted {
                        Haptics.success()
                        step = .sync
                    } else {
                        step = .notifications
                    }
                }
            } label: {
                Text(L.Onboarding.healthAllow)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)

            Button(L.Onboarding.healthSkip) {
                step = .notifications
            }
            .font(.subheadline)

            Text(L.Onboarding.healthDenied)
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Spacer()
        }
    }

    // MARK: - Initial sync

    private var syncStep: some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: "arrow.triangle.2.circlepath.circle.fill")
                .font(.system(size: 56))
                .foregroundStyle(Theme.accent)
            Text(L.Onboarding.syncTitle)
                .font(.title2.bold())
            Text(L.Onboarding.syncBody)
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            if healthKit.isSyncing || syncFinished {
                VStack(spacing: 10) {
                    ProgressView(value: syncFinished ? 1 : healthKit.syncProgress)
                        .progressViewStyle(.linear)
                    Text(syncFinished
                         ? L.Onboarding.syncDone
                         : "\(Int((healthKit.syncProgress * 100).rounded()))%")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 8)
            }

            if let error = healthKit.lastError {
                ErrorBanner(message: error) {
                    startSync()
                }
            }

            if syncFinished {
                Button {
                    Haptics.success()
                    step = .notifications
                } label: {
                    Text(L.Common.done)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            } else if !healthKit.isSyncing {
                Button {
                    startSync()
                } label: {
                    Text(L.Onboarding.syncStart)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)

                Button(L.Onboarding.syncSkip) {
                    step = .notifications
                }
                .font(.subheadline)
            }
            Spacer()
        }
        .onAppear {
            if !syncStarted {
                startSync()
            }
        }
    }

    private func startSync() {
        syncStarted = true
        Task {
            await healthKit.syncNow(fullHistory: true)
            if healthKit.lastError == nil {
                syncFinished = true
            }
        }
    }

    // MARK: - Notifications

    private var notificationsStep: some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: "bell.badge.fill")
                .font(.system(size: 56))
                .foregroundStyle(Theme.warning)
            Text(L.Onboarding.notifTitle)
                .font(.title2.bold())
            Text(L.Onboarding.notifBody)
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            Button {
                Task {
                    _ = await push.requestAuthorization()
                    finish()
                }
            } label: {
                Text(L.Onboarding.notifAllow)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)

            Button(L.Onboarding.notifSkip) {
                finish()
            }
            .font(.subheadline)
            Spacer()
        }
    }

    private func finish() {
        Haptics.success()
        healthKit.startObserving()
        auth.completeOnboarding()
        Task {
            await AppState.shared.refreshAll()
        }
    }
}
