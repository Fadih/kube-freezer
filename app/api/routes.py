"""REST API routes"""
import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from app.config.loader import ConfigLoader
from app.freeze.evaluator import is_freeze_active
from app.utils.kubernetes import get_k8s_client
from app.metrics.collector import (
    record_api_request,
    record_config_reload_success,
    record_config_reload_error
)
from app.exemptions.manager import ExemptionManager, Exemption
from app.history.tracker import HistoryTracker
from app.api.auth import verify_token, optional_auth
from app.api.ratelimit import check_rate_limit
from app.templates.engine import TemplateEngine
from app.dryrun.evaluator import evaluate_dry_run

logger = logging.getLogger(__name__)

router = APIRouter()


# Global references (set by main.py)
_config_loader: ConfigLoader = None
_exemption_manager: ExemptionManager = None
_history_tracker: HistoryTracker = None
_notification_manager = None
_audit_logger = None
_template_engine: TemplateEngine = None

def set_notification_manager(manager):
    """Set notification manager"""
    global _notification_manager
    _notification_manager = manager

def get_notification_manager():
    """Get notification manager"""
    return _notification_manager

def set_audit_logger(logger):
    """Set audit logger"""
    global _audit_logger
    _audit_logger = logger

def get_audit_logger():
    """Get audit logger"""
    return _audit_logger

def set_template_engine(engine: TemplateEngine):
    """Set template engine"""
    global _template_engine
    _template_engine = engine

def get_template_engine() -> TemplateEngine:
    """Get template engine"""
    if _template_engine is None:
        raise HTTPException(status_code=503, detail="Template engine not initialized")
    return _template_engine

def set_config_loader(loader: ConfigLoader):
    """Set the global config loader"""
    global _config_loader
    _config_loader = loader

def get_config_loader() -> ConfigLoader:
    """Dependency to get config loader"""
    if _config_loader is None:
        raise HTTPException(status_code=503, detail="Config loader not initialized")
    return _config_loader

def set_exemption_manager(manager: ExemptionManager):
    """Set the global exemption manager"""
    global _exemption_manager
    _exemption_manager = manager

def get_exemption_manager() -> ExemptionManager:
    """Dependency to get exemption manager"""
    if _exemption_manager is None:
        raise HTTPException(status_code=503, detail="Exemption manager not initialized")
    return _exemption_manager

def set_history_tracker(tracker: HistoryTracker):
    """Set the global history tracker"""
    global _history_tracker
    _history_tracker = tracker

def get_history_tracker() -> HistoryTracker:
    """Dependency to get history tracker"""
    if _history_tracker is None:
        raise HTTPException(status_code=503, detail="History tracker not initialized")
    return _history_tracker


class FreezeEnableRequest(BaseModel):
    until: str  # ISO 8601 timestamp
    reason: str = "Manual freeze enabled"
    namespaces: List[str] = []


class FreezeDisableRequest(BaseModel):
    reason: str = "Manual freeze disabled"


class ExemptionCreateRequest(BaseModel):
    namespace: str
    duration_minutes: int
    reason: str
    approved_by: str
    resource_name: Optional[str] = None


class ScheduleRemoveRequest(BaseModel):
    reason: Optional[str] = "Schedule removed via API"


