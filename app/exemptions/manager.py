"""Temporary exemptions manager"""
import logging
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
import json

logger = logging.getLogger(__name__)


@dataclass
class Exemption:
    """Temporary exemption"""
    id: str
    namespace: str
    resource_name: Optional[str]
    duration_minutes: int
    reason: str
    approved_by: str
    created_at: datetime
    expires_at: datetime
    used: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["expires_at"] = self.expires_at.isoformat()
        return data
    
    def is_expired(self) -> bool:
        """Check if exemption is expired"""
        return datetime.now(timezone.utc) >= self.expires_at
    
    def is_valid(self) -> bool:
        """Check if exemption is valid (not expired)"""
        # Exemptions remain valid for their entire duration and can be used multiple times
        return not self.is_expired()


class ExemptionManager:
    """Manages temporary exemptions"""
    
    def __init__(self, storage_backend: str = "memory"):
        """
        Initialize exemption manager
        
        Args:
            storage_backend: Storage backend ("memory" or "configmap")
        """
        self.storage_backend = storage_backend
        self._exemptions: Dict[str, Exemption] = {}
        self._k8s_client = None
    
    def set_k8s_client(self, client):
        """Set Kubernetes client for ConfigMap storage"""
        self._k8s_client = client
    
    async def create_exemption(
        self,
        namespace: str,
        duration_minutes: int,
        reason: str,
        approved_by: str,
        resource_name: Optional[str] = None
    ) -> Exemption:
        """
        Create a new temporary exemption
        
        Args:
            namespace: Namespace to exempt
            duration_minutes: Duration in minutes
            reason: Reason for exemption
            approved_by: Who approved the exemption
            resource_name: Optional specific resource name
        
        Returns:
            Created Exemption object
        """
        exemption_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(minutes=duration_minutes)
        
        exemption = Exemption(
            id=exemption_id,
            namespace=namespace,
            resource_name=resource_name,
            duration_minutes=duration_minutes,
            reason=reason,
            approved_by=approved_by,
            created_at=created_at,
            expires_at=expires_at
        )
        
        self._exemptions[exemption_id] = exemption
        
        # Persist if using ConfigMap backend
        if self.storage_backend == "configmap":
            await self._save_to_configmap()
        
        logger.info(
            f"Created exemption {exemption_id} for namespace {namespace} "
            f"expiring at {expires_at.isoformat()}"
        )
        
        return exemption
    
    async def get_exemption(self, exemption_id: str) -> Optional[Exemption]:
        """Get exemption by ID"""
        # Load from ConfigMap if needed
        if self.storage_backend == "configmap":
            await self._load_from_configmap()
        
        return self._exemptions.get(exemption_id)
    
    async def list_exemptions(
        self,
        namespace: Optional[str] = None,
        active_only: bool = False
    ) -> List[Exemption]:
        """
        List exemptions
        
        Args:
            namespace: Filter by namespace
            active_only: Only return active (non-expired) exemptions
        
        Returns:
            List of exemptions
        """
        # Load from ConfigMap if needed
        if self.storage_backend == "configmap":
            await self._load_from_configmap()
        
        exemptions = list(self._exemptions.values())
        
        # Filter by namespace
        if namespace:
            exemptions = [e for e in exemptions if e.namespace == namespace]
        
        # Filter active only
        if active_only:
            exemptions = [e for e in exemptions if e.is_valid()]
        
        # Sort by expires_at (soonest first)
        exemptions.sort(key=lambda e: e.expires_at)
        
        return exemptions
    
    async def check_exemption(
        self,
        namespace: str,
        resource_name: Optional[str] = None
    ) -> Optional[Exemption]:
        """
        Check if there's an active exemption for namespace/resource
        
        Args:
            namespace: Namespace to check
            resource_name: Optional resource name to check
        
        Returns:
            Exemption if found and valid, None otherwise
        """
        exemptions = await self.list_exemptions(namespace=namespace, active_only=True)
        
        for exemption in exemptions:
            # Check if resource-specific exemption matches
            if exemption.resource_name:
                if resource_name and exemption.resource_name == resource_name:
                    return exemption
            else:
                # Namespace-wide exemption
                return exemption
        
        return None
    
    async def use_exemption(self, exemption_id: str) -> bool:
        """
        Mark exemption as used
        
        Args:
            exemption_id: Exemption ID
        
        Returns:
            True if exemption was found and marked, False otherwise
        """
        exemption = await self.get_exemption(exemption_id)
        if exemption and exemption.is_valid():
            exemption.used = True
            
            # Persist if using ConfigMap backend
            if self.storage_backend == "configmap":
                await self._save_to_configmap()
            
            logger.info(f"Exemption {exemption_id} marked as used")
            return True
        
        return False
    
    async def delete_exemption(self, exemption_id: str) -> bool:
        """
        Delete an exemption
        
        Args:
            exemption_id: Exemption ID
        
        Returns:
            True if exemption was deleted, False otherwise
        """
        if exemption_id in self._exemptions:
            del self._exemptions[exemption_id]
            
            # Persist if using ConfigMap backend
            if self.storage_backend == "configmap":
                await self._save_to_configmap()
            
            logger.info(f"Deleted exemption {exemption_id}")
            return True
        
        return False
    
    async def cleanup_expired(self) -> int:
        """
        Clean up expired exemptions
        
        Returns:
            Number of exemptions cleaned up
        """
        expired = [
            eid for eid, exemption in self._exemptions.items()
            if exemption.is_expired()
        ]
        
        for eid in expired:
            del self._exemptions[eid]
        
        if expired and self.storage_backend == "configmap":
            await self._save_to_configmap()
        
        return len(expired)
    
    async def _save_to_configmap(self):
        """Save exemptions to ConfigMap"""
        if not self._k8s_client:
            logger.warning("Kubernetes client not set, cannot save to ConfigMap")
            return
        
        try:
            from app.config.loader import ConfigLoader
            import os
            config_loader = ConfigLoader()
            namespace = os.getenv("NAMESPACE", "kube-freezer")
            
            v1 = self._k8s_client
            cm_name = "kube-freezer-exemptions"
            
            # Serialize exemptions
            exemptions_data = {
                eid: exemption.to_dict()
                for eid, exemption in self._exemptions.items()
            }
            
            # Try to update existing ConfigMap
            try:
                cm = v1.read_namespaced_config_map(cm_name, namespace)
                cm.data["exemptions"] = json.dumps(exemptions_data)
                v1.patch_namespaced_config_map(cm_name, namespace, cm)
            except Exception:
                # Create new ConfigMap
                from kubernetes import client
                cm = client.V1ConfigMap(
                    metadata=client.V1ObjectMeta(name=cm_name),
                    data={"exemptions": json.dumps(exemptions_data)}
                )
                v1.create_namespaced_config_map(namespace, cm)
        except Exception as e:
            logger.error(f"Error saving exemptions to ConfigMap: {e}", exc_info=True)
    
    async def _load_from_configmap(self):
        """Load exemptions from ConfigMap"""
        if not self._k8s_client:
            return
        
        try:
            from app.config.loader import ConfigLoader
            import os
            namespace = os.getenv("NAMESPACE", "kube-freezer")
            
            v1 = self._k8s_client
            cm_name = "kube-freezer-exemptions"
            
            try:
                cm = v1.read_namespaced_config_map(cm_name, namespace)
                exemptions_data = json.loads(cm.data.get("exemptions", "{}"))
                
                # Deserialize exemptions
                self._exemptions = {}
                for eid, data in exemptions_data.items():
                    exemption = Exemption(
                        id=data["id"],
                        namespace=data["namespace"],
                        resource_name=data.get("resource_name"),
                        duration_minutes=data["duration_minutes"],
                        reason=data["reason"],
                        approved_by=data["approved_by"],
                        created_at=datetime.fromisoformat(data["created_at"]),
                        expires_at=datetime.fromisoformat(data["expires_at"]),
                        used=data.get("used", False)
                    )
                    self._exemptions[eid] = exemption
            except Exception:
                # ConfigMap doesn't exist yet, start with empty
                pass
        except Exception as e:
            logger.error(f"Error loading exemptions from ConfigMap: {e}", exc_info=True)

