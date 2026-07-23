import Foundation
import Combine
import Keychain

// MARK: - Authentication Manager

class AuthenticationManager: NSObject, ObservableObject {
  static let shared = AuthenticationManager()

  @Published var isAuthenticated = false
  @Published var currentUser: User? = nil
  @Published var jwtToken: String? = nil

  private let keychain = Keychain(service: "com.aethersovereign.map")
  private var cancellables = Set<AnyCancellable>()

  private override init() {
    super.init()
    restoreSession()
  }

  // MARK: - Authentication Methods

  func login(with token: String, completion: @escaping (Bool, String?) -> Void) {
    // Validate token format
    guard token.split(separator: ".").count == 3 else {
      completion(false, "Invalid JWT format")
      return
    }

    // Store token securely
    do {
      try keychain.set(token, key: "jwtToken")
      self.jwtToken = token
    } catch {
      completion(false, "Failed to store token: \(error.localizedDescription)")
      return
    }

    // Verify token is valid by making a test API call
    verifyToken(token) { [weak self] success, error in
      if success {
        self?.isAuthenticated = true
        self?.currentUser = User(
          id: "user-\(UUID().uuidString)",
          email: "user@aethersovereign.local",
          joinedAt: Date()
        )
        completion(true, nil)
      } else {
        completion(false, error ?? "Token verification failed")
      }
    }
  }

  func logout() {
    do {
      try keychain.remove("jwtToken")
      self.jwtToken = nil
      self.isAuthenticated = false
      self.currentUser = nil
    } catch {
      print("Error removing token from keychain: \(error)")
    }
  }

  func refreshToken(completion: @escaping (Bool) -> Void) {
    guard let token = jwtToken else {
      completion(false)
      return
    }

    verifyToken(token) { [weak self] success, _ in
      if success {
        self?.isAuthenticated = true
      } else {
        self?.logout()
      }
      completion(success)
    }
  }

  // MARK: - Private Methods

  private func restoreSession() {
    do {
      if let token = try keychain.get("jwtToken") {
        self.jwtToken = token
        verifyToken(token) { [weak self] success, _ in
          if success {
            self?.isAuthenticated = true
            self?.currentUser = User(
              id: "user-\(UUID().uuidString)",
              email: "user@aethersovereign.local",
              joinedAt: Date()
            )
          } else {
            self?.logout()
          }
        }
      }
    } catch {
      print("Error restoring session: \(error)")
    }
  }

  private func verifyToken(_ token: String, completion: @escaping (Bool, String?) -> Void) {
    let baseURL = APIClient.baseURL
    let url = URL(string: "\(baseURL)/health")!

    var request = URLRequest(url: url)
    request.httpMethod = "GET"
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.timeoutInterval = 10

    URLSession.shared.dataTask(with: request) { data, response, error in
      DispatchQueue.main.async {
        if let error = error {
          completion(false, error.localizedDescription)
          return
        }

        if let httpResponse = response as? HTTPURLResponse {
          let success = (200...299).contains(httpResponse.statusCode)
          completion(success, success ? nil : "HTTP \(httpResponse.statusCode)")
        } else {
          completion(false, "Invalid response")
        }
      }
    }.resume()
  }
}

// MARK: - User Model

struct User: Codable {
  let id: String
  let email: String
  let joinedAt: Date

  enum CodingKeys: String, CodingKey {
    case id
    case email
    case joinedAt = "joined_at"
  }
}
