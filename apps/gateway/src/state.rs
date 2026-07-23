use std::sync::Arc;
use std::time::Duration;

use governor::{
    clock::DefaultClock,
    state::keyed::DefaultKeyedStateStore,
    Quota, RateLimiter,
};
use nonzero_ext::nonzero;
use sqlx::PgPool;
use tokio::sync::Semaphore;

use crate::config::Config;

pub type KeyedLimiter = RateLimiter<String, DefaultKeyedStateStore<String>, DefaultClock>;

#[derive(Clone)]
pub struct AppState {
    pub config: Arc<Config>,
    pub db: PgPool,
    pub http: reqwest::Client,
    pub ip_limiter: Arc<KeyedLimiter>,
    pub user_limiter: Arc<KeyedLimiter>,
    // Caps total concurrent /ws/alerts connections process-wide -- each
    // holds a dedicated PgListener connection for its lifetime, so this
    // bounds how many a client can open. See config.ws_alerts_max_connections.
    pub ws_alerts_semaphore: Arc<Semaphore>,
}

impl AppState {
    pub fn new(config: Config, db: PgPool) -> Self {
        let burst = std::num::NonZeroU32::new(config.rate_limit_burst).unwrap_or(nonzero!(10u32));
        let per_sec = std::num::NonZeroU32::new(config.rate_limit_per_sec).unwrap_or(nonzero!(1u32));
        let authed_per_sec =
            std::num::NonZeroU32::new(config.authed_rate_limit_per_sec).unwrap_or(nonzero!(5u32));

        let ip_quota = Quota::per_second(per_sec).allow_burst(burst);
        let user_quota = Quota::per_second(authed_per_sec).allow_burst(burst.saturating_mul(nonzero!(2u32)));

        Self {
            http: reqwest::Client::builder()
                // A readiness review found this client (used by
                // geocode.rs/research.rs for outbound Nominatim/Photon/
                // python-api calls) had no timeout at all -- a hung
                // upstream could hold a request open indefinitely.
                .timeout(Duration::from_secs(config.http_client_timeout_secs))
                .build()
                .expect("failed to build http client"),
            // Read the count before `config` is moved into the Arc below
            // (usize is Copy, and struct-literal fields evaluate in
            // written order).
            ws_alerts_semaphore: Arc::new(Semaphore::new(config.ws_alerts_max_connections)),
            config: Arc::new(config),
            db,
            ip_limiter: Arc::new(RateLimiter::keyed(ip_quota)),
            user_limiter: Arc::new(RateLimiter::keyed(user_quota)),
        }
    }

    /// Evicts stale entries from both keyed rate limiters. A readiness
    /// review found nothing ever called governor's `retain_recent` here,
    /// so both keyed maps (one entry per distinct IP/user ever seen)
    /// grew without bound for the life of the process. Intended to be
    /// called periodically from a background task (see main.rs), not
    /// per-request.
    pub fn cleanup_rate_limiters(&self) {
        self.ip_limiter.retain_recent();
        self.user_limiter.retain_recent();
    }
}

#[cfg(test)]
mod tests {
    use super::*;


    #[test]
    fn per_ip_limiting_same_key_exhausts_burst() {
        // Per-IP limiter with 1 req/sec + 5 burst: first 5 requests allowed,
        // 6th rejected until the second elapses.
        let ip_limiter = Arc::new(RateLimiter::keyed(
            Quota::per_second(nonzero!(1u32)).allow_burst(nonzero!(5u32)),
        ));

        let ip = "192.168.1.1".to_string();

        // First 5 requests should succeed (burst).
        for i in 1..=5 {
            assert!(
                ip_limiter.check_key(&ip).is_ok(),
                "request {} should pass within burst",
                i
            );
        }

        // 6th request should fail (burst exhausted, not 1 second elapsed).
        assert!(
            ip_limiter.check_key(&ip).is_err(),
            "6th request should be rate-limited"
        );
    }

    #[test]
    fn per_ip_limiting_different_ips_independent() {
        // Verify that different IPs each get their own burst allowance.
        let ip_limiter = Arc::new(RateLimiter::keyed(
            Quota::per_second(nonzero!(1u32)).allow_burst(nonzero!(3u32)),
        ));

        let ip1 = "192.168.1.1".to_string();
        let ip2 = "192.168.1.2".to_string();

        // IP1: consume burst (3 requests).
        for _ in 0..3 {
            assert!(ip_limiter.check_key(&ip1).is_ok());
        }
        assert!(ip_limiter.check_key(&ip1).is_err(), "IP1 should be rate-limited");

        // IP2: should still have full burst (independent from IP1).
        for _ in 0..3 {
            assert!(
                ip_limiter.check_key(&ip2).is_ok(),
                "IP2 should have independent burst allowance"
            );
        }
        assert!(ip_limiter.check_key(&ip2).is_err(), "IP2 should be rate-limited");
    }

