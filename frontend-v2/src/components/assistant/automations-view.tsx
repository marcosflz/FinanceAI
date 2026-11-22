"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Loader2, Play, Plus, Trash2 } from "lucide-react";
import { botsApi, skillsApi } from "@/lib/agent-api";
import type { Bot as BotType, BotTemplate, Skill } from "@/lib/agent-types";
import { ApiError } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { formatDateTime } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/feedback";
import { Field, Input, Switch, Textarea } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page-header";
import { useToast } from "@/components/ui/toast";
import { SkillsPicker } from "@/components/assistant/skills-picker";

const STATUS: Record<string, { label: string; variant: "positive" | "warning" | "negative" }> = {
  completed: { label: "Correcto", variant: "positive" },
  interrupted: { label: "Pide aprobación", variant: "warning" },
  error: { label: "Error", variant: "negative" },
};

function namesToIds(skills: Skill[], names: string[]): number[] {
  return skills.filter((skill) => names.includes(skill.name)).map((skill) => skill.id);
}

function idsToNames(skills: Skill[], ids: number[]): string[] {
  return skills.filter((skill) => ids.includes(skill.id)).map((skill) => skill.name);
}

function BotForm({
  templates,
  skills,
  onDone,
}: {
  templates: BotTemplate[];
  skills: Skill[];
  onDone: () => void;
}) {
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [cron, setCron] = useState("0 9 * * *");
  const [template, setTemplate] = useState<string | null>(null);
  const [skillNames, setSkillNames] = useState<string[]>([]);
  const create = useMutation({
    mutationFn: () =>
      botsApi.create({ name, prompt, cron, template, skill_ids: namesToIds(skills, skillNames) }),
    onSuccess: () => {
      setName("");
      setPrompt("");
      setTemplate(null);
      setSkillNames([]);
      onDone();
      toast({ title: "Automatización creada", variant: "success" });
    },
    onError: (error) =>
      toast({
        title: "No se pudo crear",
        description: error instanceof ApiError ? error.message : "",
        variant: "error",
      }),
  });

  function applyTemplate(item: BotTemplate) {
    setTemplate(item.id);
    setName(item.name);
    setPrompt(item.prompt);
    setCron(item.cron);
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <Card>
      <CardHeader className="py-3">
        <div>
          <CardTitle>Nueva automatización</CardTitle>
          <CardDescription>Empieza con una plantilla o escribe tu propia instrucción</CardDescription>
        </div>
        <Plus className="size-4 text-muted-foreground" aria-hidden />
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <div className="flex flex-wrap gap-1.5">
          {templates.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => applyTemplate(item)}
              className={`rounded-full border px-3 py-1 text-[12px] transition-colors ${
                template === item.id
                  ? "border-accent bg-accent-soft text-accent-soft-foreground"
                  : "border-border text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              {item.name}
            </button>
          ))}
        </div>
        <form className="space-y-3" onSubmit={onSubmit}>
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_200px]">
            <Field label="Nombre" htmlFor="bot-name">
              <Input id="bot-name" value={name} onChange={(event) => setName(event.target.value)} />
            </Field>
            <Field label="Cuándo (cron)" htmlFor="bot-cron" hint="min hora día mes día-semana · Europa/Madrid">
              <Input
                id="bot-cron"
                className="num"
                value={cron}
                onChange={(event) => setCron(event.target.value)}
              />
            </Field>
          </div>
          <Field label="Instrucción" htmlFor="bot-prompt">
            <Textarea id="bot-prompt" rows={3} value={prompt} onChange={(event) => setPrompt(event.target.value)} />
          </Field>
          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <SkillsPicker
                skills={skills}
                selected={skillNames}
                onChange={setSkillNames}
                includeDisabled
                label="Skills del bot"
              />
              {skillNames.map((skill) => (
                <Badge key={skill} variant="accent" className="font-mono">
                  {skill}
                </Badge>
              ))}
            </div>
            <Button
              type="submit"
              size="sm"
              variant="primary"
              disabled={!name.trim() || !prompt.trim() || !cron.trim() || create.isPending}
            >
              {create.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Plus className="size-3.5" aria-hidden />}
              Crear
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function BotRow({ bot, skills, onChange }: { bot: BotType; skills: Skill[]; onChange: () => void }) {
  const { toast } = useToast();
  const confirm = useConfirm();
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => botsApi.update(bot.id, { enabled }),
    onSuccess: onChange,
  });
  const run = useMutation({
    mutationFn: () => botsApi.runNow(bot.id),
    onSuccess: (result) => {
      onChange();
      toast({
        title: result.status === "error" ? "La ejecución falló" : "Ejecución terminada",
        description: result.error ?? undefined,
        variant: result.status === "error" ? "error" : "success",
      });
    },
  });
  const remove = useMutation({ mutationFn: () => botsApi.remove(bot.id), onSuccess: onChange });
  const setSkills = useMutation({
    mutationFn: (names: string[]) => botsApi.update(bot.id, { skill_ids: namesToIds(skills, names) }),
    onSuccess: onChange,
  });
  const botSkills = idsToNames(skills, bot.skill_ids ?? []);
  const status = bot.last_status ? STATUS[bot.last_status] : null;

  async function onDelete() {
    const ok = await confirm({
      title: `¿Borrar «${bot.name}»?`,
      description: "Se cancela su programación. Las conversaciones que generó se conservan.",
      confirmLabel: "Borrar",
      tone: "danger",
    });
    if (ok) remove.mutate();
  }

  return (
    <div className="flex flex-col gap-2 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 text-[13px] font-medium">
          <Bot className="size-3.5 text-accent" aria-hidden />
          {bot.name}
          {status ? <Badge variant={status.variant}>{status.label}</Badge> : null}
        </p>
        <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">{bot.prompt}</p>
        {botSkills.length ? (
          <p className="mt-1 flex flex-wrap gap-1">
            {botSkills.map((skill) => (
              <Badge key={skill} variant="accent" className="font-mono">
                {skill}
              </Badge>
            ))}
          </p>
        ) : null}
        <p className="num mt-1 text-[10px] text-muted-foreground">
          {bot.cron} · {bot.enabled && bot.next_run_at ? `próxima ${formatDateTime(`${bot.next_run_at}Z`)}` : "pausada"}
          {bot.last_run_at ? ` · última ${formatDateTime(`${bot.last_run_at}Z`)}` : ""}
          {bot.last_thread_id ? (
            <>
              {" · "}
              <Link href={`/ai/assistant?thread=${bot.last_thread_id}`} className="underline underline-offset-2">
                ver resultado
              </Link>
            </>
          ) : null}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <SkillsPicker
          skills={skills}
          selected={botSkills}
          onChange={(names) => setSkills.mutate(names)}
          disabled={setSkills.isPending}
          includeDisabled
        />
        <Switch
          checked={bot.enabled}
          onChange={(enabled) => toggle.mutate(enabled)}
          label={`Activar ${bot.name}`}
          hideLabel
        />
        <Button size="sm" variant="outline" onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Play className="size-3.5" aria-hidden />}
          Ejecutar ahora
        </Button>
        <Button size="icon" variant="ghost" onClick={onDelete} aria-label={`Borrar ${bot.name}`}>
          <Trash2 className="size-3.5" aria-hidden />
        </Button>
      </div>
    </div>
  );
}

export function AutomationsView() {
  const queryClient = useQueryClient();
  const me = useMe();
  const templates = useQuery({ queryKey: ["agent", "bot-templates"], queryFn: () => botsApi.templates() });
  const bots = useQuery({ queryKey: ["agent", "bots"], queryFn: () => botsApi.list() });
  const skills = useQuery({ queryKey: ["agent", "skills"], queryFn: () => skillsApi.list() });
  const skillItems = skills.data?.items ?? [];
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["agent", "bots"] });
  const encrypted = Boolean(me.data?.tenancy?.encryption);
  const automationActive = Boolean(
    me.data?.automation_until && new Date(me.data.automation_until) > new Date(),
  );

  return (
    <div className="space-y-4">
      <PageHeader
        eyebrow="IA"
        title="Automatizaciones"
        description="Tareas que el asistente ejecuta solo: resúmenes, revisiones y alertas. Si proponen cambios, te llegan como aprobaciones pendientes."
      />
      {encrypted && !automationActive ? (
        <div className="rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-[12px] leading-5">
          Tus datos están cifrados con tu contraseña: las automatizaciones solo se ejecutan
          mientras tienes la sesión abierta, salvo que actives la ejecución sin sesión en{" "}
          <Link href="/settings?section=seguridad" className="font-medium underline underline-offset-2">
            Ajustes → Seguridad
          </Link>
          . Las ejecuciones perdidas se recuperan al volver a entrar.
        </div>
      ) : null}
      <BotForm templates={templates.data?.items ?? []} skills={skillItems} onDone={refresh} />
      <Card>
        <CardHeader className="py-3">
          <div>
            <CardTitle>Programadas</CardTitle>
            <CardDescription>Cada ejecución crea una conversación con el resultado</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {bots.data?.items.length ? (
            <div className="divide-y divide-border border-t border-border">
              {bots.data.items.map((bot) => (
                <BotRow key={bot.id} bot={bot} skills={skillItems} onChange={refresh} />
              ))}
            </div>
          ) : (
            <EmptyState title="Sin automatizaciones" description="Crea una desde una plantilla." />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
