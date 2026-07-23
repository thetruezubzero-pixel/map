# Aether Sovereign OS — iOS App

Production-ready iOS application for Aether Sovereign OS public records research platform.

## Overview

This is a native Swift/SwiftUI iOS app that provides access to the full Aether Sovereign OS research platform on iPhone and iPad. The app integrates with the backend REST APIs (gateway, python-api) via JWT authentication and WebSocket connections.

## Features

- **Interactive Map** — Mapbox GL integration for real-time entity layer visualization
- **Entity Search** — Full-text + spatial search with faceted filters
- **Research Pipeline** — Multi-agent consensus research with live progress tracking
- **Chat Interface** — Conversational research with database grounding
- **Agent Roster** — Monitor multi-agent swarm weights, accuracy, and graduation status
- **Heirloom Sync** — Cross-device knowledge persistence via encrypted weight snapshots
- **Real-time Alerts** — WebSocket-based alert subscriptions by entity/keyword/geofence
- **Offline Fallback** — Realm database caching for offline entity browsing

## Requirements

- iOS 14.0+
- Xcode 15.0+
- Swift 5.9+
- CocoaPods or Swift Package Manager

## Setup

### 1. Install Dependencies

```bash
cd apps/ios-app
pod install
```

### 2. Configure Build Settings

Copy the build configuration template and edit with your values:

```bash
cp Build.xcconfig Build.local.xcconfig
```

Edit `Build.local.xcconfig`:
```xcconfig
DEVELOPMENT_TEAM = ABC123DEFG
PROVISIONING_PROFILE_SPECIFIER = [your-provisioning-profile]
```

### 3. Environment Configuration

Create a `.env` file in the project root:

```bash
API_BASE_URL=http://localhost:8000
PYTHON_API_URL=http://localhost:8001
GATEWAY_URL=http://localhost:3000
MAPBOX_ACCESS_TOKEN=pk_test_xxxxx
OPENROUTER_API_KEY=sk-or-xxxxx
```

### 4. Open in Xcode

```bash
open AetherSovereignOS.xcworkspace
```

## Build & Run

### Development

```bash
# Build for device
xcodebuild -workspace AetherSovereignOS.xcworkspace \
  -scheme AetherSovereignOS \
  -configuration Debug \
  -destination generic/platform=iOS

# Run on simulator
xcrun simctl launch booted com.aethersovereign.map
```

### Production Release

```bash
# Create App Store archive
xcodebuild -workspace AetherSovereignOS.xcworkspace \
  -scheme AetherSovereignOS \
  -configuration Release \
  -sdk iphoneos \
  -archivePath ./build/AetherSovereignOS.xcarchive \
  archive

# Export for App Store
xcodebuild -exportArchive \
  -archivePath ./build/AetherSovereignOS.xcarchive \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath ./build/Release
```

## Key Files

| File | Purpose |
|------|---------|
| `App.swift` | Main SwiftUI entry point, tab navigation |
| `AuthenticationManager.swift` | JWT token handling, login/logout |
| `NetworkManager.swift` | REST API + WebSocket client |
| `LocationManager.swift` | GPS location + permissions |
| `Info.plist` | iOS app manifest (bundle ID, permissions, etc.) |
| `Entitlements.plist` | App capabilities (push notifications, keychain, etc.) |
| `Build.xcconfig` | Xcode build configuration |
| `Podfile` | CocoaPods dependencies |
| `app-store-metadata.yaml` | App Store listing data |

## Architecture

### MVVM + Reactive

The app uses SwiftUI (View), Combine (Publisher/Subscriber), and MVVM service layer:

```
SwiftUI View
    ↓
@ObservedObject Manager (ViewModel)
    ↓
NetworkManager / AuthenticationManager (Model)
    ↓
REST API / WebSocket
```

### Data Flow

1. **Authentication** → `AuthenticationManager` stores JWT in Keychain
2. **API Calls** → `NetworkManager` adds JWT to all requests
3. **Location** → `LocationManager` provides user coordinates for map
4. **Real-time** → WebSocket connections for alerts/research updates
5. **Cache** → Realm database for offline access

## Deployment

### App Store

1. **Prepare**
   - Bump version in `Info.plist` (`CFBundleShortVersionString`)
   - Create App Store Connect app record
   - Upload signing certificates

2. **Build**
   ```bash
   xcodebuild -workspace AetherSovereignOS.xcworkspace \
     -scheme AetherSovereignOS \
     -configuration Release \
     archive
   ```

3. **Submit**
   - Export archive to `.ipa`
   - Upload via Transporter or App Store Connect
   - Wait for app review (~24-48 hours)

### TestFlight Beta

