"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, KeyRound, Link2, Loader2, Sparkles, Trash2 } from "lucide-react";
import { aiApi } from "@/lib/agent-api";
import type { AiCatalogProvider, AiProviderConfig } from "@/lib/agent-types";
import { ApiError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { Field, Input } from "@/components/ui/form";
import { SelectMenu } from "@/components/ui/select-menu";
import { useToast } from "@/components/ui/toast";

function ProviderCard({
  info,
  config,
}: {
  info: AiCatalogProvider;
  config: AiProviderConfig | undefined;
}) {
  const { toast } = useToast();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(config?.model ?? info.models[0] ?? "");
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["ai", "providers"] });

  const save = useMutation({
    mutationFn: (payload: { api_key?: string; model?: string; is_default?: boolean }) =>
      aiApi.save(info.id, payload),
    onSuccess: () => {
      setApiKey("");
      refresh();
      toast({ title: `${info.label} guardado`, variant: "success" });
    },
    onError: (error) =>
      toast({
        title: "No se pudo guardar",
        description: error instanceof ApiError ? error.message : "",
        variant: "error",
      }),
  });
  const remove = useMutation({ mutationFn: () => aiApi.remove(info.id), onSuccess: refresh });

  async function onRemove() {
    const ok = await confirm({
      title: `¿Quitar ${info.label}?`,
      description: "Se borra la API key guardada en tu base de datos cifrada.",
      confirmLabel: "Quitar",
      tone: "danger",
    });
    if (ok) remove.mutate();
  }

  return (
    <div className="space-y-2 rounded-lg border border-border p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-[13px] font-medium">
            {info.label}
            {config?.is_default ? <Badge variant="accent">Por defecto</Badge> : null}
            {config?.has_key ? (
              <Badge variant="positive">
                <KeyRound className="size-2.5" aria-hidden />
                <span className="num">{config.key_hint}</span>
              </Badge>
            ) : null}
          </p>
          <p className="text-[11px] text-muted-foreground">{info.notes}</p>
        </div>
        {config ? (
          <Button size="icon" variant="ghost" onClick={onRemove} aria-label={`Quitar ${info.label}`}>
            <Trash2 className="size-3.5" aria-hidden />
          </Button>
        ) : null}
      </div>
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_200px_auto] sm:items-end">
        <Field label={config?.has_key ? "Nueva API key (opcional)" : "API key"} htmlFor={`key-${info.id}`}>
          <Input
            id={`key-${info.id}`}
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
          />
        </Field>
        <Field label="Modelo" htmlFor={`model-${info.id}`}>
          <SelectMenu
            id={`model-${info.id}`}
            value={model}
            onValueChange={setModel}
            options={info.models.map((item) => ({ value: item, label: item }))}
          />
        </Field>
        <div className="flex gap-1.5">
          <Button
            size="sm"
            variant="primary"
            disabled={save.isPending || (!apiKey && !config?.has_key)}
            onClick={() => save.mutate({ api_key: apiKey || undefined, model })}
          >
            {save.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
            Guardar
          </Button>
          {config && !config.is_default ? (
            <Button size="sm" onClick={() => save.mutate({ is_default: true })}>
              Usar por defecto
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function SubscriptionCard({
  info,
  config,
}: {
  info: AiCatalogProvider;
  config: AiProviderConfig | undefined;
}) {
  const { toast } = useToast();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const isClaude = info.link === "claude";
  const [link, setLink] = useState<{ link_id: string; url: string } | null>(null);
  const [answer, setAnswer] = useState("");
  const [token, setToken] = useState("");
  const [model, setModel] = useState(config?.model ?? info.models[0] ?? "");
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["ai", "providers"] });
  const chatgptModels = useQuery({
    queryKey: ["ai", "chatgpt-models"],
    queryFn: () => aiApi.chatgptModels(),
    enabled: !isClaude && Boolean(config?.has_key),
  });
  const models = isClaude ? info.models : chatgptModels.data?.items ?? (config?.model ? [config.model] : []);

  const onError = (title: string) => (error: unknown) =>
    toast({ title, description: error instanceof ApiError ? error.message : "", variant: "error" });

  const start = useMutation({
    mutationFn: () => aiApi.linkStart(info.id),
    onSuccess: (result) => {
      setLink(result);
      window.open(result.url, "_blank", "noopener,noreferrer");
    },
    onError: onError("No se pudo iniciar la vinculación"),
  });
  const finish = useMutation({
    mutationFn: () =>
      aiApi.linkFinish(info.id, {
        link_id: link?.link_id ?? "",
        ...(isClaude ? { code: answer } : { redirect_url: answer }),
      }),
    onSuccess: (result) => {
      setLink(null);
      setAnswer("");
      if (result.model) setModel(result.model);
      refresh();
      queryClient.invalidateQueries({ queryKey: ["ai", "chatgpt-models"] });
      toast({ title: `${info.label} vinculado`, variant: "success" });
    },
    onError: onError("No se pudo vincular"),
  });
  const saveToken = useMutation({
    mutationFn: () => aiApi.save(info.id, { api_key: token, model }),
    onSuccess: () => {
      setToken("");
      refresh();
      toast({ title: `${info.label} guardado`, variant: "success" });
    },
    onError: onError("No se pudo guardar"),
  });
  const saveModel = useMutation({
    mutationFn: (payload: { model?: string; is_default?: boolean }) => aiApi.save(info.id, payload),
    onSuccess: refresh,
    onError: onError("No se pudo guardar"),
  });
  const remove = useMutation({ mutationFn: () => aiApi.remove(info.id), onSuccess: refresh });

  async function onRemove() {
    const ok = await confirm({
      title: `¿Desvincular ${info.label}?`,
      description: "Se borra el token de tu base de datos cifrada.",
      confirmLabel: "Desvincular",
      tone: "danger",
    });
    if (ok) remove.mutate();
  }

  return (
    <div className="space-y-2 rounded-lg border border-border p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-1.5 text-[13px] font-medium">
            {info.label}
            <Badge variant="outline">Suscripción personal</Badge>
            {config?.is_default ? <Badge variant="accent">Por defecto</Badge> : null}
            {config?.has_key ? <Badge variant="positive">{config.key_hint ?? "Vinculado"}</Badge> : null}
          </p>
          <p className="text-[11px] text-muted-foreground">{info.notes}</p>
        </div>
        {config ? (
          <Button size="icon" variant="ghost" onClick={onRemove} aria-label={`Desvincular ${info.label}`}>
            <Trash2 className="size-3.5" aria-hidden />
          </Button>
        ) : null}
      </div>

      {link ? (
        <div className="space-y-2 rounded-lg border border-border bg-subtle p-2.5">
          <ol className="list-decimal space-y-1 pl-4 text-[11px] text-muted-foreground">
            <li>
              Autoriza en la página que se ha abierto (
              <a href={link.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 underline">
                abrir de nuevo <ExternalLink className="size-3" aria-hidden />
              </a>
              ).
            </li>
            <li>
              {isClaude
                ? "Copia el código que te muestra Anthropic y pégalo aquí."
                : "Al terminar, el navegador irá a una página de http://127.0.0.1:1455/ que no carga: copia la dirección completa y pégala aquí."}
            </li>
          </ol>
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <Field label={isClaude ? "Código de Anthropic" : "Dirección de la redirección"} htmlFor={`answer-${info.id}`}>
              <Input
                id={`answer-${info.id}`}
                autoComplete="off"
                spellCheck={false}
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
              />
            </Field>
            <div className="flex gap-1.5">
              <Button size="sm" variant="primary" disabled={!answer || finish.isPending} onClick={() => finish.mutate()}>
                {finish.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
                Completar
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  aiApi.linkCancel(info.id, link.link_id).catch(() => undefined);
                  setLink(null);
                }}
              >
                Cancelar
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-end gap-2">
          <Button size="sm" variant={config?.has_key ? "outline" : "primary"} disabled={start.isPending} onClick={() => start.mutate()}>
            {start.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Link2 className="size-3.5" aria-hidden />}
            {config?.has_key ? "Volver a vincular" : isClaude ? "Vincular con Claude" : "Sign in with ChatGPT"}
          </Button>
          {config?.has_key && models.length ? (
            <div className="w-48">
              <SelectMenu
                aria-label={`Modelo de ${info.label}`}
                value={config.model ?? model}
                onValueChange={(next) => {
                  setModel(next);
                  saveModel.mutate({ model: next });
                }}
                options={models.map((item) => ({ value: item, label: item }))}
              />
            </div>
          ) : null}
          {config?.has_key && !config.is_default ? (
            <Button size="sm" onClick={() => saveModel.mutate({ is_default: true })}>
              Usar por defecto
            </Button>
          ) : null}
        </div>
      )}

      {isClaude && !link ? (
        <details className="text-[11px] text-muted-foreground">
          <summary className="cursor-pointer">¿Prefieres pegar el token de `claude setup-token`?</summary>
          <div className="mt-2 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <Field label="Token de Claude Code" htmlFor={`token-${info.id}`}>
              <Input
                id={`token-${info.id}`}
                type="password"
                autoComplete="off"
                value={token}
                onChange={(event) => setToken(event.target.value)}
              />
            </Field>
            <Button size="sm" disabled={!token || saveToken.isPending} onClick={() => saveToken.mutate()}>
              Guardar token
            </Button>
          </div>
        </details>
      ) : null}
    </div>
  );
}

export function AssistantSection() {
  const catalog = useQuery({ queryKey: ["ai", "catalog"], queryFn: () => aiApi.catalog() });
  const providers = useQuery({ queryKey: ["ai", "providers"], queryFn: () => aiApi.providers() });
  const configs = new Map((providers.data?.items ?? []).map((item) => [item.provider, item]));

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="py-3">
          <div>
            <CardTitle>Proveedores de IA del asistente</CardTitle>
            <CardDescription>
              Tus claves se guardan dentro de tu base de datos cifrada y solo se usan en tus
              conversaciones y automatizaciones
            </CardDescription>
          </div>
          <Sparkles className="size-4 text-muted-foreground" aria-hidden />
        </CardHeader>
        <CardContent className="space-y-2 pt-0">
          {catalog.data?.fake ? (
            <p className="rounded-lg bg-muted px-3 py-2 text-[11px] text-muted-foreground">
              Modo de desarrollo: el servidor usa un modelo simulado (AGENT_FAKE_LLM).
            </p>
          ) : null}
          {(catalog.data?.items ?? []).map((info) =>
            info.link === "key" ? (
              <ProviderCard key={info.id} info={info} config={configs.get(info.id)} />
            ) : (
              <SubscriptionCard key={info.id} info={info} config={configs.get(info.id)} />
            ),
          )}
          <p className="text-[11px] leading-5 text-muted-foreground">
            El proveedor que elijas recibe los datos que el asistente consulte para responderte
            (movimientos, importes, comercios). Cada clave y cada suscripción es tuya: se guarda
            en tu base de datos y nadie más la usa.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
