"""
KubeFreezer - Kubernetes Admission Controller for Deployment Freeze Management
"""
import logging
import sys
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.admission.webhook import handle_admission_review
from app.api.routes import (
    router as api_router,
    set_config_loader,
    set_exemption_manager,
    set_history_tracker,
    set_notification_manager,
    set_audit_logger,
    set_template_engine
)
from app.config.loader import ConfigLoader
from app.exemptions.manager import ExemptionManager
from app.history.tracker import HistoryTracker
from app.notifications.manager import NotificationManager
from app.audit.logger import AuditLogger, FileAuditSink
from app.templates.engine import TemplateEngine
from app.utils.logging import setup_logging
from app.utils.kubernetes import get_k8s_client
from app.metrics.collector import get_metrics, get_metrics_content_type
import os

# Setup logging (JSON format by default, can be disabled with LOG_FORMAT=text)
import os
log_format = os.getenv("LOG_FORMAT", "json").lower()
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"), json_format=(log_format == "json"))
logger = logging.getLogger(__name__)

# Global managers
config_loader: ConfigLoader = None
exemption_manager: ExemptionManager = None
history_tracker: HistoryTracker = None
notification_manager: NotificationManager = None
audit_logger: AuditLogger = None
template_engine: TemplateEngine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global config_loader
    
    # Startup
    logger.info("Starting KubeFreezer...")
    global config_loader, exemption_manager, history_tracker
    global notification_manager, audit_logger, template_engine
    
    try:
        # Initialize config loader with retry logic
        config_loader = ConfigLoader()
        try:
            await config_loader.start()
        except Exception as e:
            logger.warning(f"Config loader startup had issues: {e}. Continuing with defaults...")
            # Continue anyway - config loader will retry in background
        set_config_loader(config_loader)
        config = config_loader.get_config()
        
        # Get k8s client with retry
        k8s_client = None
        try:
            k8s_client = get_k8s_client()
        except Exception as e:
            logger.warning(f"Could not get Kubernetes client: {e}. Some features may not work.")
            # Continue anyway - some features won't work but app can still serve webhook
        
        # Initialize exemption manager
        exemption_manager = ExemptionManager(storage_backend="configmap")
        exemption_manager.set_k8s_client(k8s_client)
        set_exemption_manager(exemption_manager)
        
        # Initialize history tracker
        history_tracker = HistoryTracker(max_events=1000, storage_backend="configmap")
        history_tracker.set_k8s_client(k8s_client)
        # Load existing history from ConfigMap
        if k8s_client:
            try:
                await history_tracker._load_from_configmap()
                # Ensure ConfigMap exists (create empty one if needed)
                try:
                    await history_tracker.save_to_configmap()
                    logger.info("History ConfigMap initialized/verified")
                except Exception as save_error:
                    logger.warning(f"Could not initialize history ConfigMap: {save_error}")
            except Exception as e:
                logger.warning(f"Could not load history from ConfigMap: {e}")
                # Try to create empty ConfigMap
                if k8s_client:
                    try:
                        await history_tracker.save_to_configmap()
                    except Exception:
                        pass  # Will be created on first event
        set_history_tracker(history_tracker)
        
        # Initialize notification manager (Phase 4)
        try:
            if k8s_client:
                from kubernetes import client
                v1 = client.CoreV1Api()
                namespace = os.getenv("NAMESPACE", "kube-freezer")
                try:
                    notif_cm = v1.read_namespaced_config_map("kube-freezer-notifications", namespace)
                    notif_config = {
                        "enabled": notif_cm.data.get("enabled", "false").lower() == "true",
                        "providers": notif_cm.data.get("providers", "[]")
                    }
                    notification_manager = NotificationManager(notif_config)
                except Exception:
                    notification_manager = NotificationManager({"enabled": False})
            else:
                notification_manager = NotificationManager({"enabled": False})
        except Exception as e:
            logger.warning(f"Could not initialize notification manager: {e}")
            notification_manager = NotificationManager({"enabled": False})
        
        # Initialize audit logger (Phase 4)
        audit_logger = AuditLogger(enabled=True)
        # Add file sink
        audit_file = os.getenv("AUDIT_LOG_FILE", "/var/log/kubefreezer/audit.log")
        try:
            os.makedirs(os.path.dirname(audit_file), exist_ok=True)
            audit_logger.add_sink(FileAuditSink(audit_file))
        except Exception as e:
            logger.warning(f"Could not setup audit file sink: {e}")
        
        # Initialize template engine (Phase 4)
        template_engine = TemplateEngine()
        # Load custom templates from config if available
        try:
            if k8s_client:
                from kubernetes import client
                v1 = client.CoreV1Api()
                namespace = os.getenv("NAMESPACE", "kube-freezer")
                try:
                    template_cm = v1.read_namespaced_config_map("kube-freezer-templates", namespace)
                    template_config = {"templates": template_cm.data.get("templates", "")}
                    template_engine.load_templates_from_config(template_config)
                    logger.info(f"Loaded {len(template_engine.templates)} templates from ConfigMap")
                except Exception as e:
                    logger.warning(f"Could not load templates from ConfigMap: {e}", exc_info=True)
                    # No templates configured - templates must be added via ConfigMap
        except Exception as e:
            logger.warning(f"Could not initialize template engine: {e}", exc_info=True)
        set_template_engine(template_engine)
        
        # Set global managers for API routes
        set_notification_manager(notification_manager)
        set_audit_logger(audit_logger)
        
        # Start background cleanup task for exemptions
        import asyncio
        asyncio.create_task(_cleanup_exemptions_loop(exemption_manager))
        
        logger.info("KubeFreezer started successfully")
    except Exception as e:
        logger.error(f"Failed to start KubeFreezer: {e}", exc_info=True)
        # Don't exit - let the app start anyway, it will retry in background
        logger.warning("Continuing with limited functionality. Will retry connections in background.")
    
    yield
    
    # Shutdown
    logger.info("Shutting down KubeFreezer...")
    if config_loader:
        await config_loader.stop()


