"use client";

import { useEffect } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Keep the digest in the console for correlation with backend logs.
    console.error("Unhandled UI error", error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 text-center">
        <div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-xl bg-negative-soft text-negative">
          <AlertTriangle className="size-4" aria-hidden />
        </div>
        <h1 className="text-base font-semibold">Algo se ha roto</h1>
        <p className="mt-1.5 text-[13px] leading-5 text-muted-foreground">
          La pantalla no pudo renderizarse. Puedes reintentar sin perder la sesión.
        </p>
        {error.digest ? (
          <p className="num mt-3 text-[10px] text-muted-foreground">
            digest: {error.digest}
          </p>
        ) : null}
        <Button className="mt-5" variant="primary" onClick={reset}>
          <RotateCcw className="size-3.5" aria-hidden />
          Reintentar
        </Button>
      </div>
    </div>
  );
}
