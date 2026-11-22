"use client";

import { marked } from "marked";
import { memo, useId, useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { CodeBlock } from "@/components/ui/code-block";

const REMARK_PLUGINS = [remarkGfm, remarkBreaks];

function languageOf(className?: string): string {
  return className?.match(/language-([\w+-]+)/)?.[1] ?? "plaintext";
}

const COMPONENTS: Partial<Components> = {
  code({ className, children, node, ...props }) {
    const start = node?.position?.start.line;
    const inline = !start || start === node?.position?.end.line;
    if (inline && !className) {
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    }
    return <CodeBlock code={String(children).replace(/\n$/, "")} language={languageOf(className)} />;
  },
  pre({ children }) {
    return <>{children}</>;
  },
  a({ children, href, ...props }) {
    const external = href ? /^https?:/i.test(href) : false;
    return (
      <a href={href} {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})} {...props}>
        {children}
      </a>
    );
  },
};

/** Cada bloque se memoiza: durante el streaming solo se re-renderiza el último. */
const Block = memo(
  function Block({ content }: { content: string }) {
    return (
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={COMPONENTS}>
        {content}
      </ReactMarkdown>
    );
  },
  (prev, next) => prev.content === next.content,
);

function MarkdownComponent({
  children,
  className,
  compact,
}: {
  children: string;
  className?: string;
  /** Sans-serif y 14px: para paneles secundarios (creador de skills, previsualizaciones). */
  compact?: boolean;
}) {
  const id = useId();
  const blocks = useMemo(() => marked.lexer(children).map((token) => token.raw), [children]);
  return (
    <div className={cn("aui-md", compact && "aui-md-compact", className)}>
      {blocks.map((block, index) => (
        <Block key={`${id}-${index}`} content={block} />
      ))}
    </div>
  );
}

export const Markdown = memo(MarkdownComponent);
