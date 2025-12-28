"""Admission webhook handler"""
import logging
import time
from typing import Dict, Any
from datetime import datetime, timezone

from app.freeze.evaluator import is_freeze_active
from app.bypass.evaluator import check_bypass
from app.metrics.collector import (
    record_admission_request,
    record_freeze_status,
    record_bypass_used
)
from app.api.routes import get_exemption_manager
from app.dryrun.evaluator import is_dry_run, evaluate_dry_run, create_dry_run_response

logger = logging.getLogger(__name__)


async def handle_admission_review(
    body: Dict[str, Any],
    config_loader
) -> Dict[str, Any]:
    """
    Handle admission review request
    
    Args:
        body: AdmissionReview request body
        config_loader: ConfigLoader instance
    
    Returns:
        AdmissionReview response
    """
    start_time = time.time()
    request = body.get("request", {})
    uid = request.get("uid", "")
    kind = request.get("kind", {})
    resource_kind = kind.get("kind", "").lower()
    
    # Get resource info
    namespace = request.get("namespace", "")
    name = request.get("name", "")
    operation = request.get("operation", "").upper()
    
    # Get user info
    user_info = request.get("userInfo", {})
    username = user_info.get("username", "")
    groups = user_info.get("groups", [])
    
    # Structured logging
    log_record = logging.LogRecord(
        name=__name__,
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=f"Processing {operation} request",
        args=(),
        exc_info=None
    )
    log_record.request_id = uid
    log_record.event = "admission_review"
    log_record.resource = {
        "kind": resource_kind,
        "name": name,
        "namespace": namespace
    }
    log_record.user = {
        "username": username,
        "groups": groups
    }
    logger.handle(log_record)
    
    # Get configuration
    config = config_loader.get_config()
    
    # Check if resource type is monitored
    # Normalize resource_kind to plural form for comparison (e.g., "deployment" -> "deployments")
    # Kubernetes uses singular for resource kinds, but we store plural in config
    resource_kind_normalized = resource_kind
    if resource_kind.endswith('y'):
        # "deployment" -> "deployments", "policy" -> "policies"
        resource_kind_normalized = resource_kind[:-1] + 'ies' if resource_kind[-2] in 'aeiou' else resource_kind + 's'
    elif not resource_kind.endswith('s'):
        resource_kind_normalized = resource_kind + 's'
    
    monitored_resources = [r.lower() for r in config.get("monitored_resources", ["deployments"])]
    logger.info(f"Checking resource {resource_kind} (normalized: {resource_kind_normalized}) against monitored resources: {monitored_resources}")
    
    # Check both singular and plural forms
    if resource_kind not in monitored_resources and resource_kind_normalized not in monitored_resources:
        logger.info(f"Resource {resource_kind} not monitored, allowing {resource_kind}/{name} in {namespace}")
        duration = time.time() - start_time
        record_admission_request("allow", resource_kind, namespace, duration)
        return _allow_response(uid)
    
    # Check if dry-run mode
    dry_run = is_dry_run(request)
    logger.info(f"Dry-run check for {resource_kind}/{name}: {dry_run}")
    
    # Check if namespace is exempt
    exempt_namespaces = config.get("bypass_exempt_namespaces", [])
    logger.info(f"Checking if namespace {namespace} is exempt: {exempt_namespaces}")
    if namespace in exempt_namespaces:
        logger.info(f"Namespace {namespace} is exempt, allowing {resource_kind}/{name}")
        duration = time.time() - start_time
        record_admission_request("allow", resource_kind, namespace, duration)
        return _allow_response(uid)
    
    # Get exemption manager if available
    exemption_manager = None
    try:
        from app.api.routes import _exemption_manager
        exemption_manager = _exemption_manager
    except Exception:
        pass  # Exemption manager not critical
    
    # Check bypass mechanisms first
    # Check annotation and user bypass (sync)
    bypass_result = check_bypass(
        request=request,
        config=config,
        username=username,
        groups=groups,
        exemption_manager=None  # Skip exemption check in sync function
    )
    
    logger.info(f"Bypass check for {resource_kind}/{name} in {namespace}: allowed={bypass_result.get('allowed')}, reason={bypass_result.get('reason')}, type={bypass_result.get('type')}")
    
    # Check exemption separately (async)
    if not bypass_result["allowed"] and exemption_manager:
        try:
            namespace = request.get("namespace", "")
            object_data = request.get("object", {})
            metadata = object_data.get("metadata", {})
            resource_name = metadata.get("name")
            
            exemption = await exemption_manager.check_exemption(namespace, resource_name)
            if exemption and exemption.is_valid():
                await exemption_manager.use_exemption(exemption.id)
                
                # Record history event for exemption usage
                try:
                    from app.api.routes import get_history_tracker
                    tracker = get_history_tracker()
                    tracker.record_event(
                        event_type="exemption_used",
                        reason=f"Exemption applied: {exemption.reason} (approved by: {exemption.approved_by})",
                        namespace=exemption.namespace,
                        triggered_by=username or "webhook"
                    )
                    await tracker.save_to_configmap()
                except Exception as hist_error:
                    logger.debug(f"Failed to save exemption usage history: {hist_error}")
                
                bypass_result = {
                    "allowed": True,
                    "type": "exemption",
                    "reason": f"Temporary exemption: {exemption.reason} (expires {exemption.expires_at.isoformat()})"
                }
        except Exception as e:
            logger.debug(f"Error checking exemption: {e}")
    
    if bypass_result["allowed"]:
        bypass_type = bypass_result.get("type", "unknown")
        record_bypass_used(bypass_type, namespace)
        
        log_record = logging.LogRecord(
            name=__name__,
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Bypass granted",
            args=(),
            exc_info=None
        )
        log_record.request_id = uid
        log_record.event = "bypass_granted"
        log_record.resource = {"kind": resource_kind, "name": name, "namespace": namespace}
        log_record.reason = bypass_result["reason"]
        logger.handle(log_record)
        
        duration = time.time() - start_time
        record_admission_request("allow", resource_kind, namespace, duration)
        return _allow_response(uid)
    
    # Check if freeze is active
    freeze_active, freeze_window = is_freeze_active(config, namespace)
    
    # Record freeze status
    record_freeze_status(freeze_active, namespace)
    
    # Debug logging
    logger.info(f"Freeze check for {resource_kind}/{name} in {namespace}: active={freeze_active}, window={freeze_window}")
    
    if not freeze_active:
        logger.info(f"No freeze active, allowing {resource_kind}/{name} in {namespace}")
        duration = time.time() - start_time
        record_admission_request("allow", resource_kind, namespace, duration)
        return _allow_response(uid)
    
    # Freeze is active and no bypass - deny (or warn in dry-run)
    freeze_message = config.get(
        "freeze_message",
        "Deployment freeze is active. Use bypass annotation or contact oncall."
    )
    
    if freeze_window:
        freeze_message = f"{freeze_message} (Freeze window: {freeze_window})"
    
    # Check if dry-run mode
    if dry_run:
        # In dry-run, always allow but include warnings
        allowed, warnings = evaluate_dry_run(
            request=request,
            would_be_blocked=True,
            reason=freeze_message,
            bypass_available=False,
            bypass_type=None
        )
        
        logger.info(f"Dry-run: Would block {resource_kind}/{name} in {namespace}: {freeze_message}")
        
        duration = time.time() - start_time
        record_admission_request("allow", resource_kind, namespace, duration)
        
        return create_dry_run_response(uid, warnings)
    
    # Normal mode - deny
    log_record = logging.LogRecord(
        name=__name__,
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg="Deployment denied: Freeze active",
        args=(),
        exc_info=None
    )
    log_record.request_id = uid
    log_record.event = "admission_denied"
    log_record.resource = {"kind": resource_kind, "name": name, "namespace": namespace}
    log_record.decision = "deny"
    log_record.reason = "freeze_active"
    log_record.freeze_window = freeze_window
    logger.handle(log_record)
    
    duration = time.time() - start_time
    record_admission_request("deny", resource_kind, namespace, duration)
    
    # Send violation notification (Phase 4)
    try:
        from app.api.routes import get_notification_manager
        notif_mgr = get_notification_manager()
        if notif_mgr:
            await notif_mgr.send_notification("violation", {
                "resource": f"{resource_kind}/{name}",
                "namespace": namespace,
                "user": username,
                "freeze_window": freeze_window or "Manual Freeze"
            })
    except Exception as e:
        logger.debug(f"Error sending violation notification: {e}")
    
    # Audit log violation (Phase 4)
    try:
        from app.api.routes import get_audit_logger
        from app.audit.logger import AuditActor, AuditResource
        audit = get_audit_logger()
        if audit:
            actor = audit.create_actor(username, "serviceaccount" if "serviceaccount" in username else "user")
            resource = audit.create_resource(resource_kind, name, namespace)
            await audit.log_event("violation", actor, resource, "denied", {
                "freeze_window": freeze_window,
                "reason": freeze_message
            })
    except Exception as e:
        logger.debug(f"Error logging audit event: {e}")
    
    return _deny_response(
        uid=uid,
        message=freeze_message,
        code=403
    )


def _allow_response(uid: str) -> Dict[str, Any]:
    """Create allow response"""
    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "uid": uid,
            "allowed": True
        }
    }


def _deny_response(uid: str, message: str, code: int = 403) -> Dict[str, Any]:
    """Create deny response"""
    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "uid": uid,
            "allowed": False,
            "status": {
                "code": code,
                "message": message
            }
        }
    }

