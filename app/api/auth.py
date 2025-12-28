"""API authentication"""
import logging
import os
import base64
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from fastapi import Request, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

# Cache for API keys (loaded from Secret)
_api_keys: Dict[str, str] = {}
_api_keys_last_load: Optional[datetime] = None
_api_keys_cache_ttl: int = 30  # Reload every 30 seconds


def _load_api_keys(force_reload: bool = False) -> Dict[str, str]:
    """
    Load API keys from Secret or environment
    
    Args:
        force_reload: If True, reload even if cache is still valid
    
    Returns:
        Dictionary mapping API keys to usernames
    """
    global _api_keys, _api_keys_last_load
    
    # Check if cache is still valid (unless force reload)
    if not force_reload and _api_keys_last_load:
        age = (datetime.now(timezone.utc) - _api_keys_last_load).total_seconds()
        if age < _api_keys_cache_ttl:
            return _api_keys
    
    # Clear existing keys
    _api_keys = {}
    
    try:
        from kubernetes import client
        import base64
        v1 = client.CoreV1Api()
        namespace = os.getenv("NAMESPACE", "kube-freezer")
        
        try:
            # Try to load from Secret (more secure than ConfigMap)
            secret = v1.read_namespaced_secret("kube-freezer-api-keys", namespace)
            if secret.data:
                for key, value in secret.data.items():
                    if key.startswith("api_key_"):
                        # Decode base64 value from Secret
                        decoded_value = base64.b64decode(value).decode('utf-8')
                        _api_keys[decoded_value] = key.replace("api_key_", "")
            logger.info(f"Loaded {len(_api_keys)} API keys from Secret")
            if _api_keys:
                logger.debug(f"API key usernames: {list(_api_keys.values())}")
        except Exception as e:
            logger.warning(f"Could not load API keys from Secret: {e}", exc_info=True)
        
        # Also check environment variable (for testing/development)
        env_key = os.getenv("API_KEY")
        if env_key:
            _api_keys[env_key] = "env-user"
            logger.info("Loaded API key from environment")
            
    except Exception as e:
        logger.warning(f"Could not load API keys: {e}")
    
    _api_keys_last_load = datetime.now(timezone.utc)
    return _api_keys


async def _validate_serviceaccount_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Validate Kubernetes ServiceAccount token by calling TokenReview API
    
    Args:
        token: ServiceAccount token to validate
    
    Returns:
        UserInfo dict if valid, None otherwise
    """
    try:
        from kubernetes import client
        from kubernetes.client.rest import ApiException
        
        auth_api = client.AuthenticationV1Api()
        
        # Create TokenReview request
        token_review = client.V1TokenReview(
            spec=client.V1TokenReviewSpec(token=token)
        )
        
        # Call TokenReview API
        review = auth_api.create_token_review(body=token_review)
        
        if review.status.authenticated:
            return {
                "username": review.status.user.username,
                "uid": review.status.user.uid,
                "groups": review.status.user.groups or [],
                "extra": review.status.user.extra or {}
            }
        else:
            logger.warning(f"TokenReview failed: {review.status.error}")
            return None
            
    except ApiException as e:
        logger.warning(f"TokenReview API error: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error validating ServiceAccount token: {e}")
        return None


async def _check_serviceaccount_authorization(
    username: str,
    groups: List[str],
    config: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Check if ServiceAccount is authorized to use the API
    
    Args:
        username: ServiceAccount username (e.g., system:serviceaccount:namespace:name)
        groups: Groups from token
        config: Optional config dict (if not provided, will try to load)
    
    Returns:
        True if authorized, False otherwise
    """
    # Load config if not provided
    if config is None:
        try:
            from app.config.loader import ConfigLoader
            import os
            loader = ConfigLoader(
                configmap_name=os.getenv("CONFIGMAP_NAME", "kube-freezer-config"),
                namespace=os.getenv("NAMESPACE", "kube-freezer")
            )
            # Try to get config (may fail if not initialized, that's OK)
            try:
                config = loader.get_config()
            except Exception:
                config = {}
        except Exception:
            config = {}
    
    # Get allowed ServiceAccounts from config
    allowed_users = config.get("api_allowed_serviceaccounts", [])
    
    # Security: Deny by default - only allow ServiceAccounts in the allowlist
    # If no allowlist configured, deny all access
    if not allowed_users:
        logger.warning(
            f"ServiceAccount '{username}' denied: No API allowlist configured. "
            "Configure 'api_allowed_serviceaccounts' in ConfigMap to allow access."
        )
        return False
    
    # Check if username is in allowlist
    if username in allowed_users:
        logger.debug(f"ServiceAccount {username} is authorized (in allowlist)")
        return True
    
    # Check if any group is in allowlist
    for group in groups:
        if group in allowed_users:
            logger.debug(f"ServiceAccount {username} is authorized (group {group} in allowlist)")
            return True
    
    logger.warning(f"ServiceAccount {username} is NOT authorized (not in allowlist)")
    return False


