// API Response Types
export interface ApiResponse<T> {
  success: boolean;
  data: T;
  message?: string;
  timestamp: string;
}

// Freeze Status
export interface FreezeStatus {
  active: boolean;
  freeze_enabled: boolean;
  freeze_until: string | null;
  freeze_message: string;
  remaining: string | null;
  freeze_window: string | null;
  schedules: Array<{
    name: string;
    start: string;
    end: string;
    cron: string;
    namespaces?: string[];
  }>;
}

// Template
export interface Template {
  name: string;
  description: string;
  schedule: {
    start?: string;
    end?: string;
    cron?: string;
    namespaces?: string[];
    message?: string;
    [key: string]: any;
  };
}

// Schedule
export interface Schedule {
  name: string;
  start: string;
  end: string;
  cron: string;
  namespaces?: string[];
  message?: string;
}

// Exemption
export interface Exemption {
  id: string;
  namespace: string;
  resource_name?: string;
  duration_minutes: number;
  reason: string;
  approved_by: string;
  created_at: string;
  expires_at: string;
  used: boolean;
}

// History Event
export interface HistoryEvent {
  id: string;
  event_type: string;
  timestamp: string;
  reason: string;
  triggered_by: string;
  namespace?: string;
}

// Template Apply Request
export interface TemplateApplyRequest {
  template_name: string;
  parameters?: {
    year?: string;
    month?: string;
    day?: string;
    namespaces?: string[];
    start_time?: string;
    name?: string;
    [key: string]: any;
  };
}

// Freeze Enable Request
export interface FreezeEnableRequest {
  until: string;
  reason?: string;
}

// Freeze Disable Request
export interface FreezeDisableRequest {
  reason?: string;
}

// Exemption Create Request
export interface ExemptionCreateRequest {
  namespace: string;
  resource_name?: string;
  duration_minutes: number;
  reason: string;
  approved_by: string;
}

