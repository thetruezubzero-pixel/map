# Production Deployment Guide

Aether Sovereign OS is a containerized, stateless application with persistent layers (Postgres, Redis, Qdrant, Elasticsearch).

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Load Balancer (nginx/ALB)                 │
└─────────────────────────────────────────────────────────────┘
            │
      ┌─────┴─────┐
      │           │
  ┌───▼───┐  ┌───▼───┐
  │Gateway│  │Gateway│  (scale horizontally)
  └───┬───┘  └───┬───┘
      │           │
      └─────┬─────┘
            │
      ┌─────▼─────────────────────┐
      │   Shared Services Layer   │
      │ ├─ Postgres (PostGIS)     │
      │ ├─ Redis (RediSearch)     │
      │ ├─ Qdrant (vector DB)     │
      │ ├─ Elasticsearch          │
      │ ├─ Kafka (streaming)      │
      │ ├─ Schema Registry        │
      │ ├─ ksqlDB (streaming)     │
      │ └─ Flink (CEP)           │
      └─────┬─────────────────────┘
            │
      ┌─────┴──────┬──────────┐
      │            │          │
   ┌──▼───┐  ┌──▼──┐  ┌──▼──┐
   │ Web  │  │Python│  │Alert│
   │Nginx │  │  API │  │Disp.│
   └──────┘  └──────┘  └─────┘
```

## Quick Start (5 minutes)

### Local development with Docker Compose

```bash
# 1. Copy the environment template
cp .env.example .env

# 2. Set required values
export JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export NOMINATIM_USER_AGENT="YourApp/1.0 (contact: you@example.com)"
export HEIRLOOM_DEVICE_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Update .env with your values
sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$JWT_SECRET/" .env

# 3. Start everything
docker compose up

# 4. Open http://localhost:5173 in your browser
```

## Production Deployment Patterns

### Pattern 1: Docker Swarm (simplest)

```bash
# 1. Initialize swarm
docker swarm init

# 2. Create named volumes (persistent)
docker volume create postgres_data
docker volume create redis_data
docker volume create qdrant_data
docker volume create es_data
docker volume create kafka_data

# 3. Deploy with compose
docker stack deploy -c docker-compose.yml aether

# 4. Monitor
docker service ls
docker service logs aether_gateway
```

### Pattern 2: Kubernetes (recommended for scale)

1. **Install prerequisites**: kubectl, helm, kube-prometheus, ArgoCD (optional)

2. **Create ConfigMap/Secrets**:
```yaml
# Create namespace
kubectl create namespace aether

# Create secrets
kubectl create secret generic aether-secrets \
  --from-literal=JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  --from-literal=GITHUB_TOKEN=... \
  -n aether

# Create configmap for non-secret env vars
kubectl create configmap aether-config \
  --from-literal=NOMINATIM_USER_AGENT="YourApp/1.0 (contact: you@example.com)" \
  -n aether
```

3. **Deploy persistent storage**:
```bash
# PostgreSQL with Helm
helm repo add bitnami https://charts.bitnami.com/bitnami
helm install postgres bitnami/postgresql \
  --set global.postgresql.auth.password=<password> \
  -n aether

# Redis
helm install redis bitnami/redis -n aether

# Qdrant
helm install qdrant qdrant/qdrant -n aether
```

4. **Deploy application services**:
```yaml
# gateway-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gateway
  namespace: aether
spec:
  replicas: 3
  selector:
    matchLabels:
      app: gateway
  template:
    metadata:
      labels:
        app: gateway
    spec:
      containers:
      - name: gateway
        image: your-registry/aether-gateway:latest
        ports:
        - containerPort: 8080
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: aether-secrets
              key: DATABASE_URL
        - name: JWT_SECRET
          valueFrom:
            secretKeyRef:
              name: aether-secrets
              key: JWT_SECRET
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
```

5. **Expose via Ingress**:
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: aether
  namespace: aether
spec:
  rules:
  - host: yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: gateway
            port:
              number: 8080
```

### Pattern 3: Cloud-Native (AWS/GCP/Azure)

**AWS ECS Fargate:**
- **Compute**: ECS Fargate (no instance management)
- **Database**: RDS PostgreSQL (managed)
- **Cache**: ElastiCache (managed Redis)
- **Vector DB**: Self-hosted Qdrant on EC2 or use external vector service
- **Streaming**: Managed Kafka (AWS MSK) or self-hosted Kafka
- **Load Balancing**: Application Load Balancer (ALB)
- **DNS**: Route 53
- **CDN**: CloudFront (for static assets from `apps/web/dist`)

