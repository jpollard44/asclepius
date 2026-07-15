import Charts
import SwiftUI

struct SleepView: View {
    @Environment(AppState.self) private var appState

    @State private var response: SleepResponse?
    @State private var windowDays = 30
    @State private var isLoading = false
    @State private var showLog = false
    @State private var errorMessage: String?

    private var series: [SleepNight] {
        response?.series?.filter { ($0.asleepHours ?? 0) > 0 } ?? []
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let error = errorMessage {
                    ErrorBanner(message: error) {
                        errorMessage = nil
                        Task { await load() }
                    }
                }

                Picker("", selection: $windowDays) {
                    Text("14d").tag(14)
                    Text("30d").tag(30)
                    Text("90d").tag(90)
                }
                .pickerStyle(.segmented)
                .onChange(of: windowDays) {
                    Task { await load() }
                }

                if series.isEmpty && !isLoading {
                    EmptyState(
                        icon: "moon.zzz",
                        title: L.Sleep.emptyTitle,
                        message: L.Sleep.emptyBody,
                        actionTitle: L.Sleep.logSleep
                    ) {
                        showLog = true
                    }
                } else {
                    summaryCards
                    hoursChart
                    stagesChart
                }
            }
            .padding(.horizontal)
            .padding(.bottom, 24)
        }
        .background(Theme.background)
        .navigationTitle(L.Sleep.title)
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
            LogSleepView {
                Task { await load() }
            }
        }
        .refreshable {
            await load()
        }
        .task {
            if response == nil {
                await load()
            }
        }
    }

    // MARK: - Summary

    @ViewBuilder
    private var summaryCards: some View {
        if let summary = response?.summary, summary.available == true {
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                StatCard(
                    title: L.Sleep.avg,
                    value: "\((summary.avgAsleepHours ?? 0).compactString) h",
                    subtitle: "\(summary.nightsRecorded ?? 0) \(L.Sleep.nights.lowercased())",
                    systemImage: "moon.zzz.fill",
                    tint: Theme.sleep,
                    progress: appState.dailyGoalTarget("sleep").map { ($0 > 0 ? (summary.avgAsleepHours ?? 0) / $0 : 0) })
                StatCard(
                    title: L.Sleep.lastNight,
                    value: (summary.latest?.asleepHours).map { "\($0.compactString) h" } ?? "—",
                    subtitle: (summary.latest?.date).map { Day.display($0) },
                    systemImage: "bed.double.fill",
                    tint: Theme.sleep,
                    progress: nil)
                if let rem = summary.avgRemHours {
                    StatCard(
                        title: "\(L.Sleep.stageREM) \(L.Sleep.avg.lowercased())",
                        value: "\(rem.compactString) h",
                        subtitle: nil,
                        systemImage: "brain.head.profile",
                        tint: Theme.accent,
                        progress: nil)
                }
                if let consistency = summary.consistencyStdHours {
                    StatCard(
                        title: L.Sleep.consistency,
                        value: "±\(consistency.compactString) h",
                        subtitle: nil,
                        systemImage: "clock.arrow.2.circlepath",
                        tint: Theme.carbs,
                        progress: nil)
                }
            }
        }
    }

    // MARK: - Charts

    private var hoursChart: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: L.Sleep.hoursAsleep)
            Chart {
                ForEach(series) { night in
                    BarMark(
                        x: .value("Date", Day.date(from: night.date) ?? Date(), unit: .day),
                        y: .value("Hours", night.asleepHours ?? 0))
                    .foregroundStyle(Theme.sleep)
                }
                if let goal = appState.dailyGoalTarget("sleep") {
                    RuleMark(y: .value("Goal", goal))
                        .lineStyle(StrokeStyle(lineWidth: 1, dash: [5, 4]))
                        .foregroundStyle(Theme.green)
                }
            }
            .frame(height: 160)
        }
        .cardStyle()
    }

    @ViewBuilder
    private var stagesChart: some View {
        let staged = series.filter {
            ($0.remHours ?? 0) > 0 || ($0.deepHours ?? 0) > 0 || ($0.coreHours ?? 0) > 0
        }
        if !staged.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                SectionHeader(title: L.Sleep.stages)
                Chart(stageData(staged), id: \.id) { slice in
                    BarMark(
                        x: .value("Date", slice.date, unit: .day),
                        y: .value("Hours", slice.hours))
                    .foregroundStyle(by: .value("Stage", slice.stage))
                }
                .chartForegroundStyleScale([
                    L.Sleep.stageDeep: Theme.sleep,
                    L.Sleep.stageCore: Theme.accent,
                    L.Sleep.stageREM: Theme.water,
                    L.Sleep.stageAwake: Color.secondary.opacity(0.4),
                ])
                .frame(height: 180)
            }
            .cardStyle()
        }
    }

    private struct StageSlice: Identifiable {
        let id: String
        let date: Date
        let stage: String
        let hours: Double
    }

    private func stageData(_ nights: [SleepNight]) -> [StageSlice] {
        nights.flatMap { night -> [StageSlice] in
            guard let date = Day.date(from: night.date) else { return [] }
            var slices: [StageSlice] = []
            if let deep = night.deepHours, deep > 0 {
                slices.append(StageSlice(id: night.date + "-deep", date: date, stage: L.Sleep.stageDeep, hours: deep))
            }
            if let core = night.coreHours, core > 0 {
                slices.append(StageSlice(id: night.date + "-core", date: date, stage: L.Sleep.stageCore, hours: core))
            }
            if let rem = night.remHours, rem > 0 {
                slices.append(StageSlice(id: night.date + "-rem", date: date, stage: L.Sleep.stageREM, hours: rem))
            }
            if let awake = night.awakeHours, awake > 0 {
                slices.append(StageSlice(id: night.date + "-awake", date: date, stage: L.Sleep.stageAwake, hours: awake))
            }
            return slices
        }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            response = try await APIClient.shared.sleep(days: windowDays)
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}

// MARK: - Manual log

struct LogSleepView: View {
    var onSaved: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var date = Date()
    @State private var asleepHours: Double = 8
    @State private var inBedHours: Double?
    @State private var remHours: Double?
    @State private var deepHours: Double?
    @State private var saving = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                DatePicker(L.Body.date, selection: $date, displayedComponents: .date)
                HStack {
                    Text(L.Sleep.asleep)
                    Spacer()
                    TextField(L.Sleep.asleep, value: $asleepHours, format: .number)
                        .keyboardType(.decimalPad)
                        .multilineTextAlignment(.trailing)
                        .frame(width: 80)
                }
                optionalRow(L.Sleep.inBed, value: $inBedHours)
                optionalRow(L.Sleep.rem, value: $remHours)
                optionalRow(L.Sleep.deep, value: $deepHours)
            }
            .navigationTitle(L.Sleep.logSleep)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(L.Common.cancel) { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L.Common.save) {
                        Task { await save() }
                    }
                    .disabled(saving || asleepHours <= 0)
                }
            }
            .errorAlert(message: $errorMessage)
        }
    }

    private func optionalRow(_ label: String, value: Binding<Double?>) -> some View {
        HStack {
            Text(label)
            Spacer()
            TextField(L.Common.none, value: value, format: .number)
                .keyboardType(.decimalPad)
                .multilineTextAlignment(.trailing)
                .frame(width: 80)
        }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            try await APIClient.shared.logSleep(NewSleepEntry(
                date: Day.string(from: date),
                asleepHours: asleepHours,
                inBedHours: inBedHours,
                remHours: remHours,
                deepHours: deepHours))
            Haptics.success()
            onSaved()
            dismiss()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}
