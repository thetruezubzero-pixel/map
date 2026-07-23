import Foundation
import CoreLocation
import Combine

// MARK: - Location Manager

class LocationManager: NSObject, ObservableObject, CLLocationManagerDelegate {
  static let shared = LocationManager()

  @Published var userLocation: CLLocationCoordinate2D? = nil
  @Published var authorizationStatus: CLAuthorizationStatus = .notDetermined
  @Published var isLocationUpdating = false
  @Published var lastError: Error? = nil

  private let locationManager = CLLocationManager()

  private override init() {
    super.init()
    locationManager.delegate = self
    locationManager.desiredAccuracy = kCLLocationAccuracyBest
    locationManager.distanceFilter = 50 // Update every 50 meters
    checkAuthorizationStatus()
  }

  // MARK: - Authorization

  func requestWhenInUseAuthorization() {
    locationManager.requestWhenInUseAuthorization()
  }

  func requestAlwaysAndWhenInUseAuthorization() {
    locationManager.requestAlwaysAndWhenInUseAuthorization()
  }

  private func checkAuthorizationStatus() {
    authorizationStatus = locationManager.authorizationStatus
    if authorizationStatus == .authorizedWhenInUse || authorizationStatus == .authorizedAlways {
      startUpdatingLocation()
    }
  }

  // MARK: - Location Updates

  func startUpdatingLocation() {
    if authorizationStatus == .authorizedWhenInUse || authorizationStatus == .authorizedAlways {
      isLocationUpdating = true
      locationManager.startUpdatingLocation()
    }
  }

  func stopUpdatingLocation() {
    isLocationUpdating = false
    locationManager.stopUpdatingLocation()
  }

  // MARK: - CLLocationManagerDelegate

  func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
    guard let location = locations.last else { return }
    DispatchQueue.main.async {
      self.userLocation = location.coordinate
    }
  }

  func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
    DispatchQueue.main.async {
      self.lastError = error
    }
  }

  func locationManager(_ manager: CLLocationManager, didChangeAuthorization status: CLAuthorizationStatus) {
    DispatchQueue.main.async {
      self.authorizationStatus = status
      if status == .authorizedWhenInUse || status == .authorizedAlways {
        self.startUpdatingLocation()
      } else {
        self.stopUpdatingLocation()
      }
    }
  }

  // MARK: - Utilities

  func distance(to coordinate: CLLocationCoordinate2D) -> Double? {
    guard let userLocation = userLocation else { return nil }
    let userCLLocation = CLLocation(latitude: userLocation.latitude, longitude: userLocation.longitude)
    let targetCLLocation = CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
    return userCLLocation.distance(from: targetCLLocation)
  }
}
