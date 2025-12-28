"""Freeze window evaluation"""
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

from app.freeze.schedule import get_active_schedules, parse_schedule

logger = logging.getLogger(__name__)


def is_freeze_active(config: Dict[str, Any], namespace: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    Check if freeze is currently active
    
    Args:
        config: Configuration dictionary
        namespace: Namespace to check (for namespace-scoped freezes)
    
    Returns:
        Tuple of (is_active, freeze_window_name)
    """
    # Check freeze schedules first (Phase 2)
    freeze_schedules = config.get("freeze_schedule", [])
    if freeze_schedules:
        exempt_namespaces = config.get("bypass_exempt_namespaces", [])
        active_schedules = get_active_schedules(freeze_schedules, namespace, exempt_namespaces)
        if active_schedules:
            # Return first active schedule name
            schedule_name = active_schedules[0].get("name", "Active Schedule")
            logger.debug(f"Freeze schedule active: {schedule_name}")
            return True, schedule_name
    
    # Fall back to simple freeze_enabled/freeze_until (Phase 1)
    freeze_enabled = config.get("freeze_enabled", False)
    if not freeze_enabled:
        return False, None
    
    # Check freeze_until timestamp
    freeze_until = config.get("freeze_until")
    if freeze_until is None:
        # If freeze_enabled is True but no freeze_until, assume indefinite freeze
        logger.warning("freeze_enabled is True but freeze_until is not set, assuming indefinite freeze")
        return True, "Manual Freeze"
    
    # Parse freeze_until if it's a string
    if isinstance(freeze_until, str):
        try:
            freeze_until = datetime.fromisoformat(freeze_until.replace("Z", "+00:00"))
        except ValueError as e:
            logger.error(f"Invalid freeze_until format: {freeze_until}, error: {e}")
            return False, None
    
    # Ensure timezone awareness
    if freeze_until.tzinfo is None:
        freeze_until = freeze_until.replace(tzinfo=timezone.utc)
    
    # Get current time (UTC)
    now = datetime.now(timezone.utc)
    
    # Check if freeze period has passed
    if now >= freeze_until:
        logger.debug(f"Freeze period expired. Now: {now}, Until: {freeze_until}")
        return False, None
    
    logger.debug(f"Freeze is active. Now: {now}, Until: {freeze_until}")
    return True, "Manual Freeze"

