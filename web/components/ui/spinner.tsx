"use client";

// Duotone identity icons — the filled underlayer gives the loading marks weight
// at small sizes, where a bare stroke reads as a scratch.
import {
  ChartBar,
  ChartLineUp,
  FileArrowUp,
  ImageSquare,
  CircleNotch,
  Newspaper,
  Sparkle,
  type Icon,
} from "@phosphor-icons/react";

type LoadingVariant =
  | "default"
  | "account"
  | "chat"
  | "upload"
  | "news"
  | "selection"
  | "image"
  | "preview";

const variantMeta: Record<LoadingVariant, { accent: string; icon: Icon }> = {
  default: { accent: "text-accent", icon: CircleNotch },
  account: { accent: "text-feature-content", icon: Sparkle },
  chat: { accent: "text-feature-content", icon: Sparkle },
  upload: { accent: "text-feature-analytics", icon: FileArrowUp },
  news: { accent: "text-feature-news", icon: Newspaper },
  selection: { accent: "text-feature-selection", icon: ChartLineUp },
  image: { accent: "text-feature-image", icon: ImageSquare },
  preview: { accent: "text-feature-research", icon: ChartBar },
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
      <span className={`loading-orb loading-orb-${variant} animate-pulse-ring`} aria-hidden>
        <Icon
          size={size}
          weight={variant === "default" ? "bold" : "duotone"}
          className={`${accent} ${variant === "default" ? "animate-spin" : "animate-float-soft"} transition-all duration-300`}
        />
      </span>
      {label ? <span className="text-sm font-medium">{label}</span> : null}
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
    <div className={`loading-card loading-card-${variant} animate-bounce-in ${className}`}>
      <Spinner size={24} label={label} variant={variant} />
      <span className="loading-rail" aria-hidden />
    </div>
  );
}
