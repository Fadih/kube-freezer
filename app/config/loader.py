"""ConfigMap loader with Kubernetes Watch API"""
import asyncio
import logging
from typing import Dict, Optional, Any
from datetime import datetime, timezone
import yaml

from kubernetes import client, watch
from kubernetes.client.rest import ApiException

from app.utils.kubernetes import get_k8s_client

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads and caches configuration from ConfigMap"""
    
    def __init__(
        self,
        configmap_name: str = None,
        namespace: str = None,
        cache_ttl: int = 10,
        use_watch: bool = True
    ):
        import os
        self.configmap_name = configmap_name or os.getenv("CONFIGMAP_NAME", "kube-freezer-config")
        self.namespace = namespace or os.getenv("NAMESPACE", "kube-freezer")
        self.cache_ttl = cache_ttl
        self.use_watch = use_watch
        self._config: Optional[Dict[str, Any]] = None
        self._last_load: Optional[datetime] = None
        self._k8s_client = None
        self._watch_task = None
        self._watch_stop_event = None
        self._ready = False
        self._reload_errors = 0
    
    async def start(self):
        """Start the config loader"""
        self._k8s_client = get_k8s_client()
        await self.load_config()
        self._ready = True
        
        # Start watch or refresh loop
        if self.use_watch:
            self._watch_stop_event = asyncio.Event()
            self._watch_task = asyncio.create_task(self._watch_loop())
        else:
            self._watch_task = asyncio.create_task(self._refresh_loop())
    
    async def stop(self):
        """Stop the config loader"""
        if self._watch_stop_event:
            self._watch_stop_event.set()
        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
    
    def is_ready(self) -> bool:
        """Check if config loader is ready"""
        return self._ready and self._config is not None
    
    async def _watch_loop(self):
        """Watch ConfigMap for changes using Kubernetes Watch API"""
        import concurrent.futures
        v1 = self._k8s_client
        w = watch.Watch()
        loop = asyncio.get_event_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        
        while not self._watch_stop_event.is_set():
            try:
                # Run the blocking stream() call in a thread pool to avoid blocking the event loop
                def get_stream():
                    return list(w.stream(
                        v1.list_namespaced_config_map,
                        namespace=self.namespace,
                        field_selector=f"metadata.name={self.configmap_name}",
                        timeout_seconds=60
                    ))
                
                # Get events in a non-blocking way
                stream_future = loop.run_in_executor(executor, get_stream)
                try:
                    events = await asyncio.wait_for(stream_future, timeout=65)
                except asyncio.TimeoutError:
                    continue  # Timeout, check stop event and retry
                
                for event in events:
                    if self._watch_stop_event.is_set():
                        break
                    
                    event_type = event['type']
                    if event_type in ['ADDED', 'MODIFIED']:
                        logger.info(f"ConfigMap {event_type.lower()}, reloading config...")
                        await self.load_config()
                    elif event_type == 'DELETED':
                        logger.warning("ConfigMap deleted, using default config")
                        self._config = self._get_default_config()
                        self._last_load = datetime.now(timezone.utc)
                
            except ApiException as e:
                if e.status == 404:
                    logger.warning(f"ConfigMap not found, using defaults")
                    self._config = self._get_default_config()
                    await asyncio.sleep(5)  # Wait before retrying
                else:
                    logger.error(f"Error watching ConfigMap: {e}", exc_info=True)
                    self._reload_errors += 1
                    await asyncio.sleep(5)  # Wait before retrying
            except Exception as e:
                logger.error(f"Unexpected error in watch loop: {e}", exc_info=True)
                self._reload_errors += 1
                try:
                    from app.metrics.collector import record_config_reload_error
                    record_config_reload_error()
                except Exception:
                    pass  # Metrics not critical
                await asyncio.sleep(5)  # Wait before retrying
        
        w.stop()
        executor.shutdown(wait=False)
        logger.info("ConfigMap watch stopped")
    
    async def _refresh_loop(self):
        """Background task to refresh config periodically (fallback)"""
        while True:
            try:
                await asyncio.sleep(self.cache_ttl)
                await self.load_config()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error refreshing config: {e}", exc_info=True)
                self._reload_errors += 1
    
    async def load_config(self) -> Dict[str, Any]:
        """Load configuration from ConfigMap with retry logic"""
        max_retries = 5
        retry_delay = 2
        cm = None
        
        for attempt in range(max_retries):
            try:
                v1 = self._k8s_client
                cm = v1.read_namespaced_config_map(
                    name=self.configmap_name,
                    namespace=self.namespace
                )
                break  # Success, exit retry loop
            except ApiException as e:
                if e.status == 404:
                    logger.warning(f"ConfigMap {self.configmap_name} not found in namespace {self.namespace}, using defaults")
                    self._config = self._get_default_config()
                    return self._config
                elif attempt < max_retries - 1:
                    logger.warning(f"Failed to load ConfigMap (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Failed to load ConfigMap after {max_retries} attempts: {e}")
                    logger.warning("Using default configuration. ConfigMap will be retried in background.")
                    self._config = self._get_default_config()
                    return self._config
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Failed to load ConfigMap (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Failed to load ConfigMap after {max_retries} attempts: {e}")
                    logger.warning("Using default configuration. ConfigMap will be retried in background.")
                    self._config = self._get_default_config()
                    return self._config
        
        # Continue with successful load
        if cm is None:
            logger.warning("ConfigMap not loaded, using defaults")
            self._config = self._get_default_config()
            return self._config
            
        try:
            
            config_data = {}
            
            # Parse freeze_enabled
            config_data["freeze_enabled"] = cm.data.get("freeze_enabled", "false").lower() == "true"
            
            # Parse freeze_until
            freeze_until_str = cm.data.get("freeze_until", "")
            config_data["freeze_until"] = None
            if freeze_until_str:
                try:
                    config_data["freeze_until"] = datetime.fromisoformat(
                        freeze_until_str.replace("Z", "+00:00")
                    )
                except ValueError as e:
                    logger.warning(f"Invalid freeze_until format: {freeze_until_str}, error: {e}")
            
            # Parse freeze_message
            config_data["freeze_message"] = cm.data.get(
                "freeze_message",
                "Deployment freeze is active. Use bypass annotation or contact oncall."
            )
            
            # Parse bypass_annotation_key
            config_data["bypass_annotation_key"] = cm.data.get(
                "bypass_annotation_key",
                "admission-controller.io/emergency-bypass"
            )
            
            # Parse bypass_allowed_users
            bypass_users_str = cm.data.get("bypass_allowed_users", "")
            config_data["bypass_allowed_users"] = [
                line.strip()
                for line in bypass_users_str.split("\n")
                if line.strip()
            ]
            
            # Parse api_allowed_serviceaccounts (for API authorization)
            api_allowed_str = cm.data.get("api_allowed_serviceaccounts", "")
            config_data["api_allowed_serviceaccounts"] = [
                line.strip()
                for line in api_allowed_str.split("\n")
                if line.strip() and not line.strip().startswith("#")
            ]
            
            # Parse bypass_exempt_namespaces
            exempt_ns_str = cm.data.get("bypass_exempt_namespaces", "")
            config_data["bypass_exempt_namespaces"] = [
                line.strip()
                for line in exempt_ns_str.split("\n")
                if line.strip()
            ]
            
            # Parse monitored_resources
            monitored_str = cm.data.get("monitored_resources", "deployments")
            if isinstance(monitored_str, str):
                # Strip whitespace and try to parse as YAML
                monitored_str = monitored_str.strip()
                # Try to parse as YAML list
                try:
                    parsed = yaml.safe_load(monitored_str)
                    if isinstance(parsed, list):
                        config_data["monitored_resources"] = parsed
                        logger.debug(f"Parsed monitored_resources as YAML list: {parsed}")
                    elif isinstance(parsed, str):
                        # If YAML parser returned a string, try to extract list items from YAML format
                        # Handle cases like "- deployments\n- statefulsets"
                        lines = parsed.split('\n')
                        resources = []
                        for line in lines:
                            line = line.strip()
                            if line.startswith('-'):
                                resource = line[1:].strip()
                                if resource:
                                    resources.append(resource)
                        
                        if resources:
                            config_data["monitored_resources"] = resources
                            logger.debug(f"Extracted monitored_resources from YAML string: {resources}")
                        else:
                            # Fallback to comma split
                            config_data["monitored_resources"] = [
                                r.strip() for r in parsed.split(",") if r.strip()
                            ] or ["deployments"]
                    else:
                        # Fallback to default
                        config_data["monitored_resources"] = ["deployments"]
                        logger.warning(f"Unexpected type for monitored_resources: {type(parsed)}, using default")
                except yaml.YAMLError as e:
                    logger.warning(f"Failed to parse monitored_resources as YAML: {e}, trying to extract from string")
                    # Try to extract list items from YAML-like format
                    lines = monitored_str.split('\n')
                    resources = []
                    for line in lines:
                        line = line.strip()
                        if line.startswith('-'):
                            resource = line[1:].strip()
                            if resource:
                                resources.append(resource)
                    
                    if resources:
                        config_data["monitored_resources"] = resources
                        logger.debug(f"Extracted monitored_resources from YAML-like string: {resources}")
                    else:
                        # Fall back to comma split
                        config_data["monitored_resources"] = [
                            r.strip() for r in monitored_str.split(",") if r.strip()
                        ] or ["deployments"]
            else:
                config_data["monitored_resources"] = ["deployments"]
            
            # Ensure monitored_resources is always a list of strings
            if not isinstance(config_data.get("monitored_resources"), list):
                logger.error(f"monitored_resources is not a list: {config_data.get('monitored_resources')}, type: {type(config_data.get('monitored_resources'))}")
                config_data["monitored_resources"] = ["deployments"]
            
            logger.info(f"Final monitored_resources: {config_data.get('monitored_resources')}")
            
            # Parse fail_closed
            config_data["fail_closed"] = cm.data.get("fail_closed", "true").lower() == "true"
            
            # Load freeze_schedule from separate ConfigMap (NOT managed by Helm)
            # This prevents schedules from being deleted during Helm upgrades
            try:
                from app.utils.schedules import load_schedules
                schedules = load_schedules()
                config_data["freeze_schedule"] = schedules
                logger.debug(f"Loaded {len(schedules)} schedules from separate ConfigMap")
            except Exception as e:
                logger.warning(f"Could not load schedules from separate ConfigMap: {e}")
                config_data["freeze_schedule"] = []
            
            self._config = config_data
            self._last_load = datetime.now(timezone.utc)
            self._reload_errors = 0  # Reset error count on successful load
            
            # Record metrics
            try:
                from app.metrics.collector import record_config_reload_success
                record_config_reload_success()
            except Exception:
                pass  # Metrics not critical
            
            logger.info(f"Config loaded successfully. Freeze enabled: {config_data['freeze_enabled']}")
            return config_data
        except Exception as e:
            logger.error(f"Error parsing ConfigMap: {e}", exc_info=True)
            # Use defaults instead of raising
            self._config = self._get_default_config()
            return self._config
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration"""
        return {
            "freeze_enabled": False,
            "freeze_until": None,
            "freeze_message": "Deployment freeze is active.",
            "bypass_annotation_key": "admission-controller.io/emergency-bypass",
            "bypass_allowed_users": [],
            "api_allowed_serviceaccounts": [],
            "bypass_exempt_namespaces": [],
            "monitored_resources": ["deployments"],
            "fail_closed": True,
            "freeze_schedule": []
        }
    
    def get_reload_errors(self) -> int:
        """Get count of config reload errors"""
        return self._reload_errors
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration (cached)"""
        if self._config is None:
            logger.warning("Config not loaded, using defaults")
            return self._get_default_config()
        return self._config.copy()

