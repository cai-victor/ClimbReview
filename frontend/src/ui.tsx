import { KeyboardEvent, ReactNode, useEffect, useRef, useState } from "react";

/** A small disclosure menu. Escape and choosing an item close it and return focus to the button. */
export function Menu({ label, testid, children }: { label: string; testid?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const close = () => { setOpen(false); button.current?.focus(); };
  return (
    <div className="menu" ref={root} onKeyDown={(e) => { if (e.key === "Escape" && open) { e.stopPropagation(); close(); } }}>
      <button ref={button} className="button" aria-haspopup="true" aria-expanded={open} data-testid={testid} onClick={() => setOpen((v) => !v)}>{label} <span aria-hidden="true">▾</span></button>
      {open && <div className="menu-list" onClick={(e) => { if ((e.target as HTMLElement).closest("a,button")) setOpen(false); }}>{children}</div>}
    </div>
  );
}

export interface TabItem<K extends string> { key: K; label: string; count?: number | null }

/** Tabs with arrow-key movement. Each tab controls the panel with id `panel-<key>`. */
export function Tabs<K extends string>({ items, active, onChange, label }: { items: TabItem<K>[]; active: K; onChange: (key: K) => void; label: string }) {
  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = items[(items.findIndex((i) => i.key === active) + step + items.length) % items.length];
    onChange(next.key);
    (event.currentTarget.querySelector(`[data-tab="${next.key}"]`) as HTMLElement | null)?.focus();
  };
  return (
    <div className="tabs" role="tablist" aria-label={label} onKeyDown={onKey}>
      {items.map((item) => (
        <button key={item.key} role="tab" className="tab" data-tab={item.key} data-testid={`tab-${item.key}`} id={`tab-${item.key}`} aria-selected={item.key === active} aria-controls={`panel-${item.key}`}
          tabIndex={item.key === active ? 0 : -1} onClick={() => onChange(item.key)}>
          {item.label}{item.count != null && <span className="count">{item.count}</span>}
        </button>
      ))}
    </div>
  );
}

export const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
export const scrollTo = (element: Element | null | undefined, block: ScrollLogicalPosition = "nearest") =>
  element?.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block });
