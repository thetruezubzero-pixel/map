import SwiftUI
import Combine
import Alamofire

// MARK: - App Entry Point

@main
struct AetherSovereignOSApp: App {
  @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
  @StateObject var authManager = AuthenticationManager.shared
  @StateObject var networkManager = NetworkManager.shared
  @StateObject var locationManager = LocationManager.shared

  var body: some Scene {
    WindowGroup {
      if authManager.isAuthenticated {
        ContentView()
          .environmentObject(authManager)
          .environmentObject(networkManager)
          .environmentObject(locationManager)
      } else {
        LoginView()
          .environmentObject(authManager)
      }
    }
  }
}

// MARK: - App Delegate

class AppDelegate: NSObject, UIApplicationDelegate {
  func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
  ) -> Bool {
    // Initialize Firebase
    FirebaseApp.configure()

    // Set up Crashlytics
    Crashlytics.crashlytics().setCrashlyticsCollectionEnabled(true)

    // Configure network session
    NetworkManager.shared.configureSession()

    // Initialize location services
    LocationManager.shared.requestWhenInUseAuthorization()

    return true
  }

  func application(
    _ application: UIApplication,
    supportedInterfaceOrientationsFor window: UIWindow?
  ) -> UIInterfaceOrientationMask {
    return [.portrait, .landscapeLeft, .landscapeRight]
  }
}

// MARK: - Main Content View

struct ContentView: View {
  @EnvironmentObject var authManager: AuthenticationManager
  @State var selectedTab: Tab = .map

  enum Tab {
    case map
    case search
    case research
    case agents
    case heirlooms
    case chat
    case settings
  }

  var body: some View {
    TabView(selection: $selectedTab) {
      // Map Tab
      MapView()
        .tabItem {
          Image(systemName: "map.fill")
          Text("Map")
        }
        .tag(Tab.map)

      // Search Tab
      SearchView()
        .tabItem {
          Image(systemName: "magnifyingglass")
          Text("Search")
        }
        .tag(Tab.search)

      // Research Tab
      ResearchView()
        .tabItem {
          Image(systemName: "doc.text.magnifyingglass")
          Text("Research")
        }
        .tag(Tab.research)

      // Agents Tab
      AgentsView()
        .tabItem {
          Image(systemName: "network")
          Text("Agents")
        }
        .tag(Tab.agents)

      // Heirlooms Tab
      HeirloomsView()
        .tabItem {
          Image(systemName: "crown.fill")
          Text("Heirlooms")
        }
        .tag(Tab.heirlooms)

      // Chat Tab
      ChatView()
        .tabItem {
          Image(systemName: "bubble.right.fill")
          Text("Chat")
        }
        .tag(Tab.chat)

      // Settings Tab
      SettingsView()
        .tabItem {
          Image(systemName: "gear")
          Text("Settings")
        }
        .tag(Tab.settings)
    }
    .onAppear {
      UITabBar.appearance().backgroundColor = UIColor(named: "Surface")
    }
  }
}

// MARK: - Placeholder Views (Stubs)

struct MapView: View {
  var body: some View {
    ZStack {
      Color(UIColor(named: "Background") ?? .systemBackground)
        .ignoresSafeArea()

      VStack {
        Text("Map View")
          .font(.headline)
        Text("Interactive map with entity layers")
          .font(.caption)
          .foregroundColor(.gray)
      }
    }
  }
}

struct SearchView: View {
  var body: some View {
    ZStack {
      Color(UIColor(named: "Background") ?? .systemBackground)
        .ignoresSafeArea()

      VStack {
        Text("Search View")
          .font(.headline)
        Text("Entity search & filtering")
          .font(.caption)
          .foregroundColor(.gray)
      }
    }
  }
}

struct ResearchView: View {
  var body: some View {
    ZStack {
      Color(UIColor(named: "Background") ?? .systemBackground)
        .ignoresSafeArea()

      VStack {
        Text("Research View")
          .font(.headline)
        Text("Multi-agent research pipeline")
          .font(.caption)
          .foregroundColor(.gray)
      }
    }
  }
}

