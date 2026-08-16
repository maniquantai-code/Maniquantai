'use client';

import React, { useState } from 'react';
import { Copy, Check, Users, Link as LinkIcon, ShieldCheck } from 'lucide-react';

interface InviteModalProps {
  roomCode: string;
  isOpen: boolean;
  onClose: () => void;
  isOpponentConnected: boolean;
}

export const InviteModal: React.FC<InviteModalProps> = ({
  roomCode,
  isOpen,
  onClose,
  isOpponentConnected,
}) => {
  const [copiedLink, setCopiedLink] = useState(false);
  const [copiedCode, setCopiedCode] = useState(false);

  if (!isOpen) return null;

  const inviteUrl = `${window.location.origin}/play/friends/${roomCode}`;

  const handleCopyLink = () => {
    navigator.clipboard.writeText(inviteUrl);
    setCopiedLink(true);
    setTimeout(() => setCopiedLink(false), 2000);
  };

  const handleCopyCode = () => {
    navigator.clipboard.writeText(roomCode);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-xs p-4 animate-in fade-in duration-150">
      <div className="relative w-full max-w-md rounded-xl border border-[#3c3934] bg-[#262421] p-6 shadow-2xl text-center">
        {/* Header Icon */}
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-[#81b64c] text-zinc-950 shadow-md">
          <Users className="h-6 w-6 text-zinc-950" />
        </div>

        <h3 className="text-lg font-extrabold text-zinc-100 mb-1">
          Invite Your Friend
        </h3>
        <p className="text-xs text-zinc-400 mb-5">
          Share this invite link or game code with your friend to start playing in real-time.
        </p>

        {/* Room Code Display */}
        <div className="mb-4 rounded-lg bg-[#161512] border border-[#3c3934] p-3.5">
          <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider block mb-1">
            Game Room Code
          </span>
          <div className="flex items-center justify-center gap-3">
            <span className="font-mono-chess text-2xl font-extrabold text-[#81b64c] tracking-widest">
              {roomCode}
            </span>
            <button
              onClick={handleCopyCode}
              aria-label="Copy game room code"
              className="flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded bg-[#3c3934] hover:bg-[#4a4641] text-zinc-200 border border-[#3c3934] transition-colors"
            >
              {copiedCode ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
              <span>{copiedCode ? 'Copied' : 'Copy'}</span>
            </button>
          </div>
        </div>

        {/* Shareable Invite URL */}
        <div className="mb-5">
          <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider block mb-1 text-left">
            Direct Invitation Link
          </span>
          <div className="flex items-center gap-2">
            <input
              type="text"
              readOnly
              value={inviteUrl}
              className="w-full rounded border border-[#3c3934] bg-[#161512] px-2.5 py-1.5 text-xs font-mono text-zinc-300 focus:outline-none"
            />
            <button
              onClick={handleCopyLink}
              aria-label="Copy invitation link"
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded bg-[#81b64c] text-zinc-950 hover:bg-[#70a33e] transition-colors whitespace-nowrap"
            >
              {copiedLink ? <Check className="h-3.5 w-3.5 text-zinc-950" /> : <LinkIcon className="h-3.5 w-3.5" />}
              <span>{copiedLink ? 'Copied!' : 'Copy Link'}</span>
            </button>
          </div>
        </div>

        {/* Waiting / Connected Status Indicator */}
        <div className="mb-5 flex items-center justify-center gap-2 text-xs">
          {isOpponentConnected ? (
            <div className="flex items-center gap-2 text-emerald-400 font-semibold bg-emerald-950/40 border border-emerald-800/60 px-3 py-1 rounded-full">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
              <span>Opponent Connected! Game in Progress.</span>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-zinc-300 bg-[#161512] border border-[#3c3934] px-3 py-1 rounded-full">
              <span className="h-2 w-2 rounded-full bg-[#81b64c] animate-ping" />
              <span>Waiting for friend to connect...</span>
            </div>
          )}
        </div>

        {/* Close Button */}
        <button
          onClick={onClose}
          className="w-full rounded-lg bg-[#3c3934] py-2 text-xs font-semibold text-zinc-200 hover:bg-[#4a4641] transition-colors border border-[#3c3934]"
        >
          Close & Return to Board
        </button>
      </div>
    </div>
  );
};

