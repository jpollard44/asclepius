import Charts
import SwiftUI

/// Minimal line chart for metric cards (no axes, just the shape of the data).
struct Sparkline: View {
    var points: [MetricPoint]
    var tint: Color = Theme.accent

    var body: some View {
        Chart(points) { point in
            LineMark(
                x: .value("Date", point.date),
                y: .value("Value", point.value))
            .interpolationMethod(.catmullRom)
            .foregroundStyle(tint)
            AreaMark(
                x: .value("Date", point.date),
                y: .value("Value", point.value))
            .interpolationMethod(.catmullRom)
            .foregroundStyle(
                LinearGradient(colors: [tint.opacity(0.25), .clear],
                               startPoint: .top, endPoint: .bottom))
        }
        .chartXAxis(.hidden)
        .chartYAxis(.hidden)
        .chartYScale(domain: yDomain)
        .chartLegend(.hidden)
    }

    private var yDomain: ClosedRange<Double> {
        let values = points.map(\.value)
        guard let min = values.min(), let max = values.max(), min != max else {
            let v = points.first?.value ?? 0
            return (v - 1) ... (v + 1)
        }
        let pad = (max - min) * 0.15
        return (min - pad) ... (max + pad)
    }
}
