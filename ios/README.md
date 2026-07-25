# Asclepius iOS

Native SwiftUI client for the Asclepius AI health coach. Reads Apple Health
directly (replacing the export.xml upload flow), syncs daily aggregates to the
backend, and provides chat coaching, a living plan, food/water/workout/sleep/
body tracking, goals, streaks, achievements, and push reminders.

- **iOS 17+, Swift 5.9, SwiftUI, Swift Charts** — no third-party dependencies.
- Project is generated with [XcodeGen](https://github.com/yonaskolb/XcodeGen)
  from `project.yml` (no `.xcodeproj` is checked in).

## Prerequisites

- **Xcode 16** (or newer) with the iOS 17 SDK.
- **XcodeGen**: `brew install xcodegen`
- An Apple Developer account for device builds (HealthKit, Sign in with Apple,
  and push notifications all require real entitlements; HealthKit does not
  work in the simulator's Health app beyond limited sample data).

## Generate the project

```bash
cd ios
xcodegen generate
open Asclepius.xcodeproj
```

Regenerate whenever `project.yml` changes or files are added/removed
(`xcodegen generate` is idempotent).

## Signing setup

1. In `project.yml`, set your team under
   `targets.Asclepius.settings.base.DEVELOPMENT_TEAM` (or pick the team in
   Xcode's Signing & Capabilities pane after generating).
2. Change `PRODUCT_BUNDLE_IDENTIFIER` from the placeholder `com.asclepius.app`
   to an identifier registered to your team.
3. The App ID needs these capabilities enabled in the developer portal:
   - HealthKit (with background delivery)
   - Sign in with Apple
   - Push Notifications
   - Background Modes (fetch, processing, remote notifications)
4. Entitlements live in `Asclepius/Asclepius.entitlements`. The checked-in
   `aps-environment` is `development`; release/App Store signing rewrites it
   to `production` automatically during export.

## Pointing at a backend

The API base URL is read at runtime from the `AsclepiusAPIBaseURL` Info.plist
key, which `project.yml` sets per build configuration:

- **Debug** → `http://localhost:8765`
- **Release** → `https://api.asclepius.health`

To use a different host (for example your Mac's LAN IP so a device build can
reach a locally running backend), edit the `ASCLEPIUS_API_BASE_URL` value in
`project.yml` and regenerate:

```yaml
configs:
  Debug:
    ASCLEPIUS_API_BASE_URL: "http://192.168.1.20:8765"
```

Run the backend from the repo root:

```bash
./run.sh   # serves the FastAPI app on port 8765
```

`NSAppTransportSecurity → NSAllowsLocalNetworking` is enabled so plain-HTTP
localhost/LAN backends work during development; production traffic is HTTPS.

## Architecture map

```
Asclepius/Sources/
  App/          @main entry, AppDelegate (APNs + BGTask registration), root
                routing, tab bar, global AppState + AppRouter
  Core/
    API/        APIClient actor (auth header injection, single-flight token
                refresh on 401, long-timeout chat calls, multipart upload)
                + typed endpoint wrappers
    Auth/       AuthManager (Sign in with Apple, session lifecycle),
                KeychainStore (SecItem wrapper)
    HealthKit/  Metric catalogue (HK type → backend key/unit/aggregation) and
                the sync engine (2-year backfill, incremental 7-day overlap,
                ≤120-day batches, observer queries, BGTasks)
    Push/       PushManager (authorization, APNs token → /api/devices,
                notification tap routing)
    Models/     Tolerant Codable models for every API response
  Features/     One folder per screen area (Today, Coach, Food, Fitness,
                Sleep, Body, Goals, Settings, Onboarding, More)
  UI/           Theme, reusable components (ProgressRing, StatCard, MacroBar,
                Sparkline, Chip, EmptyState, ErrorBanner…), Markdown renderer
```

## TestFlight notes

- Bump `MARKETING_VERSION` / `CURRENT_PROJECT_VERSION` in `project.yml` and
  regenerate before archiving.
- Archive with the Release configuration so the app points at the production
  API (`https://api.asclepius.health`).
- App Store Connect will ask about the required-reason APIs — the answers are
  declared in `Asclepius/PrivacyInfo.xcprivacy` (UserDefaults CA92.1, health
  data collected for app functionality, no tracking).
- App Review requires an explanation for HealthKit usage; the usage strings in
  `project.yml` describe it. Health data must not be used for advertising.
- Push reminders come from the backend via APNs; the device registers itself
  with `environment: "sandbox"` in Debug and `"production"` in Release builds,
  so the backend must send through the matching APNs endpoint.
- Sign in with Apple must be tested with a real Apple ID; the first sign-in is
  the only one that includes name/email, so delete the app's Sign in with
  Apple grant (Settings → Apple ID → Sign-In & Security) to re-test onboarding.
