# KubeFreezer

**KubeFreezer** is a Kubernetes admission controller that enforces deployment freezes to prevent deployments during maintenance windows, holidays, or scheduled freeze periods. It provides flexible bypass mechanisms for emergency deployments while maintaining strict control over your cluster's deployment schedule.

## 🎯 What is KubeFreezer?

KubeFreezer acts as a gatekeeper for your Kubernetes cluster, intercepting all deployment, statefulset, and daemonset operations through a ValidatingAdmissionWebhook. When a freeze is active, it blocks these operations unless they match one of the configured bypass mechanisms.

### Key Features

- ✅ **Time-based Freeze Windows** - Block deployments during scheduled periods
- ✅ **Freeze Templates** - Reusable freeze schedules (weekend blackouts, holiday periods, etc.)
- ✅ **Multiple Bypass Mechanisms** - Flexible options for emergency deployments
- ✅ **REST API** - Enable/disable freeze programmatically
- ✅ **Real-time Configuration** - ConfigMap changes take effect without restart
- ✅ **ArgoCD Compatible** - Works seamlessly with GitOps workflows
- ✅ **Web UI** - User-friendly interface for managing freezes
- ✅ **Audit Logging** - Track all freeze events and bypass usage

## 📦 Installation

### Prerequisites

- Kubernetes cluster (1.20+)
- `kubectl` configured with cluster access
- Helm 3.x

### Install with Helm

Add the Helm repository and install:

```bash
# Add the Helm repository
helm repo add kube-freezer https://fadih.github.io/kube-freezer
helm repo update

# Install KubeFreezer
helm install kube-freezer kube-freezer/kube-freezer \
  --namespace kube-freezer \
  --create-namespace \
  --set backend.image.tag=1.2.0 \
  --set frontend.image.tag=1.2.0
```

