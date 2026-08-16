import { MultiplayerRoomState, ChatMessage } from '@/types/chess';

export interface MultiplayerCallbacks {
  onRoomState?: (state: MultiplayerRoomState, message?: string) => void;
  onMoveMade?: (move: any, state: MultiplayerRoomState) => void;
  onGameOver?: (winner: string | null, reason: string, state: MultiplayerRoomState) => void;
  onTimeUpdate?: (whiteTime: number, blackTime: number) => void;
  onDrawOffered?: (offeredBy: 'w' | 'b', state: MultiplayerRoomState) => void;
  onDrawDeclined?: (state: MultiplayerRoomState) => void;
  onRematchOffered?: (offeredBy: 'w' | 'b', state: MultiplayerRoomState) => void;
  onRematchStarted?: (state: MultiplayerRoomState) => void;
  onChatMessage?: (msg: ChatMessage) => void;
  onError?: (errorMessage: string) => void;
  onConnectionChange?: (connected: boolean) => void;
}

class MultiplayerService {
  private ws: WebSocket | null = null;
  private callbacks: MultiplayerCallbacks = {};
  private currentRoomCode: string | null = null;
  private currentPlayerId: string | null = null;
  private currentPlayerName: string = 'Player';
  private reconnectAttempts = 0;
  private shouldReconnect = true;

  public setCallbacks(cbs: MultiplayerCallbacks) {
    this.callbacks = { ...this.callbacks, ...cbs };
  }

  public connect(roomCode: string, playerId: string, playerName: string) {
    this.currentRoomCode = roomCode;
    this.currentPlayerId = playerId;
    this.currentPlayerName = playerName;
    this.shouldReconnect = true;

    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // ignore
      }
    }

    // The Next.js app is statically/server rendered and does not itself host a
    // WebSocket server. Real-time multiplayer is served by the standalone
    // ws-server (see /ws-server in the project root) via NEXT_PUBLIC_WS_URL.
    // Falls back to same-origin /ws for local development if unset.
    const envWsUrl = process.env.NEXT_PUBLIC_WS_URL;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = envWsUrl || `${protocol}//${window.location.host}/ws`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.callbacks.onConnectionChange?.(true);
      // Send join room
      this.send({
        type: 'JOIN_ROOM',
        roomCode: this.currentRoomCode,
        playerId: this.currentPlayerId,
        playerName: this.currentPlayerName,
      });
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.handleMessage(data);
      } catch (err) {
        console.error('Error handling WS message:', err);
      }
    };

    this.ws.onclose = () => {
      this.callbacks.onConnectionChange?.(false);
      if (this.shouldReconnect && this.reconnectAttempts < 5) {
        this.reconnectAttempts++;
        setTimeout(() => {
          if (this.currentRoomCode && this.currentPlayerId) {
            this.connect(this.currentRoomCode, this.currentPlayerId, this.currentPlayerName);
          }
        }, 1500 * this.reconnectAttempts);
      }
    };

    this.ws.onerror = (err) => {
      console.warn('WebSocket encountered error:', err);
    };
  }

  private handleMessage(data: any) {
    switch (data.type) {
      case 'ROOM_STATE':
        this.callbacks.onRoomState?.(data.roomState, data.message);
        break;
      case 'MOVE_MADE':
        this.callbacks.onMoveMade?.(data.move, data.roomState);
        break;
      case 'GAME_OVER':
        this.callbacks.onGameOver?.(data.winner, data.reason, data.roomState);
        break;
      case 'TIME_UPDATE':
        this.callbacks.onTimeUpdate?.(data.whiteTime, data.blackTime);
        break;
      case 'DRAW_OFFERED':
        this.callbacks.onDrawOffered?.(data.offeredBy, data.roomState);
        break;
      case 'DRAW_DECLINED':
        this.callbacks.onDrawDeclined?.(data.roomState);
        break;
      case 'REMATCH_OFFERED':
        this.callbacks.onRematchOffered?.(data.offeredBy, data.roomState);
        break;
      case 'REMATCH_STARTED':
        this.callbacks.onRematchStarted?.(data.roomState);
        break;
      case 'CHAT_MESSAGE':
        this.callbacks.onChatMessage?.(data.message);
        break;
      case 'ERROR':
        this.callbacks.onError?.(data.message);
        break;
    }
  }

  public sendMove(from: string, to: string, promotion?: string) {
    this.send({
      type: 'MAKE_MOVE',
      from,
      to,
      promotion,
      playerId: this.currentPlayerId,
    });
  }

  public resign() {
    this.send({
      type: 'RESIGN',
      playerId: this.currentPlayerId,
    });
  }

  public offerDraw() {
    this.send({
      type: 'OFFER_DRAW',
      playerId: this.currentPlayerId,
    });
  }

  public respondDraw(accept: boolean) {
    this.send({
      type: 'RESPOND_DRAW',
      accept,
      playerId: this.currentPlayerId,
    });
  }

  public offerRematch() {
    this.send({
      type: 'OFFER_REMATCH',
      playerId: this.currentPlayerId,
    });
  }

  public sendChat(text: string, isQuickMsg = false) {
    this.send({
      type: 'CHAT_MESSAGE',
      playerId: this.currentPlayerId,
      playerName: this.currentPlayerName,
      text,
      isQuickMsg,
    });
  }

  public disconnect() {
    this.shouldReconnect = false;
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  private send(data: any) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }
}

export const multiplayerService = new MultiplayerService();
