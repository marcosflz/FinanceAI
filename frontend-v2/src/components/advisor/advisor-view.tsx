"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot as BotIcon,
  Brain,
  ExternalLink,
  MessageSquare,
  Newspaper,
  Play,
  Plus,
  RotateCcw,
  Settings2,
  Target,
  Trash2,
} from "lucide-react";
import { advisorApi, botsApi } from "@/lib/agent-api";
import type { NewsFeed } from "@/lib/agent-types";
import { ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import {
  AdviceDisclaimer,
  AdviceTable,
  HORIZONS,
  utc,
} from "@/components/assistant/recommendations-widget";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, SkeletonText } from "@/components/ui/feedback";
import { Input } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page-header";
import { useToast } from "@/components/ui/toast";

function errorText(error: unknown) {
  return error instanceof ApiError ? error.message : "Inténtalo de nuevo";
}

function SetupCard({ onSetup, loading }: { onSetup: () => void; loading: boolean }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-accent text-accent-foreground">
          <Target className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[15px] font-medium">Activa tu asesor diario</p>
          <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
            Cada día laborable a las 8:00 valora tu cartera a precio de mercado, lee las noticias
            de cada posición y te deja recomendaciones de mantener, comprar o vender a corto,
            medio y largo plazo. Instala la skill <code>asesor-cartera</code> y una
            automatización que puedes pausar o editar cuando quieras.
          </p>
        </div>
        <Button variant="primary" loading={loading} onClick={onSetup}>
          Activar asesor
        </Button>
      </CardContent>
    </Card>
  );
}

