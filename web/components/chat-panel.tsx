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

type ClarifyStep = {
  id: string;
  title: string;
  body: string;
  suggestions: ClarifySuggestion[];
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
  const [clarifyPrimary, setClarifyPrimary] = useState<ClarifySuggestion | null>(null);
  const [clarifySelections, setClarifySelections] = useState<ClarifySuggestion[]>([]);
  const [clarifyStepIndex, setClarifyStepIndex] = useState(0);
  const [clarifyReady, setClarifyReady] = useState(false);
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
  const clarifySteps = clarifyPrimary ? getClarifyFollowupSteps(clarifyPrimary.id, locale) : [];
  const clarifyCurrentStep = clarifyPrimary ? clarifySteps[clarifyStepIndex] : null;
  const clarifySuggestions = clarifyReady
    ? getClarifyFinalSuggestions(locale)
    : clarifyCurrentStep?.suggestions ?? getClarifySuggestions(input, locale);
  const clarifyTitle = clarifyReady
    ? locale === "zh" ? "信息基本完备" : "Ready to proceed"
    : clarifyCurrentStep?.title ?? copy.clarifyTitle;
  const clarifyBody = clarifyReady
    ? locale === "zh"
      ? "我已经获得了足够的信息，可以开始执行。你也可以继续补充其它要求后再执行。"
      : "I have enough context to proceed. You can also add more requirements before starting."
    : clarifyCurrentStep?.body ?? copy.clarifyBody;

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
      setClarifyPrimary(null);
      setClarifySelections([]);
      setClarifyStepIndex(0);
      setClarifyReady(false);
      return;
    }
    if (looksAmbiguous(text) && clarifyOpen) return;
    onSend(text);
    resetClarify();
  }

  function resetClarify() {
    setClarifyDraft("");
    setClarifyOpen(false);
    setClarifyCustom(false);
    setClarifyPrimary(null);
    setClarifySelections([]);
    setClarifyStepIndex(0);
    setClarifyReady(false);
  }

  function sendClarified(detail: string) {
    const text = input.trim();
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

    if (!clarifyPrimary) {
      const steps = getClarifyFollowupSteps(suggestion.id, locale);
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
    const customSuggestion: ClarifySuggestion = {
      id: `custom-${Date.now()}`,
      title: locale === "zh" ? "其它补充" : "Other context",
      description: extra,
      detail: extra,
    };

    if (clarifyReady) {
      sendClarified(extra);
      return;
    }

    if (!clarifyPrimary) {
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
              stepLabel={getClarifyStepLabel(clarifyPrimary, clarifyStepIndex, clarifySteps.length, locale)}
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

function getClarifyFollowupSteps(primaryId: string, locale: "zh" | "en"): ClarifyStep[] {
  const isZh = locale === "zh";
  const other = makeOtherSuggestion(locale);

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