@router.get("/freeze/status")
async def get_freeze_status(
    request: Request,
    config_loader: ConfigLoader = Depends(get_config_loader)
):
    """Get current freeze status"""
    start_time = time.time()
    try:
        config = config_loader.get_config()
        freeze_active, freeze_window = is_freeze_active(config)
        
        response = {
            "active": freeze_active,
            "freeze_enabled": config.get("freeze_enabled", False),
            "freeze_until": None,
            "freeze_message": config.get("freeze_message", ""),
            "remaining": None,
            "freeze_window": freeze_window,
            "schedules": []
        }
        
        # Check schedules
        freeze_schedules = config.get("freeze_schedule", [])
        if freeze_schedules:
            from app.freeze.schedule import get_active_schedules
            active_schedules = get_active_schedules(freeze_schedules)
            response["schedules"] = []
            for s in active_schedules:
                # Order: name, start, end, cron, namespaces, message
                schedule_info = {
                    "name": s.get("name"),
                    "start": s["start"].isoformat() if isinstance(s.get("start"), datetime) else str(s.get("start", "")),
                    "end": s["end"].isoformat() if isinstance(s.get("end"), datetime) else str(s.get("end", "")),
                    "cron": s.get("cron", ""),
                }
                
                if s.get("namespaces"):
                    schedule_info["namespaces"] = s["namespaces"]
                
                if s.get("message"):
                    schedule_info["message"] = s.get("message")
                
                response["schedules"].append(schedule_info)
        
        freeze_until = config.get("freeze_until")
        if freeze_until:
            if isinstance(freeze_until, str):
                freeze_until = datetime.fromisoformat(freeze_until.replace("Z", "+00:00"))
            
            if freeze_until.tzinfo is None:
                freeze_until = freeze_until.replace(tzinfo=timezone.utc)
            
            response["freeze_until"] = freeze_until.isoformat()
            
            if freeze_active:
                now = datetime.now(timezone.utc)
                remaining = freeze_until - now
                response["remaining"] = str(remaining)
        
        duration = time.time() - start_time
        record_api_request("/freeze/status", "GET", 200, duration)
        
        return {
            "success": True,
            "data": response,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/freeze/status", "GET", 500, duration)
        logger.error(f"Error getting freeze status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/freeze/enable")
async def enable_freeze(
    request: FreezeEnableRequest,
    http_request: Request,
    config_loader: ConfigLoader = Depends(get_config_loader),
    _: str = Depends(verify_token)  # Require authentication
):
    """Enable freeze by updating ConfigMap"""
    check_rate_limit(http_request)  # Check rate limit
    start_time = time.time()
    try:
        # Validate timestamp
        try:
            freeze_until = datetime.fromisoformat(request.until.replace("Z", "+00:00"))
            if freeze_until.tzinfo is None:
                freeze_until = freeze_until.replace(tzinfo=timezone.utc)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid timestamp format: {e}")
        
        # Update ConfigMap
        v1 = get_k8s_client()
        cm = v1.read_namespaced_config_map(
            name=config_loader.configmap_name,
            namespace=config_loader.namespace
        )
        
        # Update freeze settings
        cm.data["freeze_enabled"] = "true"
        cm.data["freeze_until"] = freeze_until.isoformat()
        if request.reason:
            cm.data["freeze_message"] = f"{request.reason} - Freeze until {freeze_until.isoformat()}"
        
        v1.patch_namespaced_config_map(
            name=config_loader.configmap_name,
            namespace=config_loader.namespace,
            body=cm
        )
        
        # Reload config
        try:
            await config_loader.load_config()
            record_config_reload_success()
        except Exception as reload_error:
            record_config_reload_error()
            logger.error(f"Error reloading config: {reload_error}")
        
        # Record history
        try:
            tracker = get_history_tracker()
            tracker.record_event(
                event_type="enabled",
                reason=request.reason,
                duration_minutes=int((freeze_until - datetime.now(timezone.utc)).total_seconds() / 60),
                triggered_by="api"
            )
            # Persist to ConfigMap
            await tracker.save_to_configmap()
        except Exception as hist_error:
            logger.warning(f"Failed to save history event: {hist_error}", exc_info=True)
            # Don't fail the request, but log the error
        
        # Send notification (Phase 4)
        notif_mgr = get_notification_manager()
        if notif_mgr:
            await notif_mgr.send_notification("freeze_enabled", {
                "freeze_window": "Manual Freeze",
                "until": freeze_until.isoformat(),
                "reason": request.reason,
                "namespace": ", ".join(request.namespaces) if request.namespaces else "All"
            })
        
        # Audit log (Phase 4)
        audit = get_audit_logger()
        if audit:
            from app.audit.logger import AuditActor, AuditResource
            actor = audit.create_actor("api-user", "system")
            resource = audit.create_resource("freeze_window", "Manual Freeze")
            await audit.log_event("freeze_enabled", actor, resource, "success", {
                "until": freeze_until.isoformat(),
                "reason": request.reason
            })
        
        logger.info(f"Freeze enabled until {freeze_until.isoformat()}: {request.reason}")
        
        duration = time.time() - start_time
        record_api_request("/freeze/enable", "POST", 200, duration)
        
        return {
            "success": True,
            "message": f"Freeze enabled until {freeze_until.isoformat()}",
            "data": {
                "freeze_until": freeze_until.isoformat(),
                "reason": request.reason
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/freeze/enable", "POST", 500, duration)
        logger.error(f"Error enabling freeze: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/freeze/disable")
async def disable_freeze(
    request: FreezeDisableRequest,
    http_request: Request,
    config_loader: ConfigLoader = Depends(get_config_loader),
    _: str = Depends(verify_token)  # Require authentication
):
    """Disable freeze by updating ConfigMap"""
    check_rate_limit(http_request)  # Check rate limit
    start_time = time.time()
    try:
        # Update ConfigMap
        v1 = get_k8s_client()
        cm = v1.read_namespaced_config_map(
            name=config_loader.configmap_name,
            namespace=config_loader.namespace
        )
        
        # Disable freeze
        cm.data["freeze_enabled"] = "false"
        if request.reason:
            cm.data["freeze_message"] = f"Freeze disabled: {request.reason}"
        
        v1.patch_namespaced_config_map(
            name=config_loader.configmap_name,
            namespace=config_loader.namespace,
            body=cm
        )
        
        # Reload config
        try:
            await config_loader.load_config()
            record_config_reload_success()
        except Exception as reload_error:
            record_config_reload_error()
            logger.error(f"Error reloading config: {reload_error}")
        
        # Record history
        try:
            tracker = get_history_tracker()
            tracker.record_event(
                event_type="disabled",
                reason=request.reason,
                triggered_by="api"
            )
            # Persist to ConfigMap
            await tracker.save_to_configmap()
        except Exception as hist_error:
            logger.warning(f"Failed to save history event: {hist_error}", exc_info=True)
            # Don't fail the request, but log the error
        
        # Send notification (Phase 4)
        notif_mgr = get_notification_manager()
        if notif_mgr:
            await notif_mgr.send_notification("freeze_disabled", {
                "reason": request.reason
            })
        
        # Audit log (Phase 4)
        audit = get_audit_logger()
        if audit:
            from app.audit.logger import AuditActor, AuditResource
            actor = audit.create_actor("api-user", "system")
            resource = audit.create_resource("freeze_window", "Manual Freeze")
            await audit.log_event("freeze_disabled", actor, resource, "success", {
                "reason": request.reason
            })
        
        logger.info(f"Freeze disabled: {request.reason}")
        
        duration = time.time() - start_time
        record_api_request("/freeze/disable", "POST", 200, duration)
        
        return {
            "success": True,
            "message": "Freeze disabled",
            "data": {
                "reason": request.reason
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/freeze/disable", "POST", 500, duration)
        logger.error(f"Error disabling freeze: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Exemptions API
@router.get("/freeze/exemptions")
async def list_exemptions(
    request: Request,
    namespace: Optional[str] = None,
    active_only: bool = False,
    exemption_manager: ExemptionManager = Depends(get_exemption_manager),
    _: str = Depends(verify_token)  # Require authentication
):
    """List temporary exemptions"""
    start_time = time.time()
    try:
        exemptions = await exemption_manager.list_exemptions(
            namespace=namespace,
            active_only=active_only
        )
        
        duration = time.time() - start_time
        record_api_request("/freeze/exemptions", "GET", 200, duration)
        
        return {
            "success": True,
            "data": [ex.to_dict() for ex in exemptions],
            "count": len(exemptions),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/freeze/exemptions", "GET", 500, duration)
        logger.error(f"Error listing exemptions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/freeze/exemptions")
async def create_exemption(
    request: ExemptionCreateRequest,
    http_request: Request,
    exemption_manager: ExemptionManager = Depends(get_exemption_manager),
    _: str = Depends(verify_token)  # Require authentication
):
    """Create a temporary exemption"""
    check_rate_limit(http_request)
    start_time = time.time()
    try:
        exemption = await exemption_manager.create_exemption(
            namespace=request.namespace,
            duration_minutes=request.duration_minutes,
            reason=request.reason,
            approved_by=request.approved_by,
            resource_name=request.resource_name
        )
        
        # Record history event
        try:
            tracker = get_history_tracker()
            resource_info = f"{request.namespace}"
            if request.resource_name:
                resource_info += f"/{request.resource_name}"
            
            tracker.record_event(
                event_type="exemption_created",
                reason=f"Exemption created: {request.reason} (approved by: {request.approved_by})",
                namespace=request.namespace,
                duration_minutes=request.duration_minutes,
                triggered_by="api"
            )
            await tracker.save_to_configmap()
        except Exception as hist_error:
            logger.warning(f"Failed to save history event: {hist_error}", exc_info=True)
        
        # Send notification (Phase 4)
        notif_mgr = get_notification_manager()
        if notif_mgr:
            await notif_mgr.send_notification("exemption_created", {
                "exemption_id": exemption.id,
                "namespace": request.namespace,
                "resource_name": request.resource_name,
                "duration_minutes": request.duration_minutes,
                "reason": request.reason,
                "approved_by": request.approved_by,
                "expires_at": exemption.expires_at.isoformat()
            })
        
        duration = time.time() - start_time
        record_api_request("/freeze/exemptions", "POST", 201, duration)
        
        return {
            "success": True,
            "data": exemption.to_dict(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/freeze/exemptions", "POST", 500, duration)
        logger.error(f"Error creating exemption: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/freeze/exemptions/{exemption_id}")
async def get_exemption(
    exemption_id: str,
    request: Request,
    exemption_manager: ExemptionManager = Depends(get_exemption_manager),
    _: str = Depends(verify_token)  # Require authentication
):
    """Get a specific exemption"""
    start_time = time.time()
    try:
        exemption = await exemption_manager.get_exemption(exemption_id)
        if not exemption:
            raise HTTPException(status_code=404, detail="Exemption not found")
        
        duration = time.time() - start_time
        record_api_request("/freeze/exemptions/{id}", "GET", 200, duration)
        
        return {
            "success": True,
            "data": exemption.to_dict(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/freeze/exemptions/{id}", "GET", 500, duration)
        logger.error(f"Error getting exemption: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/freeze/exemptions/{exemption_id}")
async def delete_exemption(
    exemption_id: str,
    http_request: Request,
    exemption_manager: ExemptionManager = Depends(get_exemption_manager),
    _: str = Depends(verify_token)  # Require authentication
):
    """Delete a temporary exemption"""
    check_rate_limit(http_request)
    start_time = time.time()
    try:
        # Get exemption details before deletion for history
        exemption = await exemption_manager.get_exemption(exemption_id)
        if not exemption:
            raise HTTPException(status_code=404, detail="Exemption not found")
        
        # Delete exemption
        deleted = await exemption_manager.delete_exemption(exemption_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Exemption not found")
        
        # Record history event
        try:
            tracker = get_history_tracker()
            tracker.record_event(
                event_type="exemption_deleted",
                reason=f"Exemption deleted (was for: {exemption.namespace}, reason: {exemption.reason})",
                namespace=exemption.namespace,
                triggered_by="api"
            )
            await tracker.save_to_configmap()
        except Exception as hist_error:
            logger.warning(f"Failed to save history event: {hist_error}", exc_info=True)
        
        duration = time.time() - start_time
        record_api_request("/freeze/exemptions/{id}", "DELETE", 200, duration)
        
        return {
            "success": True,
            "message": "Exemption deleted",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/freeze/exemptions/{id}", "DELETE", 500, duration)
        logger.error(f"Error deleting exemption: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Schedules API
@router.get("/freeze/schedules")
async def list_schedules(
    request: Request,
    config_loader: ConfigLoader = Depends(get_config_loader),
    _: str = Depends(verify_token)  # Require authentication
):
    """List all freeze schedules (from separate ConfigMap, NOT managed by Helm)"""
    start_time = time.time()
    try:
        # Load schedules from separate ConfigMap
        from app.utils.schedules import load_schedules
        schedules = load_schedules()
        
        duration = time.time() - start_time
        record_api_request("/freeze/schedules", "GET", 200, duration)
        
        return {
            "success": True,
            "data": schedules,
            "count": len(schedules),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/freeze/schedules", "GET", 500, duration)
        logger.error(f"Error listing schedules: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/freeze/schedules/{schedule_name}")
async def remove_schedule(
    schedule_name: str,
    http_request: Request,
    config_loader: ConfigLoader = Depends(get_config_loader),
    _: str = Depends(verify_token)  # Require authentication
):
    """Remove a specific freeze schedule (including template-applied schedules)"""
    check_rate_limit(http_request)
    start_time = time.time()
    try:
        # Parse request body for optional reason
        reason = "Schedule removed via API"
        try:
            body = await http_request.json()
            if body and isinstance(body, dict) and "reason" in body:
                reason = body.get("reason", reason)
        except Exception:
            pass  # No body or invalid JSON, use default reason
        
        # Remove schedule from separate ConfigMap (NOT managed by Helm)
        from app.utils.schedules import remove_schedule, load_schedules
        success = remove_schedule(schedule_name)
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Schedule '{schedule_name}' not found"
            )
        
        # Get remaining schedules count
        current_schedules = load_schedules()
        
        # Reload config
        try:
            await config_loader.load_config()
            record_config_reload_success()
        except Exception as reload_error:
            record_config_reload_error()
            logger.error(f"Error reloading config: {reload_error}")
        
        # Record history
        try:
            tracker = get_history_tracker()
            tracker.record_event(
                event_type="schedule_removed",
                reason=reason or f"Schedule '{schedule_name}' removed",
                triggered_by="api"
            )
            # Persist to ConfigMap
            await tracker.save_to_configmap()
        except Exception as hist_error:
            logger.warning(f"Failed to save history event: {hist_error}", exc_info=True)
            # Don't fail the request, but log the error
        
        # Send notification
        notif_mgr = get_notification_manager()
        if notif_mgr:
            await notif_mgr.send_notification("schedule_removed", {
                "schedule_name": schedule_name,
                "reason": reason
            })
        
        # Audit log
        audit = get_audit_logger()
        if audit:
            from app.audit.logger import AuditActor, AuditResource
            actor = audit.create_actor("api-user", "system")
            resource = audit.create_resource("freeze_schedule", schedule_name)
            await audit.log_event("schedule_removed", actor, resource, "success", {
                "schedule_name": schedule_name,
                "reason": reason
            })
        
        logger.info(f"Schedule '{schedule_name}' removed: {reason}")
        
        duration = time.time() - start_time
        record_api_request("/freeze/schedules/{name}", "DELETE", 200, duration)
        
        return {
            "success": True,
            "message": f"Schedule '{schedule_name}' removed",
            "data": {
                "schedule_name": schedule_name,
                "reason": reason,
                "remaining_schedules": len(current_schedules)
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/freeze/schedules/{name}", "DELETE", 500, duration)
        logger.error(f"Error removing schedule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# History API
@router.get("/freeze/history")
async def get_freeze_history(
    request: Request,
    event_type: Optional[str] = None,
    namespace: Optional[str] = None,
    limit: int = 100,
    history_tracker: HistoryTracker = Depends(get_history_tracker),
    _: str = Depends(verify_token)  # Require authentication
):
    """Get freeze history"""
    start_time = time.time()
    try:
        events = history_tracker.get_history(
            event_type=event_type,
            namespace=namespace,
            limit=limit
        )
        
        duration = time.time() - start_time
        record_api_request("/freeze/history", "GET", 200, duration)
        
        return {
            "success": True,
            "data": [event.to_dict() for event in events],
            "count": len(events),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/freeze/history", "GET", 500, duration)
        logger.error(f"Error getting history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Templates API
@router.get("/freeze/templates")
async def list_templates(
    request: Request,
    template_engine: TemplateEngine = Depends(get_template_engine),
    _: str = Depends(verify_token)  # Require authentication
):
    """List available freeze templates (from ConfigMap)"""
    start_time = time.time()
    try:
        templates = template_engine.list_templates()
        if not templates:
            logger.warning("No templates configured. Configure templates in ConfigMap 'kube-freezer-templates'")
        
        duration = time.time() - start_time
        record_api_request("/freeze/templates", "GET", 200, duration)
        
        return {
            "success": True,
            "data": templates,
            "count": len(templates),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/freeze/templates", "GET", 500, duration)
        logger.error(f"Error listing templates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class TemplateApplyRequest(BaseModel):
    template_name: str
    parameters: Optional[Dict[str, Any]] = None


@router.post("/freeze/templates/reload")
async def reload_templates(
    http_request: Request,
    template_engine: TemplateEngine = Depends(get_template_engine),
    _: str = Depends(verify_token)  # Require authentication
):
    """Reload templates from ConfigMap"""
    check_rate_limit(http_request)
    start_time = time.time()
    try:
        from kubernetes import client
        from app.utils.kubernetes import get_k8s_client
        import os
        
        v1 = client.CoreV1Api()
        namespace = os.getenv("NAMESPACE", "kube-freezer")
        
        try:
            template_cm = v1.read_namespaced_config_map("kube-freezer-templates", namespace)
            template_config = {"templates": template_cm.data.get("templates", "")}
            
            # Clear existing templates
            template_engine.templates.clear()
            
            # Reload templates
            template_engine.load_templates_from_config(template_config)
            
            duration = time.time() - start_time
            record_api_request("/freeze/templates/reload", "POST", 200, duration)
            
            return {
                "success": True,
                "message": f"Reloaded {len(template_engine.templates)} templates",
                "count": len(template_engine.templates),
                "templates": list(template_engine.templates.keys()),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            duration = time.time() - start_time
            record_api_request("/freeze/templates/reload", "POST", 500, duration)
            logger.error(f"Error reloading templates: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to reload templates: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/freeze/templates/reload", "POST", 500, duration)
        logger.error(f"Error reloading templates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/freeze/templates/apply")
async def apply_template(
    request: TemplateApplyRequest,
    http_request: Request,
    template_engine: TemplateEngine = Depends(get_template_engine),
    config_loader: ConfigLoader = Depends(get_config_loader),
    _: str = Depends(verify_token)  # Require authentication
):
    """Apply a freeze template - stores schedule directly in ConfigMap"""
    check_rate_limit(http_request)
    start_time = time.time()
    try:
        parameters = request.parameters or {}
        
        # Check if a direct schedule is provided (override_schedule)
        # If so, use it directly without any template processing
        if "override_schedule" in parameters:
            freeze_config = parameters["override_schedule"]
            # Ensure it's a dict
            if not isinstance(freeze_config, dict):
                raise HTTPException(status_code=400, detail="override_schedule must be a dictionary")
            
            # Validate schedule format (must have cron)
            if "cron" not in freeze_config:
                raise HTTPException(
                    status_code=400, 
                    detail="override_schedule must contain 'cron' field"
                )
            
            # Validate cron format - requires start and end dates
            if "start" not in freeze_config or "end" not in freeze_config:
                raise HTTPException(
                    status_code=400,
                    detail="'cron' schedule requires both 'start' and 'end' date fields"
                )
            
            # Create ordered config: name, start, end, cron, namespaces, message
            ordered_config = {
                "name": freeze_config.get("name"),
                "start": freeze_config.get("start"),
                "end": freeze_config.get("end"),
                "cron": freeze_config["cron"],
            }
            
            if freeze_config.get("namespaces"):
                ordered_config["namespaces"] = freeze_config.get("namespaces")
            
            if freeze_config.get("message"):
                ordered_config["message"] = freeze_config.get("message")
            
            freeze_config = ordered_config
        else:
            # Apply template normally (with variable substitution)
            freeze_config = template_engine.apply_template(
                template_name=request.template_name,
                parameters=parameters
            )
        
        # Store schedule in separate ConfigMap (NOT managed by Helm)
        # This prevents schedules from being deleted during Helm upgrades
        schedule_name = freeze_config.get("name", "unknown")
        try:
            from app.utils.schedules import add_schedule, load_schedules, save_schedules
            from app.utils.schedules import _order_schedule  # Import internal function for updates
            # Check if schedule already exists
            existing_schedules = load_schedules()
            existing_names = [s.get("name") for s in existing_schedules if s.get("name")]
            is_update = schedule_name in existing_names
            
            if is_update:
                # Update existing schedule
                ordered_schedule = _order_schedule(freeze_config)
                updated_schedules = []
                for s in existing_schedules:
                    if s.get("name") == schedule_name:
                        updated_schedules.append(ordered_schedule)
                    else:
                        updated_schedules.append(s)
                success = save_schedules(updated_schedules)
            else:
                # Add new schedule
                success = add_schedule(freeze_config)
            
            if not success:
                raise HTTPException(status_code=500, detail="Failed to save schedule to ConfigMap")
            
            # Reload config to refresh schedules
            await config_loader.load_config()
            
            # Record history
            try:
                tracker = get_history_tracker()
                event_type = "schedule_modified" if is_update else "schedule_added"
                tracker.record_event(
                    event_type=event_type,
                    reason=f"Schedule '{schedule_name}' {'updated' if is_update else 'added'}",
                    freeze_window=schedule_name,
                    namespace=", ".join(freeze_config.get("namespaces", [])) if freeze_config.get("namespaces") else None,
                    triggered_by="api"
                )
                # Persist to ConfigMap
                await tracker.save_to_configmap()
            except Exception as hist_error:
                logger.warning(f"Failed to save history event: {hist_error}", exc_info=True)
                # Don't fail the request, but log the error
            
            # Send notification
            notif_mgr = get_notification_manager()
            if notif_mgr:
                await notif_mgr.send_notification(
                    "schedule_modified" if is_update else "schedule_added",
                    {
                        "schedule_name": schedule_name,
                        "schedule": freeze_config
                    }
                )
            
            # Audit log
            audit = get_audit_logger()
            if audit:
                from app.audit.logger import AuditActor, AuditResource
                actor = audit.create_actor("api-user", "system")
                resource = audit.create_resource("freeze_schedule", schedule_name)
                event_type_audit = "schedule_modified" if is_update else "schedule_added"
                await audit.log_event(event_type_audit, actor, resource, "success", {
                    "schedule_name": schedule_name,
                    "schedule": freeze_config
                })
        except HTTPException:
            raise
        except Exception as update_error:
            logger.error(f"Could not save schedule to ConfigMap: {update_error}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to save schedule: {str(update_error)}")
        
        duration = time.time() - start_time
        record_api_request("/freeze/templates/apply", "POST", 200, duration)
        
        return {
            "success": True,
            "data": freeze_config,
            "message": f"Schedule stored in freeze_schedule ConfigMap",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/freeze/templates/apply", "POST", 500, duration)
        logger.error(f"Error applying template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Dry-run API
class DryRunRequest(BaseModel):
    request: Dict[str, Any]


@router.post("/dryrun/evaluate")
async def evaluate_dry_run_request(
    dryrun_request: DryRunRequest,
    http_request: Request,
    config_loader: ConfigLoader = Depends(get_config_loader),
    exemption_manager: ExemptionManager = Depends(get_exemption_manager)
):
    """Evaluate an admission request in dry-run mode"""
    check_rate_limit(http_request)
    start_time = time.time()
    try:
        from app.dryrun.evaluator import evaluate_dry_run, is_dry_run
        from app.freeze.evaluator import is_freeze_active
        from app.bypass.evaluator import check_bypass
        
        admission_request = dryrun_request.request
        
        # Check if it's actually a dry-run request
        if not is_dry_run(admission_request):
            raise HTTPException(
                status_code=400,
                detail="Request is not in dry-run mode"
            )
        
        # Get config
        config = config_loader.get_config()
        
        # Check if freeze is active
        freeze_active, freeze_window = is_freeze_active(config)
        
        # Check bypass (extract user info from request)
        user_info = admission_request.get("userInfo", {})
        username = user_info.get("username", "system:serviceaccount")
        groups = user_info.get("groups", [])
        bypass_result = check_bypass(admission_request, config, username, groups)
        
        # Normalize bypass result (check_bypass returns "allowed", but we need "bypassed")
        bypassed = bypass_result.get("allowed", False)
        
        # Evaluate dry-run
        allowed, warnings = evaluate_dry_run(
            request=admission_request,
            would_be_blocked=freeze_active and not bypassed,
            reason=config.get("freeze_message", "Freeze is active"),
            bypass_available=bypassed,
            bypass_type=bypass_result.get("type")
        )
        
        duration = time.time() - start_time
        record_api_request("/dryrun/evaluate", "POST", 200, duration)
        
        return {
            "success": True,
            "data": {
                "allowed": allowed,
                "warnings": warnings,
                "freeze_active": freeze_active,
                "freeze_window": freeze_window,
                "bypass_available": bypassed,
                "bypass_type": bypass_result.get("type")
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        duration = time.time() - start_time
        record_api_request("/dryrun/evaluate", "POST", 500, duration)
        logger.error(f"Error evaluating dry-run: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

