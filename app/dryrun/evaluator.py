"""Dry-run evaluation"""
import logging
from typing import Dict, Any, Tuple, Optional, List

logger = logging.getLogger(__name__)


def is_dry_run(request: Dict[str, Any]) -> bool:
    """
    Check if request is in dry-run mode
    
    Args:
        request: Admission request
    
    Returns:
        True if dry-run mode
    """
    dry_run = request.get("dryRun")
    if dry_run is None:
        return False
    # dryRun can be a boolean or a list/string
    if isinstance(dry_run, bool):
        return dry_run
    if isinstance(dry_run, (list, str)):
        return len(dry_run) > 0
    return bool(dry_run)


def evaluate_dry_run(
    request: Dict[str, Any],
    would_be_blocked: bool,
    reason: Optional[str] = None,
    bypass_available: bool = False,
    bypass_type: Optional[str] = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    Evaluate request in dry-run mode
    
    Args:
        request: Admission request
        would_be_blocked: Whether request would be blocked
        reason: Reason for blocking
        bypass_available: Whether bypass is available
        bypass_type: Type of bypass available
    
    Returns:
        Tuple of (allowed, warnings)
    """
    warnings = []
    
    if would_be_blocked:
        warnings.append({
            "type": "FreezeActive",
            "message": f"Would be blocked: {reason or 'Freeze is active'}",
            "bypass_available": bypass_available,
            "bypass_type": bypass_type
        })
    
    # In dry-run, always allow but include warnings
    return True, warnings


def create_dry_run_response(uid: str, warnings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create dry-run admission response with warnings"""
    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "uid": uid,
            "allowed": True,  # Always allow in dry-run
            "warnings": [w["message"] for w in warnings] if warnings else []
        }
    }

