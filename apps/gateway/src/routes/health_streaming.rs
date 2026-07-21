use axum::{extract::State, Json};
use rdkafka::{
    consumer::{BaseConsumer, Consumer},
    ClientConfig,
};
use serde_json::{json, Value};
use std::time::Duration;

use crate::state::AppState;

const TOPICS: [&str; 7] = [
    "aether.property_changes",
    "aether.business_registrations",
    "aether.permit_issuances",
    "aether.news_mentions",
    "aether.entity_resolved",
    "aether.user_alerts",
    "aether.detected_patterns",
];

/// Per-topic partition count + total message count currently in the
/// topic (sum of high-watermark offsets). This is NOT per-consumer-group
/// lag -- that requires picking a specific consumer group's committed
/// offsets to compare against, and there's no single canonical group
/// across all the streaming components (ksqlDB, Flink, the Python
/// producers/dispatcher each use their own). What's reported here is a
/// real, honest proxy for "is data flowing through this topic at all",
/// not a false claim of full lag monitoring.
fn fetch_kafka_topic_stats(bootstrap_servers: &str) -> Result<Vec<Value>, String> {
    let consumer: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers)
        .set("group.id", "gateway-health-check")
        .create()
        .map_err(|e| e.to_string())?;

    let metadata = consumer
        .fetch_metadata(None, Duration::from_secs(5))
        .map_err(|e| e.to_string())?;

    let mut out = Vec::new();
    for topic_name in TOPICS {
        let topic_meta = metadata.topics().iter().find(|t| t.name() == topic_name);
        let Some(topic_meta) = topic_meta else {
            out.push(json!({"topic": topic_name, "found": false}));
            continue;
        };

        let mut total_messages: i64 = 0;
        for partition in topic_meta.partitions() {
            if let Ok((low, high)) =
                consumer.fetch_watermarks(topic_name, partition.id(), Duration::from_secs(5))
            {
                total_messages += high - low;
            }
        }

        out.push(json!({
            "topic": topic_name,
            "found": true,
            "partition_count": topic_meta.partitions().len(),
            "message_count": total_messages,
        }));
    }
    Ok(out)
}

async fn check_http(client: &reqwest::Client, url: &str) -> bool {
    client
        .get(url)
        .timeout(Duration::from_secs(3))
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false)
}

/// Reports the health of every Phase 4 streaming component this gateway
/// doesn't otherwise talk to on the request path: Kafka topic/partition
/// state, Flink job/checkpoint status (via its REST API), ksqlDB and
/// Schema Registry reachability. See CLAUDE.md -- python-api is not a
/// direct consumer of this data either; this is purely an operational
/// dashboard endpoint.
pub async fn health_streaming(State(state): State<AppState>) -> Json<Value> {
    let bootstrap = state.config.kafka_bootstrap_servers.clone();
    let kafka_topics = tokio::task::spawn_blocking(move || fetch_kafka_topic_stats(&bootstrap))
        .await
        .unwrap_or_else(|e| Err(e.to_string()));

    let ksqldb_ok = check_http(&state.http, &format!("{}/info", state.config.ksqldb_url)).await;
    let schema_registry_ok =
        check_http(&state.http, &format!("{}/subjects", state.config.schema_registry_url)).await;

    let flink_overview = state
        .http
        .get(format!("{}/jobs/overview", state.config.flink_rest_url))
        .timeout(Duration::from_secs(3))
        .send()
        .await
        .ok();
    let flink_jobs = match flink_overview {
        Some(resp) if resp.status().is_success() => resp.json::<Value>().await.ok(),
        _ => None,
    };

    let overall_ok = kafka_topics.is_ok() && ksqldb_ok && schema_registry_ok && flink_jobs.is_some();

    Json(json!({
        "status": if overall_ok { "ok" } else { "degraded" },
        "kafka": match kafka_topics {
            Ok(topics) => json!({ "reachable": true, "topics": topics }),
            Err(err) => json!({ "reachable": false, "error": err }),
        },
        "schema_registry": { "reachable": schema_registry_ok },
        "ksqldb": { "reachable": ksqldb_ok },
        "flink": match flink_jobs {
            Some(overview) => json!({ "reachable": true, "jobs": overview }),
            None => json!({ "reachable": false }),
        },
    }))
}
