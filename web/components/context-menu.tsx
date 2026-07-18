"use client";

import { useEffect, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { ChevronDown } from "lucide-react";

export type MenuItem =
  | {
      type?: "item";
      label: string;
      icon?: LucideIcon;
      onClick: () => void;
      danger?: boolean;
      disabled?: boolean;
    }
  | { type: "separator" }
  | {
      type: "submenu";
      label: string;
      icon?: LucideIcon;
      items: MenuItem[];
    };

export function ContextMenu({
  x,
  y,
  items,
  onClose,
}: {
  x: number;
  y: number;
  items: MenuItem[];
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    function onEsc(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onEsc);
    };
  }, [onClose]);

  const left = Math.min(x, typeof window !== "undefined" ? window.innerWidth - 220 : x);
  const top = Math.min(y, typeof window !== "undefined" ? window.innerHeight - 240 : y);

  return (
    <div
      ref={ref}
      style={{ left, top }}
      className="fixed z-50 min-w-[200px] rounded-lg border border-border bg-bg-elevated shadow-xl py-1 text-sm animate-fade-in"
    >
      {items.map((item, i) => {
        if ("type" in item && item.type === "separator") {
          return <div key={i} className="my-1 border-t border-border" />;
        }
        if ("type" in item && item.type === "submenu") {
          return (
            <SubmenuItem
              key={i}
              label={item.label}
              icon={item.icon}
              items={item.items}
              onCloseRoot={onClose}
            />
          );
        }
        const I = item as Extract<MenuItem, { onClick: () => void }>;
        const Icon = I.icon;
        return (
          <button
            key={i}
            disabled={I.disabled}
            onClick={() => {
              I.onClick();
              onClose();
            }}
            className={`w-full text-left px-3 py-1.5 flex items-center gap-2 hover:bg-bg-subtle disabled:opacity-50 disabled:cursor-not-allowed ${
              I.danger ? "text-danger" : "text-fg"
            }`}
          >
            {Icon ? <Icon size={14} /> : <span className="w-3.5" />}
            <span>{I.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function SubmenuItem({
  label,
  icon: Icon,
  items,
  onCloseRoot,
}: {
  label: string;
  icon?: LucideIcon;
  items: MenuItem[];
  onCloseRoot: () => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="w-full text-left px-3 py-1.5 flex items-center gap-2 hover:bg-bg-subtle text-fg"
      >
        {Icon ? <Icon size={14} /> : <span className="w-3.5" />}
        <span className="flex-1">{label}</span>
        <ChevronDown size={12} className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <div className="mx-1 mb-1 mt-0.5 rounded-md border border-border/70 bg-bg-subtle/70 py-1 shadow-inner animate-fade-in">
          <div className="mb-1 ml-4 h-2 border-l border-border" aria-hidden />
        {items.map((item, i) => {
          if ("type" in item && item.type === "separator") {
            return <div key={i} className="my-1 border-t border-border" />;
          }
          const I = item as Extract<MenuItem, { onClick: () => void }>;
          const II = I.icon;
          return (
            <button
              key={i}
              onClick={() => {
                I.onClick();
                onCloseRoot();
              }}
              className="w-full text-left px-3 py-1.5 flex items-center gap-2 hover:bg-bg-elevated text-fg"
            >
              {II ? <II size={14} /> : <span className="w-3.5" />}
              <span>{I.label}</span>
            </button>
          );
        })}
      </div>
      ) : null}
    </div>
  );
}
