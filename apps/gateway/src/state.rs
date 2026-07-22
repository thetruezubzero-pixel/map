use std::sync::Arc;
use std::time::Duration;

use governor::{
    clock::DefaultClock,
    state::keyed::DefaultKeyedStateStore,
    Quota, RateLimiter,
};
use nonzero_ext::nonzero;
use sqlx::PgPool;

use crate::config::Config;

pub type KeyedLimiter = RateLimiter<String, DefaultKeyedStateStore<String>, DefaultClock>;

#[derive(Clone)]
pub struct AppState {
    pub config: Arc<Config>,
    pub db: PgPool,
    pub http: reqwest::Client,
    pub ip_limiter: Arc<KeyedLimiter>,
    pub user_limiter: Arc<KeyedLimiter>,
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
