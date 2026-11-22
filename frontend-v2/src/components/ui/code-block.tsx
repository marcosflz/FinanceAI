"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

/** Bloque de código resaltado con shiki (tema claro/oscuro con variables CSS). */
export function CodeBlock({ code, language = "plaintext" }: { code: string; language?: string }) {
  const [html, setHtml] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void import("shiki")
      .then(({ codeToHtml }) =>
        codeToHtml(code, {
          lang: language,
          themes: { light: "github-light", dark: "github-dark" },
          defaultColor: "light",
        }),
      )
      .then((result) => {
        if (!cancelled) setHtml(result);
      })
      .catch(() => {
        if (!cancelled) setHtml(null); // lenguaje desconocido: texto plano
      });
    return () => {
      cancelled = true;
    };
  }, [code, language]);

  const classes = cn(
    "code-block w-full overflow-x-auto text-[13px] leading-5 [&>pre]:px-4 [&>pre]:py-3.5",
  );
  return (
    <div className="not-prose my-1 flex w-full flex-col overflow-clip rounded-xl border border-border bg-card">
      {language !== "plaintext" ? (
        <div className="border-b border-border px-4 py-1.5 font-mono text-[11px] text-muted-foreground">
          {language}
        </div>
      ) : null}
      {html ? (
        <div className={classes} dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <div className={classes}>
          <pre>
            <code>{code}</code>
          </pre>
        </div>
      )}
    </div>
  );
}
