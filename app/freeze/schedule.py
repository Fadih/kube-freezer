"""Freeze schedule parsing and evaluation using cron expressions"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from croniter import croniter

logger = logging.getLogger(__name__)


def parse_schedule(schedule_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parse a freeze schedule configuration using cron expressions
    
    Schedule format (cron with date range):
    {
        "name": "schedule-name",
        "start": "2024-12-01T00:00:00Z",  # Start date (when cron becomes active) - required
        "end": "2024-12-31T23:59:59Z",    # End date (when cron stops being active) - required
        "cron": "0 22 * * *",              # Cron expression (required) - freeze is active when this matches
        "namespaces": ["production"]        # Optional namespace filter
    }
    
    The cron expression is active between start and end dates. When the cron matches,
    the freeze is active until the end date.
    
    Args:
        schedule_config: Schedule configuration dict
    
    Returns:
        Parsed schedule dict or None if invalid
    """
    try:
        name = schedule_config.get("name", "Unnamed")
        
        # Parse start and end dates (optional - if not provided, cron runs indefinitely)
        start_str = schedule_config.get("start")
        end_str = schedule_config.get("end")
        start = None
        end = None
        
        if start_str:
            start = _parse_datetime(start_str)
            if start is None:
                logger.warning(f"Schedule {name}: invalid start date format")
                return None
        
        if end_str:
            end = _parse_datetime(end_str)
            if end is None:
                logger.warning(f"Schedule {name}: invalid end date format")
            return None
        
        # Validate date range
        if start and end and end <= start:
            logger.warning(f"Schedule {name}: end date must be after start date")
            return None
        
        # Cron is required
        cron = schedule_config.get("cron")
        if not cron:
            logger.warning(f"Schedule {name}: missing required 'cron' field")
            return None
        
        # Start and end dates are required
        if not start or not end:
            logger.warning(f"Schedule {name}: 'cron' requires both 'start' and 'end' date fields")
            return None
        
        # Validate cron expression
        try:
            test_time = start
            iter = croniter(cron, test_time)
            # If we get here, cron is valid
        except Exception as e:
            logger.warning(f"Schedule {name}: invalid cron expression '{cron}': {e}")
            return None
        
        # Parse namespaces
        namespaces = schedule_config.get("namespaces", [])
        if isinstance(namespaces, str):
            namespaces = [ns.strip() for ns in namespaces.split(",") if ns.strip()]
        
        # Return in specific order: name, start, end, cron, namespaces, message
        result = {
            "name": name,
            "start": start,
            "end": end,
            "cron": cron,
        }
        
        # Add optional fields
        if namespaces:
            result["namespaces"] = namespaces
        if schedule_config.get("message"):
            result["message"] = schedule_config.get("message")
        result["original"] = schedule_config
        
        return result
    except Exception as e:
        logger.error(f"Error parsing schedule: {e}", exc_info=True)
        return None


def _parse_datetime(dt_str: str) -> Optional[datetime]:
    """Parse datetime string"""
    try:
        # Try ISO format
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        try:
            # Try common formats
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    dt = datetime.strptime(dt_str, fmt)
                    return dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        except Exception:
            pass
        
        logger.error(f"Unable to parse datetime: {dt_str}")
        return None


