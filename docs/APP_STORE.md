# Shipping Asclepius to the App Store

A checklist for taking the iOS app in `ios/` from source to TestFlight and
review. Everything here assumes a Mac with Xcode 16+.

## 1. Apple Developer setup

1. Enroll in the Apple Developer Program (organization enrollment if you'll
   publish under a company name).
2. Register the bundle id (default `com.asclepius.app` — change it in
   `ios/project.yml` and `ASCLEPIUS_APPLE_BUNDLE_ID` on the server together).
3. Enable capabilities on the App ID: **HealthKit**, **Sign in with Apple**,
   **Push Notifications**, **Background Modes**.
4. Create an **APNs auth key** (Keys → “+” → Apple Push Notifications
   service). Download the `.p8` once; set `APNS_KEY`, `APNS_KEY_ID`,
   `APNS_TEAM_ID` on the server.

## 2. Build

```bash
cd ios
brew install xcodegen
xcodegen generate
open Asclepius.xcodeproj
```

Set your team for signing, pick a device, run. To develop against a local
backend, see `ios/README.md` (DEBUG builds default to `http://localhost:8765`;
run the server with `ASCLEPIUS_MULTI_TENANT=1 ASCLEPIUS_DEV_LOGIN=1`).

## 3. App Review requirements this app already handles

- **Health data (Guideline 5.1.3)**: health data is used only to provide the
  user's own coaching, never for advertising; the privacy policy must say so
  explicitly. The app requests HealthKit *read* access only.
- **Account deletion (5.1.1(v))**: Settings → Delete Account calls
  `DELETE /api/account`, which destroys the account and all server data.
- **Sign in with Apple (4.8)**: it's the only login, so the requirement is
  satisfied trivially.
- **Privacy manifest**: `ios/Asclepius/PrivacyInfo.xcprivacy` declares
  collected data types and required-reason APIs.
- **Medical disclaimer (1.4.1)**: the app presents coaching as informational,
  not diagnosis. Keep the disclaimer visible in onboarding and the App Store
  description.

## 4. App Store Connect

- **Privacy nutrition label**: declare Health & Fitness data, linked to the
  user, not used for tracking. Also “Contact Info → Email” (account) and
  “User Content → Photos” (food photos, processed transiently).
- **App Privacy report questions**: photos sent to `/api/food/analyze` are
  analyzed and discarded — nothing is stored server-side.
- **Review notes**: provide a demo account (enable `ASCLEPIUS_DEV_LOGIN` on a
  staging server for the review build, or pre-seed a TestFlight demo user) and
  a sentence on where health data goes (your server + Anthropic API summaries).
- **Age rating**: 12+ (medical/treatment information: infrequent).

## 5. TestFlight → release

1. Archive in Xcode (Product → Archive) with the `production`
   `aps-environment` entitlement (Xcode handles this on distribution signing).
2. Upload, wait for processing, add internal testers.
3. Verify on a physical device: Sign in with Apple, HealthKit permission
   sheet, an end-to-end sync, a coach turn, and a push notification
   (`POST /api/push/send`).
4. Submit for review with the notes above.
