.PHONY: help build build-frontend build-backend test install clean certs namespace venv local-run local-test compile frontend-install frontend-dev frontend-build frontend-test generate-api-key

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Image tags
BACKEND_IMAGE := fadihussien/kubefreezer
BACKEND_TAG := 0.3.12
FRONTEND_IMAGE := fadihussien/kubefreezer-ui
FRONTEND_TAG := 0.3.12

build-backend: ## Build backend Docker image
	docker build -t $(BACKEND_IMAGE):$(BACKEND_TAG) -f app/Dockerfile app/

build-frontend: ## Build frontend Docker image
	@echo "Building frontend Docker image..."
	cd frontend && docker build -t $(FRONTEND_IMAGE):$(FRONTEND_TAG) .

build: build-backend build-frontend ## Build both backend and frontend Docker images

docker-push-backend: build-backend ## Build and push backend Docker image
	docker push $(BACKEND_IMAGE):$(BACKEND_TAG)

docker-push-frontend: build-frontend ## Build and push frontend Docker image
	docker push $(FRONTEND_IMAGE):$(FRONTEND_TAG)

docker-push: docker-push-backend docker-push-frontend ## Build and push both Docker images

test: ## Run tests
	@echo "TODO: Add tests"
	# pytest tests/

namespace: ## Create namespace
	@echo "Creating namespace if it doesn't exist..."
	@kubectl create namespace kube-freezer --dry-run=client -o yaml | kubectl apply -f -

generate-api-key: ## Generate a new API key (usage: make generate-api-key KEY_NAME=admin)
	@if [ -z "$(KEY_NAME)" ]; then \
		echo "❌ Error: KEY_NAME is required"; \
		echo "Usage: make generate-api-key KEY_NAME=admin"; \
		echo "Example: make generate-api-key KEY_NAME=operator"; \
		exit 1; \
	fi
	@echo "🔑 Generating API key for: $(KEY_NAME)"
	@./scripts/generate-api-key.sh $(KEY_NAME)
	@echo ""
	@echo "📋 To add the key to the Secret, run the command shown above."

certs: namespace ## Generate TLS certificates (required for webhook - Kubernetes mandates HTTPS)
	@echo "🔐 Generating TLS certificates for webhook..."
	@SERVICE_NAME=kube-freezer-backend ./scripts/generate-certs.sh
	@echo ""
	@echo "📋 Updating ValidatingWebhookConfiguration with CA bundle..."
	@CA_BUNDLE=$$(cat certs/tls.crt | base64 | tr -d '\n'); \
	kubectl patch validatingwebhookconfiguration kube-freezer \
		--type='json' \
		-p="[{\"op\": \"replace\", \"path\": \"/webhooks/0/clientConfig/caBundle\", \"value\":\"$$CA_BUNDLE\"}]" 2>/dev/null || \
		echo "⚠️  Warning: ValidatingWebhookConfiguration not found. Run 'make install' first, then 'make certs'."

