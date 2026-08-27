"use client";
import { Check } from "lucide-react";

export type StageStatus = "complete" | "current" | "upcoming";

export interface Stage {
  label: string;
  status: StageStatus;
}

export function PipelineStepper({ stages }: { stages: Stage[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-bg-panel p-4 sm:p-5">
      <div className="flex min-w-[420px] items-center">
        {stages.map((stage, i) => (
          <div key={stage.label} className="flex flex-1 items-center last:flex-none">
            <div className="flex flex-col items-center gap-2">
              <div
                className={[
                  "flex h-8 w-8 sm:h-9 sm:w-9 items-center justify-center rounded-full border text-sm font-medium",
                  stage.status === "complete" && "border-accent bg-accent-dim text-accent",
                  stage.status === "current" && "border-accent text-accent",
                  stage.status === "upcoming" && "border-border text-text-faint",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                {stage.status === "complete" ? <Check size={16} /> : i + 1}
              </div>
              <span
                className={[
                  "whitespace-nowrap text-xs",
                  stage.status === "upcoming" ? "text-text-faint" : "text-text-muted",
                ].join(" ")}
              >
                {stage.label}
              </span>
            </div>
            {i < stages.length - 1 && (
              <div
                className={[
                  "mx-2 h-px flex-1",
                  stage.status === "complete" ? "bg-accent/40" : "bg-border",
                ].join(" ")}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
