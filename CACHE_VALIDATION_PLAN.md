# TiTiler-EOPF Cache Validation Plan
**Date:** January 13, 2026  
**Version:** Phase 5 Completion Testing  
**Setup:** S3+Redis cache with dedicated bucket `esa-sentinel-zarr-explorer-cache`

## Test Environment Overview
```bash
Cache Backend: s3-redis (Redis metadata + S3 tile storage)
Redis Service: localhost:6379 (docker)
S3 Bucket: esa-sentinel-zarr-explorer-cache
API Services: 
  - Main API: localhost:8000
  - OpenEO API: localhost:8081 (planned)
```

## 1. 🔧 Infrastructure Validation

### 1.1 Service Health Check
```bash
# Check all services are running
docker compose ps

# Expected: api and cache services UP
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

### 1.2 Cache Backend Connectivity 
```bash
# Test cache admin status endpoint
curl -s http://localhost:8000/admin/cache/status | jq .

# Expected: JSON response with backend_type: "s3-redis", namespace: "titiler-eopf"
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

### 1.3 Redis Connection Test
```bash
# Test Redis directly
docker exec titiler-eopf-cache-1 redis-cli ping

# Expected: PONG
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

## 2. 🎯 Core Caching Functionality

### 2.1 Cache MISS → HIT Behavior
```bash
# First request (should be MISS)
curl -I "http://localhost:8000/collections/eopf_geozarr/items/S2B_MSIL2A_20250804T103629_N0511_R008_T31TDH_20250804T130722/tiles/WebMercatorQuad/10/500/300?variables=%2Fmeasurements%2Freflectance%2Fr10m%3Ab04"

# Look for: X-Cache: MISS
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________

# Second identical request (should be HIT)  
curl -I "http://localhost:8000/collections/eopf_geozarr/items/S2B_MSIL2A_20250804T103629_N0511_R008_T31TDH_20250804T130722/tiles/WebMercatorQuad/10/500/300?variables=%2Fmeasurements%2Freflectance%2Fr10m%3Ab04"

# Look for: X-Cache: HIT
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

### 2.2 TileJSON Caching
```bash
# Test tilejson endpoint caching
curl -I "http://localhost:8000/collections/eopf_geozarr/items/S2B_MSIL2A_20250804T103629_N0511_R008_T31TDH_20250804T130722/tilejson.json?variables=%2Fmeasurements%2Freflectance%2Fr10m%3Ab04"

# Expected: X-Cache header present
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

### 2.3 Parameter Exclusion Verification
```bash
# Test with debug parameter (should be excluded from cache key)
curl -I "http://localhost:8000/collections/eopf_geozarr/items/S2B_MSIL2A_20250804T103629_N0511_R008_T31TDH_20250804T130722/tiles/WebMercatorQuad/10/500/300?variables=%2Fmeasurements%2Freflectance%2Fr10m%3Ab04&debug=true"

# Should still hit cache if tile was cached without debug param
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

## 3. 🛠️ Admin API Validation

### 3.1 Cache Status Endpoint
```bash
curl -s http://localhost:8000/admin/cache/status | jq .

# Expected: backend_type, namespace, key counts
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

### 3.2 Cache Key Listing
```bash
curl -s http://localhost:8000/admin/cache/keys | jq .

# Expected: Array of cache keys with metadata
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

