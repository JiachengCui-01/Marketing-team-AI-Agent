"use client";

import { createPortal } from "react-dom";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";

const EXIT_MS = 220;

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  );
}

export function Modal({
  title,
  children,
  onClose,
  wide,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const { t } = useI18n();
  const panelRef = useRef<HTMLElement | null>(null);
  // The element that had focus when the modal opened == the button that triggered it.
  const triggerRef = useRef<Element | null>(
    typeof document !== "undefined" ? document.activeElement : null,
  );
  const [shown, setShown] = useState(false);
  const [origin, setOrigin] = useState<string>("center center");
  const closingRef = useRef(false);

  // Measure the trigger button and set transform-origin so the panel appears to
  // grow out of (and later collapse back into) that button.
  useLayoutEffect(() => {
    const panel = panelRef.current;
    const trigger = triggerRef.current as HTMLElement | null;
    if (panel && trigger && trigger.getBoundingClientRect) {
      const pr = panel.getBoundingClientRect();
      const tr = trigger.getBoundingClientRect();
      if (tr.width && tr.height) {
        const ox = Math.max(0, Math.min(pr.width, tr.left + tr.width / 2 - pr.left));
        const oy = Math.max(0, Math.min(pr.height, tr.top + tr.height / 2 - pr.top));
        setOrigin(`${ox}px ${oy}px`);
      }
    }
    // setTimeout (not rAF) so the enter transition still fires when the tab is
    // backgrounded (rAF is throttled/paused for hidden tabs).
    const id = window.setTimeout(() => setShown(true), 20);
    return () => window.clearTimeout(id);
  }, []);

  const close = useCallback(() => {
    if (closingRef.current) return;
    closingRef.current = true;
    if (prefersReducedMotion()) {
      onClose();
      return;
    }
    setShown(false); // play the reverse (collapse-to-button) transition
    window.setTimeout(onClose, EXIT_MS);
  }, [onClose]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  if (typeof document === "undefined") return null;

  const reduce = prefersReducedMotion();

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
      style={{
        backgroundColor: "rgb(0 0 0 / 0.4)",
        backdropFilter: "blur(2px)",
        opacity: reduce ? 1 : shown ? 1 : 0,
        transition: reduce ? undefined : "opacity 200ms ease-out",
      }}
    >
      <section
        ref={panelRef}
        className={`w-full ${wide ? "max-w-3xl" : "max-w-2xl"} max-h-[calc(100vh-2rem)] overflow-y-auto rounded-2xl border border-border bg-bg-elevated p-5 shadow-xl`}
        style={{
          transformOrigin: origin,
          transform: reduce ? undefined : shown ? "scale(1)" : "scale(0.72)",
          opacity: reduce ? 1 : shown ? 1 : 0,
          transition: reduce
            ? undefined
            : `transform ${EXIT_MS}ms cubic-bezier(0.32, 0.72, 0, 1), opacity ${EXIT_MS}ms ease-out`,
          willChange: "transform, opacity",
        }}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">{title}</h2>
          <button type="button" onClick={close} className="btn-ghost px-2 py-1 text-sm text-fg-subtle">
            {t.close}
          </button>
        </div>
        {children}
      </section>
    </div>,
    document.body,
  );
}
