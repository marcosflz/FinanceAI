"use client";

import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, X } from "lucide-react";
import { Popover } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/* Utilidades de fecha: siempre ``YYYY-MM-DD`` en hora local.          */
/* ------------------------------------------------------------------ */

export function toIsoDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function parseIsoDate(value: string | null | undefined): Date | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return date.getMonth() === month - 1 ? date : null;
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

export function startOfWeek(date: Date): Date {
  return addDays(date, -((date.getDay() + 6) % 7));
}

const WEEKDAYS = ["L", "M", "X", "J", "V", "S", "D"];
const monthFormatter = new Intl.DateTimeFormat("es-ES", { month: "long", year: "numeric" });
const monthShortFormatter = new Intl.DateTimeFormat("es-ES", { month: "short" });
const dayFormatter = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", year: "numeric" });
const dayNoYearFormatter = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short" });
const fullDayFormatter = new Intl.DateTimeFormat("es-ES", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function formatIsoDate(value: string): string {
  const date = parseIsoDate(value);
  return date ? dayFormatter.format(date).replace(".", "") : value;
}

export function formatIsoRange(from: string, to: string): string {
  const start = parseIsoDate(from);
  const end = parseIsoDate(to);
  if (start && end) {
    const sameYear = start.getFullYear() === end.getFullYear();
    const left = (sameYear ? dayNoYearFormatter : dayFormatter).format(start).replace(".", "");
    return `${left} – ${dayFormatter.format(end).replace(".", "")}`;
  }
  if (start) return `Desde ${formatIsoDate(from)}`;
  if (end) return `Hasta ${formatIsoDate(to)}`;
  return "";
}

/* ------------------------------------------------------------------ */
/* Calendario                                                          */
/* ------------------------------------------------------------------ */

export type CalendarSelection =
  | { mode: "single"; value: string }
  | { mode: "range"; from: string; to: string }
  | { mode: "week"; value: string };

type CalendarView = "days" | "months" | "years";

/**
 * Calendario mensual (lunes primero). Pulsa el título para saltar a meses y
 * años. ``onPickMonth`` permite usarlo como selector de mes completo.
 */
export function Calendar({
  selection,
  onPickDay,
  onPickMonth,
  month,
  onMonthChange,
  min,
  max,
  initialView = "days",
}: {
  selection: CalendarSelection;
  onPickDay?: (iso: string) => void;
  onPickMonth?: (year: number, monthIndex: number) => void;
  month: Date;
  onMonthChange: (month: Date) => void;
  min?: string;
  max?: string;
  initialView?: CalendarView;
}) {
  const [view, setView] = useState<CalendarView>(initialView);
  const [hover, setHover] = useState<string | null>(null);
  const today = toIsoDate(new Date());
  const year = month.getFullYear();
  const monthIndex = month.getMonth();

  const days = useMemo(() => {
    const first = startOfWeek(new Date(year, monthIndex, 1));
    return Array.from({ length: 42 }, (_, index) => addDays(first, index));
  }, [year, monthIndex]);

  const isDisabled = (iso: string) => Boolean((min && iso < min) || (max && iso > max));

  let rangeFrom = "";
  let rangeTo = "";
  if (selection.mode === "range") {
    rangeFrom = selection.from;
    rangeTo = selection.to;
    if (rangeFrom && !rangeTo && hover) {
      [rangeFrom, rangeTo] = hover < rangeFrom ? [hover, rangeFrom] : [rangeFrom, hover];
    }
  } else if (selection.mode === "week") {
    const base = parseIsoDate(hover ?? selection.value);
    if (base) {
      rangeFrom = toIsoDate(startOfWeek(base));
      rangeTo = toIsoDate(addDays(startOfWeek(base), 6));
    }
  }

  function shift(delta: number) {
    if (view === "days") onMonthChange(new Date(year, monthIndex + delta, 1));
    else if (view === "months") onMonthChange(new Date(year + delta, monthIndex, 1));
    else onMonthChange(new Date(year + delta * 12, monthIndex, 1));
  }

  const yearStart = Math.floor(year / 12) * 12;
  const title =
    view === "days"
      ? capitalize(monthFormatter.format(month))
      : view === "months"
        ? String(year)
        : `${yearStart} – ${yearStart + 11}`;

  const navButton =
    "flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground";

  return (
    <div className="w-[17.5rem] select-none">
      <div className="mb-2 flex items-center justify-between gap-1">
        <button type="button" className={navButton} onClick={() => shift(-1)} aria-label="Anterior">
          <ChevronLeft className="size-4" aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => setView(view === "days" ? "months" : "years")}
          disabled={view === "years"}
          className="rounded-md px-2 py-1 text-[13px] font-semibold text-foreground transition-colors hover:bg-muted disabled:cursor-default disabled:hover:bg-transparent"
          aria-live="polite"
        >
          {title}
        </button>
        <button type="button" className={navButton} onClick={() => shift(1)} aria-label="Siguiente">
          <ChevronRight className="size-4" aria-hidden />
        </button>
      </div>

      {view === "days" ? (
        <div role="grid" aria-label={title} onPointerLeave={() => setHover(null)}>
          <div className="mb-1 grid grid-cols-7" role="row">
            {WEEKDAYS.map((label) => (
              <span
                key={label}
                role="columnheader"
                className="py-1 text-center text-[10px] font-semibold uppercase text-muted-foreground"
              >
                {label}
              </span>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-y-0.5" role="row">
            {days.map((date) => {
              const iso = toIsoDate(date);
              const outside = date.getMonth() !== monthIndex;
              const disabled = isDisabled(iso);
              const isEdge =
                (selection.mode === "single" && selection.value === iso) ||
                (rangeFrom && iso === rangeFrom) ||
                (rangeTo && iso === rangeTo);
              const inRange = Boolean(rangeFrom && rangeTo && iso > rangeFrom && iso < rangeTo);
              const weekday = (date.getDay() + 6) % 7;
              return (
                <div
                  key={iso}
                  role="gridcell"
                  className={cn(
                    "relative flex h-8 items-center justify-center",
                    (inRange || (isEdge && rangeFrom && rangeTo && rangeFrom !== rangeTo)) &&
                      "bg-accent-soft",
                    iso === rangeFrom && rangeTo && rangeFrom !== rangeTo && "rounded-l-full",
                    iso === rangeTo && rangeFrom && rangeFrom !== rangeTo && "rounded-r-full",
                    inRange && weekday === 0 && "rounded-l-md",
                    inRange && weekday === 6 && "rounded-r-md",
                  )}
                >
                  <button
                    type="button"
                    disabled={disabled}
                    aria-pressed={Boolean(isEdge)}
                    aria-label={capitalize(fullDayFormatter.format(date))}
                    onPointerEnter={() => setHover(iso)}
                    onFocus={() => setHover(iso)}
                    onClick={() => onPickDay?.(iso)}
                    className={cn(
                      "num relative flex size-8 items-center justify-center rounded-full text-[12px] transition-colors",
                      "disabled:cursor-not-allowed disabled:opacity-30",
                      outside ? "text-muted-foreground/60" : "text-foreground",
                      !isEdge && "hover:bg-muted",
                      inRange && "text-accent-soft-foreground",
                      isEdge && "bg-accent font-semibold text-accent-foreground",
                      iso === today && !isEdge && "font-semibold text-accent ring-1 ring-inset ring-accent/40",
                    )}
                  >
                    {date.getDate()}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      ) : view === "months" ? (
        <div className="grid grid-cols-3 gap-1.5 py-1">
          {Array.from({ length: 12 }, (_, index) => {
            const isCurrent = index === monthIndex;
            const now = new Date();
            const isNow = index === now.getMonth() && year === now.getFullYear();
            return (
              <button
                key={index}
                type="button"
                onClick={() => {
                  if (onPickMonth) {
                    onPickMonth(year, index);
                  } else {
                    onMonthChange(new Date(year, index, 1));
                    setView("days");
                  }
                }}
                className={cn(
                  "h-10 rounded-lg text-[12px] capitalize transition-colors",
                  isCurrent
                    ? "bg-accent font-semibold text-accent-foreground"
                    : "text-foreground hover:bg-muted",
                  isNow && !isCurrent && "font-semibold text-accent",
                )}
              >
                {monthShortFormatter.format(new Date(year, index, 1)).replace(".", "")}
              </button>
            );
          })}
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-1.5 py-1">
          {Array.from({ length: 12 }, (_, index) => {
            const value = yearStart + index;
            return (
              <button
                key={value}
                type="button"
                onClick={() => {
                  onMonthChange(new Date(value, monthIndex, 1));
                  setView("months");
                }}
                className={cn(
                  "num h-10 rounded-lg text-[12px] transition-colors",
                  value === year
                    ? "bg-accent font-semibold text-accent-foreground"
                    : "text-foreground hover:bg-muted",
                  value === new Date().getFullYear() && value !== year && "font-semibold text-accent",
                )}
              >
                {value}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Disparadores                                                        */
/* ------------------------------------------------------------------ */

type TriggerVariant = "field" | "pill";

function triggerClasses(variant: TriggerVariant, active: boolean, open: boolean) {
  return variant === "pill"
    ? cn(
        "h-8 shrink-0 rounded-full border px-3 text-[12px] font-medium",
        active
          ? "border-accent/40 bg-accent-soft text-accent-soft-foreground"
          : "border-border bg-card text-muted-foreground hover:border-input hover:text-foreground",
      )
    : cn(
        "h-9 w-full rounded-lg border border-input bg-card px-3 text-sm hover:border-muted-foreground/40 focus-visible:border-accent",
        active ? "text-foreground" : "text-muted-foreground",
        open && "border-accent",
      );
}

function ClearButton({ onClear, label, pill }: { onClear: () => void; label: string; pill: boolean }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClear}
      className={cn(
        "absolute top-1/2 flex size-5 -translate-y-1/2 items-center justify-center rounded-full opacity-70 transition-colors hover:bg-foreground/10 hover:opacity-100",
        pill ? "right-1.5" : "right-2",
      )}
    >
      <X className="size-3" aria-hidden />
    </button>
  );
}

function FooterButton({ children, onClick, primary = false, disabled = false }: {
  children: ReactNode;
  onClick: () => void;
  primary?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "h-7 rounded-md px-2.5 text-[12px] font-medium transition-colors disabled:opacity-50",
        primary
          ? "bg-accent text-accent-foreground hover:bg-accent/90"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

/** Selector de un día. ``value`` y ``onChange`` en ``YYYY-MM-DD`` ("" = vacío). */
export function DatePicker({
  value,
  onChange,
  placeholder = "Elegir fecha",
  min,
  max,
  clearable = true,
  disabled = false,
  id,
  "aria-label": ariaLabel,
  className,
  variant = "field",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  min?: string;
  max?: string;
  clearable?: boolean;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
  className?: string;
  variant?: TriggerVariant;
}) {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(() => parseIsoDate(value) ?? new Date());
  const close = useCallback(() => setOpen(false), []);

  function toggle() {
    if (disabled) return;
    if (!open) setMonth(parseIsoDate(value) ?? parseIsoDate(max) ?? new Date());
    setOpen(!open);
  }

  function pick(iso: string) {
    onChange(iso);
    setOpen(false);
    anchorRef.current?.focus();
  }

  const today = toIsoDate(new Date());
  const todayAllowed = !(min && today < min) && !(max && today > max);

  const showClear = clearable && Boolean(value) && !disabled;

  return (
    <span className={cn("relative inline-flex min-w-0", variant === "field" && "w-full", className)}>
      <button
        ref={anchorRef}
        id={id}
        type="button"
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={ariaLabel ? `${ariaLabel}${value ? `: ${formatIsoDate(value)}` : ""}` : undefined}
        onClick={toggle}
        className={cn(
          "inline-flex min-w-0 items-center gap-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50",
          triggerClasses(variant, Boolean(value), open),
          "w-full",
          showClear && "pr-8",
        )}
      >
        <CalendarDays className="size-3.5 shrink-0 opacity-70" aria-hidden />
        <span className="min-w-0 flex-1 truncate">{value ? formatIsoDate(value) : placeholder}</span>
      </button>
      {showClear ? (
        <ClearButton onClear={() => onChange("")} label="Borrar fecha" pill={variant === "pill"} />
      ) : null}
      <Popover open={open} onClose={close} anchorRef={anchorRef} ariaLabel={ariaLabel ?? "Elegir fecha"} className="p-3">
        <Calendar
          selection={{ mode: "single", value }}
          month={month}
          onMonthChange={setMonth}
          onPickDay={pick}
          min={min}
          max={max}
        />
        <div className="mt-2 flex items-center justify-between border-t border-border pt-2">
          <FooterButton onClick={() => pick(today)} disabled={!todayAllowed}>
            Hoy
          </FooterButton>
          {clearable && value ? <FooterButton onClick={() => pick("")}>Borrar</FooterButton> : null}
        </div>
      </Popover>
    </span>
  );
}

export interface RangePreset {
  label: string;
  from: string;
  to: string;
}

export function defaultRangePresets(now = new Date()): RangePreset[] {
  const year = now.getFullYear();
  const month = now.getMonth();
  const today = toIsoDate(now);
  return [
    { label: "Este mes", from: toIsoDate(new Date(year, month, 1)), to: toIsoDate(new Date(year, month + 1, 0)) },
    { label: "Mes anterior", from: toIsoDate(new Date(year, month - 1, 1)), to: toIsoDate(new Date(year, month, 0)) },
    { label: "Últimos 30 días", from: toIsoDate(addDays(now, -29)), to: today },
    { label: "Últimos 3 meses", from: toIsoDate(new Date(year, month - 2, 1)), to: toIsoDate(new Date(year, month + 1, 0)) },
    { label: "Este año", from: toIsoDate(new Date(year, 0, 1)), to: toIsoDate(new Date(year, 11, 31)) },
    { label: "Año anterior", from: toIsoDate(new Date(year - 1, 0, 1)), to: toIsoDate(new Date(year - 1, 11, 31)) },
  ];
}

/**
 * Selector de rango: primer clic fija el inicio, el segundo el final (con
 * vista previa al pasar el ratón). Incluye atajos de periodos habituales.
 */
export function DateRangePicker({
  from,
  to,
  onChange,
  placeholder = "Fechas",
  presets = defaultRangePresets(),
  variant = "field",
  "aria-label": ariaLabel = "Rango de fechas",
  className,
  align = "start",
}: {
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
  placeholder?: string;
  presets?: RangePreset[];
  variant?: TriggerVariant;
  "aria-label"?: string;
  className?: string;
  align?: "start" | "end";
}) {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({ from, to });
  const [month, setMonth] = useState(() => parseIsoDate(from) ?? new Date());
  const close = useCallback(() => setOpen(false), []);
  const hasValue = Boolean(from || to);

  function toggle() {
    if (!open) {
      setDraft({ from, to });
      setMonth(parseIsoDate(from) ?? parseIsoDate(to) ?? new Date());
    }
    setOpen(!open);
  }

  function commit(nextFrom: string, nextTo: string) {
    onChange(nextFrom, nextTo);
    setOpen(false);
    anchorRef.current?.focus();
  }

  function pickDay(iso: string) {
    if (!draft.from || draft.to) {
      setDraft({ from: iso, to: "" });
      return;
    }
    const [start, end] = iso < draft.from ? [iso, draft.from] : [draft.from, iso];
    setDraft({ from: start, to: end });
    commit(start, end);
  }

  const activePreset = presets.find((preset) => preset.from === from && preset.to === to);
  const label = activePreset?.label ?? (hasValue ? formatIsoRange(from, to) : placeholder);

  return (
    <span className={cn("relative inline-flex min-w-0 shrink-0", variant === "field" && "w-full", className)}>
      <button
        ref={anchorRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={hasValue ? `${ariaLabel}: ${label}` : ariaLabel}
        onClick={toggle}
        className={cn(
          "inline-flex min-w-0 items-center gap-1.5 text-left transition-colors",
          triggerClasses(variant, hasValue, open),
          "w-full",
          hasValue && "pr-8",
        )}
      >
        <CalendarDays className="size-3.5 shrink-0" aria-hidden />
        <span className="min-w-0 truncate">{label}</span>
      </button>
      {hasValue ? (
        <ClearButton onClear={() => onChange("", "")} label="Quitar fechas" pill={variant === "pill"} />
      ) : null}
      <Popover open={open} onClose={close} anchorRef={anchorRef} align={align} ariaLabel={ariaLabel} className="p-0">
        <div className="flex flex-col sm:flex-row">
          {presets.length > 0 ? (
            <div className="flex gap-1 overflow-x-auto border-b border-border p-2 sm:w-40 sm:flex-col sm:border-b-0 sm:border-r">
              {presets.map((preset) => {
                const isActive = preset.from === draft.from && preset.to === draft.to;
                return (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => commit(preset.from, preset.to)}
                    className={cn(
                      "shrink-0 rounded-md px-2.5 py-1.5 text-left text-[12px] transition-colors",
                      isActive
                        ? "bg-accent-soft font-medium text-accent-soft-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    {preset.label}
                  </button>
                );
              })}
            </div>
          ) : null}
          <div className="p-3">
            <Calendar
              selection={{ mode: "range", from: draft.from, to: draft.to }}
              month={month}
              onMonthChange={setMonth}
              onPickDay={pickDay}
            />
            <div className="mt-2 flex items-center justify-between gap-2 border-t border-border pt-2">
              <p className="min-w-0 truncate text-[11px] text-muted-foreground">
                {draft.from && !draft.to
                  ? `Desde ${formatIsoDate(draft.from)} · elige el final`
                  : draft.from
                    ? formatIsoRange(draft.from, draft.to)
                    : "Elige el día de inicio"}
              </p>
              {hasValue ? <FooterButton onClick={() => commit("", "")}>Quitar</FooterButton> : null}
            </div>
          </div>
        </div>
      </Popover>
    </span>
  );
}