### 3.3 Pattern-Based Invalidation
```bash
# Invalidate specific pattern
curl -X POST "http://localhost:8000/admin/cache/invalidate/pattern/S2B_MSIL2A_20250804T103629*"

# Expected: success: true, invalidated_count > 0
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

### 3.4 Direct Key Invalidation
```bash
# Get a cache key first
KEY=$(curl -s http://localhost:8000/admin/cache/keys | jq -r '.keys[0].key' 2>/dev/null)

# Invalidate specific key
curl -X DELETE "http://localhost:8000/admin/cache/invalidate/key/$KEY"

# Expected: successful deletion response
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

## 4. 🌐 Multi-Endpoint Testing

### 4.1 Preview Endpoint Caching
```bash
curl -I "http://localhost:8000/collections/eopf_geozarr/items/S2B_MSIL2A_20250804T103629_N0511_R008_T31TDH_20250804T130722/preview?variables=%2Fmeasurements%2Freflectance%2Fr10m%3Ab04"

# Expected: X-Cache header present
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

### 4.2 Statistics Endpoint Caching
```bash
curl -I "http://localhost:8000/collections/eopf_geozarr/items/S2B_MSIL2A_20250804T103629_N0511_R008_T31TDH_20250804T130722/statistics?variables=%2Fmeasurements%2Freflectance%2Fr10m%3Ab04"

# Expected: X-Cache header present  
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

### 4.3 Info.json Endpoint Caching
```bash
curl -I "http://localhost:8000/collections/eopf_geozarr/items/S2B_MSIL2A_20250804T103629_N0511_R008_T31TDH_20250804T130722/info.json?variables=%2Fmeasurements%2Freflectance%2Fr10m%3Ab04"

# Expected: X-Cache header present
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

## 5. 🚨 Error Handling Scenarios

### 5.1 Redis Unavailable Test
```bash
# Stop Redis temporarily
docker compose stop cache

# Make a tile request
curl -I "http://localhost:8000/collections/eopf_geozarr/items/S2B_MSIL2A_20250804T103629_N0511_R008_T31TDH_20250804T130722/tiles/WebMercatorQuad/10/500/300?variables=%2Fmeasurements%2Freflectance%2Fr10m%3Ab04"

# Expected: X-Cache: ERROR or SKIP, but response should still work
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________

# Restart Redis
docker compose start cache
```

### 5.2 Invalid Pattern Invalidation
```bash
# Try invalid invalidation pattern
curl -X POST "http://localhost:8000/admin/cache/invalidate/pattern/"

# Expected: 400 or 422 error with proper error message
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

### 5.3 Non-existent Key Invalidation
```bash
# Try to invalidate non-existent key
curl -X DELETE "http://localhost:8000/admin/cache/invalidate/key/nonexistent-key-12345"

# Expected: Proper error response (404 or similar)
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

## 6. 📊 Performance & Storage Validation

### 6.1 Cache Key Generation Performance
```bash
# Time multiple cache key generations
time curl -s "http://localhost:8000/admin/cache/keys" >/dev/null

# Expected: Response time < 1 second
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

### 6.2 S3 Storage Verification
```bash
# Check if tiles are actually stored in S3 bucket
# (Requires AWS CLI with eopf-explorer profile)
aws s3 ls s3://esa-sentinel-zarr-explorer-cache/ --profile eopf-explorer --endpoint-url=https://s3.de.io.cloud.ovh.net

# Expected: Some cached tile objects visible
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

## 7. 🔄 OpenEO Integration (Optional)

### 7.1 Start OpenEO Service
```bash
# Start OpenEO API service
docker compose up -d api-openeo

# Check status
docker compose ps
```

### 7.2 OpenEO Cache Functionality
```bash
# Test OpenEO endpoint with caching
curl -I "http://localhost:8081/[openeo-endpoint]"

# Expected: X-Cache headers present
# Status: [ ] PASS [ ] FAIL [ ] NOTES: ___________
```

## 8. 📝 Validation Checklist

### Critical Functionality
- [ ] Basic service connectivity works
- [ ] Cache MISS→HIT behavior works correctly
- [ ] Admin API status endpoint responds
- [ ] Cache invalidation works
- [ ] Error handling graceful degradation works

### Performance Requirements
- [ ] Cache response time < 100ms for hits
- [ ] Admin API response time < 1s
- [ ] No memory leaks during sustained testing
- [ ] S3 storage working correctly

### Integration Points
- [ ] All cache-enabled endpoints work
- [ ] Parameter exclusion working
- [ ] X-Cache headers present on all responses
- [ ] Redis and S3 backend coordination working

## 9. 📊 Issue Reporting Template

```
### Issue #X: [Brief Description]

**Environment:** 
- Backend: s3-redis
- Redis: localhost:6379
- S3: esa-sentinel-zarr-explorer-cache

**Steps to Reproduce:**
1. [Step]
2. [Step]  
3. [Step]

**Expected Behavior:**
[What should happen]

**Actual Behavior:**
[What actually happened]

**Request/Response:**
[curl command and response]

**Priority:** [ ] Critical [ ] High [ ] Medium [ ] Low

**Logs:**
```bash
# Get API logs
docker compose logs api

# Get Redis logs  
docker compose logs cache
```

**Resolution Status:** [ ] Open [ ] In Progress [ ] Resolved
```

---

## Summary Report

**Total Tests:** [X]  
**Passed:** [X]  
**Failed:** [X]  
**Critical Issues:** [X]  

**Overall Assessment:** [ ] ✅ Ready for Production [ ] ⚠️ Issues Found [ ] ❌ Critical Problems

**Next Steps:**
- [ ] Proceed to Phase 6 (Monitoring)
- [ ] Fix identified issues
- [ ] Additional testing required

**Performance Baseline:**
- Cache Hit Rate: __%
- Average Response Time (HIT): __ms
- Average Response Time (MISS): __ms
- Redis Memory Usage: __MB