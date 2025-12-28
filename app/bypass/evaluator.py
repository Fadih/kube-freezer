"""Bypass mechanism evaluation"""
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


def check_bypass(
    request: Dict[str, Any],
    config: Dict[str, Any],
    username: str,
    groups: List[str],
    exemption_manager: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Check if request should bypass freeze (synchronous bypass mechanisms only)
    
    Priority order:
    1. Annotation bypass
    2. User/ServiceAccount allowlist
    
    Note: Temporary exemption check is handled separately in the async webhook handler
    
    Args:
        request: Admission request
        config: Configuration dictionary
        username: Username from userInfo
        groups: Groups from userInfo
        exemption_manager: Optional (not used in sync function, kept for compatibility)
    
    Returns:
        Dict with 'allowed' (bool), 'reason' (str), and 'type' (str)
    """
    # 1. Check annotation bypass
    annotation_result = _check_annotation_bypass(request, config)
    if annotation_result["allowed"]:
        return annotation_result
    
    # Note: Temporary exemption check is handled in the async webhook handler
    # This function only handles sync bypass mechanisms (annotation, user allowlist)
    
    # 2. Check user allowlist
    user_result = _check_user_allowlist(username, groups, config)
    if user_result["allowed"]:
        return user_result
    
    # No bypass found
    return {"allowed": False, "reason": "No bypass mechanism matched"}


def _check_annotation_bypass(
    request: Dict[str, Any],
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """Check if annotation bypass is present"""
    annotation_key = config.get(
        "bypass_annotation_key",
        "admission-controller.io/emergency-bypass"
    )
    
    # Get object from request
    object_data = request.get("object", {})
    metadata = object_data.get("metadata", {})
    annotations = metadata.get("annotations", {})
    
    # Check for bypass annotation
    bypass_value = annotations.get(annotation_key, "").lower()
    if bypass_value == "true":
        reason = annotations.get(
            f"{annotation_key.rsplit('/', 1)[0]}/emergency-reason",
            "Emergency bypass annotation present"
        )
        return {
            "allowed": True,
            "type": "annotation",
            "reason": f"Annotation bypass: {reason}"
        }
    
    return {"allowed": False, "reason": "No bypass annotation found"}


def _check_user_allowlist(
    username: str,
    groups: List[str],
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """Check if user is in allowlist"""
    allowed_users = config.get("bypass_allowed_users", [])
    
    if not allowed_users:
        return {"allowed": False, "reason": "No users in allowlist"}
    
    # Check username
    if username in allowed_users:
        return {
            "allowed": True,
            "type": "user",
            "reason": f"User {username} is in bypass allowlist"
        }
    
    # Check groups
    for group in groups:
        if group in allowed_users:
            return {
                "allowed": True,
                "type": "group",
                "reason": f"Group {group} is in bypass allowlist"
            }
    
    return {"allowed": False, "reason": f"User {username} not in allowlist"}

