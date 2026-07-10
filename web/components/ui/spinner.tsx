"use client";

import { Loader2 } from "lucide-react";

/** Consistent spinner used across loading states. */
export function Spinner({
  size = 16,
  label,
  className = "",
}: {
  size?: number;
  label?: string;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2 text-fg-subtle ${className}`}>
      <Loader2 size={size} className="animate-spin text-accent" />
      {label ? <span className="text-sm">{label}</span> : null}
    </span>
  );
}

/** Centered spinner for filling an empty area while loading. */
export function SpinnerBlock({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center py-10">
      <Spinner size={20} label={label} />
    </div>
  );
}
