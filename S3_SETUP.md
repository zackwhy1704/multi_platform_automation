# AWS S3 Media Storage Setup

For production: Move media from local filesystem to S3 + CloudFront CDN.

## Step 1: Create S3 Bucket

```bash
aws s3 mb s3://catalyx-bot-media --region us-east-1

# Enable versioning
aws s3api put-bucket-versioning \
  --bucket catalyx-bot-media \
  --versioning-configuration Status=Enabled

# Enable encryption
aws s3api put-bucket-encryption \
  --bucket catalyx-bot-media \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'

# Block public access (we'll use CloudFront)
aws s3api put-public-access-block \
  --bucket catalyx-bot-media \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

## Step 2: Create IAM User for App

```bash
# Create user
aws iam create-user --user-name catalyx-bot-app

# Create access key
aws iam create-access-key --user-name catalyx-bot-app

# Save the Access Key ID and Secret Access Key

# Attach policy (S3 only)
aws iam put-user-policy --user-name catalyx-bot-app \
  --policy-name S3MediaUpload \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::catalyx-bot-media/*"
    }]
  }'
```

## Step 3: Create CloudFront Distribution

```bash
# Create origin access identity
aws cloudfront create-cloud-front-origin-access-identity \
  --cloud-front-origin-access-identity-config \
  CallerReference=catalyx-$(date +%s),Comment="Catalyx Bot Media"

# Note the OAI ID returned

# Create distribution config
cat > cf-config.json << 'EOF'
{
  "CallerReference": "catalyx-$(date +%s)",
  "Comment": "Catalyx Bot Media CDN",
  "DefaultRootObject": "",
  "Origins": {
    "Quantity": 1,
    "Items": [
      {
        "Id": "myS3Origin",
        "DomainName": "catalyx-bot-media.s3.amazonaws.com",
        "S3OriginConfig": {
          "OriginAccessIdentity": "origin-access-identity/cloudfront/YOUR_OAI_ID"
        }
      }
    ]
  },
  "DefaultCacheBehavior": {
    "AllowedMethods": {
      "Quantity": 2,
      "Items": ["GET", "HEAD"]
    },
    "Compress": true,
    "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",
    "ViewerProtocolPolicy": "https-only",
    "TargetOriginId": "myS3Origin"
  },
  "Enabled": true,
  "HttpVersion": "http2and3",
  "PriceClass": "PriceClass_100"
}
EOF

# Create distribution
aws cloudfront create-distribution --distribution-config file://cf-config.json

# Note the domain name: d123456.cloudfront.net
```

## Step 4: Update Application Code

Edit `gateway/media.py`:

```python
import boto3
import os
from datetime import timedelta

s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name='us-east-1'
)

CLOUDFRONT_DOMAIN = os.getenv('CLOUDFRONT_DOMAIN', 'd123456.cloudfront.net')
S3_BUCKET = os.getenv('S3_BUCKET', 'catalyx-bot-media')

async def upload_media_to_s3(file_path: str, key: str) -> str:
    """Upload file to S3 and return CloudFront URL"""
    try:
        with open(file_path, 'rb') as f:
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=f.read(),
                ContentType='image/jpeg',
                CacheControl='max-age=31536000'  # 1 year
            )

        # Return CloudFront URL (cached globally)
        return f"https://{CLOUDFRONT_DOMAIN}/{key}"
    except Exception as e:
        logger.error(f"S3 upload failed: {e}")
        return None

def get_media_public_url(filename: str) -> str:
    """Get the public URL for a media file"""
    return f"https://{CLOUDFRONT_DOMAIN}/media/{filename}"
```

## Step 5: Environment Variables

Add to `.env.production`:

```
AWS_ACCESS_KEY_ID=AKIXXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxx
S3_BUCKET=catalyx-bot-media
CLOUDFRONT_DOMAIN=d123456.cloudfront.net
```

## Step 6: Update Custom Domain

Add CNAME to CloudFront:

```bash
# In Route 53 or your DNS provider
media.catalyx-bot.com CNAME d123456.cloudfront.net
```

Then use in code:
```python
CLOUDFRONT_DOMAIN = 'media.catalyx-bot.com'
```

## Costs

- **S3 Storage**: $0.023 per GB/month
- **CloudFront**: $0.085 per GB delivered
- **Data transfer out**: $0.02 per GB
- **Requests**: $0.0075 per 10,000 PUT requests

**For 1000 users × 10 media/month × 5MB**:
- 50 GB storage: ~$1.15/month
- 50 GB delivery: ~$4.25/month
- **Total: ~$5/month**

## Cleanup (Local)

Once migrated to S3, remove local media storage:

```bash
# Disable local media storage
rm -rf media_files/
```

Update docker-compose to remove `media_data` volume:

```yaml
# REMOVE this from gateway service:
# volumes:
#   - media_data:/app/media_files
```

## Backup & Disaster Recovery

Enable cross-region replication:

```bash
aws s3api put-bucket-replication \
  --bucket catalyx-bot-media \
  --replication-configuration '{
    "Role": "arn:aws:iam::ACCOUNT_ID:role/s3-replication",
    "Rules": [{
      "Status": "Enabled",
      "Priority": 1,
      "DeleteMarkerReplication": {"Status": "Enabled"},
      "Filter": {"Prefix": ""},
      "Destination": {
        "Bucket": "arn:aws:s3:::catalyx-bot-media-backup",
        "ReplicationTime": {"Status": "Enabled", "Time": {"Minutes": 15}},
        "Metrics": {"Status": "Enabled", "EventThreshold": {"Minutes": 15}}
      }
    }]
  }'
```

This replicates all files to a backup bucket within 15 minutes.
