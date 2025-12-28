"""Prometheus metrics collector"""
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Admission request metrics
admission_requests_total = Counter(
    'kubefreezer_admission_requests_total',
    'Total number of admission requests',
    ['decision', 'resource_type', 'namespace']
)

admission_request_duration_seconds = Histogram(
    'kubefreezer_admission_request_duration_seconds',
    'Time spent processing admission requests',
    ['decision']
)

# Freeze status metrics
freeze_active = Gauge(
    'kubefreezer_freeze_active',
    'Whether freeze is currently active (1) or not (0)',
    ['namespace']
)

freeze_window_remaining_seconds = Gauge(
    'kubefreezer_freeze_window_remaining_seconds',
    'Seconds remaining in current freeze window',
    ['freeze_window']
)

# Bypass usage metrics
bypass_used_total = Counter(
    'kubefreezer_bypass_used_total',
    'Total number of times bypass was used',
    ['type', 'namespace']
)

# Configuration metrics
config_reload_errors_total = Counter(
    'kubefreezer_config_reload_errors_total',
    'Total number of config reload errors'
)

config_reload_timestamp = Gauge(
    'kubefreezer_config_reload_timestamp',
    'Timestamp of last successful config reload'
)

# API request metrics
api_requests_total = Counter(
    'kubefreezer_api_requests_total',
    'Total number of API requests',
    ['endpoint', 'method', 'status_code']
)

api_request_duration_seconds = Histogram(
    'kubefreezer_api_request_duration_seconds',
    'Time spent processing API requests',
    ['endpoint', 'method']
)


def record_admission_request(decision: str, resource_type: str, namespace: str, duration: float):
    """Record admission request metrics"""
    admission_requests_total.labels(
        decision=decision,
        resource_type=resource_type,
        namespace=namespace or "default"
    ).inc()
    admission_request_duration_seconds.labels(decision=decision).observe(duration)


def record_freeze_status(active: bool, namespace: Optional[str] = None):
    """Record freeze status"""
    freeze_active.labels(namespace=namespace or "global").set(1 if active else 0)


def record_freeze_window_remaining(seconds: float, freeze_window: str):
    """Record freeze window remaining time"""
    freeze_window_remaining_seconds.labels(freeze_window=freeze_window).set(seconds)


def record_bypass_used(bypass_type: str, namespace: str):
    """Record bypass usage"""
    bypass_used_total.labels(type=bypass_type, namespace=namespace or "default").inc()


def record_config_reload_error():
    """Record config reload error"""
    config_reload_errors_total.inc()


def record_config_reload_success():
    """Record successful config reload"""
    from datetime import datetime, timezone
    config_reload_timestamp.set(datetime.now(timezone.utc).timestamp())


def record_api_request(endpoint: str, method: str, status_code: int, duration: float):
    """Record API request metrics"""
    api_requests_total.labels(
        endpoint=endpoint,
        method=method,
        status_code=str(status_code)
    ).inc()
    api_request_duration_seconds.labels(endpoint=endpoint, method=method).observe(duration)


def get_metrics():
    """Get Prometheus metrics"""
    return generate_latest()


def get_metrics_content_type():
    """Get content type for metrics endpoint"""
    return CONTENT_TYPE_LATEST

