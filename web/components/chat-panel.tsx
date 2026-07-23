"use client";

import {
  Check,
  ChevronDown,
  FolderOpen,
  Loader2,
  MessageSquare,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { createPortal } from "react-dom";
import { useEffect, useRef, useState } from "react";
import { MessageBubble, type ChatMessage, type MessageArtifact } from "./message";
import { FileUploader } from "./file-uploader";
import { getMarketingMemory, getWorkflowSkills, requestClarification, uploadFile, type ClarifyPlan, type ClarifyQuestion, type MarketingMemoryProfile, type UploadResponse, type WorkflowSkill } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type DirectoryHandle = FileSystemDirectoryHandle & {
  values: () => AsyncIterable<FileSystemHandle>;
};

type WorkspaceFile = {
  file: File;
  key: string;
};

type ClarifySuggestion = {
  id: string;
  title: string;
  description: string;
  detail: string;
  custom?: boolean;
};

type ClarifyStep = {
  id: string;
  title: string;
  body: string;
  suggestions: ClarifySuggestion[];
};

type ClarifySlot = "platform" | "audience" | "tone" | "format" | "product";

export function ChatPanel({
  messages,
  input,
  setInput,
  onSend,
  busy,
  attached,
  onAttach,
  onRemoveAttached,
  onClarificationRequest,
  onPreviewUpload,
  onPreviewArtifact,
  onDownloadArtifact,
  userAvatar,
  selectedSkillIds,
  setSelectedSkillIds,
  workspaceFileIds,
  setWorkspaceFileIds,
  onWorkspaceSelected,
}: {
  messages: ChatMessage[];
  input: string;
  setInput: (v: string) => void;
  onSend: (override?: string) => void;
  busy: boolean;
  attached: UploadResponse[];
  onAttach: (f: UploadResponse) => void;
  onRemoveAttached: (fileId: string) => void;
  onClarificationRequest?: (prompt: string, assistantText: string) => void;
  onPreviewUpload: (f: UploadResponse) => void;
  onPreviewArtifact: (a: MessageArtifact) => void;
  onDownloadArtifact?: (a: MessageArtifact) => void;
  userAvatar?: string | null;
  selectedSkillIds: string[];
  setSelectedSkillIds: (ids: string[]) => void;
  workspaceFileIds: string[];
  setWorkspaceFileIds: (ids: string[]) => void;
  onWorkspaceSelected: (handle: DirectoryHandle | null, name: string | null) => void;
}) {
  const { t, locale } = useI18n();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [skills, setSkills] = useState<WorkflowSkill[]>([]);
  const [skillsOpen, setSkillsOpen] = useState(false);
  const [workspaceName, setWorkspaceName] = useState<string | null>(null);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [workspaceNote, setWorkspaceNote] = useState<string | null>(null);
  const [workspaceHandle, setWorkspaceHandle] = useState<DirectoryHandle | null>(null);
  const [clarifyOpen, setClarifyOpen] = useState(false);
  const [clarifyDraft, setClarifyDraft] = useState("");
  const [clarifyCustom, setClarifyCustom] = useState(false);
  const [clarifyPrimary, setClarifyPrimary] = useState<ClarifySuggestion | null>(null);
  const [clarifySelections, setClarifySelections] = useState<ClarifySuggestion[]>([]);
  const [clarifyStepIndex, setClarifyStepIndex] = useState(0);
  const [clarifyReady, setClarifyReady] = useState(false);
  const [clarifyBaseText, setClarifyBaseText] = useState("");
  // When set, clarification is driven by the LLM-generated questions instead of
  // the client-side heuristic question tree.
  const [clarifyServerSteps, setClarifyServerSteps] = useState<ClarifyStep[] | null>(null);
  const [clarifyChecking, setClarifyChecking] = useState(false);
  const [marketingMemory, setMarketingMemory] = useState<Partial<MarketingMemoryProfile> | null>(null);
  const skillButtonRef = useRef<HTMLButtonElement>(null);
  const workspaceUploadMapRef = useRef<Map<string, string>>(new Map());

  const copy = locale === "zh"
    ? {
        workspace: "工作区",
        chooseWorkspace: "选择工作区",
        workspaceSynced: (count: number) => `已同步 ${count} 个可读文件`,
        workspaceUnsupported: "当前浏览器不支持直接选择文件夹，可继续使用上传文件。",
        skills: "skill",
        noSkill: "未选择 skill",
        selected: (count: number) => `已选 ${count} 个 skill`,
        clarifyTitle: "补充一下任务信息",
        clarifyBody: "这个问题有点宽泛。补充目标、受众、渠道或交付格式后，我能按更稳定的流程生成。",
        clarifyPlaceholder: "例如：目标用户、品牌/产品、平台、语气、字数、截止时间、需要的格式...",
        continueSend: "继续发送",
        clarifyChecking: "分析中...",
        clarifyServerIntro: "为了更好地完成，我先确认几点：",
        clarifyPickAnswer: "选择或补充你的答案",
      }
    : {
        workspace: "Workspace",
        chooseWorkspace: "Choose workspace",
        workspaceSynced: (count: number) => `${count} readable files synced`,
        workspaceUnsupported: "This browser cannot choose folders directly. You can still attach files.",
        skills: "skill",
        noSkill: "No skill selected",
        selected: (count: number) => `${count} skills selected`,
        clarifyTitle: "Add a little context",
        clarifyBody: "This request is broad. Adding goal, audience, channel, or output format helps produce a steadier result.",
        clarifyPlaceholder: "e.g. audience, product, platform, tone, length, deadline, desired format...",
        continueSend: "Continue",
        clarifyChecking: "Analyzing...",
        clarifyServerIntro: "To do this well, let me confirm a few things:",
        clarifyPickAnswer: "Pick or type your answer",
      };

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    getWorkflowSkills().then(setSkills).catch(() => setSkills([]));
  }, []);

  useEffect(() => {
    getMarketingMemory()
      .then((res) => setMarketingMemory(res.profile))
      .catch(() => setMarketingMemory(null));
  }, []);

  const empty = messages.length === 0;
  const selectedSkills = skills.filter((skill) => selectedSkillIds.includes(skill.id));
  const serverMode = clarifyServerSteps !== null;
  const clarifyInitialStep = !serverMode && !clarifyPrimary ? getInitialClarifyStep(clarifyBaseText || input, locale, marketingMemory) : null;
  const clarifySteps = serverMode
    ? clarifyServerSteps
    : clarifyPrimary
    ? getClarifyFollowupSteps(clarifyPrimary.id, locale, clarifyBaseText || input, marketingMemory)
    : [];
  const clarifyCurrentStep = serverMode || clarifyPrimary ? clarifySteps[clarifyStepIndex] : null;
  const clarifySuggestions = clarifyReady
    ? getClarifyFinalSuggestions(locale)
    : clarifyCurrentStep?.suggestions ?? clarifyInitialStep?.suggestions ?? getClarifySuggestions(clarifyBaseText || input, locale, marketingMemory);
  const clarifyTitle = clarifyReady
    ? locale === "zh" ? "信息基本完备" : "Ready to proceed"
    : clarifyCurrentStep?.title ?? clarifyInitialStep?.title ?? copy.clarifyTitle;
  const clarifyBody = clarifyReady
    ? locale === "zh"
      ? "我已经获得了足够的信息，可以开始执行。你也可以继续补充其它要求后再执行。"
      : "I have enough context to proceed. You can also add more requirements before starting."
    : clarifyCurrentStep?.body ?? clarifyInitialStep?.body ?? copy.clarifyBody;
  const clarifyStepLabelText = serverMode
    ? clarifyReady
      ? locale === "zh" ? "确认执行" : "Confirm"
      : `${locale === "zh" ? "追问" : "Question"} ${Math.min(clarifyStepIndex + 1, clarifySteps.length)}/${clarifySteps.length}`
    : getClarifyStepLabel(clarifyPrimary, clarifyStepIndex, clarifySteps.length, locale);

  useEffect(() => {
    if (!workspaceHandle) return;
    const id = window.setInterval(() => {
      void syncWorkspace(workspaceHandle, true);
    }, 4500);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceHandle]);

  function toggleSkill(skillId: string) {
    setSelectedSkillIds(
      selectedSkillIds.includes(skillId)
        ? selectedSkillIds.filter((id) => id !== skillId)
        : [...selectedSkillIds, skillId],
    );
  }

  async function chooseWorkspace() {
    const picker = (window as unknown as {
      showDirectoryPicker?: () => Promise<DirectoryHandle>;
    }).showDirectoryPicker;
    if (!picker) {
      setWorkspaceNote(copy.workspaceUnsupported);
      return;
    }
    setWorkspaceBusy(true);
    setWorkspaceNote(null);
    try {
      const handle = await picker();
      setWorkspaceName(handle.name);
      setWorkspaceHandle(handle);
      onWorkspaceSelected(handle, handle.name);
      await syncWorkspace(handle);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setWorkspaceNote(String(error));
      }
    } finally {
      setWorkspaceBusy(false);
    }
  }

  function clearWorkspace() {
    setWorkspaceName(null);
    setWorkspaceHandle(null);
    workspaceUploadMapRef.current.clear();
    setWorkspaceFileIds([]);
    onWorkspaceSelected(null, null);
    setWorkspaceNote(null);
  }

  async function syncWorkspace(handle: DirectoryHandle, quiet = false) {
    if (!quiet) setWorkspaceBusy(true);
    try {
      const files = await collectWorkspaceFiles(handle);
      const known = workspaceUploadMapRef.current;
      const nextIds: string[] = [];
      const liveKeys = new Set(files.map((item) => item.key));
      for (const key of Array.from(known.keys())) {
        if (!liveKeys.has(key)) known.delete(key);
      }
      for (const item of files) {
        let fileId = known.get(item.key);
        if (!fileId) {
          const saved = await uploadFile(item.file);
          fileId = saved.file_id;
          known.set(item.key, fileId);
        }
        nextIds.push(fileId);
      }
      setWorkspaceFileIds(nextIds);
      setWorkspaceNote(copy.workspaceSynced(nextIds.length));
    } catch (error) {
      if (!quiet) setWorkspaceNote(String(error));
    } finally {
      if (!quiet) setWorkspaceBusy(false);
    }
  }

  async function submitWithClarifyCheck() {
    const text = input.trim();
    if (!text || busy || clarifyChecking || clarifyOpen) return;

    // Chit-chat / non-task messages skip clarification entirely (no LLM round-trip).
    if (!looksLikeTask(text)) {
      onSend(text);
      resetClarify();
      return;
    }

    // Ask the model whether — and what — to clarify.
    setClarifyChecking(true);
    let plan: ClarifyPlan | null = null;
    try {
      plan = await requestClarification(text, locale);
    } catch {
      plan = null;
    }
    setClarifyChecking(false);

    if (plan && plan.source === "llm") {
      if (plan.needs_clarification && plan.questions.length > 0) {
        openServerClarify(text, mapServerQuestions(plan.questions, locale, copy.clarifyPickAnswer));
        return;
      }
      // Model judged the request clear enough — run it directly.
      onSend(text);
      resetClarify();
      return;
    }

    // LLM unavailable or errored — fall back to the heuristic flow.
    if (looksAmbiguous(text, marketingMemory)) {
      openHeuristicClarify(text);
      return;
    }
    onSend(text);
    resetClarify();
  }

  function openServerClarify(text: string, steps: ClarifyStep[]) {
    setClarifyServerSteps(steps);
    setClarifyOpen(true);
    setClarifyCustom(false);
    setClarifyDraft("");
    setClarifyPrimary(null);
    setClarifySelections([]);
    setClarifyStepIndex(0);
    setClarifyReady(steps.length === 0);
    setClarifyBaseText(text);
    setInput("");
    const intro = `${copy.clarifyServerIntro}\n${steps.map((s) => `- ${s.title}`).join("\n")}`;
    onClarificationRequest?.(text, intro);
  }

  function openHeuristicClarify(text: string) {
    setClarifyServerSteps(null);
    setClarifyOpen(true);
    setClarifyCustom(false);
    setClarifyDraft("");
    setClarifyPrimary(null);
    setClarifySelections([]);
    setClarifyStepIndex(0);
    setClarifyReady(false);
    setClarifyBaseText(text);
    setInput("");
    onClarificationRequest?.(text, buildClarificationReply(text, locale, marketingMemory));
  }

  function resetClarify() {
    setClarifyDraft("");
    setClarifyOpen(false);
    setClarifyCustom(false);
    setClarifyPrimary(null);
    setClarifySelections([]);
    setClarifyStepIndex(0);
    setClarifyReady(false);
    setClarifyBaseText("");
    setClarifyServerSteps(null);
    setClarifyChecking(false);
  }

  function sendClarified(detail: string) {
    const text = clarifyBaseText.trim() || input.trim();
    const details = [
      clarifyPrimary?.detail,
      ...clarifySelections.map((item) => item.detail),
      detail,
    ].filter(Boolean);
    const extra = details.join("\n").trim();
    const prefix = locale === "zh" ? "补充信息" : "Additional context";
    onSend(extra ? `${text}\n\n${prefix}: ${extra}` : text);
    resetClarify();
  }

  function chooseClarifySuggestion(suggestion: ClarifySuggestion) {
    if (clarifyReady && suggestion.id === "execute") {
      sendClarified("");
      return;
    }
    if (suggestion.custom) {
      setClarifyCustom(true);
      return;
    }
    setClarifyCustom(false);
    setClarifyDraft("");

    // Heuristic mode: the first choice picks a direction (the "primary").
    if (!serverMode && !clarifyPrimary) {
      const steps = getClarifyFollowupSteps(suggestion.id, locale, clarifyBaseText || input);
      setClarifyPrimary(suggestion);
      setClarifySelections([]);
      setClarifyStepIndex(0);
      setClarifyReady(steps.length === 0);
      return;
    }

    const nextSelections = [...clarifySelections, suggestion];
    setClarifySelections(nextSelections);
    if (clarifyStepIndex + 1 >= clarifySteps.length) {
      setClarifyReady(true);
    } else {
      setClarifyStepIndex((index) => index + 1);
    }
  }

  function closeClarify() {
    resetClarify();
  }

  function submitCustomClarify() {
    const extra = clarifyDraft.trim();
    if (!extra) return;
    // In server mode, tag the custom answer with the current question for a clean Q→A summary.
    const sep = locale === "zh" ? "：" : ": ";
    const detail = serverMode && clarifyCurrentStep ? `${clarifyCurrentStep.title}${sep}${extra}` : extra;
    const customSuggestion: ClarifySuggestion = {
      id: `custom-${Date.now()}`,
      title: locale === "zh" ? "其它补充" : "Other context",
      description: extra,
      detail,
    };

    if (clarifyReady) {
      sendClarified(extra);
      return;
    }

    if (!serverMode && !clarifyPrimary) {
      setClarifyPrimary(customSuggestion);
      setClarifySelections([]);
      setClarifyStepIndex(0);
      setClarifyReady(true);
    } else {
      const nextSelections = [...clarifySelections, customSuggestion];
      setClarifySelections(nextSelections);
      if (clarifyStepIndex + 1 >= clarifySteps.length) {
        setClarifyReady(true);
      } else {
        setClarifyStepIndex((index) => index + 1);
      }
    }
    setClarifyDraft("");
    setClarifyCustom(false);
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 panel-card">
      <header className="col-header">
        <div className="flex items-center gap-2 mx-auto text-sm font-medium">
          <MessageSquare size={15} className="text-feature-content" />
          <span>{t.chatHeader}</span>
        </div>
      </header>
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {empty ? (
          <div className="h-full flex flex-col items-center justify-center px-6 py-12">
            <div className="text-center max-w-xl">
              <h1 className="text-3xl font-semibold tracking-tight">
                {t.heroTitle}
              </h1>
              <p className="mt-2 text-fg-muted text-sm">
                {t.heroBody}
              </p>
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-5">
            {messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                onPreviewArtifact={onPreviewArtifact}
                onDownloadArtifact={onDownloadArtifact}
                userAvatar={userAvatar}
              />
            ))}
          </div>
        )}
      </div>

      <div className="border-t border-border bg-bg-elevated/60 backdrop-blur">
        <div className="max-w-3xl mx-auto px-4 py-2">
          {clarifyOpen ? (
            <ClarifyInlinePrompt
              title={clarifyTitle}
              body={clarifyBody}
              placeholder={copy.clarifyPlaceholder}
              continueLabel={copy.continueSend}
              confirmLabel={locale === "zh" ? "确定" : "OK"}
              cancelLabel={t.cancel}
              suggestions={clarifySuggestions}
              selections={[clarifyPrimary, ...clarifySelections].filter(Boolean) as ClarifySuggestion[]}
              ready={clarifyReady}
              stepLabel={clarifyStepLabelText}
              customOpen={clarifyCustom}
              customDraft={clarifyDraft}
              busy={busy}
              onChoose={chooseClarifySuggestion}
              onDraftChange={setClarifyDraft}
              onCustomSubmit={submitCustomClarify}
              onClose={closeClarify}
            />
          ) : null}
          <div className="input-shell chat-composer-shell overflow-visible">
            <div className="chat-composer-input-row">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submitWithClarifyCheck();
                  }
                }}
                rows={1}
                placeholder={t.inputPlaceholder}
                disabled={busy}
                className="block w-full resize-none bg-transparent px-4 pt-2.5 pb-1 text-sm placeholder:text-fg-subtle focus:outline-none disabled:opacity-50 max-h-40"
                style={{ minHeight: 40 }}
              />
            </div>
            <div className="flex flex-wrap items-center gap-1.5 px-2 pb-2 pt-1">
              <FileUploader
                attached={attached}
                onAttach={onAttach}
                onRemove={onRemoveAttached}
                onPreview={onPreviewUpload}
                compact
              />
              <button
                type="button"
                onClick={chooseWorkspace}
                disabled={busy || workspaceBusy}
                className="btn-ghost h-8 px-2 text-xs disabled:opacity-50"
                title={copy.workspace}
              >
                {workspaceBusy ? <Loader2 size={14} className="animate-spin" /> : <FolderOpen size={14} />}
                <span className="max-w-[16ch] truncate">{workspaceName ?? copy.chooseWorkspace}</span>
              </button>
              {workspaceName ? (
                <button
                  type="button"
                  onClick={clearWorkspace}
                  className="btn-ghost h-8 w-8 text-xs"
                  title={t.removeFile}
                >
                  <X size={14} />
                </button>
              ) : null}
              <div>
                <button
                  ref={skillButtonRef}
                  type="button"
                  onClick={() => setSkillsOpen((open) => !open)}
                  className="btn-ghost h-8 px-2 text-xs"
                  title={copy.skills}
                >
                  <Sparkles size={14} />
                  <span>{selectedSkills.length ? copy.selected(selectedSkills.length) : copy.noSkill}</span>
                  <ChevronDown size={13} className={`transition ${skillsOpen ? "rotate-180" : ""}`} />
                </button>
                <SkillPickerPopover
                  open={skillsOpen}
                  anchorRef={skillButtonRef}
                  skills={skills}
                  selectedSkillIds={selectedSkillIds}
                  locale={locale}
                  onToggleSkill={toggleSkill}
                  onClose={() => setSkillsOpen(false)}
                />
              </div>
              {workspaceNote ? (
                <span className="min-w-0 truncate text-[11px] text-fg-subtle">
                  {workspaceNote}
                </span>
              ) : workspaceFileIds.length > 0 ? (
                <span className="text-[11px] text-fg-subtle">{copy.workspaceSynced(workspaceFileIds.length)}</span>
              ) : null}
              {clarifyChecking ? (
                <span className="ml-auto mr-1 inline-flex items-center gap-1 text-[11px] text-fg-subtle">
                  <Loader2 size={12} className="animate-spin" />
                  {copy.clarifyChecking}
                </span>
              ) : null}
              <button
                onClick={submitWithClarifyCheck}
                disabled={busy || clarifyChecking || !input.trim()}
                className={`btn-accent h-8 w-8 disabled:cursor-not-allowed${clarifyChecking ? "" : " ml-auto"}`}
                aria-label={t.send}
              >
                {busy || clarifyChecking ? (
                  <Loader2 size={15} className="animate-spin text-feature-content transition-all duration-300" />
                ) : (
                  <Send size={15} className="transition-all duration-200 group-hover:scale-110" />
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ClarifyInlinePrompt({
  title,
  body,
  placeholder,
  continueLabel,
  confirmLabel,
  cancelLabel,
  suggestions,
  selections,
  ready,
  stepLabel,
  customOpen,
  customDraft,
  busy,
  onChoose,
  onDraftChange,
  onCustomSubmit,
  onClose,
}: {
  title: string;
  body: string;
  placeholder: string;
  continueLabel: string;
  confirmLabel: string;
  cancelLabel: string;
  suggestions: ClarifySuggestion[];
  selections: ClarifySuggestion[];
  ready: boolean;
  stepLabel: string;
  customOpen: boolean;
  customDraft: string;
  busy: boolean;
  onChoose: (suggestion: ClarifySuggestion) => void;
  onDraftChange: (value: string) => void;
  onCustomSubmit: () => void;
  onClose: () => void;
}) {
  return (
    <div className="clarify-inline-panel mb-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-fg">
            <Sparkles size={15} className="text-accent" />
            <span>{title}</span>
            <span className="rounded-full border border-accent/20 bg-accent/10 px-2 py-0.5 text-[10px] font-medium text-accent">
              {stepLabel}
            </span>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-fg-muted">{body}</p>
        </div>
        <button type="button" onClick={onClose} className="btn-ghost h-7 w-7 shrink-0" aria-label={cancelLabel}>
          <X size={14} />
        </button>
      </div>
      {selections.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {selections.map((item) => (
            <span key={item.id} className="rounded-full border border-border/70 bg-bg/55 px-2 py-1 text-[11px] text-fg-muted">
              {item.title}
            </span>
          ))}
        </div>
      ) : null}
      <div className="mt-3 space-y-1.5">
        {suggestions.map((suggestion) => {
          const isCustomActive = suggestion.custom && customOpen;
          return (
            <div
              key={suggestion.id}
              className={`clarify-choice-row ${isCustomActive ? "clarify-choice-row-active" : ""}`}
            >
              <button
                type="button"
                onClick={() => onChoose(suggestion)}
                disabled={busy}
                className="flex min-w-0 flex-1 items-center gap-3 text-left disabled:opacity-60"
              >
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-accent/25 text-[10px] font-semibold text-accent">
                  {suggestion.custom ? "+" : "›"}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-xs font-semibold text-fg">{suggestion.title}</span>
                  <span className="block truncate text-[11px] leading-snug text-fg-muted">
                    {suggestion.description}
                  </span>
                </span>
              </button>
              {isCustomActive ? (
                <div className="mt-2 flex gap-2 pl-8">
                  <input
                    value={customDraft}
                    onChange={(e) => onDraftChange(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        onCustomSubmit();
                      }
                    }}
                    placeholder={placeholder}
                    className="min-w-0 flex-1 rounded-lg border border-border bg-bg/80 px-3 py-2 text-xs text-fg placeholder:text-fg-subtle focus:outline-none focus:ring-2 focus:ring-accent/25"
                    autoFocus
                  />
                  <button
                    type="button"
                    onClick={onCustomSubmit}
                    disabled={busy || !customDraft.trim()}
                    className="btn-accent shrink-0 px-3 py-2 text-xs disabled:cursor-not-allowed"
                  >
                    {ready ? continueLabel : confirmLabel}
                  </button>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function looksAmbiguous(text: string, memory?: Partial<MarketingMemoryProfile> | null): boolean {
  const compact = text.replace(/\s+/g, "");
  const broad = /^(帮我)?(写|做|生成|分析|总结|策划|优化)(一下|一个|一份)?[。.!！?？]*$/;
  const englishBroad = /^(write|make|generate|analyze|summarize|plan|optimize)(\s+it|\s+this)?[.!?]*$/i;
  return (
    compact.length <= 8 ||
    broad.test(compact) ||
    englishBroad.test(text.trim()) ||
    isUnderSpecifiedMarketingTask(text, memory)
  );
}

function isUnderSpecifiedMarketingTask(text: string, memory?: Partial<MarketingMemoryProfile> | null): boolean {
  const compact = text.replace(/\s+/g, "").toLowerCase();
  const normalized = text.toLowerCase();
  const isMarketingGeneration =
    /营销|文案|种草|推广|宣传|广告|海报|社媒|小红书|公众号|朋友圈|短视频|邮件|linkedin|post|copy|campaign|ad|social/.test(compact) &&
    /写|生成|编写|创作|出一|做|produce|write|generate|create|draft/.test(compact);
  if (!isMarketingGeneration) return false;

  const hasPlatform =
    /平台|渠道|小红书|抖音|公众号|朋友圈|视频号|微博|知乎|b站|邮件|官网|社群|私域|linkedin|twitter|xhs|instagram|facebook|tiktok|youtube|newsletter|email/.test(compact);
  const hasAudience =
    /受众|人群|用户|客户|消费者|女生|男性|女性|学生|白领|宝妈|决策者|企业|b2b|b2c|audience|customer|user|buyer|persona|segment/.test(compact);
  const hasTone =
    /语气|语调|风格|调性|口吻|专业|亲切|活泼|高级|年轻|正式|幽默|tone|voice|style|professional|friendly|formal|playful/.test(compact);
  const hasFormat =
    /字数|标题|正文|cta|行动号召|格式|篇幅|长度|条|篇|版本|hashtag|话题|caption|headline|body|length|format/.test(compact);
  const hasProductDetail =
    /卖点|亮点|功能|价格|材质|颜色|尺码|款式|系列|品牌|产品|服务|新品|新推出|手机|ai|feature|benefit|price|material|brand|product/.test(compact);

  const remembered = memorySlots(memory);
  const effectivePlatform = hasPlatform || remembered.hasPlatform;
  const effectiveAudience = hasAudience || remembered.hasAudience;
  const effectiveTone = hasTone || remembered.hasTone;
  const effectiveFormat = hasFormat || remembered.hasFormat;
  const effectiveProduct = hasProductDetail || remembered.hasProduct;
  const filledSlots = [effectivePlatform, effectiveAudience, effectiveTone, effectiveFormat, effectiveProduct].filter(Boolean).length;
  if (filledSlots < 3) return true;

  return (
    /文案|copy|post|caption/.test(normalized) &&
    !effectivePlatform &&
    (!effectiveAudience || !effectiveTone || !effectiveFormat)
  );
}

function buildClarificationReply(text: string, locale: "zh" | "en", memory?: Partial<MarketingMemoryProfile> | null): string {
  const missing = missingMarketingSlots(text, locale, memory);
  if (locale === "zh") {
    const items = missing.length ? missing.join("、") : "目标、受众、渠道或交付格式";
    return `这个任务我可以做，但为了避免直接套默认假设，我还需要补齐：**${items}**。\n\n请选择下面最接近的补充信息；我只会继续追问当前提问和长期记忆里还没有、但完成任务必需的内容。`;
  }
  const items = missing.length ? missing.join(", ") : "goal, audience, channel, or output format";
  return `I can do this, but to avoid relying on default assumptions, I still need: **${items}**.\n\nChoose the closest supplemental detail below. I will only ask for information that is missing from both this request and long-term memory, and necessary for the task.`;
}

function missingMarketingSlots(text: string, locale: "zh" | "en", memory?: Partial<MarketingMemoryProfile> | null): string[] {
  const compact = text.replace(/\s+/g, "").toLowerCase();
  const zh = locale === "zh";
  const hasPlatform =
    /平台|渠道|小红书|抖音|公众号|朋友圈|视频号|微博|知乎|b站|邮件|官网|社群|私域|linkedin|twitter|xhs|instagram|facebook|tiktok|youtube|newsletter|email/.test(compact);
  const hasAudience =
    /受众|人群|用户|客户|消费者|女生|男性|女性|学生|白领|宝妈|决策者|企业|b2b|b2c|audience|customer|user|buyer|persona|segment/.test(compact);
  const hasTone =
    /语气|语调|风格|调性|口吻|专业|亲切|活泼|高级|年轻|正式|幽默|tone|voice|style|professional|friendly|formal|playful/.test(compact);
  const hasFormat =
    /字数|标题|正文|cta|行动号召|格式|篇幅|长度|条|篇|版本|hashtag|话题|caption|headline|body|length|format/.test(compact);
  const hasProductDetail =
    /卖点|亮点|功能|价格|材质|颜色|尺码|款式|系列|品牌|产品|服务|新品|新推出|手机|ai|feature|benefit|price|material|brand|product/.test(compact);

  const remembered = memorySlots(memory);
  const out: string[] = [];
  if (!(hasPlatform || remembered.hasPlatform)) out.push(zh ? "平台/渠道" : "platform/channel");
  if (!(hasProductDetail || remembered.hasProduct)) out.push(zh ? "产品/核心卖点" : "product/core benefit");
  if (!(hasAudience || remembered.hasAudience)) out.push(zh ? "目标受众" : "target audience");
  if (!(hasTone || remembered.hasTone)) out.push(zh ? "语气/风格" : "tone/style");
  if (!(hasFormat || remembered.hasFormat)) out.push(zh ? "字数/格式/CTA" : "length/format/CTA");
  return out;
}

function detectMarketingPlatform(compact: string): "xhs" | "linkedin" | "email" | "short-video" | "owned" | "other-social" | null {
  if (/知乎|微博|b站|bilibili|instagram|facebook|twitter|threads/.test(compact)) return "other-social";
  if (/小红书|xhs|littleredbook/.test(compact)) return "xhs";
  if (/linkedin|领英/.test(compact)) return "linkedin";
  if (/邮件|email|newsletter/.test(compact)) return "email";
  if (/抖音|短视频|视频号|tiktok|youtube/.test(compact)) return "short-video";
  if (/朋友圈|社群|私域/.test(compact)) return "owned";
  return null;
}

function memoryText(memory?: Partial<MarketingMemoryProfile> | null, keys?: (keyof MarketingMemoryProfile)[]): string {
  if (!memory) return "";
  const selected = keys ?? Object.keys(memory) as (keyof MarketingMemoryProfile)[];
  return selected
    .flatMap((key) => memory[key] ?? [])
    .join(" ")
    .toLowerCase();
}

function memorySlots(memory?: Partial<MarketingMemoryProfile> | null) {
  const channels = memoryText(memory, ["channels"]);
  const audience = memoryText(memory, ["target_customers"]);
  const tone = memoryText(memory, ["tone_preferences"]);
  const format = memoryText(memory, ["report_format_preferences", "kpi_data_preferences"]);
  const product = memoryText(memory, ["products", "company_brand", "industry"]);
  return {
    hasPlatform: !!detectMarketingPlatform(channels) || channels.length > 0,
    hasAudience: audience.length > 0,
    hasTone: tone.length > 0,
    hasFormat: format.length > 0,
    hasProduct: product.length > 0,
    platform: detectMarketingPlatform(channels),
  };
}

function analyzeMarketingPrompt(text: string, memory?: Partial<MarketingMemoryProfile> | null) {
  const compact = text.replace(/\s+/g, "").toLowerCase();
  const isMarketingGeneration =
    /营销|文案|种草|推广|宣传|广告|海报|社媒|小红书|公众号|朋友圈|短视频|邮件|linkedin|post|copy|campaign|ad|social/.test(compact) &&
    /写|生成|编写|创作|出一|做|produce|write|generate|create|draft/.test(compact);
  const hasPlatform =
    /平台|渠道|小红书|抖音|公众号|朋友圈|视频号|微博|知乎|b站|邮件|官网|社群|私域|linkedin|twitter|xhs|instagram|facebook|tiktok|youtube|newsletter|email/.test(compact);
  const hasAudience =
    /受众|人群|用户|客户|消费者|女生|男性|女性|学生|白领|宝妈|决策者|企业|b2b|b2c|audience|customer|user|buyer|persona|segment/.test(compact);
  const hasTone =
    /语气|语调|风格|调性|口吻|专业|亲切|活泼|高级|年轻|正式|幽默|tone|voice|style|professional|friendly|formal|playful/.test(compact);
  const hasFormat =
    /字数|标题|正文|cta|行动号召|格式|篇幅|长度|条|篇|版本|hashtag|话题|caption|headline|body|length|format/.test(compact);
  const hasProductDetail =
    /卖点|亮点|功能|价格|材质|面料|颜色|尺码|版型|显瘦|舒适|透气|百搭|系列|品牌|产品|服务|新品|新推出|手机|ai|feature|benefit|price|material|brand|product/.test(compact);

  const remembered = memorySlots(memory);
  const platform = detectMarketingPlatform(compact) ?? remembered.platform;

  const category =
    /服装|衣服|女装|男装|穿搭|裙|裤|外套|衬衫|t恤|鞋|包|apparel|fashion|outfit/.test(compact)
      ? "apparel"
      : /saas|b2b|企业|客户|系统|平台|软件|工具|解决方案|crm/.test(compact)
        ? "b2b"
        : "general";

  let productLabel = "这个产品/服务";
  if (category === "apparel") productLabel = "这款服装新品";
  else if (category === "b2b") productLabel = "这个企业产品";

  const productMatch =
    text.match(/(?:为|给|围绕|推广|宣传)([^，。,.!?！？\n]{2,24}?)(?:写|生成|编写|创作|做|的)/) ||
    text.match(/([^，。,.!?！？\n]{2,20}?)(?:营销文案|推广文案|种草文案|宣传文案|广告文案)/);
  if (productMatch?.[1]) {
    productLabel = productMatch[1].replace(/^(公司|我们|新推出的|推出的)/, "").trim() || productLabel;
  }

  return {
    isMarketingGeneration,
    category,
    productLabel,
    hasPlatform: hasPlatform || remembered.hasPlatform,
    hasAudience: hasAudience || remembered.hasAudience,
    hasTone: hasTone || remembered.hasTone,
    hasFormat: hasFormat || remembered.hasFormat,
    hasProductDetail: hasProductDetail || remembered.hasProduct,
    platform,
  };
}

function getInitialClarifyStep(
  text: string,
  locale: "zh" | "en",
  memory?: Partial<MarketingMemoryProfile> | null,
): ClarifyStep | null {
  return buildDynamicMarketingFollowupSteps(text, locale, "initial", memory)[0] ?? null;
}

function getClarifySuggestions(text: string, locale: "zh" | "en", memory?: Partial<MarketingMemoryProfile> | null): ClarifySuggestion[] {
  const compact = text.replace(/\s+/g, "").toLowerCase();
  const isZh = locale === "zh";
  const isAnalysis = /分析|总结|复盘|analy[sz]e|summari[sz]e|review/.test(compact);
  const isPlan = /策划|计划|规划|方案|plan|campaign|strategy/.test(compact);

  const dynamicQuestion = getInitialClarifyStep(text, locale, memory);
  if (dynamicQuestion) return dynamicQuestion.suggestions;

  const dynamicMarketing = buildDynamicMarketingEntrySuggestions(text, locale, memory);
  if (dynamicMarketing) return dynamicMarketing;

  const other: ClarifySuggestion = isZh
    ? {
        id: "other",
        title: "其它",
        description: "自己补充目标、对象、格式或限制条件",
        detail: "",
        custom: true,
      }
    : {
        id: "other",
        title: "Other",
        description: "Add your own goal, audience, format, or constraints",
        detail: "",
        custom: true,
      };

  if (isAnalysis) {
    return [
      isZh
        ? {
            id: "competitor",
            title: "竞品分析",
            description: "对比对象、差异点、机会与可执行建议",
            detail: "请按竞品分析 SOP 完成：明确分析对象与竞品范围，输出竞争格局、核心卖点对比、渠道/内容表现、差异化机会、风险判断和下一步行动建议。",
          }
        : {
            id: "competitor",
            title: "Competitive analysis",
            description: "Compare players, gaps, opportunities, and actions",
            detail: "Use a competitive analysis SOP: define the target and competitors, then cover positioning, feature/message comparison, channel/content signals, differentiation opportunities, risks, and next actions.",
          },
      isZh
        ? {
            id: "data",
            title: "数据分析",
            description: "基于上传数据找表现、原因和建议",
            detail: "请按数据分析方式完成：先确认可用数据与口径，再输出关键指标、异常变化、可能原因、细分发现、结论和建议。",
          }
        : {
            id: "data",
            title: "Data analysis",
            description: "Find performance, drivers, and recommendations from data",
            detail: "Handle this as a data analysis task: confirm available data and definitions, then report key metrics, anomalies, likely drivers, segment findings, conclusions, and recommendations.",
          },
      isZh
        ? {
            id: "market",
            title: "市场调研",
            description: "梳理趋势、用户需求、机会和证据来源",
            detail: "请按市场调研方式完成：梳理趋势背景、目标用户需求、竞品或替代方案、机会判断、证据来源和可落地建议。",
          }
        : {
            id: "market",
            title: "Market research",
            description: "Map trends, needs, opportunities, and evidence",
            detail: "Handle this as market research: cover trend context, user needs, competitors or alternatives, opportunity assessment, evidence sources, and practical recommendations.",
          },
      other,
    ];
  }

  if (isPlan) {
    return [
      isZh
        ? {
            id: "launch",
            title: "营销活动方案",
            description: "目标、受众、渠道、节奏、内容与 KPI",
            detail: "请按营销活动方案完成：明确目标、目标受众、核心信息、渠道组合、执行节奏、内容清单、预算/资源假设和 KPI。",
          }
        : {
            id: "launch",
            title: "Campaign plan",
            description: "Goal, audience, channels, timeline, content, and KPIs",
            detail: "Handle this as a campaign plan: define goal, audience, key message, channel mix, timeline, content list, budget/resource assumptions, and KPIs.",
          },
      isZh
        ? {
            id: "content-calendar",
            title: "内容排期",
            description: "主题、平台、频率、形式和交付清单",
            detail: "请按内容排期完成：输出主题方向、平台选择、发布频率、内容形式、每条内容要点和交付清单。",
          }
        : {
            id: "content-calendar",
            title: "Content calendar",
            description: "Themes, platforms, cadence, formats, and deliverables",
            detail: "Handle this as a content calendar: include themes, platform choices, cadence, content formats, per-post angles, and deliverables.",
          },
      other,
    ];
  }

  return [
    isZh
      ? {
          id: "social-copy",
          title: "社媒文案",
          description: "指定平台、受众、语气和字数后生成",
          detail: "请按社媒文案任务完成：默认面向企业营销场景，补齐平台、目标受众、核心卖点、语气、字数和 CTA 后生成。",
        }
      : {
          id: "social-copy",
          title: "Social copy",
          description: "Generate with platform, audience, tone, and length",
          detail: "Handle this as a social copy task: assume a business marketing context and include platform, audience, value proposition, tone, length, and CTA.",
        },
    isZh
      ? {
          id: "brief",
          title: "营销简报",
          description: "整理背景、目标、策略、交付物和下一步",
          detail: "请按营销简报完成：输出背景、目标、受众、核心策略、关键信息、交付物、时间线和下一步。",
        }
      : {
          id: "brief",
          title: "Marketing brief",
          description: "Frame context, goal, strategy, deliverables, and next steps",
          detail: "Handle this as a marketing brief: include context, goal, audience, core strategy, key message, deliverables, timeline, and next steps.",
        },
    isZh
      ? {
          id: "report",
          title: "报告/文档",
          description: "输出结构化正文，可继续生成附件",
          detail: "请按报告或文档任务完成：先给出清晰结构，再输出完整正文、重点结论、可复用小标题和后续可生成的交付物建议。",
        }
      : {
          id: "report",
          title: "Report/document",
          description: "Produce structured content and possible artifacts",
          detail: "Handle this as a report or document task: provide a clear structure, full draft, key conclusions, reusable headings, and suggested deliverables.",
        },
    other,
  ];
}

function buildDynamicMarketingEntrySuggestions(
  text: string,
  locale: "zh" | "en",
  memory?: Partial<MarketingMemoryProfile> | null,
): ClarifySuggestion[] | null {
  const profile = analyzeMarketingPrompt(text, memory);
  if (!profile.isMarketingGeneration) return null;
  const other = makeOtherSuggestion(locale);
  const isZh = locale === "zh";
  const product = profile.productLabel;

  if (profile.platform === "xhs") {
    return [
      makeSuggestion(
        "xhs-publish-copy",
        isZh ? "小红书营销文案" : "Little Red Book marketing copy",
        isZh ? `围绕${product}生成可直接发布的小红书内容` : `Create publish-ready Little Red Book content for ${product}`,
        isZh
          ? `方向：小红书营销文案。平台：小红书。围绕${product}输出标题、正文、CTA 和话题标签，后续只补齐受众、语气和交付格式。`
          : `Direction: Little Red Book marketing copy. Platform: Little Red Book. Produce title, body, CTA, and tags for ${product}; only clarify audience, tone, and output shape next.`,
      ),
      makeSuggestion(
        "xhs-seeding",
        isZh ? "小红书种草角度" : "Little Red Book seeding angle",
        isZh ? "更偏体验感、场景感和真实推荐" : "More experiential, scenario-led, and recommendation-like",
        isZh
          ? `方向：小红书种草角度。平台：小红书。围绕${product}强化使用场景、体验感、真实推荐和评论互动引导。`
          : `Direction: Little Red Book seeding angle. Platform: Little Red Book. Emphasize usage scenarios, experience, authentic recommendation, and comment engagement.`,
      ),
      makeSuggestion(
        "xhs-conversion-copy",
        isZh ? "小红书转化文案" : "Little Red Book conversion copy",
        isZh ? "更强调卖点、信任感和行动引导" : "Emphasizes benefits, trust, and action",
        isZh
          ? `方向：小红书转化文案。平台：小红书。围绕${product}突出核心卖点、信任理由、行动引导和可收藏信息。`
          : `Direction: Little Red Book conversion copy. Platform: Little Red Book. Highlight benefits, trust reasons, CTA, and save-worthy information.`,
      ),
      other,
    ];
  }

  if (profile.category === "apparel") {
    return [
      makeSuggestion(
        "xhs-seeding",
        isZh ? "小红书种草文案" : "Little Red Book seeding copy",
        isZh ? `适合把${product}写成生活方式种草` : `Frame ${product} as lifestyle seeding content`,
        isZh
          ? `方向：小红书种草文案。平台：小红书。围绕${product}做生活方式种草，后续补齐受众、穿搭场景、语气和 CTA。`
          : `Direction: Little Red Book seeding copy. Platform: Little Red Book. Build lifestyle content around ${product}, then clarify audience, usage scene, tone, and CTA.`,
      ),
      makeSuggestion(
        "short-video-script",
        isZh ? "短视频口播脚本" : "Short video script",
        isZh ? `适合把${product}做成口播/镜头脚本` : `Turn ${product} into a spoken or shot-by-shot script`,
        isZh
          ? `方向：短视频口播脚本。围绕${product}输出开场钩子、镜头/口播、卖点节奏和 CTA。`
          : `Direction: short video script. Produce hook, voiceover or shots, benefit pacing, and CTA for ${product}.`,
      ),
      makeSuggestion(
        "private-conversion",
        isZh ? "私域转化文案" : "Owned-channel conversion copy",
        isZh ? `适合社群/朋友圈推动咨询或下单` : `Use owned channels to drive inquiries or purchase`,
        isZh
          ? `方向：私域转化文案。围绕${product}输出适合朋友圈/社群的转化型表达、利益点和行动引导。`
          : `Direction: owned-channel conversion copy. Write conversion-focused copy, benefits, and CTA for ${product}.`,
      ),
      other,
    ];
  }

  if (profile.category === "b2b") {
    return [
      makeSuggestion(
        "linkedin-b2b",
        isZh ? "LinkedIn 专业帖" : "LinkedIn B2B post",
        isZh ? `适合面向企业客户介绍${product}` : `Introduce ${product} to business buyers`,
        isZh
          ? `方向：LinkedIn 专业帖。围绕${product}输出面向企业客户的痛点、价值主张、可信表达和 CTA。`
          : `Direction: LinkedIn B2B post. Cover pain points, value proposition, credible proof, and CTA for ${product}.`,
      ),
      makeSuggestion(
        "sales-email",
        isZh ? "销售/培育邮件" : "Sales or nurture email",
        isZh ? `适合转化线索或唤醒客户` : `Convert leads or re-engage prospects`,
        isZh
          ? `方向：销售/培育邮件。围绕${product}输出邮件主题、正文结构、价值点和下一步行动。`
          : `Direction: sales or nurture email. Produce subject, body structure, value points, and next action for ${product}.`,
      ),
      makeSuggestion(
        "solution-brief",
        isZh ? "解决方案简版介绍" : "Solution brief",
        isZh ? `适合官网/销售材料的简明介绍` : `A concise website or sales-material description`,
        isZh
          ? `方向：解决方案简版介绍。围绕${product}输出适合官网或销售材料的结构化介绍。`
          : `Direction: solution brief. Produce a structured website or sales-material description for ${product}.`,
      ),
      other,
    ];
  }

  return [
    makeSuggestion(
      "social-copy",
      isZh ? "社媒发布文案" : "Social publishing copy",
      isZh ? `为${product}生成可直接发布的内容` : `Create publishable content for ${product}`,
      isZh
        ? `方向：社媒发布文案。围绕${product}补齐平台、受众、语气、篇幅和 CTA 后生成。`
        : `Direction: social publishing copy. Clarify platform, audience, tone, length, and CTA for ${product}.`,
    ),
    makeSuggestion(
      "campaign-angle",
      isZh ? "营销切入角度" : "Campaign angle",
      isZh ? `先确定传播角度再生成内容` : `Choose the communication angle before drafting`,
      isZh
        ? `方向：营销切入角度。先为${product}确定传播角度，再输出对应内容。`
        : `Direction: campaign angle. Define the communication angle for ${product}, then draft the content.`,
    ),
    makeSuggestion(
      "conversion-copy",
      isZh ? "转化型文案" : "Conversion copy",
      isZh ? `突出卖点和行动引导` : `Emphasize benefits and next action`,
      isZh
        ? `方向：转化型文案。围绕${product}突出卖点、信任感和行动引导。`
        : `Direction: conversion copy. Emphasize benefits, trust, and next action for ${product}.`,
    ),
    other,
  ];
}

function answeredSlots(primaryId: string): Set<ClarifySlot> {
  const out = new Set<ClarifySlot>();
  if (primaryId.startsWith("platform-") || primaryId.includes("xhs") || primaryId.includes("linkedin") || primaryId.includes("email")) {
    out.add("platform");
  }
  if (primaryId.startsWith("audience-") || ["b2b", "operators", "consumers"].includes(primaryId)) out.add("audience");
  if (primaryId.startsWith("tone-")) out.add("tone");
  if (primaryId.startsWith("format-") || ["copy", "outline", "doc"].includes(primaryId)) out.add("format");
  if (primaryId.startsWith("product-") || ["fit", "comfort", "style"].includes(primaryId)) out.add("product");
  return out;
}

function buildDynamicMarketingFollowupSteps(
  text: string,
  locale: "zh" | "en",
  primaryId: string,
  memory?: Partial<MarketingMemoryProfile> | null,
): ClarifyStep[] {
  const profile = analyzeMarketingPrompt(text, memory);
  if (!profile.isMarketingGeneration) return [];
  const isZh = locale === "zh";
  const product = profile.productLabel;
  const other = makeOtherSuggestion(locale);
  const steps: ClarifyStep[] = [];
  const answered = answeredSlots(primaryId);
  const primaryAddsPlatform = [
    "xhs-publish-copy",
    "xhs-seeding",
    "xhs-conversion-copy",
    "short-video-script",
    "private-conversion",
    "linkedin-b2b",
    "sales-email",
    "solution-brief",
  ].includes(primaryId);

  if (!profile.hasProductDetail && profile.category !== "apparel" && !answered.has("product")) {
    steps.push({
      id: "dynamic-product",
      title: isZh ? "这次要推广的产品或核心卖点是什么？" : "What product or core benefit should this promote?",
      body: isZh ? "先确认产品和卖点，后面的受众、语气和 CTA 才能贴合任务。" : "Product and benefit come first, then audience, tone, and CTA can fit the task.",
      suggestions: [
        makeSuggestion("product-new", isZh ? "新品发布" : "New product launch", isZh ? "突出新功能、新价值和尝鲜理由" : "Highlight new features, value, and reasons to try", isZh ? "产品信息：新品发布，突出新功能、新价值和尝鲜理由。" : "Product context: new product launch; highlight new features, value, and reasons to try."),
        makeSuggestion("product-solution", isZh ? "解决方案/服务" : "Solution or service", isZh ? "突出痛点、方案和结果" : "Highlight pain point, solution, and outcome", isZh ? "产品信息：解决方案/服务，突出用户痛点、解决方式和结果收益。" : "Product context: solution or service; highlight pain point, approach, and outcome."),
        makeSuggestion("product-offer", isZh ? "活动/优惠" : "Campaign offer", isZh ? "突出限时权益和行动理由" : "Highlight limited-time value and reason to act", isZh ? "产品信息：活动/优惠，突出限时权益和行动理由。" : "Product context: campaign offer; highlight limited-time value and reason to act."),
        other,
      ],
    });
  }

  if (!profile.hasAudience && !answered.has("audience")) {
    const apparelOptions = [
      makeSuggestion(
        "audience-commuter",
        isZh ? "通勤白领/职场女性" : "Commuting professionals",
        isZh ? "强调舒适、显瘦、好搭配" : "Emphasize comfort, flattering fit, and easy styling",
        isZh ? "目标受众：通勤白领/职场女性，强调舒适、显瘦和好搭配。" : "Audience: commuting professionals; emphasize comfort, flattering fit, and easy styling.",
      ),
      makeSuggestion(
        "audience-young",
        isZh ? "年轻学生/初入职场" : "Students or early-career buyers",
        isZh ? "强调性价比、出片、日常百搭" : "Emphasize value, photogenic looks, and daily versatility",
        isZh ? "目标受众：年轻学生/初入职场人群，强调性价比、出片和日常百搭。" : "Audience: students or early-career buyers; emphasize value, photogenic looks, and everyday versatility.",
      ),
      makeSuggestion(
        "audience-light-mature",
        isZh ? "轻熟精致女性" : "Polished modern women",
        isZh ? "强调质感、版型、场合适配" : "Emphasize texture, fit, and occasion fit",
        isZh ? "目标受众：轻熟精致女性，强调质感、版型和场合适配。" : "Audience: polished modern women; emphasize texture, fit, and occasion fit.",
      ),
      other,
    ];
    const b2bOptions = [
      makeSuggestion("audience-founder", isZh ? "创始人/管理层" : "Founders or executives", isZh ? "强调增长、效率和确定性" : "Emphasize growth, efficiency, and certainty", isZh ? "目标受众：创始人/管理层，强调增长、效率和确定性。" : "Audience: founders or executives; emphasize growth, efficiency, and certainty."),
      makeSuggestion("audience-marketing", isZh ? "市场/运营负责人" : "Marketing or ops leaders", isZh ? "强调执行效率和可衡量结果" : "Emphasize execution efficiency and measurable outcomes", isZh ? "目标受众：市场/运营负责人，强调执行效率和可衡量结果。" : "Audience: marketing or operations leaders; emphasize execution efficiency and measurable outcomes."),
      makeSuggestion("audience-sales", isZh ? "销售团队/BD" : "Sales or BD teams", isZh ? "强调线索、话术和转化" : "Emphasize leads, talking points, and conversion", isZh ? "目标受众：销售团队/BD，强调线索、话术和转化。" : "Audience: sales or BD teams; emphasize leads, talking points, and conversion."),
      other,
    ];
    const generalOptions = [
      makeSuggestion("audience-tech", isZh ? "科技尝鲜人群" : "Tech early adopters", isZh ? "强调新功能、体验升级和新鲜感" : "Emphasize new features, upgraded experience, and novelty", isZh ? `目标受众：科技尝鲜人群，围绕${product}突出新功能、体验升级和新鲜感。` : `Audience: tech early adopters; highlight new features, upgraded experience, and novelty for ${product}.`),
      makeSuggestion("audience-productivity", isZh ? "高效办公/学习人群" : "Productivity-focused users", isZh ? "强调效率、续航、AI 辅助和稳定体验" : "Emphasize efficiency, battery life, AI assistance, and reliability", isZh ? `目标受众：高效办公/学习人群，围绕${product}强调效率、续航、AI 辅助和稳定体验。` : `Audience: productivity-focused users; emphasize efficiency, battery life, AI assistance, and reliability for ${product}.`),
      makeSuggestion("audience-lifestyle", isZh ? "年轻生活方式用户" : "Young lifestyle users", isZh ? "强调拍照、外观、社交表达和日常场景" : "Emphasize camera, design, social expression, and daily scenarios", isZh ? `目标受众：年轻生活方式用户，围绕${product}强调拍照、外观、社交表达和日常场景。` : `Audience: young lifestyle users; emphasize camera, design, social expression, and daily scenarios for ${product}.`),
      other,
    ];
    steps.push({
      id: "dynamic-audience",
      title: isZh ? `${product}主要想打动谁？` : `Who should ${product} speak to?`,
      body: isZh ? "我会根据受众调整卖点顺序、措辞和 CTA。" : "I will adapt the benefit order, wording, and CTA to the audience.",
      suggestions: profile.category === "b2b" ? b2bOptions : profile.category === "apparel" ? apparelOptions : generalOptions,
    });
  }

  if (!profile.hasPlatform && !primaryAddsPlatform && !answered.has("platform")) {
    steps.push({
      id: "dynamic-platform",
      title: isZh ? "这条内容优先发布在哪里？" : "Where will this be published first?",
      body: isZh ? "不同平台会影响开头钩子、篇幅和表达密度。" : "The platform changes hook, length, and density.",
      suggestions: [
        makeSuggestion("platform-xhs", isZh ? "小红书" : "Little Red Book", isZh ? "种草感、生活方式、标签更重要" : "Lifestyle seeding, relatability, and tags matter", isZh ? "发布平台：小红书，使用种草感、生活方式表达和标签。" : "Platform: Little Red Book; use lifestyle seeding, relatability, and tags."),
        makeSuggestion("platform-short-video", isZh ? "短视频平台" : "Short video", isZh ? "需要钩子、口播和镜头节奏" : "Needs hook, voiceover, and shot pacing", isZh ? "发布平台：短视频平台，输出钩子、口播和镜头节奏。" : "Platform: short video; include hook, voiceover, and shot pacing."),
        makeSuggestion("platform-owned", isZh ? "朋友圈/社群" : "Owned channels", isZh ? "更偏信任、转化和行动引导" : "Trust, conversion, and action matter more", isZh ? "发布平台：朋友圈/社群，偏信任转化和行动引导。" : "Platform: owned channels; emphasize trust, conversion, and action."),
        other,
      ],
    });
  }

  if (profile.category === "apparel" && !profile.hasProductDetail && !answered.has("product")) {
    steps.push({
      id: "dynamic-selling-point",
      title: isZh ? "这款服装最该突出哪个卖点？" : "Which apparel benefit matters most?",
      body: isZh ? "卖点会决定文案的主钩子和正文展开顺序。" : "The benefit will determine the main hook and body structure.",
      suggestions: [
        makeSuggestion("fit", isZh ? "版型显瘦/修饰身材" : "Flattering fit", isZh ? "突出视觉效果和穿着自信" : "Highlight look and confidence", isZh ? "核心卖点：版型显瘦/修饰身材，突出视觉效果和穿着自信。" : "Core benefit: flattering fit; emphasize visual effect and confidence."),
        makeSuggestion("comfort", isZh ? "舒适透气/适合日常" : "Comfort and daily wear", isZh ? "突出长时间穿着体验" : "Highlight all-day wearability", isZh ? "核心卖点：舒适透气/适合日常，突出长时间穿着体验。" : "Core benefit: comfort and daily wearability."),
        makeSuggestion("style", isZh ? "百搭出片/场景多" : "Versatile and photogenic", isZh ? "突出通勤、约会、周末等场景" : "Highlight work, dates, weekends, and styling", isZh ? "核心卖点：百搭出片/场景多，突出通勤、约会、周末等穿搭场景。" : "Core benefit: versatile and photogenic; highlight work, dates, weekend styling."),
        other,
      ],
    });
  }

  if (!profile.hasTone && !answered.has("tone")) {
    steps.push({
      id: "dynamic-tone",
      title: isZh ? "想要什么语气和风格？" : "What tone should it use?",
      body: isZh ? "语气会影响标题钩子、情绪浓度和销售感强弱。" : "Tone changes the hook, emotional intensity, and sales feel.",
      suggestions: [
        makeSuggestion("tone-seeding", isZh ? "真实种草感" : "Authentic recommendation", isZh ? "像亲身体验后的自然分享" : "Feels like a real personal recommendation", isZh ? "语气风格：真实种草感，像亲身体验后的自然分享。" : "Tone: authentic recommendation, like a real personal experience."),
        makeSuggestion("tone-refined", isZh ? "精致高级感" : "Refined and premium", isZh ? "更克制，突出质感和审美" : "More restrained, focused on quality and taste", isZh ? "语气风格：精致高级感，更克制，突出质感和审美。" : "Tone: refined and premium, restrained and quality-focused."),
        makeSuggestion("tone-conversion", isZh ? "强转化/促单" : "Conversion-focused", isZh ? "卖点明确，行动引导更强" : "Clear benefits and stronger CTA", isZh ? "语气风格：强转化/促单，卖点明确，行动引导更强。" : "Tone: conversion-focused with clear benefits and stronger CTA."),
        other,
      ],
    });
  }

  if (!profile.hasFormat && !answered.has("format")) {
    steps.push({
      id: "dynamic-format",
      title: isZh ? "最终要输出成什么形态？" : "What final shape should it take?",
      body: isZh ? "我会按这个形态控制长度、结构和 CTA。" : "I will use this to control length, structure, and CTA.",
      suggestions: [
        makeSuggestion("format-one", isZh ? "1 条可直接发布" : "One publish-ready piece", isZh ? "标题 + 正文 + CTA + 话题" : "Title, body, CTA, and tags", isZh ? "交付形式：1 条可直接发布内容，包含标题、正文、CTA 和话题标签。" : "Deliverable: one publish-ready piece with title, body, CTA, and tags."),
        makeSuggestion("format-three", isZh ? "3 个不同角度版本" : "Three angle variants", isZh ? "便于 A/B 测试或挑选" : "Useful for A/B testing or selection", isZh ? "交付形式：3 个不同角度版本，便于 A/B 测试或挑选。" : "Deliverable: three angle variants for A/B testing or selection."),
        makeSuggestion("format-script", isZh ? "短视频脚本" : "Short video script", isZh ? "钩子 + 镜头/口播 + CTA" : "Hook, shots/voiceover, CTA", isZh ? "交付形式：短视频脚本，包含钩子、镜头/口播和 CTA。" : "Deliverable: short video script with hook, shots/voiceover, and CTA."),
        other,
      ],
    });
  }

  return steps.slice(0, 3);
}

function getClarifyFinalSuggestions(locale: "zh" | "en"): ClarifySuggestion[] {
  if (locale === "zh") {
    return [
      {
        id: "execute",
        title: "信息完备，开始执行",
        description: "按已选择的方向和补充信息生成结果",
        detail: "",
      },
      {
        id: "other",
        title: "其它",
        description: "继续手动补充额外要求后再执行",
        detail: "",
        custom: true,
      },
    ];
  }
  return [
    {
      id: "execute",
      title: "Ready, start",
      description: "Run with the selected direction and collected context",
      detail: "",
    },
    {
      id: "other",
      title: "Other",
      description: "Add more custom requirements before starting",
      detail: "",
      custom: true,
    },
  ];
}

function getClarifyStepLabel(
  primary: ClarifySuggestion | null,
  stepIndex: number,
  totalSteps: number,
  locale: "zh" | "en",
) {
  if (!primary) return locale === "zh" ? "选择方向" : "Choose direction";
  if (stepIndex >= totalSteps) return locale === "zh" ? "确认执行" : "Confirm";
  return locale === "zh" ? `追问 ${stepIndex + 1}/${totalSteps}` : `Question ${stepIndex + 1}/${totalSteps}`;
}

function getClarifyFollowupSteps(
  primaryId: string,
  locale: "zh" | "en",
  prompt = "",
  memory?: Partial<MarketingMemoryProfile> | null,
): ClarifyStep[] {
  const isZh = locale === "zh";
  const other = makeOtherSuggestion(locale);
  const dynamicMarketing = buildDynamicMarketingFollowupSteps(prompt, locale, primaryId, memory);
  if (dynamicMarketing.length > 0) return dynamicMarketing;

  if (primaryId === "competitor") {
    return [
      {
        id: "competitor-scope",
        title: isZh ? "先确定竞品范围" : "Define the competitor set",
        body: isZh
          ? "你希望我围绕哪类竞品展开？选择一个最贴近的范围。"
          : "Which competitor scope should I use? Pick the closest option.",
        suggestions: [
          makeSuggestion("direct", isZh ? "直接竞品" : "Direct competitors", isZh ? "同类产品/服务逐项对比" : "Compare similar products or services", isZh ? "竞品范围：直接竞品，重点比较同类产品/服务。" : "Competitor scope: direct competitors; focus on comparable products or services."),
          makeSuggestion("alternatives", isZh ? "替代方案" : "Alternatives", isZh ? "用户可能选择的替代路径" : "Other ways customers solve the problem", isZh ? "竞品范围：替代方案，重点分析用户可能选择的其它解决路径。" : "Competitor scope: alternatives; analyze other ways customers solve the problem."),
          makeSuggestion("benchmark", isZh ? "行业标杆" : "Market leaders", isZh ? "选择头部品牌做标杆参考" : "Benchmark against category leaders", isZh ? "竞品范围：行业标杆，重点参考头部品牌做法。" : "Competitor scope: market leaders; benchmark against category leaders."),
          other,
        ],
      },
      {
        id: "competitor-output",
        title: isZh ? "你更需要哪种产出？" : "What output do you need?",
        body: isZh
          ? "不同产出会影响分析颗粒度和表达方式。"
          : "The deliverable changes the depth and wording of the analysis.",
        suggestions: [
          makeSuggestion("battlecard", isZh ? "销售 Battlecard" : "Sales battlecard", isZh ? "便于销售应对客户比较" : "Help sales handle customer comparisons", isZh ? "交付形式：销售 battlecard，强调对比话术、反驳点和销售建议。" : "Output: sales battlecard with comparison talking points, rebuttals, and sales guidance."),
          makeSuggestion("brief", isZh ? "策略简报" : "Strategy brief", isZh ? "用于内部判断和方向选择" : "For internal decisions and prioritization", isZh ? "交付形式：策略简报，强调竞争格局、机会判断和行动建议。" : "Output: strategy brief focused on landscape, opportunities, and actions."),
          makeSuggestion("content", isZh ? "营销内容素材" : "Marketing content", isZh ? "转化成可发布内容方向" : "Turn analysis into content angles", isZh ? "交付形式：营销内容素材，强调可发布选题、卖点表达和内容角度。" : "Output: marketing content angles, value propositions, and publishable topics."),
          other,
        ],
      },
      {
        id: "competitor-depth",
        title: isZh ? "分析深度要到哪里？" : "How deep should it go?",
        body: isZh
          ? "选择分析深度，我会据此控制篇幅和证据要求。"
          : "Choose depth so I can tune length and evidence requirements.",
        suggestions: [
          makeSuggestion("quick", isZh ? "快速判断" : "Quick read", isZh ? "短结论和关键建议优先" : "Short conclusions and key actions", isZh ? "分析深度：快速判断，优先输出短结论和关键建议。" : "Depth: quick read; prioritize concise conclusions and key actions."),
          makeSuggestion("standard", isZh ? "标准分析" : "Standard analysis", isZh ? "完整结构和清晰依据" : "Full structure with clear rationale", isZh ? "分析深度：标准分析，输出完整结构、依据和建议。" : "Depth: standard analysis with structure, rationale, and recommendations."),
          makeSuggestion("deep", isZh ? "深度报告" : "Deep report", isZh ? "适合沉淀成报告或 PDF" : "Suitable for a report or PDF", isZh ? "分析深度：深度报告，适合沉淀成正式报告或 PDF。" : "Depth: deep report suitable for a formal report or PDF."),
          other,
        ],
      },
    ];
  }

  if (primaryId === "data") {
    return [
      {
        id: "data-source",
        title: isZh ? "数据来源是什么？" : "What data source should I use?",
        body: isZh ? "如果已有文件，可以先说明数据类型或直接上传。" : "If you have a file, describe the data type or attach it.",
        suggestions: [
          makeSuggestion("uploaded", isZh ? "已上传/工作区数据" : "Uploaded/workspace data", isZh ? "基于现有文件分析" : "Analyze available files", isZh ? "数据来源：基于已上传或工作区文件分析。" : "Data source: use uploaded or workspace files."),
          makeSuggestion("campaign", isZh ? "投放/活动数据" : "Campaign data", isZh ? "关注投放表现和转化" : "Focus on performance and conversion", isZh ? "数据来源：投放或活动数据，重点关注表现和转化。" : "Data source: campaign data; focus on performance and conversion."),
          makeSuggestion("manual", isZh ? "文字描述数据" : "Described data", isZh ? "用户会用文字提供口径" : "Use user-provided definitions", isZh ? "数据来源：用户文字描述的数据和口径。" : "Data source: user-described data and definitions."),
          other,
        ],
      },
      {
        id: "data-goal",
        title: isZh ? "最想回答什么问题？" : "What question should it answer?",
        body: isZh ? "选一个分析目标，我会据此组织指标和结论。" : "Pick an analysis goal so I can structure metrics and findings.",
        suggestions: [
          makeSuggestion("why", isZh ? "为什么变化" : "Why it changed", isZh ? "寻找涨跌原因和影响因素" : "Find drivers of movement", isZh ? "分析目标：解释指标变化原因和影响因素。" : "Analysis goal: explain metric movement and drivers."),
          makeSuggestion("performance", isZh ? "表现评估" : "Performance readout", isZh ? "判断好坏和优先级" : "Assess performance and priorities", isZh ? "分析目标：评估表现好坏并给出优先级。" : "Analysis goal: evaluate performance and priorities."),
          makeSuggestion("next", isZh ? "下一步建议" : "Next actions", isZh ? "直接产出行动建议" : "Produce practical recommendations", isZh ? "分析目标：产出下一步行动建议。" : "Analysis goal: produce practical next actions."),
          other,
        ],
      },
    ];
  }

  if (primaryId === "launch" || primaryId === "content-calendar") {
    return [
      {
        id: "plan-goal",
        title: isZh ? "这次方案的核心目标是什么？" : "What is the core goal?",
        body: isZh ? "先定目标，后续渠道、内容和 KPI 才能对齐。" : "Goal first, then channels, content, and KPIs can align.",
        suggestions: [
          makeSuggestion("awareness", isZh ? "提升认知" : "Awareness", isZh ? "让更多目标用户知道" : "Reach more target users", isZh ? "核心目标：提升认知，扩大目标用户触达。" : "Core goal: awareness and reach."),
          makeSuggestion("leads", isZh ? "获客转化" : "Lead generation", isZh ? "收集线索或促进咨询" : "Collect leads or inquiries", isZh ? "核心目标：获客转化，收集线索或促进咨询。" : "Core goal: lead generation and inquiries."),
          makeSuggestion("activation", isZh ? "用户激活" : "Activation", isZh ? "推动试用、购买或复购" : "Drive trials, purchases, or repeat use", isZh ? "核心目标：用户激活，推动试用、购买或复购。" : "Core goal: activation, trials, purchases, or repeat use."),
          other,
        ],
      },
      {
        id: "plan-channel",
        title: isZh ? "优先面向哪个渠道？" : "Which channel is primary?",
        body: isZh ? "选择主渠道后，我会匹配内容形式和节奏。" : "With a primary channel, I can match formats and cadence.",
        suggestions: [
          makeSuggestion("social", isZh ? "社媒平台" : "Social channels", isZh ? "小红书/LinkedIn/公众号等" : "LinkedIn, newsletters, social posts", isZh ? "主渠道：社媒平台，按平台内容形式组织。" : "Primary channel: social platforms; structure by content format."),
          makeSuggestion("private", isZh ? "私域/社群" : "Owned/community", isZh ? "社群、邮件、企微等" : "Email, community, owned channels", isZh ? "主渠道：私域或社群，强调转化链路和持续触达。" : "Primary channel: owned/community; emphasize conversion path and repeated touchpoints."),
          makeSuggestion("multi", isZh ? "多渠道整合" : "Integrated channels", isZh ? "线上线下组合推进" : "Coordinate multiple channels", isZh ? "主渠道：多渠道整合，按阶段组合线上线下触点。" : "Primary channel: integrated channels across stages."),
          other,
        ],
      },
    ];
  }

  return [
    {
      id: "generic-target",
      title: isZh ? "目标受众是谁？" : "Who is the audience?",
      body: isZh ? "先确定对象，生成内容才会更贴近真实场景。" : "Define the audience so the output fits the actual use case.",
      suggestions: [
        makeSuggestion("b2b", isZh ? "B2B 决策者" : "B2B decision-makers", isZh ? "面向企业客户和采购决策" : "Enterprise buyers and decision-makers", isZh ? "目标受众：B2B 决策者或企业客户。" : "Audience: B2B decision-makers or enterprise buyers."),
        makeSuggestion("operators", isZh ? "运营/市场团队" : "Marketing/operators", isZh ? "面向内部执行团队" : "Internal execution teams", isZh ? "目标受众：运营、市场或内部执行团队。" : "Audience: marketing, operations, or internal execution teams."),
        makeSuggestion("consumers", isZh ? "普通消费者" : "Consumers", isZh ? "面向 C 端用户" : "Consumer-facing audience", isZh ? "目标受众：普通消费者或 C 端用户。" : "Audience: consumers or end users."),
        other,
      ],
    },
    {
      id: "generic-format",
      title: isZh ? "希望最终是什么形式？" : "What final format do you want?",
      body: isZh ? "选择交付形式后，我会按对应结构输出。" : "Choose the deliverable so I can use the right structure.",
      suggestions: [
        makeSuggestion("copy", isZh ? "可直接发布的文案" : "Publishable copy", isZh ? "短内容、标题、正文和 CTA" : "Short copy, title, body, CTA", isZh ? "交付形式：可直接发布的文案，包含标题、正文和 CTA。" : "Format: publishable copy with title, body, and CTA."),
        makeSuggestion("outline", isZh ? "结构化方案" : "Structured plan", isZh ? "分模块给出策略和步骤" : "Modular strategy and steps", isZh ? "交付形式：结构化方案，分模块给出策略和步骤。" : "Format: structured plan with modules and steps."),
        makeSuggestion("doc", isZh ? "完整文档" : "Full document", isZh ? "适合沉淀成报告或附件" : "Suitable for report or artifact", isZh ? "交付形式：完整文档，适合沉淀成报告或附件。" : "Format: full document suitable for a report or artifact."),
        other,
      ],
    },
  ];
}

function makeSuggestion(
  id: string,
  title: string,
  description: string,
  detail: string,
): ClarifySuggestion {
  return { id, title, description, detail };
}

function makeOtherSuggestion(locale: "zh" | "en"): ClarifySuggestion {
  return locale === "zh"
    ? {
        id: "other",
        title: "其它",
        description: "自己输入补充内容",
        detail: "",
        custom: true,
      }
    : {
        id: "other",
        title: "Other",
        description: "Type your own context",
        detail: "",
        custom: true,
      };
}

// Broad pre-gate: only spend an LLM round-trip on prompts that look like an
// actual task (generation / analysis / planning). Greetings and short replies
// go straight through.
function looksLikeTask(text: string): boolean {
  const compact = text.replace(/\s+/g, "");
  if (compact.length < 4) return false;
  const taskVerb = /写|做|生成|编写|创作|出一|制作|分析|总结|复盘|策划|规划|方案|优化|设计|撰写|起草|润色|改写|produce|write|generate|create|draft|analyz|analys|summar|plan|optimi|design|review|rewrite/i;
  const taskNoun = /营销|文案|种草|推广|宣传|广告|海报|社媒|小红书|公众号|朋友圈|短视频|邮件|活动|报告|方案|brief|linkedin|post|copy|campaign|report|email|social/i;
  return taskVerb.test(text) || taskNoun.test(text);
}

// Map the LLM-planned questions onto the existing ClarifyStep/ClarifySuggestion
// UI structures so the inline panel renders them unchanged. Each option's
// `detail` carries a "question: answer" line for a clean final summary.
function mapServerQuestions(
  questions: ClarifyQuestion[],
  locale: "zh" | "en",
  pickAnswerLabel: string,
): ClarifyStep[] {
  const sep = locale === "zh" ? "：" : ": ";
  return questions.map((q, qi) => {
    const qid = q.id || `q${qi + 1}`;
    const suggestions: ClarifySuggestion[] = q.options.map((opt, oi) => ({
      id: `${qid}-opt${oi}`,
      title: opt.label,
      description: opt.value && opt.value !== opt.label ? opt.value : "",
      detail: `${q.question}${sep}${opt.value || opt.label}`,
    }));
    if (q.allow_custom) suggestions.push(makeOtherSuggestion(locale));
    return { id: qid, title: q.question, body: pickAnswerLabel, suggestions };
  });
}

function SkillPickerPopover({
  open,
  anchorRef,
  skills,
  selectedSkillIds,
  locale,
  onToggleSkill,
  onClose,
}: {
  open: boolean;
  anchorRef: React.RefObject<HTMLButtonElement>;
  skills: WorkflowSkill[];
  selectedSkillIds: string[];
  locale: "zh" | "en";
  onToggleSkill: (skillId: string) => void;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: 16, bottom: 88, width: 448 });

  useEffect(() => {
    if (!open) return;

    function updatePosition() {
      const anchor = anchorRef.current;
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      const width = Math.min(448, window.innerWidth - 24);
      const left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12));
      setPosition({
        left,
        width,
        bottom: Math.max(12, window.innerHeight - rect.top + 8),
      });
    }

    function onPointerDown(event: MouseEvent | TouchEvent) {
      const target = event.target as Node | null;
      if (!target) return;
      if (panelRef.current?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      onClose();
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("touchstart", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("touchstart", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [anchorRef, onClose, open]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      ref={panelRef}
      className="fixed z-[70] max-h-[44vh] overflow-hidden rounded-2xl border border-border bg-bg-elevated/95 shadow-2xl backdrop-blur-xl"
      style={{
        left: position.left,
        bottom: position.bottom,
        width: position.width,
      }}
    >
      <div className="border-b border-border/70 px-4 py-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-fg">
          <Sparkles size={14} className="text-accent" />
          <span>{locale === "zh" ? "选择 skill" : "Choose skill"}</span>
        </div>
        <p className="mt-1 text-[11px] leading-snug text-fg-subtle">
          {locale === "zh"
            ? "选择一个营销 SOP，生成内容时会按对应流程执行。"
            : "Pick a marketing SOP to guide the response workflow."}
        </p>
      </div>
      <div className="max-h-[calc(44vh-4.75rem)] space-y-2 overflow-y-auto p-2">
        {skills.map((skill) => {
          const active = selectedSkillIds.includes(skill.id);
          const display = localizedSkill(skill, locale);
          return (
            <button
              key={skill.id}
              type="button"
              onClick={() => onToggleSkill(skill.id)}
              className={`group flex w-full items-start gap-3 rounded-xl border px-3 py-3 text-left transition ${
                active
                  ? "border-accent/45 bg-accent/10 text-fg shadow-sm"
                  : "border-border/70 bg-bg-elevated/55 text-fg-muted hover:border-accent/30 hover:bg-bg-subtle/70"
              }`}
            >
              <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition ${
                active
                  ? "border-accent bg-accent text-accent-fg shadow-sm shadow-accent/25"
                  : "border-border bg-bg text-transparent group-hover:border-accent/45"
              }`}>
                <Check size={13} strokeWidth={2.6} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold leading-tight text-fg">{display.name}</span>
                <span className="mt-1 block text-xs leading-relaxed text-fg-muted">{display.description}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>,
    document.body,
  );
}

function localizedSkill(skill: WorkflowSkill, locale: "zh" | "en") {
  if (locale !== "zh") return skill;

  const zh: Record<string, { name: string; description: string }> = {
    "competitive-positioning-brief": {
      name: "竞争定位简报",
      description: "用于竞品对比、差异化叙事、销售 battlecard 或定位备忘录，帮助梳理竞争格局、证据强度、差异化支柱和营销话术。",
    },
    "product-launch-campaign": {
      name: "产品上市 campaign",
      description: "用于新产品、新功能或服务发布，按目标、受众、渠道、时间线和 KPI 拆解完整上市计划与内容交付清单。",
    },
  };

  return zh[skill.id] ?? skill;
}

async function collectWorkspaceFiles(handle: DirectoryHandle): Promise<WorkspaceFile[]> {
  const allowed = new Set(["csv", "xlsx", "xls", "json", "pdf", "docx", "txt", "md", "png", "jpg", "jpeg", "webp"]);
  const out: WorkspaceFile[] = [];

  async function visit(dir: DirectoryHandle, prefix = "") {
    for await (const entry of dir.values()) {
      if (out.length >= 20) return;
      if (entry.kind === "directory") {
        if (!entry.name.startsWith(".") && entry.name !== "node_modules") {
          await visit(entry as DirectoryHandle, `${prefix}${entry.name}/`);
        }
      } else if (entry.kind === "file") {
        const file = await (entry as FileSystemFileHandle).getFile();
        const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
        if (allowed.has(ext) && file.size <= 5 * 1024 * 1024) {
          out.push({
            file,
            key: `${prefix}${file.name}:${file.size}:${file.lastModified}`,
          });
        }
      }
    }
  }

  await visit(handle);
  return out;
}
