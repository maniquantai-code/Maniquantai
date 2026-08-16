import express from 'express';
import http from 'http';
import cors from 'cors';
import { WebSocketServer, WebSocket } from 'ws';
import { Chess } from 'chess.js';

// Standalone real-time multiplayer server for Grandmaster Chess Online.
// The Next.js app (in the project root) handles all page rendering, SEO,
// and the blog. This service ONLY handles WebSocket game rooms and is
// deployed separately (Railway/Render/Fly/a small VPS all work well).
// Point the Next.js app at this server via NEXT_PUBLIC_WS_URL.

interface ServerPlayer {
  id: string;
  name: string;
  color: 'w' | 'b';
  ws?: WebSocket;
  connected: boolean;
  timeRemaining: number;
}

interface ServerRoom {
  code: string;
  chess: Chess;
  whitePlayer: ServerPlayer | null;
  blackPlayer: ServerPlayer | null;
  spectators: Array<{ id: string; name: string; ws: WebSocket }>;
  timeControl: {
    id: string;
    label: string;
    initialSeconds: number;
    incrementSeconds: number;
  };
  status: 'waiting' | 'active' | 'checkmate' | 'stalemate' | 'draw' | 'resigned' | 'timeout';
  winner: 'w' | 'b' | 'draw' | null;
  winReason?: string;
  drawOfferedBy: 'w' | 'b' | null;
  rematchOfferedBy: 'w' | 'b' | null;
  lastMoveTimestamp: number;
  timerInterval?: NodeJS.Timeout;
  moves: Array<{
    san: string;
    from: string;
    to: string;
    piece: string;
    color: string;
    captured?: string;
    promotion?: string;
  }>;
  createdAt: number;
}

const rooms = new Map<string, ServerRoom>();

