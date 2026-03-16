# Cloud Deployment Guide — Scalable to 10,000+ Users

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    INTERNET (Users)                         │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
         ┌───────────────────────────────┐
         │   Your Custom Domain (HTTPS)  │
         │    api.yourdomain.com         │
         │     (DNS A record)            │
         └───────────┬───────────────────┘
                     │
         ┌───────────▼───────────┐
         │  AWS ALB / LB         │
         │  (auto-scale)         │
         └───────────┬───────────┘
                     │
      ┌──────────────┼──────────────┐
      │              │              │
      ▼              ▼              ▼
   ┌─────────┐ ┌─────────┐ ┌─────────┐
   │ Gateway │ │ Payment │ │ Gateway │  (ECS/K8s)
   │ :8000   │ │ :5000   │ │ :8000   │  (Auto-scaling)
   └────┬────┘ └────┬────┘ └────┬────┘
        │           │           │
        └───────────┼───────────┘
                    │
      ┌─────────────┼─────────────┐
      │             │             │
      ▼             ▼             ▼
   Workers      Database    Message Broker
   (Celery)     (RDS)        (Redis Cloud)
   (ECS)        (PostgreSQL)  (Upstash)
   (Scaled)     (HA)          (HA)
      │
      ▼
   Media Storage
   (S3 + CloudFront)
```

---

## Step 1: Choose Cloud Provider

### Option A: **AWS** (Most scalable)
- ALB (Application Load Balancer)
- ECS Fargate (serverless containers)
- RDS PostgreSQL (managed database)
- ElastiCache or Redis Cloud
- S3 + CloudFront (media CDN)
- **Cost**: $200-500/month for 1000 users

### Option B: **Railway** (Easiest, medium scale)
- Push Docker Compose → auto-deploys
- Managed PostgreSQL
- Managed Redis
- Built-in domains
- Auto-scaling available
- **Cost**: $50-200/month

### Option C: **DigitalOcean App Platform** (Good balance)
- Simple deployment
- Managed databases
- Kubernetes available
- **Cost**: $100-300/month

### Option D: **GCP Cloud Run** (Serverless)
- Pay-per-request billing
- Auto-scaling built-in
- Firestore or Cloud SQL
- **Cost**: Variable, $30-200/month

**Recommendation for you**: Start with **Railway** or **DigitalOcean**, graduate to **AWS** at 5000+ users.

---

## Step 2: Use Railway (Simplest Path)

### 2.1 Create Railway Project

1. Go to https://railway.app/
2. Sign up → Create new project
3. Connect GitHub: select `multi_platform_automation`

### 2.2 Deploy via Docker Compose

1. Create `Dockerfile.payment` to separate payment service:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "payments.server:app", "--host", "0.0.0.0", "--port", "5000"]
```

2. Railway will auto-detect `docker-compose.yml` and deploy all services

### 2.3 Configure Environment

In Railway dashboard:
- Add PostgreSQL plugin (auto-creates DATABASE_URL)
- Add Redis plugin (auto-creates REDIS_URL)
- Add env vars from `.env.production`:

```
WHATSAPP_TOKEN=...
STRIPE_SECRET_KEY=sk_live_...
ANTHROPIC_API_KEY=...
etc.
```

### 2.4 Get Production Domain

Railway gives you: `api-prod-xyz.railway.app`

Update your `.env.production`:
```
PUBLIC_BASE_URL=https://api-prod-xyz.railway.app
PAYMENT_SERVER_URL=https://api-prod-xyz.railway.app
OAUTH_REDIRECT_URI=https://api-prod-xyz.railway.app/auth/callback
```

---

## Step 3: Custom Domain + DNS

### 3.1 Buy a Domain

- GoDaddy, Namecheap, Route53, Cloudflare
- Example: `catalyx-bot.com`

### 3.2 Update DNS

If using Railway:
- Go to Railway → Custom domain
- Add `api.catalyx-bot.com`
- Railway gives you a CNAME target
- Update DNS provider:
  ```
  api.catalyx-bot.com CNAME api-prod-xyz.railway.app
  ```

Railway auto-provides HTTPS via Let's Encrypt ✅

### 3.3 Update All URLs

Update `.env.production`:
```
PUBLIC_BASE_URL=https://api.catalyx-bot.com
PAYMENT_SERVER_URL=https://api.catalyx-bot.com
OAUTH_REDIRECT_URI=https://api.catalyx-bot.com/auth/callback
WHATSAPP_WEBHOOK_URL=https://api.catalyx-bot.com/webhook
```

Update Meta dashboards:
- WhatsApp webhook: `https://api.catalyx-bot.com/webhook`
- Facebook OAuth: `https://api.catalyx-bot.com/auth/callback`

Update Stripe dashboard:
- Webhook endpoint: `https://api.catalyx-bot.com/stripe/webhook`

---

## Step 4: Scale for 1000-10000 Users

### 4.1 Database Scaling (PostgreSQL)

**Current**: Local PostgreSQL container (not scalable)

**Production**: Managed RDS

```
RDS PostgreSQL 15 (db.t3.small)
  - 2 vCPU, 2 GB RAM
  - 100 GB storage (auto-scale)
  - Multi-AZ (HA)
  - Automated backups
  - Cost: $30-50/month

Handles: 1000-5000 concurrent users
```

Connection pooling (PgBouncer in Railway or built-in):
```
DATABASE_URL=postgresql://user:pass@rds-instance.aws.com:5432/bot?sslmode=require
```

### 4.2 Message Broker Scaling (Redis)

**Current**: Local Redis container

**Production**: Redis Cloud (Upstash)

