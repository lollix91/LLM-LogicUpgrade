import { User, Bot, Zap } from 'lucide-react';
import { type Message } from '../api/client';

interface MessageBubbleProps {
  message: Message;
  onTraceClick?: () => void;
}

export function MessageBubble({ message, onTraceClick }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary-600/20 flex items-center justify-center">
          <Bot className="w-4 h-4 text-primary-400" />
        </div>
      )}

      <div className={`max-w-[80%] ${isUser ? 'order-first' : ''}`}>
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
            isUser
              ? 'bg-primary-600 text-white rounded-br-sm'
              : 'bg-gray-800 text-gray-200 rounded-bl-sm'
          }`}
        >
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>

        {onTraceClick && (
          <button
            onClick={onTraceClick}
            className={`mt-1.5 flex items-center gap-1 text-xs transition-colors ${
              message.has_logic
                ? 'text-amber-400 hover:text-amber-300'
                : 'text-primary-400 hover:text-primary-300'
            }`}
          >
            <Zap className="w-3 h-3" />
            {message.has_logic ? 'View logic trace' : 'View reasoning trace'}
          </button>
        )}
      </div>

      {isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gray-700 flex items-center justify-center">
          <User className="w-4 h-4 text-gray-300" />
        </div>
      )}
    </div>
  );
}
