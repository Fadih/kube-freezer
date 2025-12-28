import { useState, useEffect, FormEvent } from 'react';
import { api } from '@/services/api';
import type { Exemption, ExemptionCreateRequest } from '@/types';
import { Shield, Plus, Trash2, X, CheckCircle2 } from 'lucide-react';

interface CreateExemptionModalProps {
  onClose: () => void;
  onSuccess: () => void;
}

function CreateExemptionModal({ onClose, onSuccess }: CreateExemptionModalProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [namespace, setNamespace] = useState('');
  const [resourceName, setResourceName] = useState('');
  const [durationMinutes, setDurationMinutes] = useState(60);
  const [reason, setReason] = useState('');
  const [approvedBy, setApprovedBy] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (!namespace.trim()) {
        throw new Error('Namespace is required');
      }
      if (!reason.trim()) {
        throw new Error('Reason is required');
      }
      if (!approvedBy.trim()) {
        throw new Error('Approved by is required');
      }
      if (durationMinutes < 1) {
        throw new Error('Duration must be at least 1 minute');
      }

      const request: ExemptionCreateRequest = {
        namespace: namespace.trim(),
        duration_minutes: durationMinutes,
        reason: reason.trim(),
        approved_by: approvedBy.trim(),
        ...(resourceName.trim() && { resource_name: resourceName.trim() }),
      };

      await api.createExemption(request);
      onSuccess();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create exemption');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <h2 className="text-2xl font-bold text-gray-900">Create Exemption</h2>
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

          <div>
            <label htmlFor="namespace" className="block text-sm font-medium text-gray-700 mb-2">
              Namespace <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              id="namespace"
              value={namespace}
              onChange={(e) => setNamespace(e.target.value)}
              required
              placeholder="production"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            />
            <p className="text-xs text-gray-500 mt-1">
              Namespace where the exemption applies
            </p>
          </div>

          <div>
            <label htmlFor="resourceName" className="block text-sm font-medium text-gray-700 mb-2">
              Resource Name (Optional)
            </label>
            <input
              type="text"
              id="resourceName"
              value={resourceName}
              onChange={(e) => setResourceName(e.target.value)}
              placeholder="my-deployment"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            />
            <p className="text-xs text-gray-500 mt-1">
              Leave empty for namespace-wide exemption. If specified, applies only to this resource.
            </p>
          </div>

          <div>
            <label htmlFor="durationMinutes" className="block text-sm font-medium text-gray-700 mb-2">
              Duration (Minutes) <span className="text-red-500">*</span>
            </label>
            <input
              type="number"
              id="durationMinutes"
              value={durationMinutes}
              onChange={(e) => setDurationMinutes(parseInt(e.target.value) || 60)}
              min="1"
              required
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            />
            <p className="text-xs text-gray-500 mt-1">
              How long the exemption should last (e.g., 60 = 1 hour, 120 = 2 hours)
            </p>
          </div>

          <div>
            <label htmlFor="reason" className="block text-sm font-medium text-gray-700 mb-2">
              Reason <span className="text-red-500">*</span>
            </label>
            <textarea
              id="reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
              rows={3}
              placeholder="Emergency security patch deployment"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            />
            <p className="text-xs text-gray-500 mt-1">
              Explain why this exemption is needed
            </p>
          </div>

          <div>
            <label htmlFor="approvedBy" className="block text-sm font-medium text-gray-700 mb-2">
              Approved By <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              id="approvedBy"
              value={approvedBy}
              onChange={(e) => setApprovedBy(e.target.value)}
              required
              placeholder="admin@company.com"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            />
            <p className="text-xs text-gray-500 mt-1">
              Who approved this exemption (email or name)
            </p>
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
              {loading ? 'Creating...' : 'Create Exemption'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function Exemptions() {
  const [exemptions, setExemptions] = useState<Exemption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  useEffect(() => {
    loadExemptions();
  }, []);

  const loadExemptions = async () => {
    try {
      const data = await api.getExemptions();
      setExemptions(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load exemptions');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to delete this exemption?')) {
      return;
    }

    try {
      await api.deleteExemption(id);
      await loadExemptions();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete exemption');
    }
  };

  const handleModalClose = () => {
    setIsModalOpen(false);
  };

  const handleModalSuccess = () => {
    setSuccessMessage('Exemption created successfully!');
    setTimeout(() => {
      setSuccessMessage(null);
    }, 5000);
    loadExemptions();
  };

  if (loading) {
    return <div className="text-center py-8">Loading exemptions...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Exemptions</h1>
          <p className="text-gray-600 mt-2">Manage temporary deployment exemptions</p>
        </div>
        <button
          onClick={() => setIsModalOpen(true)}
          className="flex items-center space-x-2 bg-blue-600 text-white py-2 px-4 rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          <span>Create Exemption</span>
        </button>
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

      {exemptions.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center">
          <Shield className="w-16 h-16 text-gray-400 mx-auto mb-4" />
          <p className="text-gray-600">No exemptions configured</p>
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  ID
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Namespace
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Resource
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Duration
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Reason
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Approved By
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Expires
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {exemptions.map((exemption) => (
                <tr key={exemption.id}>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm font-mono text-gray-900">{exemption.id.substring(0, 8)}...</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-gray-900">{exemption.namespace}</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-gray-900">
                      {exemption.resource_name || <span className="text-gray-400 italic">All resources</span>}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-gray-900">{exemption.duration_minutes} min</div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm text-gray-900 max-w-xs truncate" title={exemption.reason}>
                      {exemption.reason}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-gray-900">{exemption.approved_by}</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-gray-900">
                      {new Date(exemption.expires_at).toLocaleString()}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`px-2 py-1 text-xs rounded-full ${
                      exemption.used
                        ? 'bg-gray-100 text-gray-800'
                        : new Date(exemption.expires_at) > new Date()
                        ? 'bg-green-100 text-green-800'
                        : 'bg-red-100 text-red-800'
                    }`}>
                      {exemption.used ? 'Used' : new Date(exemption.expires_at) > new Date() ? 'Active' : 'Expired'}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <button
                      onClick={() => handleDelete(exemption.id)}
                      className="text-red-600 hover:text-red-900 flex items-center space-x-1 ml-auto"
                    >
                      <Trash2 className="w-4 h-4" />
                      <span>Delete</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {isModalOpen && (
        <CreateExemptionModal
          onClose={handleModalClose}
          onSuccess={handleModalSuccess}
        />
      )}
    </div>
  );
}

