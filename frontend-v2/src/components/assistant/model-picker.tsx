"use client";

import { useSyncExternalStore } from "react";
import { Cpu } from "lucide-react";
import type { AiCatalogProvider, AiProviderConfig } from "@/lib/agent-types";
import { SelectMenu, type SelectOption } from "@/components/ui/select-menu";

export interface ModelChoice {
  provider: string;
  model: string;
}

const STORAGE_KEY = "ft.assistant.model";
const CHANGE_EVENT = "ft:model-choice";

function readChoice(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null; // almacenamiento no disponible: se usa el proveedor por defecto
  }
}

function subscribe(callback: () => void): () => void {
  window.addEventListener("storage", callback);
  window.addEventListener(CHANGE_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(CHANGE_EVENT, callback);
  };
}

/** Elección de modelo recordada en este navegador (no es un dato sensible). */
export function useModelChoice(): [ModelChoice | null, (choice: ModelChoice | null) => void] {
  const raw = useSyncExternalStore(subscribe, readChoice, () => null);
  let choice: ModelChoice | null = null;
  if (raw) {
    try {
      choice = JSON.parse(raw) as ModelChoice;
    } catch {
      choice = null;
    }
  }
  function update(next: ModelChoice | null) {
    try {
      if (next) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignorado
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }
  return [choice, update];
}

export function ModelPicker({
  providers,
  catalog,
  value,
  onChange,
}: {
  providers: AiProviderConfig[];
  catalog: AiCatalogProvider[];
  value: ModelChoice | null;
  onChange: (choice: ModelChoice | null) => void;
}) {
  const options: SelectOption[] = [{ value: "", label: "Modelo por defecto" }];
  for (const provider of providers.filter((item) => item.enabled)) {
    const models = new Set<string>(catalog.find((item) => item.id === provider.provider)?.models ?? []);
    if (provider.model) models.add(provider.model);
    for (const model of models) {
      options.push({
        value: `${provider.provider}::${model}`,
        label: model,
        group: provider.label,
        hint: provider.is_default && model === provider.model ? "por defecto" : undefined,
      });
    }
  }
  const current = value ? `${value.provider}::${value.model}` : "";
  const known = options.some((option) => option.value === current);

  return (
    <SelectMenu
      aria-label="Modelo del asistente"
      variant="pill"
      icon={<Cpu className="size-3.5" aria-hidden />}
      value={known ? current : ""}
      options={options}
      onValueChange={(next) => {
        if (!next) return onChange(null);
        const [provider, ...rest] = next.split("::");
        onChange({ provider, model: rest.join("::") });
      }}
      align="start"
    />
  );
}