**GCP Cloud Run:**
- **Compute**: Cloud Run (serverless, auto-scaling)
- **Database**: Cloud SQL (managed PostgreSQL)
- **Cache**: Memorystore (managed Redis)
- **Load Balancing**: Cloud Load Balancing
- **Streaming**: Self-hosted Kafka (Compute Engine) or Pub/Sub

## Service Configuration

### Gateway (`apps/gateway`)

**Scaling**: Stateless — scale horizontally with load balancer
**Resource requirements**:
- Memory: 128-256 MB per instance
- CPU: 100-200m per instance
- Instances: 2-10 (depends on request volume)

**Key environment variables**:
- `JWT_SECRET` — token signing key (must match python-api)
- `DATABASE_URL` — postgres connection string
- `PYTHON_API_BASE_URL` — internal URL to python-api
- `ALLOWED_ORIGINS` — CORS whitelist
- `NOMINATIM_BASE_URL` — geocoding service (external)

**Health check**: `GET /health` → 200 JSON

### Python API (`apps/api/python`)

**Scaling**: Stateless (but single-worker default — see note below)
**Resource requirements**:
- Memory: 512 MB - 1 GB per instance
- CPU: 250-500m per instance

**⚠️ Architectural note**: Currently runs as a single uvicorn worker (no `--workers` flag in Dockerfile). This is intentional per CLAUDE.md ("no hardcoded secrets"): the `python-api` service is only reachable from `gateway` and `web`'s nginx, never exposed directly to untrusted input. Scaling to multiple workers requires:
1. A shared session store (Redis-backed sessions, not in-memory)
2. Coordination layer for the Architect's `GIT_WORKING_TREE_LOCK` (currently `asyncio.Lock`, which doesn't work across processes)

Both are feasible; the current single-worker choice keeps the codebase simpler for now.

**Key environment variables**:
- `JWT_SECRET` — token verification (must match gateway)
- `DATABASE_URL` — postgres connection string
- `OPENROUTER_API_KEY` — optional, for AI features
- `GITHUB_TOKEN` — optional, for Architect git commits
- `AGENT_SWARM_ENABLED` — set to true/false

**Health check**: `GET /health` → 200 JSON

### Frontend (`apps/web`)

**Deployment**: Static files (SPA) — use a CDN/object storage
**Build**: `npm run build` produces `dist/` directory
**Server**: nginx or any static file server
**Resource requirements**: Negligible (static serving)

**Nginx configuration**:
- Route `/api/` to gateway (already in `apps/web/nginx.conf`)
- Route `/py-api/` to python-api (already configured)
- Cache-bust `index.html`, long-lived cache for `/assets/`

### Kafka & Streaming Layer

**Required for**: 
- SEC EDGAR/NewsAPI ingestion (data pipelines)
- Real-time CEP alerts (Flink)
- Alert dispatcher (Postgres LISTEN → Kafka)

**Can be disabled if**: You only need the map + entity search (no research pipeline)

**Typical resources**:
- Kafka: 3 brokers (HA), 2-4 GB RAM each
- Schema Registry: 1-2 instances, 512 MB RAM each
- ksqlDB: 1 instance, 1-2 GB RAM
- Flink: 1 JobManager + N TaskManagers (depends on data volume)

## Database Setup

### Migrations

Postgres migrations live in `apps/api/python/migrations/`. Run them once at deployment:

```bash
# Via python-api container
docker exec aether-python-api python -m alembic upgrade head

# Or via psql directly
psql $DATABASE_URL -f migrations/001_initial_schema.sql
```

### Backup & Recovery

**Automated backups** (recommended):
```bash
# Daily backup to S3
docker exec aether-postgres pg_dump -U aether aether | \
  gzip > backup-$(date +%Y%m%d).sql.gz && \
  aws s3 cp backup-*.sql.gz s3://your-bucket/backups/

# Restore
aws s3 cp s3://your-bucket/backups/backup-20260723.sql.gz - | \
  gunzip | psql $DATABASE_URL
```

**Point-in-time recovery**:
Postgres WAL archival (requires object storage):
```sql
-- In postgresql.conf
wal_level = replica
archive_mode = on
archive_command = 'aws s3 cp %p s3://your-bucket/wal/%f'
restore_command = 'aws s3 cp s3://your-bucket/wal/%f %p'
```

