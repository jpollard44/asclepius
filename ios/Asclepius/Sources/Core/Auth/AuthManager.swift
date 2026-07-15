import AuthenticationServices
import Foundation
import Observation

/// Owns the session lifecycle: Sign in with Apple, token persistence (via the
/// APIClient's Keychain store), onboarding gating, sign-out and account
/// deletion.
@MainActor
@Observable
final class AuthManager {
    enum SessionState: Equatable {
        /// Checking the Keychain at launch.
        case loading
        /// No session — show the welcome + sign-in flow.
        case signedOut
        /// Signed in but onboarding (HealthKit, first sync) not finished.
        case onboarding
        /// Fully signed in.
        case signedIn
    }

    static let shared = AuthManager()

    private(set) var state: SessionState = .loading
    private(set) var user: UserProfile?
    var lastError: String?

    private let api = APIClient.shared

    private var onboardingComplete: Bool {
        get { UserDefaults.standard.bool(forKey: DefaultsKey.onboardingComplete) }
        set { UserDefaults.standard.set(newValue, forKey: DefaultsKey.onboardingComplete) }
    }

    // MARK: - Bootstrap

    /// Called once at launch. Restores the cached session if one exists and
    /// registers the expiry handler that signs the user out when a token
    /// refresh fails.
    func bootstrap() async {
        await api.setSessionExpiredHandler { [weak self] in
            await MainActor.run {
                self?.handleSessionExpired()
            }
        }

        guard await api.hasSession else {
            state = .signedOut
            return
        }
        user = await api.cachedUser
        state = onboardingComplete ? .signedIn : .onboarding

        // Refresh the profile in the background; tolerate being offline.
        do {
            let account = try await api.account()
            if let fresh = account.user {
                user = fresh
                await api.cacheUser(fresh)
            }
        } catch let error as APIError where error.isUnauthorized {
            // The expiry handler has already cleared the session.
        } catch {
            // Offline or transient server issue — keep the cached session.
        }
    }

    // MARK: - Sign in with Apple

    /// Handles the completion of the SwiftUI SignInWithAppleButton flow.
    /// Returns true when the backend session was established.
    func handleSignInWithApple(_ result: Result<ASAuthorization, Error>) async -> Bool {
        switch result {
        case .failure(let error):
            let ns = error as NSError
            if ns.domain == ASAuthorizationError.errorDomain,
               ns.code == ASAuthorizationError.canceled.rawValue {
                return false // User dismissed — not an error worth surfacing.
            }
            lastError = L.Onboarding.signInFailed
            return false

        case .success(let authorization):
            guard let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
                  let tokenData = credential.identityToken,
                  let identityToken = String(data: tokenData, encoding: .utf8) else {
                lastError = L.Onboarding.signInFailed
                return false
            }
            let fullName = [credential.fullName?.givenName, credential.fullName?.familyName]
                .compactMap { $0 }
                .joined(separator: " ")
            do {
                let tokens = try await api.signInWithApple(
                    identityToken: identityToken,
                    fullName: fullName.isEmpty ? nil : fullName,
                    email: credential.email)
                user = tokens.user
                lastError = nil
                state = onboardingComplete ? .signedIn : .onboarding
                return true
            } catch {
                lastError = (error as? APIError)?.errorDescription ?? L.Onboarding.signInFailed
                return false
            }
        }
    }

    // MARK: - Session transitions

    func completeOnboarding() {
        onboardingComplete = true
        state = .signedIn
    }

    func signOut() async {
        await PushManager.shared.unregisterFromBackend()
        await api.logout()
        await api.clearTokens()
        onboardingComplete = false
        HealthKitManager.shared.resetSyncState()
        user = nil
        state = .signedOut
    }

    /// DELETE /api/account, then tear the local session down.
    func deleteAccount() async throws {
        _ = try await api.deleteAccount()
        await api.clearTokens()
        onboardingComplete = false
        HealthKitManager.shared.resetSyncState()
        user = nil
        state = .signedOut
    }

    private func handleSessionExpired() {
        // Keep the onboarding flag: re-signing in shouldn't redo the flow.
        user = nil
        state = .signedOut
    }
}
