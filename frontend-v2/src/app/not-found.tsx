import Link from "next/link";
import { FileQuestion } from "lucide-react";

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-6 text-foreground">
      <div className="w-full max-w-sm text-center">
        <div className="mx-auto mb-4 flex size-11 items-center justify-center rounded-xl border border-border bg-card text-muted-foreground">
          <FileQuestion className="size-5" aria-hidden />
        </div>
        <p className="num text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
          404
        </p>
        <h1 className="mt-1 text-xl font-semibold">Página no encontrada</h1>
        <p className="mt-2 text-[13px] leading-5 text-muted-foreground">
          La ruta que buscas no existe o ha cambiado de sitio.
        </p>
        <Link
          href="/"
          className="mt-5 inline-flex h-9 items-center justify-center rounded-lg bg-accent px-3.5 text-sm font-medium text-accent-foreground transition-colors hover:bg-accent/90"
        >
          Volver al dashboard
        </Link>
      </div>
    </div>
  );
}
