"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Search, UploadCloud } from "lucide-react";
import { sectionLabel } from "@/components/shell/nav";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import { UserMenu } from "@/components/shell/user-menu";

function openCommandPalette() {
  window.dispatchEvent(new Event("ft:command"));
}

export function Topbar() {
  const pathname = usePathname();
  const section = sectionLabel(pathname);

  return (
    <header className="fixed inset-x-0 top-0 z-30 h-14 border-b border-border bg-background/95 backdrop-blur lg:left-[240px]">
      <div className="flex h-full items-center justify-between gap-3 px-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2.5">
          <Link
            href="/"
            className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-accent text-[11px] font-semibold text-accent-foreground lg:hidden"
            aria-label="Financial Tools, inicio"
          >
            FT
          </Link>
          <div className="min-w-0">
            <p className="truncate text-[12px] font-medium leading-4 text-foreground">
              {section}
            </p>
            <p className="hidden truncate text-[10px] leading-3 text-muted-foreground sm:block">
              Datos personales · EUR
            </p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1 sm:gap-1.5">
          <button
            type="button"
            onClick={openCommandPalette}
            className="inline-flex h-8 items-center gap-2 rounded-lg border border-border bg-card px-2.5 text-[12px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="Abrir búsqueda y comandos"
          >
            <Search className="size-3.5" aria-hidden />
            <span className="hidden md:inline">Buscar</span>
            <kbd className="num hidden rounded border border-border bg-muted px-1 py-0.5 text-[9px] leading-none text-muted-foreground md:inline">
              ⌘K
            </kbd>
          </button>

          <Link
            href="/imports"
            className="hidden h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-[12px] font-medium text-accent-foreground transition-colors hover:bg-accent/90 sm:inline-flex"
          >
            <UploadCloud className="size-3.5" aria-hidden />
            Importar
          </Link>
          <Link
            href="/imports"
            className="inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground sm:hidden"
            aria-label="Importar"
          >
            <UploadCloud className="size-4" aria-hidden />
          </Link>

          <ThemeToggle />
          <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
          <UserMenu />
        </div>
      </div>
    </header>
  );
}
