import SwiftUI

struct MainTabView: View {
    @Environment(AppRouter.self) private var router

    var body: some View {
        @Bindable var router = router
        TabView(selection: $router.selectedTab) {
            TodayView()
                .tabItem { Label(L.Tabs.today, systemImage: "sun.max.fill") }
                .tag(AppTab.today)

            CoachView()
                .tabItem { Label(L.Tabs.coach, systemImage: "bubble.left.and.text.bubble.right.fill") }
                .tag(AppTab.coach)

            FoodView()
                .tabItem { Label(L.Tabs.food, systemImage: "fork.knife") }
                .tag(AppTab.food)

            FitnessView()
                .tabItem { Label(L.Tabs.fitness, systemImage: "dumbbell.fill") }
                .tag(AppTab.fitness)

            MoreView()
                .tabItem { Label(L.Tabs.more, systemImage: "ellipsis.circle.fill") }
                .tag(AppTab.more)
        }
    }
}
