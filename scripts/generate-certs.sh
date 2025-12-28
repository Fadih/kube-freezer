#!/bin/bash
set -e

# Generate TLS certificates for KubeFreezer webhook
# Kubernetes webhooks REQUIRE HTTPS - this is mandatory

NAMESPACE="${NAMESPACE:-kube-freezer}"
SERVICE_NAME="${SERVICE_NAME:-kube-freezer-backend}"
SECRET_NAME="${SECRET_NAME:-kube-freezer-tls}"
CERT_DIR="${CERT_DIR:-./certs}"

# Create certs directory
mkdir -p "${CERT_DIR}"

echo "🔐 Generating TLS certificates for webhook..."

# Generate private key
openssl genrsa -out "${CERT_DIR}/tls.key" 2048

# Generate certificate signing request
openssl req -new -key "${CERT_DIR}/tls.key" \
  -out "${CERT_DIR}/tls.csr" \
  -subj "/CN=${SERVICE_NAME}.${NAMESPACE}.svc"

# Generate self-signed certificate with proper SANs
openssl x509 -req -in "${CERT_DIR}/tls.csr" \
  -signkey "${CERT_DIR}/tls.key" \
  -out "${CERT_DIR}/tls.crt" \
  -days 365 \
  -extensions v3_req \
  -extfile <(
    cat <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req

[v3_req]
basicConstraints = CA:TRUE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment, keyCertSign
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${SERVICE_NAME}
DNS.2 = ${SERVICE_NAME}.${NAMESPACE}
DNS.3 = ${SERVICE_NAME}.${NAMESPACE}.svc
DNS.4 = ${SERVICE_NAME}.${NAMESPACE}.svc.cluster.local
EOF
  )

# Create/update Kubernetes Secret
echo "📦 Updating Kubernetes Secret..."
# Base64 encode the certificate and key
TLS_CRT=$(cat "${CERT_DIR}/tls.crt" | base64 | tr -d '\n')
TLS_KEY=$(cat "${CERT_DIR}/tls.key" | base64 | tr -d '\n')

# Check if Secret exists
if kubectl get secret "${SECRET_NAME}" -n "${NAMESPACE}" &>/dev/null; then
  # Secret exists - patch it to preserve Helm labels
  echo "   Patching existing Secret (preserving Helm metadata)..."
  kubectl patch secret "${SECRET_NAME}" \
    --namespace="${NAMESPACE}" \
    --type='json' \
    -p="[{\"op\": \"replace\", \"path\": \"/data/tls.crt\", \"value\":\"${TLS_CRT}\"}, {\"op\": \"replace\", \"path\": \"/data/tls.key\", \"value\":\"${TLS_KEY}\"}]"
else
  # Secret doesn't exist - create it
  echo "   Creating new Secret..."
  kubectl create secret tls "${SECRET_NAME}" \
    --namespace="${NAMESPACE}" \
    --cert="${CERT_DIR}/tls.crt" \
    --key="${CERT_DIR}/tls.key" \
    --dry-run=client -o yaml | kubectl apply -f -
fi

# Extract CA bundle for ValidatingWebhookConfiguration
CA_BUNDLE=$(cat "${CERT_DIR}/tls.crt" | base64 | tr -d '\n')

echo ""
echo "✅ Certificate generated successfully!"
echo ""
echo "📋 CA Bundle (base64):"
echo "${CA_BUNDLE}"
echo ""
echo "🔧 To update ValidatingWebhookConfiguration, run:"
echo "kubectl patch validatingwebhookconfiguration ${SERVICE_NAME} \\"
echo "  --type='json' \\"
echo "  -p='[{\"op\": \"replace\", \"path\": \"/webhooks/0/clientConfig/caBundle\", \"value\":\"${CA_BUNDLE}\"}]'"
echo ""

