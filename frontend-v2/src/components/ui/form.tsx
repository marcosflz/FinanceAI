import {
  Children,
  Fragment,
  forwardRef,
  isValidElement,
  useId,
  type ChangeEvent,
  type InputHTMLAttributes,
  type LabelHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { SelectMenu, type SelectOption } from "@/components/ui/select-menu";
import { cn } from "@/lib/utils";

const controlClasses =
  "h-9 w-full rounded-lg border border-input bg-card px-3 text-sm text-foreground placeholder:text-muted-foreground/80 transition-colors hover:border-muted-foreground/40 focus-visible:border-accent disabled:cursor-not-allowed disabled:opacity-50";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(controlClasses, className)} {...props} />
  ),
);
Input.displayName = "Input";

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(controlClasses, "h-auto min-h-24 resize-y py-2 leading-5", className)}
    {...props}
  />
));
Textarea.displayName = "Textarea";

interface SelectProps {
  value?: string | number | readonly string[];
  onChange?: (event: ChangeEvent<HTMLSelectElement>) => void;
  disabled?: boolean;
  id?: string;
  name?: string;
  title?: string;
  className?: string;
  children?: ReactNode;
  "aria-label"?: string;
}

function optionText(children: ReactNode): string {
  return Children.toArray(children)
    .map((child) => (typeof child === "string" || typeof child === "number" ? String(child) : ""))
    .join("");
}

/** Lee ``<option>``/``<optgroup>`` para mantener la API de ``<select>``. */
function collectOptions(children: ReactNode, group?: string): SelectOption[] {
  const result: SelectOption[] = [];
  Children.forEach(children, (child) => {
    if (!isValidElement(child)) return;
    const props = child.props as {
      value?: string | number;
      disabled?: boolean;
      label?: string;
      children?: ReactNode;
    };
    if (child.type === Fragment) {
      result.push(...collectOptions(props.children, group));
    } else if (child.type === "optgroup") {
      result.push(...collectOptions(props.children, props.label));
    } else if (child.type === "option") {
      const label = optionText(props.children);
      result.push({
        value: props.value === undefined ? label : String(props.value),
        label,
        disabled: props.disabled,
        group,
      });
    }
  });
  return result;
}

/**
 * Selector con la API de ``<select>`` (``value``, ``onChange``, ``<option>``)
 * pero con menú propio: el desplegable nativo no respeta el tema ni la tipografía.
 */
export const Select = forwardRef<HTMLButtonElement, SelectProps>(
  ({ className, children, onChange, value, ...props }, ref) => {
    const options = collectOptions(children);
    return (
      <SelectMenu
        ref={ref}
        {...props}
        value={value === undefined || value === null ? "" : String(value)}
        options={options}
        placeholder={options.find((option) => option.value === "")?.label}
        className={className}
        onValueChange={(next) =>
          onChange?.({
            target: { value: next },
            currentTarget: { value: next },
          } as unknown as ChangeEvent<HTMLSelectElement>)
        }
      />
    );
  },
);
Select.displayName = "Select";

export function Label({
  className,
  ...props
}: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn("mb-1.5 block text-xs font-medium text-muted-foreground", className)}
      {...props}
    />
  );
}

interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
  htmlFor?: string;
  className?: string;
}

export function Field({ label, hint, error, children, htmlFor, className }: FieldProps) {
  const generatedId = useId();
  const id = htmlFor ?? generatedId;
  return (
    <div className={cn("space-y-1", className)}>
      <Label htmlFor={id}>{label}</Label>
      <div>{children}</div>
      {error ? (
        <p className="text-[11px] text-negative" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-[11px] text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}

export function Checkbox({
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type="checkbox"
      className={cn(
        "size-3.5 cursor-pointer rounded border-input accent-[var(--accent)]",
        className,
      )}
      {...props}
    />
  );
}

export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled,
  hideLabel = false,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
  hideLabel?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-4",
        hideLabel ? "justify-end py-0" : "justify-between py-2.5",
      )}
    >
      {hideLabel ? null : (
        <div className="min-w-0">
          <p className="text-[13px] font-medium text-foreground">{label}</p>
          {description ? (
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          ) : null}
        </div>
      )}
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative h-5 w-9 shrink-0 rounded-full border transition-colors",
          hideLabel ? "" : "mt-0.5",
          checked
            ? "border-accent bg-accent"
            : "border-input bg-muted",
          disabled && "cursor-not-allowed opacity-50",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 size-3.5 rounded-full bg-white shadow-sm transition-transform",
            checked ? "translate-x-[18px]" : "translate-x-0.5",
          )}
        />
      </button>
    </div>
  );
}
