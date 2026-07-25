import SwiftUI

struct BodyView: View {
    @Environment(AppState.self) private var appState

    @State private var metrics: [BodyMetric] = []
    @State private var isLoading = false
    @State private var showLog = false
    @State private var errorMessage: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if let error = errorMessage {
                    ErrorBanner(message: error) {
                        errorMessage = nil
                        Task { await load() }
                    }
                }

                if metrics.isEmpty && !isLoading {
                    EmptyState(
                        icon: "figure.arms.open",
                        title: L.Body.emptyTitle,
                        message: L.Body.emptyBody,
                        actionTitle: L.Body.logMeasurement
                    ) {
                        showLog = true
                    }
                }

                ForEach(metrics) { metric in
                    BodyMetricCard(metric: metric)
                }
            }
            .padding(.horizontal)
            .padding(.bottom, 24)
        }
        .background(Theme.background)
        .navigationTitle(L.Body.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    showLog = true
                } label: {
                    Image(systemName: "plus.circle.fill")
                }
            }
        }
        .sheet(isPresented: $showLog) {
            LogBodyView(manualMetrics: appState.manualMetrics) {
                Task { await load() }
            }
        }
        .refreshable {
            await load()
        }
        .task {
            if metrics.isEmpty {
                await load()
            }
        }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await APIClient.shared.bodyMetrics(days: 365)
            metrics = response.metrics ?? []
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}

struct BodyMetricCard: View {
    let metric: BodyMetric

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(metric.label ?? metric.key)
                        .font(.subheadline.weight(.semibold))
                    if let latest = metric.summary?.latest {
                        HStack(spacing: 4) {
                            Text("\(latest.compactString) \(metric.unit ?? "")")
                                .font(.title3.bold())
                            if let date = metric.summary?.latestDate {
                                Text(Day.display(date))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                Spacer()
                if let trend = metric.summary?.trend, let pct = trend.pctChange, trend.direction != "flat" {
                    Label("\(abs(pct).compactString)%",
                          systemImage: trend.direction == "up" ? "arrow.up.right" : "arrow.down.right")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
            }
            if let series = metric.series, series.count > 1 {
                Sparkline(points: series, tint: Theme.accent)
                    .frame(height: 46)
            }
        }
        .cardStyle()
    }
}

// MARK: - Log measurement

struct LogBodyView: View {
    let manualMetrics: [String: ManualMetricInfo]
    var onSaved: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var metricKey = "body_mass"
    @State private var value: Double?
    @State private var date = Date()
    @State private var saving = false
    @State private var errorMessage: String?

    private struct MetricOption: Identifiable {
        let key: String
        let label: String
        let unit: String

        var id: String { key }
    }

    /// Sorted metric options; falls back to a core set if config is missing.
    private var options: [MetricOption] {
        let source: [MetricOption]
        if manualMetrics.isEmpty {
            source = [
                MetricOption(key: "body_mass", label: "Weight", unit: "kg"),
                MetricOption(key: "body_fat", label: "Body Fat", unit: "%"),
                MetricOption(key: "waist", label: "Waist", unit: "cm"),
                MetricOption(key: "resting_heart_rate", label: "Resting Heart Rate", unit: "bpm"),
            ]
        } else {
            source = manualMetrics.map {
                MetricOption(key: $0.key, label: $0.value.label ?? $0.key, unit: $0.value.unit ?? "")
            }
        }
        return source.sorted { $0.label < $1.label }
    }

    private var selectedUnit: String {
        options.first { $0.key == metricKey }?.unit ?? ""
    }

    var body: some View {
        NavigationStack {
            Form {
                Picker(L.Body.metric, selection: $metricKey) {
                    ForEach(options) { option in
                        Text(option.unit.isEmpty ? option.label : "\(option.label) (\(option.unit))")
                            .tag(option.key)
                    }
                }
                HStack {
                    Text(L.Body.value)
                    Spacer()
                    TextField(L.Body.value, value: $value, format: .number)
                        .keyboardType(.decimalPad)
                        .multilineTextAlignment(.trailing)
                        .frame(width: 100)
                    Text(selectedUnit)
                        .foregroundStyle(.secondary)
                }
                DatePicker(L.Body.date, selection: $date, displayedComponents: .date)
            }
            .navigationTitle(L.Body.logMeasurement)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(L.Common.cancel) { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L.Common.save) {
                        Task { await save() }
                    }
                    .disabled(saving || value == nil)
                }
            }
            .errorAlert(message: $errorMessage)
        }
    }

    private func save() async {
        guard let value else { return }
        saving = true
        defer { saving = false }
        do {
            try await APIClient.shared.logBody(NewBodyEntry(
                metric: metricKey,
                value: value,
                date: Day.string(from: date)))
            Haptics.success()
            onSaved()
            dismiss()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}
