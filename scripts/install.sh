#!/bin/bash
set -e

# KubeFreezer Installation Script

NAMESPACE="${NAMESPACE:-kube-freezer}"
RELEASE_NAME="${RELEASE_NAME:-kube-freezer}"

echo "🚀 Installing KubeFreezer..."
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl is not installed. Please install kubectl first."
    exit 1
fi

# Check if helm is available
if ! command -v helm &> /dev/null; then
    echo "❌ Helm is not installed. Please install Helm 3.x first."
    exit 1
fi

# Check cluster connectivity
if ! kubectl cluster-info &> /dev/null; then
    echo "❌ Cannot connect to Kubernetes cluster. Please check your kubeconfig."
    exit 1
fi

echo "✅ Prerequisites check passed"
echo ""

# Create namespace first
echo ""
echo "📦 Creating namespace..."
kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

# Delete existing Secret if present (Helm will recreate it)
echo ""
echo "🗑️  Cleaning up existing Secret if present..."
kubectl delete secret "${RELEASE_NAME}-tls" -n "${NAMESPACE}" --ignore-not-found=true || true

# Install with Helm
echo ""
echo "📦 Installing KubeFreezer with Helm..."
# Default image tags (can be overridden via environment variables)
BACKEND_TAG="${BACKEND_TAG:-0.5.10}"
FRONTEND_TAG="${FRONTEND_TAG:-0.5.11}"

helm install "${RELEASE_NAME}" ./helm/kube-freezer \
    --namespace "${NAMESPACE}" \
    --set createNamespace=false \
    --set backend.image.tag="${BACKEND_TAG}" \
    --set frontend.image.tag="${FRONTEND_TAG}" \
    --set backend.enabled=true \
    --set frontend.enabled=true \
    --wait

# Generate certificates and update Secret
echo ""
echo "🔐 Generating TLS certificates (required for webhook - Kubernetes mandates HTTPS)..."
./scripts/generate-certs.sh

# Extract CA bundle and update ValidatingWebhookConfiguration
echo ""
echo "📋 Updating ValidatingWebhookConfiguration with CA bundle..."
CA_BUNDLE=$(cat certs/tls.crt | base64 | tr -d '\n')
kubectl patch validatingwebhookconfiguration "${RELEASE_NAME}" \
    --type='json' \
    -p="[{\"op\": \"replace\", \"path\": \"/webhooks/0/clientConfig/caBundle\", \"value\":\"${CA_BUNDLE}\"}]"

# Wait for pods to be ready
echo ""
echo "⏳ Waiting for KubeFreezer to be ready..."
kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/name=kube-freezer \
    -n "${NAMESPACE}" \
    --timeout=120s

echo ""
echo "✅ KubeFreezer installed successfully!"
echo ""
echo "To check status:"
echo "  kubectl get pods -n ${NAMESPACE}"
echo ""
echo "To check freeze status:"
echo "  kubectl port-forward -n ${NAMESPACE} svc/${RELEASE_NAME}-backend 8443:443"
echo "  curl -k https://localhost:8443/api/v1/freeze/status"
echo ""
echo "To access the UI:"
echo "  kubectl port-forward -n ${NAMESPACE} svc/${RELEASE_NAME}-frontend 8080:80"
echo "  Then open: http://localhost:8080"
echo ""
echo "Environment variables:"
echo "  BACKEND_TAG=${BACKEND_TAG}  (default: 0.5.10)"
echo "  FRONTEND_TAG=${FRONTEND_TAG}  (default: 0.5.11)"
echo ""

