import type {
  ApiResponse,
  FreezeStatus,
  Template,
  Schedule,
  Exemption,
  HistoryEvent,
  TemplateApplyRequest,
  FreezeEnableRequest,
  FreezeDisableRequest,
  ExemptionCreateRequest,
} from '@/types';

// Determine API base URL
const getApiBase = (): string => {
  // Always use relative path - Nginx will proxy /api/ to the backend
  // This works both in development (via Vite proxy) and production (via Nginx proxy)
  return '/api/v1';
};

class KubeFreezerAPI {
  private token: string | null = null;
  private apiBase: string;

  constructor() {
    this.apiBase = getApiBase();
    // Load token from localStorage on init
    this.token = localStorage.getItem('kubefreezer_token');
  }

  setToken(token: string) {
    // Trim whitespace to prevent issues
    const trimmedToken = token.trim();
    this.token = trimmedToken;
    localStorage.setItem('kubefreezer_token', trimmedToken);
  }

  getToken(): string | null {
    const token = this.token || localStorage.getItem('kubefreezer_token');
    // Trim any whitespace that might have been stored
    return token ? token.trim() : null;
  }

  clearToken() {
    this.token = null;
    localStorage.removeItem('kubefreezer_token');
  }

  isAuthenticated(): boolean {
    return !!this.getToken();
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const token = this.getToken();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string> || {}),
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const url = `${this.apiBase}${endpoint}`;
    
    try {
      const response = await fetch(url, {
        ...options,
        headers: headers as HeadersInit,
      });

      if (response.status === 401) {
        // Token expired or invalid
        this.clearToken();
        throw new Error('Authentication required');
      }

      if (response.status === 403) {
        const error = await response.json().catch(() => ({ detail: 'Forbidden' }));
        throw new Error(error.detail || 'Access forbidden');
      }

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(error.detail || `Request failed: ${response.statusText}`);
      }

      const data: ApiResponse<T> = await response.json();
      return data.data;
    } catch (error) {
      if (error instanceof Error) {
        throw error;
      }
      throw new Error('Network error');
    }
  }

  // Freeze Management
  async getFreezeStatus(): Promise<FreezeStatus> {
    return this.request<FreezeStatus>('/freeze/status');
  }

  async enableFreeze(request: FreezeEnableRequest): Promise<void> {
    await this.request('/freeze/enable', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  async disableFreeze(request?: FreezeDisableRequest): Promise<void> {
    await this.request('/freeze/disable', {
      method: 'POST',
      body: JSON.stringify(request || {}),
    });
  }

  // Templates
  async getTemplates(): Promise<Template[]> {
    const response = await this.request<{ data: Template[]; count: number }>('/freeze/templates');
    return Array.isArray(response) ? response : (response as any).data || [];
  }

  async applyTemplate(request: TemplateApplyRequest): Promise<Schedule> {
    const response = await this.request<{ data: Schedule; success: boolean; message?: string } | Schedule>('/freeze/templates/apply', {
      method: 'POST',
      body: JSON.stringify(request),
    });
    // Handle both direct Schedule response and wrapped response
    if ('data' in response && response.data) {
      return response.data;
    }
    return response as Schedule;
  }

  async reloadTemplates(): Promise<void> {
    await this.request('/freeze/templates/reload', {
      method: 'POST',
    });
  }

  // Schedules
  async getSchedules(): Promise<Schedule[]> {
    const response = await this.request<{ data: Schedule[]; count: number }>('/freeze/schedules');
    return Array.isArray(response) ? response : (response as any).data || [];
  }

  async deleteSchedule(name: string, reason?: string): Promise<void> {
    await this.request(`/freeze/schedules/${encodeURIComponent(name)}`, {
      method: 'DELETE',
      body: JSON.stringify({ reason }),
    });
  }

  // Exemptions
  async getExemptions(): Promise<Exemption[]> {
    const response = await this.request<{ data: Exemption[]; count: number }>('/freeze/exemptions');
    return Array.isArray(response) ? response : (response as any).data || [];
  }

  async getExemption(id: string): Promise<Exemption> {
    return this.request<Exemption>(`/freeze/exemptions/${id}`);
  }

  async createExemption(request: ExemptionCreateRequest): Promise<Exemption> {
    return this.request<Exemption>('/freeze/exemptions', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  async deleteExemption(id: string): Promise<void> {
    await this.request(`/freeze/exemptions/${id}`, {
      method: 'DELETE',
    });
  }

  // History
  async getHistory(limit?: number, eventType?: string, namespace?: string): Promise<HistoryEvent[]> {
    const params = new URLSearchParams();
    if (limit) params.append('limit', limit.toString());
    if (eventType) params.append('event_type', eventType);
    if (namespace) params.append('namespace', namespace);
    
    const query = params.toString();
    const response = await this.request<{ data: HistoryEvent[]; count: number }>(
      `/freeze/history${query ? `?${query}` : ''}`
    );
    return Array.isArray(response) ? response : (response as any).data || [];
  }
}

export const api = new KubeFreezerAPI();

