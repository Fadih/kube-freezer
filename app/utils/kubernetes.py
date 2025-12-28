"""Kubernetes client utilities"""
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import logging

logger = logging.getLogger(__name__)

_k8s_client = None


def get_k8s_client():
    """Get or create Kubernetes client"""
    global _k8s_client
    if _k8s_client is None:
        try:
            # Try in-cluster config first
            config.load_incluster_config()
        except config.ConfigException:
            try:
                # Fall back to kubeconfig
                config.load_kube_config()
            except config.ConfigException as e:
                logger.error(f"Failed to load Kubernetes config: {e}")
                raise
        
        _k8s_client = client.CoreV1Api()
    
    return _k8s_client