async def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    request: Request = None
) -> str:
    """
    Verify API token
    
    Supports:
    1. Kubernetes ServiceAccount tokens (validated via TokenReview API)
    2. API keys from ConfigMap/Secret
    3. Environment variable API key (for testing)
    
    Args:
        credentials: HTTP Bearer token credentials
        request: FastAPI request object
    
    Returns:
        Username/service account name
    
    Raises:
        HTTPException: If authentication fails
    """
    # Extract token
    if not credentials and request:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid authorization header"
            )
    elif credentials:
        token = credentials.credentials
    else:
        raise HTTPException(
            status_code=401,
            detail="Missing authorization credentials"
        )
    
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )
    
    # Method 1: Try ServiceAccount token validation (Kubernetes TokenReview API)
    user_info = await _validate_serviceaccount_token(token)
    if user_info:
        username = user_info.get("username", "serviceaccount")
        groups = user_info.get("groups", [])
        
        # Check authorization (is this ServiceAccount allowed to use the API?)
        try:
            from app.config.loader import ConfigLoader
            import os
            loader = ConfigLoader(
                configmap_name=os.getenv("CONFIGMAP_NAME", "kube-freezer-config"),
                namespace=os.getenv("NAMESPACE", "kube-freezer")
            )
            config = loader.get_config()
        except Exception:
            config = {}
        
        is_authorized = await _check_serviceaccount_authorization(username, groups, config)
        if not is_authorized:
            allowed_list = config.get("api_allowed_serviceaccounts", [])
            if not allowed_list:
                raise HTTPException(
                    status_code=403,
                    detail="API access is restricted. No ServiceAccounts are authorized. "
                           "Configure 'api_allowed_serviceaccounts' in ConfigMap to allow access."
                )
            else:
                raise HTTPException(
                    status_code=403,
                    detail=f"ServiceAccount '{username}' is not authorized to use this API. "
                           f"Authorized ServiceAccounts: {', '.join(allowed_list)}. "
                           "Contact administrator to add your ServiceAccount to 'api_allowed_serviceaccounts' in ConfigMap."
                )
        
        logger.debug(f"ServiceAccount token validated and authorized for user: {username}")
        return username
    
    # Method 2: Check API keys from Secret
    # Try loading API keys (will use cache if recent, or reload if stale)
    api_keys = _load_api_keys()
    logger.debug(f"Checking API key. Loaded {len(api_keys)} keys. Token length: {len(token)}")
    if token in api_keys:
        username = api_keys[token]
        logger.info(f"API key validated for user: {username}")
        return username
    
    # If token not found, try force reloading (in case Secret was just created)
    # This handles the case where Secret is created after pod startup
    logger.debug("Token not found in cached keys, force reloading...")
    api_keys = _load_api_keys(force_reload=True)
    logger.debug(f"After reload: {len(api_keys)} keys loaded")
    if token in api_keys:
        username = api_keys[token]
        logger.info(f"API key validated for user: {username} (after reload)")
        return username
    
    logger.warning(f"API key validation failed. Token not found in {len(api_keys)} loaded keys.")
    
    # Method 3: Fallback - check if it's a valid-looking token (for development only)
    # This is less secure but allows testing without proper tokens
    # In production, you should disable this or make it configurable
    if len(token) >= 10:
        # Check if we're in development mode (no strict auth required)
        strict_auth = os.getenv("STRICT_AUTH", "false").lower() == "true"
        if not strict_auth:
            logger.warning(f"Using fallback token validation (not secure for production)")
            return "api-user"
    
    # All validation methods failed
    raise HTTPException(
        status_code=401,
        detail="Invalid or expired token"
    )


async def optional_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    request: Request = None
) -> Optional[str]:
    """
    Optional authentication - doesn't fail if no token provided
    
    Useful for endpoints that work with or without auth
    """
    try:
        return await verify_token(credentials, request)
    except HTTPException:
        return None

