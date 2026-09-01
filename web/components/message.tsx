"use client";

import { useState } from "react";
import { User, Sparkles, FileText, FileImage, Download, BookOpen, Pencil } from "lucide-react";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";
import { StatusChip, type StatusInfo } from "./status-chip";
import { artifactDownloadUrl, uploadPreviewUrl, type OaDraft, type UploadResponse } from "@/lib/api";
import { AvatarImage } from "./auth-ui";
import { CitationMarkdown } from "./citation-markdown";
import { OaDraftCard } from "./oa-draft-card";
import { usePreviewOpener } from "@/lib/preview-context";

export type MessageArtifact = {
  artifact_id: string;
  filename: string;
  mime: string;
};

export type ChatMessage = {
  id: string;
  server_id?: number;
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
  status?: StatusInfo;
  artifacts?: MessageArtifact[];
  drafts?: OaDraft[];
  kbSources?: { title: string; doc_id: string }[];
  attachments?: UploadResponse[];
};

export function MessageBubble({
  message,
  onPreviewArtifact,
  onPreviewUpload,
  onDownloadArtifact,
  onEditMessage,
  canEdit,
  userAvatar,
}: {
  message: ChatMessage;
  onPreviewArtifact?: (a: MessageArtifact) => void;
  onPreviewUpload?: (file: UploadResponse) => void;
  onDownloadArtifact?: (a: MessageArtifact) => void;
  onEditMessage?: (message: ChatMessage, newText: string) => void;
  canEdit?: boolean;
  userAvatar?: string | null;
}) {
  const { t } = useI18n();
  const previewOpener = usePreviewOpener();
  const isUser = message.role === "user";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  // Only settled user turns that are persisted (have a server id) can be edited.
  const editable =
    isUser && !!canEdit && !!onEditMessage && message.server_id != null && !message.pending;

  const startEdit = () => {
    setDraft(message.content);
    setEditing(true);
  };
  const submitEdit = () => {
    const next = draft.trim();
    if (!next) return;
    setEditing(false);
    if (next !== message.content) onEditMessage!(message, next);
  };

  if (isUser && editing) {
    return (
      <div className="flex min-w-0 flex-col items-end gap-2">
        <textarea
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submitEdit();
            } else if (e.key === "Escape") {
              setEditing(false);
            }
          }}
          rows={Math.min(8, Math.max(2, draft.split("\n").length))}
          className="field field-accent w-full max-w-[78%] resize-none rounded-2xl px-4 py-3 text-sm leading-relaxed"
        />
        <div className="flex items-center gap-2">
          <button
            onClick={() => setEditing(false)}
            className="btn-ghost rounded-lg border border-border px-3 py-1 text-xs"
          >
            {t.cancel}
          </button>
          <button
            onClick={submitEdit}
            disabled={!draft.trim()}
            className="btn-accent rounded-lg px-3 py-1 text-xs disabled:opacity-40"
          >
            {t.editResend}
          </button>
        </div>
      </div>
    );
  }
  const showStatus =
    message.pending && !!message.status && message.content.length === 0;
  const showTypingDots =
    message.pending && !message.status && message.content.length === 0;

  return (
    <div
      className={cn(
        "group flex min-w-0 items-start gap-3 animate-fade-in transition-all duration-300",
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
          "flex min-w-0 max-w-[78%] flex-col gap-1",
          isUser ? "items-end" : "items-start",
        )}
      >
        <div
          className={cn(
            "min-w-0 max-w-full w-fit rounded-2xl px-4 py-3 text-sm leading-relaxed transition-all duration-300",
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
          <div className="flex min-w-0 flex-col gap-2.5">
            {message.attachments && message.attachments.length > 0 ? (
              <div
                className={cn(
                  "grid w-64 max-w-full gap-2",
                  message.attachments.length > 1 ? "grid-cols-2" : "grid-cols-1",
                )}
              >
                {message.attachments.map((file) => (
                  <MessageAttachment
                    key={file.file_id}
                    file={file}
                    onPreview={onPreviewUpload}
                  />
                ))}
              </div>
            ) : null}
            <span className="whitespace-pre-wrap">{message.content}</span>
          </div>
        ) : (
          <>
            <CitationMarkdown content={message.content + (message.pending ? "▍" : "")} stripSourceSections />
            {message.artifacts && message.artifacts.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {message.artifacts.map((a) => (
                  <ArtifactChip
                    key={a.artifact_id}
                    artifact={a}
                    onPreview={onPreviewArtifact}
                    onDownload={onDownloadArtifact}
                    downloadLabel={t.download}
                  />
                ))}
              </div>
            ) : null}
            {message.drafts && message.drafts.length > 0 ? (
              <div className="flex flex-col">
                {message.drafts.map((d, i) => (
                  <OaDraftCard key={i} draft={d} />
                ))}
              </div>
            ) : null}
            {message.kbSources && message.kbSources.length > 0 ? (
              <div className="mt-3 border-t border-border/60 pt-2.5">
                <div className="text-[11px] text-fg-subtle mb-1.5">{t.knowledgeBase}</div>
                <div className="flex flex-wrap gap-2">
                  {message.kbSources.map((s) => (
                    <button
                      key={s.doc_id}
                      type="button"
                      onClick={() => previewOpener?.openKb(s.doc_id, s.title)}
                      className="inline-flex items-center gap-1.5 rounded-full border border-border bg-bg-subtle/60 px-2.5 py-1 text-xs text-fg-muted transition hover:border-accent/40 hover:text-fg"
                      title={s.title}
                    >
                      <BookOpen size={12} className="text-accent shrink-0" />
                      <span className="truncate max-w-[20ch]">{s.title}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </>
        )}
        </div>
        {editable ? (
          <button
            onClick={startEdit}
            className="btn-ghost inline-flex h-6 items-center gap-1 rounded-full px-2 text-[11px] text-fg-subtle opacity-0 transition group-hover:opacity-100"
            aria-label={t.editMessage}
            title={t.editMessage}
          >
            <Pencil size={12} />
            <span>{t.editMessage}</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}

function MessageAttachment({
  file,
  onPreview,
}: {
  file: UploadResponse;
  onPreview?: (file: UploadResponse) => void;
}) {
  const isImage = file.mime.startsWith("image/");
  return (
    <button
      type="button"
      onClick={() => onPreview?.(file)}
      className="min-w-0 overflow-hidden rounded-xl border border-white/25 bg-black/10 text-left transition hover:bg-black/15"
      title={file.original_name}
    >
      {isImage ? (
        <img
          src={uploadPreviewUrl(file.file_id)}
          alt={file.original_name}
          className="h-32 w-full object-cover"
        />
      ) : (
        <div className="flex h-20 items-center justify-center">
          <FileText size={24} />
        </div>
      )}
      <span className="flex min-w-0 items-center gap-1.5 px-2.5 py-2 text-xs">
        {isImage ? <FileImage size={13} className="shrink-0" /> : <FileText size={13} className="shrink-0" />}
        <span className="truncate">{file.original_name}</span>
      </span>
    </button>
  );
}

function ArtifactChip({
  artifact,
  onPreview,
  onDownload,
  downloadLabel,
}: {
  artifact: MessageArtifact;
  onPreview?: (a: MessageArtifact) => void;
  onDownload?: (a: MessageArtifact) => void;
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
        onClick={(event) => {
          if (!onDownload) return;
          event.preventDefault();
          onDownload(artifact);
        }}
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
