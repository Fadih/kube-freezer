#!/bin/bash
set -e

# Generate API key for KubeFreezer
# Usage: ./scripts/generate-api-key.sh <key-name> [prefix]

KEY_NAME="${1:-user}"
PREFIX="${2:-kf}"
NAMESPACE="${NAMESPACE:-kube-freezer}"

if [ -z "$KEY_NAME" ]; then
    echo "Usage: $0 <key-name> [prefix]"
    echo "Example: $0 admin"
    echo "Example: $0 operator kf"
    exit 1
fi

# Generate secure random key
# Format: <prefix>-<key-name>-<random-hex>
RANDOM_HEX=$(openssl rand -hex 16)
API_KEY="${PREFIX}-${KEY_NAME}-${RANDOM_HEX}"
CONFIGMAP_KEY="api_key_${KEY_NAME}"

echo "🔑 Generated API Key"
echo "==================="
echo ""
echo "Key Name: ${CONFIGMAP_KEY}"
echo "API Key:  ${API_KEY}"
echo ""
echo "📋 To add to Secret:"
echo ""
echo "# Create new Secret or add to existing:"
echo "kubectl create secret generic kube-freezer-api-keys \\"
echo "  --from-literal=${CONFIGMAP_KEY}=\"${API_KEY}\" \\"
echo "  -n ${NAMESPACE} \\"
echo "  --dry-run=client -o yaml | kubectl apply -f -"
echo ""
echo "# Or update existing Secret:"
echo "API_KEY_B64=\$$(echo -n ${API_KEY} | base64); \\"
echo "kubectl patch secret kube-freezer-api-keys \\"
echo "  -n ${NAMESPACE} \\"
echo "  --type='json' \\"
echo "  -p \"[{\\\"op\\\": \\\"replace\\\", \\\"path\\\": \\\"/data/${CONFIGMAP_KEY}\\\", \\\"value\\\":\\\"\$$API_KEY_B64\\\"}]\""
echo ""
echo "🔄 After adding, restart backend pods to load the key:"
echo ""
echo "kubectl rollout restart deployment/kube-freezer-backend -n ${NAMESPACE}"
echo ""
echo "🧪 Test the key:"
echo ""
echo "curl -k -H \"Authorization: Bearer ${API_KEY}\" \\"
echo "  https://localhost:8443/api/v1/freeze/status"
echo ""
echo "⚠️  Save this key securely - it won't be shown again!"