install: namespace ## Install KubeFreezer with Helm
	@echo "Installing KubeFreezer with Helm..."
	@echo "Deleting existing Secret if present (will be recreated by Helm)..."
	@kubectl delete secret kube-freezer-tls -n kube-freezer --ignore-not-found=true || true
	helm install kube-freezer ./helm/kube-freezer \
		--namespace kube-freezer \
		--set createNamespace=false \
		--set backend.image.tag=$(BACKEND_TAG) \
		--set frontend.image.tag=$(FRONTEND_TAG) \
		--set backend.enabled=true \
		--set frontend.enabled=true
	@echo ""
	@echo "🔐 Generating TLS certificates and updating webhook configuration..."
	@SERVICE_NAME=kube-freezer-backend ./scripts/generate-certs.sh
	@echo ""
	@echo "📋 Updating ValidatingWebhookConfiguration with CA bundle..."
	@CA_BUNDLE=$$(cat certs/tls.crt | base64 | tr -d '\n'); \
	kubectl patch validatingwebhookconfiguration kube-freezer \
		--type='json' \
		-p="[{\"op\": \"replace\", \"path\": \"/webhooks/0/clientConfig/caBundle\", \"value\":\"$$CA_BUNDLE\"}]" || \
		(echo "⚠️  Warning: Failed to update ValidatingWebhookConfiguration. Run manually:" && \
		 echo "kubectl patch validatingwebhookconfiguration kube-freezer --type='json' -p='[{\"op\": \"replace\", \"path\": \"/webhooks/0/clientConfig/caBundle\", \"value\":\"$$CA_BUNDLE\"}]'")
	@echo ""
	@echo "📋 Creating schedules ConfigMap (NOT managed by Helm)..."
	@if ! kubectl get configmap kube-freezer-schedules -n kube-freezer &>/dev/null; then \
		kubectl create configmap kube-freezer-schedules \
			--from-literal=schedules="[]" \
			-n kube-freezer \
			--dry-run=client -o yaml | kubectl apply -f -; \
		kubectl label configmap kube-freezer-schedules \
			-n kube-freezer \
			app.kubernetes.io/name=kube-freezer \
			app.kubernetes.io/component=schedules \
			app.kubernetes.io/managed-by=kubefreezer --overwrite; \
		echo "   ✅ Created schedules ConfigMap (kube-freezer-schedules)"; \
		echo "   This ConfigMap is NOT managed by Helm and will persist through upgrades"; \
	else \
		echo "   Schedules ConfigMap already exists, skipping creation."; \
	fi
	@echo ""
	@echo "📋 Creating history ConfigMap (NOT managed by Helm)..."
	@if ! kubectl get configmap kube-freezer-history -n kube-freezer &>/dev/null; then \
		kubectl create configmap kube-freezer-history \
			--from-literal=events="[]" \
			-n kube-freezer \
			--dry-run=client -o yaml | kubectl apply -f -; \
		kubectl label configmap kube-freezer-history \
			-n kube-freezer \
			app.kubernetes.io/name=kube-freezer \
			app.kubernetes.io/component=history \
			app.kubernetes.io/managed-by=kubefreezer --overwrite; \
		echo "   ✅ Created history ConfigMap (kube-freezer-history)"; \
		echo "   This ConfigMap is NOT managed by Helm and will persist through upgrades"; \
	else \
		echo "   History ConfigMap already exists, skipping creation."; \
	fi
	@echo ""
	@echo "🔑 Generating default API key for admin user..."
	@if ! kubectl get secret kube-freezer-api-keys -n kube-freezer &>/dev/null; then \
		API_KEY=$$(openssl rand -hex 16); \
		FULL_KEY="kf-admin-$$API_KEY"; \
		echo "   Generated API key: $$FULL_KEY"; \
		kubectl create secret generic kube-freezer-api-keys \
			--from-literal=api_key_admin="$$FULL_KEY" \
			-n kube-freezer \
			--dry-run=client -o yaml | kubectl apply -f -; \
		echo ""; \
		echo "✅ API key created and stored in Secret: kube-freezer-api-keys"; \
		echo "   Key: $$FULL_KEY"; \
		echo "   ⚠️  Save this key securely - it won't be shown again!"; \
		echo ""; \
		echo "   To view the key later:"; \
		echo "     kubectl get secret kube-freezer-api-keys -n kube-freezer -o jsonpath='{.data.api_key_admin}' | base64 -d && echo"; \
		echo ""; \
	else \
		echo "   Secret kube-freezer-api-keys already exists, skipping key generation."; \
		echo "   To generate a new key, run: make generate-api-key KEY_NAME=admin"; \
	fi
	@echo ""
	@echo "⏳ Waiting for pods to be ready..."
	@kubectl wait --for=condition=ready pod \
		-l app.kubernetes.io/name=kube-freezer \
		-n kube-freezer \
		--timeout=120s || echo "⚠️  Warning: Some pods may not be ready yet"
	@echo ""
	@echo "✅ Installation complete!"
	@echo ""
	@echo "To access the UI:"
	@echo "  kubectl port-forward -n kube-freezer svc/kube-freezer-frontend 8080:80"
	@echo "  Then open: http://localhost:8080"
	@echo ""
	@echo "To get your API key:"
	@echo "  kubectl get secret kube-freezer-api-keys -n kube-freezer -o jsonpath='{.data.api_key_admin}' | base64 -d && echo"

