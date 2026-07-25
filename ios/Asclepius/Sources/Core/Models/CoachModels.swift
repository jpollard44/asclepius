import Foundation

// MARK: - Chat

/// One persisted coach-conversation message.
struct ChatMessage: Decodable, Identifiable, Equatable {
    var id: Int
    var timestamp: String?
    var role: String
    var content: String

    enum CodingKeys: String, CodingKey {
        case id, timestamp, role, content
    }

    init(id: Int, timestamp: String? = nil, role: String, content: String) {
        self.id = id
        self.timestamp = timestamp
        self.role = role
        self.content = content
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decode(Int.self, forKey: .id)) ?? Int.random(in: Int.min ..< 0)
        timestamp = try? c.decodeIfPresent(String.self, forKey: .timestamp)
        role = (try? c.decodeIfPresent(String.self, forKey: .role)) ?? "assistant"
        content = (try? c.decodeIfPresent(String.self, forKey: .content)) ?? ""
    }

    var isUser: Bool { role == "user" }
}

struct ChatHistoryResponse: Decodable {
    var messages: [ChatMessage]?
    var hasMore: Bool?

    enum CodingKeys: String, CodingKey {
        case messages
        case hasMore = "has_more"
    }
}

/// POST /api/chat request body.
struct ChatRequest: Encodable {
    struct Turn: Encodable {
        var role: String
        var content: String
    }

    var messages: [Turn]
}

/// POST /api/chat and /api/briefing reply.
struct ChatReply: Decodable {
    var reply: String?
    var plan: Plan?
}

/// POST /api/recommend.
struct RecommendRequest: Encodable {
    var topic: String
    var label: String?
}

struct RecommendReply: Decodable {
    var reply: String?
    var topic: String?
}

// MARK: - Plan

/// The living plan the coach maintains.
struct Plan: Decodable, Equatable {
    var goal: String?
    var focus: [String]?
    var content: String?
    var updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case goal, focus, content
        case updatedAt = "updated_at"
    }
}

struct PlanHistoryEntry: Decodable, Identifiable {
    var goal: String?
    var focus: [String]?
    var savedAt: String?

    var id: String { savedAt ?? goal ?? UUID().uuidString }

    enum CodingKeys: String, CodingKey {
        case goal, focus
        case savedAt = "saved_at"
    }
}

struct PlanResponse: Decodable {
    var plan: Plan?
    var history: [PlanHistoryEntry]?
}

// MARK: - Push preferences

struct PushTypePref: Decodable, Identifiable {
    var key: String?
    var enabled: Bool?
    var time: String?
    var label: String?
    var desc: String?
    var editableTime: Bool?

    var id: String { key ?? label ?? UUID().uuidString }

    enum CodingKeys: String, CodingKey {
        case key, enabled, time, label, desc
        case editableTime = "editable_time"
    }
}

/// GET /api/push/prefs.
struct PushPrefsResponse: Decodable {
    var enabled: Bool?
    var dndStart: String?
    var dndEnd: String?
    var types: [String: PushTypePref]?

    enum CodingKeys: String, CodingKey {
        case enabled, types
        case dndStart = "dnd_start"
        case dndEnd = "dnd_end"
    }
}

/// PUT /api/push/prefs — partial update.
struct PushPrefsUpdate: Encodable {
    struct TypeUpdate: Encodable {
        var enabled: Bool? = nil
        var time: String? = nil
    }

    var enabled: Bool? = nil
    var dndStart: String? = nil
    var dndEnd: String? = nil
    var types: [String: TypeUpdate]? = nil

    enum CodingKeys: String, CodingKey {
        case enabled, types
        case dndStart = "dnd_start"
        case dndEnd = "dnd_end"
    }
}
