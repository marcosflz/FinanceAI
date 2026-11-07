"use client";

import type { KeyboardEvent } from "react";
import { cn } from "@/lib/utils";

/** Control segmentado para 2–5 opciones visibles a la vez. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  "aria-label": ariaLabel,
  className,
}: {
  options: Array<{ value: T; label: string; disabled?: boolean; title?: string }>;
  value: T;
  onChange: (value: T) => void;
  "aria-label": string;
  className?: string;
}) {
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const enabled = options.filter((option) => !option.disabled);
    const index = enabled.findIndex((option) => option.value === value);
    const delta = event.key === "ArrowRight" ? 1 : -1;
    const next = enabled[(index + delta + enabled.length) % enabled.length];
    if (next) {
      onChange(next.value);
      event.currentTarget
        .querySelector<HTMLButtonElement>(`[data-value="${next.value}"]`)
        ?.focus();
    }
  }

  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={cn("inline-flex h-8 items-center gap-0.5 rounded-lg bg-muted p-0.5", className)}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            data-value={option.value}
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            disabled={option.disabled}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={cn(
              "h-full rounded-md px-2.5 text-[11px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
              selected
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
