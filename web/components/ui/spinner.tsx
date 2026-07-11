"use client";

import { BarChart3, FileUp, ImageIcon, Loader2, Newspaper, Sparkles } from "lucide-react";

type LoadingVariant = "default" | "account" | "chat" | "upload" | "news" | "image" | "preview";

const variantMeta: Record<LoadingVariant, { accent: string; icon: typeof Loader2 }> = {
  default: { accent: "text-accent", icon: Loader2 },
  account: { accent: "text-feature-content", icon: Sparkles },
  chat: { accent: "text-feature-content", icon: Sparkles },
  upload: { accent: "text-feature-analytics", icon: FileUp },
  news: { accent: "text-feature-news", icon: Newspaper },
  image: { accent: "text-feature-image", icon: ImageIcon },
  preview: { accent: "text-feature-research", icon: BarChart3 },
};

/** Consistent spinner used across loading states. */
export function Spinner({
  size = 16,
  label,
  className = "",
  variant = "default",
}: {
  size?: number;
  label?: string;
  className?: string;
  variant?: LoadingVariant;
}) {
  const Icon = variantMeta[variant].icon;
  const accent = variantMeta[variant].accent;
  return (
    <span className={`inline-flex items-center gap-2 text-fg-subtle ${className}`}>
      <span className={`loading-orb loading-orb-${variant}`} aria-hidden>
        <Icon size={size} className={`${accent} ${variant === "default" ? "animate-spin" : "animate-float-soft"}`} />
      </span>
      {label ? <span className="text-sm">{label}</span> : null}
    </span>
  );
}

/** Centered spinner for filling an empty area while loading. */
export function SpinnerBlock({
  label,
  variant = "default",
}: {
  label?: string;
  variant?: LoadingVariant;
}) {
  return (
    <div className="flex items-center justify-center py-10">
      <Spinner size={20} label={label} variant={variant} />
    </div>
  );
}

export function LoadingCard({
  label,
  variant = "default",
  className = "",
}: {
  label: string;
  variant?: LoadingVariant;
  className?: string;
}) {
  return (
    <div className={`loading-card loading-card-${variant} ${className}`}>
      <Spinner size={22} label={label} variant={variant} />
      <span className="loading-rail" aria-hidden />
    </div>
  );
}
