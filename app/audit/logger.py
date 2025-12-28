"""Advanced audit logger"""
import logging
import json
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class AuditActor:
    """Audit actor information"""
    type: str  # user, serviceaccount, system
    identity: str  # username, service account name
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class AuditResource:
    """Audit resource information"""
    type: str  # freeze_window, exemption, deployment
    name: str
    namespace: Optional[str] = None
    cluster: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class AuditEvent:
    """Audit event"""
    event_id: str
    timestamp: datetime
    event_type: str  # freeze_enabled, violation, exemption_created, etc.
    actor: AuditActor
    resource: AuditResource
    outcome: str  # success, failure, denied
    details: Dict[str, Any]
    compliance_tags: List[str]  # soc2, hipaa, etc.
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        data["actor"] = self.actor.to_dict()
        data["resource"] = self.resource.to_dict()
        return data


class AuditSink:
    """Base class for audit sinks"""
    
    async def write(self, event: AuditEvent):
        """Write audit event"""
        raise NotImplementedError


class FileAuditSink(AuditSink):
    """File-based audit sink"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
    
    async def write(self, event: AuditEvent):
        """Write audit event to file"""
        try:
            with open(self.file_path, "a") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except Exception as e:
            logger.error(f"Error writing audit event to file: {e}", exc_info=True)


class ExternalAuditSink(AuditSink):
    """External system audit sink (Splunk, ELK, etc.)"""
    
    def __init__(self, endpoint: str, auth: Optional[Dict[str, str]] = None):
        self.endpoint = endpoint
        self.auth = auth
    
    async def write(self, event: AuditEvent):
        """Write audit event to external system"""
        try:
            import httpx
            headers = {}
            if self.auth:
                if "bearer" in self.auth:
                    headers["Authorization"] = f"Bearer {self.auth['bearer']}"
                elif "api_key" in self.auth:
                    headers["X-API-Key"] = self.auth["api_key"]
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.endpoint,
                    json=event.to_dict(),
                    headers=headers
                )
                response.raise_for_status()
        except Exception as e:
            logger.error(f"Error writing audit event to external system: {e}", exc_info=True)


class AuditLogger:
    """Advanced audit logger"""
    
    def __init__(self, sinks: Optional[List[AuditSink]] = None, enabled: bool = True):
        self.enabled = enabled
        self.sinks = sinks or []
        self.compliance_tags_map = {
            "freeze_enabled": ["soc2", "audit"],
            "freeze_disabled": ["soc2", "audit"],
            "violation": ["soc2", "security", "audit"],
            "exemption_created": ["soc2", "audit"],
            "exemption_deleted": ["soc2", "audit"],
            "config_changed": ["soc2", "audit"]
        }
    
    def add_sink(self, sink: AuditSink):
        """Add audit sink"""
        self.sinks.append(sink)
    
    async def log_event(
        self,
        event_type: str,
        actor: AuditActor,
        resource: AuditResource,
        outcome: str,
        details: Dict[str, Any]
    ):
        """Log audit event"""
        if not self.enabled:
            return
        
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            actor=actor,
            resource=resource,
            outcome=outcome,
            details=details,
            compliance_tags=self.compliance_tags_map.get(event_type, ["audit"])
        )
        
        # Write to all sinks
        for sink in self.sinks:
            try:
                await sink.write(event)
            except Exception as e:
                logger.error(f"Error writing to audit sink: {e}", exc_info=True)
    
    def create_actor(
        self,
        identity: str,
        actor_type: str = "user",
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditActor:
        """Create audit actor"""
        return AuditActor(
            type=actor_type,
            identity=identity,
            ip_address=ip_address,
            user_agent=user_agent
        )
    
    def create_resource(
        self,
        resource_type: str,
        name: str,
        namespace: Optional[str] = None,
        cluster: Optional[str] = None
    ) -> AuditResource:
        """Create audit resource"""
        return AuditResource(
            type=resource_type,
            name=name,
            namespace=namespace,
            cluster=cluster
        )