```bash
# Upload for external testing
xcodebuild -exportArchive \
  -archivePath ./build/AetherSovereignOS.xcarchive \
  -exportOptionsPlist ExportOptions_TestFlight.plist \
  -exportPath ./build/TestFlight

# Then upload via App Store Connect
```

### Enterprise Distribution

For internal/MDM distribution (requires Apple Enterprise Developer Program):

```bash
xcodebuild -exportArchive \
  -archivePath ./build/AetherSovereignOS.xcarchive \
  -exportOptionsPlist ExportOptions_Enterprise.plist \
  -exportPath ./build/Enterprise
```

## Network Configuration

### API Endpoints

All requests route through JWT-authenticated API calls:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Check API health |
| `/search` | GET | Entity full-text search |
| `/entity/{id}` | GET | Fetch entity detail + relationships |
| `/research/{job_id}` | GET/POST | Research job creation + status |
| `/agents` | GET | Agent roster (swarm state) |
| `/swarm` | GET | Multi-agent consensus activity |
| `/chat` | POST | Conversational research interface |
| `/heirlooms` | GET/POST | Cross-device persistence |
| `/ws/alerts` | WS | Real-time alert subscriptions |

### Certificate Pinning

For production, enable certificate pinning in `NetworkManager`:

```swift
let trustManager = ServerTrustManager(
  evaluators: [
    "api.aethersovereign.app": PinnedCertificatesTrustEvaluator(),
  ]
)
```

## Permissions

The app requests these permissions (all optional, graceful degradation if denied):

| Permission | Usage | User Control |
|-----------|-------|--------------|
| Location (When In Use) | Center map, nearby entity search | iOS Settings → Aether OS → Location |
| Keychain | JWT token storage | Automatic (system-managed) |
| Network | API calls, WebSocket | Automatic |

The app declares but does **not** use:
- Camera
- Microphone
- Contacts
- Calendar
- Health

## Security

### Authentication

- JWT tokens stored in Keychain (encrypted by OS)
- Tokens never logged or transmitted insecurely
- Auto-logout on token expiration

### Data at Rest

- Entity search results cached in Realm (encrypted)
- Heirloom weights encrypted with AES-256-GCM
- No PII stored anywhere

### Data in Transit

- All HTTP/WebSocket connections use TLS 1.3+
- Certificate pinning enforced for production domains
- No hardcoded API keys (all from environment)

## Testing

### Unit Tests

```bash
xcodebuild -workspace AetherSovereignOS.xcworkspace \
  -scheme AetherSovereignOS \
  -configuration Debug \
  test
```

### UI Testing

```bash
xcodebuild -workspace AetherSovereignOS.xcworkspace \
  -scheme AetherSovereignOSUITests \
  -configuration Debug \
  test
```

### Manual Testing Checklist

- [ ] Login with JWT token
- [ ] Search for entity
- [ ] Zoom/pan map
- [ ] View entity detail with relationships
- [ ] Submit research job
- [ ] Monitor swarm consensus votes
- [ ] Open chat, ask question
- [ ] Check real-time alerts
- [ ] Export heirloom
- [ ] Logout

## Troubleshooting

### Build Errors

**"Could not locate the iPhone OS SDK"**
```bash
xcode-select --install
xcode-select --switch /Applications/Xcode.app/Contents/Developer
```

**"CocoaPods not found"**
```bash
sudo gem install cocoapods
pod repo update
```

### Runtime Issues

**"Cannot connect to API"**
- Check `API_BASE_URL` environment variable
- Verify backend is running (`docker compose up`)
- Confirm JWT token is valid

**"Location always shows nil"**
- Check Privacy → Location in Settings
- Verify `NSLocationWhenInUseUsageDescription` in Info.plist

**"WebSocket connection timeout"**
- Check network reachability
- Verify WebSocket proxy in nginx
- Confirm JWT is valid (refresh if needed)

## Monitoring

### Logging

Enable debug logging:

```swift
// In AppDelegate.swift
#if DEBUG
  os_log("Debug mode enabled", log: .default, type: .debug)
#endif
```

### Crashes

Firebase Crashlytics is integrated for production monitoring:
- Automatic crash reporting
- Custom analytics events
- Performance monitoring

View crashes in Xcode → Product → Scheme → Edit Scheme → Run → Arguments.

## Version History

| Version | Date | Notes |
|---------|------|-------|
| 1.0.0 | Jan 2026 | Initial App Store release |

## Support

- **Issues**: https://github.com/thetruezubzero-pixel/map/issues
- **Privacy**: https://github.com/thetruezubzero-pixel/map/blob/main/PRIVACY.md
- **Email**: support@aethersovereign.local

---

**Built with** SwiftUI • Combine • Mapbox GL • Alamofire • Realm • Firebase
