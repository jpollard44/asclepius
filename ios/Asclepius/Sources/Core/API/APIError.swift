import Foundation

enum APIError: LocalizedError {
    case invalidURL
    case transport(Error)
    case server(status: Int, message: String?)
    case decoding(Error)
    case unauthorized

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid request URL."
        case .transport(let error):
            let ns = error as NSError
            if ns.domain == NSURLErrorDomain {
                switch ns.code {
                case NSURLErrorNotConnectedToInternet, NSURLErrorNetworkConnectionLost:
                    return "You appear to be offline."
                case NSURLErrorTimedOut:
                    return "The request timed out."
                default:
                    break
                }
            }
            return "Couldn't reach the server."
        case .server(let status, let message):
            if let message, !message.isEmpty { return message }
            return "Server error (\(status))."
        case .decoding:
            return "Received an unexpected response."
        case .unauthorized:
            return "Your session expired. Please sign in again."
        }
    }

    var isUnauthorized: Bool {
        switch self {
        case .unauthorized: return true
        case .server(let status, _): return status == 401
        default: return false
        }
    }
}
