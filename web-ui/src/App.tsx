import { useState, useCallback } from 'react';
import { Sidebar } from './components/Sidebar';
import { ChatPanel } from './components/ChatPanel';
import { ReasoningPanel } from './components/ReasoningPanel';
import { SettingsModal } from './components/SettingsModal';
import { sendMessage, getConversation, type Message, type PipelineStep } from './api/client';

export default function App() {
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [activeTrace, setActiveTrace] = useState<PipelineStep[] | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [sidebarRefresh, setSidebarRefresh] = useState(0);

  const handleSend = useCallback(async (text: string) => {
    const userMsg: Message = { role: 'user', content: text };
    setMessages(prev => [...prev, userMsg]);
    setIsLoading(true);
    setActiveTrace(null);

    try {
      const response = await sendMessage(text, conversationId);
      setConversationId(response.conversation_id);

      const assistantMsg: Message = {
        role: 'assistant',
        content: response.answer,
        reasoning_trace: response.reasoning_trace,
        has_logic: response.has_logic,
      };
      setMessages(prev => [...prev, assistantMsg]);
      setActiveTrace(response.reasoning_trace);
      setSidebarRefresh(prev => prev + 1);
    } catch (err) {
      const errorMsg: Message = {
        role: 'assistant',
        content: `Error: ${err instanceof Error ? err.message : 'Unknown error'}`,
      };
      setMessages(prev => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  }, [conversationId]);

  const handleSelectConversation = useCallback(async (id: string) => {
    try {
      const conv = await getConversation(id);
      setConversationId(id);
      setMessages(conv.messages);
      setActiveTrace(null);
    } catch (err) {
      console.error('Failed to load conversation:', err);
    }
  }, []);

  const handleNewChat = useCallback(() => {
    setConversationId(undefined);
    setMessages([]);
    setActiveTrace(null);
  }, []);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        onSelectConversation={handleSelectConversation}
        onNewChat={handleNewChat}
        onOpenSettings={() => setShowSettings(true)}
        activeConversationId={conversationId}
        refreshTrigger={sidebarRefresh}
      />

      <div className="flex flex-1 min-w-0">
        <ChatPanel
          messages={messages}
          isLoading={isLoading}
          onSend={handleSend}
          onTraceClick={setActiveTrace}
        />

        {activeTrace && (
          <ReasoningPanel
            trace={activeTrace}
            onClose={() => setActiveTrace(null)}
          />
        )}
      </div>

      {showSettings && (
        <SettingsModal onClose={() => setShowSettings(false)} />
      )}
    </div>
  );
}