```
Upstash Redis (Free tier to Start)
  - 10 GB storage
  - Automatic failover
  - Global CDN
  - Cost: $0-50/month

Handles: 10000+ workers
```

Update:
```
REDIS_URL=rediss://default:token@redis-cloud.upstash.io:6379
```

### 4.3 Application Scaling (Containers)

**Current**: 1 gateway + 1 payment + 3 workers

**Production**: Auto-scaling deployment

Railway auto-scales, but for AWS/K8s:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: gateway-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gateway
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

This means:
- Minimum 3 gateway replicas always running
- Scales up to 20 when CPU > 70%
- Cost increases with traffic

### 4.4 Media Storage Scaling (S3 + CloudFront)

**Current**: Local filesystem (lost on container restart)

**Production**: S3 + CDN

```python
# In gateway/media.py

import boto3
from botocore.config import Config

s3 = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name='us-east-1',
    config=Config(signature_version='s3v4')
)

async def upload_media(file_path: str) -> str:
    """Upload to S3 and return CloudFront URL"""
    key = f"media/{uuid.uuid4()}.jpg"
    s3.upload_file(file_path, 'catalyx-media', key)
    return f"https://media.catalyx-bot.com/{key}"
```

Cost: $0.023 per GB (S3) + $0.085 per GB (CloudFront)
- 1000 users × 10 media/month × 5 MB = 50 GB/month = ~$5

### 4.5 Load Balancer

For Railway: Built-in ✅

For AWS:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: gateway-lb
spec:
  type: LoadBalancer
  ports:
  - port: 443
    targetPort: 8000
    protocol: TCP
  selector:
    app: gateway
```

---

## Step 5: Monitoring & Alerts

### 5.1 Logging (CloudWatch / Railway)

Railway dashboard shows logs automatically.

For AWS CloudWatch:
```python
import watchtower
import logging

logging.basicConfig(
    handlers=[watchtower.CloudWatchLogHandler()],
    level=logging.INFO
)
```

### 5.2 Metrics

Monitor:
- Container CPU/Memory
- Database connection pool
- API response times
- Worker queue depth
- Stripe webhook success rate

### 5.3 Alerts

Set up alerts for:
- Gateway error rate > 5%
- Payment webhook failures
- Database CPU > 80%
- Redis memory > 90%

---

## Step 6: Cost Estimation for 1000-10000 Users

| Component | Tier 1 (1K) | Tier 2 (5K) | Tier 3 (10K) |
|-----------|-----------|-----------|------------|
| **Hosting** (Railway/K8s) | $50-100 | $200-300 | $500-1000 |
| **Database** (RDS) | $30 | $50 | $100+ |
| **Redis** (Cloud) | $0-30 | $30-50 | $50-100 |
| **Media** (S3+CDN) | $5-20 | $20-50 | $50-200 |
| **Domain** | $10/yr | $10/yr | $10/yr |
| **Monitoring** | $0-50 | $50-100 | $100-200 |
| **Total/month** | **$95-230** | **$350-550** | **$800-1610** |

---

## Step 7: Deployment Script

Create `deploy.sh` for one-click deployment:

```bash
#!/bin/bash

echo "🚀 Deploying to production..."

# 1. Build images
docker build -t catalyx-bot-gateway:latest .
docker build -t catalyx-bot-payment:latest -f Dockerfile.payment .

# 2. Push to registry (ECR/Docker Hub)
docker tag catalyx-bot-gateway:latest myregistry/catalyx-gateway:latest
docker push myregistry/catalyx-gateway:latest

# 3. Deploy to Railway/ECS/K8s
railway up --detach

# 4. Run migrations
docker exec catalyx-db psql -U postgres -d multi_platform_bot < migrations/schema.sql

# 5. Verify health
curl https://api.catalyx-bot.com/health/gateway
curl https://api.catalyx-bot.com/health/payment

echo "✅ Deployment complete!"
```

---

## Step 8: Zero-Downtime Updates

### Blue-Green Deployment

```
Version A (Current)     Version B (New)
    ↓                       ↓
  50% traffic           50% traffic  (gradual rollout)

If B fails:
    ↓
  100% → A (rollback)
```

Most cloud platforms support this natively.

---

## Step 9: Backup & Disaster Recovery

### Database Backups

AWS RDS:
- Automated backups: 7 days
- Manual snapshots: on-demand
- Copy to another region: disaster recovery

### Media Backups

S3:
- Versioning enabled
- Cross-region replication
- Lifecycle policies: old files → Glacier

---

## Migration Checklist

- [ ] Choose cloud provider (Railway recommended)
- [ ] Create account + project
- [ ] Connect GitHub repo
- [ ] Provision PostgreSQL (auto)
- [ ] Provision Redis (auto or Redis Cloud)
- [ ] Add environment variables
- [ ] Update DNS (custom domain)
- [ ] Test all webhooks (WhatsApp, Stripe, Facebook)
- [ ] Enable database backups
- [ ] Set up monitoring/alerts
- [ ] Configure S3 + CloudFront for media
- [ ] Load test (1000 concurrent users)
- [ ] Monitor costs

---

## Cost Optimization

1. **Use auto-scaling**: Only pay for what you use
2. **Reserved instances**: 30% discount for committed capacity
3. **Spot instances**: 70% discount, but interruptible
4. **Multi-region**: Distribute traffic, reduce latency
5. **CDN caching**: 80% of requests cached

---

## Next Steps

1. **Immediate**: Deploy to Railway (takes 15 minutes)
2. **Week 1**: Set up custom domain
3. **Week 2**: Migrate media to S3
4. **Week 3**: Load testing
5. **Week 4**: Scale for production traffic

Want me to create Railway deployment files?
