"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ExternalLink, Info } from "lucide-react";
import type { AdviceAction, AdvisorAsset, Horizon, Recommendation } from "@/lib/agent-types";
import { cn, formatDate, formatMoney } from "@/lib/utils";

export const HORIZONS: { id: Horizon; label: string; hint: string }[] = [
  { id: "corto", label: "Corto", hint: "< 3 meses" },
  { id: "medio", label: "Medio", hint: "3–18 meses" },
  { id: "largo", label: "Largo", hint: "> 18 meses" },
];

const ACTION_STYLE: Record<AdviceAction, string> = {
  comprar: "bg-positive-soft text-positive",
  vender: "bg-negative-soft text-negative",
  mantener: "bg-muted text-foreground",
};
const ACTION_LABEL: Record<AdviceAction, string> = {
  comprar: "Comprar",
  vender: "Vender",
  mantener: "Mantener",
};
const CONFIDENCE_DOTS: Record<Recommendation["confidence"], number> = { baja: 1, media: 2, alta: 3 };

/** El backend guarda fechas UTC sin zona: se marcan como UTC para mostrarlas en hora local. */
export function utc(value: string | null | undefined): string | null {
  if (!value) return null;
  return /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
}

export function ActionPill({ rec }: { rec?: Recommendation }) {
  if (!rec) return <span className="text-[12px] text-muted-foreground">—</span>;
  const dots = CONFIDENCE_DOTS[rec.confidence] ?? 2;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[12px] font-medium",
        ACTION_STYLE[rec.action],
      )}
      title={`Confianza ${rec.confidence}`}
    >
      {ACTION_LABEL[rec.action]}
      <span className="flex gap-0.5" aria-label={`Confianza ${rec.confidence}`}>
        {[1, 2, 3].map((n) => (
          <span key={n} className={cn("size-1 rounded-full bg-current", n > dots && "opacity-25")} />
        ))}
      </span>
    </span>
  );
}

function SourceList({ sources }: { sources: string[] }) {
  if (!sources.length) return null;
  return (
    <ul className="mt-1.5 space-y-0.5">
      {sources.map((source) => (
        <li key={source} className="truncate text-[12px] text-muted-foreground">
          {/^https?:\/\//.test(source) ? (
            <a
              href={source}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex max-w-full items-center gap-1 underline-offset-2 hover:text-foreground hover:underline"
            >
              <ExternalLink className="size-3 shrink-0" aria-hidden />
              <span className="truncate">{source.replace(/^https?:\/\/(www\.)?/, "")}</span>
            </a>
          ) : (
            <span>· {source}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function AssetRow({ asset }: { asset: AdvisorAsset }) {
  const [open, setOpen] = useState(false);
  const any = HORIZONS.map((h) => asset.horizons[h.id]).find(Boolean);
  return (
    <li className="py-2.5">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 text-left sm:grid-cols-[minmax(0,1fr)_repeat(3,96px)_16px]"
      >
        <span className="min-w-0">
          <span className="block truncate text-[14px] font-medium">{asset.symbol}</span>
          <span className="block truncate text-[12px] text-muted-foreground">
            {asset.name ?? "—"}
            {any?.price != null ? ` · ${formatMoney(any.price, { currency: any.currency ?? "EUR" })}` : ""}
          </span>
        </span>
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform sm:order-last",
            open && "rotate-180",
          )}
          aria-hidden
        />
        <span className="col-span-2 flex flex-wrap gap-2 sm:contents">
          {HORIZONS.map((h) => (
            <span key={h.id} className="flex items-center gap-1.5 sm:block">
              <span className="text-[11px] text-muted-foreground sm:hidden">{h.label}</span>
              <ActionPill rec={asset.horizons[h.id]} />
            </span>
          ))}
        </span>
      </button>
      {open ? (
        <div className="animate-fade-in mt-2 space-y-2.5 rounded-xl bg-surface-2 p-3">
          {HORIZONS.map((h) => {
            const rec = asset.horizons[h.id];
            if (!rec) return null;
            return (
              <div key={h.id}>
                <p className="text-[12px] font-medium">
                  {h.label} plazo <span className="font-normal text-muted-foreground">({h.hint})</span>
                  {rec.created_at ? (
                    <span className="font-normal text-muted-foreground"> · {formatDate(utc(rec.created_at), "day")}</span>
                  ) : null}
                </p>
                <p className="mt-0.5 text-[13px] leading-5">{rec.rationale}</p>
                <SourceList sources={rec.sources ?? []} />
              </div>
            );
          })}
        </div>
      ) : null}
    </li>
  );
}

/** Tabla de recomendaciones por activo y horizonte (chat y página del asesor). */
export function AdviceTable({ assets, className }: { assets: AdvisorAsset[]; className?: string }) {
  return (
    <div className={className}>
      <div className="hidden grid-cols-[minmax(0,1fr)_repeat(3,96px)_16px] gap-x-3 border-b border-border pb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground sm:grid">
        <span>Activo</span>
        {HORIZONS.map((h) => (
          <span key={h.id} title={h.hint}>
            {h.label}
          </span>
        ))}
        <span />
      </div>
      <ul className="divide-y divide-border">
        {assets.map((asset) => (
          <AssetRow key={asset.symbol} asset={asset} />
        ))}
      </ul>
    </div>
  );
}

export function groupRecommendations(items: Recommendation[]): AdvisorAsset[] {
  const map = new Map<string, AdvisorAsset>();
  for (const item of items) {
    const symbol = item.symbol.toUpperCase();
    const asset = map.get(symbol) ?? {
      symbol,
      name: item.name ?? null,
      asset_id: item.asset_id ?? null,
      horizons: {},
      updated_at: item.created_at ?? null,
    };
    asset.name = asset.name ?? item.name ?? null;
    asset.horizons[item.horizon] = { ...item, sources: item.sources ?? [] };
    map.set(symbol, asset);
  }
  return [...map.values()];
}

interface Spec {
  summary?: string;
  items: Recommendation[];
}

export function isRecommendationSpec(value: unknown): value is Spec {
  return Boolean(
    value && typeof value === "object" && Array.isArray((value as { items?: unknown }).items),
  );
}

export function AdviceDisclaimer() {
  return (
    <p className="flex items-start gap-1.5 text-[11px] leading-4 text-muted-foreground">
      <Info className="mt-px size-3 shrink-0" aria-hidden />
      Orientativo y generado por IA a partir de datos públicos: no es asesoramiento financiero
      profesional ni se ejecuta ninguna operación.
    </p>
  );
}

export function RecommendationsWidget({ spec, result }: { spec: Spec; result: unknown }) {
  const failed = Boolean(result && typeof result === "object" && "error" in (result as object));
  if (failed) return null;
  const assets = groupRecommendations(spec.items);
  return (
    <div className="rounded-2xl border border-border bg-card p-4 shadow-1">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <p className="text-[13px] font-medium">
          Recomendaciones · {assets.length} {assets.length === 1 ? "activo" : "activos"}
        </p>
        <Link href="/ai/advisor" className="text-[12px] text-muted-foreground hover:text-foreground">
          Ver histórico
        </Link>
      </div>
      {spec.summary ? <p className="mb-2 text-[13px] text-muted-foreground">{spec.summary}</p> : null}
      <AdviceTable assets={assets} />
      <div className="mt-3">
        <AdviceDisclaimer />
      </div>
    </div>
  );
}
