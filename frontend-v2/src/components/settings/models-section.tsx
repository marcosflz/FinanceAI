"use client";

import { useEffect, useState } from "react";
import {
  BrainCircuit,
  CheckCircle2,
  Cpu,
  Gauge,
  KeyRound,
  Save,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { modelsApi } from "@/lib/api";
import type { ModelSettings } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";

const documentModels = [
  { value: "deepseek-v4.1-flash", label: "DeepSeek V4.1 Flash · 0 días", retention: 0 },
  { value: "glm-5.3-flash", label: "GLM-5.3 Flash · 0 días", retention: 0 },
  { value: "qwen3.8-flash", label: "Qwen3.8 Flash · 0 días", retention: 0 },
  { value: "mimo-v2.6-flash", label: "MiMo v2.6 Flash · 0 días", retention: 0 },
  { value: "gpt-6-luna", label: "GPT-6 Luna · 30 días", retention: 30 },
];

function numberValue(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function ModelsSection() {
  const { toast } = useToast();
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [fallbackModel, setFallbackModel] = useState("glm-5.3-flash");

  useEffect(() => {
    let mounted = true;
    void modelsApi
      .get()
      .then((data) => {
        if (!mounted) return;
        setSettings(data);
        setFallbackModel(data.opencode_fallback_models[0] ?? "glm-5.3-flash");
      })
      .catch(() => {
        if (mounted) setSettings(null);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  function update<K extends keyof ModelSettings>(key: K, value: ModelSettings[K]) {
    setSettings((current) => (current ? { ...current, [key]: value } : current));
  }

  async function save() {
    if (!settings || saving) return;
    setSaving(true);
    try {
      const saved = await modelsApi.update({
        jev_model: settings.jev_model,
        jev_reference_max: settings.jev_reference_max,
        classification_batch_size: settings.classification_batch_size,
        jev_max_calls_per_run: settings.jev_max_calls_per_run,
        opencode_model: settings.opencode_model,
        opencode_fallback_models: [fallbackModel],
        ocr_lang: settings.ocr_lang,
        ocr_dpi: settings.ocr_dpi,
        auto_approve_threshold: settings.auto_approve_threshold,
      });
      setSettings(saved);
      setFallbackModel(saved.opencode_fallback_models[0] ?? fallbackModel);
      toast({
        title: "Configuración guardada",
        description: "Los cambios se aplican al próximo import o lote de clasificación.",
        variant: "success",
      });
    } catch {
      toast({
        title: "No se pudo guardar",
        description: "Revisa los rangos y que la API v3 esté disponible.",
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-36 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="rounded-lg border border-negative/25 bg-negative-soft px-3 py-2.5 text-[11px] text-negative">
        No se pudo cargar la configuración de modelos.
      </div>
    );
  }

  const selectedModel =
    documentModels.find((model) => model.value === settings.opencode_model) ??
    documentModels[0];
  const referenceLimits = settings.limits.jev_reference_max;
  const batchLimits = settings.limits.classification_batch_size;
  const callLimits = settings.limits.jev_max_calls_per_run;
  const dpiLimits = settings.limits.ocr_dpi;

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 rounded-lg border border-border bg-card px-3 py-2.5 text-[11px] leading-5 text-muted-foreground">
        <KeyRound className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden />
        <p>
          Las API keys siguen en el servidor (<span className="num">TYPESAFE_API_KEY</span> y{" "}
          <span className="num">OPENCODE_API_KEY</span>) y no se guardan en{" "}
          <span className="num">app_config</span>. Aquí solo se editan parámetros no
          sensibles del modelo.
        </p>
      </div>

      <Card>
        <CardHeader className="py-3">
          <div>
            <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
              <BrainCircuit className="size-3" aria-hidden />
              Decisor tipado
            </p>
            <CardTitle className="mt-1">Jev · TypeSafe</CardTitle>
            <CardDescription>
              El contexto son ejemplos aceptados que se envían en cada lote. Empieza
              en 0 y crece hasta el límite que configures.
            </CardDescription>
          </div>
          <Badge variant={settings.typesafe_configured ? "positive" : "warning"} dot>
            {settings.typesafe_configured ? "Clave configurada" : "Sin clave"}
          </Badge>
        </CardHeader>
        <CardContent className="pt-1">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Modelo" htmlFor="jev-model" hint="Endpoint síncrono de TypeSafe">
              <Select
                id="jev-model"
                value={settings.jev_model}
                onChange={(event) => update("jev_model", event.target.value)}
              >
                <option value="jev-latest">jev-latest</option>
              </Select>
            </Field>
            <Field
              label="Contexto / referencias"
              htmlFor="jev-reference-max"
              hint={`Máximo de ejemplos aceptados enviados a Jev (${referenceLimits[0]}–${referenceLimits[1]})`}
            >
              <Input
                id="jev-reference-max"
                type="number"
                min={referenceLimits[0]}
                max={referenceLimits[1]}
                value={settings.jev_reference_max}
                onChange={(event) =>
                  update("jev_reference_max", numberValue(event.target.value))
                }
              />
            </Field>
            <Field
              label="Movimientos por lote"
              htmlFor="batch-size"
              hint={`Tamaño de la tanda de revisión (${batchLimits[0]}–${batchLimits[1]})`}
            >
              <Input
                id="batch-size"
                type="number"
                min={batchLimits[0]}
                max={batchLimits[1]}
                value={settings.classification_batch_size}
                onChange={(event) =>
                  update("classification_batch_size", numberValue(event.target.value))
                }
              />
            </Field>
            <Field
              label="Llamadas máximas por ejecución"
              htmlFor="jev-max-calls"
              hint={`Protección de coste (${callLimits[0]}–${callLimits[1]})`}
            >
              <Input
                id="jev-max-calls"
                type="number"
                min={callLimits[0]}
                max={callLimits[1]}
                value={settings.jev_max_calls_per_run}
                onChange={(event) =>
                  update("jev_max_calls_per_run", numberValue(event.target.value))
                }
              />
            </Field>
            <Field
              label="Autoaprobar desde"
              htmlFor="auto-approve-threshold"
              hint="Confianza mínima para aprobar sin revisión (0–1; por defecto 0,95)"
            >
              <Input
                id="auto-approve-threshold"
                type="number"
                min={0}
                max={1}
                step="0.01"
                value={settings.auto_approve_threshold}
                onChange={(event) =>
                  update(
                    "auto_approve_threshold",
                    Math.max(0, Math.min(1, Number(event.target.value))),
                  )
                }
              />
            </Field>
          </div>
          <div className="mt-3 flex items-start gap-2 rounded-lg bg-muted px-2.5 py-2 text-[10px] leading-4 text-muted-foreground">
            <Gauge className="mt-0.5 size-3 shrink-0 text-accent" aria-hidden />
            <p>
              Con 40 el siguiente lote envía hasta 40 ejemplos aceptados. Al llegar al
              tope se eligen los más parecidos al movimiento actual, no solo los últimos.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="py-3">
          <div>
            <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
              <Cpu className="size-3" aria-hidden />
              Modelo documental
            </p>
            <CardTitle className="mt-1">OpenCode Go</CardTitle>
            <CardDescription>
              DeepSeek V4.1 Flash es el modelo primario. El fallback solo se usa si
              el modelo principal falla o agota cuota.
            </CardDescription>
          </div>
          <Badge variant={settings.opencode_configured ? "positive" : "warning"} dot>
            {settings.opencode_configured ? "Clave configurada" : "Sin clave"}
          </Badge>
        </CardHeader>
        <CardContent className="pt-1">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Modelo por defecto" htmlFor="go-model">
              <Select
                id="go-model"
                value={settings.opencode_model}
                onChange={(event) => update("opencode_model", event.target.value)}
              >
                {documentModels.map((model) => (
                  <option key={model.value} value={model.value}>
                    {model.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Fallback" htmlFor="go-fallback" hint="Un solo modelo de respaldo">
              <Select
                id="go-fallback"
                value={fallbackModel}
                onChange={(event) => setFallbackModel(event.target.value)}
              >
                {documentModels
                  .filter((model) => model.value !== settings.opencode_model)
                  .map((model) => (
                    <option key={model.value} value={model.value}>
                      {model.label}
                    </option>
                  ))}
              </Select>
            </Field>
            <Field label="Idioma OCR" htmlFor="ocr-lang" hint="Tesseract para imágenes/escaneos">
              <Input
                id="ocr-lang"
                value={settings.ocr_lang}
                onChange={(event) => update("ocr_lang", event.target.value)}
              />
            </Field>
            <Field
              label="DPI de OCR"
              htmlFor="ocr-dpi"
              hint={`Render de PDF escaneado (${dpiLimits[0]}–${dpiLimits[1]})`}
            >
              <Input
                id="ocr-dpi"
                type="number"
                min={dpiLimits[0]}
                max={dpiLimits[1]}
                value={settings.ocr_dpi}
                onChange={(event) => update("ocr_dpi", numberValue(event.target.value))}
              />
            </Field>
          </div>

          {selectedModel.retention > 0 ? (
            <div className="mt-3 flex items-start gap-2 rounded-lg bg-warning-soft px-2.5 py-2 text-[10px] leading-4 text-warning">
              <ShieldAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
              GPT-6 Luna retiene datos 30 días. Úsalo solo como fallback y con
              redacción previa de IBAN, nombres y direcciones.
            </div>
          ) : (
            <div className="mt-3 flex items-start gap-2 rounded-lg bg-positive-soft px-2.5 py-2 text-[10px] leading-4 text-positive">
              <CheckCircle2 className="mt-0.5 size-3 shrink-0" aria-hidden />
              Retención 0 días. Aun así, el texto se redacta antes de salir.
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-3 py-2.5">
        <p className="flex items-center gap-1.5 text-[10px] leading-4 text-muted-foreground">
          <Sparkles className="size-3 text-accent" aria-hidden />
          Los cambios se aplican en la siguiente extracción o lote de clasificación.
        </p>
        <Button variant="primary" size="sm" onClick={() => void save()} loading={saving}>
          <Save className="size-3.5" aria-hidden />
          Guardar configuración
        </Button>
      </div>
    </div>
  );
}
