import SwiftUI

/// App palette: a teal/green health look that adapts to dark mode via
/// dynamic colors.
enum Theme {
    /// Primary brand teal.
    static let accent = Color(
        light: Color(red: 0.05, green: 0.55, blue: 0.51),
        dark: Color(red: 0.25, green: 0.78, blue: 0.72))

    /// Secondary green.
    static let green = Color(
        light: Color(red: 0.22, green: 0.63, blue: 0.36),
        dark: Color(red: 0.42, green: 0.80, blue: 0.55))

    // Semantic metric tints.
    static let calories = Color.orange
    static let protein = Color(
        light: Color(red: 0.75, green: 0.25, blue: 0.35),
        dark: Color(red: 0.92, green: 0.45, blue: 0.55))
    static let carbs = Color(
        light: Color(red: 0.85, green: 0.6, blue: 0.1),
        dark: Color(red: 0.95, green: 0.72, blue: 0.3))
    static let fat = Color(
        light: Color(red: 0.55, green: 0.4, blue: 0.75),
        dark: Color(red: 0.7, green: 0.58, blue: 0.9))
    static let water = Color(
        light: Color(red: 0.12, green: 0.5, blue: 0.78),
        dark: Color(red: 0.35, green: 0.7, blue: 0.95))
    static let sleep = Color(
        light: Color(red: 0.35, green: 0.34, blue: 0.72),
        dark: Color(red: 0.6, green: 0.58, blue: 0.95))
    static let heart = Color(
        light: Color(red: 0.8, green: 0.2, blue: 0.3),
        dark: Color(red: 0.95, green: 0.4, blue: 0.5))
    static let steps = green
    static let energy = Color.orange

    static let warning = Color.orange
    static let danger = Color.red

    static let background = Color(uiColor: .systemGroupedBackground)
    static let cardBackground = Color(uiColor: .secondarySystemGroupedBackground)

    /// Tint for a macro/goal progress where lower is better inverts meaning.
    static func goalColor(progress: Double, lowerBetter: Bool = false) -> Color {
        if lowerBetter {
            if progress <= 0.85 { return green }
            if progress <= 1.0 { return warning }
            return danger
        }
        if progress >= 1.0 { return green }
        if progress >= 0.6 { return accent }
        return accent.opacity(0.85)
    }
}

extension Color {
    /// Dynamic color that resolves per light/dark trait.
    init(light: Color, dark: Color) {
        self.init(uiColor: UIColor { traits in
            traits.userInterfaceStyle == .dark ? UIColor(dark) : UIColor(light)
        })
    }
}

extension View {
    /// Standard card styling used across the app.
    func cardStyle() -> some View {
        self
            .padding(14)
            .background(Theme.cardBackground, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}
