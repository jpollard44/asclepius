import SwiftUI

// MARK: - ProgressRing

/// Circular progress ring with arbitrary center content.
struct ProgressRing<Content: View>: View {
    var progress: Double
    var color: Color
    var lineWidth: CGFloat = 10
    @ViewBuilder var content: () -> Content

    var body: some View {
        ZStack {
            Circle()
                .stroke(color.opacity(0.18), lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: min(max(progress, 0), 1))
                .stroke(color, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(.easeOut(duration: 0.5), value: progress)
            content()
        }
    }
}

extension ProgressRing where Content == EmptyView {
    init(progress: Double, color: Color, lineWidth: CGFloat = 10) {
        self.init(progress: progress, color: color, lineWidth: lineWidth) { EmptyView() }
    }
}

// MARK: - StatCard

/// Compact dashboard card: icon, title, value, optional goal progress bar.
struct StatCard: View {
    var title: String
    var value: String
    var subtitle: String? = nil
    var systemImage: String
    var tint: Color
    var progress: Double? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: systemImage)
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(tint)
                Text(title)
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
            }
            Text(value)
                .font(.title3.bold())
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            if let subtitle {
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            if let progress {
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Capsule().fill(tint.opacity(0.18))
                        Capsule()
                            .fill(tint)
                            .frame(width: geo.size.width * min(max(progress, 0), 1))
                    }
                }
                .frame(height: 5)
            }
        }
        .cardStyle()
    }
}

// MARK: - MacroBar

/// Labeled progress bar for one macro against its daily goal.
struct MacroBar: View {
    var label: String
    var value: Double
    var goal: Double? = nil
    var unit: String
    var tint: Color
    var lowerBetter: Bool = false

    private var progress: Double {
        guard let goal, goal > 0 else { return 0 }
        return value / goal
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label)
                    .font(.caption.weight(.semibold))
                Spacer()
                Text(goalText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(tint.opacity(0.18))
                    Capsule()
                        .fill(Theme.goalColor(progress: progress, lowerBetter: lowerBetter) == Theme.danger ? Theme.danger : tint)
                        .frame(width: geo.size.width * min(max(progress, 0), 1))
                }
            }
            .frame(height: 6)
        }
    }

    private var goalText: String {
        if let goal, goal > 0 {
            return "\(value.compactString) / \(goal.compactString) \(unit)"
        }
        return "\(value.compactString) \(unit)"
    }
}

// MARK: - Chip

/// Small pill, optionally tappable (Coach suggestions, plan focus areas).
struct Chip: View {
    var text: String
    var systemImage: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        if let action {
            Button(action: action) { label }
                .buttonStyle(.plain)
        } else {
            label
        }
    }

    private var label: some View {
        HStack(spacing: 4) {
            if let systemImage {
                Image(systemName: systemImage)
                    .font(.caption2)
            }
            Text(text)
                .font(.footnote.weight(.medium))
                .lineLimit(1)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 7)
        .background(Theme.accent.opacity(0.12), in: Capsule())
        .foregroundStyle(Theme.accent)
    }
}

// MARK: - SectionHeader

struct SectionHeader: View {
    var title: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        HStack {
            Text(title)
                .font(.headline)
            Spacer()
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .font(.subheadline)
            }
        }
    }
}

// MARK: - EmptyState

struct EmptyState: View {
    var icon: String
    var title: String
    var message: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 42))
                .foregroundStyle(Theme.accent.opacity(0.6))
            Text(title)
                .font(.headline)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .buttonStyle(.borderedProminent)
                    .padding(.top, 4)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 36)
        .padding(.horizontal, 24)
    }
}

// MARK: - ErrorBanner

/// Inline error banner with an optional retry button.
struct ErrorBanner: View {
    var message: String
    var retry: (() -> Void)? = nil

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(Theme.warning)
            Text(message)
                .font(.footnote)
                .foregroundStyle(.primary)
            Spacer(minLength: 0)
            if let retry {
                Button(L.Common.retry, action: retry)
                    .font(.footnote.weight(.semibold))
            }
        }
        .padding(12)
        .background(Theme.warning.opacity(0.12), in: RoundedRectangle(cornerRadius: 12))
    }
}

// MARK: - LoadingOverlay

struct LoadingOverlay: View {
    var text: String = L.Common.loading

    var body: some View {
        ZStack {
            Color.black.opacity(0.15).ignoresSafeArea()
            VStack(spacing: 10) {
                ProgressView()
                Text(text)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            .padding(22)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
        }
    }
}

// MARK: - Error alert helper

/// Standard error alert bound to an optional message.
extension View {
    func errorAlert(message: Binding<String?>, retry: (() -> Void)? = nil) -> some View {
        alert(
            L.Common.error,
            isPresented: Binding(
                get: { message.wrappedValue != nil },
                set: { if !$0 { message.wrappedValue = nil } }
            )
        ) {
            if let retry {
                Button(L.Common.retry) {
                    message.wrappedValue = nil
                    retry()
                }
            }
            Button(L.Common.ok, role: .cancel) {
                message.wrappedValue = nil
            }
        } message: {
            Text(message.wrappedValue ?? "")
        }
    }
}
