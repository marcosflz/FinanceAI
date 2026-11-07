"use client";

import { useRef, useState } from "react";
import { Check, Palette } from "lucide-react";
import { Popover } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export const COLOR_SWATCHES = [
  "#64748b", "#ef4444", "#f97316", "#f59e0b", "#eab308", "#84cc16",
  "#22c55e", "#10b981", "#14b8a6", "#06b6d4", "#0ea5e9", "#3b82f6",
  "#6366f1", "#8b5cf6", "#a855f7", "#d946ef", "#ec4899", "#f43f5e",
];

const HEX = /^#[0-9a-f]{6}$/i;

/** Color con paleta predefinida, hexadecimal y selector libre. */
export function ColorField({
  value,
  onChange,
  "aria-label": ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  "aria-label": string;
}) {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(value);
  const valid = HEX.test(value);

  function pick(color: string) {
    onChange(color.toLowerCase());
    setText(color.toLowerCase());
  }

  return (
    <>
      <button
        ref={anchorRef}
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          setText(value);
          setOpen(!open);
        }}
        className={cn(
          "inline-flex h-9 w-full items-center gap-2 rounded-lg border bg-card px-2.5 text-sm transition-colors hover:border-muted-foreground/40",
          open ? "border-accent" : "border-input",
        )}
      >
        <span
          className="size-5 shrink-0 rounded-md border border-black/10"
          style={{ backgroundColor: valid ? value : "transparent" }}
          aria-hidden
        />
        <span className="num truncate text-foreground">{value || "Sin color"}</span>
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchorRef={anchorRef} ariaLabel={ariaLabel} className="w-[15.5rem] p-3">
        <div className="grid grid-cols-6 gap-1.5">
          {COLOR_SWATCHES.map((color) => {
            const selected = color.toLowerCase() === value.toLowerCase();
            return (
              <button
                key={color}
                type="button"
                aria-label={color}
                aria-pressed={selected}
                onClick={() => {
                  pick(color);
                  setOpen(false);
                }}
                className="flex size-8 items-center justify-center rounded-lg ring-offset-2 ring-offset-popover transition-transform hover:scale-110 aria-pressed:ring-2 aria-pressed:ring-foreground/50"
                style={{ backgroundColor: color }}
              >
                {selected ? <Check className="size-3.5 text-white" aria-hidden /> : null}
              </button>
            );
          })}
        </div>
        <div className="mt-3 flex items-center gap-2 border-t border-border pt-3">
          <label
            className="relative flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-input text-muted-foreground hover:bg-muted"
            title="Color personalizado"
          >
            <Palette className="size-3.5" aria-hidden />
            <input
              type="color"
              value={valid ? value : "#64748b"}
              onChange={(event) => pick(event.target.value)}
              className="absolute inset-0 cursor-pointer opacity-0"
              aria-label="Color personalizado"
            />
          </label>
          <input
            value={text}
            onChange={(event) => {
              const next = event.target.value.trim();
              setText(next);
              const normalized = next.startsWith("#") ? next : `#${next}`;
              if (HEX.test(normalized)) onChange(normalized.toLowerCase());
            }}
            aria-label="Código hexadecimal"
            placeholder="#6366f1"
            className={cn(
              "num h-8 min-w-0 flex-1 rounded-lg border bg-card px-2.5 text-[12px] focus-visible:outline-none",
              HEX.test(text.startsWith("#") ? text : `#${text}`) ? "border-input focus-visible:border-accent" : "border-negative",
            )}
          />
        </div>
      </Popover>
    </>
  );
}