def is_schedule_active(
    schedule: Dict[str, Any],
    current_time: Optional[datetime] = None,
    namespace: Optional[str] = None,
    exempt_namespaces: Optional[List[str]] = None
) -> bool:
    """
    Check if a schedule is currently active using cron logic
    
    Args:
        schedule: Parsed schedule dict
        current_time: Current time (defaults to now)
        namespace: Namespace to check (for namespace-scoped schedules)
        exempt_namespaces: List of exempt namespaces (when schedule has empty namespaces list)
    
    Returns:
        True if schedule is active
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    
    exempt_namespaces = exempt_namespaces or []
    
    # Check namespace scope
    namespaces = schedule.get("namespaces", [])
    if namespaces and len(namespaces) > 0:
        # Schedule has specific namespaces - check if namespace matches
        if namespace and namespace not in namespaces:
            return False
    else:
        # Schedule has no namespaces specified - applies to ALL namespaces EXCEPT exempt ones
        if namespace and namespace in exempt_namespaces:
            # This namespace is exempt, so don't apply the schedule
        return False
    
    # Use UTC for all time operations
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time_utc = current_time
    
    # Check if we're within the date range (start/end dates)
    start = schedule.get("start")
    end = schedule.get("end")
    
    # Convert string dates to datetime objects if needed
    if start:
        if isinstance(start, str):
            start = _parse_datetime(start)
            if start is None:
                logger.warning(f"Schedule {schedule.get('name', 'Unknown')}: invalid start date format")
                return False
        # Ensure start is UTC
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if current_time_utc < start:
            return False  # Before start date
    else:
        logger.warning(f"Schedule {schedule.get('name', 'Unknown')}: missing start date")
        return False
    
    if end:
        if isinstance(end, str):
            end = _parse_datetime(end)
            if end is None:
                logger.warning(f"Schedule {schedule.get('name', 'Unknown')}: invalid end date format")
                return False
        # Ensure end is UTC
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if current_time_utc > end:
            return False  # After end date
    else:
        logger.warning(f"Schedule {schedule.get('name', 'Unknown')}: missing end date")
        return False
    
    # Cron is required - check if freeze is active when cron matches
    cron = schedule.get("cron")
    if not cron:
    return False

    return _check_cron_active(cron, current_time_utc, start, end)


def _check_cron_active(
    cron: str,
    current_time: datetime,
    start: datetime,
    end: datetime
) -> bool:
    """
    Check if current time is within an active freeze window based on cron expression
    
    Logic:
    1. Current time must be within start/end date range (already checked above)
    2. Find the most recent cron match before or at current time
    3. If a match is found, freeze is active from that match time until the end of that same day
    4. If cron matches at midnight, freeze is active all day
    
    Example:
    - Cron: "0 22 * * *" (10 PM daily)
      If cron matches at 2024-12-01 22:00:00, freeze is active from 22:00:00 to 23:59:59 that same day
    - Cron: "0 0 * * 1-5" (midnight on weekdays)
      If cron matches at 2024-12-01 00:00:00, freeze is active all day (00:00:00 to 23:59:59)
    """
    try:
        # Ensure start and end are datetime objects in UTC
        if isinstance(start, str):
            start = _parse_datetime(start)
            if start is None:
                return False
        if isinstance(end, str):
            end = _parse_datetime(end)
            if end is None:
                return False
        
        # Ensure UTC timezone
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        
        # Find the most recent cron match before or at current time
        iter_current = croniter(cron, current_time)
        cron_match = iter_current.get_prev(datetime)
        
        # If no match found or match is before start date, check next match
        if cron_match < start:
            iter_start = croniter(cron, start)
            next_match = iter_start.get_next(datetime)
            if next_match <= current_time and next_match <= end:
                cron_match = next_match
            else:
                return False
        
        # If match is after end date or after current time, not active
        if cron_match > end or cron_match > current_time:
    return False
        
        # Calculate end of day for the cron match day (in UTC)
        # Set to 23:59:59.999999 of the same day as the cron match
        match_day_start = cron_match.replace(hour=0, minute=0, second=0, microsecond=0)
        match_day_end = match_day_start + timedelta(days=1) - timedelta(microseconds=1)
        
        # Ensure we don't go beyond the overall end date
        day_end = min(match_day_end, end)
        
        # Check if current time is between cron match and end of that day (all in UTC)
        if cron_match <= current_time <= day_end:
            return True
        
        return False
    except Exception as e:
        logger.error(f"Error checking cron active: {e}", exc_info=True)
        return False




def get_active_schedules(
    schedules: List[Dict[str, Any]],
    namespace: Optional[str] = None,
    exempt_namespaces: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Get all active schedules
    
    Args:
        schedules: List of schedule configs
        namespace: Namespace to check
        exempt_namespaces: List of exempt namespaces (when schedule has empty namespaces list)
    
    Returns:
        List of active schedule dicts
    """
    active = []
    current_time = datetime.now(timezone.utc)
    exempt_namespaces = exempt_namespaces or []
    
    for schedule_config in schedules:
        # Parse schedule if needed (check if it has cron field)
        if "cron" not in schedule_config:
            parsed = parse_schedule(schedule_config)
            if parsed is None:
                continue
            schedule = parsed
        else:
            schedule = schedule_config
        
        if is_schedule_active(schedule, current_time, namespace, exempt_namespaces):
            active.append(schedule)
    
    return active
