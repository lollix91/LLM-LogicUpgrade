import { useState, useEffect } from 'react';
import { X, Download, Check, Loader2 } from 'lucide-react';
import { getModelInfo, changeModel, pullModel } from '../api/client';

interface SettingsModalProps {
  onClose: () => void;
}

export function SettingsModal({ onClose }: SettingsModalProps) {
  const [currentModel, setCurrentModel] = useState('');
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [newModelName, setNewModelName] = useState('');
  const [loading, setLoading] = useState(false);
  const [pulling, setPulling] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    loadModelInfo();
  }, []);

  async function loadModelInfo() {
    try {
      const info = await getModelInfo();
      setCurrentModel(info.current_model);
      setAvailableModels(info.available_models);
    } catch {
      setMessage('Failed to connect to orchestrator');
    }
  }

  async function handleChangeModel(model: string) {
    setLoading(true);
    setMessage('');
    try {
      await changeModel(model);
      setCurrentModel(model);
      setMessage(`Switched to ${model}`);
    } catch (err) {
      setMessage(`Failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setLoading(false);
    }
  }

  async function handlePullModel() {
    if (!newModelName.trim()) return;
    setPulling(true);
    setMessage(`Pulling ${newModelName}... this may take a while`);
    try {
      await pullModel(newModelName.trim());
      setMessage(`Successfully pulled ${newModelName}`);
      setNewModelName('');
      await loadModelInfo();
    } catch (err) {
      setMessage(`Failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setPulling(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-gray-800">
          <h2 className="text-lg font-semibold text-white">Settings</h2>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-gray-800 text-gray-400 hover:text-gray-200 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-6">
          {/* Current Model */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Active Model
            </label>
            <div className="px-3 py-2 bg-gray-800 rounded-lg text-sm text-primary-400 font-mono">
              {currentModel || 'Loading...'}
            </div>
          </div>

          {/* Available Models */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Available Models
            </label>
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {availableModels.map(model => (
                <div
                  key={model}
                  className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-gray-800 transition-colors"
                >
                  <span className="text-sm text-gray-300 font-mono">{model}</span>
                  {model === currentModel ? (
                    <Check className="w-4 h-4 text-green-400" />
                  ) : (
                    <button
                      onClick={() => handleChangeModel(model)}
                      disabled={loading}
                      className="text-xs px-2 py-1 rounded bg-primary-600 hover:bg-primary-700 text-white disabled:opacity-50 transition-colors"
                    >
                      Use
                    </button>
                  )}
                </div>
              ))}
              {availableModels.length === 0 && (
                <p className="text-sm text-gray-500 py-2">No models found</p>
              )}
            </div>
          </div>

          {/* Pull New Model */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Pull New Model
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={newModelName}
                onChange={e => setNewModelName(e.target.value)}
                placeholder="e.g. mistral:7b, llama3.1:8b"
                className="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-500 outline-none focus:border-primary-500 transition-colors"
              />
              <button
                onClick={handlePullModel}
                disabled={pulling || !newModelName.trim()}
                className="flex items-center gap-1 px-3 py-2 rounded-lg bg-primary-600 hover:bg-primary-700 text-white text-sm disabled:opacity-50 transition-colors"
              >
                {pulling ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                Pull
              </button>
            </div>
          </div>

          {/* Status message */}
          {message && (
            <p className="text-sm text-gray-400 bg-gray-800/50 rounded-lg px-3 py-2">
              {message}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
