import Foundation

// Shared primitive response models. Feature-specific models live in
// Core/Models/*.swift; everything decodes tolerantly (optionals for any field
// the backend may omit) so shape drift never crashes the app.

/// Generic `{"status": "ok"}`-style acknowledgement.
struct SimpleStatus: Decodable {
    var status: String?
}

/// A `{start, end}` date-string range.
struct DateRange: Decodable, Equatable {
    var start: String?
    var end: String?
}

/// One point of a daily metric series: `{date, value, min?, max?, unit?}`.
struct MetricPoint: Decodable, Identifiable, Equatable {
    var date: String
    var value: Double
    var min: Double?
    var max: Double?
    var unit: String?

    var id: String { date }
}

/// Direction summary the backend computes over a series' halves.
struct Trend: Decodable, Equatable {
    var direction: String?
    var pctChange: Double?
    var firstHalfAvg: Double?
    var secondHalfAvg: Double?

    enum CodingKeys: String, CodingKey {
        case direction
        case pctChange = "pct_change"
        case firstHalfAvg = "first_half_avg"
        case secondHalfAvg = "second_half_avg"
    }
}

/// Headline statistics for one metric over a window.
struct MetricSummary: Decodable, Identifiable {
    var key: String
    var label: String?
    var unit: String?
    var available: Bool?
    var windowDays: Int?
    var dataPoints: Int?
    var latest: Double?
    var latestDate: String?
    var average: Double?
    var min: Double?
    var max: Double?
    var stdDev: Double?
    var trend: Trend?

    var id: String { key }

    enum CodingKeys: String, CodingKey {
        case key, label, unit, available, latest, average, min, max, trend
        case windowDays = "window_days"
        case dataPoints = "data_points"
        case latestDate = "latest_date"
        case stdDev = "std_dev"
    }
}

/// The most recent reading of a metric (dashboard "weight" card, etc.).
struct MetricLatest: Decodable {
    var metric: String?
    var date: String?
    var value: Double?
    var min: Double?
    var max: Double?
    var unit: String?
}

/// Coverage entry from GET /api/metrics.
struct MetricInfo: Decodable, Identifiable {
    var key: String
    var label: String?
    var unit: String?
    var area: String?
    var days: Int?
    var start: String?
    var end: String?

    var id: String { key }
}

struct MetricsListResponse: Decodable {
    var metrics: [MetricInfo]?
}

/// GET /api/metric/{key} → summary + daily series.
struct MetricDetailResponse: Decodable {
    var summary: MetricSummary?
    var series: [MetricPoint]?
}
