"use client";

import Link from "next/link";
import { useState } from "react";
import { ChevronDown, LogOut, Settings, ShieldCheck } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { DEMO_MODE } from "@/lib/demo";
import { cn, initials } from "@/lib/utils";

export function UserMenu() {
  const [open, setOpen] = useState(false);
  const { user, isLoading, logout } = useAuth();

  if (isLoading || !user) {
    return <div className="size-8 rounded-full bg-muted" aria-hidden />;
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex h-8 items-center gap-1.5 rounded-lg pl-0.5 pr-1.5 text-left transition-colors hover:bg-muted"
      >
        <span className="flex size-7 items-center justify-center rounded-full bg-accent-soft text-[10px] font-semibold text-accent-soft-foreground">
          {initials(user.name ?? user.email)}
        </span>
        <ChevronDown className="hidden size-3 text-muted-foreground sm:block" aria-hidden />
        <span className="sr-only">Abrir menú de usuario</span>
      </button>

      {open ? (
        <>
          <button
            type="button"
            className="fixed inset-0 z-40 cursor-default"
            aria-label="Cerrar menú"
            onClick={() => setOpen(false)}
          />
          <div
            role="menu"
            className="animate-fade-in absolute right-0 top-full z-50 mt-1.5 w-60 rounded-xl border border-border bg-popover p-1 shadow-lg"
          >
            <div className="border-b border-border px-2.5 py-2">
              <p className="truncate text-[13px] font-medium">{user.name ?? user.email}</p>
              <p className="truncate text-[11px] text-muted-foreground">{user.email}</p>
              <p className="mt-1.5 inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                <ShieldCheck className="size-3 text-positive" aria-hidden />
                {DEMO_MODE ? "Sesión demo local" : "Sesión verificada por API"}
              </p>
            </div>
            <div className="py-1">
              <Link
                href="/settings"
                role="menuitem"
                onClick={() => setOpen(false)}
                className="flex h-8 items-center gap-2 rounded-md px-2.5 text-[13px] text-foreground transition-colors hover:bg-muted"
              >
                <Settings className="size-3.5 text-muted-foreground" aria-hidden />
                Ajustes
              </Link>
              <Link
                href="/settings?section=privacidad"
                role="menuitem"
                onClick={() => setOpen(false)}
                className="flex h-8 items-center gap-2 rounded-md px-2.5 text-[13px] text-foreground transition-colors hover:bg-muted"
              >
                <ShieldCheck className="size-3.5 text-muted-foreground" aria-hidden />
                Privacidad y sesiones
              </Link>
            </div>
            <div className="border-t border-border pt-1">
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  void logout();
                }}
                className={cn(
                  "flex h-8 w-full items-center gap-2 rounded-md px-2.5 text-[13px] text-negative transition-colors hover:bg-negative-soft",
                )}
              >
                <LogOut className="size-3.5" aria-hidden />
                Cerrar sesión
              </button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
