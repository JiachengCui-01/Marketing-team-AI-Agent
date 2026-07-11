"use client";

/** Shimmer skeleton placeholder. Compose with width/height/rounded via className. */
export function Skeleton({
  className = "",
  variant = "default",
}: {
  className?: string;
  variant?: "default" | "news" | "image" | "preview";
}) {
  return <div className={`skeleton skeleton-${variant} rounded-lg ${className}`} />;
}
