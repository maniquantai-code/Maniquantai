'use client';

import React, { useState } from 'react';
import { MessageSquare, Send } from 'lucide-react';
import { ChatMessage } from '@/types/chess';
import { QUICK_CHAT_MESSAGES } from '@/lib/constants';

interface QuickChatProps {
  messages: ChatMessage[];
  onSendMessage: (text: string, isQuickMsg?: boolean) => void;
  myPlayerId: string;
}

export const QuickChat: React.FC<QuickChatProps> = ({
  messages,
  onSendMessage,
  myPlayerId,
}) => {
  const [inputText, setInputText] = useState('');
  const [isOpen, setIsOpen] = useState(false);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim()) return;
    onSendMessage(inputText.trim(), false);
    setInputText('');
  };

  return (
    <div className="rounded-lg border border-[#3c3934] bg-[#262421] p-2.5 shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5 text-xs font-bold text-zinc-200 uppercase tracking-wider">
          <MessageSquare className="h-3.5 w-3.5 text-[#81b64c]" />
          <span>In-Game Chat</span>
        </div>
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="text-[11px] text-zinc-400 hover:text-zinc-200 font-medium"
        >
          {isOpen ? 'Minimize' : 'Expand'}
        </button>
      </div>

      {/* Message history */}
      <div className="h-28 overflow-y-auto space-y-1.5 p-1.5 text-xs border border-[#3c3934] rounded bg-[#161512]/60 mb-2">
        {messages.length === 0 ? (
          <div className="h-full flex items-center justify-center text-zinc-400 italic text-[11px]">
            No messages yet. Send a quick hello!
          </div>
        ) : (
          messages.map((msg) => {
            const isMe = msg.senderId === myPlayerId;
            return (
              <div
                key={msg.id}
                className={`flex flex-col ${isMe ? 'items-end' : 'items-start'}`}
              >
                <div
                  className={`rounded px-2 py-1 max-w-[85%] text-xs leading-relaxed ${
                    isMe
                      ? 'bg-[#81b64c]/20 text-[#81b64c] border border-[#81b64c]/30 font-medium'
                      : 'bg-[#3c3934] text-zinc-200 border border-[#3c3934]'
                  }`}
                >
                  <span className="text-[10px] font-bold block text-zinc-400 mb-0.5">
                    {msg.senderName}
                  </span>
                  {msg.text}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Quick Message Chips */}
      <div className="flex flex-wrap gap-1 mb-2">
        {QUICK_CHAT_MESSAGES.slice(0, 4).map((msg) => (
          <button
            key={msg}
            onClick={() => onSendMessage(msg, true)}
            className="text-[10px] font-medium bg-[#3c3934] hover:bg-[#4a4641] text-zinc-300 px-2 py-0.5 rounded border border-[#3c3934] transition-colors whitespace-nowrap"
          >
            {msg}
          </button>
        ))}
      </div>

      {/* Text Input */}
      <form onSubmit={handleSend} className="flex gap-1.5">
        <input
          type="text"
          maxLength={100}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          placeholder="Send a message..."
          className="flex-1 bg-[#161512] border border-[#3c3934] rounded px-2 py-1 text-xs text-zinc-200 focus:outline-none focus:border-[#81b64c]"
        />
        <button
          type="submit"
          disabled={!inputText.trim()}
          className="bg-[#81b64c] hover:bg-[#70a33e] disabled:opacity-40 text-zinc-950 font-bold px-2.5 py-1 rounded transition-colors"
        >
          <Send className="h-3.5 w-3.5" />
        </button>
      </form>
    </div>
  );
};

