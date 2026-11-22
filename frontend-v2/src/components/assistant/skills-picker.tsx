"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { Check, Sparkles } from "lucide-react";
import type { Skill } from "@/lib/agent-types";
import { cn } from "@/lib/utils";
import { Popover } from "@/components/ui/popover";

/** Desplegable del composer para forzar skills en el siguiente mensaje (como Nexus). */
export function SkillsPicker({
  skills,
  selected,
  onChange,
  disabled,
  includeDisabled,
  label = "Skills",
}: {
  skills: Skill[];
  selected: string[];
  onChange: (names: string[]) => void;
  disabled?: boolean;
  /** Automatizaciones: también las skills que no están activas en el chat. */
  includeDisabled?: boolean;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  const available = skills.filter(
    (skill) => (includeDisabled || skill.enabled_in_chat) && skill.version !== null,
  );

  function toggle(name: string) {
    onChange(selected.includes(name) ? selected.filter((item) => item !== name) : [...selected, name]);
  }

  return (
    <>
      <button
        ref={anchor}
        type="button"
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label="Skills"
        title="Skills"
        className={cn(
          "inline-flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[13px] text-muted-foreground transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-50",
          selected.length && "text-accent",
        )}
      >
        <Sparkles className="size-4" aria-hidden />
        <span className="hidden sm:inline">{label}</span>
        {selected.length ? <span className="tabular text-[12px]">{selected.length}</span> : null}
      </button>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchorRef={anchor}
        ariaLabel="Elegir skills"
        className="w-72 rounded-xl border border-border bg-popover p-1.5 shadow-2"
      >
        {available.length ? (
          <ul className="max-h-72 overflow-y-auto">
            {available.map((skill) => {
              const active = selected.includes(skill.name);
              return (
                <li key={skill.id}>
                  <button
                    type="button"
                    onClick={() => toggle(skill.name)}
                    className="flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left hover:bg-surface-2"
                  >
                    <span
                      className={cn(
                        "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded border",
                        active ? "border-accent bg-accent text-accent-foreground" : "border-border-strong",
                      )}
                    >
                      {active ? <Check className="size-3" aria-hidden /> : null}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate font-mono text-[12px]">/{skill.name}</span>
                      <span className="line-clamp-2 text-[12px] text-muted-foreground">{skill.description}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="px-2.5 py-2 text-[12px] text-muted-foreground">
            {includeDisabled ? "Aún no tienes skills publicadas." : "Aún no tienes skills activas en el chat."}
          </p>
        )}
        <div className="mt-1 border-t border-border px-2.5 pb-1 pt-2 text-[12px]">
          <Link href="/ai/skills" className="text-accent hover:underline">
            Gestionar skills
          </Link>
          {includeDisabled ? null : (
            <span className="text-muted-foreground"> · también puedes escribir /nombre</span>
          )}
        </div>
      </Popover>
    </>
  );
}
