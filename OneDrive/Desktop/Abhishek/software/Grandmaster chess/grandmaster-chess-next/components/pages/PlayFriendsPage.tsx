'use client';

import React, { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { Chess, Square } from 'chess.js';
import { Users, Link as LinkIcon, Copy, Check, Swords, ShieldCheck, ChevronLeft, Send, Handshake, Flag, RefreshCw } from 'lucide-react';
import { ChessBoard } from '@/components/ChessBoard';
import { ChessClock } from '@/components/ChessClock';
import { MoveHistory } from '@/components/MoveHistory';
import { CapturedPieces } from '@/components/CapturedPieces';
import { GameControls } from '@/components/GameControls';
import { PromotionModal } from '@/components/PromotionModal';
import { GameEndModal } from '@/components/GameEndModal';
import { InviteModal } from '@/components/InviteModal';
import { QuickChat } from '@/components/QuickChat';
import { ThemeSelector } from '@/components/ThemeSelector';
import { SoundSettingsModal } from '@/components/SoundSettingsModal';
import { PieceColor, PieceType, TimeControlPreset, MoveRecord, BoardTheme, MultiplayerRoomState, ChatMessage } from '@/types/chess';
import { DEFAULT_BOARD_THEME } from '@/lib/chess/themes';
import { TIME_CONTROLS } from '@/lib/constants';
import { multiplayerService } from '@/services/multiplayer';
import { sound } from '@/lib/audio';
import { getStoredUserStats, recordGameResult } from '@/lib/storage';
import { Volume2 } from 'lucide-react';

interface PlayFriendsPageProps {
  roomCodeFromUrl?: string;
  navigate?: (path: string) => void;
}

export const PlayFriendsPage: React.FC<PlayFriendsPageProps> = ({
  roomCodeFromUrl,
}) => {
  const router = useRouter();
  const navigate = (path: string) => router.push(path);

  const [tab, setTab] = useState<'create' | 'join'>('create');
  const [timePreset, setTimePreset] = useState<TimeControlPreset>('10+0');
  const [preferredColor, setPreferredColor] = useState<'w' | 'b' | 'random'>('random');
  const [playerName, setPlayerName] = useState(getStoredUserStats().name);
  const [joinCodeInput, setJoinCodeInput] = useState(roomCodeFromUrl || '');
  const [boardTheme, setBoardTheme] = useState<BoardTheme>(DEFAULT_BOARD_THEME);
  const [isSoundModalOpen, setIsSoundModalOpen] = useState(false);

  // Active Multiplayer Room State
  const [roomState, setRoomState] = useState<MultiplayerRoomState | null>(null);
  const [myPlayerId, setMyPlayerId] = useState<string>(getStoredUserStats().id);
  const [myColor, setMyColor] = useState<PieceColor>('w');
  const [isConnected, setIsConnected] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [isInviteModalOpen, setIsInviteModalOpen] = useState(false);

  // Local chess instance for smooth board rendering
  const [chess] = useState<Chess>(() => new Chess());
  const [fen, setFen] = useState<string>(chess.fen());
  const [moves, setMoves] = useState<MoveRecord[]>([]);
  const [lastMove, setLastMove] = useState<{ from: string; to: string } | null>(null);

  // Clocks
  const [whiteTime, setWhiteTime] = useState(600);
  const [blackTime, setBlackTime] = useState(600);

  // Captured
  const [whiteCaptured, setWhiteCaptured] = useState<PieceType[]>([]);
  const [blackCaptured, setBlackCaptured] = useState<PieceType[]>([]);

  // Promotion
  const [pendingPromotion, setPendingPromotion] = useState<{ from: Square; to: Square } | null>(null);

  // Draw offer prompt
  const [incomingDrawOffer, setIncomingDrawOffer] = useState<'w' | 'b' | null>(null);

  // Loading / Error
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // If URL has room code on mount, auto-join
  useEffect(() => {
    if (roomCodeFromUrl && !roomState) {
      handleJoinRoom(roomCodeFromUrl);
    }
  }, [roomCodeFromUrl]);

  // Configure multiplayer callbacks
  useEffect(() => {
    multiplayerService.setCallbacks({
      onConnectionChange: (conn) => setIsConnected(conn),
      onRoomState: (state) => {
        setRoomState(state);
        chess.load(state.fen);
        setFen(state.fen);
        setMoves(state.moves);
        setWhiteTime(state.whiteTime);
        setBlackTime(state.blackTime);

        // Determine user color
        if (state.whitePlayer?.id === myPlayerId) {
          setMyColor('w');
        } else if (state.blackPlayer?.id === myPlayerId) {
          setMyColor('b');
        }

        // Recompute captured pieces from move list
        recomputeCaptured(state.moves);
      },
      onMoveMade: (move, state) => {
        chess.load(state.fen);
        setFen(state.fen);
        setMoves(state.moves);
        setLastMove({ from: move.from, to: move.to });
        setWhiteTime(state.whiteTime);
        setBlackTime(state.blackTime);

        if (move.promotion) sound.playPromotion();
        else if (move.captured) sound.playCapture();
        else if (move.flags && (move.flags.includes('k') || move.flags.includes('q'))) sound.playCastle();
        else sound.playMove();

        if (chess.inCheck()) {
          setTimeout(() => sound.playCheck(), 75);
        }

        recomputeCaptured(state.moves);
      },
      onTimeUpdate: (wTime, bTime) => {
        setWhiteTime(wTime);
        setBlackTime(bTime);
      },
      onDrawOffered: (offeredBy) => {
        if (offeredBy !== myColor) {
          setIncomingDrawOffer(offeredBy);
          sound.playNotification();
        }
      },
      onDrawDeclined: () => {
        alert('Your draw offer was declined.');
      },
      onRematchStarted: (state) => {
        setRoomState(state);
        chess.reset();
        setFen(chess.fen());
        setMoves([]);
        setLastMove(null);
        setWhiteCaptured([]);
        setBlackCaptured([]);
        setIncomingDrawOffer(null);
        sound.playMove();

        // Swap colors
        if (state.whitePlayer?.id === myPlayerId) setMyColor('w');
        else if (state.blackPlayer?.id === myPlayerId) setMyColor('b');
      },
      onChatMessage: (msg) => {
        setChatMessages((prev) => [...prev, msg]);
        if (msg.senderId !== myPlayerId) {
          sound.playNotification();
        }
      },
      onGameOver: (winner, reason, state) => {
        setRoomState(state);
        const opponent = myColor === 'w' ? state.blackPlayer?.name : state.whitePlayer?.name;
        const isWin = winner === myColor;
        const resType = winner === 'draw' ? 'draw' : isWin ? 'win' : 'loss';

        sound.playGameEnd(resType === 'win');

        recordGameResult(
          resType,
          opponent || 'Online Friend',
          1200,
          'friend',
          myColor,
          reason,
          state.moves.length,
          state.pgn,
          state.fen
        );
      },
      onError: (msg) => {
        setErrorMsg(msg);
        setTimeout(() => setErrorMsg(null), 5000);
      },
    });

    return () => {
      multiplayerService.disconnect();
    };
  }, [myPlayerId, myColor]);

  const recomputeCaptured = (moveList: MoveRecord[]) => {
    const wCap: PieceType[] = [];
    const bCap: PieceType[] = [];
    for (const m of moveList) {
      if (m.captured) {
        if (m.color === 'w') wCap.push(m.captured);
        else bCap.push(m.captured);
      }
    }
    setWhiteCaptured(wCap);
    setBlackCaptured(bCap);
  };

  // Create Room via API
  const handleCreateRoom = async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const tc = TIME_CONTROLS[timePreset];
      const res = await fetch('/api/rooms/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          timeControl: tc,
          hostName: playerName.trim() || 'Player 1',
          preferredColor,
        }),
      });
      const data = await res.json();
      if (data.success) {
        setMyPlayerId(data.playerId);
        setMyColor(data.playerColor);
        setRoomState(data.roomState);
        setIsInviteModalOpen(true);
        // Connect WebSocket
        multiplayerService.connect(data.roomCode, data.playerId, playerName.trim() || 'Player 1');
      } else {
        setErrorMsg(data.error || 'Failed to create room');
      }
    } catch (err: any) {
      setErrorMsg(err.message || 'Network error');
    } finally {
      setLoading(false);
    }
  };

  // Join Room
  const handleJoinRoom = async (codeToJoin: string) => {
    const code = codeToJoin.trim().toUpperCase();
    if (!code) {
      setErrorMsg('Please enter a valid 6-character room code');
      return;
    }

    setLoading(true);
    setErrorMsg(null);
    try {
      const res = await fetch(`/api/rooms/${code}`);
      const data = await res.json();
      if (data.success) {
        const stats = getStoredUserStats();
        const pId = stats.id;
        setMyPlayerId(pId);
        setRoomState(data.roomState);
        // Connect WebSocket
        multiplayerService.connect(code, pId, playerName.trim() || 'Guest Player');
      } else {
        setErrorMsg('Game room not found or expired');
      }
    } catch (err: any) {
      setErrorMsg('Unable to join game room');
    } finally {
      setLoading(false);
    }
  };

  // User submits move
  const handlePlayerMove = (from: Square, to: Square, promotion: PieceType = 'q') => {
    if (!roomState || roomState.status !== 'active') return;
    if (chess.turn() !== myColor) return;

    multiplayerService.sendMove(from, to, promotion);
  };

  const handleResign = () => {
    multiplayerService.resign();
  };

  const handleOfferDraw = () => {
    multiplayerService.offerDraw();
  };

  const handleRespondDraw = (accept: boolean) => {
    multiplayerService.respondDraw(accept);
    setIncomingDrawOffer(null);
  };

  const handleRematch = () => {
    multiplayerService.offerRematch();
  };

  const opponentInfo = myColor === 'w' ? roomState?.blackPlayer : roomState?.whitePlayer;

  return (
    <div className="mx-auto max-w-7xl px-3 py-4 sm:px-5 lg:px-6">
      
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-[#3c3934] mb-4">
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              if (roomState) multiplayerService.disconnect();
              navigate('/');
            }}
            className="flex items-center gap-1 text-xs font-semibold text-zinc-400 hover:text-zinc-100 transition-colors"
          >
            <ChevronLeft className="h-4 w-4" />
            <span>Lobby</span>
          </button>
          <span className="text-zinc-600">/</span>
          <div className="flex items-center gap-1.5 text-xs font-bold text-[#81b64c]">
            <Users className="h-4 w-4" />
            <span>Play with Friend {roomState ? `• Room ${roomState.code}` : ''}</span>
          </div>
        </div>

        {/* Board theme & Audio FX selector */}
        <div className="flex items-center gap-2">
          <button
            id="play-friends-sound-settings-btn"
            onClick={() => setIsSoundModalOpen(true)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-semibold rounded-lg border border-[#3c3934] bg-[#262421] text-zinc-300 hover:text-white hover:border-[#81b64c]/60 transition-colors"
            title="Audio FX Settings"
          >
            <Volume2 className="h-3.5 w-3.5 text-[#81b64c]" />
            <span>Audio FX</span>
          </button>
          <ThemeSelector currentTheme={boardTheme} onSelectTheme={setBoardTheme} />
        </div>
      </div>

      {/* ERROR ALERT */}
      {errorMsg && (
        <div className="mb-4 rounded-lg bg-rose-950/60 border border-rose-800 p-3 text-xs font-semibold text-rose-300">
          {errorMsg}
        </div>
      )}

      {/* DRAW OFFER BANNER */}
      {incomingDrawOffer && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[#81b64c]/20 border border-[#81b64c]/50 p-3 shadow-md">
          <div className="flex items-center gap-2 text-[#81b64c] font-bold text-xs">
            <Handshake className="h-4 w-4" />
            <span>Your opponent offered a draw. Accept?</span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => handleRespondDraw(true)}
              className="px-3 py-1 text-xs font-bold rounded bg-[#81b64c] text-zinc-950 hover:bg-[#70a33e]"
            >
              Accept Draw
            </button>
            <button
              onClick={() => handleRespondDraw(false)}
              className="px-3 py-1 text-xs font-semibold rounded bg-[#3c3934] text-zinc-300 hover:bg-[#4a4641]"
            >
              Decline
            </button>
          </div>
        </div>
      )}

      {/* IF NOT IN A ROOM -> CREATE OR JOIN LOBBY */}
      {!roomState ? (
        <div className="max-w-lg mx-auto rounded-xl border border-[#3c3934] bg-[#262421] p-5 sm:p-6 shadow-xl">
          
          {/* Lobby Switcher Tabs */}
          <div className="grid grid-cols-2 gap-1.5 bg-[#161512] p-1 rounded-lg border border-[#3c3934] mb-4">
            <button
              onClick={() => setTab('create')}
              className={`py-2 text-xs font-bold rounded transition-colors ${
                tab === 'create'
                  ? 'bg-[#81b64c] text-zinc-950 shadow-xs'
                  : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              Create Private Game
            </button>
            <button
              onClick={() => setTab('join')}
              className={`py-2 text-xs font-bold rounded transition-colors ${
                tab === 'join'
                  ? 'bg-[#81b64c] text-zinc-950 shadow-xs'
                  : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              Join with Code
            </button>
          </div>

          {/* Player Display Name Input */}
          <div className="mb-4">
            <label className="block text-[10px] font-bold uppercase tracking-wider text-zinc-400 mb-1">
              Your Display Name
            </label>
            <input
              type="text"
              maxLength={20}
              value={playerName}
              onChange={(e) => setPlayerName(e.target.value)}
              placeholder="e.g. GrandmasterTiger"
              className="w-full rounded border border-[#3c3934] bg-[#161512] px-3 py-2 text-xs text-zinc-100 focus:outline-none focus:border-[#81b64c]"
            />
          </div>

          {tab === 'create' ? (
            <>
              {/* Preferred Color */}
              <div className="mb-4">
                <label className="block text-[10px] font-bold uppercase tracking-wider text-zinc-400 mb-1.5">
                  Your Color Preference
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { id: 'random', label: 'Random' },
                    { id: 'w', label: 'White' },
                    { id: 'b', label: 'Black' },
                  ].map((c) => (
                    <button
                      key={c.id}
                      onClick={() => setPreferredColor(c.id as any)}
                      className={`p-2 rounded border text-xs font-semibold text-center transition-colors ${
                        preferredColor === c.id
                          ? 'bg-[#81b64c]/20 border-[#81b64c] text-[#81b64c] font-bold'
                          : 'bg-[#161512] border-[#3c3934] text-zinc-300'
                      }`}
                    >
                      {c.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Time Control */}
              <div className="mb-5">
                <label className="block text-[10px] font-bold uppercase tracking-wider text-zinc-400 mb-1.5">
                  Time Control
                </label>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
                  {(Object.keys(TIME_CONTROLS) as TimeControlPreset[]).map((key) => (
                    <button
                      key={key}
                      onClick={() => setTimePreset(key)}
                      className={`p-2 rounded border text-xs font-semibold text-center transition-colors ${
                        timePreset === key
                          ? 'bg-[#81b64c]/20 border-[#81b64c] text-[#81b64c] font-bold'
                          : 'bg-[#161512] border-[#3c3934] text-zinc-300'
                      }`}
                    >
                      {TIME_CONTROLS[key].label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Create Game Button */}
              <button
                onClick={handleCreateRoom}
                disabled={loading}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#81b64c] py-3 text-sm font-bold text-zinc-950 hover:bg-[#70a33e] shadow-md transition-all active:scale-98 disabled:opacity-50"
              >
                <Swords className="h-4 w-4" />
                <span>{loading ? 'Creating Room...' : 'Create Private Game'}</span>
              </button>
            </>
          ) : (
            /* Join Room Tab */
            <div>
              <div className="mb-5">
                <label className="block text-[10px] font-bold uppercase tracking-wider text-zinc-400 mb-1">
                  Enter 6-Letter Game Code
                </label>
                <input
                  type="text"
                  maxLength={6}
                  value={joinCodeInput}
                  onChange={(e) => setJoinCodeInput(e.target.value.toUpperCase())}
                  placeholder="e.g. X7K9P2"
                  className="w-full rounded border border-[#3c3934] bg-[#161512] px-3.5 py-2.5 font-mono-chess text-center text-lg font-bold tracking-widest text-[#81b64c] uppercase focus:outline-none focus:border-[#81b64c]"
                />
              </div>

              <button
                onClick={() => handleJoinRoom(joinCodeInput)}
                disabled={loading || !joinCodeInput.trim()}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#81b64c] py-3 text-sm font-bold text-zinc-950 hover:bg-[#70a33e] shadow-md transition-all active:scale-98 disabled:opacity-50"
              >
                <Users className="h-4 w-4" />
                <span>{loading ? 'Joining Room...' : 'Join Game Room'}</span>
              </button>
            </div>
          )}
        </div>
      ) : (
        /* LIVE MULTIPLAYER GAME ROOM */
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
          
          {/* LEFT: Chessboard + Clocks */}
          <div className="lg:col-span-8 flex flex-col items-center">
            <div className="w-full max-w-[560px] flex flex-col gap-2.5">
              
              {/* Opponent (Top) Bar */}
              <div className="flex items-center justify-between">
                <ChessClock
                  timeInSeconds={myColor === 'w' ? blackTime : whiteTime}
                  isActive={roomState.status === 'active' && chess.turn() !== myColor}
                  playerName={opponentInfo?.name || 'Waiting for Friend...'}
                  playerColor={myColor === 'w' ? 'b' : 'w'}
                  isUntimed={roomState.timeControl.initialSeconds === 0}
                />
                <CapturedPieces
                  whiteCaptured={myColor === 'w' ? blackCaptured : whiteCaptured}
                  blackCaptured={[]}
                />
              </div>

              {/* Board */}
              <ChessBoard
                chess={chess}
                boardTheme={boardTheme}
                orientation={myColor}
                isInteractive={roomState.status === 'active' && chess.turn() === myColor}
                onMove={(from, to, promo) => handlePlayerMove(from, to, promo || 'q')}
                lastMove={lastMove}
                onPromotionRequired={(from, to) => setPendingPromotion({ from, to })}
              />

              {/* Bottom (My) Player Bar */}
              <div className="flex items-center justify-between">
                <ChessClock
                  timeInSeconds={myColor === 'w' ? whiteTime : blackTime}
                  isActive={roomState.status === 'active' && chess.turn() === myColor}
                  playerName={playerName || 'You'}
                  playerColor={myColor}
                  isUntimed={roomState.timeControl.initialSeconds === 0}
                />
                <CapturedPieces
                  whiteCaptured={myColor === 'w' ? whiteCaptured : blackCaptured}
                  blackCaptured={[]}
                />
              </div>

              {/* Game Controls */}
              <GameControls
                onResign={handleResign}
                onOfferDraw={handleOfferDraw}
                onFlipBoard={() => setMyColor((c) => (c === 'w' ? 'b' : 'w'))}
                onRematch={handleRematch}
                isGameOver={roomState.status !== 'active' && roomState.status !== 'waiting'}
                drawOfferedByMe={roomState.drawOfferedBy === myColor}
              />
            </div>
          </div>

          {/* RIGHT: Move Notation & Quick Chat */}
          <div className="lg:col-span-4 flex flex-col gap-3">
            
            {/* Invite Button Banner */}
            <button
              onClick={() => setIsInviteModalOpen(true)}
              className="flex items-center justify-between p-2.5 rounded-lg bg-[#81b64c]/10 border border-[#81b64c]/30 hover:bg-[#81b64c]/20 text-xs font-bold text-[#81b64c] transition-colors"
            >
              <div className="flex items-center gap-2">
                <LinkIcon className="h-3.5 w-3.5 text-[#81b64c]" />
                <span>Invite Friend (Room: {roomState.code})</span>
              </div>
              <span className="bg-[#81b64c] text-zinc-950 px-2 py-0.5 rounded text-[10px] font-bold">
                Copy Link
              </span>
            </button>

            {/* Move History */}
            <MoveHistory
              moves={moves}
              pgn={roomState.pgn}
            />

            {/* Quick Chat */}
            <QuickChat
              messages={chatMessages}
              onSendMessage={(text, isQuick) => multiplayerService.sendChat(text, isQuick)}
              myPlayerId={myPlayerId}
            />
          </div>
        </div>
      )}


      {/* Promotion Modal */}
      {pendingPromotion && (
        <PromotionModal
          color={myColor}
          onSelect={(piece) => {
            handlePlayerMove(pendingPromotion.from, pendingPromotion.to, piece);
            setPendingPromotion(null);
          }}
          onCancel={() => setPendingPromotion(null)}
        />
      )}

      {/* Invite Modal */}
      {roomState && (
        <InviteModal
          roomCode={roomState.code}
          isOpen={isInviteModalOpen}
          onClose={() => setIsInviteModalOpen(false)}
          isOpponentConnected={!!roomState.whitePlayer && !!roomState.blackPlayer}
        />
      )}

      {/* Game Over Modal */}
      {roomState && roomState.status !== 'active' && roomState.status !== 'waiting' && (
        <GameEndModal
          winner={roomState.winner}
          reason={roomState.winReason || 'Game Finished'}
          myColor={myColor}
          movesCount={moves.length}
          pgn={roomState.pgn}
          onRematch={handleRematch}
          onNewGame={() => setRoomState(null)}
          onClose={() => {}}
        />
      )}

      {/* Sound Settings Modal */}
      <SoundSettingsModal
        isOpen={isSoundModalOpen}
        onClose={() => setIsSoundModalOpen(false)}
      />
    </div>
  );
};
