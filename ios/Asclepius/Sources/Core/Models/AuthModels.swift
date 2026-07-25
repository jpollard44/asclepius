import Foundation

/// The signed-in user, as returned inside auth and account payloads.
struct UserProfile: Codable, Equatable {
    var id: String
    var email: String?
    var name: String?

    init(id: String, email: String? = nil, name: String? = nil) {
        self.id = id
        self.email = email
        self.name = name
    }

    enum CodingKeys: String, CodingKey {
        case id, email, name
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        // The backend may serialize the id as a string or an integer.
        if let s = try? c.decode(String.self, forKey: .id) {
            id = s
        } else if let i = try? c.decode(Int.self, forKey: .id) {
            id = String(i)
        } else {
            id = ""
        }
        email = try c.decodeIfPresent(String.self, forKey: .email)
        name = try c.decodeIfPresent(String.self, forKey: .name)
    }
}

/// POST /api/auth/apple and /api/auth/refresh both return this shape.
struct TokenResponse: Decodable {
    var accessToken: String
    var refreshToken: String
    var expiresIn: Double?
    var user: UserProfile?

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case expiresIn = "expires_in"
        case user
    }
}

/// GET /api/account.
struct AccountResponse: Decodable {
    var user: UserProfile?
    var createdAt: String?

    enum CodingKeys: String, CodingKey {
        case user
        case createdAt = "created_at"
    }
}

// MARK: - Request bodies

struct AppleSignInRequest: Encodable {
    var identityToken: String
    var fullName: String?
    var email: String?

    enum CodingKeys: String, CodingKey {
        case identityToken = "identity_token"
        case fullName = "full_name"
        case email
    }
}

struct RefreshRequest: Encodable {
    var refreshToken: String

    enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}

struct LogoutRequest: Encodable {
    var refreshToken: String

    enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}

/// POST /api/devices — APNs device registration.
struct DeviceRegistration: Encodable {
    var platform: String = "ios"
    var token: String
    var environment: String
}
