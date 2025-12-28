"""Freeze history tracker"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
import json

logger = logging.getLogger(__name__)


@dataclass
class FreezeEvent:
    """Freeze event record"""
    id: str
    event_type: str  # "enabled", "disabled", "schedule_activated", "schedule_deactivated"
    timestamp: datetime
    reason: str
    freeze_window: Optional[str] = None
    namespace: Optional[str] = None
    duration_minutes: Optional[int] = None
    triggered_by: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


class HistoryTracker:
    """Tracks freeze history"""
    
    def __init__(self, max_events: int = 1000, storage_backend: str = "configmap"):
        """
        Initialize history tracker
        
        Args:
            max_events: Maximum number of events to keep in memory
            storage_backend: Storage backend ("memory" or "configmap")
        """
        self.max_events = max_events
        self.storage_backend = storage_backend
        self._events: List[FreezeEvent] = []
        self._k8s_client = None
        self._namespace = None
    
    def set_k8s_client(self, client):
        """Set Kubernetes client for persistent storage"""
        self._k8s_client = client
        import os
        self._namespace = os.getenv("NAMESPACE", "kube-freezer")
    
    def record_event(
        self,
        event_type: str,
        reason: str,
        freeze_window: Optional[str] = None,
        namespace: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        triggered_by: Optional[str] = None
    ):
        """
        Record a freeze event
        
        Args:
            event_type: Type of event
            reason: Reason for the event
            freeze_window: Freeze window name
            namespace: Namespace affected
            duration_minutes: Duration in minutes
            triggered_by: Who/what triggered the event
        """
        import uuid
        event = FreezeEvent(
            id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            reason=reason,
            freeze_window=freeze_window,
            namespace=namespace,
            duration_minutes=duration_minutes,
            triggered_by=triggered_by
        )
        
        self._events.append(event)
        
        # Keep only last max_events
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events:]
        
        logger.info(f"Recorded freeze event: {event_type} - {reason} (total events: {len(self._events)})")
    
    async def save_to_configmap(self):
        """Public method to save history to ConfigMap (called after record_event)"""
        if self.storage_backend != "configmap":
            logger.debug(f"Skipping ConfigMap save - storage_backend is '{self.storage_backend}'")
            return
        
        if not self._k8s_client:
            logger.warning("Cannot save history to ConfigMap: Kubernetes client not set")
            return
        
        logger.info(f"Saving {len(self._events)} history events to ConfigMap")
        await self._save_to_configmap()
    
    async def _save_to_configmap(self):
        """Save history to ConfigMap"""
        if not self._k8s_client:
            logger.warning("Kubernetes client not set, cannot save history to ConfigMap")
            return
        
        if not self._namespace:
            logger.warning("Namespace not set, cannot save history to ConfigMap")
            return
        
        try:
            v1 = self._k8s_client
            cm_name = "kube-freezer-history"
            logger.debug(f"Attempting to save history to ConfigMap '{cm_name}' in namespace '{self._namespace}'")
            
            # Serialize events
            events_data = [event.to_dict() for event in self._events]
            events_json = json.dumps(events_data)
            logger.debug(f"Serialized {len(events_data)} events ({len(events_json)} bytes)")
            
            # Try to update existing ConfigMap
            try:
                cm = v1.read_namespaced_config_map(cm_name, self._namespace)
                logger.info(f"Found existing history ConfigMap '{cm_name}', updating...")
                cm.data["events"] = events_json
                v1.patch_namespaced_config_map(cm_name, self._namespace, cm)
                logger.info(f"Successfully updated history ConfigMap '{cm_name}' with {len(events_data)} events")
            except Exception as read_error:
                # Create new ConfigMap if it doesn't exist (same pattern as schedules ConfigMap)
                from kubernetes import client
                logger.info(f"ConfigMap '{cm_name}' not found, creating new one. Error: {read_error}")
                cm = client.V1ConfigMap(
                    metadata=client.V1ObjectMeta(
                        name=cm_name,
                        namespace=self._namespace,
                        labels={
                            "app.kubernetes.io/name": "kube-freezer",
                            "app.kubernetes.io/component": "history",
                            "app.kubernetes.io/managed-by": "kubefreezer"  # NOT Helm
                        }
                    ),
                    data={"events": events_json}
                )
                try:
                    v1.create_namespaced_config_map(namespace=self._namespace, body=cm)
                    logger.info(f"Successfully created history ConfigMap '{cm_name}' with {len(events_data)} events in namespace '{self._namespace}'")
                except Exception as create_error:
                    logger.error(f"Failed to create history ConfigMap '{cm_name}' in namespace '{self._namespace}': {create_error}", exc_info=True)
                    raise
        except Exception as e:
            logger.error(f"Error saving history to ConfigMap: {e}", exc_info=True)
            raise
    
    def _sync_load_from_configmap(self):
        """Load history from ConfigMap (synchronous version for use in get_history)"""
        if not self._k8s_client or self.storage_backend != "configmap":
            return
        
        try:
            v1 = self._k8s_client
            cm_name = "kube-freezer-history"
            
            try:
                cm = v1.read_namespaced_config_map(cm_name, self._namespace)
                events_json = cm.data.get("events", "[]")
                events_data = json.loads(events_json)
                
                # Deserialize events
                self._events = []
                for event_dict in events_data:
                    # Parse timestamp
                    timestamp_str = event_dict.get("timestamp")
                    if timestamp_str:
                        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    else:
                        timestamp = datetime.now(timezone.utc)
                    
                    event = FreezeEvent(
                        id=event_dict.get("id", ""),
                        event_type=event_dict.get("event_type", ""),
                        timestamp=timestamp,
                        reason=event_dict.get("reason", ""),
                        freeze_window=event_dict.get("freeze_window"),
                        namespace=event_dict.get("namespace"),
                        duration_minutes=event_dict.get("duration_minutes"),
                        triggered_by=event_dict.get("triggered_by")
                    )
                    self._events.append(event)
                
                # Keep only last max_events
                if len(self._events) > self.max_events:
                    self._events = self._events[-self.max_events:]
                
                logger.debug(f"Refreshed {len(self._events)} history events from ConfigMap")
            except Exception as e:
                logger.debug(f"ConfigMap {cm_name} not found or empty, using in-memory cache: {e}")
        except Exception as e:
            logger.debug(f"Error refreshing history from ConfigMap: {e}")
    
    async def _load_from_configmap(self):
        """Load history from ConfigMap (async version for startup)"""
        self._sync_load_from_configmap()
    
    def get_history(
        self,
        event_type: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 100
    ) -> List[FreezeEvent]:
        """
        Get freeze history
        
        Args:
            event_type: Filter by event type
            namespace: Filter by namespace
            limit: Maximum number of events to return
        
        Returns:
            List of freeze events (most recent first)
        """
        # Always reload from ConfigMap to get latest data (fixes issue with multiple pods)
        # Each pod may have stale in-memory cache, so read from source of truth
        if self.storage_backend == "configmap" and self._k8s_client:
            try:
                self._sync_load_from_configmap()
            except Exception as e:
                logger.debug(f"Could not refresh history from ConfigMap, using in-memory cache: {e}")
        
        events = self._events.copy()
        
        # Filter by event type
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        # Filter by namespace
        if namespace:
            events = [e for e in events if e.namespace == namespace or e.namespace is None]
        
        # Sort by timestamp (most recent first)
        events.sort(key=lambda e: e.timestamp, reverse=True)
        
        # Limit results
        return events[:limit]
    
    def get_events_dict(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get events as dictionary list"""
        events = self.get_history(limit=limit)
        return [event.to_dict() for event in events]

