import Foundation
import Observation

enum AppTab: Hashable {
    case today
    case coach
    case food
    case fitness
    case more
}

/// Destinations inside the More tab's navigation stack.
enum MoreRoute: Hashable {
    case sleep
    case body
    case goals
    case achievements
    case weeklyReport
    case settings
}

/// Global navigation state: the selected tab and the More tab's path, so
/// notification taps can deep-link anywhere.
@MainActor
@Observable
final class AppRouter {
    static let shared = AppRouter()

    var selectedTab: AppTab = .today
    var morePath: [MoreRoute] = []

    /// Routes a push-notification `ntype` to the right screen.
    func handleNotification(type: String) {
        switch type {
        case "breakfast", "lunch", "dinner", "snack", "meal", "food", "water":
            selectedTab = .food
        case "workout":
            selectedTab = .fitness
        case "sleep":
            selectedTab = .more
            morePath = [.sleep]
        case "coach", "weekly":
            selectedTab = .coach
        default:
            selectedTab = .today
        }
    }

    func open(_ route: MoreRoute) {
        selectedTab = .more
        morePath = [route]
    }
}
