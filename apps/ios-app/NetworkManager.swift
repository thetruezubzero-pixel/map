import Foundation
import Combine
import Alamofire

// MARK: - API Client Configuration

class APIClient {
  static let baseURL = ProcessInfo.processInfo.environment["API_BASE_URL"] ?? "http://localhost:8000"
  static let pythonAPIBaseURL = ProcessInfo.processInfo.environment["PYTHON_API_URL"] ?? "http://localhost:8001"
  static let gatewayBaseURL = ProcessInfo.processInfo.environment["GATEWAY_URL"] ?? "http://localhost:3000"
}

// MARK: - Network Manager

class NetworkManager: NSObject, ObservableObject {
  static let shared = NetworkManager()

  @Published var isConnected = true
  @Published var isLoading = false
  @Published var lastError: Error? = nil

  private var reachability: Reachability?
  private var cancellables = Set<AnyCancellable>()
  private var session: Session?

  private override init() {
    super.init()
    configureSession()
    setupReachability()
  }

  // MARK: - Session Configuration

  func configureSession() {
    let configuration = URLSessionConfiguration.af.default
    configuration.timeoutIntervalForRequest = 30
    configuration.timeoutIntervalForResource = 300
    configuration.waitsForConnectivity = true
    configuration.httpMaximumConnectionsPerHost = 10
    configuration.httpShouldUsePipelining = true

    // TLS Configuration
    let trustManager = ServerTrustManager(
      evaluators: [
        "localhost": DisabledTrustEvaluator(),
        "127.0.0.1": DisabledTrustEvaluator(),
      ]
    )

    self.session = Session(
      configuration: configuration,
      serverTrustManager: trustManager
    )
  }

  // MARK: - Network Reachability

  private func setupReachability() {
    do {
      reachability = try Reachability(hostname: APIClient.baseURL)
      reachability?.whenReachable = { [weak self] _ in
        DispatchQueue.main.async {
          self?.isConnected = true
        }
      }
      reachability?.whenUnreachable = { [weak self] _ in
        DispatchQueue.main.async {
          self?.isConnected = false
        }
      }
      try reachability?.startNotifier()
    } catch {
      print("Failed to set up reachability: \(error)")
    }
  }

  // MARK: - Generic API Methods

  func request<T: Decodable>(
    _ endpoint: APIEndpoint,
    method: HTTPMethod = .get,
    parameters: [String: Any]? = nil,
    token: String? = nil
  ) -> AnyPublisher<T, Error> {
    let url = URL(string: endpoint.url)!
    var headers: HTTPHeaders = [.accept("application/json")]

    if let token = token {
      headers.add(.authorization(bearerToken: token))
    }

    return Future { [weak self] promise in
      self?.isLoading = true

      self?.session?.request(url, method: method, parameters: parameters, headers: headers)
        .validate(statusCode: 200..<300)
        .responseDecodable(of: T.self) { response in
          self?.isLoading = false

          switch response.result {
          case .success(let value):
            promise(.success(value))
          case .failure(let error):
            self?.lastError = error
            promise(.failure(error))
          }
        }
    }
    .eraseToAnyPublisher()
  }

  func requestArray<T: Decodable>(
    _ endpoint: APIEndpoint,
    method: HTTPMethod = .get,
    parameters: [String: Any]? = nil,
    token: String? = nil
  ) -> AnyPublisher<[T], Error> {
    let url = URL(string: endpoint.url)!
    var headers: HTTPHeaders = [.accept("application/json")]

    if let token = token {
      headers.add(.authorization(bearerToken: token))
    }

    return Future { [weak self] promise in
      self?.isLoading = true

      self?.session?.request(url, method: method, parameters: parameters, headers: headers)
        .validate(statusCode: 200..<300)
        .responseDecodable(of: [T].self) { response in
          self?.isLoading = false

          switch response.result {
          case .success(let value):
            promise(.success(value))
          case .failure(let error):
            self?.lastError = error
            promise(.failure(error))
          }
        }
    }
    .eraseToAnyPublisher()
  }

