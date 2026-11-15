"use client";

import { useState } from "react";
import { ArrowRight, Check, Copy, Download, KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox, Label } from "@/components/ui/form";

/**
 * Muestra la clave de recuperación una única vez. El servidor no la guarda en
 * claro: si se pierde junto con la contraseña, los datos no se pueden
 * recuperar.
 */
export function RecoveryKeyNotice({
  recoveryKey,
  onContinue,
  continueLabel = "Continuar",
}: {
  recoveryKey: string;
  onContinue: () => void;
  continueLabel?: string;
}) {
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(recoveryKey);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  function download() {
    const text = [
      "Financial Tools — clave de recuperación",
      "",
      recoveryKey,
      "",
      "Permite restablecer la contraseña sin perder tus datos.",
      "Guárdala fuera de este ordenador (gestor de contraseñas o papel).",
    ].join("\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "financial-tools-clave-recuperacion.txt";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 rounded-xl border border-warning/30 bg-warning-soft p-3.5">
        <KeyRound className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
        <div className="space-y-1 text-[12px] leading-5">
          <p className="font-medium text-foreground">Guarda tu clave de recuperación</p>
          <p className="text-muted-foreground">
            Tus datos se cifran con tu contraseña y nadie más, ni el administrador,
            puede leerlos. Si olvidas la contraseña, esta clave es la única forma de
            recuperarlos. Solo se muestra ahora.
          </p>
        </div>
      </div>

      <p
        className="num select-all break-all rounded-lg border border-border bg-subtle px-3 py-3 text-center text-[15px] font-semibold tracking-[0.08em]"
        aria-label="Clave de recuperación"
      >
        {recoveryKey}
      </p>

      <div className="flex gap-2">
        <Button type="button" size="sm" className="flex-1" onClick={copy}>
          {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
          {copied ? "Copiada" : "Copiar"}
        </Button>
        <Button type="button" size="sm" className="flex-1" onClick={download}>
          <Download className="size-3.5" aria-hidden />
          Descargar .txt
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <Checkbox
          id="recovery-saved"
          checked={saved}
          onChange={(event) => setSaved(event.target.checked)}
        />
        <Label htmlFor="recovery-saved" className="mb-0 cursor-pointer text-[12px] text-foreground">
          La he guardado en un lugar seguro
        </Label>
      </div>

      <Button
        type="button"
        variant="primary"
        className="h-10 w-full"
        disabled={!saved}
        onClick={onContinue}
      >
        {continueLabel}
        <ArrowRight className="size-3.5" aria-hidden />
      </Button>
    </div>
  );
}
