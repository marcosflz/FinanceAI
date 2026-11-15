import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export type Numeric = number | string | null | undefined;

export function toNumber(value: Numeric): number {
  if (value === null || value === undefined || value === "") return 0;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

const eurFormatter = new Intl.NumberFormat("es-ES", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  useGrouping: true,
});

const eurIntegerFormatter = new Intl.NumberFormat("es-ES", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
  useGrouping: true,
});

const moneyFormatters = new Map<string, Intl.NumberFormat>();

function moneyFormatter(currency: string, compact: boolean): Intl.NumberFormat {
  const code = currency.toUpperCase();
  const key = `${code}:${compact ? "compact" : "full"}`;
  const cached = moneyFormatters.get(key);
  if (cached) return cached;
  const formatter = compact
    ? new Intl.NumberFormat("es-ES", {
        style: "currency",
        currency: code,
        maximumFractionDigits: 0,
        useGrouping: true,
      })
    : new Intl.NumberFormat("es-ES", {
        style: "currency",
        currency: code,
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
        useGrouping: true,
      });
  moneyFormatters.set(key, formatter);
  return formatter;
}

export function formatMoney(
  value: Numeric,
  options: {
    signDisplay?: "auto" | "always" | "never";
    compact?: boolean;
    currency?: string;
  } = {},
): string {
  const amount = toNumber(value);
  const formatter = options.currency
    ? moneyFormatter(options.currency, Boolean(options.compact))
    : options.compact ? eurIntegerFormatter : eurFormatter;
  if (options.signDisplay === "always") {
    return formatter.format(amount).replace(/^([+-]?)/, (sign) =>
      amount > 0 ? "+" : sign,
    );
  }
  return formatter.format(amount);
}

const decimalFormatter = new Intl.NumberFormat("es-ES", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
  useGrouping: true,
});

export function formatNumber(value: Numeric, digits = 2): string {
  return new Intl.NumberFormat("es-ES", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
    useGrouping: true,
  }).format(toNumber(value));
}

export function formatQuantity(value: Numeric, digits = 4): string {
  const amount = toNumber(value);
  if (Math.abs(amount) < 0.0001) return decimalFormatter.format(amount);
  return new Intl.NumberFormat("es-ES", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
    useGrouping: true,
  }).format(amount);
}

export function formatPercent(
  value: Numeric,
  options: { fractionDigits?: number; signDisplay?: "auto" | "always" | "never" } = {},
): string {
  const amount = toNumber(value);
  return new Intl.NumberFormat("es-ES", {
    style: "percent",
    minimumFractionDigits: options.fractionDigits ?? 1,
    maximumFractionDigits: options.fractionDigits ?? 1,
    signDisplay: options.signDisplay ?? "auto",
  }).format(amount / 100);
}

export function formatDate(
  value: string | Date | null | undefined,
  style: "short" | "medium" | "long" | "month" | "day" = "short",
): string {
  if (!value) return "—";
  const date =
    typeof value === "string"
      ? new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value)
      : value;
  if (Number.isNaN(date.getTime())) return "—";

  const options: Intl.DateTimeFormatOptions =
    style === "long"
      ? { day: "numeric", month: "long", year: "numeric" }
      : style === "medium"
        ? { day: "2-digit", month: "short", year: "numeric" }
        : style === "month"
          ? { month: "short", year: "2-digit" }
          : style === "day"
            ? { day: "numeric", month: "short" }
            : { day: "2-digit", month: "2-digit", year: "numeric" };

  return new Intl.DateTimeFormat("es-ES", options).format(date);
}

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("es-ES", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function relativeDate(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "—";
  const days = Math.round((date.getTime() - Date.now()) / 86_400_000);
  const formatter = new Intl.RelativeTimeFormat("es-ES", { numeric: "auto" });
  if (Math.abs(days) < 1) return "hoy";
  if (Math.abs(days) < 30) return formatter.format(days, "day");
  if (Math.abs(days) < 365) return formatter.format(Math.round(days / 30), "month");
  return formatter.format(Math.round(days / 365), "year");
}

export function maskIban(iban: string | null | undefined): string {
  if (!iban) return "Sin IBAN";
  const clean = iban.replace(/\s+/g, "");
  if (clean.length <= 8) return clean;
  return `${clean.slice(0, 4)} ···· ${clean.slice(-4)}`;
}

export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function safeNextPath(value: string | null | undefined): string {
  if (!value) return "/";
  if (!value.startsWith("/") || value.startsWith("//")) return "/";
  if (value.startsWith("/login")) return "/";
  return value;
}

export function pluralize(
  count: number,
  singular: string,
  plural = `${singular}s`,
): string {
  return count === 1 ? singular : plural;
}
