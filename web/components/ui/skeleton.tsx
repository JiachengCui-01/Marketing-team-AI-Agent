"use client";

/** Shimmer skeleton placeholder. Compose with width/height/rounded via className. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton rounded-lg ${className}`} />;
}