upgrade: ## Upgrade KubeFreezer with Helm
	@echo "📦 Upgrading KubeFreezer with Helm..."
	@echo "⚠️  Note: Helm may overwrite the TLS Secret with empty values during upgrade."
	@echo "   We will regenerate and update it immediately after upgrade."
	@echo ""
	@echo "🔧 Temporarily setting webhook failurePolicy to Ignore to allow upgrade..."
	@kubectl patch validatingwebhookconfiguration kube-freezer --type='json' \
		-p='[{"op": "replace", "path": "/webhooks/0/failurePolicy", "value":"Ignore"}]' \
		2>/dev/null || true
	@echo ""
	@helm upgrade kube-freezer ./helm/kube-freezer \
		--namespace kube-freezer \
		--set createNamespace=false \
		--set certificate.useCertManager=false \
		--set backend.image.tag=$(BACKEND_TAG) \
		--set frontend.image.tag=$(FRONTEND_TAG) \
		--set backend.enabled=true \
		--set frontend.enabled=true
	@echo ""
	@echo "🔧 Restoring webhook failurePolicy to Fail..."
	@kubectl patch validatingwebhookconfiguration kube-freezer --type='json' \
		-p='[{"op": "replace", "path": "/webhooks/0/failurePolicy", "value":"Fail"}]' \
		2>/dev/null || true
	@echo ""
	@echo "🔐 Regenerating TLS certificates and updating Secret (Helm may have cleared it)..."
	@SERVICE_NAME=kube-freezer-backend ./scripts/generate-certs.sh
	@echo ""
	@echo "📋 Updating ValidatingWebhookConfiguration with CA bundle..."
	@CA_BUNDLE=$$(cat certs/tls.crt | base64 | tr -d '\n'); \
	kubectl patch validatingwebhookconfiguration kube-freezer \
		--type='json' \
		-p="[{\"op\": \"replace\", \"path\": \"/webhooks/0/clientConfig/caBundle\", \"value\":\"$$CA_BUNDLE\"}]" || \
		(echo "⚠️  Warning: Failed to update ValidatingWebhookConfiguration. Run manually:" && \
		 echo "kubectl patch validatingwebhookconfiguration kube-freezer --type='json' -p='[{\"op\": \"replace\", \"path\": \"/webhooks/0/clientConfig/caBundle\", \"value\":\"$$CA_BUNDLE\"}]'")
	@echo ""
	@echo "✅ Upgrade complete! Waiting for pods to be ready..."
	@kubectl wait --for=condition=ready pod \
		-l app.kubernetes.io/name=kube-freezer \
		-n kube-freezer \
		--timeout=120s || echo "⚠️  Warning: Some pods may not be ready yet"

uninstall: ## Uninstall KubeFreezer and remove all resources including namespace
	@echo "🗑️  Uninstalling KubeFreezer..."
	@echo ""
	@echo "Step 1: Deleting ValidatingWebhookConfiguration (to prevent blocking)..."
	@kubectl delete validatingwebhookconfiguration kube-freezer --ignore-not-found=true || true
	@echo ""
	@echo "Step 2: Uninstalling Helm release..."
	@helm uninstall kube-freezer --namespace kube-freezer || true
	@echo ""
	@echo "Step 3: Deleting all remaining Secrets (including manually created)..."
	@kubectl delete secret kube-freezer-tls -n kube-freezer --ignore-not-found=true || true
	@kubectl delete secret kube-freezer-api-keys -n kube-freezer --ignore-not-found=true || true
	@echo "   Deleted: kube-freezer-tls, kube-freezer-api-keys"
	@echo ""
	@echo "Step 4: Deleting all remaining ConfigMaps (including manually created)..."
	@kubectl delete configmap kube-freezer-config -n kube-freezer --ignore-not-found=true || true
	@kubectl delete configmap kube-freezer-templates -n kube-freezer --ignore-not-found=true || true
	@kubectl delete configmap kube-freezer-notifications -n kube-freezer --ignore-not-found=true || true
	@kubectl delete configmap kube-freezer-exemptions -n kube-freezer --ignore-not-found=true || true
	@kubectl delete configmap kube-freezer-schedules -n kube-freezer --ignore-not-found=true || true
	@kubectl delete configmap kube-freezer-history -n kube-freezer --ignore-not-found=true || true
	@echo "   Deleted: kube-freezer-config, kube-freezer-templates, kube-freezer-notifications, kube-freezer-exemptions, kube-freezer-schedules, kube-freezer-history"
	@echo ""
	@echo "Step 5: Deleting namespace (this will remove all remaining resources)..."
	@kubectl delete namespace kube-freezer --ignore-not-found=true || true
	@echo ""
	@echo "✅ Uninstall complete!"
	@echo ""
	@echo "Note: Local certificate files in certs/ directory are not removed."
	@echo "      Run 'make clean' to remove local build artifacts."

