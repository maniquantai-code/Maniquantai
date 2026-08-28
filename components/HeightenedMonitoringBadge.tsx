"use client";

export function HeightenedMonitoringBadge({ day, totalDays }: { day: number; totalDays: number }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-warn/30 bg-warn-dim px-3 py-1 text-xs font-medium text-warn">
      <span className="h-1.5 w-1.5 rounded-full bg-warn" />
      Heightened Monitoring — Day {day} of {totalDays}
    </span>
  );
}
