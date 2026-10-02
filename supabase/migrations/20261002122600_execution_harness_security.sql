-- ManiQuantAI execution harness security boundary.
-- The tables below are intentionally append-oriented and user-scoped.

CREATE TABLE IF NOT EXISTS execution_audit (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  strategy_id uuid NOT NULL REFERENCES strategies(strategy_id) ON DELETE CASCADE,
  signal_key text NOT NULL,
  action text NOT NULL CHECK (action IN ('allowed','rejected','queued','filled','cancelled','blocked')),
  symbol text NOT NULL,
  timeframe text NOT NULL,
  side text,
  consensus double precision,
  risk_pct double precision,
  reason text,
  checks jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(strategy_id, signal_key)
);

CREATE INDEX IF NOT EXISTS execution_audit_user_idx ON execution_audit(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS execution_audit_strategy_idx ON execution_audit(strategy_id, created_at DESC);

ALTER TABLE execution_audit ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users read own execution audit" ON execution_audit;
CREATE POLICY "Users read own execution audit"
  ON execution_audit FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "Service role manages execution audit" ON execution_audit;
CREATE POLICY "Service role manages execution audit"
  ON execution_audit FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- Per-user/strategy emergency stop. Default is safe: disabled means no block.
CREATE TABLE IF NOT EXISTS execution_controls (
  user_id uuid NOT NULL,
  strategy_id uuid NOT NULL REFERENCES strategies(strategy_id) ON DELETE CASCADE,
  kill_switch boolean NOT NULL DEFAULT false,
  max_open_positions integer NOT NULL DEFAULT 1 CHECK (max_open_positions BETWEEN 0 AND 20),
  daily_loss_limit_pct double precision NOT NULL DEFAULT -5.0 CHECK (daily_loss_limit_pct < 0 AND daily_loss_limit_pct >= -100),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(user_id, strategy_id)
);

ALTER TABLE execution_controls ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users read own execution controls" ON execution_controls;
CREATE POLICY "Users read own execution controls"
  ON execution_controls FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "Users update own execution controls" ON execution_controls;
CREATE POLICY "Users update own execution controls"
  ON execution_controls FOR UPDATE TO authenticated
  USING ((SELECT auth.uid()) = user_id)
  WITH CHECK ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "Service role manages execution controls" ON execution_controls;
CREATE POLICY "Service role manages execution controls"
  ON execution_controls FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- Safe initial control row can be created by the service after strategy approval.
