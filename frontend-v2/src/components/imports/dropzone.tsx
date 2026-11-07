"use client";

import { useRef, useState, type DragEvent } from "react";
import { FileUp, Image as ImageIcon, Paperclip, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const ACCEPTED = ".csv,.pdf,.xlsx,.xls,.ofx,.qif,.png,.jpg,.jpeg,.webp,.heic";
const ACCEPTED_EXTENSIONS = new Set([
  "csv",
  "pdf",
  "xlsx",
  "xls",
  "ofx",
  "qif",
  "png",
  "jpg",
  "jpeg",
  "webp",
  "heic",
]);
const MAX_SIZE = 25 * 1024 * 1024;

export function Dropzone({
  onFiles,
  pending,
}: {
  onFiles: (files: File[]) => void;
  pending: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    const files = Array.from(fileList);
    const tooLarge = files.find((file) => file.size > MAX_SIZE);
    if (tooLarge) {
      setError(`«${tooLarge.name}» supera el límite de 25 MB.`);
      return;
    }
    const unsupported = files.find((file) => {
      const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
      return !ACCEPTED_EXTENSIONS.has(extension) && !file.type.startsWith("image/");
    });
    if (unsupported) {
      setError(`«${unsupported.name}» no es un formato admitido.`);
      return;
    }
    setError(null);
    onFiles(files);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    handleFiles(event.dataTransfer.files);
  }

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node)) return;
        setDragging(false);
      }}
      onDrop={onDrop}
      className={cn(
        "rounded-xl border border-dashed border-input bg-card transition-colors",
        dragging && "border-accent bg-accent-soft/30",
      )}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED}
        className="sr-only"
        onChange={(event) => {
          handleFiles(event.target.files);
          event.target.value = "";
        }}
        aria-label="Seleccionar archivos para importar"
      />
      <div className="flex flex-col items-center justify-center px-5 py-8 text-center">
        <div
          className={cn(
            "mb-3 flex size-10 items-center justify-center rounded-xl border border-border bg-muted text-muted-foreground",
            dragging && "border-accent bg-accent-soft text-accent",
          )}
        >
          <UploadCloud className="size-4" aria-hidden />
        </div>
        <p className="text-[13px] font-medium text-foreground">
          Arrastra extractos, CSV o recibos
        </p>
        <p className="mt-1 max-w-md text-[11px] leading-4 text-muted-foreground">
          Detectamos el banco y el formato automáticamente. También puedes pegar una
          captura o subir una foto del ticket.
        </p>
        <div className="mt-3 flex flex-wrap items-center justify-center gap-1.5 text-[10px] text-muted-foreground">
          <span className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5">
            <Paperclip className="size-2.5" aria-hidden /> CSV
          </span>
          <span className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5">
            <FileUp className="size-2.5" aria-hidden /> PDF
          </span>
          <span className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5">
            <ImageIcon className="size-2.5" aria-hidden /> Imagen
          </span>
          <span className="rounded border border-border px-1.5 py-0.5">XLSX</span>
          <span className="rounded border border-border px-1.5 py-0.5">OFX / QIF</span>
          <span className="rounded border border-border px-1.5 py-0.5">máx. 25 MB</span>
        </div>
        <Button
          className="mt-4"
          size="sm"
          variant="secondary"
          onClick={() => inputRef.current?.click()}
          disabled={pending}
        >
          <UploadCloud className="size-3.5" aria-hidden />
          Seleccionar archivos
        </Button>
        {error ? (
          <p role="alert" className="mt-2 text-[11px] text-negative">
            {error}
          </p>
        ) : null}
      </div>
    </div>
  );
}
