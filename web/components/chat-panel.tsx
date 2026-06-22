"use client";

import { Send, Loader2 } from "lucide-react";
import { useEffect, useRef } from "react";
import { MessageBubble, type ChatMessage, type MessageArtifact } from "./message";
import { FileUploader } from "./file-uploader";
import { ExamplePrompts } from "./example-prompts";
import type { UploadResponse } from "@/lib/api";

export function ChatPanel({
  messages,
  input,
  setInput,
  onSend,
  busy,
  attached,
  onAttach,
  onRemoveAttached,
  onPreviewUpload,
  onPreviewArtifact,
  userAvatar,
}: {
  messages: ChatMessage[];
  input: string;
  setInput: (v: string) => void;
  onSend: () => void;
  busy: boolean;
  attached: UploadResponse[];
  onAttach: (f: UploadResponse) => void;
  onRemoveAttached: (fileId: string) => void;
  onPreviewUpload: (f: UploadResponse) => void;
  onPreviewArtifact: (a: MessageArtifact) => void;
  userAvatar?: string | null;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const empty = messages.length === 0;

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {empty ? (
          <div className="h-full flex flex-col items-center justify-center px-6 py-12 gap-8">
            <div className="text-center max-w-xl">
              <h1 className="text-3xl font-semibold tracking-tight">
                Your marketing team&apos;s AI copilot
              </h1>
              <p className="mt-2 text-fg-muted text-sm">
                Ask for content, campaign analysis, or competitor research.
                The orchestrator routes to specialists and synthesizes the
                result.
              </p>
            </div>
            <ExamplePrompts
              onPick={(prompt) => {
                setInput(prompt);
              }}
            />
          </div>
        ) : (
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-5">
            {messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                onPreviewArtifact={onPreviewArtifact}
                userAvatar={userAvatar}
              />
            ))}
          </div>
        )}
      </div>

      <div className="border-t border-border bg-bg-elevated/60 backdrop-blur">
        <div className="max-w-3xl mx-auto px-4 py-3 space-y-2">
          <FileUploader
            attached={attached}
            onAttach={onAttach}
            onRemove={onRemoveAttached}
            onPreview={onPreviewUpload}
          />
          <div className="flex items-end gap-2 rounded-xl border border-border bg-bg-elevated focus-within:border-accent transition shadow-sm">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  if (!busy && input.trim()) onSend();
                }
              }}
              rows={1}
              placeholder="Ask the marketing team anything…  (Enter to send, Shift+Enter for newline)"
              disabled={busy}
              className="flex-1 resize-none bg-transparent px-4 py-3 text-sm placeholder:text-fg-subtle focus:outline-none disabled:opacity-50 max-h-48"
              style={{ minHeight: 48 }}
            />
            <button
              onClick={onSend}
              disabled={busy || !input.trim()}
              className="m-1.5 inline-flex items-center justify-center w-9 h-9 rounded-lg bg-accent text-accent-fg hover:opacity-90 transition disabled:opacity-40 disabled:cursor-not-allowed"
              aria-label="Send"
            >
              {busy ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Send size={16} />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
