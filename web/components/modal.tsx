"use client";

import { createPortal } from "react-dom";
import { useI18n } from "@/lib/i18n";

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
  if (typeof document === "undefined") return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <section
        className={`w-full ${wide ? "max-w-3xl" : "max-w-2xl"} max-h-[calc(100vh-2rem)] overflow-y-auto rounded-xl border border-border bg-bg-elevated p-5 shadow-xl`}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">{title}</h2>
          <button type="button" onClick={onClose} className="text-sm text-fg-subtle hover:text-fg">
            {t.close}
          </button>
        </div>
        {children}
      </section>
    </div>,
    document.body,
  );
}
