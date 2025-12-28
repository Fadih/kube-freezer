"""Utility functions for managing schedules in a separate ConfigMap"""
import logging
import yaml
from typing import List, Dict, Any, Optional
from kubernetes import client

logger = logging.getLogger(__name__)

# ConfigMap name for schedules (NOT managed by Helm)
SCHEDULES_CONFIGMAP_NAME = "kube-freezer-schedules"
SCHEDULES_KEY = "schedules"


def get_schedules_configmap_name() -> str:
    """Get the name of the schedules ConfigMap"""
    import os
    return os.getenv("SCHEDULES_CONFIGMAP_NAME", SCHEDULES_CONFIGMAP_NAME)


def get_schedules_namespace() -> str:
    """Get the namespace for schedules ConfigMap"""
    import os
    return os.getenv("NAMESPACE", "kube-freezer")


def load_schedules() -> List[Dict[str, Any]]:
    """
    Load schedules from the separate schedules ConfigMap
    
    Returns:
        List of schedule dictionaries
    """
    try:
        v1 = client.CoreV1Api()
        namespace = get_schedules_namespace()
        cm_name = get_schedules_configmap_name()
        
        try:
            cm = v1.read_namespaced_config_map(name=cm_name, namespace=namespace)
            schedules_str = cm.data.get(SCHEDULES_KEY, "[]")
            schedules = yaml.safe_load(schedules_str) or []
            if not isinstance(schedules, list):
                logger.warning(f"Schedules ConfigMap contains invalid data, expected list, got {type(schedules)}")
                return []
            logger.debug(f"Loaded {len(schedules)} schedules from {cm_name}")
            return schedules
        except client.exceptions.ApiException as e:
            if e.status == 404:
                logger.debug(f"Schedules ConfigMap {cm_name} not found, returning empty list")
                return []
            raise
    except Exception as e:
        logger.error(f"Error loading schedules: {e}", exc_info=True)
        return []


def _order_schedule(schedule: Dict[str, Any]) -> Dict[str, Any]:
    """
    Order schedule fields: name, start, end, cron, namespaces, message
    
    Args:
        schedule: Schedule dictionary
    
    Returns:
        Ordered schedule dictionary
    """
    # Order: name, start, end, cron, namespaces, message
    ordered = {
        "name": schedule.get("name"),
        "start": schedule.get("start"),
        "end": schedule.get("end"),
        "cron": schedule.get("cron"),
    }
    
    # Add optional fields if present
    if schedule.get("namespaces"):
        ordered["namespaces"] = schedule.get("namespaces")
    if schedule.get("message"):
        ordered["message"] = schedule.get("message")
    
    return ordered


def save_schedules(schedules: List[Dict[str, Any]]) -> bool:
    """
    Save schedules to the separate schedules ConfigMap
    
    Args:
        schedules: List of schedule dictionaries to save
    
    Returns:
        True if successful, False otherwise
    """
    try:
        v1 = client.CoreV1Api()
        namespace = get_schedules_namespace()
        cm_name = get_schedules_configmap_name()
        
        # Order all schedules before saving
        ordered_schedules = [_order_schedule(s) for s in schedules]
        
        # Prepare schedules data with explicit ordering
        schedules_yaml = yaml.dump(ordered_schedules, sort_keys=False) if ordered_schedules else "[]"
        
        try:
            # Try to read existing ConfigMap
            cm = v1.read_namespaced_config_map(name=cm_name, namespace=namespace)
            # Update existing ConfigMap
            cm.data[SCHEDULES_KEY] = schedules_yaml
            v1.patch_namespaced_config_map(
                name=cm_name,
                namespace=namespace,
                body=cm
            )
            logger.info(f"Updated {len(schedules)} schedules in {cm_name}")
        except client.exceptions.ApiException as e:
            if e.status == 404:
                # ConfigMap doesn't exist, create it
                cm = client.V1ConfigMap(
                    metadata=client.V1ObjectMeta(
                        name=cm_name,
                        namespace=namespace,
                        labels={
                            "app.kubernetes.io/name": "kube-freezer",
                            "app.kubernetes.io/component": "schedules",
                            "app.kubernetes.io/managed-by": "kubefreezer"  # NOT Helm
                        }
                    ),
                    data={
                        SCHEDULES_KEY: schedules_yaml
                    }
                )
                v1.create_namespaced_config_map(namespace=namespace, body=cm)
                logger.info(f"Created schedules ConfigMap {cm_name} with {len(schedules)} schedules")
            else:
                raise
        
        return True
    except Exception as e:
        logger.error(f"Error saving schedules: {e}", exc_info=True)
        return False


def add_schedule(schedule: Dict[str, Any]) -> bool:
    """
    Add a new schedule to the schedules ConfigMap
    
    Args:
        schedule: Schedule dictionary to add (will be reordered before saving)
    
    Returns:
        True if successful, False otherwise
    """
    schedules = load_schedules()
    # Order the new schedule before appending
    ordered_schedule = _order_schedule(schedule)
    schedules.append(ordered_schedule)
    return save_schedules(schedules)


def remove_schedule(schedule_name: str) -> bool:
    """
    Remove a schedule from the schedules ConfigMap
    
    Args:
        schedule_name: Name of the schedule to remove
    
    Returns:
        True if schedule was found and removed, False otherwise
    """
    schedules = load_schedules()
    original_count = len(schedules)
    schedules = [s for s in schedules if s.get("name", "") != schedule_name]
    
    if len(schedules) == original_count:
        return False  # Schedule not found
    
    return save_schedules(schedules)

