use std::sync::Arc;

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
            config: Arc::new(config),
            db,
            http: reqwest::Client::builder()
                .build()
                .expect("failed to build http client"),
            ip_limiter: Arc::new(RateLimiter::keyed(ip_quota)),
            user_limiter: Arc::new(RateLimiter::keyed(user_quota)),
        }
    }
}
