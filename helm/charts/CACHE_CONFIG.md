# Cache Configuration Guide

The TiTiler-EOPF Helm chart supports a comprehensive caching system with multiple backend options and configurations.

## Cache Backends

### 1. Redis-only (`redis`)
Uses Redis for both metadata and tile data storage.
- **Pros**: Simple setup, good performance for small to medium datasets
- **Cons**: Memory limitations, data loss on Redis restart without persistence
- **Use cases**: Development, testing, small deployments

### 2. S3-only (`s3`) 
Uses S3 for tile data storage with TTL metadata stored as object tags.
- **Pros**: Unlimited storage, persistent across restarts
- **Cons**: Higher latency, more complex TTL management
- **Use cases**: Large datasets with infrequent access patterns

### 3. S3+Redis hybrid (`s3-redis`)
Uses Redis for metadata and S3 for tile data storage.
- **Pros**: Fast metadata access, unlimited storage, efficient TTL handling
- **Cons**: More complex setup, requires both services
- **Use cases**: Production deployments with large datasets

## Configuration Examples

### Development Setup (Redis-only with internal Redis)
```yaml
cache:
  enabled: true
  backend: redis
  redis:
    internal:
      enabled: true
```

### Staging Setup (External Redis)
```yaml
cache:
  enabled: true
  backend: redis
  redis:
    external:
      enabled: true
      host: "redis.staging.example.com"
      auth:
        enabled: true
        existingSecret: "redis-secret"
```

### Production Setup (S3+Redis hybrid)
```yaml
cache:
  enabled: true
  backend: s3-redis
  redis:
    external:
      enabled: true
      host: "cache-cluster.prod.amazonaws.com"
      auth:
        enabled: true
        existingSecret: "redis-secret"
  s3:
    enabled: true
    bucket: "prod-tile-cache"
    auth:
      existingSecret: "s3-cache-secret"
```

## Required Secrets

### Redis Authentication Secret
```bash
kubectl create secret generic redis-cache-secret \
  --from-literal=redis-password="your-redis-password"
```

### S3 Authentication Secret
```bash
kubectl create secret generic s3-cache-secret \
  --from-literal=access-key-id="your-access-key" \
  --from-literal=secret-access-key="your-secret-key"
```

## Environment Variables Generated

The chart automatically generates the following environment variables based on configuration:

### Cache Control
- `TITILER_EOPF_CACHE_ENABLE`: "true" when cache is enabled
- `TITILER_EOPF_CACHE_BACKEND`: Backend type (redis/s3/s3-redis)  
- `TITILER_EOPF_CACHE_TTL_DEFAULT`: Default TTL in seconds
- `TITILER_EOPF_CACHE_NAMESPACE`: Cache key namespace

### Redis Configuration
- `TITILER_EOPF_CACHE_REDIS_HOST`: Redis hostname
- `TITILER_EOPF_CACHE_REDIS_PORT`: Redis port
- `TITILER_EOPF_CACHE_REDIS_DATABASE`: Redis database number
- `TITILER_EOPF_CACHE_REDIS_PASSWORD`: Redis password (from secret)

### S3 Configuration  
- `TITILER_EOPF_CACHE_S3_BUCKET`: S3 bucket name
- `TITILER_EOPF_CACHE_S3_REGION`: S3 region
- `TITILER_EOPF_CACHE_S3_ENDPOINT_URL`: Custom S3 endpoint (optional)
- `TITILER_EOPF_CACHE_S3_ACCESS_KEY_ID`: S3 access key (from secret)
- `TITILER_EOPF_CACHE_S3_SECRET_ACCESS_KEY`: S3 secret key (from secret)

### Admin API
- `TITILER_EOPF_CACHE_ADMIN_ENABLE`: "true" when admin API enabled
- `TITILER_EOPF_CACHE_ADMIN_PREFIX`: Admin API path prefix

## Validation Rules

The chart includes comprehensive validation:

1. **Backend validation**: Must be one of `redis`, `s3`, or `s3-redis`
2. **Redis requirements**: Redis configuration required for `redis` and `s3-redis` backends
3. **S3 requirements**: S3 configuration required for `s3` and `s3-redis` backends  
4. **Authentication validation**: Ensures proper auth configuration for external services
5. **Mutual exclusion**: Internal and external Redis cannot both be enabled

## Migration from Environment Variables

If you're currently using environment variables for cache configuration, migrate to Helm values:

### Before (Environment Variables)
```yaml
env:
  TITILER_EOPF_CACHE_ENABLE: "true"
  TITILER_EOPF_CACHE_HOST: "redis.example.com"
  TITILER_EOPF_CACHE_PORT: "6379"
```

### After (Helm Values)
```yaml
cache:
  enabled: true
  backend: redis
  redis:
    external:
      enabled: true
      host: "redis.example.com"
      port: 6379
```

## Troubleshooting

### Common Issues

1. **Backend validation failed**
   - Check that `cache.backend` is one of: `redis`, `s3`, `s3-redis`

2. **Redis configuration missing**
   - Ensure either `cache.redis.internal.enabled` or `cache.redis.external.enabled` is true
   - For external Redis, provide `cache.redis.external.host`

3. **S3 configuration missing**
   - Set `cache.s3.enabled: true`
   - Provide `cache.s3.bucket`
   - Configure S3 authentication (existingSecret recommended)

4. **Authentication errors**
   - Verify secret names and keys match configuration
   - Check that secrets exist in the same namespace

### Debugging Commands

```bash
# Test chart validation
helm template . --values examples/cache-redis-values.yaml --debug

# Check generated environment variables
helm template . --values examples/cache-s3-redis-values.yaml | grep -A 20 "env:"

# Validate specific backend
helm template . --set cache.enabled=true --set cache.backend=invalid
```

## Performance Considerations

### Redis-only Backend
- Memory usage: ~1MB per 1000 tiles (depends on tile size)
- Recommended memory: 2-4GB for typical workloads
- Enable Redis persistence for production

### S3-only Backend
- Latency: Higher due to S3 round-trips
- Cost: Storage costs for cached tiles
- TTL cleanup: Requires periodic cleanup jobs

### S3+Redis Hybrid
- Memory usage: ~100KB per 1000 tiles (metadata only)
- Best performance with unlimited storage
- Recommended for production workloads