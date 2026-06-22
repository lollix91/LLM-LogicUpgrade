import { useState, useEffect } from 'react';
import { X, Download, Check, Loader2, Cloud, HardDrive, Key, Search } from 'lucide-react';
import {
  getModelInfo,
  changeModel,
  pullModel,
  switchBackend,
  updateApiKey,
  searchModels,
} from '../api/client';

interface SettingsModalProps {
  onClose: () => void;
}

export function SettingsModal({ onClose }: SettingsModalProps) {
  const [backend, setBackend] = useState<string>('');
  const [apiKeySet, setApiKeySet] = useState(false);
  const [currentModel, setCurrentModel] = useState('');
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [newModelName, setNewModelName] = useState('');
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [pulling, setPulling] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [savingKey, setSavingKey] = useState(false);
  const [searching, setSearching] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    loadModelInfo();
  }, []);

  async function loadModelInfo() {
    try {
      const info = await getModelInfo();
      setBackend(info.backend);
      setApiKeySet(info.api_key_set);
      setCurrentModel(info.current_model);
      setAvailableModels(info.available_models);
    } catch {
      setMessage('Failed to connect to orchestrator');
    }
  }

  async function handleSwitchBackend(newBackend: string) {
    if (newBackend === backend) return;
    setSwitching(true);
    setMessage('');
    try {
      const result = await switchBackend(newBackend);
      setBackend(result.backend);
      setApiKeySet(result.api_key_set);
      setCurrentModel(result.current_model);
      setAvailableModels(result.available_models || []);
      setMessage(`Switched to ${newBackend === 'ollama' ? 'Local (Ollama)' : 'OpenRouter (Cloud)'}`);
    } catch (err) {
      setMessage(`Failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setSwitching(false);
    }
  }

  async function handleSaveApiKey() {
    if (!apiKeyInput.trim()) return;
    setSavingKey(true);
    setMessage('');
    try {
      await updateApiKey(apiKeyInput.trim());
      setApiKeySet(true);
      setApiKeyInput('');
      setMessage('API key updated successfully');
      await loadModelInfo();
    } catch (err) {
      setMessage(`Failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setSavingKey(false);
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

  async function handleSearchModels() {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setMessage('');
    try {
      const result = await searchModels(searchQuery.trim());
      setSearchResults(result.models);
    } catch (err) {
      setMessage(`Failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg shadow-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-gray-800 sticky top-0 bg-gray-900 z-10">
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
          {/* Backend Mode Selection */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-3">
              Backend Mode
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => handleSwitchBackend('ollama')}
                disabled={switching}
                className={`flex items-center gap-2 px-4 py-3 rounded-lg border transition-colors disabled:opacity-50 ${
                  backend === 'ollama'
                    ? 'border-primary-500 bg-primary-600/20 text-primary-400'
                    : 'border-gray-700 bg-gray-800 text-gray-400 hover:border-gray-600'
                }`}
              >
                <HardDrive className="w-5 h-5" />
                <div className="text-left">
                  <div className="text-sm font-medium">Local</div>
                  <div className="text-xs opacity-70">Ollama</div>
                </div>
                {backend === 'ollama' && <Check className="w-4 h-4 ml-auto" />}
              </button>
              <button
                onClick={() => handleSwitchBackend('openrouter')}
                disabled={switching}
                className={`flex items-center gap-2 px-4 py-3 rounded-lg border transition-colors disabled:opacity-50 ${
                  backend === 'openrouter'
                    ? 'border-primary-500 bg-primary-600/20 text-primary-400'
                    : 'border-gray-700 bg-gray-800 text-gray-400 hover:border-gray-600'
                }`}
              >
                <Cloud className="w-5 h-5" />
                <div className="text-left">
                  <div className="text-sm font-medium">Cloud</div>
                  <div className="text-xs opacity-70">OpenRouter</div>
                </div>
                {backend === 'openrouter' && <Check className="w-4 h-4 ml-auto" />}
              </button>
            </div>
            {switching && (
              <div className="flex items-center gap-2 mt-2 text-xs text-gray-500">
                <Loader2 className="w-3 h-3 animate-spin" /> Switching backend...
              </div>
            )}
          </div>

          {/* OpenRouter API Key */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              OpenRouter API Key
            </label>
            <div className="flex items-center gap-2 mb-2">
              <Key className="w-4 h-4 text-gray-500" />
              <span className={`text-xs ${apiKeySet ? 'text-green-400' : 'text-gray-500'}`}>
                {apiKeySet ? 'API key is set' : 'No API key set'}
              </span>
            </div>
            <div className="flex gap-2">
              <div className="flex-1 relative">
                <input
                  type={showApiKey ? 'text' : 'password'}
                  value={apiKeyInput}
                  onChange={e => setApiKeyInput(e.target.value)}
                  placeholder="sk-or-v1-..."
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-500 outline-none focus:border-primary-500 transition-colors pr-16"
                />
                <button
                  onClick={() => setShowApiKey(!showApiKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-500 hover:text-gray-300"
                >
                  {showApiKey ? 'Hide' : 'Show'}
                </button>
              </div>
              <button
                onClick={handleSaveApiKey}
                disabled={savingKey || !apiKeyInput.trim()}
                className="flex items-center gap-1 px-3 py-2 rounded-lg bg-primary-600 hover:bg-primary-700 text-white text-sm disabled:opacity-50 transition-colors"
              >
                {savingKey ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                Save
              </button>
            </div>
          </div>

          {/* Current Model */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Active Model
            </label>
            <div className="px-3 py-2 bg-gray-800 rounded-lg text-sm text-primary-400 font-mono">
              {currentModel || 'Loading...'}
            </div>
          </div>

          {/* Model Search (especially useful for OpenRouter with 100+ models) */}
          {backend === 'openrouter' && (
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Search Models
              </label>
              <div className="flex gap-2">
                <div className="flex-1 relative">
                  <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleSearchModels()}
                    placeholder="e.g. qwen, llama, mistral..."
                    className="w-full pl-8 pr-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-500 outline-none focus:border-primary-500 transition-colors"
                  />
                </div>
                <button
                  onClick={handleSearchModels}
                  disabled={searching || !searchQuery.trim()}
                  className="flex items-center gap-1 px-3 py-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-white text-sm disabled:opacity-50 transition-colors"
                >
                  {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                  Search
                </button>
              </div>
              {searchResults.length > 0 && (
                <div className="space-y-1 max-h-32 overflow-y-auto mt-2">
                  {searchResults.map(model => (
                    <div
                      key={model}
                      className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-gray-800 transition-colors"
                    >
                      <span className="text-sm text-gray-300 font-mono truncate">{model}</span>
                      {model === currentModel ? (
                        <Check className="w-4 h-4 text-green-400 flex-shrink-0" />
                      ) : (
                        <button
                          onClick={() => handleChangeModel(model)}
                          disabled={loading}
                          className="text-xs px-2 py-1 rounded bg-primary-600 hover:bg-primary-700 text-white disabled:opacity-50 transition-colors flex-shrink-0"
                        >
                          Use
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Available Models */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Available Models {availableModels.length > 0 && `(${availableModels.length})`}
            </label>
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {availableModels.map(model => (
                <div
                  key={model}
                  className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-gray-800 transition-colors"
                >
                  <span className="text-sm text-gray-300 font-mono truncate">{model}</span>
                  {model === currentModel ? (
                    <Check className="w-4 h-4 text-green-400 flex-shrink-0" />
                  ) : (
                    <button
                      onClick={() => handleChangeModel(model)}
                      disabled={loading}
                      className="text-xs px-2 py-1 rounded bg-primary-600 hover:bg-primary-700 text-white disabled:opacity-50 transition-colors flex-shrink-0"
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

          {/* Pull New Model (Ollama only) */}
          {backend === 'ollama' && (
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
          )}

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
