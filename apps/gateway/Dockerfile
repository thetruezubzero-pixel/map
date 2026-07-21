FROM rust:1.82-slim AS builder
WORKDIR /app
# librdkafka-dev: rdkafka (Cargo.toml) links dynamically against the
# system librdkafka via pkg-config -- used by /health/streaming to
# report Kafka topic/partition metadata.
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config libssl-dev ca-certificates librdkafka-dev && rm -rf /var/lib/apt/lists/*
COPY Cargo.toml Cargo.lock* ./
COPY src ./src
COPY migrations ./migrations
RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates librdkafka1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/target/release/aether-gateway /app/aether-gateway
COPY --from=builder /app/migrations /app/migrations
EXPOSE 8080
CMD ["/app/aether-gateway"]