  func upload<T: Decodable>(
    _ endpoint: APIEndpoint,
    data: Data,
    fileName: String,
    mimeType: String,
    token: String? = nil
  ) -> AnyPublisher<T, Error> {
    let url = URL(string: endpoint.url)!
    var headers: HTTPHeaders = [.accept("application/json")]

    if let token = token {
      headers.add(.authorization(bearerToken: token))
    }

    return Future { [weak self] promise in
      self?.isLoading = true

      self?.session?.upload(multipartFormData: { multipart in
        multipart.append(data, withName: "file", fileName: fileName, mimeType: mimeType)
      }, to: url, headers: headers)
        .validate(statusCode: 200..<300)
        .responseDecodable(of: T.self) { response in
          self?.isLoading = false

          switch response.result {
          case .success(let value):
            promise(.success(value))
          case .failure(let error):
            self?.lastError = error
            promise(.failure(error))
          }
        }
    }
    .eraseToAnyPublisher()
  }

  // MARK: - WebSocket

  func connectWebSocket(
    path: String,
    token: String,
    onMessage: @escaping (String) -> Void,
    onError: @escaping (Error) -> Void,
    onClose: @escaping () -> Void
  ) -> Cancellable {
    let wsURL = APIClient.baseURL
      .replacingOccurrences(of: "http://", with: "ws://")
      .replacingOccurrences(of: "https://", with: "wss://")

    let socket = WebSocketManager(
      url: "\(wsURL)\(path)?token=\(token)",
      onMessage: onMessage,
      onError: onError,
      onClose: onClose
    )

    socket.connect()

    return AnyCancellable {
      socket.disconnect()
    }
  }
}

// MARK: - API Endpoint Enum

enum APIEndpoint {
  case health
  case search(String)
  case entity(String)
  case research(String)
  case agents
  case swarm
  case chat(String)
  case heirlooms
  case training

  var url: String {
    let base = APIClient.baseURL
    switch self {
    case .health:
      return "\(base)/health"
    case .search(let query):
      return "\(base)/search?q=\(query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")"
    case .entity(let id):
      return "\(base)/entity/\(id)"
    case .research(let jobId):
      return "\(base)/research/\(jobId)"
    case .agents:
      return "\(base)/agents"
    case .swarm:
      return "\(base)/swarm"
    case .chat(let message):
      return "\(APIClient.pythonAPIBaseURL)/chat"
    case .heirlooms:
      return "\(base)/heirlooms"
    case .training:
      return "\(base)/training"
    }
  }
}

// MARK: - WebSocket Manager

class WebSocketManager: NSObject, URLSessionWebSocketDelegate {
  private let url: String
  private var webSocket: URLSessionWebSocket?
  private let onMessage: (String) -> Void
  private let onError: (Error) -> Void
  private let onClose: () -> Void

  init(
    url: String,
    onMessage: @escaping (String) -> Void,
    onError: @escaping (Error) -> Void,
    onClose: @escaping () -> Void
  ) {
    self.url = url
    self.onMessage = onMessage
    self.onError = onError
    self.onClose = onClose
  }

  func connect() {
    guard let url = URL(string: url) else {
      onError(NSError(domain: "Invalid URL", code: -1))
      return
    }

    webSocket = URLSessionWebSocket(url: url)
    webSocket?.resume()
    receiveMessage()
  }

  func disconnect() {
    webSocket?.cancel(with: .goingAway, reason: nil)
    onClose()
  }

  private func receiveMessage() {
    webSocket?.receive { [weak self] result in
      switch result {
      case .success(let message):
        switch message {
        case .string(let text):
          self?.onMessage(text)
        case .data(let data):
          if let text = String(data: data, encoding: .utf8) {
            self?.onMessage(text)
          }
        @unknown default:
          break
        }
        self?.receiveMessage()
      case .failure(let error):
        self?.onError(error)
      }
    }
  }
}