function EvaluationCard() {
  const evaluation = useQuery({
    queryKey: ["advisor", "evaluation"],
    queryFn: () => advisorApi.evaluation(),
    staleTime: 5 * 60_000,
  });
  const data = evaluation.data;
  return (
    <Card>
      <CardHeader className="py-3">
        <div>
          <CardTitle>Aciertos</CardTitle>
          <CardDescription>
            Recomendaciones de hace más de 7 días frente al precio actual
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {evaluation.isLoading ? <SkeletonText lines={2} /> : null}
        {evaluation.isError ? (
          <p className="text-[12px] text-muted-foreground">No se pudieron consultar las cotizaciones.</p>
        ) : null}
        {data && !data.evaluated ? (
          <p className="text-[12px] leading-5 text-muted-foreground">
            Aún no hay recomendaciones con antigüedad suficiente. Vuelve en unos días.
          </p>
        ) : null}
        {data && data.evaluated ? (
          <div className="space-y-3">
            <p className="text-[28px] font-semibold tabular-nums">
              {data.hit_rate?.toLocaleString("es-ES")} %
              <span className="ml-2 text-[12px] font-normal text-muted-foreground">
                de {data.evaluated} recomendaciones
              </span>
            </p>
            <div className="grid grid-cols-3 gap-2">
              {HORIZONS.map((h) => {
                const stat = data.by_horizon[h.id];
                return (
                  <div key={h.id} className="rounded-lg bg-surface-2 px-2.5 py-2">
                    <p className="text-[11px] text-muted-foreground">{h.label}</p>
                    <p className="text-[14px] font-medium tabular-nums">
                      {stat?.total ? `${stat.hits}/${stat.total}` : "—"}
                    </p>
                  </div>
                );
              })}
            </div>
            <p className="text-[11px] leading-4 text-muted-foreground">
              Comprar acierta si el precio sube; vender, si baja; mantener, si se mueve menos de un
              5 %.
            </p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function FeedsEditor({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const feeds = useQuery({ queryKey: ["advisor", "feeds"], queryFn: () => advisorApi.feeds() });
  const [draft, setDraft] = useState<NewsFeed[] | null>(null);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const items = draft ?? feeds.data?.items ?? [];
  const save = useMutation({
    mutationFn: (next: NewsFeed[]) => advisorApi.saveFeeds(next),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["advisor", "feeds"] });
      queryClient.invalidateQueries({ queryKey: ["advisor", "news"] });
      toast({ title: "Fuentes guardadas", variant: "success" });
      onClose();
    },
    onError: (error) => toast({ title: "No se pudo guardar", description: errorText(error), variant: "error" }),
  });
  function add(event: FormEvent) {
    event.preventDefault();
    if (!url.trim()) return;
    setDraft([...items, { name: name.trim() || url.trim(), url: url.trim() }]);
    setName("");
    setUrl("");
  }
  return (
    <div className="space-y-2 rounded-lg border border-border p-3">
      <ul className="space-y-1">
        {items.map((feed) => (
          <li key={feed.url} className="flex items-center gap-2 text-[13px]">
            <span className="min-w-0 flex-1 truncate">
              {feed.name} <span className="text-[11px] text-muted-foreground">{feed.url}</span>
            </span>
            <Button
              size="icon"
              variant="ghost"
              aria-label={`Quitar ${feed.name}`}
              onClick={() => setDraft(items.filter((item) => item.url !== feed.url))}
            >
              <Trash2 className="size-3.5" aria-hidden />
            </Button>
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="flex flex-col gap-1.5 sm:flex-row">
        <Input aria-label="Nombre" placeholder="Nombre" value={name} onChange={(e) => setName(e.target.value)} className="sm:w-40" />
        <Input aria-label="URL del feed RSS" placeholder="https://…/rss.xml" value={url} onChange={(e) => setUrl(e.target.value)} />
        <Button type="submit" size="sm" className="h-9">
          <Plus className="size-3.5" aria-hidden />
          Añadir
        </Button>
      </form>
      <div className="flex flex-wrap gap-1.5">
        <Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate(items)}>
          Guardar fuentes
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setDraft(feeds.data?.defaults ?? [])}>
          <RotateCcw className="size-3.5" aria-hidden />
          Restaurar predeterminadas
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Cancelar
        </Button>
      </div>
    </div>
  );
}

function NewsCard() {
  const [editing, setEditing] = useState(false);
  const news = useQuery({
    queryKey: ["advisor", "news"],
    queryFn: () => advisorApi.news(),
    staleTime: 10 * 60_000,
  });
  const items = news.data?.items.slice(0, 12) ?? [];
  return (
    <Card>
      <CardHeader className="py-3">
        <div>
          <CardTitle>Noticias de mercado</CardTitle>
          <CardDescription>
            Las fuentes que lee el asesor ({news.data?.feeds.length ?? "…"} feeds RSS)
          </CardDescription>
        </div>
        <Button size="sm" variant="ghost" onClick={() => setEditing((value) => !value)}>
          <Settings2 className="size-3.5" aria-hidden />
          Fuentes
        </Button>
      </CardHeader>
      <CardContent className="space-y-2 pt-0">
        {editing ? <FeedsEditor onClose={() => setEditing(false)} /> : null}
        {news.isLoading ? <SkeletonText lines={5} /> : null}
        {news.data?.failed.length ? (
          <p className="text-[11px] text-muted-foreground">
            Sin respuesta: {news.data.failed.join(", ")}
          </p>
        ) : null}
        {news.isSuccess && !items.length ? (
          <p className="text-[12px] text-muted-foreground">No hay titulares ahora mismo.</p>
        ) : null}
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <li key={`${item.source}-${item.title}`} className="py-2">
              <a
                href={item.url || undefined}
                target="_blank"
                rel="noreferrer noopener"
                className="group block"
              >
                <p className="text-[13px] font-medium leading-5 group-hover:underline">
                  {item.title}
                  {item.url ? (
                    <ExternalLink className="ml-1 inline size-3 text-muted-foreground" aria-hidden />
                  ) : null}
                </p>
                <p className="text-[11px] text-muted-foreground">
                  {item.source}
                  {item.published_at ? ` · ${formatDateTime(item.published_at)}` : ""}
                </p>
              </a>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function AdvisorView() {
  const router = useRouter();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["advisor", "status"], queryFn: () => advisorApi.status() });
  const latest = useQuery({ queryKey: ["advisor", "latest"], queryFn: () => advisorApi.latest() });
  const bot = status.data?.bot ?? null;

  const setup = useMutation({
    mutationFn: () => advisorApi.setup(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["advisor"] });
      queryClient.invalidateQueries({ queryKey: ["agent", "bots"] });
      queryClient.invalidateQueries({ queryKey: ["agent", "skills"] });
      toast({ title: "Asesor activado", description: "Se ejecutará los días laborables a las 8:00.", variant: "success" });
    },
    onError: (error) => toast({ title: "No se pudo activar", description: errorText(error), variant: "error" }),
  });
  const run = useMutation({
    mutationFn: (id: number) => botsApi.runNow(id),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["advisor"] });
      queryClient.invalidateQueries({ queryKey: ["agent", "threads"] });
      if (result.status === "error") {
        toast({ title: "El asesor ha fallado", description: result.error ?? "", variant: "error" });
        return;
      }
      router.push(`/ai/assistant?thread=${result.thread_id}`);
    },
    onError: (error) => toast({ title: "No se pudo ejecutar", description: errorText(error), variant: "error" }),
  });

  const assets = latest.data?.items ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Asesor de cartera"
        description="Consejos diarios de mantener, comprar o vender por activo y horizonte, cruzando tu cartera con mercado, noticias y tu perfil."
        actions={
          <>
            <Button variant="outline" onClick={() => router.push("/ai/assistant?skill=asesor-cartera")}>
              <MessageSquare className="size-4" aria-hidden />
              Preguntar al asesor
            </Button>
            {bot ? (
              <Button variant="primary" loading={run.isPending} onClick={() => run.mutate(bot.id)}>
                <Play className="size-4" aria-hidden />
                {run.isPending ? "Analizando…" : "Analizar ahora"}
              </Button>
            ) : null}
          </>
        }
      />

      {status.isError ? <ErrorState title="No se pudo cargar el asesor" /> : null}
      {status.isSuccess && !bot ? <SetupCard onSetup={() => setup.mutate()} loading={setup.isPending} /> : null}

      {bot ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <BotIcon className="size-3.5" aria-hidden />
            <Link href="/ai/automations" className="hover:text-foreground hover:underline">
              {bot.name}
            </Link>
            <Badge variant={bot.enabled ? "positive" : "neutral"}>{bot.enabled ? "Activo" : "Pausado"}</Badge>
          </span>
          {bot.next_run_at ? <span>Próximo análisis: {formatDateTime(utc(bot.next_run_at))}</span> : null}
          {status.data?.last_report_at ? (
            <span>Último informe: {formatDateTime(utc(status.data.last_report_at))}</span>
          ) : null}
          {bot.last_thread_id ? (
            <Link href={`/ai/assistant?thread=${bot.last_thread_id}`} className="hover:text-foreground hover:underline">
              Ver último análisis
            </Link>
          ) : null}
          <Link href="/ai/settings" className="inline-flex items-center gap-1 hover:text-foreground hover:underline">
            <Brain className="size-3.5" aria-hidden />
            Tu perfil en memoria
          </Link>
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card>
          <CardHeader className="py-3">
            <div>
              <CardTitle>Recomendaciones actuales</CardTitle>
              <CardDescription>La última opinión del asesor para cada activo y horizonte</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            {latest.isLoading ? <SkeletonText lines={5} /> : null}
            {latest.isSuccess && !assets.length ? (
              <EmptyState
                icon={<Target className="size-4" aria-hidden />}
                title="Todavía no hay recomendaciones"
                description={
                  bot
                    ? "Pulsa «Analizar ahora» o espera al próximo análisis programado."
                    : "Activa el asesor o pídele consejo en el chat."
                }
              />
            ) : null}
            {assets.length ? <AdviceTable assets={assets} /> : null}
            <div className="mt-4">
              <AdviceDisclaimer />
            </div>
          </CardContent>
        </Card>
        <div className="space-y-5">
          <EvaluationCard />
          <NewsCard />
        </div>
      </div>
      <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Newspaper className="size-3" aria-hidden />
        Cotizaciones y noticias de Yahoo Finance y de los feeds RSS configurados.
      </p>
    </div>
  );
}
