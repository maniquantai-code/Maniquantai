"use client";
import { AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip } from "recharts";

export interface DrawdownPoint {
  month: string;
  drawdown: number;
}

export function DrawdownChart({ data }: { data: DrawdownPoint[] }) {
  return (
    <div className="rounded-lg border border-border bg-bg-panel p-5">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-text-muted">Drawdown curve</span>
        <span className="text-xs text-text-faint">12-month backtest</span>
      </div>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="ddGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#22c55e" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#22c55e" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="month"
              tick={{ fill: "#6b7280", fontSize: 11 }}
              axisLine={{ stroke: "#2a2d31" }}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: "#6b7280", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              contentStyle={{
                background: "#16181b",
                border: "1px solid #2a2d31",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: "#9ca3af" }}
            />
            <Area
              type="monotone"
              dataKey="drawdown"
              stroke="#22c55e"
              strokeWidth={2}
              fill="url(#ddGradient)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
