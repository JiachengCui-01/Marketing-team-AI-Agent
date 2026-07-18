"use client";

import { User, Sparkles, FileText, Download } from "lucide-react";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";
import { StatusChip, type StatusInfo } from "./status-chip";
import { artifactDownloadUrl } from "@/lib/api";
import { AvatarImage } from "./auth-ui";
import { CitationMarkdown } from "./citation-markdown";

export type MessageArtifact = {
  artifact_id: string;
  filename: string;
  mime: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
  status?: StatusInfo;
  artifacts?: MessageArtifact[];
};

export function MessageBubble({
  message,
  onPreviewArtifact,
  userAvatar,
}: {
  message: ChatMessage;
  onPreviewArtifact?: (a: MessageArtifact) => void;
  userAvatar?: string | null;
}) {
  const { t } = useI18n();
  const isUser = message.role === "user";
  const showStatus =
    message.pending && !!message.status && message.content.length === 0;
  const showTypingDots =
    message.pending && !message.status && message.content.length === 0;

  return (
    <div
      className={cn(
        "flex gap-3 animate-fade-in transition-all duration-300",
        isUser ? "flex-row-reverse" : "flex-row",
      )}
    >
      <div
        className={cn(
          "shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition-all duration-200",
          isUser ? "bg-accent text-accent-fg shadow-md shadow-accent/30" : "bg-bg-subtle text-fg-muted",
        )}
        aria-hidden
      >
        {isUser ? (
          userAvatar ? (
            <AvatarImage avatar={userAvatar} className="h-8 w-8" />
          ) : (
            <User size={16} />
          )
        ) : (
          <Sparkles size={16} className="animate-float-soft" />
        )}
      </div>

      <div
        className={cn(
          "max-w-[78%] rounded-2xl px-4 py-3 text-sm leading-relaxed transition-all duration-300",
          isUser
            ? "bg-accent text-accent-fg rounded-tr-sm shadow-lg shadow-accent/25 hover:shadow-xl hover:shadow-accent/35"
            : "bg-bg-elevated text-fg border border-border rounded-tl-sm shadow-sm hover:shadow-md hover:border-accent/30",
        )}
      >
        {showStatus ? (
          <StatusChip status={message.status!} />
        ) : showTypingDots ? (
          <TypingDots />
        ) : isUser ? (
          <span className="whitespace-pre-wrap">{message.content}</span>
        ) : (
          <>
            <CitationMarkdown content={message.content + (message.pending ? "▍" : "")} />
            {message.artifacts && message.artifacts.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {message.artifacts.map((a) => (
                  <ArtifactChip
                    key={a.artifact_id}
                    artifact={a}
                    onPreview={onPreviewArtifact}
                    downloadLabel={t.download}
                  />
                ))}
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function ArtifactChip({
  artifact,
  onPreview,
  downloadLabel,
}: {
  artifact: MessageArtifact;
  onPreview?: (a: MessageArtifact) => void;
  downloadLabel: string;
}) {
  return (
    <div className="inline-flex items-center gap-2 rounded-lg border border-border bg-bg-subtle/60 px-2.5 py-1.5 text-xs">
      <FileText size={13} className="text-accent shrink-0" />
      <button
        onClick={() => onPreview?.(artifact)}
        className="font-medium hover:underline truncate max-w-[16ch]"
        title={artifact.filename}
      >
        {artifact.filename}
      </button>
      <a
        href={artifactDownloadUrl(artifact.artifact_id)}
        download={artifact.filename}
        className="inline-flex items-center gap-1 text-fg-muted hover:text-accent transition"
        title={downloadLabel}
      >
        <Download size={12} />
      </a>
    </div>
  );
}

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1.5 py-1" aria-label="thinking">
      <span
        className="w-2 h-2 rounded-full bg-feature-content animate-dot-drift shadow-sm"
        style={{ animationDelay: "-0.36s" }}
      />
      <span
        className="w-2 h-2 rounded-full bg-feature-content animate-dot-drift shadow-sm"
        style={{ animationDelay: "-0.18s" }}
      />
      <span className="w-2 h-2 rounded-full bg-feature-content animate-dot-drift shadow-sm" />
    </span>
  );
}
