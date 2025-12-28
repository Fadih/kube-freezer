import { useState, useEffect, FormEvent } from 'react';
import { api } from '@/services/api';
import type { Template, Schedule } from '@/types';
import { FileText, Play, X, Calendar, Clock, Globe, MessageSquare, RefreshCw, CheckCircle2 } from 'lucide-react';

interface ApplyTemplateModalProps {
  template: Template;
  onClose: () => void;
  onSuccess: (scheduleName?: string) => void;
}

function ApplyTemplateModal({ template, onClose, onSuccess }: ApplyTemplateModalProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Editable schedule fields
  const [scheduleName, setScheduleName] = useState(`Schedule from ${template.name}`);
  
  // Date range fields
  const [startDate, setStartDate] = useState('');
  const [startTime, setStartTime] = useState('00:00');
  const [endDate, setEndDate] = useState('');
  const [endTime, setEndTime] = useState('23:59');
  
  // Cron fields
  const [cron, setCron] = useState('');
  const [namespaces, setNamespaces] = useState<string[]>(template.schedule.namespaces || []);
  const [namespaceInput, setNamespaceInput] = useState('');
  const [message, setMessage] = useState(template.schedule.message || '');
  
  // Helper to parse date string (must be defined before useEffect)
      const parseDateString = (dateStr: string | undefined): { date: string; time: string } => {
        if (!dateStr || typeof dateStr !== 'string') {
          return { date: '', time: '00:00' };
        }
        
        try {
          const date = new Date(dateStr);
          if (!isNaN(date.getTime())) {
            return {
              date: date.toISOString().split('T')[0],
              time: date.toTimeString().slice(0, 5)
            };
          }
        } catch (e) {
          // Not a valid date
        }
        
        const isoMatch = dateStr.match(/^(\d{4})-\d{2}-\d{2}T(\d{2}:\d{2}):\d{2}/);
        if (isoMatch) {
          return {
            date: `${isoMatch[1]}-${dateStr.match(/\d{4}-(\d{2}-\d{2})T/)?.[1] || '01-01'}`,
            time: isoMatch[2]
          };
        }
        
        return { date: '', time: '00:00' };
      };

  // Initialize form fields from template schedule
  useEffect(() => {
    // Initialize cron from template
    if (template.schedule.cron) {
      setCron(template.schedule.cron);
    }
    
    // Initialize start/end dates from template
    if (template.schedule.start) {
      const startParsed = parseDateString(template.schedule.start);
      if (startParsed.date) {
        setStartDate(startParsed.date);
        setStartTime(startParsed.time);
      }
      }
    if (template.schedule.end) {
      const endParsed = parseDateString(template.schedule.end);
      if (endParsed.date) {
        setEndDate(endParsed.date);
        setEndTime(endParsed.time);
      }
    }
    
    // Initialize other fields from template
    if (template.schedule.namespaces && Array.isArray(template.schedule.namespaces)) {
      setNamespaces([...template.schedule.namespaces]);
    }
    if (template.schedule.message) {
      setMessage(template.schedule.message);
    }
  }, [template]);

  const handleAddNamespace = () => {
    if (namespaceInput.trim() && !namespaces.includes(namespaceInput.trim())) {
      setNamespaces([...namespaces, namespaceInput.trim()]);
      setNamespaceInput('');
    }
  };

  const handleRemoveNamespace = (ns: string) => {
    setNamespaces(namespaces.filter((n: string) => n !== ns));
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      // Validate start/end dates
        if (!startDate || !startTime) {
          throw new Error('Start date and time are required');
        }
        if (!endDate || !endTime) {
          throw new Error('End date and time are required');
        }

      // Build start and end ISO strings from local time
        // Create Date objects in local timezone (no 'Z' suffix means local time)
        const startDateTime = new Date(`${startDate}T${startTime}:00`);
        const endDateTime = new Date(`${endDate}T${endTime}:00`);

        if (isNaN(startDateTime.getTime())) {
        throw new Error('Invalid start date/time values');
        }
        if (isNaN(endDateTime.getTime())) {
        throw new Error('Invalid end date/time values');
        }
        if (endDateTime <= startDateTime) {
        throw new Error('End date/time must be after start date/time');
        }

      const startISO = startDateTime.toISOString();
      const endISO = endDateTime.toISOString();

      // Build schedule based on type
      if (!cron) {
        throw new Error('Cron expression is required');
      }

      // Order: name, start, end, cron, namespaces, message
      const schedule: Schedule = {
        name: scheduleName,
        start: startISO,
        end: endISO,
        cron: cron,
        namespaces: namespaces.length > 0 ? namespaces : undefined,
        message: message || undefined,
      };

      // Send the complete schedule directly to backend
      // Backend will store it in freeze_schedule ConfigMap without any processing
      await api.applyTemplate({
        template_name: template.name,
        parameters: {
          // Pass the complete schedule - backend stores it as-is
          override_schedule: schedule,
        },
      });

      // Show success and pass schedule name for notification
      onSuccess(schedule.name);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply template');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <h2 className="text-2xl font-bold text-gray-900">
            Apply Template: {template.name}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-6">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
              {error}
            </div>
          )}

          {/* Schedule Name */}
          <div>
            <label htmlFor="scheduleName" className="block text-sm font-medium text-gray-700 mb-2">
              Schedule Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              id="scheduleName"
              value={scheduleName}
              onChange={(e) => setScheduleName(e.target.value)}
              required
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            />
          </div>

          {/* Cron Expression Field */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              <RefreshCw className="w-4 h-4 inline mr-1" />
              Cron Expression <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              placeholder="0 22 * * *"
              required
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 font-mono"
            />
            <p className="text-xs text-gray-500 mt-1">
              Format: minute hour day-of-month month day-of-week (e.g., "0 22 * * *" = daily at 10 PM)
            </p>
              <p className="text-sm text-gray-600 mt-1 bg-blue-50 p-2 rounded">
              💡 <strong>Cron Expression:</strong> The cron pattern is active between the start and end dates below. 
              When the cron matches, freeze is active until the end date.
              Examples: <code className="bg-gray-100 px-1 rounded">0 22 * * *</code> (daily at 10 PM), 
              <code className="bg-gray-100 px-1 rounded">0 0 * * 6</code> (Saturday at midnight)
            </p>
          </div>

              {/* Start Date/Time */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    <Calendar className="w-4 h-4 inline mr-1" />
                    Start Date *
                  </label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    required
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    <Clock className="w-4 h-4 inline mr-1" />
                    Start Time *
                  </label>
                  <input
                    type="time"
                    value={startTime}
                    onChange={(e) => setStartTime(e.target.value)}
                    required
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                  />
                </div>
              </div>

              {/* End Date/Time */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    <Calendar className="w-4 h-4 inline mr-1" />
                    End Date *
                  </label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    required
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    <Clock className="w-4 h-4 inline mr-1" />
                    End Time *
                  </label>
                  <input
                    type="time"
                    value={endTime}
                    onChange={(e) => setEndTime(e.target.value)}
                    required
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                  />
                </div>
              </div>
          
          <div className="text-sm text-gray-600 bg-blue-50 p-3 rounded-lg">
            <p>💡 <strong>Date Range:</strong> The cron expression will run between the start and end dates/times above. All times are in your local timezone.</p>
          </div>

          {/* Namespaces */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              <Globe className="w-4 h-4 inline mr-1" />
              Namespaces (Optional - leave empty for all namespaces)
            </label>
            <div className="flex gap-2 mb-2">
              <input
                type="text"
                value={namespaceInput}
                onChange={(e) => setNamespaceInput(e.target.value)}
                onKeyPress={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAddNamespace();
                  }
                }}
                placeholder="Enter namespace and press Enter"
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
              <button
                type="button"
                onClick={handleAddNamespace}
                className="px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition-colors"
              >
                Add
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {namespaces.map((ns) => (
                <span
                  key={ns}
                  className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800"
                >
                  {ns}
                  <button
                    type="button"
                    onClick={() => handleRemoveNamespace(ns)}
                    className="ml-2 text-blue-600 hover:text-blue-800"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </span>
              ))}
            </div>
          </div>

          {/* Message */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              <MessageSquare className="w-4 h-4 inline mr-1" />
              Message (Optional)
            </label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            ></textarea>
          </div>

          <div className="flex justify-end space-x-4 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-6 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              disabled={loading}
            >
              {loading ? 'Creating...' : 'Create Schedule'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function Templates() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);

  useEffect(() => {
    loadTemplates();
  }, []);

  const loadTemplates = async (showRefreshing = false) => {
    if (showRefreshing) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    try {
      const data = await api.getTemplates();
      setTemplates(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load templates');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleApply = (template: Template) => {
    setSelectedTemplate(template);
    setIsModalOpen(true);
  };

  const handleModalClose = () => {
    setIsModalOpen(false);
    setSelectedTemplate(null);
  };

  const handleModalSuccess = (scheduleName?: string) => {
    // Show success message
    if (scheduleName) {
      setSuccessMessage(`Schedule "${scheduleName}" created successfully!`);
      // Auto-hide after 5 seconds
      setTimeout(() => {
        setSuccessMessage(null);
      }, 5000);
    }
    loadTemplates(); // Refresh templates after applying
  };

  if (loading) {
    return <div className="text-center py-8">Loading templates...</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Templates</h1>
        <p className="text-gray-600 mt-2">Apply freeze templates to create schedules</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg flex items-center justify-between">
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
            className="text-red-700 hover:text-red-900 ml-4"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {successMessage && (
        <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <CheckCircle2 className="w-5 h-5" />
            <span>{successMessage}</span>
          </div>
          <button
            onClick={() => setSuccessMessage(null)}
            className="text-green-700 hover:text-green-900 ml-4"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      <div className="flex justify-end">
        <button
          onClick={() => loadTemplates(true)}
          disabled={refreshing || loading}
          className="flex items-center space-x-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          <span>{refreshing ? 'Refreshing...' : 'Refresh Templates'}</span>
        </button>
      </div>

      {templates.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center">
          <FileText className="w-16 h-16 text-gray-400 mx-auto mb-4" />
          <p className="text-gray-600">No templates available</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {templates.map((template) => (
            <div key={template.name} className="bg-white rounded-lg shadow p-6">
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h3 className="text-xl font-semibold text-gray-900">{template.name}</h3>
                  {template.description && (
                    <p className="text-gray-600 mt-1">{template.description}</p>
                  )}
                </div>
              </div>

              <div className="mb-4">
                <p className="text-sm text-gray-500 mb-2">Schedule:</p>
                <pre className="text-xs bg-gray-50 p-2 rounded overflow-x-auto">
                  {JSON.stringify(template.schedule, null, 2)}
                </pre>
              </div>

              <button
                onClick={() => handleApply(template)}
                className="w-full flex items-center justify-center space-x-2 bg-blue-600 text-white py-2 px-4 rounded-lg hover:bg-blue-700 transition-colors"
              >
                <Play className="w-4 h-4" />
                <span>Apply Template</span>
              </button>
            </div>
          ))}
        </div>
      )}

      {isModalOpen && selectedTemplate && (
        <ApplyTemplateModal
          template={selectedTemplate}
          onClose={handleModalClose}
          onSuccess={handleModalSuccess}
        />
      )}
    </div>
  );
}
