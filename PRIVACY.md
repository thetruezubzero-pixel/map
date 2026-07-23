# Privacy Policy

**Last Updated:** January 2026  
**Effective Date:** January 2026

## Overview

Aether Sovereign OS ("the App") is a public records research platform designed for due diligence, journalism, and urban planning. This Privacy Policy explains how we collect, use, and protect your information when you use the App.

## What We Collect

### Information We DO Collect

1. **Authentication Data**
   - JWT tokens for API authentication (stored locally on your device only)
   - No username or password storage — authentication is token-based and stateless

2. **Location Data**
   - Your device's GPS location is used ONLY to center the map and search for nearby entities
   - Location is **never** stored, tracked, or transmitted beyond the map viewport
   - You control location permissions in iOS Settings; the App respects your choices

3. **Search Queries**
   - Your searches and entity lookups are sent to our API to retrieve results
   - Query text is logged on our server for rate-limiting and abuse prevention only
   - Logs are retained for 30 days and then automatically deleted

4. **API Usage Analytics**
   - We log which endpoints you use (search, entity detail, graph queries, etc.)
   - Usage logs help us understand which features are valuable and optimize performance
   - Individual user activity is not tracked; we aggregate patterns only

### Information We DO NOT Collect

- ❌ **No personal data about individuals** — this App only searches public records of businesses, properties, and locations
- ❌ **No device tracking** — we don't collect your IDFA, device ID, or any persistent identifier
- ❌ **No behavioral tracking** — no cookies, no cross-app tracking, no ad networks
- ❌ **No camera/microphone access** — the App declares these as "Not used"
- ❌ **No contact, calendar, or health data** — no access to private user data of any kind
- ❌ **No personal identity information** — entity searches return company names, locations, SEC filings, news mentions, never individual people

## Data Sources and Licensing

All data displayed in Aether Sovereign OS comes from public, licensed sources:

| Source | License | Type |
|--------|---------|------|
| OpenStreetMap | ODbL | Businesses, properties, locations |
| SEC EDGAR | Public Domain | Corporate filings, officer names (company context only) |
| OpenCorporates | CC-BY | Company registrations worldwide |
| NewsAPI / GDELT | CC-BY-NC | News mentions and events |
| Census TIGER | Public Domain | Geographic boundaries |
| USGS | Public Domain | Geographic data |
| FCC License Records | Public Domain | Broadcast licenses |
| Zoning & Property Boundaries | Various | Public records |

Every entity record in the App includes its source, license, and retrieval date for full transparency.

## How We Use Your Data

1. **To provide search results** — answering your queries against our public-records database
2. **To sync multi-agent research** — tracking consensus votes from our AI research pipeline (stored in Postgres)
3. **To surface alerts** — notifying you of changes to entities you're monitoring via WebSocket subscriptions
4. **To improve the App** — analyzing aggregated usage patterns (no individual user tracking)
5. **To prevent abuse** — rate-limiting based on API usage (IP address and JWT token)

## How We Protect Your Data

- **In Transit:** All API calls use HTTPS/TLS encryption
- **At Rest:** Your JWT token is stored locally on your device only; we never store passwords
- **Database:** Sensitive data is encrypted using AES-256-GCM (for heirlooms, agent weights)
- **Access Control:** Only authenticated API calls can reach user-specific data
- **Audit Logging:** All agent actions are logged to an append-only audit trail (immutable after insertion)

## Your Data Rights

### Access
- You can export your own research jobs, saved heirlooms, and agent training data at any time via the App's export features

### Deletion
- You can delete your own heirlooms and custom agents from the Heirlooms and Agents pages
- To request complete account deletion, contact support@aethersovereign.local

### Portability
- All your exported data (heirlooms, research reports, agent configs) is in plain JSON and can be imported on another device

### Opt-Out
- You can disable location access in iOS Settings → Aether Sovereign OS → Location
- You can disable App analytics in iOS Settings (via Apple's App Analytics toggle)

## Cookies and Tracking

We do **not** use cookies, web beacons, or any form of persistent cross-session tracking. Each session is stateless and authenticated via JWT only.

## Third-Party Services

### OpenRouter (LLM API)
- Aether Sovereign OS queries external LLM models via OpenRouter (claude, GPT-4, etc.)
- Your search queries may be sent to OpenRouter's infrastructure to power AI-assisted research
- [OpenRouter Privacy Policy](https://openrouter.ai/privacy)
- All queries to OpenRouter are anonymous (no user ID attached)

### Mapbox (Maps)
- The App uses Mapbox GL for map rendering
- [Mapbox Privacy Policy](https://www.mapbox.com/legal/privacy)
- Mapbox receives your viewport center and zoom level to render tiles

### NewsAPI / GDELT (Public Data Feeds)
- We ingest news data from NewsAPI and GDELT for entity-related news mentions
- No personal queries are sent to these services; we only ingest their public data feeds

## Children's Privacy

Aether Sovereign OS is not intended for children under 13. We do not knowingly collect data from children. If you are under 13, please do not use this App.

## Changes to This Privacy Policy

We may update this Privacy Policy to reflect changes in our practices or applicable law. We will notify you of material changes by updating the "Last Updated" date at the top of this page. Your continued use of the App after such changes constitutes your acceptance of the updated Privacy Policy.

## Contact Us

If you have questions about this Privacy Policy or our privacy practices, please contact:

**Aether Sovereign OS Support**  
📧 support@aethersovereign.local  
🔗 https://github.com/thetruezubzero-pixel/map/issues  
📝 GitHub Issues: Report privacy concerns or request data access

---

## Summary: What Makes Aether Sovereign OS Different

| Aspect | Aether OS | Typical SaaS App |
|--------|-----------|-----------------|
| Personal data collection | ❌ None | ✓ Extensive |
| Device tracking | ❌ No | ✓ Yes |
| Behavioral profiling | ❌ No | ✓ Yes |
| Cross-app tracking | ❌ No | ✓ Yes |
| Data sale to third parties | ❌ No | ✓ Often |
| Location persistence | ❌ No (ephemeral) | ✓ Yes |
| End-to-end encryption | ✓ Per-session | ~ Partial |
| Audit trail visibility | ✓ Full transparency | ~ Limited |

**This App researches PUBLIC records only.** There is no surveillance, no dossier-building, no individual tracking.
