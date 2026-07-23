"use client";

/** Shimmer skeleton placeholder. Compose with width/height/rounded via className. */
export function Skeleton({
  className = "",
  variant = "default",
  style,
}: {
  className?: string;
  variant?: "default" | "news" | "image" | "preview";
  style?: React.CSSProperties;
}) {
  return <div className={`skeleton skeleton-${variant} rounded-lg ${className}`} style={style} />;
}
