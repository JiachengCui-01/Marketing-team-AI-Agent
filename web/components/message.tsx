"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { User, Sparkles, FileText, Download } from "lucide-react";
import { cn } from "@/lib/cn";
import { StatusChip, type StatusInfo } from "./status-chip";
import { artifactDownloadUrl } from "@/lib/api";

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
}: {
  message: ChatMessage;
  onPreviewArtifact?: (a: MessageArtifact) => void;
}) {
  const isUser = message.role === "user";
  const showStatus =
    message.pending && !!message.status && message.content.length === 0;
  const showTypingDots =
    message.pending && !message.status && message.content.length === 0;

  return (
    <div
      className={cn(
        "flex gap-3 animate-fade-in",
        isUser ? "flex-row-reverse" : "flex-row",
      )}
    >
      <div
        className={cn(
          "shrink-0 w-8 h-8 rounded-full flex items-center justify-center",
          isUser ? "bg-accent text-accent-fg" : "bg-bg-subtle text-fg-muted",
        )}
        aria-hidden
      >
        {isUser ? <User size={16} /> : <Sparkles size={16} />}
      </div>

      <div
        className={cn(
          "max-w-[78%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm",
          isUser
            ? "bg-accent text-accent-fg rounded-tr-sm"
            : "bg-bg-elevated text-fg border border-border rounded-tl-sm",
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
            <div className="prose-chat">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content + (message.pending ? "▍" : "")}
              </ReactMarkdown>
            </div>
            {message.artifacts && message.artifacts.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {message.artifacts.map((a) => (
                  <ArtifactChip
                    key={a.artifact_id}
                    artifact={a}
                    onPreview={onPreviewArtifact}
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
}: {
  artifact: MessageArtifact;
  onPreview?: (a: MessageArtifact) => void;
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
        title="Download"
      >
        <Download size={12} />
      </a>
    </div>
  );
}

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1 py-1">
      <span
        className="w-1.5 h-1.5 rounded-full bg-fg-muted animate-dot-pulse"
        style={{ animationDelay: "-0.32s" }}
      />
      <span
        className="w-1.5 h-1.5 rounded-full bg-fg-muted animate-dot-pulse"
        style={{ animationDelay: "-0.16s" }}
      />
      <span className="w-1.5 h-1.5 rounded-full bg-fg-muted animate-dot-pulse" />
    </span>
  );
}
