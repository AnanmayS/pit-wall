"use client";

import { useState, useSyncExternalStore } from "react";
import { controlClass, secondaryButtonClass } from "@/components/Field";

const noop = () => () => {};

export function ShareLink({ id }: { id: string }) {
  const origin = useSyncExternalStore(noop, () => window.location.origin, () => "");
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");
  const url = `${origin}/what-if/${encodeURIComponent(id)}`;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied("copied");
    } catch {
      setCopied("failed");
    }
    window.setTimeout(() => setCopied("idle"), 2000);
  };

  return (
    <div className="flex items-center gap-2">
      <input
        readOnly
        aria-label="Share link"
        value={url}
        onFocus={(e) => e.currentTarget.select()}
        className={`${controlClass} font-mono text-xs`}
      />
      <button type="button" onClick={copy} className={`${secondaryButtonClass} shrink-0`}>
        {copied === "copied" ? "Copied" : copied === "failed" ? "Copy failed" : "Copy link"}
      </button>
    </div>
  );
}