Replace `1.2.0` with the version you want to install (check [releases](https://github.com/Fadih/kube-freezer/releases) for available versions).

### Verify Installation

```bash
# Check pods are running
kubectl get pods -n kube-freezer

# Check webhook is registered
kubectl get validatingwebhookconfiguration kube-freezer
```

### Get Your API Key

After installation, retrieve your API key:

```bash
kubectl get secret kube-freezer-api-keys -n kube-freezer \
  -o jsonpath='{.data.api_key_admin}' | base64 -d && echo
```

Save this key securely - you'll need it to authenticate API requests.

## ⚙️ Configuration

KubeFreezer is configured via a ConfigMap. All configuration changes take effect immediately without requiring a pod restart.

### Configuration Options

The main configuration is stored in the `kube-freezer-config` ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: kube-freezer-config
  namespace: kube-freezer
data:
  # Freeze control
  freeze_enabled: "false"                    # Enable/disable freeze
  freeze_until: ""                           # ISO 8601 timestamp when freeze ends
  freeze_message: "Deployment freeze is active. Use bypass annotation or contact oncall."
  
  # Bypass configuration
  bypass_annotation_key: "admission-controller.io/emergency-bypass"
  bypass_allowed_users: |                    # Users/ServiceAccounts that can bypass
    system:serviceaccount:ops:oncall-engineer
  bypass_exempt_namespaces: |                # Namespaces exempt from freeze
    kube-system
    kube-public
    monitoring
  
  # Resource monitoring
  monitored_resources: |                     # Resources to monitor
    - deployments
    - statefulsets
    - daemonsets
  
  # Security
  fail_closed: "true"                        # If true, webhook failures block deployments
  api_allowed_serviceaccounts: |             # ServiceAccounts allowed to use REST API
    system:serviceaccount:kube-freezer:kube-freezer
```

### Enable/Disable Freeze

**Method 1: Update ConfigMap**

```bash
kubectl patch configmap kube-freezer-config \
  -n kube-freezer \
  --type merge \
  -p '{"data":{"freeze_enabled":"true","freeze_until":"2025-12-31T23:59:59Z"}}'
```

**Method 2: REST API**

```bash
# Get your API key first
API_KEY=$(kubectl get secret kube-freezer-api-keys -n kube-freezer \
  -o jsonpath='{.data.api_key_admin}' | base64 -d)

# Enable freeze
curl -k -X POST https://kube-freezer-backend.kube-freezer.svc/api/v1/freeze/enable \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "freeze_until": "2025-12-31T23:59:59Z",
    "reason": "Holiday freeze period"
  }'

# Check status
curl -k https://kube-freezer-backend.kube-freezer.svc/api/v1/freeze/status \
  -H "Authorization: Bearer $API_KEY"

# Disable freeze
curl -k -X POST https://kube-freezer-backend.kube-freezer.svc/api/v1/freeze/disable \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Freeze period ended"}'
```

**Method 3: Web UI**

Access the web UI via port-forward:

```bash
kubectl port-forward -n kube-freezer svc/kube-freezer-frontend 8080:80
```

Then open http://localhost:8080 in your browser.

## 🔓 Bypass Mechanisms

KubeFreezer provides four bypass mechanisms, checked in the following priority order:

### 1. Annotation Bypass (Highest Priority)

Add an annotation to your deployment manifest to bypass the freeze for that specific resource.

**How it works:**
- Checked first before any other bypass mechanism
- Resource-specific (only affects the annotated resource)
- Requires no pre-configuration
- Ideal for emergency hotfixes

**Usage:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: critical-hotfix
  annotations:
    admission-controller.io/emergency-bypass: "true"
    admission-controller.io/emergency-reason: "Critical CVE-2024-XXXX patch"
spec:
  # ... deployment spec
```

**Configuration:**
- Default annotation key: `admission-controller.io/emergency-bypass`
- Can be customized via `bypass_annotation_key` in ConfigMap
- Optional reason annotation: `admission-controller.io/emergency-reason`

**When to use:**
- Emergency security patches
- Critical bug fixes that can't wait
- One-off deployments during freeze periods

---

### 2. User/ServiceAccount Allowlist

Pre-configure specific users or ServiceAccounts that are allowed to bypass the freeze for all their deployments.

**How it works:**
- Checked after annotation bypass
- User-based (all deployments by this user bypass the freeze)
- Requires pre-configuration in ConfigMap
- Ideal for on-call engineers or automated systems

**Configuration:**

```yaml
# In kube-freezer-config ConfigMap
bypass_allowed_users: |
  system:serviceaccount:ops:oncall-engineer
  system:serviceaccount:ci-cd:deployment-bot
  system:serviceaccount:security:security-team
```

**Supported formats:**
- Kubernetes ServiceAccounts: `system:serviceaccount:<namespace>:<name>`
- AWS IAM users: `arn:aws:iam::<account-id>:user/<username>`
- Kubernetes users: `<username>`
- Groups: `<group-name>`

**When to use:**
- On-call engineers who need to deploy during freezes
- CI/CD pipelines that need to deploy hotfixes
- Security teams deploying patches
- Automated systems with controlled access

---

### 3. Namespace Exemptions

Exempt entire namespaces from freeze enforcement. All resources in exempted namespaces can be deployed regardless of freeze status.

**How it works:**
- Checked after user allowlist
- Namespace-wide (all resources in the namespace are exempt)
- Requires pre-configuration in ConfigMap
- Ideal for system namespaces or staging environments

**Configuration:**

```yaml
# In kube-freezer-config ConfigMap
bypass_exempt_namespaces: |
  kube-system
  kube-public
  kube-node-lease
  monitoring
  logging
  staging
```

**Default exempt namespaces:**
- `kube-system` - Kubernetes system components
- `kube-public` - Public cluster information
- `kube-node-lease` - Node heartbeat leases
- `kube-freezer` - KubeFreezer itself

**When to use:**
- System namespaces that need to operate normally
- Staging/test environments
- Monitoring and logging infrastructure
- Namespaces that should never be frozen

---

### 4. Temporary Exemptions (API-based)

Create time-limited exemptions via the REST API. These exemptions are resource-specific or namespace-specific and automatically expire.

**How it works:**
- Checked after namespace exemptions
- Time-limited (automatically expire)
- Created via REST API
- Can be resource-specific or namespace-wide
- Ideal for planned maintenance windows

**Usage:**

```bash
# Get your API key
API_KEY=$(kubectl get secret kube-freezer-api-keys -n kube-freezer \
  -o jsonpath='{.data.api_key_admin}' | base64 -d)

# Create a temporary exemption for a specific resource
curl -k -X POST https://kube-freezer-backend.kube-freezer.svc/api/v1/freeze/exemptions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "namespace": "production",
    "resource_name": "hotfix-deployment",
    "duration_minutes": 120,
    "reason": "Emergency security patch deployment",
    "approved_by": "security-team@company.com"
  }'

# Create a namespace-wide exemption
curl -k -X POST https://kube-freezer-backend.kube-freezer.svc/api/v1/freeze/exemptions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "namespace": "production",
    "duration_minutes": 60,
    "reason": "Planned maintenance window",
    "approved_by": "ops-team@company.com"
  }'

# List active exemptions
curl -k https://kube-freezer-backend.kube-freezer.svc/api/v1/freeze/exemptions?active_only=true \
  -H "Authorization: Bearer $API_KEY"

# Delete an exemption
curl -k -X DELETE https://kube-freezer-backend.kube-freezer.svc/api/v1/freeze/exemptions/<exemption-id> \
  -H "Authorization: Bearer $API_KEY"
```

**When to use:**
- Planned maintenance windows
- Scheduled deployments during freeze periods
- Temporary access for specific teams
- Resource-specific exemptions that need to expire automatically

---

## 🔄 Bypass Priority Order

When a deployment request is made, KubeFreezer checks bypass mechanisms in this order:

1. **Annotation Bypass** - If the resource has the bypass annotation → **ALLOW**
2. **User Allowlist** - If the user/ServiceAccount is in the allowlist → **ALLOW**
3. **Namespace Exemption** - If the namespace is exempt → **ALLOW**
4. **Temporary Exemption** - If an active exemption exists → **ALLOW**
5. **Freeze Check** - If freeze is active → **DENY**, otherwise → **ALLOW**

**Important:** The first matching bypass mechanism wins. If none match and freeze is active, the deployment is blocked.

## 🎨 Freeze Templates

KubeFreezer supports freeze templates for recurring freeze periods (weekends, holidays, maintenance windows). Templates use cron expressions for flexible scheduling.

See the [Templates documentation](https://github.com/Fadih/kube-freezer) for details on creating and managing templates.

## 🔌 ArgoCD Integration

KubeFreezer works seamlessly with ArgoCD and other GitOps tools:

- ArgoCD syncs are intercepted by the webhook
- During freeze, ArgoCD syncs are blocked
- Use annotation bypass in your GitOps manifests for emergency deployments
- Exempt ArgoCD's namespace if needed for system operations

**Example ArgoCD Application with bypass:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: critical-hotfix
  annotations:
    admission-controller.io/emergency-bypass: "true"
    admission-controller.io/emergency-reason: "CVE patch"
spec:
  # ... application spec
```

## 📊 Monitoring and Logging

### View Freeze History

```bash
# Get API key
API_KEY=$(kubectl get secret kube-freezer-api-keys -n kube-freezer \
  -o jsonpath='{.data.api_key_admin}' | base64 -d)

# View freeze history
curl -k https://kube-freezer-backend.kube-freezer.svc/api/v1/freeze/history \
  -H "Authorization: Bearer $API_KEY"
```

### Prometheus Metrics

KubeFreezer exposes Prometheus metrics at `/metrics`:

- `kubefreezer_freeze_active` - Whether freeze is currently active
- `kubefreezer_requests_total` - Total admission requests
- `kubefreezer_requests_blocked` - Blocked requests
- `kubefreezer_bypass_used_total` - Bypass usage by type

## 🛠️ Troubleshooting

### Check Webhook Status

```bash
# Verify webhook is registered
kubectl get validatingwebhookconfiguration kube-freezer

# Check webhook logs
kubectl logs -n kube-freezer -l app.kubernetes.io/name=kube-freezer,component=backend
```

### Test Bypass Mechanisms

1. **Test annotation bypass:**
   ```bash
   kubectl apply -f - <<EOF
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: test-bypass
     annotations:
       admission-controller.io/emergency-bypass: "true"
   spec:
     replicas: 1
     selector:
       matchLabels:
         app: test
     template:
       metadata:
         labels:
           app: test
       spec:
         containers:
         - name: test
           image: nginx:latest
   EOF
   ```

2. **Check if user is in allowlist:**
   ```bash
   kubectl get configmap kube-freezer-config -n kube-freezer -o yaml | grep bypass_allowed_users
   ```

## 📚 Additional Resources

- [GitHub Repository](https://github.com/Fadih/kube-freezer)
- [Helm Chart Repository](https://fadih.github.io/kube-freezer)
- [Issue Tracker](https://github.com/Fadih/kube-freezer/issues)

## 📝 License

Apache 2.0 - See [LICENSE](LICENSE) file for details.
