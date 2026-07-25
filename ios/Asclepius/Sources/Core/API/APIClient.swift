import Foundation

enum HTTPMethod: String {
    case get = "GET"
    case post = "POST"
    case put = "PUT"
    case delete = "DELETE"
}

/// Type-erasing box so the client can take `any Encodable` bodies.
struct AnyEncodable: Encodable {
    let value: any Encodable

    init(_ value: any Encodable) {
        self.value = value
    }

    func encode(to encoder: Encoder) throws {
        try value.encode(to: encoder)
    }
}

/// FastAPI error payload: `{"detail": "..."}`.
private struct ServerDetail: Decodable {
    var detail: String?
}

/// The single HTTP gateway to the Asclepius backend.
///
/// - Injects the bearer token from the Keychain on authenticated calls.
/// - On a 401, performs a single-flight token refresh and retries once; if
///   the refresh itself fails, the stored session is cleared and the
///   registered handler (AuthManager) is told to sign the user out.
/// - Chat calls use a long-timeout session because coach replies can take
///   30–120 seconds.
actor APIClient {
    static let shared = APIClient()

    private let keychain = KeychainStore()
    private let session: URLSession
    private let longSession: URLSession
    private var refreshTask: Task<Void, Error>?
    private var sessionExpiredHandler: (@Sendable () async -> Void)?

    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = AppConfig.requestTimeout
        config.waitsForConnectivity = false
        session = URLSession(configuration: config)

        let longConfig = URLSessionConfiguration.default
        longConfig.timeoutIntervalForRequest = AppConfig.chatTimeout
        longConfig.timeoutIntervalForResource = AppConfig.chatTimeout + 60
        longSession = URLSession(configuration: longConfig)
    }

    /// AuthManager registers here so a failed refresh signs the user out.
    func setSessionExpiredHandler(_ handler: @escaping @Sendable () async -> Void) {
        sessionExpiredHandler = handler
    }

    // MARK: - Requests

    func request<T: Decodable>(
        _ method: HTTPMethod,
        _ path: String,
        query: [URLQueryItem] = [],
        body: (any Encodable)? = nil,
        authenticated: Bool = true,
        longRunning: Bool = false
    ) async throws -> T {
        let data = try await requestData(
            method, path, query: query, body: body,
            authenticated: authenticated, longRunning: longRunning)
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }

    /// Fire-and-check variant for endpoints whose payload we don't need.
    @discardableResult
    func send(
        _ method: HTTPMethod,
        _ path: String,
        query: [URLQueryItem] = [],
        body: (any Encodable)? = nil,
        authenticated: Bool = true
    ) async throws -> SimpleStatus {
        let data = try await requestData(
            method, path, query: query, body: body,
            authenticated: authenticated, longRunning: false)
        return (try? decoder.decode(SimpleStatus.self, from: data)) ?? SimpleStatus(status: "ok")
    }

    /// Multipart upload of a single image under the field name "file".
    func uploadImage<T: Decodable>(
        _ path: String,
        imageData: Data,
        filename: String = "photo.jpg",
        mimeType: String = "image/jpeg"
    ) async throws -> T {
        guard let url = buildURL(path, query: []) else { throw APIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = HTTPMethod.post.rawValue

        let boundary = "asclepius-\(UUID().uuidString)"
        request.setValue("multipart/form-data; boundary=\(boundary)",
                         forHTTPHeaderField: "Content-Type")
        var body = Data()
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(Data("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".utf8))
        body.append(Data("Content-Type: \(mimeType)\r\n\r\n".utf8))
        body.append(imageData)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        request.httpBody = body
        request.timeoutInterval = AppConfig.chatTimeout

        let data = try await perform(request, authenticated: true, allowRetry: true, longRunning: true)
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }

    // MARK: - Internals

    private func requestData(
        _ method: HTTPMethod,
        _ path: String,
        query: [URLQueryItem],
        body: (any Encodable)?,
        authenticated: Bool,
        longRunning: Bool
    ) async throws -> Data {
        guard let url = buildURL(path, query: query) else { throw APIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = method.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            do {
                request.httpBody = try encoder.encode(AnyEncodable(body))
            } catch {
                throw APIError.decoding(error)
            }
        }
        if longRunning {
            request.timeoutInterval = AppConfig.chatTimeout
        }
        return try await perform(request, authenticated: authenticated,
                                 allowRetry: true, longRunning: longRunning)
    }

    private func buildURL(_ path: String, query: [URLQueryItem]) -> URL? {
        guard var components = URLComponents(
            url: AppConfig.baseURL.appending(path: path),
            resolvingAgainstBaseURL: false
        ) else { return nil }
        if !query.isEmpty {
            components.queryItems = query
        }
        return components.url
    }

    private func perform(
        _ request: URLRequest,
        authenticated: Bool,
        allowRetry: Bool,
        longRunning: Bool
    ) async throws -> Data {
        var req = request
        if authenticated, let token = keychain.string(for: .accessToken) {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await (longRunning ? longSession : session).data(for: req)
        } catch {
            throw APIError.transport(error)
        }
        guard let http = response as? HTTPURLResponse else {
            throw APIError.server(status: 0, message: nil)
        }

        switch http.statusCode {
        case 200 ..< 300:
            return data
        case 401 where authenticated:
            guard allowRetry else { throw APIError.unauthorized }
            try await refreshTokens()
            return try await perform(request, authenticated: true,
                                     allowRetry: false, longRunning: longRunning)
        default:
            let detail = try? decoder.decode(ServerDetail.self, from: data)
            throw APIError.server(status: http.statusCode, message: detail?.detail)
        }
    }

    // MARK: - Token refresh (single-flight)

    private func refreshTokens() async throws {
        if let existing = refreshTask {
            // Another call is already refreshing — piggyback on it.
            do {
                try await existing.value
                return
            } catch {
                throw APIError.unauthorized
            }
        }

        let task = Task { try await self.performRefresh() }
        refreshTask = task
        defer { refreshTask = nil }
        do {
            try await task.value
        } catch {
            await expireSession()
            throw APIError.unauthorized
        }
    }

    private func performRefresh() async throws {
        guard let refreshToken = keychain.string(for: .refreshToken) else {
            throw APIError.unauthorized
        }
        guard let url = buildURL("/api/auth/refresh", query: []) else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = HTTPMethod.post.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try encoder.encode(RefreshRequest(refreshToken: refreshToken))

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            // A network failure during refresh should not destroy the session;
            // surface it as transport so the caller can retry later.
            throw APIError.transport(error)
        }
        guard let http = response as? HTTPURLResponse, (200 ..< 300).contains(http.statusCode) else {
            throw APIError.unauthorized
        }
        let tokens = try decoder.decode(TokenResponse.self, from: data)
        storeTokens(tokens)
    }

    /// Persist a fresh token pair (used by both sign-in and refresh).
    func storeTokens(_ tokens: TokenResponse) {
        keychain.set(tokens.accessToken, for: .accessToken)
        keychain.set(tokens.refreshToken, for: .refreshToken)
        if let user = tokens.user {
            keychain.encode(user, for: .userProfile)
        }
    }

    func clearTokens() {
        keychain.clearAll()
    }

    var refreshTokenValue: String? {
        keychain.string(for: .refreshToken)
    }

    var hasSession: Bool {
        keychain.string(for: .refreshToken) != nil
    }

    var cachedUser: UserProfile? {
        keychain.decode(UserProfile.self, for: .userProfile)
    }

    func cacheUser(_ user: UserProfile) {
        keychain.encode(user, for: .userProfile)
    }

    private func expireSession() async {
        keychain.delete(.accessToken)
        keychain.delete(.refreshToken)
        await sessionExpiredHandler?()
    }
}
