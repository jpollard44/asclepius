import Foundation
import Observation

@MainActor
@Observable
final class CoachViewModel {
    private let api = APIClient.shared

    private(set) var messages: [ChatMessage] = []
    private(set) var hasMore = false
    private(set) var isLoadingHistory = false
    private(set) var isLoadingOlder = false
    private(set) var isSending = false
    var errorMessage: String?
    var plan: Plan?

    /// Local id sequence for optimistic messages (negative so they never
    /// collide with server ids).
    private var localID = -1

    struct SuggestionChip: Identifiable {
        let id: String
        let topic: String
        let label: String
    }

    let suggestions: [SuggestionChip] = [
        .init(id: "sleep", topic: "sleep", label: L.Coach.suggestionSleep),
        .init(id: "week", topic: "week", label: L.Coach.suggestionWeek),
        .init(id: "focus", topic: "focus", label: L.Coach.suggestionFocus),
    ]

    // MARK: - History

    func loadHistory() async {
        guard !isLoadingHistory else { return }
        isLoadingHistory = true
        defer { isLoadingHistory = false }
        do {
            let page = try await api.chatHistory(limit: 50)
            messages = page.messages ?? []
            hasMore = page.hasMore ?? false
        } catch {
            errorMessage = describe(error)
        }
    }

    func loadOlder() async {
        guard hasMore, !isLoadingOlder, let oldest = messages.first?.id, oldest > 0 else { return }
        isLoadingOlder = true
        defer { isLoadingOlder = false }
        do {
            let page = try await api.chatHistory(limit: 50, before: oldest)
            messages.insert(contentsOf: page.messages ?? [], at: 0)
            hasMore = page.hasMore ?? false
        } catch {
            errorMessage = describe(error)
        }
    }

    // MARK: - Sending

    func send(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isSending else { return }
        appendLocal(role: "user", content: trimmed)
        isSending = true
        defer { isSending = false }
        do {
            let reply = try await api.sendChat(trimmed)
            appendLocal(role: "assistant", content: reply.reply ?? "")
            if let plan = reply.plan {
                self.plan = plan
            }
        } catch {
            errorMessage = describe(error)
            // Remove the dangling optimistic user turn — the server only
            // persists turns that produced a reply.
            if let last = messages.last, last.id < 0, last.isUser {
                messages.removeLast()
            }
        }
    }

    func sendSuggestion(_ chip: SuggestionChip) async {
        guard !isSending else { return }
        appendLocal(role: "user", content: chip.label)
        isSending = true
        defer { isSending = false }
        do {
            let reply = try await api.recommend(topic: chip.topic, label: chip.label)
            appendLocal(role: "assistant", content: reply.reply ?? "")
        } catch {
            errorMessage = describe(error)
            if let last = messages.last, last.id < 0, last.isUser {
                messages.removeLast()
            }
        }
    }

    /// Fetches the proactive morning briefing (used to seed a fresh chat).
    func requestBriefing() async {
        guard !isSending else { return }
        isSending = true
        defer { isSending = false }
        do {
            let reply = try await api.briefing()
            appendLocal(role: "assistant", content: reply.reply ?? "")
            if let plan = reply.plan {
                self.plan = plan
            }
        } catch {
            errorMessage = describe(error)
        }
    }

    func startNewChat() async {
        do {
            try await api.clearChatHistory()
            messages = []
            hasMore = false
        } catch {
            errorMessage = describe(error)
        }
    }

    private func appendLocal(role: String, content: String) {
        messages.append(ChatMessage(id: localID, role: role, content: content))
        localID -= 1
    }

    private func describe(_ error: Error) -> String {
        (error as? APIError)?.errorDescription ?? L.Common.error
    }
}
