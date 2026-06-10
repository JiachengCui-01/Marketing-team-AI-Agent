"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { User, Sparkles } from "lucide-react";
import { cn } from "@/lib/cn";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
};

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

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
        {message.pending ? (
          <TypingDots />
        ) : isUser ? (
          <span className="whitespace-pre-wrap">{message.content}</span>
        ) : (
          <div className="prose-chat">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
        )}
      </div>
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
