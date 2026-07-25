import Foundation

/// Date and number helpers used across the app. All day-level dates are
/// exchanged with the backend as "yyyy-MM-dd" strings in the user's local
/// calendar, matching how the backend buckets daily aggregates.
enum Day {
    /// Formatter for the wire format ("2026-07-15"), local time zone.
    static let wireFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = .current
        return f
    }()

    /// Short human format ("Tue, Jul 15").
    static let displayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.setLocalizedDateFormatFromTemplate("EEEdMMM")
        return f
    }()

    static func string(from date: Date) -> String {
        wireFormatter.string(from: date)
    }

    static func date(from string: String) -> Date? {
        wireFormatter.date(from: string)
    }

    static var todayString: String { string(from: Date()) }

    /// "Today" / "Yesterday" / "Tue, Jul 15" for a wire date string.
    static func display(_ wire: String) -> String {
        guard let date = date(from: wire) else { return wire }
        return display(date)
    }

    static func display(_ date: Date) -> String {
        let cal = Calendar.current
        if cal.isDateInToday(date) { return L.Common.today }
        if cal.isDateInYesterday(date) { return L.Common.yesterday }
        return displayFormatter.string(from: date)
    }

    static func adding(_ days: Int, to date: Date) -> Date {
        Calendar.current.date(byAdding: .day, value: days, to: date) ?? date
    }
}

extension Double {
    /// "1,234" — rounded to a whole number with grouping.
    var intString: String {
        Self.intFormatter.string(from: NSNumber(value: self.rounded())) ?? String(Int(self.rounded()))
    }

    /// Compact value: whole numbers drop the fraction, otherwise one decimal.
    var compactString: String {
        if abs(self.truncatingRemainder(dividingBy: 1)) < 0.05 {
            return intString
        }
        return Self.oneDecimalFormatter.string(from: NSNumber(value: self)) ?? String(format: "%.1f", self)
    }

    func string(decimals: Int) -> String {
        String(format: "%.\(decimals)f", self)
    }

    private static let intFormatter: NumberFormatter = {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.maximumFractionDigits = 0
        return f
    }()

    private static let oneDecimalFormatter: NumberFormatter = {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.minimumFractionDigits = 0
        f.maximumFractionDigits = 1
        return f
    }()
}

/// Water unit conversion. The backend stores milliliters; the UI can show
/// fluid ounces (US) based on the user's preference.
enum WaterUnits {
    static let mlPerFlOz = 29.5735

    static var preferOunces: Bool {
        get {
            UserDefaults.standard.object(forKey: DefaultsKey.waterInFluidOunces) as? Bool ?? true
        }
        set { UserDefaults.standard.set(newValue, forKey: DefaultsKey.waterInFluidOunces) }
    }

    static func display(ml: Double) -> String {
        if preferOunces {
            return "\((ml / mlPerFlOz).compactString) fl oz"
        }
        return "\(ml.intString) ml"
    }
}

/// "HH:MM" strings used by the notification preferences API.
enum TimeOfDay {
    static let formatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm"
        return f
    }()

    static func date(from string: String) -> Date {
        formatter.date(from: string) ?? Date()
    }

    static func string(from date: Date) -> String {
        formatter.string(from: date)
    }
}

/// ISO-8601 timestamps ("2026-07-15T08:30:00") from the backend, parsed
/// leniently (with or without fractional seconds / offsets).
enum Timestamp {
    private static let isoWithFraction: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    private static let bare: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        f.timeZone = .current
        return f
    }()

    static func parse(_ string: String) -> Date? {
        isoWithFraction.date(from: string)
            ?? iso.date(from: string)
            ?? bare.date(from: string)
    }

    static func display(_ string: String) -> String {
        guard let date = parse(string) else { return string }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}
