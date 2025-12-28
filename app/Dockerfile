FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
# We're building from the app/ directory, so we need to create the app/ subdirectory
# to match the import structure (from app.main import ...)
COPY . /app/app/

# Create non-root user
RUN useradd -m -u 1000 kubefreezer && \
    chown -R kubefreezer:kubefreezer /app

USER kubefreezer

# Set PYTHONPATH so Python can find the app module
ENV PYTHONPATH=/app

# Expose port (HTTPS for webhook - Kubernetes requires HTTPS)
EXPOSE 8443

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; import ssl; ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE; urllib.request.urlopen('https://localhost:8443/health', context=ctx)"

# Run application with HTTPS (required for Kubernetes webhooks)
# Now the structure is /app/app/main.py, so we can use app.main:app
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8443", "--ssl-keyfile", "/etc/certs/tls.key", "--ssl-certfile", "/etc/certs/tls.crt"]

