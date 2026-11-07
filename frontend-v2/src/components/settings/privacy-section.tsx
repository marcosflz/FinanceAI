"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  EyeOff,
  LockKeyhole,
  Save,
  ShieldCheck,
  ShieldQuestion,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Switch, Textarea } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";

export function PrivacySection() {
  const { toast } = useToast();
  const [literals, setLiterals] = useState(
    "Marcos Florez Fernandez\nES18 1583 0000 0084 9100 02\nCalle Ejemplo 12, Madrid",
  );
  const [sendDescription, setSendDescription] = useState(true);
  const [redactIban, setRedactIban] = useState(true);
  const [sendImages, setSendImages] = useState(false);
  const [storeEvidence, setStoreEvidence] = useState(true);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="py-3">
          <div>
            <CardTitle>Redacción antes de enviar al modelo</CardTitle>
            <CardDescription>
              Literales que se sustituyen por marcadores en cualquier texto enviado a Jev
              o a OpenCode Go.
            </CardDescription>
          </div>
          <Badge variant="positive">
            <ShieldCheck className="size-2.5" aria-hidden /> Activa
          </Badge>
        </CardHeader>
        <CardContent className="pt-1">
          <Field
            label="Literales sensibles"
            htmlFor="privacy-literals"
            hint="Uno por línea. Se cargan una vez por job en el backend."
          >
            <Textarea
              id="privacy-literals"
              value={literals}
              onChange={(event) => setLiterals(event.target.value)}
              rows={4}
              className="num text-[11px]"
            />
          </Field>

          <div className="mt-2 divide-y divide-border">
            <Switch
              checked={redactIban}
              onChange={setRedactIban}
              label="Redactar IBAN automáticamente"
              description="Se sustituyen por [IBAN] en descripciones y prompts, pero se conserva el IBAN normalizado para el matching interno."
            />
            <Switch
              checked={sendDescription}
              onChange={setSendDescription}
              label="Enviar descripción limpia al decisor"
              description="Solo el estado estructurado (merchant, importe, MCC, tipo). Jev nunca recibe el fichero ni la imagen."
            />
            <Switch
              checked={sendImages}
              onChange={setSendImages}
              label="Permitir imágenes al modelo documental"
              description="Necesario para recibos y PDFs escaneados. Usa DeepSeek V4.1 Flash (0 días) por defecto."
            />
            <Switch
              checked={storeEvidence}
              onChange={setStoreEvidence}
              label="Guardar evidencia de extracción"
              description="Crops, página y bbox para auditar una importación. Se guardan en ./data/files, nunca como BLOB."
            />
          </div>

          <div className="mt-3 flex justify-end border-t border-border pt-3">
            <Button
              variant="primary"
              size="sm"
              onClick={() =>
                toast({
                  title: "Preferencias de privacidad guardadas",
                  description:
                    "Scaffold F5: se conectarán al endpoint de configuración y al cargador de literales del backend.",
                  variant: "success",
                })
              }
            >
              <Save className="size-3.5" aria-hidden />
              Guardar
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="py-3">
            <div>
              <CardTitle>Qué sale de casa</CardTitle>
              <CardDescription>Contrato de datos con proveedores</CardDescription>
            </div>
            <ShieldQuestion className="size-4 text-muted-foreground" aria-hidden />
          </CardHeader>
          <CardContent className="space-y-2 pt-0 text-[11px] leading-5 text-muted-foreground">
            <div className="rounded-lg border border-border bg-subtle p-2.5">
              <p className="font-medium text-foreground">Decisor Jev</p>
              <p className="mt-0.5">
                Merchant, descripción limpia, importe, moneda, MCC, tipo de broker,
                cuenta, contraparte y reglas que han casado. Sin PDFs ni imágenes.
              </p>
            </div>
            <div className="rounded-lg border border-border bg-subtle p-2.5">
              <p className="font-medium text-foreground">OpenCode Go</p>
              <p className="mt-0.5">
                Texto redactado y, si se activa, páginas renderizadas o crops. Retención 0
                días con DeepSeek V4.1 Flash.
              </p>
            </div>
            <div className="flex items-start gap-2 rounded-lg bg-muted px-2.5 py-2 text-[10px] leading-4">
              <EyeOff className="mt-0.5 size-3 shrink-0" aria-hidden />
              Los IBAN y nombres configurados se redactan antes de cualquier llamada. La
              versión del prompt y el modelo se guardan en cada clasificación.
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="py-3">
            <div>
              <CardTitle>Sesiones y acceso</CardTitle>
              <CardDescription>Cookie de sesión y revocación</CardDescription>
            </div>
            <LockKeyhole className="size-4 text-muted-foreground" aria-hidden />
          </CardHeader>
          <CardContent className="pt-0">
            <div className="space-y-2 text-[11px]">
              <div className="flex items-center justify-between gap-2 border-b border-border pb-2">
                <span className="text-muted-foreground">Sesión actual</span>
                <Badge variant="positive">Activa</Badge>
              </div>
              <div className="flex items-center justify-between gap-2 border-b border-border pb-2">
                <span className="text-muted-foreground">Cookie</span>
                <span className="num text-[10px]">HttpOnly · SameSite=Lax</span>
              </div>
              <div className="flex items-center justify-between gap-2 border-b border-border pb-2">
                <span className="text-muted-foreground">Duración</span>
                <span className="num text-[10px]">7 días con rotación</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">CSRF</span>
                <span className="num text-[10px]">X-CSRF-Token en mutaciones</span>
              </div>
            </div>
            <div className="mt-3 border-t border-border pt-3">
              <Link
                href="/settings?section=general"
                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-[12px] font-medium text-foreground transition-colors hover:bg-muted"
              >
                Cerrar sesiones en General
                <ArrowRight className="size-3.5" aria-hidden />
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
