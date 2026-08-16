import { UserStats, SavedGameSummary } from '@/types/chess';

const STATS_STORAGE_KEY = 'grandmaster_chess_user_stats';
const PREFS_STORAGE_KEY = 'grandmaster_chess_user_prefs';

export function getStoredUserStats(): UserStats {
  if (typeof window === 'undefined') {
    return createDefaultStats();
  }
  try {
    const raw = localStorage.getItem(STATS_STORAGE_KEY);
    if (raw) {
      return JSON.parse(raw);
    }
  } catch {
    // fallback
  }
  const defaultStats = createDefaultStats();
  saveUserStats(defaultStats);
  return defaultStats;
}

function createDefaultStats(): UserStats {
  const randomSuffix = Math.floor(1000 + Math.random() * 9000);
  return {
    id: `guest_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
    name: `Player_${randomSuffix}`,
    rating: 1200,
    gamesPlayed: 0,
    wins: 0,
    losses: 0,
    draws: 0,
    history: [],
  };
}

export function saveUserStats(stats: UserStats): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(STATS_STORAGE_KEY, JSON.stringify(stats));
  } catch {
    // ignore
  }
}

export function updateUserName(newName: string): UserStats {
  const stats = getStoredUserStats();
  stats.name = newName.trim();
  saveUserStats(stats);
  return stats;
}

export function resetUserStats(): UserStats {
  const fresh = createDefaultStats();
  saveUserStats(fresh);
  return fresh;
}

export function recordGameResult(
  result: 'win' | 'loss' | 'draw',
  opponentName: string,
  opponentRating: number,
  mode: SavedGameSummary['mode'],
  playerColor: SavedGameSummary['playerColor'],
  reason: string,
  movesCount: number,
  pgn: string,
  fenFinal: string
): UserStats {
  const stats = getStoredUserStats();

  // Simple standard Elo update formula (K-factor = 32)
  const K = 32;
  const expectedScore = 1 / (1 + Math.pow(10, (opponentRating - stats.rating) / 400));
  const actualScore = result === 'win' ? 1 : result === 'draw' ? 0.5 : 0;
  const ratingDelta = Math.round(K * (actualScore - expectedScore));
  
  stats.rating = Math.max(100, stats.rating + ratingDelta);
  stats.gamesPlayed += 1;
  if (result === 'win') stats.wins += 1;
  else if (result === 'loss') stats.losses += 1;
  else stats.draws += 1;

  const summary: SavedGameSummary = {
    id: `game_${Date.now()}`,
    date: new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
    mode,
    opponentName,
    playerColor,
    result,
    reason,
    movesCount,
    pgn,
    fenFinal,
  };

  stats.history = [summary, ...stats.history].slice(0, 50); // keep last 50 games
  saveUserStats(stats);
  return stats;
}

export function downloadPgnFile(pgn: string, filename = 'game.pgn') {
  const blob = new Blob([pgn], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
