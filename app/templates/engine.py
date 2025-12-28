"""Freeze template engine"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
import yaml

logger = logging.getLogger(__name__)


# No built-in templates - all templates must be configured via ConfigMap
# This allows full flexibility and avoids hardcoded values
BUILTIN_TEMPLATES = {}


class TemplateEngine:
    """Engine for applying freeze templates"""
    
    def __init__(self, templates: Optional[Dict[str, Any]] = None):
        """
        Initialize template engine
        
        Args:
            templates: Templates from ConfigMap (no built-in templates)
        """
        # Start with empty dict - all templates must come from ConfigMap
        self.templates = {}
        if templates:
            self.templates.update(templates)
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """List all available templates"""
        if not self.templates:
            return []  # No templates configured
        return [
            {
                "name": name,
                "description": template.get("description", ""),
                "schedule": template.get("schedule", {})
            }
            for name, template in self.templates.items()
        ]
    
    def get_template(self, template_name: str) -> Optional[Dict[str, Any]]:
        """Get template by name"""
        return self.templates.get(template_name)
    
    def apply_template(
        self,
        template_name: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Apply template with parameters
        
        Args:
            template_name: Name of template to apply
            parameters: Template parameters (can include override_schedule for direct schedule override)
        
        Returns:
            Freeze schedule configuration
        """
        template = self.templates.get(template_name)
        if not template:
            raise ValueError(f"Template '{template_name}' not found")
        
        parameters = parameters or {}
        
        # Check if a direct schedule override is provided
        if "override_schedule" in parameters:
            # Use the provided schedule directly
            # Order: name, start, end, cron, namespaces, message
            override = parameters["override_schedule"]
            result = {
                "name": override.get("name", parameters.get("name", f"{template_name}-{datetime.now(timezone.utc).year}")),
                "start": override.get("start"),
                "end": override.get("end"),
                "cron": override.get("cron"),
            }
            # Add optional fields if present
            if override.get("namespaces"):
                result["namespaces"] = override.get("namespaces")
            if override.get("message"):
                result["message"] = override.get("message")
            elif template.get("message"):
                result["message"] = template.get("message", "Freeze active")
            return result
        
        # Render schedule from template
        schedule = self._render_schedule(template.get("schedule", {}), parameters)
        
        # Get namespaces (from parameters, then template)
        namespaces = parameters.get("namespaces") or template.get("namespaces", [])
        
        # Get message (from parameters, then template)
        message = parameters.get("message") or template.get("message", "Freeze active")
        
        # Generate name (from parameters, then auto-generate)
        name = parameters.get("name") or f"{template_name}-{parameters.get('year', datetime.now(timezone.utc).year)}"
        
        # Allow direct override of schedule fields via parameters
        # Order: name, start, end, cron, namespaces, message
        result = {
            "name": name,
            "start": parameters.get("start_time") or schedule.get("start"),
            "end": parameters.get("end_time") or schedule.get("end"),
            "cron": parameters.get("cron") or schedule.get("cron"),
        }
        # Add optional fields if present
        if namespaces:
            namespaces_list = namespaces if isinstance(namespaces, list) else (namespaces.split(",") if isinstance(namespaces, str) else [])
            if namespaces_list:
                result["namespaces"] = namespaces_list
        if message:
            result["message"] = message
        return result
    
    def _render_schedule(
        self,
        schedule_template: Dict[str, Any],
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Render schedule template with parameters"""
        schedule = schedule_template.copy()
        
        # Handle duration-based schedules
        if "duration_hours" in schedule:
            start_time = parameters.get("start_time")
            if not start_time:
                start_time = datetime.now(timezone.utc)
            elif isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            
            duration_hours = schedule["duration_hours"]
            end_time = start_time + timedelta(hours=duration_hours)
            
            schedule["start"] = start_time.isoformat()
            schedule["end"] = end_time.isoformat()
            del schedule["duration_hours"]
        
        elif "duration_days" in schedule:
            start_time = parameters.get("start_time")
            if not start_time:
                start_time = datetime.now(timezone.utc)
            elif isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            
            duration_days = schedule["duration_days"]
            end_time = start_time + timedelta(days=duration_days)
            
            schedule["start"] = start_time.isoformat()
            schedule["end"] = end_time.isoformat()
            del schedule["duration_days"]
        
        # No variable substitution - templates should have explicit values
        # Return schedule as-is
        return schedule
    
    def load_templates_from_config(self, config: Dict[str, Any]):
        """Load templates from configuration"""
        templates_str = config.get("templates", "")
        if not templates_str:
            logger.debug("No templates string in config")
            return
        
        try:
            if isinstance(templates_str, str):
                templates = yaml.safe_load(templates_str)
            else:
                templates = templates_str
            
            if not templates:
                logger.debug("Templates YAML parsed to None or empty")
                return
            
            if isinstance(templates, list):
                loaded_count = 0
                for template in templates:
                    name = template.get("name")
                    if name:
                        self.templates[name] = template
                        loaded_count += 1
                    else:
                        logger.warning(f"Template missing 'name' field: {template}")
                logger.info(f"Loaded {loaded_count} templates from config")
            else:
                logger.warning(f"Templates is not a list, got: {type(templates)}")
        except yaml.YAMLError as e:
            logger.error(f"Error parsing templates YAML: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error loading templates from config: {e}", exc_info=True)