async def _cleanup_exemptions_loop(exemption_manager: ExemptionManager):
    """Background task to clean up expired exemptions"""
    import asyncio
    while True:
        try:
            await asyncio.sleep(300)  # Run every 5 minutes
            cleaned = await exemption_manager.cleanup_expired()
            if cleaned > 0:
                logger.info(f"Cleaned up {cleaned} expired exemptions")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error cleaning up exemptions: {e}", exc_info=True)


# Create FastAPI app
app = FastAPI(
    title="KubeFreezer",
    description="Kubernetes admission controller for deployment freeze management",
    version="0.1.0",
    lifespan=lifespan
)

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Development
        "http://localhost:8080",  # Port-forward
        "http://kube-freezer-frontend",  # Kubernetes service
        "http://kube-freezer-frontend.kube-freezer.svc",  # Full service name
        "http://kube-freezer-frontend.kube-freezer.svc.cluster.local",  # FQDN
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health():
    """Liveness probe endpoint"""
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    """Readiness probe endpoint"""
    global config_loader
    if config_loader and config_loader.is_ready():
        return {"status": "ready"}
    else:
        raise HTTPException(status_code=503, detail="Not ready")


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    from fastapi.responses import Response
    return Response(
        content=get_metrics(),
        media_type=get_metrics_content_type()
    )


@app.post("/admission")
async def admission(request: Request):
    """Admission webhook endpoint"""
    try:
        body = await request.json()
        logger.debug(f"Received admission request: {body.get('kind')}")
        
        response = await handle_admission_review(body, config_loader)
        return response
    except Exception as e:
        logger.error(f"Error processing admission request: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "apiVersion": "admission.k8s.io/v1",
                "kind": "AdmissionReview",
                "response": {
                    "uid": body.get("request", {}).get("uid", ""),
                    "allowed": False,
                    "status": {
                        "code": 500,
                        "message": f"Internal server error: {str(e)}"
                    }
                }
            }
        )


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8443,
        log_config=None,  # Use our custom logging
        ssl_keyfile="/etc/certs/tls.key",
        ssl_certfile="/etc/certs/tls.crt"
    )

