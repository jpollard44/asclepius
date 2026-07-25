import SwiftUI

struct CoachView: View {
    @Environment(AppState.self) private var appState

    @State private var model = CoachViewModel()
    @State private var draft = ""
    @State private var showPlan = false
    @State private var confirmNewChat = false

    var body: some View {
        NavigationStack {
            Group {
                if appState.hasData || !model.messages.isEmpty {
                    conversation
                } else {
                    EmptyState(
                        icon: "bubble.left.and.exclamationmark.bubble.right",
                        title: L.Coach.needsDataTitle,
                        message: L.Coach.needsDataBody)
                }
            }
            .navigationTitle(L.Coach.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        showPlan = true
                    } label: {
                        Label(L.Coach.plan, systemImage: "list.clipboard")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button(L.Coach.briefing, systemImage: "sunrise") {
                            Task { await model.requestBriefing() }
                        }
                        Button(L.Coach.newChat, systemImage: "square.and.pencil", role: .destructive) {
                            confirmNewChat = true
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            }
            .sheet(isPresented: $showPlan) {
                PlanView(latestPlan: model.plan)
            }
            .confirmationDialog(L.Coach.newChatConfirm, isPresented: $confirmNewChat, titleVisibility: .visible) {
                Button(L.Coach.newChat, role: .destructive) {
                    Task { await model.startNewChat() }
                }
                Button(L.Common.cancel, role: .cancel) {}
            }
            .errorAlert(message: Binding(
                get: { model.errorMessage },
                set: { model.errorMessage = $0 }))
            .task {
                if model.messages.isEmpty {
                    await model.loadHistory()
                }
            }
        }
    }

    // MARK: - Conversation

    private var conversation: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 12) {
                        if model.hasMore {
                            Button {
                                Task { await model.loadOlder() }
                            } label: {
                                if model.isLoadingOlder {
                                    ProgressView()
                                } else {
                                    Text(L.Coach.loadOlder)
                                        .font(.footnote)
                                }
                            }
                            .padding(.top, 8)
                        }

                        if model.messages.isEmpty && !model.isLoadingHistory {
                            EmptyState(
                                icon: "hand.wave",
                                title: L.Coach.emptyTitle,
                                message: L.Coach.emptyBody,
                                actionTitle: L.Coach.briefing
                            ) {
                                Task { await model.requestBriefing() }
                            }
                        }

                        ForEach(model.messages) { message in
                            MessageBubble(message: message)
                                .id(message.id)
                        }

                        if model.isSending {
                            TypingIndicator()
                                .id("typing")
                        }
                    }
                    .padding(.horizontal)
                    .padding(.bottom, 8)
                }
                .onChange(of: model.messages.count) {
                    withAnimation {
                        if model.isSending {
                            proxy.scrollTo("typing", anchor: .bottom)
                        } else if let last = model.messages.last {
                            proxy.scrollTo(last.id, anchor: .bottom)
                        }
                    }
                }
                .refreshable {
                    await model.loadHistory()
                }
            }

            suggestionRow
            inputBar
        }
        .background(Theme.background)
    }

    private var suggestionRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(model.suggestions) { chip in
                    Chip(text: chip.label, systemImage: "sparkles") {
                        Haptics.tap()
                        Task { await model.sendSuggestion(chip) }
                    }
                    .disabled(model.isSending)
                }
            }
            .padding(.horizontal)
            .padding(.vertical, 6)
        }
    }

    private var inputBar: some View {
        HStack(spacing: 10) {
            TextField(L.Coach.placeholder, text: $draft, axis: .vertical)
                .lineLimit(1 ... 4)
                .textFieldStyle(.plain)
                .padding(.horizontal, 14)
                .padding(.vertical, 9)
                .background(Theme.cardBackground, in: RoundedRectangle(cornerRadius: 20))

            Button {
                let text = draft
                draft = ""
                Haptics.tap()
                Task { await model.send(text) }
            } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 30))
                    .foregroundStyle(canSend ? Theme.accent : Color.secondary)
            }
            .disabled(!canSend)
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(.bar)
    }

    private var canSend: Bool {
        !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !model.isSending
    }
}

// MARK: - Bubbles

struct MessageBubble: View {
    let message: ChatMessage

    var body: some View {
        HStack {
            if message.isUser { Spacer(minLength: 48) }
            Group {
                if message.isUser {
                    Text(message.content)
                        .foregroundStyle(.white)
                } else {
                    MarkdownText(markdown: message.content)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                message.isUser ? AnyShapeStyle(Theme.accent) : AnyShapeStyle(Theme.cardBackground),
                in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            if !message.isUser { Spacer(minLength: 48) }
        }
    }
}

struct TypingIndicator: View {
    @State private var phase = 0

    var body: some View {
        HStack {
            HStack(spacing: 5) {
                ForEach(0 ..< 3, id: \.self) { index in
                    Circle()
                        .fill(Color.secondary)
                        .frame(width: 7, height: 7)
                        .opacity(phase == index ? 1 : 0.35)
                }
                Text(L.Coach.thinking)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.leading, 4)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(Theme.cardBackground, in: RoundedRectangle(cornerRadius: 18))
            Spacer(minLength: 48)
        }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 350_000_000)
                phase = (phase + 1) % 3
            }
        }
    }
}
