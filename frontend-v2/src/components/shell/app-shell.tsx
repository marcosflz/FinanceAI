"use client";

import type { ReactNode } from "react";
import { AuthGate, AuthProvider } from "@/lib/auth";
import { Sidebar } from "@/components/shell/sidebar";
import { Topbar } from "@/components/shell/topbar";
import { MobileNav } from "@/components/shell/mobile-nav";
import { CommandPalette } from "@/components/shell/command-palette";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <div className="min-h-screen">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-accent focus:px-3 focus:py-2 focus:text-sm focus:text-accent-foreground"
        >
          Saltar al contenido
        </a>
        <Sidebar />
        <div className="lg:pl-[240px]">
          <Topbar />
          <main
            id="main"
            className="mx-auto w-full max-w-[1440px] px-4 pb-24 pt-20 sm:px-6 lg:px-8 lg:pb-10 lg:pt-[76px]"
          >
            <AuthGate>{children}</AuthGate>
          </main>
        </div>
        <MobileNav />
        <CommandPalette />
      </div>
    </AuthProvider>
  );
}
