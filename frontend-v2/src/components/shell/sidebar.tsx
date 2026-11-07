"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Command, DatabaseZap } from "lucide-react";
import { cn } from "@/lib/utils";
import { navItems } from "@/components/shell/nav";

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-[240px] flex-col border-r border-border bg-sidebar lg:flex">
      <Link
        href="/"
        className="flex h-14 shrink-0 items-center gap-2.5 border-b border-border px-4"
        aria-label="Financial Tools, inicio"
      >
        <span className="flex size-7 items-center justify-center rounded-lg bg-accent text-[12px] font-semibold tracking-tight text-accent-foreground">
          FT
        </span>
        <span className="min-w-0">
          <span className="block truncate text-[13px] font-semibold leading-4">
            Financial Tools
          </span>
          <span className="block truncate text-[10px] leading-3 text-muted-foreground">
            Panel personal
          </span>
        </span>
      </Link>

      <nav className="flex-1 overflow-y-auto px-2.5 py-3" aria-label="Navegación principal">
        <p className="px-2 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/70">
          Espacio
        </p>
        <ul className="space-y-0.5">
          {navItems.map((item) => {
            const active =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "group flex h-8 items-center gap-2.5 rounded-lg px-2 text-[13px] font-medium transition-colors",
                    active
                      ? "bg-accent-soft text-accent-soft-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  <Icon
                    className={cn(
                      "size-4 shrink-0",
                      active ? "text-accent" : "text-muted-foreground group-hover:text-foreground",
                    )}
                    strokeWidth={1.8}
                    aria-hidden
                  />
                  <span className="truncate">{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>

        <div className="mt-6 rounded-lg border border-border bg-card p-3">
          <div className="flex items-center gap-2 text-[11px] font-medium text-foreground">
            <DatabaseZap className="size-3.5 text-accent" aria-hidden />
            Datos v3
          </div>
          <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">
            Scaffold F5 conectado a contratos <span className="num">/api/v3</span>.
            Los mocks se activan si la API no responde.
          </p>
        </div>
      </nav>

      <div className="border-t border-border px-3 py-3">
        <p className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
          <Command className="size-3" aria-hidden />
          <span className="num">⌘K</span> para navegar
        </p>
        <p className="mt-1 text-[10px] text-muted-foreground/70">
          Fiscalidad personal · EUR
        </p>
      </div>
    </aside>
  );
}