function generateRoomCode(): string {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let code = '';
  for (let i = 0; i < 6; i++) {
    code += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return rooms.has(code) ? generateRoomCode() : code;
}

function broadcastToRoom(room: ServerRoom, type: string, payload: any) {
  const message = JSON.stringify({ type, ...payload });

  if (room.whitePlayer?.ws && room.whitePlayer.ws.readyState === WebSocket.OPEN) {
    room.whitePlayer.ws.send(message);
  }
  if (room.blackPlayer?.ws && room.blackPlayer.ws.readyState === WebSocket.OPEN) {
    room.blackPlayer.ws.send(message);
  }
  for (const spec of room.spectators) {
    if (spec.ws && spec.ws.readyState === WebSocket.OPEN) {
      spec.ws.send(message);
    }
  }
}

function getRoomPublicState(room: ServerRoom) {
  return {
    code: room.code,
    fen: room.chess.fen(),
    pgn: room.chess.pgn(),
    turn: room.chess.turn(),
    inCheck: room.chess.inCheck(),
    status: room.status,
    winner: room.winner,
    winReason: room.winReason,
    timeControl: room.timeControl,
    whitePlayer: room.whitePlayer
      ? {
          id: room.whitePlayer.id,
          name: room.whitePlayer.name,
          color: 'w',
          connected: room.whitePlayer.connected,
          timeRemaining: room.whitePlayer.timeRemaining,
        }
      : null,
    blackPlayer: room.blackPlayer
      ? {
          id: room.blackPlayer.id,
          name: room.blackPlayer.name,
          color: 'b',
          connected: room.blackPlayer.connected,
          timeRemaining: room.blackPlayer.timeRemaining,
        }
      : null,
    drawOfferedBy: room.drawOfferedBy,
    rematchOfferedBy: room.rematchOfferedBy,
    moves: room.moves,
    lastMove: room.moves.length > 0 ? room.moves[room.moves.length - 1] : null,
  };
}

function startRoomTimer(room: ServerRoom) {
  if (room.timerInterval) {
    clearInterval(room.timerInterval);
  }
  if (room.timeControl.initialSeconds <= 0) return; // untimed

  room.lastMoveTimestamp = Date.now();
  room.timerInterval = setInterval(() => {
    if (room.status !== 'active') {
      if (room.timerInterval) clearInterval(room.timerInterval);
      return;
    }

    const currentTurn = room.chess.turn();
    const activePlayer = currentTurn === 'w' ? room.whitePlayer : room.blackPlayer;

    if (activePlayer) {
      activePlayer.timeRemaining = Math.max(0, activePlayer.timeRemaining - 1);
      if (activePlayer.timeRemaining <= 0) {
        room.status = 'timeout';
        room.winner = currentTurn === 'w' ? 'b' : 'w';
        room.winReason = 'Won on time';
        if (room.timerInterval) clearInterval(room.timerInterval);
        broadcastToRoom(room, 'GAME_OVER', {
          roomState: getRoomPublicState(room),
          winner: room.winner,
          reason: 'Time expired',
        });
      } else {
        broadcastToRoom(room, 'TIME_UPDATE', {
          whiteTime: room.whitePlayer?.timeRemaining ?? 0,
          blackTime: room.blackPlayer?.timeRemaining ?? 0,
        });
      }
    }
  }, 1000);
}

async function startServer() {
  const app = express();
  const PORT = Number(process.env.PORT) || 3001;

  app.use(cors());
  app.use(express.json());

  // Health check
  app.get('/api/health', (req, res) => {
    res.json({ status: 'ok', activeRooms: rooms.size, timestamp: Date.now() });
  });

  // Create room endpoint
  app.post('/api/rooms/create', (req, res) => {
    const { timeControl, hostName, preferredColor } = req.body;
    const code = generateRoomCode();
    const chess = new Chess();

    const initialSeconds = timeControl?.initialSeconds ?? 600;
    const incrementSeconds = timeControl?.incrementSeconds ?? 0;

    let assignedColor: 'w' | 'b' = 'w';
    if (preferredColor === 'b') {
      assignedColor = 'b';
    } else if (preferredColor === 'random') {
      assignedColor = Math.random() < 0.5 ? 'w' : 'b';
    }

    const hostPlayer: ServerPlayer = {
      id: `player_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
      name: hostName || 'Player 1',
      color: assignedColor,
      connected: false,
      timeRemaining: initialSeconds,
    };

    const room: ServerRoom = {
      code,
      chess,
      whitePlayer: assignedColor === 'w' ? hostPlayer : null,
      blackPlayer: assignedColor === 'b' ? hostPlayer : null,
      spectators: [],
      timeControl: {
        id: timeControl?.id || '10+0',
        label: timeControl?.label || '10 min Rapid',
        initialSeconds,
        incrementSeconds,
      },
      status: 'waiting',
      winner: null,
      drawOfferedBy: null,
      rematchOfferedBy: null,
      lastMoveTimestamp: Date.now(),
      moves: [],
      createdAt: Date.now(),
    };

    rooms.set(code, room);

    res.json({
      success: true,
      roomCode: code,
      playerId: hostPlayer.id,
      playerColor: assignedColor,
      roomState: getRoomPublicState(room),
    });
  });

  // Get room info endpoint
  app.get('/api/rooms/:code', (req, res) => {
    const code = req.params.code.toUpperCase();
    const room = rooms.get(code);
    if (!room) {
      return res.status(404).json({ error: 'Game room not found' });
    }
    res.json({ success: true, roomState: getRoomPublicState(room) });
  });

  const server = http.createServer(app);

  // WebSocket Server
  const wss = new WebSocketServer({ server, path: '/ws' });

  wss.on('connection', (ws, req) => {
    let currentRoomCode: string | null = null;
    let currentPlayerId: string | null = null;

    ws.on('message', (rawData) => {
      try {
        const data = JSON.parse(rawData.toString());
        const { type } = data;

        // 1. JOIN ROOM
        if (type === 'JOIN_ROOM') {
          const code = (data.roomCode || '').toUpperCase();
          const playerId = data.playerId;
          const playerName = data.playerName || 'Guest Player';
          const room = rooms.get(code);

          if (!room) {
            ws.send(JSON.stringify({ type: 'ERROR', message: 'Room not found or expired.' }));
            return;
          }

          currentRoomCode = code;
          currentPlayerId = playerId;

          // Check if reconnecting existing player
          if (room.whitePlayer && room.whitePlayer.id === playerId) {
            room.whitePlayer.ws = ws;
            room.whitePlayer.connected = true;
          } else if (room.blackPlayer && room.blackPlayer.id === playerId) {
            room.blackPlayer.ws = ws;
            room.blackPlayer.connected = true;
          } else if (!room.whitePlayer) {
            // Assign white
            room.whitePlayer = {
              id: playerId,
              name: playerName,
              color: 'w',
              ws,
              connected: true,
              timeRemaining: room.timeControl.initialSeconds,
            };
          } else if (!room.blackPlayer) {
            // Assign black
            room.blackPlayer = {
              id: playerId,
              name: playerName,
              color: 'b',
              ws,
              connected: true,
              timeRemaining: room.timeControl.initialSeconds,
            };
          } else {
            // Room is full -> add as spectator
            room.spectators.push({ id: playerId, name: playerName, ws });
          }

          // If both players joined, activate game
          if (room.whitePlayer && room.blackPlayer && room.status === 'waiting') {
            room.status = 'active';
            startRoomTimer(room);
          }

          broadcastToRoom(room, 'ROOM_STATE', {
            roomState: getRoomPublicState(room),
            message: `${playerName} connected.`,
          });
        }

        // 2. MAKE MOVE
        else if (type === 'MAKE_MOVE') {
          if (!currentRoomCode) return;
          const room = rooms.get(currentRoomCode);
          if (!room || room.status !== 'active') return;

          const { from, to, promotion, playerId } = data;
          const currentTurn = room.chess.turn();

          const isWhiteTurn = currentTurn === 'w';
          const activePlayer = isWhiteTurn ? room.whitePlayer : room.blackPlayer;

          if (!activePlayer || activePlayer.id !== playerId) {
            ws.send(JSON.stringify({ type: 'ERROR', message: 'Not your turn!' }));
            return;
          }

          try {
            // Server-side authoritative validation
            const move = room.chess.move({ from, to, promotion: promotion || 'q' });
            if (!move) {
              ws.send(JSON.stringify({ type: 'ERROR', message: 'Illegal move rejected by server' }));
              return;
            }

            // Apply increment
            activePlayer.timeRemaining += room.timeControl.incrementSeconds;

            room.moves.push({
              san: move.san,
              from: move.from,
              to: move.to,
              piece: move.piece,
              color: move.color,
              captured: move.captured,
              promotion: move.promotion,
            });

            // Check game termination states
            if (room.chess.isCheckmate()) {
              room.status = 'checkmate';
              room.winner = move.color;
              room.winReason = 'Checkmate';
              if (room.timerInterval) clearInterval(room.timerInterval);
            } else if (room.chess.isStalemate()) {
              room.status = 'stalemate';
              room.winner = 'draw';
              room.winReason = 'Stalemate';
              if (room.timerInterval) clearInterval(room.timerInterval);
            } else if (room.chess.isThreefoldRepetition()) {
              room.status = 'draw';
              room.winner = 'draw';
              room.winReason = 'Threefold repetition';
              if (room.timerInterval) clearInterval(room.timerInterval);
            } else if (room.chess.isInsufficientMaterial()) {
              room.status = 'draw';
              room.winner = 'draw';
              room.winReason = 'Insufficient material';
              if (room.timerInterval) clearInterval(room.timerInterval);
            }

            broadcastToRoom(room, 'MOVE_MADE', {
              move,
              roomState: getRoomPublicState(room),
            });
          } catch (err: any) {
            ws.send(JSON.stringify({ type: 'ERROR', message: 'Illegal move: ' + (err.message || '') }));
          }
        }

        // 3. RESIGN
        else if (type === 'RESIGN') {
          if (!currentRoomCode) return;
          const room = rooms.get(currentRoomCode);
          if (!room || room.status !== 'active') return;

          const resigningPlayerColor = room.whitePlayer?.id === data.playerId ? 'w' : 'b';
          room.status = 'resigned';
          room.winner = resigningPlayerColor === 'w' ? 'b' : 'w';
          room.winReason = `${resigningPlayerColor === 'w' ? 'White' : 'Black'} resigned`;
          if (room.timerInterval) clearInterval(room.timerInterval);

          broadcastToRoom(room, 'GAME_OVER', {
            roomState: getRoomPublicState(room),
            winner: room.winner,
            reason: room.winReason,
          });
        }

        // 4. OFFER DRAW
        else if (type === 'OFFER_DRAW') {
          if (!currentRoomCode) return;
          const room = rooms.get(currentRoomCode);
          if (!room || room.status !== 'active') return;

          const offeringColor = room.whitePlayer?.id === data.playerId ? 'w' : 'b';
          room.drawOfferedBy = offeringColor;

          broadcastToRoom(room, 'DRAW_OFFERED', {
            offeredBy: offeringColor,
            roomState: getRoomPublicState(room),
          });
        }

        // 5. RESPOND DRAW
        else if (type === 'RESPOND_DRAW') {
          if (!currentRoomCode) return;
          const room = rooms.get(currentRoomCode);
          if (!room || room.status !== 'active') return;

          if (data.accept) {
            room.status = 'draw';
            room.winner = 'draw';
            room.winReason = 'Draw by mutual agreement';
            if (room.timerInterval) clearInterval(room.timerInterval);

            broadcastToRoom(room, 'GAME_OVER', {
              roomState: getRoomPublicState(room),
              winner: 'draw',
              reason: 'Draw agreed',
            });
          } else {
            room.drawOfferedBy = null;
            broadcastToRoom(room, 'DRAW_DECLINED', {
              roomState: getRoomPublicState(room),
            });
          }
        }

        // 6. REMATCH
        else if (type === 'OFFER_REMATCH') {
          if (!currentRoomCode) return;
          const room = rooms.get(currentRoomCode);
          if (!room) return;

          const requestingColor = room.whitePlayer?.id === data.playerId ? 'w' : 'b';

          if (room.rematchOfferedBy && room.rematchOfferedBy !== requestingColor) {
            // Both agree to rematch -> swap colors & reset board
            const oldWhite = room.whitePlayer;
            const oldBlack = room.blackPlayer;

            room.whitePlayer = oldBlack ? { ...oldBlack, color: 'w', timeRemaining: room.timeControl.initialSeconds } : null;
            room.blackPlayer = oldWhite ? { ...oldWhite, color: 'b', timeRemaining: room.timeControl.initialSeconds } : null;
            room.chess = new Chess();
            room.moves = [];
            room.status = 'active';
            room.winner = null;
            room.winReason = undefined;
            room.drawOfferedBy = null;
            room.rematchOfferedBy = null;

            startRoomTimer(room);

            broadcastToRoom(room, 'REMATCH_STARTED', {
              roomState: getRoomPublicState(room),
            });
          } else {
            room.rematchOfferedBy = requestingColor;
            broadcastToRoom(room, 'REMATCH_OFFERED', {
              offeredBy: requestingColor,
              roomState: getRoomPublicState(room),
            });
          }
        }

        // 7. CHAT MESSAGE
        else if (type === 'CHAT_MESSAGE') {
          if (!currentRoomCode) return;
          const room = rooms.get(currentRoomCode);
          if (!room) return;

          const chatMessage = {
            id: `msg_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
            senderId: data.playerId,
            senderName: data.playerName || 'Player',
            text: (data.text || '').slice(0, 120),
            timestamp: Date.now(),
            isQuickMsg: !!data.isQuickMsg,
          };

          broadcastToRoom(room, 'CHAT_MESSAGE', { message: chatMessage });
        }
      } catch (err) {
        console.error('WebSocket message parsing error:', err);
      }
    });

    ws.on('close', () => {
      if (currentRoomCode && currentPlayerId) {
        const room = rooms.get(currentRoomCode);
        if (room) {
          if (room.whitePlayer?.id === currentPlayerId) {
            room.whitePlayer.connected = false;
          } else if (room.blackPlayer?.id === currentPlayerId) {
            room.blackPlayer.connected = false;
          }
          broadcastToRoom(room, 'PLAYER_DISCONNECTED', {
            playerId: currentPlayerId,
            roomState: getRoomPublicState(room),
          });
        }
      }
    });
  });

  server.listen(PORT, '0.0.0.0', () => {
    console.log(`Grandmaster Chess server running on port ${PORT}`);
  });
}

startServer();
