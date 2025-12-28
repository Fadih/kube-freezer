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
        
        channels = self.config.get("channels", ["#general"])
        
        try:
            message = self._format_message(event_type, data)
            
            for channel in channels:
                payload = {
                    "channel": channel,
                    "text": message.get("text", ""),
                    "blocks": message.get("blocks", [])
                }
                
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(webhook_url, json=payload)
                    response.raise_for_status()
            
            logger.info(f"Slack notification sent for {event_type}")
            return True
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
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"⏰ *Freeze schedule will activate soon*\n*Window:* {data.get('freeze_window', 'N/A')}\n*Starts:* {data.get('starts_at', 'N/A')}"
                        }
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


class EmailProvider(NotificationProvider):
    """Email notification provider"""
    
    async def send(self, event_type: str, data: Dict[str, Any]) -> bool:
        """Send email notification"""
        if not self.enabled:
            return False
        
        if event_type not in self.events:
            return False
        
        # For Phase 4, we'll use a simple SMTP approach
        # In production, consider using a service like SendGrid, SES, etc.
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            smtp_server = self.config.get("smtp_server")
            smtp_port = self.config.get("smtp_port", 587)
            smtp_user = self.config.get("smtp_user")
            smtp_password = self.config.get("smtp_password")
            from_email = self.config.get("from", "kubefreezer@company.com")
            to_emails = self.config.get("to", [])
            
            if not smtp_server or not to_emails:
                logger.warning("Email configuration incomplete")
                return False
            
            subject = self._get_subject(event_type)
            body = self._format_email_body(event_type, data)
            
            msg = MIMEMultipart()
            msg["From"] = from_email
            msg["To"] = ", ".join(to_emails)
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html"))
            
            # Note: This is synchronous SMTP, consider async SMTP library for production
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if smtp_user and smtp_password:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                server.send_message(msg)
            
            logger.info(f"Email notification sent for {event_type}")
            return True
        except Exception as e:
            logger.error(f"Error sending email notification: {e}", exc_info=True)
            return False
    
    def _get_subject(self, event_type: str) -> str:
        """Get email subject"""
        subjects = {
            "freeze_enabled": "🚫 KubeFreezer: Deployment Freeze Activated",
            "freeze_disabled": "✅ KubeFreezer: Deployment Freeze Disabled",
            "violation": "⚠️ KubeFreezer: Deployment Blocked During Freeze",
            "schedule_reminder": "⏰ KubeFreezer: Freeze Schedule Reminder"
        }
        return subjects.get(event_type, f"KubeFreezer: {event_type}")
    
    def _format_email_body(self, event_type: str, data: Dict[str, Any]) -> str:
        """Format email body as HTML"""
        if event_type == "freeze_enabled":
            return f"""
            <html>
            <body>
                <h2>🚫 Deployment Freeze Activated</h2>
                <p><strong>Freeze Window:</strong> {data.get('freeze_window', 'Manual Freeze')}</p>
                <p><strong>Until:</strong> {data.get('until', 'N/A')}</p>
                <p><strong>Namespace:</strong> {data.get('namespace', 'All')}</p>
                <p><strong>Reason:</strong> {data.get('reason', 'N/A')}</p>
            </body>
            </html>
            """
        elif event_type == "freeze_disabled":
            return f"""
            <html>
            <body>
                <h2>✅ Deployment Freeze Disabled</h2>
                <p><strong>Reason:</strong> {data.get('reason', 'N/A')}</p>
            </body>
            </html>
            """
        elif event_type == "violation":
            return f"""
            <html>
            <body>
                <h2>⚠️ Deployment Blocked During Freeze</h2>
                <p><strong>Resource:</strong> {data.get('resource', 'N/A')}</p>
                <p><strong>Namespace:</strong> {data.get('namespace', 'N/A')}</p>
                <p><strong>User:</strong> {data.get('user', 'N/A')}</p>
                <p><strong>Freeze Window:</strong> {data.get('freeze_window', 'N/A')}</p>
            </body>
            </html>
            """
        else:
            return f"<html><body><h2>KubeFreezer Event: {event_type}</h2><pre>{data}</pre></body></html>"


class WebhookProvider(NotificationProvider):
    """Generic webhook provider"""
    
    async def send(self, event_type: str, data: Dict[str, Any]) -> bool:
        """Send webhook notification"""
        if not self.enabled:
            return False
        
        if event_type not in self.events:
            return False
        
        webhook_url = self.config.get("url")
        if not webhook_url:
            logger.warning("Webhook URL not configured")
            return False
        
        try:
            headers = self.config.get("headers", {})
            payload = {
                "event_type": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": data
            }
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(webhook_url, json=payload, headers=headers)
                response.raise_for_status()
            
            logger.info(f"Webhook notification sent for {event_type}")
            return True
        except Exception as e:
            logger.error(f"Error sending webhook notification: {e}", exc_info=True)
            return False


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
            elif provider_type == "email":
                self.providers.append(EmailProvider(provider_config))
            elif provider_type == "webhook":
                self.providers.append(WebhookProvider(provider_config))
            else:
                logger.warning(f"Unknown notification provider type: {provider_type}")
    
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

