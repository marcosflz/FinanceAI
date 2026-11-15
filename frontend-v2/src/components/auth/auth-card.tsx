import type { ReactNode } from "react";
import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import { ThemeToggle } from "@/components/shell/theme-toggle";

/** Contenedor de las pantallas públicas de cuenta (recuperar, invitación). */
export function AuthCard({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <div className="flex h-14 items-center justify-between px-4 sm:px-8">
        <Link href="/login" className="flex items-center gap-2">
          <span className="flex size-7 items-center justify-center rounded-lg bg-accent text-[11px] font-semibold text-accent-foreground">
            FT
          </span>
          <span className="text-[13px] font-semibold">Financial Tools</span>
        </Link>
        <ThemeToggle />
      </div>
      <div className="flex flex-1 items-center justify-center px-4 pb-16 pt-6 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-7">
            <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
              {eyebrow}
            </p>
            <h1 className="mt-1.5 text-[26px] font-semibold leading-8 tracking-[-0.03em]">
              {title}
            </h1>
            <p className="mt-2 text-[13px] leading-5 text-muted-foreground">{description}</p>
          </div>
          {children}
          <p className="mt-8 flex items-center justify-center gap-1.5 text-center text-[10px] text-muted-foreground">
            <ShieldCheck className="size-3" aria-hidden />
            Tus datos se cifran con una clave que solo tú puedes desbloquear.
          </p>
        </div>
      </div>
    </div>
  );
}
