-- ManiQuantAI Agent Team Live Trading Schema v2
-- Run in Supabase SQL editor or as a migration

-- ─── 1. Extend strategies table ────────────────────────────────────────────
ALTER TABLE strategies
  ADD COLUMN IF NOT EXISTS active_agents   text[]    DEFAULT ARRAY['momentum','mean_reversion','breakout','sentiment'],
  ADD COLUMN IF NOT EXISTS strategy_type   text      DEFAULT 'multi_signal',
  ADD COLUMN IF NOT EXISTS live_symbol     text,
  ADD COLUMN IF NOT EXISTS live_timeframe  text      DEFAULT '15m',
  ADD COLUMN IF NOT EXISTS live_approved   boolean   DEFAULT false,
  ADD COLUMN IF NOT EXISTS live_paused     boolean   DEFAULT false,
  ADD COLUMN IF NOT EXISTS last_scan_at    timestamptz;

-- ─── 2. Agent scan log ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_scans (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id    uuid  NOT NULL REFERENCES strategies(strategy_id) ON DELETE CASCADE,
  user_id        uuid  NOT NULL,
  scanned_at     timestamptz NOT NULL DEFAULT now(),
  symbol         text  NOT NULL,
  timeframe      text  NOT NULL,
  bars_scanned   int,
  consensus      float,
  execute        boolean DEFAULT false,
  reason         text,
  signals        jsonb,                 -- array of AgentSignal
  order_queued   boolean DEFAULT false,
  job_id         text,
  created_at     timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_scans_strategy_idx ON agent_scans(strategy_id, scanned_at DESC);
CREATE INDEX IF NOT EXISTS agent_scans_user_idx     ON agent_scans(user_id, scanned_at DESC);

-- RLS
ALTER TABLE agent_scans ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "Users see own scans" ON agent_scans
  FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY IF NOT EXISTS "Service role manages scans" ON agent_scans
  FOR ALL USING (auth.role() = 'service_role');

-- ─── 3. Live positions tracker ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS live_positions (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id    uuid  NOT NULL REFERENCES strategies(strategy_id) ON DELETE CASCADE,
  user_id        uuid  NOT NULL,
  symbol         text  NOT NULL,
  direction      text  NOT NULL CHECK (direction IN ('long','short')),
  entry_price    float,
  volume         float,
  stop_loss      float,
  take_profit    float,
  mt5_ticket     bigint,
  opened_at      timestamptz DEFAULT now(),
  closed_at      timestamptz,
  close_price    float,
  pnl_pct        float,
  status         text DEFAULT 'open' CHECK (status IN ('open','closed','error')),
  agent_reason   text,
  created_at     timestamptz DEFAULT now(),
  updated_at     timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS live_positions_strategy_idx ON live_positions(strategy_id, status);
CREATE INDEX IF NOT EXISTS live_positions_user_idx     ON live_positions(user_id, status);

ALTER TABLE live_positions ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "Users see own positions" ON live_positions
  FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY IF NOT EXISTS "Service role manages positions" ON live_positions
  FOR ALL USING (auth.role() = 'service_role');

-- ─── 4. Daily P&L tracker ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_pnl (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id    uuid  NOT NULL REFERENCES strategies(strategy_id) ON DELETE CASCADE,
  user_id        uuid  NOT NULL,
  trading_date   date  NOT NULL,
  start_equity   float,
  end_equity     float,
  pnl_amount     float,
  pnl_pct        float,
  trades_taken   int DEFAULT 0,
  wins           int DEFAULT 0,
  losses         int DEFAULT 0,
  max_drawdown_pct float DEFAULT 0,
  created_at     timestamptz DEFAULT now(),
  updated_at     timestamptz DEFAULT now(),
  UNIQUE (strategy_id, trading_date)
);

ALTER TABLE daily_pnl ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "Users see own daily pnl" ON daily_pnl
  FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY IF NOT EXISTS "Service role manages daily pnl" ON daily_pnl
  FOR ALL USING (auth.role() = 'service_role');

-- ─── 5. Extend mt5_bridge_jobs for agent team ──────────────────────────────
ALTER TABLE mt5_bridge_jobs
  ADD COLUMN IF NOT EXISTS agent_signals  jsonb,
  ADD COLUMN IF NOT EXISTS consensus      float,
  ADD COLUMN IF NOT EXISTS signal_source  text DEFAULT 'agent_team';

-- ─── 6. Helper function — get agent team summary for a strategy ─────────────
CREATE OR REPLACE FUNCTION get_agent_summary(p_strategy_id uuid, p_limit int DEFAULT 20)
RETURNS TABLE (
  scanned_at  timestamptz,
  symbol      text,
  consensus   float,
  execute     boolean,
  signal_count int
)
LANGUAGE sql STABLE SECURITY DEFINER AS $$
  SELECT
    scanned_at,
    symbol,
    consensus,
    execute,
    jsonb_array_length(COALESCE(signals, '[]'::jsonb)) as signal_count
  FROM agent_scans
  WHERE strategy_id = p_strategy_id
  ORDER BY scanned_at DESC
  LIMIT p_limit;
$$;

-- ─── 7. Daily loss limit gate ───────────────────────────────────────────────
CREATE OR REPLACE FUNCTION check_daily_loss_limit(
  p_strategy_id uuid,
  p_user_id     uuid,
  p_loss_limit  float DEFAULT -0.05   -- -5%
)
RETURNS boolean     -- true = trading allowed, false = paused
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  v_pnl_pct float;
BEGIN
  SELECT pnl_pct INTO v_pnl_pct
  FROM daily_pnl
  WHERE strategy_id = p_strategy_id
    AND user_id     = p_user_id
    AND trading_date = CURRENT_DATE;

  IF v_pnl_pct IS NULL THEN RETURN true; END IF;
  RETURN v_pnl_pct > p_loss_limit;
END;
$$;

COMMENT ON TABLE agent_scans    IS 'Every agent team evaluation run — stores all 5 agent signals + portfolio decision';
COMMENT ON TABLE live_positions IS 'Live and closed positions opened by the agent team through MT5';
COMMENT ON TABLE daily_pnl      IS 'Daily P&L summary per strategy — used for loss-limit gate';
