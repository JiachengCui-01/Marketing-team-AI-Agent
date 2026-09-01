"use client";

import {
  Check,
  ChevronDown,
  FolderOpen,
  Loader2,
  MessageSquare,
  Send,
  Sparkles,
  Square,
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
  onStop,
  onEditMessage,
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
  onStop?: () => void;
  onEditMessage?: (message: ChatMessage, newText: string) => void;
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
      plan = await requestClarification(
        text,
        locale,
        Array.from(new Set([...attached.map((file) => file.file_id), ...workspaceFileIds])),
        messages
          .filter((message) => !message.pending && (message.role === "user" || message.role === "assistant"))
          .slice(-10)
          .map((message) => ({ role: message.role, content: message.content })),
      );
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

    // Never fall back to a fixed checklist. If contextual planning is unavailable,
    // the executing agent receives the same task context and can ask naturally only
    // when it discovers a genuinely blocking gap.
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
                onPreviewUpload={onPreviewUpload}
                onDownloadArtifact={onDownloadArtifact}
                onEditMessage={onEditMessage}
                canEdit={!busy}
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
              {busy && onStop ? (
                <button
                  onClick={onStop}
                  className={`btn-accent h-8 w-8${clarifyChecking ? "" : " ml-auto"}`}
                  aria-label={t.stopGenerating}
                  title={t.stopGenerating}
                >
                  <Square size={12} className="fill-current" />
                </button>
              ) : (
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
              )}
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
                    className="field min-w-0 flex-1 rounded-lg px-3 py-2 text-xs text-fg placeholder:text-fg-subtle"
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

// Slot-detection vocabulary for the clarification engine. One definition, used by
// isUnderSpecifiedMarketingTask, missingMarketingSlots, and analyzeMarketingPrompt —
// these three used to carry three drifting copies of the same regexes.
const SLOT_PATTERNS = {
  // Does the request even look like a content-generation ask?
  intent:
    /listing|文案|商详|详情页|落地页|社媒|推广|宣传|广告|海报|邮件|edm|脚本|短视频|博客|post|copy|caption|script|ad\b|social|blog|bullet|五点/,
  verb: /写|生成|编写|创作|出一|做|produce|write|generate|create|draft/,
  channel:
    /平台|渠道|亚马逊|amazon|asin|wayfair|overstock|独立站|自有站|官网|shopify|instagram|ins\b|meta|facebook|pinterest|tiktok|抖音|短视频|邮件|email|edm|newsletter|谷歌|google|博客|blog|listing|商详|详情页/,
  audience:
    /受众|人群|用户|客户|消费者|买家|房主|业主|租客|新房|搬家|首次|装修|设计师|美国|北美|audience|customer|homeowner|renter|buyer|persona|segment|apartment/,
  tone: /语气|语调|风格|调性|口吻|专业|温馨|亲切|真实|高级|精致|极简|中古|北欧|正式|tone|voice|style|premium|minimal|warm|professional|cozy/,
  format:
    /字数|标题|正文|五点|bullet|cta|行动号召|格式|篇幅|长度|条|篇|版本|hashtag|话题|caption|headline|body|length|format|规格单|尺寸表|spec sheet/,
  // Furniture-specific product detail: the physical attributes that decide the copy.
  product:
    /卖点|亮点|材质|实木|橡木|胡桃|松木|板式|布艺|绒|皮|金属|尺寸|规格|承重|组装|安装|配送|物流|颜色|饰面|款式|系列|品牌|产品|新品|沙发|沙发床|床架|床头|餐桌|餐椅|茶几|边柜|斗柜|书桌|衣柜|储物柜|柜子|sofa|couch|sectional|loveseat|bed\b|headboard|dining|table|chair|desk|cabinet|dresser|sideboard|nightstand|material|oak|walnut|dimension|assembly|benefit|product/,
  // Furniture nouns alone, for category detection.
  furniture:
    /沙发|床架|床头|餐桌|餐椅|茶几|边柜|斗柜|书桌|衣柜|储物柜|柜子|家具|sofa|couch|sectional|loveseat|bed frame|headboard|dining table|dining chair|coffee table|side table|desk|cabinet|dresser|sideboard|nightstand|furniture/,
} as const;

function isUnderSpecifiedMarketingTask(text: string, memory?: Partial<MarketingMemoryProfile> | null): boolean {
  const compact = text.replace(/\s+/g, "").toLowerCase();
  const normalized = text.toLowerCase();
  const isMarketingGeneration = SLOT_PATTERNS.intent.test(compact) && SLOT_PATTERNS.verb.test(compact);
  if (!isMarketingGeneration) return false;

  const remembered = memorySlots(memory);
  const effectivePlatform = SLOT_PATTERNS.channel.test(compact) || remembered.hasPlatform;
  const effectiveAudience = SLOT_PATTERNS.audience.test(compact) || remembered.hasAudience;
  const effectiveTone = SLOT_PATTERNS.tone.test(compact) || remembered.hasTone;
  const effectiveFormat = SLOT_PATTERNS.format.test(compact) || remembered.hasFormat;
  const effectiveProduct = SLOT_PATTERNS.product.test(compact) || remembered.hasProduct;
  const filledSlots = [effectivePlatform, effectiveAudience, effectiveTone, effectiveFormat, effectiveProduct].filter(Boolean).length;
  if (filledSlots < 3) return true;

  return (
    /文案|listing|copy|post|caption/.test(normalized) &&
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
  const remembered = memorySlots(memory);
  const out: string[] = [];
  if (!(SLOT_PATTERNS.channel.test(compact) || remembered.hasPlatform)) out.push(zh ? "渠道/平台" : "channel");
  if (!(SLOT_PATTERNS.product.test(compact) || remembered.hasProduct)) out.push(zh ? "产品/核心卖点" : "product/core benefit");
  if (!(SLOT_PATTERNS.audience.test(compact) || remembered.hasAudience)) out.push(zh ? "目标客户" : "target customer");
  if (!(SLOT_PATTERNS.tone.test(compact) || remembered.hasTone)) out.push(zh ? "语气/风格" : "tone/style");
  if (!(SLOT_PATTERNS.format.test(compact) || remembered.hasFormat)) out.push(zh ? "篇幅/格式/CTA" : "length/format/CTA");
  return out;
}

type MarketingChannel = "amazon" | "wayfair" | "dtc" | "instagram" | "pinterest" | "tiktok" | "email" | "other-social";

function detectMarketingPlatform(compact: string): MarketingChannel | null {
  if (/亚马逊|amazon|asin|fba/.test(compact)) return "amazon";
  if (/wayfair|overstock/.test(compact)) return "wayfair";
  if (/独立站|自有站|官网|shopify|商详|详情页|落地页|product page/.test(compact)) return "dtc";
  if (/pinterest|pin\b/.test(compact)) return "pinterest";
  if (/tiktok|抖音|短视频|视频号|reels/.test(compact)) return "tiktok";
  if (/instagram|ins\b|meta|facebook/.test(compact)) return "instagram";
  if (/邮件|email|newsletter|edm/.test(compact)) return "email";
  if (/知乎|微博|twitter|threads|youtube/.test(compact)) return "other-social";
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
  const isMarketingGeneration = SLOT_PATTERNS.intent.test(compact) && SLOT_PATTERNS.verb.test(compact);

  const remembered = memorySlots(memory);
  const platform = detectMarketingPlatform(compact) ?? remembered.platform;

  // The company sells one category, so there is one product tree rather than the
  // apparel / B2B split the generic version carried.
  const category = SLOT_PATTERNS.furniture.test(compact) ? "furniture" : "general";

  let productLabel = category === "furniture" ? "这件家具" : "这个产品";
  const productMatch =
    text.match(/(?:为|给|围绕|推广|宣传)([^，。,.!?！？\n]{2,24}?)(?:写|生成|编写|创作|做|的)/) ||
    text.match(/([^，。,.!?！？\n]{2,20}?)(?:listing|商详|详情页|营销文案|推广文案|宣传文案|广告文案)/i);
  if (productMatch?.[1]) {
    // Strip the request wrapper the capture group inevitably drags along:
    // "帮我写个沙发的推广文案" would otherwise yield the label "帮我写个沙发的".
    const cleaned = productMatch[1]
      .replace(/^(帮我|帮忙|请|麻烦|我想|我要|我们)?\s*(写|做|生成|编写|创作|出|来|搞)?\s*(一下|一个|一份|一条|个|份|条)?/, "")
      .replace(/^(公司|新推出的|推出的|这款|这张|这件|那款)/, "")
      .replace(/的$/, "")
      .trim();
    if (cleaned.length >= 2) productLabel = cleaned;
  }

  return {
    isMarketingGeneration,
    category,
    productLabel,
    hasPlatform: SLOT_PATTERNS.channel.test(compact) || remembered.hasPlatform,
    hasAudience: SLOT_PATTERNS.audience.test(compact) || remembered.hasAudience,
    hasTone: SLOT_PATTERNS.tone.test(compact) || remembered.hasTone,
    hasFormat: SLOT_PATTERNS.format.test(compact) || remembered.hasFormat,
    hasProductDetail: SLOT_PATTERNS.product.test(compact) || remembered.hasProduct,
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
  const isPlan = /策划|计划|规划|方案|上架|plan|campaign|strategy|launch/.test(compact);

  const dynamicQuestion = getInitialClarifyStep(text, locale, memory);
  if (dynamicQuestion) return dynamicQuestion.suggestions;

  const dynamicMarketing = buildDynamicMarketingEntrySuggestions(text, locale, memory);
  if (dynamicMarketing) return dynamicMarketing;

  const other = makeOtherSuggestion(locale);

  if (isAnalysis) {
    return [
      makeSuggestion(
        "competitor",
        isZh ? "竞品 Listing 对比" : "Competitor listing analysis",
        isZh ? "价格带、尺寸材质、评分与图文质量对比" : "Compare price band, specs, ratings, and listing quality",
        isZh
          ? "请按竞品分析 SOP 完成：明确对比的竞品与平台，输出价格带、尺寸与材质、配送方式、评分与评论量、listing 图文质量、退货政策的逐项对比，并给出我们的差异化机会、风险判断和下一步行动。"
          : "Use a competitive analysis SOP: define the competing brands or sellers and the marketplace, then compare price band, dimensions and materials, delivery method, rating and review volume, listing content quality, and return policy. Close with our differentiation opportunities, risks, and next actions.",
      ),
      makeSuggestion(
        "data",
        isZh ? "销售与广告数据分析" : "Sales and ad data analysis",
        isZh ? "ACOS、转化率、客单价、退货率与净贡献" : "ACOS, conversion, AOV, return rate, and net contribution",
        isZh
          ? "请按数据分析方式完成：先确认可用数据与口径，再输出分渠道/SKU 的 ACOS、转化率、客单价、退货率和扣除退货后的净 ROAS，指出异常变化与可能原因，最后给出预算与 listing 的调整建议。"
          : "Handle this as a data analysis task: confirm the available data and definitions, then report ACOS, conversion rate, AOV, return rate, and net ROAS after returns by channel or SKU. Call out anomalies and likely drivers, and close with budget and listing recommendations.",
      ),
      makeSuggestion(
        "market",
        isZh ? "美国市场与品类调研" : "US market and category research",
        isZh ? "需求趋势、风格走向、平台政策与关税" : "Demand trends, style shifts, marketplace policy, tariffs",
        isZh
          ? "请按市场调研方式完成：梳理美国家具与家居的需求趋势、品类与风格走向、主要竞争格局，以及可能影响我们的平台政策、关税或产品安全规定，标注来源并给出对选品和内容的启示。"
          : "Handle this as market research: cover US furniture and home-furnishings demand, category and style shifts, the competitive set, and any marketplace policy, tariff, or product-safety changes that could affect us. Cite sources and close with implications for assortment and content.",
      ),
      other,
    ];
  }

  if (isPlan) {
    return [
      makeSuggestion(
        "launch",
        isZh ? "新品上架战役" : "New product launch plan",
        isZh ? "打样到上架、冷启动、评论积累与广告放量" : "Sampling to listing, cold start, reviews, then scaling ads",
        isZh
          ? "请按新品上架战役完成：明确产品与目标市场，给出打样确认、首批到仓、listing 上架与冷启动、评论积累、广告放量的阶段计划，每阶段列出内容与素材需求、负责人假设和衡量指标。"
          : "Handle this as a launch plan: define the product and target market, then lay out phases from sample sign-off, first container landed, listing go-live and cold start, review accumulation, to scaling ads. For each phase give content and asset needs, owner assumptions, and measurement.",
      ),
      makeSuggestion(
        "content-calendar",
        isZh ? "内容排期" : "Content calendar",
        isZh ? "主题、渠道、频率、形式和交付清单" : "Themes, channels, cadence, formats, deliverables",
        isZh
          ? "请按内容排期完成：输出主题方向（房间场景、尺寸指南、材质工艺、组装与配送）、渠道选择、发布频率、内容形式、每条内容要点和交付清单。"
          : "Handle this as a content calendar: include themes (room scenes, sizing guides, materials and craft, assembly and delivery), channel choices, cadence, formats, per-piece angles, and deliverables.",
      ),
      other,
    ];
  }

  return [
    makeSuggestion(
      "listing-copy",
      isZh ? "平台 Listing 文案" : "Marketplace listing copy",
      isZh ? "标题、五点描述、A+ 与后台关键词" : "Title, bullets, A+ content, and backend keywords",
      isZh
        ? "请按平台 listing 任务完成：补齐产品、平台（Amazon / Wayfair）、已确认的尺寸与材质后，输出标题、五点描述、简介和后台关键词；缺失的实物参数用 [待确认 xxx] 标出，不要编造。"
        : "Handle this as a marketplace listing task: once product, marketplace (Amazon / Wayfair), and confirmed specs are known, produce title, bullets, description, and backend keywords. Mark any missing physical spec as [confirm ...] rather than inventing it.",
    ),
    makeSuggestion(
      "social-copy",
      isZh ? "社媒与房间场景内容" : "Social and room-scene content",
      isZh ? "指定渠道、客户、语气和篇幅后生成" : "Generate with channel, customer, tone, and length",
      isZh
        ? "请按社媒内容任务完成：面向美国终端消费者，补齐渠道、目标客户、房间场景、语气、篇幅和 CTA 后生成。"
        : "Handle this as a social content task: write for the US end consumer, and include channel, target customer, room scenario, tone, length, and CTA.",
    ),
    makeSuggestion(
      "report",
      isZh ? "规格单 / 报告文档" : "Spec sheet or report",
      isZh ? "输出结构化正文，可继续生成 PDF" : "Produce structured content, PDF optional",
      isZh
        ? "请按文档任务完成：先给出清晰结构，再输出完整正文（规格表、材质与工艺、配送与组装说明）、重点结论和后续可生成的交付物建议。"
        : "Handle this as a document task: provide a clear structure, then the full draft (spec table, materials and construction, delivery and assembly notes), key conclusions, and suggested follow-up deliverables.",
    ),
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

  if (profile.platform === "amazon" || profile.platform === "wayfair") {
    const isAmazon = profile.platform === "amazon";
    const channelZh = isAmazon ? "Amazon" : "Wayfair";
    return [
      makeSuggestion(
        "listing-full",
        isZh ? `${channelZh} Listing 全套` : `Full ${channelZh} listing`,
        isZh ? `围绕${product}输出标题、五点和关键词` : `Title, bullets, and keywords for ${product}`,
        isZh
          ? `方向：${channelZh} listing 全套。围绕${product}输出标题、五点描述、简介和后台关键词，其中一条专讲尺寸、一条专讲组装与配送；缺失的实物参数用 [待确认 xxx] 标出。`
          : `Direction: full ${channelZh} listing for ${product} — title, bullets, description, and backend keywords, with one bullet on dimensions and one on assembly and delivery. Mark missing specs as [confirm ...].`,
      ),
      makeSuggestion(
        "listing-bullets",
        isZh ? "只优化五点描述" : "Rewrite the bullets only",
        isZh ? "针对转化重写卖点顺序和表达" : "Reorder and sharpen the benefits for conversion",
        isZh
          ? `方向：只重写五点描述。围绕${product}按"收益先说、参数背书"的顺序重排卖点，保留尺寸与组装信息。`
          : `Direction: rewrite the bullets only. Reorder ${product}'s benefits as outcome-then-proof, keeping the dimension and assembly bullets.`,
      ),
      makeSuggestion(
        "listing-aplus",
        isZh ? "A+ / 图文详情文案" : "A+ / enhanced content",
        isZh ? "分模块讲材质、工艺、场景和尺寸" : "Modules for material, craft, room scene, and sizing",
        isZh
          ? `方向：A+ 图文详情。围绕${product}分模块输出材质与工艺、房间场景、尺寸与适配、配送与售后的文案，并标注每个模块建议配的图型。`
          : `Direction: A+ enhanced content for ${product} — modules for material and craft, room scene, sizing and fit, delivery and after-sales, each with the image type it should pair with.`,
      ),
      other,
    ];
  }

  if (profile.platform === "pinterest" || profile.platform === "instagram" || profile.platform === "tiktok") {
    return [
      makeSuggestion(
        "roomscene-social",
        isZh ? "房间场景内容" : "Room-scene content",
        isZh ? `把${product}放进真实房间里讲` : `Show ${product} as part of a real room`,
        isZh
          ? `方向：房间场景社媒内容。围绕${product}输出场景化开头、房间搭配描述、一句尺寸提示和 CTA。`
          : `Direction: room-scene social content for ${product} — scene-led opening, styling description, one sizing line, and a CTA.`,
      ),
      makeSuggestion(
        "sizing-angle",
        isZh ? "尺寸/空间适配角度" : "Fit and small-space angle",
        isZh ? "小空间、量尺寸、能不能放得下" : "Small spaces, measuring, and whether it fits",
        isZh
          ? `方向：尺寸与空间适配角度。围绕${product}讲清适合的房间尺寸、如何量、常见误判，转化到"确认能放得下"。`
          : `Direction: fit and space angle for ${product} — what room size it suits, how to measure, common mistakes, converting on "it will fit".`,
      ),
      makeSuggestion(
        "unboxing-assembly",
        isZh ? "开箱 / 组装角度" : "Unboxing and assembly angle",
        isZh ? "真实到货、拆箱、组装体验" : "Real delivery, unboxing, and assembly",
        isZh
          ? `方向：开箱与组装角度。围绕${product}呈现到货形态、拆箱、组装步骤与耗时，用真实感建立信任。`
          : `Direction: unboxing and assembly angle for ${product} — how it arrives, unboxing, assembly steps and time, building trust through honesty.`,
      ),
      other,
    ];
  }

  if (profile.platform === "email") {
    return [
      makeSuggestion(
        "email-launch",
        isZh ? "上新通知邮件" : "New arrival email",
        isZh ? `告诉订阅者${product}上线了` : `Announce ${product} to subscribers`,
        isZh
          ? `方向：上新通知邮件。围绕${product}输出主题行、预览文本、正文和单一 CTA，正文突出房间场景与一条尺寸信息。`
          : `Direction: new arrival email for ${product} — subject, preheader, body, and one CTA, leading with the room scene plus one sizing fact.`,
      ),
      makeSuggestion(
        "email-cart",
        isZh ? "弃购挽回邮件" : "Cart recovery email",
        isZh ? "用消除顾虑代替打折" : "Remove doubt instead of discounting",
        isZh
          ? `方向：弃购挽回邮件。围绕${product}针对"尺寸放不下、配送不确定、退货麻烦"三个顾虑各写一段，不以折扣为主。`
          : `Direction: cart recovery email for ${product} — one short block each for fit, delivery, and returns doubt. Do not lead with a discount.`,
      ),
      makeSuggestion(
        "email-review",
        isZh ? "售后评论邀请" : "Post-delivery review request",
        isZh ? "到货后请评价，并提供组装帮助" : "Ask for a review and offer assembly help",
        isZh
          ? `方向：售后评论邀请邮件。围绕${product}在到货后邀请评价，同时提供组装帮助和售后入口。`
          : `Direction: post-delivery review request for ${product} — ask for a review while offering assembly help and a support path.`,
      ),
      other,
    ];
  }

  if (profile.platform === "dtc") {
    return [
      makeSuggestion(
        "product-page",
        isZh ? "独立站商详页" : "Own-store product page",
        isZh ? "场景 + 材质 + 尺寸表 + FAQ" : "Scene, materials, dimensions table, FAQ",
        isZh
          ? `方向：独立站商详页。围绕${product}输出 H1、场景化开头、4-6 个卖点分段、尺寸表、材质与保养、以及覆盖适配/配送/组装/退货的 FAQ。`
          : `Direction: own-store product page for ${product} — H1, scene-led hero, 4-6 benefit sections, dimensions table, materials and care, and FAQs covering fit, delivery, assembly, and returns.`,
      ),
      makeSuggestion(
        "landing-page",
        isZh ? "系列落地页" : "Collection landing page",
        isZh ? "讲清系列定位和选购路径" : "Frame the collection and how to choose",
        isZh
          ? `方向：系列落地页。围绕${product}所在系列输出定位、风格说明、按房间/尺寸的选购路径和 CTA。`
          : `Direction: collection landing page for ${product}'s line — positioning, style story, a choose-by-room or by-size path, and CTA.`,
      ),
      makeSuggestion(
        "buying-guide",
        isZh ? "选购指南（SEO）" : "Buying guide (SEO)",
        isZh ? "回答一个具体的选购问题" : "Answer one concrete buying question",
        isZh
          ? `方向：选购指南博客。围绕${product}回答一个具体选购问题（怎么量尺寸、多大够坐几人、实木与板式怎么选），含一张对比表。`
          : `Direction: SEO buying guide answering one concrete question about ${product} (how to measure, what size seats how many, solid vs engineered wood), including a comparison table.`,
      ),
      other,
    ];
  }

  return [
    makeSuggestion(
      "listing-copy",
      isZh ? "平台 Listing 文案" : "Marketplace listing copy",
      isZh ? `为${product}写 Amazon / Wayfair listing` : `Write an Amazon / Wayfair listing for ${product}`,
      isZh
        ? `方向：平台 listing 文案。围绕${product}补齐平台、已确认的尺寸与材质后，输出标题、五点描述和关键词。`
        : `Direction: marketplace listing copy. Once the marketplace and confirmed specs for ${product} are known, produce title, bullets, and keywords.`,
    ),
    makeSuggestion(
      "roomscene-social",
      isZh ? "房间场景内容" : "Room-scene content",
      isZh ? `把${product}放进真实房间里讲` : `Show ${product} as part of a real room`,
      isZh
        ? `方向：房间场景内容。围绕${product}补齐渠道、目标客户、语气和篇幅后生成。`
        : `Direction: room-scene content for ${product}. Clarify channel, customer, tone, and length first.`,
    ),
    makeSuggestion(
      "conversion-copy",
      isZh ? "转化型文案" : "Conversion copy",
      isZh ? "突出尺寸适配、材质可信和配送确定性" : "Lead with fit, credible materials, and delivery certainty",
      isZh
        ? `方向：转化型文案。围绕${product}突出尺寸适配、材质与做工的可信理由、配送与退货的确定性。`
        : `Direction: conversion copy for ${product} — emphasize fit, credible material and construction proof, and delivery/returns certainty.`,
    ),
    other,
  ];
}

function answeredSlots(primaryId: string): Set<ClarifySlot> {
  const out = new Set<ClarifySlot>();
  if (
    primaryId.startsWith("platform-") ||
    primaryId.startsWith("listing-") ||
    primaryId.startsWith("email-") ||
    ["product-page", "landing-page", "buying-guide", "roomscene-social"].includes(primaryId)
  ) {
    out.add("platform");
  }
  if (primaryId.startsWith("audience-") || ["homeowner", "renter", "designer"].includes(primaryId)) out.add("audience");
  if (primaryId.startsWith("tone-")) out.add("tone");
  if (primaryId.startsWith("format-") || ["copy", "outline", "doc"].includes(primaryId)) out.add("format");
  if (primaryId.startsWith("product-") || ["fit", "material", "delivery", "value"].includes(primaryId)) out.add("product");
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
  const primaryAddsPlatform = answered.has("platform");

  if (!profile.hasProductDetail && !answered.has("product")) {
    steps.push({
      id: "dynamic-product",
      title: isZh ? "这次要推的是哪件产品？" : "Which product is this for?",
      body: isZh
        ? "先确认品类和阶段，后面的客户、语气和 CTA 才能贴合。尺寸和材质如果已确认，也一起告诉我。"
        : "Category and stage first, then customer, tone, and CTA can fit. If dimensions and materials are confirmed, include them.",
      suggestions: [
        makeSuggestion(
          "product-new",
          isZh ? "新品首发" : "New product launch",
          isZh ? "第一批到仓，需要冷启动" : "First container landed, needs a cold start",
          isZh ? "产品信息：新品首发，需要冷启动，突出设计与首发理由。" : "Product context: new launch needing a cold start; lead with design and reason to be first.",
        ),
        makeSuggestion(
          "product-core",
          isZh ? "在售主力款" : "Existing best-seller",
          isZh ? "已有评论和数据，重在提转化" : "Has reviews and data; optimize conversion",
          isZh ? "产品信息：在售主力款，已有评论与数据，重点提升转化。" : "Product context: existing best-seller with reviews and data; focus on lifting conversion.",
        ),
        makeSuggestion(
          "product-line",
          isZh ? "整个系列" : "A whole collection",
          isZh ? "多个 SKU 一起讲风格和搭配" : "Several SKUs, sold as a style story",
          isZh ? "产品信息：整个系列，多个 SKU 一起讲风格定位与搭配。" : "Product context: a whole collection of SKUs sold as a style and pairing story.",
        ),
        other,
      ],
    });
  }

  if (!profile.hasAudience && !answered.has("audience")) {
    steps.push({
      id: "dynamic-audience",
      title: isZh ? `${product}主要卖给谁？` : `Who is ${product} for?`,
      body: isZh ? "我会按客户情境调整卖点顺序、措辞和 CTA。" : "I will adapt the benefit order, wording, and CTA to the buying situation.",
      suggestions: [
        makeSuggestion(
          "homeowner",
          isZh ? "美国房主 · 换新升级" : "US homeowners upgrading",
          isZh ? "在意品质、耐用和整体搭配" : "Care about quality, durability, and how it fits the room",
          isZh ? "目标客户：美国房主，换掉旧家具做升级，在意品质、耐用度和整体搭配。" : "Customer: US homeowners replacing older furniture; they care about quality, durability, and how it fits the room.",
        ),
        makeSuggestion(
          "renter",
          isZh ? "租客 · 小空间" : "Renters in small spaces",
          isZh ? "在意尺寸、搬运和不留痕" : "Care about size, moving it, and not damaging the place",
          isZh ? "目标客户：美国租客，房间偏小，在意尺寸适配、搬运方便和易组装拆卸。" : "Customer: US renters with limited space; they care about fit, ease of moving, and simple assembly.",
        ),
        makeSuggestion(
          "firsthome",
          isZh ? "首次置业 · 新居入住" : "First-time buyers furnishing",
          isZh ? "一次要买多件，在意性价比和成套感" : "Buying several pieces at once; value and coherence matter",
          isZh ? "目标客户：首次置业或刚入住新居，一次采购多件，在意性价比和成套搭配。" : "Customer: first-time buyers furnishing a new place; buying several pieces, so value and a coherent look matter.",
        ),
        makeSuggestion(
          "designer",
          isZh ? "设计爱好者" : "Design-minded shoppers",
          isZh ? "看风格、材质和细节工艺" : "Judge style, material, and construction detail",
          isZh ? "目标客户：设计爱好者，关注风格准确性、材质真实性和细节工艺。" : "Customer: design-minded shoppers who judge style accuracy, honest materials, and construction detail.",
        ),
        other,
      ],
    });
  }

  if (!profile.hasPlatform && !primaryAddsPlatform && !answered.has("platform")) {
    steps.push({
      id: "dynamic-platform",
      title: isZh ? "这条内容发在哪里？" : "Where will this be published?",
      body: isZh ? "渠道决定开头钩子、篇幅、合规限制和信息密度。" : "The channel drives the hook, length, policy limits, and information density.",
      suggestions: [
        makeSuggestion(
          "platform-amazon",
          "Amazon",
          isZh ? "搜索驱动，合规限制严，尺寸要写清" : "Search-driven, strict policy, dimensions must be explicit",
          isZh ? "发布渠道：Amazon listing，按搜索意图组织，遵守平台文案规范，必须写清尺寸与组装。" : "Channel: Amazon listing — organize around search intent, follow marketplace copy policy, and state dimensions and assembly explicitly.",
        ),
        makeSuggestion(
          "platform-wayfair",
          "Wayfair",
          isZh ? "属性表要齐全，风格标签要对" : "Attribute grid must be complete; style tags matter",
          isZh ? "发布渠道：Wayfair listing，属性表齐全，风格标签贴合平台筛选项，写清配送方式与箱数。" : "Channel: Wayfair listing — complete the attribute grid, match the site's style filters, and state delivery method and carton count.",
        ),
        makeSuggestion(
          "platform-social",
          isZh ? "Instagram / Pinterest" : "Instagram / Pinterest",
          isZh ? "卖房间氛围，尺寸只点一句" : "Sell the room; mention size once",
          isZh ? "发布渠道：Instagram / Pinterest，以房间实景和风格为主，尺寸信息点一句即可。" : "Channel: Instagram / Pinterest — lead with the room set and style, with a single sizing line.",
        ),
        makeSuggestion(
          "platform-dtc",
          isZh ? "独立站" : "Own store",
          isZh ? "可以更长，要覆盖 FAQ 和退换" : "Can run longer; must cover FAQs and returns",
          isZh ? "发布渠道：自有独立站，可写更长，覆盖尺寸表、材质保养和适配/配送/组装/退货 FAQ。" : "Channel: own store — longer copy is fine; cover the dimensions table, materials and care, and fit/delivery/assembly/returns FAQs.",
        ),
        other,
      ],
    });
  }

  if (!profile.hasProductDetail && !answered.has("product") && steps.length < 3) {
    steps.push({
      id: "dynamic-selling-point",
      title: isZh ? "最该突出哪个卖点？" : "Which benefit should lead?",
      body: isZh ? "卖点决定主钩子和正文展开顺序。" : "The lead benefit determines the hook and body order.",
      suggestions: [
        makeSuggestion(
          "fit",
          isZh ? "尺寸与空间适配" : "Fit and footprint",
          isZh ? "小空间也放得下，附量法" : "Works in tight rooms; include how to measure",
          isZh ? "核心卖点：尺寸与空间适配，说明适合的房间尺寸并给出量法。" : "Lead benefit: fit and footprint — what room size it suits and how to measure.",
        ),
        makeSuggestion(
          "material",
          isZh ? "材质与做工" : "Material and construction",
          isZh ? "实木、面料、结构与耐用度" : "Solid wood, fabric, joinery, and durability",
          isZh ? "核心卖点：材质与做工，突出用料、结构工艺和耐用度证据。" : "Lead benefit: material and construction — the materials, joinery, and evidence of durability.",
        ),
        makeSuggestion(
          "delivery",
          isZh ? "配送与组装" : "Delivery and assembly",
          isZh ? "怎么送到、几箱、多久装好" : "How it ships, carton count, assembly time",
          isZh ? "核心卖点：配送与组装，写清配送方式、箱数和组装耗时。" : "Lead benefit: delivery and assembly — shipping method, carton count, and assembly time.",
        ),
        makeSuggestion(
          "value",
          isZh ? "价格与价值感" : "Price and value",
          isZh ? "同价位里为什么更值" : "Why it beats others in the same price band",
          isZh ? "核心卖点：价格与价值感，说明同价位区间内为什么更值得买。" : "Lead benefit: price and value — why it wins inside its price band.",
        ),
        other,
      ],
    });
  }

  if (!profile.hasTone && !answered.has("tone")) {
    steps.push({
      id: "dynamic-tone",
      title: isZh ? "想要什么语气和风格？" : "What tone should it use?",
      body: isZh ? "语气影响标题钩子、情绪浓度和销售感强弱。" : "Tone changes the hook, emotional intensity, and how salesy it feels.",
      suggestions: [
        makeSuggestion(
          "tone-warm",
          isZh ? "温暖真实" : "Warm and honest",
          isZh ? "像懂行的朋友在讲，不夸大" : "Like a knowledgeable friend, no overclaiming",
          isZh ? "语气风格：温暖真实，像懂行的朋友在讲，不夸大。" : "Tone: warm and honest, like a knowledgeable friend, without overclaiming.",
        ),
        makeSuggestion(
          "tone-refined",
          isZh ? "克制精致" : "Refined and restrained",
          isZh ? "少形容词，突出材质与工艺" : "Fewer adjectives, more material and craft",
          isZh ? "语气风格：克制精致，少用形容词，突出材质与工艺细节。" : "Tone: refined and restrained — fewer adjectives, more material and craft detail.",
        ),
        makeSuggestion(
          "tone-practical",
          isZh ? "务实清晰" : "Practical and clear",
          isZh ? "直接给参数和结论，便于比较" : "Lead with specs and conclusions for easy comparison",
          isZh ? "语气风格：务实清晰，直接给参数和结论，方便买家比较。" : "Tone: practical and clear — specs and conclusions up front so buyers can compare.",
        ),
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
        makeSuggestion(
          "format-one",
          isZh ? "1 份可直接用" : "One ready-to-use piece",
          isZh ? "直接贴到平台或站点上" : "Paste straight into the marketplace or site",
          isZh ? "交付形式：1 份可直接使用的成稿。" : "Deliverable: one ready-to-use draft.",
        ),
        makeSuggestion(
          "format-three",
          isZh ? "3 个不同角度版本" : "Three angle variants",
          isZh ? "便于 A/B 测试标题或钩子" : "For A/B testing titles or hooks",
          isZh ? "交付形式：3 个不同角度版本，便于 A/B 测试。" : "Deliverable: three angle variants for A/B testing.",
        ),
        makeSuggestion(
          "format-doc",
          isZh ? "规格单 / PDF" : "Spec sheet / PDF",
          isZh ? "含尺寸表和材质说明的文档" : "A document with a dimensions table and materials",
          isZh ? "交付形式：规格单或 PDF 文档，含尺寸表与材质说明。" : "Deliverable: a spec sheet or PDF with a dimensions table and materials.",
        ),
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
        title: isZh ? "先确定对比范围" : "Define the comparison set",
        body: isZh ? "你希望我围绕哪类竞品展开？选择一个最贴近的范围。" : "Which competitor scope should I use? Pick the closest option.",
        suggestions: [
          makeSuggestion("direct", isZh ? "同品类同价位" : "Same category, same price band", isZh ? "逐项对比同类家具" : "Compare comparable pieces item by item", isZh ? "对比范围：同品类同价位的竞品，逐项比较尺寸、材质、价格和评价。" : "Scope: same category and price band; compare dimensions, materials, price, and ratings item by item."),
          makeSuggestion("marketplace", isZh ? "平台头部卖家" : "Top marketplace sellers", isZh ? "Amazon / Wayfair 上的畅销 listing" : "Best-selling listings on Amazon or Wayfair", isZh ? "对比范围：Amazon / Wayfair 上同品类的头部 listing，关注图文结构与评论。" : "Scope: top same-category listings on Amazon or Wayfair, focusing on listing structure and reviews."),
          makeSuggestion("dtcbrand", isZh ? "DTC 品牌" : "DTC brands", isZh ? "Article、Castlery 这类独立站品牌" : "Own-store brands like Article or Castlery", isZh ? "对比范围：面向美国市场的家具 DTC 品牌，关注品牌叙事、定价与配送承诺。" : "Scope: US-facing furniture DTC brands; focus on brand story, pricing, and delivery promises."),
          other,
        ],
      },
      {
        id: "competitor-output",
        title: isZh ? "你更需要哪种产出？" : "What output do you need?",
        body: isZh ? "不同产出会影响分析颗粒度和表达方式。" : "The deliverable changes the depth and wording of the analysis.",
        suggestions: [
          makeSuggestion("listing-gap", isZh ? "Listing 差距清单" : "Listing gap list", isZh ? "我们的 listing 缺什么、该补什么" : "What our listing is missing and what to add", isZh ? "交付形式：listing 差距清单，逐项指出我们的标题、五点、图片和属性缺什么。" : "Output: a listing gap list naming what our title, bullets, images, and attributes are missing."),
          makeSuggestion("brief", isZh ? "定位简报" : "Positioning brief", isZh ? "用于内部判断选品和定价" : "For internal assortment and pricing decisions", isZh ? "交付形式：定位简报，强调竞争格局、价格带机会和差异化方向。" : "Output: positioning brief covering the landscape, price-band opportunities, and differentiation."),
          makeSuggestion("content", isZh ? "内容角度素材" : "Content angles", isZh ? "转化成可发布的选题" : "Turn the analysis into publishable topics", isZh ? "交付形式：内容角度素材，输出可发布的选题和卖点表达。" : "Output: content angles and publishable topics drawn from the analysis."),
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
          makeSuggestion("ads", isZh ? "广告与销售数据" : "Ad and sales data", isZh ? "关注 ACOS、转化和客单价" : "Focus on ACOS, conversion, and AOV", isZh ? "数据来源：广告与销售数据，重点关注 ACOS、转化率和客单价。" : "Data source: ad and sales data; focus on ACOS, conversion rate, and AOV."),
          makeSuggestion("returns", isZh ? "退货与评论数据" : "Returns and review data", isZh ? "关注退货率、原因和评分" : "Focus on return rate, reasons, and ratings", isZh ? "数据来源：退货与评论数据，重点关注退货率、退货原因和评分变化。" : "Data source: returns and review data; focus on return rate, reasons, and rating shifts."),
          other,
        ],
      },
      {
        id: "data-goal",
        title: isZh ? "最想回答什么问题？" : "What question should it answer?",
        body: isZh ? "选一个分析目标，我会据此组织指标和结论。" : "Pick an analysis goal so I can structure metrics and findings.",
        suggestions: [
          makeSuggestion("why", isZh ? "为什么变化" : "Why it changed", isZh ? "寻找涨跌原因和影响因素" : "Find drivers of movement", isZh ? "分析目标：解释指标变化原因和影响因素。" : "Analysis goal: explain metric movement and drivers."),
          makeSuggestion("profitable", isZh ? "哪个渠道真赚钱" : "Which channel actually earns", isZh ? "扣掉退货和运费后再排序" : "Rank after returns and freight", isZh ? "分析目标：扣除退货和运费后，比较各渠道/SKU 的真实贡献并排序。" : "Analysis goal: compare true contribution by channel or SKU after returns and freight, then rank."),
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
        body: isZh ? "先定目标，后续渠道、内容和指标才能对齐。" : "Goal first, then channels, content, and metrics can align.",
        suggestions: [
          makeSuggestion("coldstart", isZh ? "新品冷启动" : "Cold-start a new SKU", isZh ? "拿到前几十个订单和首批评论" : "Get the first orders and first reviews", isZh ? "核心目标：新品冷启动，拿到首批订单和评论。" : "Core goal: cold-start a new SKU — first orders and first reviews."),
          makeSuggestion("scale", isZh ? "放量增长" : "Scale volume", isZh ? "在可接受 ACOS 下扩大销量" : "Grow orders at an acceptable ACOS", isZh ? "核心目标：放量增长，在可接受的 ACOS 下扩大销量。" : "Core goal: scale volume while holding ACOS acceptable."),
          makeSuggestion("margin", isZh ? "改善利润" : "Improve margin", isZh ? "降退货、提客单价、减广告依赖" : "Cut returns, lift AOV, reduce ad dependence", isZh ? "核心目标：改善利润，降低退货率、提升客单价、减少对广告的依赖。" : "Core goal: improve margin — cut returns, lift AOV, reduce ad dependence."),
          other,
        ],
      },
      {
        id: "plan-channel",
        title: isZh ? "优先面向哪个渠道？" : "Which channel is primary?",
        body: isZh ? "选择主渠道后，我会匹配内容形式和节奏。" : "With a primary channel, I can match formats and cadence.",
        suggestions: [
          makeSuggestion("marketplace", isZh ? "平台（Amazon / Wayfair）" : "Marketplaces (Amazon / Wayfair)", isZh ? "listing、广告和评论为主" : "Listings, ads, and reviews", isZh ? "主渠道：Amazon / Wayfair，围绕 listing 优化、广告结构和评论积累组织。" : "Primary channel: Amazon / Wayfair — organize around listing optimization, ad structure, and review accumulation."),
          makeSuggestion("owned", isZh ? "独立站 + 邮件" : "Own store + email", isZh ? "商详、落地页和生命周期邮件" : "Product pages, landing pages, lifecycle email", isZh ? "主渠道：自有独立站与邮件，围绕商详、落地页和生命周期邮件组织。" : "Primary channel: own store and email — product pages, landing pages, and lifecycle email."),
          makeSuggestion("social", isZh ? "社媒（IG / Pinterest / TikTok）" : "Social (IG / Pinterest / TikTok)", isZh ? "房间实景内容拉新" : "Room-scene content for discovery", isZh ? "主渠道：Instagram / Pinterest / TikTok，围绕房间实景内容拉新。" : "Primary channel: Instagram / Pinterest / TikTok — room-scene content for discovery."),
          makeSuggestion("multi", isZh ? "多渠道整合" : "Integrated channels", isZh ? "分阶段组合平台与自有渠道" : "Sequence marketplace and owned channels", isZh ? "主渠道：多渠道整合，按阶段组合平台与自有渠道。" : "Primary channel: integrated — sequence marketplace and owned channels by phase."),
          other,
        ],
      },
    ];
  }

  return [
    {
      id: "generic-target",
      title: isZh ? "目标客户是谁？" : "Who is the customer?",
      body: isZh ? "先确定对象，生成内容才会更贴近真实场景。" : "Define the customer so the output fits the actual situation.",
      suggestions: [
        makeSuggestion("homeowner", isZh ? "美国房主" : "US homeowners", isZh ? "换新升级，在意品质和搭配" : "Upgrading; quality and coherence matter", isZh ? "目标客户：美国房主，换新升级，在意品质和整体搭配。" : "Customer: US homeowners upgrading; quality and a coherent look matter."),
        makeSuggestion("renter", isZh ? "租客 / 小空间" : "Renters / small spaces", isZh ? "在意尺寸、搬运和组装" : "Size, moving, and assembly matter", isZh ? "目标客户：租客或小空间用户，在意尺寸适配、搬运和组装。" : "Customer: renters or small-space buyers; fit, moving, and assembly matter."),
        makeSuggestion("firsthome", isZh ? "首次置业" : "First-time buyers", isZh ? "一次买多件，在意性价比" : "Buying several pieces; value matters", isZh ? "目标客户：首次置业人群，一次采购多件，在意性价比和成套感。" : "Customer: first-time buyers purchasing several pieces; value and coherence matter."),
        other,
      ],
    },
    {
      id: "generic-format",
      title: isZh ? "希望最终是什么形式？" : "What final format do you want?",
      body: isZh ? "选择交付形式后，我会按对应结构输出。" : "Choose the deliverable so I can use the right structure.",
      suggestions: [
        makeSuggestion("copy", isZh ? "可直接用的文案" : "Ready-to-use copy", isZh ? "listing、商详或社媒成稿" : "A listing, product page, or social draft", isZh ? "交付形式：可直接使用的文案成稿。" : "Format: ready-to-use copy."),
        makeSuggestion("outline", isZh ? "结构化方案" : "Structured plan", isZh ? "分模块给出策略和步骤" : "Modular strategy and steps", isZh ? "交付形式：结构化方案，分模块给出策略和步骤。" : "Format: structured plan with modules and steps."),
        makeSuggestion("doc", isZh ? "完整文档 / PDF" : "Full document / PDF", isZh ? "规格单、目录或对比报告" : "Spec sheet, catalog page, or comparison report", isZh ? "交付形式：完整文档，可沉淀成规格单、目录或对比报告。" : "Format: a full document — spec sheet, catalog page, or comparison report."),
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
  const taskNoun = /listing|文案|商详|详情页|落地页|营销|推广|宣传|广告|社媒|短视频|邮件|上架|活动|报告|方案|规格|尺寸|材质|退货|竞品|brief|post|copy|campaign|report|email|social|amazon|wayfair|pinterest/i;
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
            ? "选择一个业务 SOP，生成内容时会按对应流程执行。"
            : "Pick a business SOP to guide the response workflow."}
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
      name: "竞品 Listing 对比简报",
      description: "用于对比同品类竞品或平台头部 listing：价格带、尺寸与材质、配送方式、评分与评论、图文质量、退货政策，输出差异化机会与 PDF 简报。",
    },
    "product-launch-campaign": {
      name: "新品上架战役",
      description: "用于新品从打样确认到上架放量：分阶段拆解首批到仓、listing 冷启动、评论积累、广告放量，并给出各阶段素材需求与衡量指标。",
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
