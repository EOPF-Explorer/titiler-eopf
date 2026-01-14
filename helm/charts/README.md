# TiTiler EOPF Helm Chart

This Helm chart deploys TiTiler EOPF on a Kubernetes cluster with comprehensive caching support.

## Prerequisites

- Kubernetes 1.16+
- Helm 3.0+

## Installation

### Quick Start (No Caching)
```bash
helm install titiler-eopf ./helm
```

### With Redis Caching
```bash
helm install titiler-eopf ./helm -f examples/cache-redis-values.yaml
```

### With S3+Redis Hybrid Caching (Production)
```bash
# Create secrets first
kubectl create secret generic redis-cache-secret --from-literal=redis-password="your-password"
kubectl create secret generic s3-cache-secret --from-literal=access-key-id="your-key" --from-literal=secret-access-key="your-secret"

helm install titiler-eopf ./helm -f examples/cache-s3-redis-values.yaml
```

## Cache Configuration

The chart supports three cache backends:

1. **Redis-only** (`redis`): Simple setup using Redis for all cache data
2. **S3-only** (`s3`): Uses S3 for tile storage with TTL metadata 
3. **S3+Redis hybrid** (`s3-redis`): Redis for metadata, S3 for tile data (recommended for production)

See [CACHE_CONFIG.md](CACHE_CONFIG.md) for detailed configuration guide.

## Configuration

### Cache Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `cache.enabled` | Enable tile caching system | `false` |
| `cache.backend` | Cache backend: `redis`, `s3`, or `s3-redis` | `redis` |
| `cache.ttl.default` | Default TTL in seconds | `3600` |
| `cache.ttl.tiles` | Tile cache TTL in seconds | `3600` |
| `cache.ttl.datasets` | Dataset cache TTL in seconds | `1800` |
| `cache.namespace` | Cache key namespace | `titiler-eopf` |

### Redis Cache Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `cache.redis.internal.enabled` | Use internal Redis deployment | `false` |
| `cache.redis.external.enabled` | Use external Redis instance | `false` |
| `cache.redis.external.host` | External Redis hostname | `""` |
| `cache.redis.external.port` | External Redis port | `6379` |
| `cache.redis.external.database` | Redis database number | `0` |
| `cache.redis.external.auth.enabled` | Enable Redis authentication | `false` |
| `cache.redis.external.auth.existingSecret` | Secret name for Redis password | `""` |

### S3 Cache Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `cache.s3.enabled` | Enable S3 cache storage | `false` |
| `cache.s3.bucket` | S3 bucket name | `""` |
| `cache.s3.region` | S3 region | `us-east-1` |
| `cache.s3.endpoint_url` | Custom S3 endpoint URL | `""` |
| `cache.s3.prefix` | S3 object prefix | `cache/` |
| `cache.s3.auth.existingSecret` | Secret name for S3 credentials | `""` |
| `cache.s3.auth.accessKeyIdKey` | Secret key for S3 access key ID | `access-key-id` |
| `cache.s3.auth.secretAccessKeyKey` | Secret key for S3 secret access key | `secret-access-key` |

### Image Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.repository` | Image repository | `ghcr.io/eopf-explorer/titiler-eopf` |
| `image.tag` | Image tag | `latest` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |

### Application Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of replicas | `1` |
| `service.type` | Kubernetes service type | `ClusterIP` |
| `service.port` | Kubernetes service port | `80` |
| `terminationGracePeriodSeconds` | Pod termination grace period | `30` |

### Environment Variables

| Parameter | Description | Default |
|-----------|-------------|---------|
| `env.LOG_LEVEL` | Application log level | `INFO` |
| `env.TITILER_EOPF_STORE_URL` | EOPF store URL (can be any URL supported by xarray, fsspec, or obstore) | `s3://esa-zarr-sentinel-explorer-fra/tests-output/` |

### AWS Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `secrets.secretName` | Name of the AWS credentials secret | `titiler-eopf-secret` |
| `secrets.keys.AWS_ACCESS_KEY_ID` | AWS access key ID | `""` |
| `secrets.keys.AWS_SECRET_ACCESS_KEY` | AWS secret access key | `""` |
| `env.AWS_DEFAULT_REGION` | AWS region | `de` |
| `env.AWS_ENDPOINT_URL` | AWS endpoint URL | `https://s3.de.io.cloud.ovh.net/` |

### Resource Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `resources.limits.cpu` | CPU limit | `1` |
| `resources.limits.memory` | Memory limit | `2Gi` |
| `resources.requests.cpu` | CPU request | `500m` |
| `resources.requests.memory` | Memory request | `1Gi` |

### Ingress Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ingress.enabled` | Enable ingress | `false` |
| `ingress.annotations` | Ingress annotations | `{}` |
| `ingress.hosts` | Ingress hosts configuration | `[{host: titiler-eopf.local, paths: ["/"]}]` |
| `ingress.tls` | Ingress TLS configuration | `[]` |
| `ingress.className` | Ingress class | `""` |

## Usage Example

1. Create a values.yaml file with your configuration:

```yaml
replicaCount: 2

ingress:
  enabled: true
  annotations:
    kubernetes.io/ingress.class: nginx # Deprecated - https://kubernetes.io/docs/concepts/services-networking/ingress/#deprecated-annotation
  className: nginx
  hosts:
    - host: titiler.example.com
      paths: ["/"]

secrets:
  keys:
    AWS_ACCESS_KEY_ID: your-access-key
    AWS_SECRET_ACCESS_KEY: your-secret-key
```

2. Install the chart:

```bash
helm install titiler-eopf ./helm -f values.yaml
```

## Development

To modify or extend this Helm chart:

1. Update the values.yaml file with your desired defaults
2. Modify the templates as needed
3. Test the changes:

```bash
helm lint ./helm
helm template titiler-eopf ./helm
```
