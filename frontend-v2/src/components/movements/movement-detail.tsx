"use client";

import Link from "next/link";
import { ExternalLink, Info, TriangleAlert } from "lucide-react";
import type { Category, Movement } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { ConfidenceBadge } from "@/components/movements/movement-badges";
import { kindLabels } from "@/components/movements/constants";
import { categoryPair } from "@/lib/categories";
import { formatDate, formatMoney, toNumber } from "@/lib/utils";

function DetailItem({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 text-[12px] text-foreground">{value}</dd>
    </div>
  );
}

export function MovementDetail({
  movement,
  categories,
}: {
  movement: Movement;
  categories: Category[];
}) {
  const pair = categoryPair(
    categories,
    movement.classification?.categoria_id,
  );
  const category = pair.child ?? pair.root;
  const reasons = movement.review_reasons ?? [];

  return (
    <div className="grid gap-5 text-left lg:grid-cols-[1.6fr_1fr]">
      <div className="space-y-4">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            Descripción
          </p>
          <p className="mt-0.5 text-[12px] leading-5 text-foreground">
            {movement.description || movement.merchant || "Sin descripción del broker."}
          </p>
        </div>

        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <DetailItem label="Fecha valor" value={formatDate(movement.value_date, "medium")} />
          <DetailItem label="Tipo" value={kindLabels[movement.kind]} />
          <DetailItem
            label="Cuenta"
            value={
              movement.account ? (
                <span>
                  {movement.account.nombre}
                  {movement.account_destino ? (
                    <span className="text-muted-foreground">
                      {" "}
                      → {movement.account_destino.nombre}
                    </span>
                  ) : null}
                </span>
              ) : (
                "Sin asignar"
              )
            }
          />
          <DetailItem
            label="Importe"
            value={
              <span
                className={
                  movement.amount !== null && toNumber(movement.amount) >= 0
                    ? "text-positive"
                    : ""
                }
              >
                {movement.amount === null
                  ? "—"
                  : formatMoney(movement.amount, {
                      signDisplay: "always",
                      currency: movement.currency,
                    })}
              </span>
            }
          />
          <DetailItem
            label="Comisión / impuesto"
            value={`${formatMoney(movement.fee ?? 0)} · ${formatMoney(movement.tax ?? 0)}`}
          />
          <DetailItem label="MCC" value={movement.mcc_code ?? "—"} />
          <DetailItem label="Contraparte" value={movement.counterparty_name ?? "—"} />
          <DetailItem label="Fuente" value={movement.source_label ?? "—"} />
          <DetailItem
            label="Raw row"
            value={movement.raw_row_id ? `#${movement.raw_row_id}` : "—"}
          />
          {movement.account_destino ? (
            <DetailItem
              label="Cuenta destino"
              value={movement.account_destino.nombre}
            />
          ) : null}
        </dl>

        <div className="rounded-lg border border-border bg-card p-3">
          <div className="flex items-center gap-2">
            <p className="text-[11px] font-medium text-foreground">Clasificación vigente</p>
            <ConfidenceBadge classification={movement.classification} showOrigin />
          </div>
          <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">
            {movement.classification?.explicacion ??
              "Sin explicación registrada. La decisión puede venir del broker o de una importación antigua."}
          </p>
          {category ? (
            <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
              <span
                className="size-1.5 rounded-full"
                style={{ backgroundColor: category.color }}
                aria-hidden
              />
              <span>
                Categoría: <strong>{pair.root?.nombre ?? "—"}</strong>
              </span>
              <span aria-hidden>·</span>
              <span>
                Subcategoría: <strong>{pair.child?.nombre ?? "—"}</strong>
              </span>
              {movement.classification?.subtipo
                ? ` · ${movement.classification.subtipo}`
                : ""}
            </p>
          ) : null}
        </div>
      </div>

      <div className="space-y-3 border-border lg:border-l lg:pl-5">
        {reasons.length > 0 ? (
          <div>
            <p className="flex items-center gap-1.5 text-[11px] font-medium text-warning">
              <TriangleAlert className="size-3.5" aria-hidden />
              Motivos de revisión
            </p>
            <ul className="mt-1.5 space-y-1">
              {reasons.map((reason) => (
                <li
                  key={reason}
                  className="rounded-md bg-warning-soft px-2 py-1 text-[10px] leading-4 text-warning"
                >
                  {reason}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="flex items-start gap-1.5 text-[10px] leading-4 text-muted-foreground">
            <Info className="mt-0.5 size-3 shrink-0" aria-hidden />
            Sin incidencias marcadas para este movimiento.
          </p>
        )}

        {movement.duplicate_of ? (
          <div className="rounded-lg border border-warning/30 bg-warning-soft p-2.5">
            <p className="text-[11px] font-medium text-warning">Posible duplicado</p>
            <p className="mt-0.5 text-[10px] leading-4 text-warning">
              Par con el movimiento #{movement.duplicate_of}
              {movement.duplicate_score
                ? ` · similitud ${Math.round(movement.duplicate_score * 100)} %`
                : ""}
              . Resuélvelo desde la pestaña Duplicados.
            </p>
          </div>
        ) : null}

        {movement.source_file_id ? (
          <Link
            href={`/imports/${movement.source_file_id}`}
            className="inline-flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            <ExternalLink className="size-3" aria-hidden />
            Ver importación de origen
          </Link>
        ) : null}

        <div className="flex flex-wrap gap-1.5">
          <Badge variant="outline">ID #{movement.id}</Badge>
          <Badge variant="outline">{movement.estado}</Badge>
          {movement.classification ? (
            <Badge variant="outline">{movement.classification.origen}</Badge>
          ) : (
            <Badge variant="warning">Sin clasificar</Badge>
          )}
        </div>
      </div>
    </div>
  );
}
