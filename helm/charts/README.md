# TiTiler EOPF Helm Chart

This Helm chart deploys TiTiler EOPF on a Kubernetes cluster.

## Prerequisites

- Kubernetes 1.16+
- Helm 3.0+

## Installation

```bash
helm install titiler-eopf ./helm
```

## Configuration

The following table lists the configurable parameters of the TiTiler EOPF chart and their default values.

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
| `env.TITILER_EOPF_STORE_URL` | EOPF store URL | `s3://esa-zarr-sentinel-explorer-fra/tests-output/` |

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

## Usage Example

1. Create a values.yaml file with your configuration:

```yaml
replicaCount: 2

ingress:
  enabled: true
  annotations:
    kubernetes.io/ingress.class: nginx
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