struct AgentsView: View {
  var body: some View {
    ZStack {
      Color(UIColor(named: "Background") ?? .systemBackground)
        .ignoresSafeArea()

      VStack {
        Text("Agents View")
          .font(.headline)
        Text("Agent roster & weight graph")
          .font(.caption)
          .foregroundColor(.gray)
      }
    }
  }
}

struct HeirloomsView: View {
  var body: some View {
    ZStack {
      Color(UIColor(named: "Background") ?? .systemBackground)
        .ignoresSafeArea()

      VStack {
        Text("Heirlooms View")
          .font(.headline)
        Text("Cross-device knowledge persistence")
          .font(.caption)
          .foregroundColor(.gray)
      }
    }
  }
}

struct ChatView: View {
  var body: some View {
    ZStack {
      Color(UIColor(named: "Background") ?? .systemBackground)
        .ignoresSafeArea()

      VStack {
        Text("Chat View")
          .font(.headline)
        Text("Conversational research interface")
          .font(.caption)
          .foregroundColor(.gray)
      }
    }
  }
}

struct SettingsView: View {
  @EnvironmentObject var authManager: AuthenticationManager

  var body: some View {
    NavigationStack {
      Form {
        Section("Account") {
          Button(role: .destructive) {
            authManager.logout()
          } label: {
            Text("Logout")
          }
        }

        Section("About") {
          HStack {
            Text("Version")
            Spacer()
            Text("1.0.0")
              .foregroundColor(.gray)
          }

          HStack {
            Text("Build")
            Spacer()
            Text("1")
              .foregroundColor(.gray)
          }

          Link(destination: URL(string: "https://github.com/thetruezubzero-pixel/map")!) {
            Text("GitHub Repository")
          }

          Link(destination: URL(string: "https://github.com/thetruezubzero-pixel/map/blob/main/PRIVACY.md")!) {
            Text("Privacy Policy")
          }
        }
      }
      .navigationTitle("Settings")
    }
  }
}

struct LoginView: View {
  @EnvironmentObject var authManager: AuthenticationManager
  @State var jwtToken = ""
  @State var showError = false
  @State var errorMessage = ""

  var body: some View {
    ZStack {
      LinearGradient(
        gradient: Gradient(colors: [
          Color(UIColor(named: "Accent") ?? .systemBlue).opacity(0.1),
          Color(UIColor(named: "Background") ?? .systemBackground)
        ]),
        startPoint: .topLeading,
        endPoint: .bottomTrailing
      )
      .ignoresSafeArea()

      VStack(spacing: 20) {
        VStack(spacing: 8) {
          Image(systemName: "map.circle.fill")
            .font(.system(size: 48))
            .foregroundColor(.accentColor)

          Text("Aether Sovereign OS")
            .font(.title2)
            .fontWeight(.bold)

          Text("Public Records Research Platform")
            .font(.caption)
            .foregroundColor(.gray)
        }
        .padding(.bottom, 32)

        VStack(spacing: 12) {
          SecureField("JWT Token", text: $jwtToken)
            .textFieldStyle(.roundedBorder)
            .font(.caption)

          Button {
            authManager.login(with: jwtToken) { success, error in
              if !success {
                showError = true
                errorMessage = error ?? "Authentication failed"
              }
            }
          } label: {
            Text("Login")
              .frame(maxWidth: .infinity)
              .padding()
              .background(.accentColor)
              .foregroundColor(.white)
              .cornerRadius(8)
          }
          .disabled(jwtToken.isEmpty)

          if showError {
            Text(errorMessage)
              .font(.caption)
              .foregroundColor(.red)
              .padding(8)
              .background(Color.red.opacity(0.1))
              .cornerRadius(4)
          }
        }
        .padding()
        .background(Color(UIColor(named: "Surface") ?? .secondarySystemBackground))
        .cornerRadius(12)

        VStack(spacing: 8) {
          Text("Don't have a token?")
            .font(.caption)
            .foregroundColor(.gray)

          Link(destination: URL(string: "https://github.com/settings/tokens")!) {
            Text("Generate one on GitHub")
              .font(.caption)
              .foregroundColor(.accentColor)
          }
        }
        .padding(.top, 16)

        Spacer()
      }
      .padding()
    }
  }
}

// MARK: - Previews

#Preview {
  LoginView()
    .environmentObject(AuthenticationManager.shared)
}
