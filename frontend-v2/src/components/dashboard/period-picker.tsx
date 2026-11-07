"use client";

import { useCallback, useRef, useState } from "react";
import { CalendarDays, Check, ChevronDown } from "lucide-react";
import { Popover } from "@/components/ui/popover";
import {
  Calendar,
  formatIsoRange,
  parseIsoDate,
  startOfWeek,
  toIsoDate,
} from "@/components/ui/date-picker";
import { cn } from "@/lib/utils";

export interface PeriodPreset<T extends string> {
  value: T;
  label: string;
}

type Mode = "range" | "month" | "week";

const modes: Array<[Mode, string]> = [
  ["range", "Rango"],
  ["month", "Mes"],
  ["week", "Semana"],
];

/**
 * Selector de periodo único: atajos a la izquierda y calendario a la
 * derecha (rango libre, mes completo o semana de lunes a domingo).
 */
export function PeriodPicker<T extends string>({
  presets,
  value,
  label,
  from,
  to,
  onPreset,
  onCustom,
}: {
  presets: PeriodPreset<T>[];
  value: T | "custom";
  label: string;
  from?: string;
  to?: string;
  onPreset: (value: T) => void;
  onCustom: (from: string, to: string) => void;
}) {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("range");
  const [draft, setDraft] = useState({ from: "", to: "" });
  const [week, setWeek] = useState("");
  const [month, setMonth] = useState(() => new Date());
  const close = useCallback(() => setOpen(false), []);

  function toggle() {
    if (!open) {
      setDraft({ from: from ?? "", to: to ?? "" });
      setWeek(to ?? toIsoDate(new Date()));
      setMonth(parseIsoDate(to) ?? new Date());
    }
    setOpen(!open);
  }

  function apply(nextFrom: string, nextTo: string) {
    onCustom(nextFrom, nextTo);
    setOpen(false);
    anchorRef.current?.focus();
  }

  function pickRangeDay(iso: string) {
    if (!draft.from || draft.to) {
      setDraft({ from: iso, to: "" });
      return;
    }
    const [start, end] = iso < draft.from ? [iso, draft.from] : [draft.from, iso];
    setDraft({ from: start, to: end });
    apply(start, end);
  }

  function pickWeekDay(iso: string) {
    const date = parseIsoDate(iso);
    if (!date) return;
    const monday = startOfWeek(date);
    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    setWeek(iso);
    apply(toIsoDate(monday), toIsoDate(sunday));
  }

  return (
    <>
      <button
        ref={anchorRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Periodo del dashboard: ${label}`}
        onClick={toggle}
        className={cn(
          "inline-flex h-8 min-w-0 max-w-[16rem] items-center gap-1.5 rounded-lg border bg-card px-3 text-[12px] font-medium text-foreground transition-colors hover:bg-muted",
          open ? "border-accent" : "border-border",
        )}
      >
        <CalendarDays className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span className="min-w-0 truncate first-letter:uppercase">{label}</span>
        <ChevronDown
          className={cn("size-3.5 shrink-0 opacity-60 transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>
      <Popover open={open} onClose={close} anchorRef={anchorRef} align="end" ariaLabel="Seleccionar periodo">
        <div className="flex flex-col sm:flex-row">
          <div className="flex gap-1 overflow-x-auto border-b border-border p-2 sm:w-44 sm:flex-col sm:border-b-0 sm:border-r">
            {presets.map((preset) => (
              <button
                key={preset.value}
                type="button"
                onClick={() => {
                  onPreset(preset.value);
                  setOpen(false);
                }}
                className={cn(
                  "flex shrink-0 items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left text-[12px] transition-colors",
                  value === preset.value
                    ? "bg-accent-soft font-medium text-accent-soft-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {preset.label}
                {value === preset.value ? <Check className="hidden size-3.5 sm:block" aria-hidden /> : null}
              </button>
            ))}
          </div>
          <div className="p-3">
            <div className="mb-3 grid grid-cols-3 gap-1 rounded-lg bg-muted p-0.5" role="tablist">
              {modes.map(([item, text]) => (
                <button
                  key={item}
                  type="button"
                  role="tab"
                  aria-selected={mode === item}
                  onClick={() => setMode(item)}
                  className={cn(
                    "rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
                    mode === item
                      ? "bg-card text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {text}
                </button>
              ))}
            </div>
            {mode === "range" ? (
              <Calendar
                key="range"
                selection={{ mode: "range", from: draft.from, to: draft.to }}
                month={month}
                onMonthChange={setMonth}
                onPickDay={pickRangeDay}
              />
            ) : mode === "month" ? (
              <Calendar
                key="month"
                initialView="months"
                selection={{ mode: "range", from: from ?? "", to: to ?? "" }}
                month={month}
                onMonthChange={setMonth}
                onPickMonth={(year, monthIndex) =>
                  apply(
                    toIsoDate(new Date(year, monthIndex, 1)),
                    toIsoDate(new Date(year, monthIndex + 1, 0)),
                  )
                }
              />
            ) : (
              <Calendar
                key="week"
                selection={{ mode: "week", value: week }}
                month={month}
                onMonthChange={setMonth}
                onPickDay={pickWeekDay}
              />
            )}
            <p className="mt-2 border-t border-border pt-2 text-[11px] text-muted-foreground">
              {mode === "range"
                ? draft.from && !draft.to
                  ? "Elige el día final"
                  : draft.from
                    ? formatIsoRange(draft.from, draft.to)
                    : "Elige el día de inicio"
                : mode === "month"
                  ? "Elige un mes completo"
                  : "Elige cualquier día: se toma de lunes a domingo"}
            </p>
          </div>
        </div>
      </Popover>
    </>
  );
}
