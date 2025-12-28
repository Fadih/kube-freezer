"""Notification manager"""
import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import httpx
import yaml

logger = logging.getLogger(__name__)


class NotificationProvider:
    """Base class for notification providers"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config.get("enabled", True)
        self.events = config.get("events", [])
    
    async def send(self, event_type: str, data: Dict[str, Any]) -> bool:
        """Send notification"""
        raise NotImplementedError


class SlackProvider(NotificationProvider):
    """Slack notification provider"""
    
    async def send(self, event_type: str, data: Dict[str, Any]) -> bool:
        """Send Slack notification"""
        if not self.enabled:
            return False
        
        if event_type not in self.events:
            return False
        
        webhook_url = self.config.get("webhook_url")
        if not webhook_url:
            logger.warning("Slack webhook_url not configured")
            return False
        
        try:
            message = self._format_message(event_type, data)
            
            # Build payload - Slack webhook format
            payload = {
                "text": message.get("text", ""),
            }
            
            # Add blocks if available (richer formatting)
            if message.get("blocks"):
                payload["blocks"] = message.get("blocks")
            
            # Optional: override channel (only works if webhook has permission)
            # Channels are typically set when creating the webhook URL
            channel = self.config.get("channel")
            if channel:
                payload["channel"] = channel
            
            # Optional: username override
            username = self.config.get("username")
            if username:
                payload["username"] = username
            
            # Optional: icon override
            icon_emoji = self.config.get("icon_emoji")
            if icon_emoji:
                payload["icon_emoji"] = icon_emoji
            elif self.config.get("icon_url"):
                payload["icon_url"] = self.config.get("icon_url")
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
                
                # Slack webhooks return "ok" as plain text or JSON {"ok": true/false}
                try:
                    response_text = response.text.strip()
                    if response_text == "ok":
                        # Success - Slack returned plain text "ok"
                        pass
                    else:
                        # Try to parse as JSON
                        response_data = response.json()
                        if response_data.get("ok") is False:
                            error = response_data.get("error", "Unknown error")
                            logger.error(f"Slack API error: {error}")
                            return False
                except Exception:
                    # If response parsing fails but status is 200, assume success
                    # Slack webhooks can return various formats
                    pass
            
            logger.info(f"Slack notification sent for {event_type}")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error sending Slack notification: {e.response.status_code} - {e.response.text}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Error sending Slack notification: {e}", exc_info=True)
            return False
    
    def _format_message(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format message for Slack"""
        if event_type == "freeze_enabled":
            return {
                "text": "🚫 Deployment Freeze Activated",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "🚫 Deployment Freeze Activated"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Freeze Window:* {data.get('freeze_window', 'Manual Freeze')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Until:* {data.get('until', 'N/A')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Namespace:* {data.get('namespace', 'All')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Reason:* {data.get('reason', 'N/A')}"
                            }
                        ]
                    }
                ]
            }
        elif event_type == "freeze_disabled":
            return {
                "text": "✅ Deployment Freeze Disabled",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "✅ Deployment Freeze Disabled"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Reason:* {data.get('reason', 'N/A')}"
                        }
                    }
                ]
            }
        elif event_type == "violation":
            return {
                "text": "⚠️ Deployment Blocked During Freeze",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "⚠️ Deployment Blocked During Freeze"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Resource:* {data.get('resource', 'N/A')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Namespace:* {data.get('namespace', 'N/A')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*User:* {data.get('user', 'N/A')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Freeze Window:* {data.get('freeze_window', 'N/A')}"
                            }
                        ]
                    }
                ]
            }
        elif event_type == "schedule_reminder":
            return {
                "text": "⏰ Freeze Schedule Reminder",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "⏰ Freeze Schedule Reminder"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Window:* {data.get('freeze_window', 'N/A')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Starts:* {data.get('starts_at', 'N/A')}"
                            }
                        ]
                    }
                ]
            }
        elif event_type == "schedule_removed":
            return {
                "text": "🗑️ Freeze Schedule Removed",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "🗑️ Freeze Schedule Removed"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Schedule:* {data.get('schedule_name', 'N/A')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Reason:* {data.get('reason', 'N/A')}"
                            }
                        ]
                    }
                ]
            }
        elif event_type == "exemption_created":
            resource_info = data.get('namespace', 'N/A')
            if data.get('resource_name'):
                resource_info += f"/{data.get('resource_name')}"
            
            duration_hours = data.get('duration_minutes', 0) / 60
            duration_str = f"{data.get('duration_minutes', 0)} min"
            if duration_hours >= 1:
                duration_str = f"{duration_hours:.1f} hours" if duration_hours > 1 else "1 hour"
            
            return {
                "text": "✅ Exemption Created",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "✅ Exemption Created"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Exemption ID:* `{data.get('exemption_id', 'N/A')[:8]}...`"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Resource:* {resource_info}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Duration:* {duration_str}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Expires:* {data.get('expires_at', 'N/A')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Approved By:* {data.get('approved_by', 'N/A')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Reason:* {data.get('reason', 'N/A')}"
                            }
                        ]
                    }
                ]
            }
        else:
            return {
                "text": f"KubeFreezer Event: {event_type}",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Event:* {event_type}\n*Details:* {data}"
                        }
                    }
                ]
            }


class NotificationManager:
    """Manages all notification providers"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.enabled = config.get("enabled", False) if config else False
        self.providers: List[NotificationProvider] = []
        self._rate_limit_cache: Dict[str, datetime] = {}
        self._rate_limit_window = 60  # seconds
        
        if config and self.enabled:
            self._load_providers(config)
    
    def _load_providers(self, config: Dict[str, Any]):
        """Load notification providers from config"""
        providers_config = config.get("providers", [])
        
        if isinstance(providers_config, str):
            try:
                providers_config = yaml.safe_load(providers_config)
            except yaml.YAMLError:
                logger.error("Invalid providers YAML configuration")
                return
        
        for provider_config in providers_config:
            provider_type = provider_config.get("type", "").lower()
            
            if provider_type == "slack":
                self.providers.append(SlackProvider(provider_config))
            else:
                logger.warning(f"Unsupported notification provider type: {provider_type}. Only 'slack' is supported.")
    
    async def send_notification(self, event_type: str, data: Dict[str, Any]):
        """Send notification to all configured providers"""
        if not self.enabled:
            return
        
        # Rate limiting: prevent spam
        if self._is_rate_limited(event_type, data):
            logger.debug(f"Rate limited for event {event_type}")
            return
        
        # Send to all providers in parallel
        tasks = [provider.send(event_type, data) for provider in self.providers]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    def _is_rate_limited(self, event_type: str, data: Dict[str, Any]) -> bool:
        """Check if notification should be rate limited"""
        # Create a key for rate limiting (event type + namespace)
        namespace = data.get("namespace", "global")
        key = f"{event_type}:{namespace}"
        
        now = datetime.now(timezone.utc)
        last_sent = self._rate_limit_cache.get(key)
        
        if last_sent and (now - last_sent).total_seconds() < self._rate_limit_window:
            return True
        
        self._rate_limit_cache[key] = now
        return False
    
    def reload_config(self, config: Dict[str, Any]):
        """Reload notification configuration"""
        self.enabled = config.get("enabled", False)
        self.providers = []
        if self.enabled:
            self._load_providers(config)