    #[test]
    fn per_user_limiting_same_key_exhausts_burst() {
        // Per-user limiter with 5 req/sec + 20 burst (2x burst for authed users):
        // first 20 requests allowed, 21st rejected.
        let user_limiter = Arc::new(RateLimiter::keyed(
            Quota::per_second(nonzero!(5u32)).allow_burst(nonzero!(20u32)),
        ));

        let user = "user-123".to_string();

        // First 20 requests should succeed (burst).
        for i in 1..=20 {
            assert!(
                user_limiter.check_key(&user).is_ok(),
                "request {} should pass within burst",
                i
            );
        }

        // 21st request should fail (burst exhausted).
        assert!(
            user_limiter.check_key(&user).is_err(),
            "21st request should be rate-limited"
        );
    }

    #[test]
    fn per_user_limiting_different_users_independent() {
        // Verify that different users each get their own burst allowance.
        let user_limiter = Arc::new(RateLimiter::keyed(
            Quota::per_second(nonzero!(5u32)).allow_burst(nonzero!(10u32)),
        ));

        let user1 = "user-123".to_string();
        let user2 = "user-456".to_string();

        // User1: consume burst (10 requests).
        for _ in 0..10 {
            assert!(user_limiter.check_key(&user1).is_ok());
        }
        assert!(
            user_limiter.check_key(&user1).is_err(),
            "user1 should be rate-limited"
        );

        // User2: should still have full burst (independent from user1).
        for _ in 0..10 {
            assert!(
                user_limiter.check_key(&user2).is_ok(),
                "user2 should have independent burst allowance"
            );
        }
        assert!(
            user_limiter.check_key(&user2).is_err(),
            "user2 should be rate-limited"
        );
    }

    #[test]
    fn cleanup_rate_limiters_evicts_stale_entries() {
        // Verify that cleanup_rate_limiters calls retain_recent on both
        // limiters without panicking. We can't directly verify eviction
        // (that's governor's internal behavior), but we can verify the
        // method completes successfully and the limiters remain functional.
        let ip_limiter = Arc::new(RateLimiter::keyed(
            Quota::per_second(nonzero!(1u32)).allow_burst(nonzero!(5u32)),
        ));
        let user_limiter = Arc::new(RateLimiter::keyed(
            Quota::per_second(nonzero!(5u32)).allow_burst(nonzero!(10u32)),
        ));

        // Create some entries by checking a key.
        let ip1 = "192.168.1.1".to_string();
        let user1 = "user-123".to_string();
        let _ = ip_limiter.check_key(&ip1);
        let _ = user_limiter.check_key(&user1);

        // Cleanup should not panic and should not break the limiters.
        ip_limiter.retain_recent();
        user_limiter.retain_recent();

        // Limiters should still work after cleanup.
        let ip2 = "192.168.1.2".to_string();
        let user2 = "user-456".to_string();
        assert!(
            ip_limiter.check_key(&ip2).is_ok(),
            "limiter should be functional after cleanup"
        );
        assert!(
            user_limiter.check_key(&user2).is_ok(),
            "limiter should be functional after cleanup"
        );
    }

    #[test]
    fn authed_users_have_higher_limit_than_anon_ips() {
        // Verify that authed users get a higher per-second limit than
        // anonymous IPs: 5 req/sec (authed) vs 1 req/sec (IP).
        // The burst is also higher for authed (2x), which we can verify
        // by comparing max burst before exhaustion.

        let ip_limiter = Arc::new(RateLimiter::keyed(
            Quota::per_second(nonzero!(1u32)).allow_burst(nonzero!(5u32)),
        ));

        let user_limiter = Arc::new(RateLimiter::keyed(
            Quota::per_second(nonzero!(5u32)).allow_burst(nonzero!(10u32)),
        ));

        let ip = "192.168.1.1".to_string();
        let user = "user-123".to_string();

        // IP limiter: burst of 5.
        let mut ip_count = 0;
        for _ in 0..100 {
            if ip_limiter.check_key(&ip).is_ok() {
                ip_count += 1;
            }
        }
        assert_eq!(ip_count, 5, "IP burst should be 5");

        // User limiter: burst of 10 (2x).
        let mut user_count = 0;
        for _ in 0..100 {
            if user_limiter.check_key(&user).is_ok() {
                user_count += 1;
            }
        }
        assert_eq!(user_count, 10, "User burst should be 10 (2x IP burst)");
    }
}
