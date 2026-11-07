"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Landmark, RefreshCw, Wallet } from "lucide-react";
import { accountsApi } from "@/lib/api";
import { withMock } from "@/lib/demo";
import { mockAccounts } from "@/lib/mock";
import type { AccountType } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/feedback";
import { cn, formatMoney, maskIban } from "@/lib/utils";

const typeLabels: Record<AccountType, string> = {
  broker_central: "Principal",
  efectivo_externa: "Vinculada",
};

export function AccountsSettingsSection() {
  const accountsQuery = useQuery({
    queryKey: ["accounts"],
    queryFn: () => withMock(() => accountsApi.list(), { items: mockAccounts }),
  });
  const accounts = accountsQuery.data?.items ?? [];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="py-3">
          <div>
            <CardTitle>Cuentas y patrones</CardTitle>
            <CardDescription>
              Cada extracto se asigna a una cuenta al importarlo. Aquí se revisan
              los saldos y las cuentas archivadas.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              onClick={() => void accountsQuery.refetch()}
              loading={accountsQuery.isFetching}
              aria-label="Recargar cuentas"
            >
              <RefreshCw className="size-3.5" aria-hidden />
            </Button>
            <Link
              href="/accounts"
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-[12px] font-medium text-accent-foreground transition-colors hover:bg-accent/90"
            >
              Gestionar cuentas
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Link>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          {accountsQuery.isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 3 }).map((_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <div className="divide-y divide-border">
              {accounts.map((account) => (
                <div
                  key={account.id}
                  className="flex flex-wrap items-center gap-2 py-2.5 text-[11px]"
                >
                  <span
                    className="size-2 rounded-[3px]"
                    style={{ backgroundColor: account.color }}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                      <span className="truncate font-medium">{account.nombre}</span>
                      <Badge variant="outline">{typeLabels[account.tipo]}</Badge>
                    </span>
                    <span className="num mt-0.5 block text-[10px] text-muted-foreground">
                      {maskIban(account.iban)} · {account.alias_patrones.length} patrones
                    </span>
                  </span>
                  <span className="num text-[11px] font-medium">
                    {formatMoney(account.balance)}
                  </span>
                  <Badge
                    variant={
                      account.reconciliacion_diferencia !== null &&
                      Math.abs(Number(account.reconciliacion_diferencia)) < 0.005
                        ? "positive"
                        : "warning"
                    }
                  >
                    {account.reconciliacion_diferencia !== null &&
                    Math.abs(Number(account.reconciliacion_diferencia)) < 0.005
                      ? "Conciliada"
                      : "Revisar"}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="py-3">
          <div>
            <CardTitle>Resolución automática</CardTitle>
            <CardDescription>Orden de prioridad del motor de cuentas</CardDescription>
          </div>
          <Landmark className="size-4 text-muted-foreground" aria-hidden />
        </CardHeader>
        <CardContent className="space-y-2 pt-0 text-[11px] leading-5 text-muted-foreground">
          {[
            {
              title: "IBAN exacto",
              text: "Se extrae de description_raw antes de redactar y se compara con accounts.iban.",
            },
            {
              title: "Patrón de contraparte",
              text: "alias_patrones sobre counterparty_name, merchant y descripción. Admite glob (*).",
            },
            {
              title: "Tipo de transferencia",
              text: "Si no hay cuenta propia, transferencia TR se clasifica como ingreso/gasto en «Transferencias».",
            },
          ].map((item, index) => (
            <div key={item.title} className="flex gap-2">
              <span
                className={cn(
                  "num mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full text-[9px] font-medium",
                  index === 0 ? "bg-accent-soft text-accent" : "bg-muted text-muted-foreground",
                )}
              >
                {index + 1}
              </span>
              <p>
                <span className="font-medium text-foreground">{item.title}.</span>{" "}
                {item.text}
              </p>
            </div>
          ))}
          <div className="flex items-start gap-2 rounded-lg bg-muted px-2.5 py-2 text-[10px] leading-4">
            <Wallet className="mt-0.5 size-3 shrink-0" aria-hidden />
            Añadir un IBAN o patrón re-etiqueta retroactivamente los movimientos
            coincidentes. Las transferencias internas quedan fuera de los KPIs.
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