### PostGIS Extension

Required for geospatial queries. Included in `postgis/postgis` Docker image.

**Verify it's installed**:
```bash
psql $DATABASE_URL -c "SELECT postgis_version();"
```

## Monitoring & Observability

### Key metrics to track

1. **Gateway**:
   - Request latency (p50, p95, p99)
   - Error rate (4xx, 5xx)
   - Active WebSocket connections (`/ws/alerts`)
   - Rate limiter hit rate

2. **Python API**:
   - Research job success/failure rate
   - OpenRouter API call latency
   - Database connection pool utilization
   - Background task queue size

3. **Database**:
   - Connection pool utilization
   - Query latency (especially geo queries)
   - Replication lag (if replicated)
   - Disk space

4. **Kafka**:
   - Consumer lag (data pipelines)
   - Message throughput
   - Partition balance

### Monitoring stack suggestion

```yaml
# docker-compose.yml additions
prometheus:
  image: prom/prometheus
  volumes:
    - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
  ports:
    - "9090:9090"

grafana:
  image: grafana/grafana
  ports:
    - "3000:3000"
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=changeme

# Scrape targets:
# - gateway:8080/metrics (Rust axum metrics via middleware)
# - python-api:8000/metrics (FastAPI prometheus_client)
# - postgres_exporter:9187 (database metrics)
# - kafka_exporter:9308 (Kafka metrics)
```

### Alerting

Key alerts to set up:

1. **High error rate**: Gateway 5xx errors > 1% for 5m
2. **High latency**: p99 latency > 5s for 10m
3. **Database**: Connection pool > 80% utilized
4. **Kafka consumer lag**: Research pipeline lag > 1 hour
5. **Disk space**: < 10% free on postgres volume

## Security Checklist

- [ ] `JWT_SECRET` is a real, random, 64-char hex string (not the placeholder)
- [ ] `NOMINATIM_USER_AGENT` contains a real email (not a placeholder domain)
- [ ] All services run behind a load balancer (no direct service exposure)
- [ ] HTTPS/TLS enabled on external endpoints (gateway, CDN)
- [ ] Database credentials stored in secrets manager (not in docker-compose)
- [ ] `GITHUB_TOKEN` (if used) is a fine-grained PAT, scoped to this repo only
- [ ] Postgres backups are encrypted and stored off-site
- [ ] WAL archival enabled for point-in-time recovery
- [ ] Network policies restrict service-to-service communication
- [ ] Secrets are rotated every 90 days (JWT_SECRET, GITHUB_TOKEN, etc.)

## Disaster Recovery

**RTO** (Recovery Time Objective): 15-30 minutes
**RPO** (Recovery Point Objective): Last automated backup (daily) or latest WAL archive (~5 min)

**Recovery procedure**:
1. Restore Postgres from latest backup
2. Replay WAL archives if point-in-time recovery is needed
3. Re-seed Redis cache (ephemeral, can be lost)
4. Redeploy application containers
5. Verify `/health` endpoints respond

**Test quarterly**: Restore a backup to a staging environment and verify end-to-end functionality.

## Troubleshooting

### Gateway can't reach Python API

**Symptom**: `POST /research` returns 503 or timeout

```bash
# From gateway container
curl http://python-api:8000/health
# Should return 200

# Check docker network
docker network inspect aether-sovereign-os_default
# Verify python-api container is connected
```

### Postgres connection pool exhausted

**Symptom**: Errors like "all connection attempts failed"

```bash
# Check active connections
psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity;"

# Check python-api logs for leaks
docker logs aether-python-api | grep "PgPool\|connection"

# Restart python-api to reset pool
docker restart aether-python-api
```

### Kafka producer failing silently

**Symptom**: Data pipelines run but no records reach Kafka

```bash
# Check schema registry
curl http://schema-registry:8082/subjects
# Should list aether-* schemas

# Check Kafka topic
docker exec aether-kafka kafka-topics.sh --list --bootstrap-server localhost:9092
```

## Next Steps

- Set up monitoring (Prometheus + Grafana)
- Configure automated backups to object storage
- Test failover and recovery procedures
- Scale gateway/python-api based on load metrics
- Set up a staging environment that mirrors production

## References

- `docker-compose.yml` — full local dev stack
- `CLAUDE.md` — architecture overview
- `CODESPACES.md` — remote development setup
- `ROADMAP.md` — feature phases and planned work
