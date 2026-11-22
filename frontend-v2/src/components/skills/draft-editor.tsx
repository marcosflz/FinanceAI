"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, CheckCircle2, FileText, MessageSquare, Upload, Wand2 } from "lucide-react";
import { agentApi, aiApi, skillsApi } from "@/lib/agent-api";
import type { AgentEvent, SkillFiles } from "@/lib/agent-types";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { applyEvent, emptyLive, type LiveState } from "@/components/assistant/chat-stream";
import { Composer } from "@/components/assistant/composer";
import { MessageView } from "@/components/assistant/message-view";
import { ModelPicker, useModelChoice } from "@/components/assistant/model-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorState, SkeletonText } from "@/components/ui/feedback";
import { Markdown } from "@/components/ui/markdown";
import { Segmented } from "@/components/ui/segmented";
import { SelectMenu } from "@/components/ui/select-menu";
import { useToast } from "@/components/ui/toast";

const DRAFT_WRITES = new Set(["write_draft_file", "delete_draft_file"]);
type Tab = "preview" | "files" | "changes";

/** Separa el frontmatter YAML del cuerpo de SKILL.md para la vista previa. */
export function splitSkillMd(text: string): { meta: Record<string, string>; body: string } {
  const match = text.replace(/\r\n/g, "\n").match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!match) return { meta: {}, body: text };
  const meta: Record<string, string> = {};
  for (const line of match[1].split("\n")) {
    const pair = line.match(/^([\w-]+):\s*(.*)$/);
    if (pair) meta[pair[1]] = pair[2].replace(/^["']|["']$/g, "");
  }
  return { meta, body: match[2] };
}

export function SkillPreview({ files }: { files: SkillFiles }) {
  const skillMd = files["SKILL.md"];
  if (!skillMd) {
    return (
      <p className="text-[13px] text-muted-foreground">
        El creador preparará aquí la skill a partir de vuestra conversación.
      </p>
    );
  }
  const { meta, body } = splitSkillMd(skillMd);
  const others = Object.keys(files).filter((path) => path !== "SKILL.md");
  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-surface-2 px-4 py-3">
        <p className="font-mono text-[13px] font-medium">{meta.name ?? "sin-nombre"}</p>
        <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{meta.description ?? "Sin descripción"}</p>
      </div>
      <Markdown compact>{body}</Markdown>
      {others.length ? (
        <div className="border-t border-border pt-3">
          <p className="mb-1.5 text-[12px] text-muted-foreground">Recursos</p>
          <ul className="space-y-1">
            {others.map((path) => (
              <li key={path} className="flex items-center gap-1.5 font-mono text-[12px]">
                <FileText className="size-3.5 text-muted-foreground" aria-hidden />
                {path}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function SkillDraftEditor({ id }: { id: number }) {
  const router = useRouter();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const key = useMemo(() => ["agent", "skill-draft", id] as const, [id]);
  const detail = useQuery({ queryKey: key, queryFn: () => skillsApi.draft(id) });
  const providers = useQuery({ queryKey: ["ai", "providers"], queryFn: () => aiApi.providers() });
  const catalog = useQuery({ queryKey: ["ai", "catalog"], queryFn: () => aiApi.catalog() });
  const [choice, setChoice] = useModelChoice();

  const [tab, setTab] = useState<Tab>("preview");
  const [mobilePane, setMobilePane] = useState<"chat" | "draft">("chat");
  const [path, setPath] = useState("SKILL.md");
  const [editor, setEditor] = useState<string | null>(null);
  const [newPath, setNewPath] = useState("");
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const [live, setLive] = useState<LiveState | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const busy = live !== null;

  const data = detail.data;
  const files = useMemo(() => data?.files ?? {}, [data?.files]);
  const dirty = editor !== null && editor !== (files[path] ?? "");

  const refresh = useCallback(() => queryClient.invalidateQueries({ queryKey: key }), [queryClient, key]);

  const runStream = useCallback(
    async (start: (onEvent: (event: AgentEvent) => void, signal: AbortSignal) => Promise<void>) => {
      const controller = new AbortController();
      abortRef.current = controller;
      setLive(emptyLive());
      try {
        await start((event) => {
          setLive((current) => applyEvent(current ?? emptyLive(), event));
          // El borrador cambia en vivo mientras el creador escribe archivos.
          if (event.type === "TOOL_CALL_RESULT" && DRAFT_WRITES.has(event.name)) void refresh();
          if (event.type === "RUN_ERROR") {
            toast({ title: "El creador ha fallado", description: event.message, variant: "error" });
          }
        }, controller.signal);
      } catch (error) {
        toast({
          title: "No se pudo enviar",
          description: error instanceof ApiError ? error.message : "Error de conexión",
          variant: "error",
        });
      } finally {
        abortRef.current = null;
        await refresh();
        setLive(null);
        setPendingUser(null);
      }
    },
    [refresh, toast],
  );

  const activeRun = data?.active_run_id ?? null;
  useEffect(() => {
    if (!activeRun || abortRef.current) return;
    void runStream((onEvent, signal) => agentApi.follow(activeRun, 0, onEvent, signal));
  }, [activeRun, runStream]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [data?.messages.length, live?.message.parts, pendingUser]);

  function send(text: string) {
    if (abortRef.current) return;
    if (dirty) {
      toast({ title: "Guarda o descarta tu edición antes de hablar con el creador", variant: "error" });
      return;
    }
    setPendingUser(text);
    void runStream((onEvent, signal) =>
      skillsApi.send(id, { message: text, provider: choice?.provider, model: choice?.model }, onEvent, signal),
    );
  }

  async function save(changes: Record<string, string | null>) {
    if (!data) return;
    setSaving(true);
    try {
      await skillsApi.saveDraft(id, data.revision, changes);
      setEditor(null);
      await refresh();
      toast({ title: "Borrador guardado", variant: "success" });
    } catch (error) {
      toast({
        title: "No se pudo guardar",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  async function publish() {
    setPublishing(true);
    try {
      const result = await skillsApi.publish(id);
      queryClient.invalidateQueries({ queryKey: ["agent", "skills"] });
      queryClient.invalidateQueries({ queryKey: ["agent", "skill-drafts"] });
      toast({ title: `«${result.name}» v${result.version} publicada`, variant: "success" });
      router.push(`/ai/skills/${result.skill_id}`);
    } catch (error) {
      toast({
        title: "No se pudo publicar",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
      setPublishing(false);
    }
  }

  if (detail.isError) return <ErrorState title="No se pudo cargar el borrador" />;
  if (!data) return <SkeletonText lines={6} />;

  const validation = data.validation;
  const paths = [...new Set(["SKILL.md", ...Object.keys(files)])];
  const baseFiles = data.base_files;
  const changed = baseFiles
    ? [...new Set([...Object.keys(baseFiles), ...Object.keys(files)])].filter((name) => baseFiles[name] !== files[name])
    : [];
  const binary = path in files && files[path] === null;

  return (
    <div className="space-y-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <Link
            href="/ai/skills"
            className="inline-flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-3.5" aria-hidden />
            Skills
          </Link>
          <h1 className="mt-1 flex items-center gap-2 text-[22px] font-semibold tracking-[-0.02em]">
            <Wand2 className="size-5 text-accent" aria-hidden />
            Creador de skills
          </h1>
          <p className="mt-1 text-[13px] text-muted-foreground">
            Conversa con el creador, revisa el borrador y publícalo en tu biblioteca.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {validation ? (
            validation.ok ? (
              <Badge variant="positive">
                <CheckCircle2 className="size-3" aria-hidden /> Válida
              </Badge>
            ) : (
              <Badge variant="warning" title={validation.error}>
                <AlertTriangle className="size-3" aria-hidden /> Incompleta
              </Badge>
            )
          ) : null}
          <Button
            variant="primary"
            size="sm"
            loading={publishing}
            disabled={busy || dirty || !validation?.ok}
            onClick={() => void publish()}
          >
            <Upload className="size-3.5" aria-hidden />
            {data.skill_id ? "Publicar nueva versión" : "Publicar"}
          </Button>
        </div>
      </header>

      <Segmented
        className="lg:hidden"
        aria-label="Panel"
        value={mobilePane}
        onChange={setMobilePane}
        options={[
          { value: "chat", label: "Conversación" },
          { value: "draft", label: "Borrador" },
        ]}
      />

      <div className="grid gap-4 lg:h-[calc(100svh-294px)] lg:min-h-[520px] lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section
          className={cn(
            "card flex h-[calc(100svh-364px)] min-h-[420px] flex-col overflow-hidden lg:h-auto",
            mobilePane !== "chat" && "hidden lg:flex",
          )}
        >
          <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {!data.messages.length && !pendingUser ? (
              <div className="flex items-start gap-2.5 rounded-xl bg-surface-2 p-4 text-[13px] leading-5 text-muted-foreground">
                <MessageSquare className="mt-0.5 size-4 shrink-0" aria-hidden />
                <p>
                  Cuéntale qué tarea quieres enseñar al asistente. Por ejemplo: «Quiero una skill que cada mes
                  me resuma el gasto por categoría, lo compare con el mes anterior y señale suscripciones nuevas».
                </p>
              </div>
            ) : null}
            {data.messages.map((message, index) => (
              <MessageView
                key={message.id}
                message={message}
                compact
                last={index === data.messages.length - 1 && !live && !pendingUser}
              />
            ))}
            {pendingUser ? (
              <MessageView compact message={{ id: "pending-user", role: "user", content: pendingUser, parts: [] }} />
            ) : null}
            {live ? <MessageView compact message={live.message} streaming runningCalls={live.running} busy /> : null}
            <div ref={bottomRef} />
          </div>
          <div className="border-t border-border p-3">
            <Composer
              onSend={send}
              busy={busy}
              placeholder={data.messages.length ? "Pide cambios al creador…" : "¿Qué debe hacer esta skill?"}
              right={
                <ModelPicker
                  providers={providers.data?.items ?? []}
                  catalog={catalog.data?.items ?? []}
                  value={choice}
                  onChange={setChoice}
                />
              }
            />
          </div>
        </section>

        <section
          className={cn(
            "card flex min-h-[420px] flex-col overflow-hidden",
            mobilePane !== "draft" && "hidden lg:flex",
          )}
        >
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
            <Segmented
              aria-label="Vista del borrador"
              value={tab}
              onChange={setTab}
              options={[
                { value: "preview", label: "Borrador" },
                { value: "files", label: "Archivos" },
                ...(baseFiles ? [{ value: "changes" as const, label: `Cambios · ${changed.length}` }] : []),
              ]}
            />
            <span className="tabular text-[12px] text-muted-foreground">
              Revisión {data.revision} · {Object.keys(files).length} archivos
            </span>
          </div>
          {validation && !validation.ok && Object.keys(files).length ? (
            <p className="flex items-start gap-1.5 border-b border-border bg-warning-soft px-4 py-2 text-[12px] text-warning">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {validation.error}
            </p>
          ) : null}
          <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4">
            {tab === "preview" ? <SkillPreview files={files} /> : null}

            {tab === "files" ? (
              <div className="flex h-full flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <SelectMenu
                    aria-label="Archivo del borrador"
                    value={path}
                    disabled={dirty}
                    onValueChange={(next) => {
                      setPath(next);
                      setEditor(null);
                    }}
                    options={paths.map((name) => ({ value: name, label: name }))}
                    className="w-auto min-w-[180px] font-mono text-[12px]"
                  />
                  <form
                    className="flex items-center gap-1.5"
                    onSubmit={(event) => {
                      event.preventDefault();
                      const name = newPath.trim();
                      if (!name) return;
                      setPath(name);
                      setEditor("");
                      setNewPath("");
                    }}
                  >
                    <input
                      value={newPath}
                      onChange={(event) => setNewPath(event.target.value)}
                      placeholder="references/nuevo.md"
                      aria-label="Ruta del archivo nuevo"
                      disabled={dirty}
                      className="h-8 w-44 rounded-lg border border-input bg-card px-2.5 font-mono text-[12px] outline-none focus-visible:border-accent"
                    />
                    <Button size="sm" type="submit" disabled={dirty || !newPath.trim()}>
                      Añadir
                    </Button>
                  </form>
                </div>
                {binary ? (
                  <p className="text-[13px] text-muted-foreground">Archivo binario: se conserva tal cual en el paquete.</p>
                ) : (
                  <>
                    <textarea
                      aria-label="Contenido del archivo"
                      value={editor ?? files[path] ?? ""}
                      disabled={busy}
                      onChange={(event) => setEditor(event.target.value)}
                      spellCheck={false}
                      className="min-h-[360px] w-full flex-1 resize-none rounded-xl border border-input bg-card p-3 font-mono text-[12px] leading-5 outline-none focus-visible:border-accent"
                    />
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="primary"
                        size="sm"
                        loading={saving}
                        disabled={!dirty || busy}
                        onClick={() => void save({ [path]: editor ?? "" })}
                      >
                        Guardar archivo
                      </Button>
                      {dirty ? (
                        <Button size="sm" variant="ghost" onClick={() => setEditor(null)}>
                          Descartar
                        </Button>
                      ) : null}
                      {path !== "SKILL.md" && path in files ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="ml-auto text-negative"
                          disabled={busy || saving}
                          onClick={() => {
                            void save({ [path]: null }).then(() => setPath("SKILL.md"));
                          }}
                        >
                          Borrar archivo
                        </Button>
                      ) : null}
                    </div>
                  </>
                )}
              </div>
            ) : null}

            {tab === "changes" && baseFiles ? (
              changed.length ? (
                <div className="space-y-3">
                  {changed.map((name) => (
                    <details key={name} className="rounded-xl border border-border">
                      <summary className="cursor-pointer px-3 py-2 font-mono text-[12px]">
                        {!(name in baseFiles) ? "+ " : !(name in files) ? "− " : "~ "}
                        {name}
                      </summary>
                      <div className="grid gap-2 border-t border-border p-3 md:grid-cols-2">
                        <pre className="scrollbar-thin max-h-72 overflow-auto rounded-lg bg-negative-soft/60 p-2 text-[11px] leading-4">
                          {name in baseFiles ? baseFiles[name] ?? "Binario" : "No existía"}
                        </pre>
                        <pre className="scrollbar-thin max-h-72 overflow-auto rounded-lg bg-positive-soft/60 p-2 text-[11px] leading-4">
                          {name in files ? files[name] ?? "Binario" : "Eliminado"}
                        </pre>
                      </div>
                    </details>
                  ))}
                </div>
              ) : (
                <p className="text-[13px] text-muted-foreground">Sin cambios respecto a la versión publicada.</p>
              )
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
}
