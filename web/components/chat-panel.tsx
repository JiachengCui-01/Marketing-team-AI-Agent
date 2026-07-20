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
import { getWorkflowSkills, uploadFile, type UploadResponse, type WorkflowSkill } from "@/lib/api";
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
      };

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    getWorkflowSkills().then(setSkills).catch(() => setSkills([]));
  }, []);

  const empty = messages.length === 0;
  const selectedSkills = skills.filter((skill) => selectedSkillIds.includes(skill.id));
  const clarifySuggestions = getClarifySuggestions(input, locale);

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

  function submitWithClarifyCheck() {
    const text = input.trim();
    if (!text || busy) return;
    if (looksAmbiguous(text) && !clarifyOpen) {
      setClarifyOpen(true);
      setClarifyCustom(false);
      setClarifyDraft("");
      return;
    }
    if (looksAmbiguous(text) && clarifyOpen) return;
    onSend(text);
    setClarifyDraft("");
    setClarifyOpen(false);
    setClarifyCustom(false);
  }

  function sendClarified(detail: string) {
    const text = input.trim();
    const extra = detail.trim();
    const prefix = locale === "zh" ? "补充信息" : "Additional context";
    onSend(extra ? `${text}\n\n${prefix}: ${extra}` : text);
    setClarifyDraft("");
    setClarifyOpen(false);
    setClarifyCustom(false);
  }

  function chooseClarifySuggestion(suggestion: ClarifySuggestion) {
    if (suggestion.custom) {
      setClarifyCustom(true);
      return;
    }
    sendClarified(suggestion.detail);
  }

  function closeClarify() {
    setClarifyOpen(false);
    setClarifyCustom(false);
    setClarifyDraft("");
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
              title={copy.clarifyTitle}
              body={copy.clarifyBody}
              placeholder={copy.clarifyPlaceholder}
              continueLabel={copy.continueSend}
              cancelLabel={t.cancel}
              suggestions={clarifySuggestions}
              customOpen={clarifyCustom}
              customDraft={clarifyDraft}
              busy={busy}
              onChoose={chooseClarifySuggestion}
              onDraftChange={setClarifyDraft}
              onCustomSubmit={() => sendClarified(clarifyDraft)}
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
              <button
                onClick={submitWithClarifyCheck}
                disabled={busy || !input.trim()}
                className="btn-accent ml-auto h-8 w-8 disabled:cursor-not-allowed"
                aria-label={t.send}
              >
                {busy ? (
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
  cancelLabel,
  suggestions,
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
  cancelLabel: string;
  suggestions: ClarifySuggestion[];
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
          </div>
          <p className="mt-1 text-xs leading-relaxed text-fg-muted">{body}</p>
        </div>
        <button type="button" onClick={onClose} className="btn-ghost h-7 w-7 shrink-0" aria-label={cancelLabel}>
          <X size={14} />
        </button>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion.id}
            type="button"
            onClick={() => onChoose(suggestion)}
            disabled={busy}
            className={`clarify-choice ${suggestion.custom && customOpen ? "clarify-choice-active" : ""}`}
          >
            <span className="block text-xs font-semibold text-fg">{suggestion.title}</span>
            <span className="mt-0.5 block text-[11px] leading-snug text-fg-muted">
              {suggestion.description}
            </span>
          </button>
        ))}
      </div>
      {customOpen ? (
        <div className="mt-3 rounded-xl border border-border/70 bg-bg-elevated/65 p-2">
          <textarea
            value={customDraft}
            onChange={(e) => onDraftChange(e.target.value)}
            placeholder={placeholder}
            className="min-h-20 w-full resize-none rounded-lg border border-border bg-bg/80 px-3 py-2 text-sm text-fg placeholder:text-fg-subtle focus:outline-none focus:ring-2 focus:ring-accent/25"
          />
          <div className="mt-2 flex justify-end gap-2">
            <button type="button" onClick={onClose} className="btn-ghost px-3 py-2 text-xs">
              {cancelLabel}
            </button>
            <button
              type="button"
              onClick={onCustomSubmit}
              disabled={busy || !customDraft.trim()}
              className="btn-accent px-3 py-2 text-xs disabled:cursor-not-allowed"
            >
              {continueLabel}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function looksAmbiguous(text: string): boolean {
  const compact = text.replace(/\s+/g, "");
  const broad = /^(帮我)?(写|做|生成|分析|总结|策划|优化)(一下|一个|一份)?[。.!！?？]*$/;
  const englishBroad = /^(write|make|generate|analyze|summarize|plan|optimize)(\s+it|\s+this)?[.!?]*$/i;
  return compact.length <= 8 || broad.test(compact) || englishBroad.test(text.trim());
}

function getClarifySuggestions(text: string, locale: "zh" | "en"): ClarifySuggestion[] {
  const compact = text.replace(/\s+/g, "").toLowerCase();
  const isZh = locale === "zh";
  const isAnalysis = /分析|总结|复盘|analy[sz]e|summari[sz]e|review/.test(compact);
  const isPlan = /策划|计划|规划|方案|plan|campaign|strategy/.test(compact);

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
