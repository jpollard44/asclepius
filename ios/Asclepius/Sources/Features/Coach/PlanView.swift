import SwiftUI

/// The living plan the coach maintains: goal, focus chips, markdown content,
/// and past revisions.
struct PlanView: View {
    var latestPlan: Plan?

    @Environment(\.dismiss) private var dismiss
    @State private var plan: Plan?
    @State private var history: [PlanHistoryEntry] = []
    @State private var isLoading = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let plan {
                        planBody(plan)
                    } else if isLoading {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 60)
                    } else {
                        EmptyState(
                            icon: "list.clipboard",
                            title: L.Coach.planTitle,
                            message: L.Coach.planEmpty)
                    }

                    if !history.isEmpty {
                        historySection
                    }
                }
                .padding()
            }
            .background(Theme.background)
            .navigationTitle(L.Coach.planTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L.Common.done) { dismiss() }
                }
            }
            .errorAlert(message: $errorMessage) {
                Task { await load() }
            }
            .task {
                plan = latestPlan
                await load()
            }
        }
    }

    @ViewBuilder
    private func planBody(_ plan: Plan) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            if let goal = plan.goal, !goal.isEmpty {
                Text(goal)
                    .font(.title3.bold())
            }
            if let updated = plan.updatedAt {
                Text("\(L.Coach.planUpdated) \(Timestamp.display(updated))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let focus = plan.focus, !focus.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text(L.Coach.planFocus)
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(.secondary)
                    FlowChips(items: focus)
                }
            }
            if let content = plan.content, !content.isEmpty {
                Divider()
                MarkdownText(markdown: content)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .cardStyle()
    }

    private var historySection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: L.Coach.planHistory)
            ForEach(history) { entry in
                VStack(alignment: .leading, spacing: 4) {
                    Text(entry.goal ?? "—")
                        .font(.subheadline.weight(.semibold))
                    if let focus = entry.focus, !focus.isEmpty {
                        Text(focus.joined(separator: " · "))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    if let saved = entry.savedAt {
                        Text(Timestamp.display(saved))
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .cardStyle()
            }
        }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await APIClient.shared.plan()
            if let fetched = response.plan {
                plan = fetched
            }
            history = response.history ?? []
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}

/// Simple wrapping chip row.
struct FlowChips: View {
    let items: [String]

    var body: some View {
        FlexibleHStack(spacing: 6) {
            ForEach(items, id: \.self) { item in
                Chip(text: item)
            }
        }
    }
}

/// Minimal wrapping layout for chips (iOS 16+ Layout protocol).
struct FlexibleHStack: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth, x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = Swift.max(rowHeight, size.height)
        }
        return CGSize(width: maxWidth == .infinity ? x : maxWidth, height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX, x > bounds.minX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = Swift.max(rowHeight, size.height)
        }
    }
}
