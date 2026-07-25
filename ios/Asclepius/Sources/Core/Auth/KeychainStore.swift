import Foundation
import Security

/// Thin wrapper over SecItem for storing auth tokens and the cached user
/// profile. Values are stored as generic passwords scoped to the app's
/// keychain service, accessible after first unlock so background sync can
/// authenticate.
struct KeychainStore: Sendable {
    enum Key: String, CaseIterable {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case userProfile = "user_profile"
    }

    private let service = AppConfig.keychainService

    // MARK: - Strings

    func string(for key: Key) -> String? {
        guard let data = data(for: key) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    func set(_ value: String, for key: Key) {
        set(Data(value.utf8), for: key)
    }

    // MARK: - Data

    func data(for key: Key) -> Data? {
        var query = baseQuery(for: key)
        query[kSecReturnData as String] = kCFBooleanTrue
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess else { return nil }
        return result as? Data
    }

    func set(_ data: Data, for key: Key) {
        var query = baseQuery(for: key)
        let attributes: [String: Any] = [kSecValueData as String: data]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            query[kSecValueData as String] = data
            query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
            SecItemAdd(query as CFDictionary, nil)
        }
    }

    func delete(_ key: Key) {
        SecItemDelete(baseQuery(for: key) as CFDictionary)
    }

    func clearAll() {
        for key in Key.allCases {
            delete(key)
        }
    }

    // MARK: - Codable convenience

    func decode<T: Decodable>(_ type: T.Type, for key: Key) -> T? {
        guard let data = data(for: key) else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }

    func encode<T: Encodable>(_ value: T, for key: Key) {
        guard let data = try? JSONEncoder().encode(value) else { return }
        set(data, for: key)
    }

    private func baseQuery(for key: Key) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key.rawValue,
        ]
    }
}
