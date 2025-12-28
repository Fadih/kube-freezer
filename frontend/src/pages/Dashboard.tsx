import { useState, useEffect } from 'react';
import { api } from '@/services/api';
import type { FreezeStatus } from '@/types';
import { AlertCircle, CheckCircle, Clock, Calendar } from 'lucide-react';

export default function Dashboard() {
  const [status, setStatus] = useState<FreezeStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState<Date>(new Date());

  useEffect(() => {
    loadData();
    // Refresh every 30 seconds
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, []);

  // Update current time every second
  useEffect(() => {
    const timeInterval = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
    return () => clearInterval(timeInterval);
  }, []);

  const loadData = async () => {
    try {
      const statusData = await api.getFreezeStatus();
      setStatus(statusData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  // Helper to format date
  const formatDate = (dateStr: string): string => {
    try {
      return new Date(dateStr).toLocaleString();
    } catch {
      return dateStr;
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
        {error}
      </div>
    );
  }

  if (!status) {
    return null;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-600 mt-2">Current freeze status and overview</p>
        </div>
        <div className="flex items-center space-x-2 bg-blue-50 px-4 py-2 rounded-lg border border-blue-200">
          <Clock className="w-5 h-5 text-blue-600" />
          <div className="text-right">
            <div className="text-sm text-gray-600">Current Time</div>
            <div className="text-lg font-semibold text-blue-900 font-mono">
              {currentTime.toLocaleString()}
            </div>
          </div>
        </div>
      </div>

      {/* Freeze Status Card */}
      <div className={`rounded-lg shadow-lg p-6 ${
        status.active ? 'bg-red-50 border-2 border-red-200' : 'bg-green-50 border-2 border-green-200'
      }`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-4">
            {status.active ? (
              <AlertCircle className="w-8 h-8 text-red-600" />
            ) : (
              <CheckCircle className="w-8 h-8 text-green-600" />
            )}
            <div>
              <h2 className="text-2xl font-bold text-gray-900">
                Freeze {status.active ? 'Active' : 'Inactive'}
              </h2>
              {status.active && status.freeze_message && (
                <p className="text-gray-700 mt-1">{status.freeze_message}</p>
              )}
              {!status.active && (
                <p className="text-gray-600 mt-1">No freeze is currently active. Deployments are allowed.</p>
              )}
            </div>
          </div>
        </div>

        {status.active && (
          <div className="mt-4 space-y-2">
            {status.freeze_until && (
              <div className="flex items-center space-x-2 text-gray-700">
                <Clock className="w-5 h-5" />
                <span>
                  Until: {new Date(status.freeze_until).toLocaleString()}
                </span>
              </div>
            )}
            {status.remaining && (
              <div className="flex items-center space-x-2 text-gray-700">
                <Calendar className="w-5 h-5" />
                <span>Remaining: {status.remaining}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Currently Active Schedules */}
      {status.schedules && status.schedules.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-lg shadow p-6">
          <h3 className="text-xl font-semibold text-red-900 mb-4 flex items-center space-x-2">
            <AlertCircle className="w-6 h-6" />
            <span>Currently Active Schedules ({status.schedules.length})</span>
          </h3>
          <div className="space-y-2">
            {status.schedules.map((schedule) => (
              <div key={schedule.name} className="bg-white border border-red-200 rounded-lg p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h4 className="font-medium text-gray-900">{schedule.name}</h4>
                    <p className="text-sm text-gray-600">
                      {schedule.start && schedule.end 
                        ? `${formatDate(schedule.start)} - ${formatDate(schedule.end)}`
                        : schedule.cron 
                        ? `Cron: ${schedule.cron}`
                        : 'Schedule active'}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Quick Actions */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-xl font-semibold text-gray-900 mb-4">Quick Actions</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <a
            href="/templates"
            className="p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <h4 className="font-medium text-gray-900">Apply Template</h4>
            <p className="text-sm text-gray-600 mt-1">Quickly apply a freeze template</p>
          </a>
          <a
            href="/schedules"
            className="p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <h4 className="font-medium text-gray-900">View Schedules</h4>
            <p className="text-sm text-gray-600 mt-1">Manage all freeze schedules</p>
          </a>
          <a
            href="/exemptions"
            className="p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <h4 className="font-medium text-gray-900">Create Exemption</h4>
            <p className="text-sm text-gray-600 mt-1">Allow deployments during freeze</p>
          </a>
        </div>
      </div>
    </div>
  );
}

