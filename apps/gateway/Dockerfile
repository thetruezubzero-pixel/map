FROM rust:1.90-slim AS builder
WORKDIR /app
# librdkafka-dev: rdkafka (Cargo.toml) links dynamically against the
# system librdkafka via pkg-config -- used by /health/streaming to
# report Kafka topic/partition metadata. build-essential (specifically a
# C++ compiler): rdkafka-sys's build.rs still runs its vendored
# ./configure probe even when the system lib is present, and that probe
# itself needs a C++ compiler or it fails outright (confirmed: without
# it, the build panics at rdkafka-sys's build.rs:36 on "c++: command not
# found", even with librdkafka-dev already installed above).
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config libssl-dev ca-certificates librdkafka-dev build-essential && rm -rf /var/lib/apt/lists/*
COPY Cargo.toml Cargo.lock* ./
COPY src ./src
COPY migrations ./migrations
RUN cargo build --release

# Must match the builder's Debian release (trixie) -- a binary built
# against trixie's glibc failed to run on bookworm-slim's older one
# ("version `GLIBC_2.38' not found"), confirmed live.
FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates librdkafka1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/target/release/aether-gateway /app/aether-gateway
COPY --from=builder /app/migrations /app/migrations
EXPOSE 8080
CMD ["/app/aether-gateway"]