lint: ## Lint code
	@echo "TODO: Add linting"
	# flake8 app/
	# pylint app/

clean: ## Clean build artifacts
	rm -rf certs/
	rm -rf __pycache__/
	rm -rf venv/
	rm -rf frontend/node_modules/
	rm -rf frontend/dist/
	find . -type d -name __pycache__ -exec rm -r {} +
	find . -type f -name "*.pyc" -delete


venv: ## Create Python virtual environment
	@echo "Creating virtual environment..."
	@python3 -m venv venv
	@echo "Virtual environment created. Activate with: source venv/bin/activate"

compile: ## Compile all Python files to check for syntax errors
	@echo "Compiling Python files..."
	@find app -name "*.py" -type f ! -path "*/__pycache__/*" -exec python3 -m py_compile {} \; 2>&1 | grep -v "^$$" || echo "✓ All Python files compiled successfully"

local-install: venv ## Install dependencies in virtual environment
	@echo "Installing dependencies..."
	@. venv/bin/activate && pip install --upgrade pip && pip install -r app/requirements.txt
	@echo "✓ Dependencies installed"

local-test: local-install compile ## Test application locally (compile + import check)
	@echo "Testing imports..."
	@. venv/bin/activate && python3 -c "import sys; sys.path.insert(0, 'app'); from app.main import app; print('✓ All imports successful')" || (echo "✗ Import test failed" && exit 1)
	@echo "✓ Local test passed"

local-run: local-install ## Run application locally (for testing)
	@echo "Starting KubeFreezer locally..."
	@echo "Note: This requires Kubernetes cluster access (kubeconfig)"
	@echo "Running on http://localhost:8080 (not HTTPS for local dev)"
	@echo "Press Ctrl+C to stop"
	@. venv/bin/activate && PYTHONPATH=. python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload || \
		(echo "Note: If this fails, ensure you have a valid kubeconfig")

local: local-test ## Full local test (venv + install + compile + test)
	@echo "✓ Local development environment ready"
	@echo ""
	@echo "To run locally:"
	@echo "  source venv/bin/activate"
	@echo "  PYTHONPATH=. python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8080"

# Frontend commands
frontend-install: ## Install frontend dependencies
	@echo "Installing frontend dependencies..."
	cd frontend && npm install
	@echo "✓ Frontend dependencies installed (package-lock.json generated)"

frontend-dev: frontend-install ## Run frontend development server
	@echo "Starting frontend development server..."
	@echo "Frontend: http://localhost:5173"
	@echo "Backend API will be proxied to https://localhost:8443"
	cd frontend && npm run dev

frontend-build: frontend-install ## Build frontend for production
	@echo "Building frontend for production..."
	cd frontend && npm run build
	@echo "✓ Frontend built successfully (output: frontend/dist/)"

frontend-test: frontend-install ## Test frontend (lint, type check)
	@echo "Testing frontend..."
	cd frontend && npm run lint || echo "⚠️  Linting issues found"
	@echo "✓ Frontend test completed"

frontend-preview: frontend-build ## Preview production build locally
	@echo "Previewing production build..."
	cd frontend && npm run preview

# Combined development
dev-backend: local-install ## Run backend in development mode
	@echo "Starting backend on http://localhost:8080..."
	@. venv/bin/activate && PYTHONPATH=. python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

dev-frontend: frontend-install ## Run frontend in development mode
	@echo "Starting frontend on http://localhost:5173..."
	cd frontend && npm run dev

dev: ## Run both backend and frontend in development (requires 2 terminals)
	@echo "To run both frontend and backend:"
	@echo "  Terminal 1: make dev-backend"
	@echo "  Terminal 2: make dev-frontend"
	@echo ""
	@echo "Or use: make -j2 dev-backend dev-frontend"
