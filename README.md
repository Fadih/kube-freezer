# KubeFreezer

Kubernetes admission controller for deployment freeze management. Block deployments during maintenance windows, holidays, or scheduled freezes with configurable bypass mechanisms for emergency patches.

## Features

- ✅ **Time-based Freeze Windows** - Block deployments during scheduled periods
- ✅ **Annotation Bypass** - Emergency deployments via annotation
- ✅ **User Allowlist** - Allow specific users/service accounts to bypass freeze
- ✅ **Namespace Exemptions** - Exempt specific namespaces from freeze
- ✅ **REST API** - Enable/disable freeze programmatically
- ✅ **ArgoCD Compatible** - Works seamlessly with GitOps workflows
- ✅ **Hot Reload** - ConfigMap changes take effect without restart

## Quick Start

### Prerequisites

- Kubernetes cluster (1.20+)
- kubectl configured
- Helm 3.x (optional, for Helm installation)

### Installation with Helm

```bash
# Create namespace first
kubectl create namespace kube-freezer

# Install
helm install kube-freezer ./helm/kube-freezer \
  --namespace kube-freezer \
  --set createNamespace=false

# Or use the install script (handles everything)
./scripts/install.sh
```

### Manual Installation

```bash
# 1. Generate TLS certificates
./scripts/generate-certs.sh

# 2. Update ValidatingWebhookConfiguration with CA bundle
# (Output from script above)

# 3. Apply manifests
kubectl apply -f helm/kube-freezer/templates/
```

## Configuration

### ConfigMap Structure

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: kube-freezer-config
  namespace: kube-freezer
data:
  freeze_enabled: "true"
  freeze_until: "2024-12-25T00:00:00Z"
  freeze_message: "Holiday freeze - no deployments allowed"
  bypass_annotation_key: "admission-controller.io/emergency-bypass"
  bypass_allowed_users: |
    system:serviceaccount:ops:oncall-engineer
  bypass_exempt_namespaces: |
    kube-system
    monitoring
  monitored_resources: |
    - deployments
    - statefulsets
    - daemonsets
```

### Enable/Disable Freeze

**Method 1: Update ConfigMap**
```bash
kubectl patch configmap kube-freezer-config \
  -n kube-freezer \
  --type merge \
  -p '{"data":{"freeze_enabled":"true","freeze_until":"2024-12-25T00:00:00Z"}}'
```

**Method 2: REST API**
```bash
# Enable freeze
curl -X POST https://kube-freezer.kube-freezer.svc/api/v1/freeze/enable \
  -H "Content-Type: application/json" \
  -d '{"until": "2024-12-25T00:00:00Z", "reason": "Holiday freeze"}'

# Check status
curl https://kube-freezer.kube-freezer.svc/api/v1/freeze/status

# Disable freeze
curl -X POST https://kube-freezer.kube-freezer.svc/api/v1/freeze/disable \
  -d '{"reason": "Freeze period ended"}'
```

## Bypass Mechanisms

### 1. Annotation Bypass

Add annotation to your deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hotfix
  annotations:
    admission-controller.io/emergency-bypass: "true"
    admission-controller.io/emergency-reason: "Critical CVE patch"
```

### 2. User Allowlist

Configure allowed users in ConfigMap:

```yaml
bypass_allowed_users: |
  system:serviceaccount:ops:oncall-engineer
  arn:aws:iam::123456789012:user/admin-user
```

### 3. Namespace Exemption

Exempt namespaces from freeze:

```yaml
bypass_exempt_namespaces: |
  kube-system
  monitoring
  staging
```

## ArgoCD Integration

KubeFreezer works seamlessly with ArgoCD. See [ArgoCD Integration Guide](docs/ARGOCD_INTEGRATION.md) for details.

**Quick Example:**
- ArgoCD syncs are intercepted by the webhook
- During freeze, ArgoCD syncs are blocked
- Use annotation bypass for emergency deployments via GitOps

## Development

### Local Development Setup

Before deploying to Kubernetes, test locally to catch issues early:

```bash
# Full local test (creates venv, installs deps, compiles, tests imports)
make local

# Or step by step:
make venv              # Create virtual environment
make local-install     # Install dependencies
make compile           # Check for syntax errors
make local-test        # Test imports and basic functionality
make local-run         # Run the application locally (requires kubeconfig)
```

### Build Docker Image

```bash
make build
# Or manually:
docker build -t fadihussien/kubefreezer:0.3.0 -f app/Dockerfile app/
```

### Run Locally

```bash
# Using Makefile (recommended)
make local-run

# Or manually:
source venv/bin/activate
cd app
python -m uvicorn main:app --host 0.0.0.0 --port 8443 --reload
```

**Note:** Local run requires:
- Valid Kubernetes cluster access (kubeconfig)
- Or mock configuration for testing

### Run Tests

```bash
# TODO: Add tests
pytest tests/
```

## Documentation

- [Design Document](DESIGN.md) - Architecture and design decisions
- [ArgoCD Integration](docs/ARGOCD_INTEGRATION.md) - ArgoCD integration guide

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

Apache 2.0 - See [LICENSE](LICENSE) file

## Status

✅ **Phase 4 - Complete**

Current features:
- ✅ Basic webhook server
- ✅ ConfigMap-based configuration
- ✅ Time-based freeze
- ✅ Freeze schedules (recurring, timezone support)
- ✅ Annotation bypass
- ✅ User allowlist
- ✅ Temporary exemptions API
- ✅ Freeze history tracking
- ✅ API authentication
- ✅ Rate limiting
- ✅ REST API
- ✅ Helm chart
- ✅ Kubernetes Watch API (real-time config updates)
- ✅ Prometheus metrics
- ✅ Structured JSON logging
- ✅ NetworkPolicy security
- ✅ **Notification integration (Slack, email)** 🆕
- ✅ **Freeze templates** 🆕
- ✅ **Advanced audit logging** 🆕
- ✅ **Dry-run mode** 🆕

Future enhancements (optional):
- ⏳ CRD support
- ⏳ Multi-cluster support
- ⏳ OIDC/OAuth2 authentication
