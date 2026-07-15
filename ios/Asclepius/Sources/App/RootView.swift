import SwiftUI

/// Switches between the launch splash, the onboarding flow, and the main app
/// based on session state.
struct RootView: View {
    @Environment(AuthManager.self) private var auth

    var body: some View {
        switch auth.state {
        case .loading:
            splash
        case .signedOut:
            OnboardingFlowView(startStep: .welcome)
        case .onboarding:
            OnboardingFlowView(startStep: .health)
        case .signedIn:
            MainTabView()
        }
    }

    private var splash: some View {
        ZStack {
            Theme.background.ignoresSafeArea()
            VStack(spacing: 16) {
                Image(systemName: "staroflife.fill")
                    .font(.system(size: 56))
                    .foregroundStyle(Theme.accent)
                Text("Asclepius")
                    .font(.title.bold())
                ProgressView()
            }
        }
    }
}
