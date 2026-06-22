"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

export type Locale = "zh" | "en";

const LOCALE_KEY = "marketing-agent-locale";

type I18nContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (typeof messages)[Locale];
};

const messages = {
  zh: {
    language: "语言",
    chinese: "中文",
    english: "English",
    appName: "Marketing Agent",
    authSubtitle: "账号工作区",
    loadingAccount: "正在加载账号...",
    accountLabel: "账号",
    account: "邮箱或手机号",
    password: "密码",
    passwordInput: "请输入密码",
    rememberMe: "记住我",
    login: "登录",
    loggingIn: "登录中...",
    registerAccount: "注册账号",
    deleteRememberedTitle: "删除记住的登录账号",
    deleteRememberedBody: (account: string) => `仅从当前设备删除 ${account} 的记住记录，数据库账号不会被删除。`,
    deleteRememberedShortBody: (account: string) => `仅从当前设备删除 ${account} 的记住记录。`,
    rememberedPasswordExpired: "本机保存的快捷登录密码已失效，请重新输入密码登录一次。",
    delete: "删除",
    registerTitle: "注册账号",
    requiredHint: "带 * 的项目为必填。",
    accountRequired: "账号 *",
    passwordRequired: "密码 *",
    passwordHint: "至少 8 位",
    usernameRequired: "用户名 *",
    usernameHint: "展示名称",
    realNameRequired: "真实姓名 *",
    realNameHint: "实名姓名",
    idCardRequired: "身份证号 *",
    idCardHint: "18 位身份证号",
    idCardError: "身份证号格式或校验位不正确",
    phone: "手机号",
    phoneHint: "11 位手机号",
    email: "邮箱",
    emailHint: "name@example.com",
    company: "公司",
    companyHint: "公司名称",
    title: "职位",
    titleHint: "职位名称",
    bio: "简介",
    bioHint: "简单介绍",
    backToLogin: "返回登录",
    submitting: "提交中...",
    finishRegister: "完成注册",
    settings: "设置",
    switchAccount: "切换账号",
    profile: "个人信息",
    subscription: "订阅套餐",
    help: "帮助",
    logout: "退出登录",
    deleteAccount: "注销账号",
    placeholderBody: (title: string) => `${title}功能入口已预留，后续可在这里接入完整业务内容。`,
    close: "关闭",
    noRememberedAccounts: "当前设备暂无记住的登录账号。",
    deleteRememberedRecord: "删除记住记录",
    loginAccount: "登录账号",
    realName: "实名",
    idCard: "身份证",
    changePassword: "修改密码",
    keepBlankPassword: "留空则不修改",
    cancel: "取消",
    saving: "保存中...",
    save: "保存",
    deleteAccountNotice: "注销后会删除该账号和所有会话、上传文件、生成材料，且无法恢复。",
    deleteAccountConfirmLabel: "请输入：我确认注销账号",
    deleteAccountConfirmText: "我确认注销账号",
    confirmDeleteAccount: "确认注销",
    setAvatar: "设置头像",
    useDefaultAvatar: "使用默认头像",
    ok: "知道了",
    chooseRememberedAccount: "选择记住的登录账号",
    navSubtitle: "内容 · 分析 · 研究",
    newChat: "新对话",
    newGroup: "新分组",
    collapseSidebar: "收起侧栏",
    expandSidebar: "展开侧栏",
    noChats: "还没有对话。点击“新对话”开始。",
    ungrouped: "未分组",
    rename: "重命名",
    moveToGroup: "移动到分组",
    deleteChat: "删除",
    deleteChatConfirm: "删除这个对话？此操作无法撤销。",
    groupNamePrompt: "分组名称：",
    renameChatPrompt: "重命名对话：",
    renameGroup: "重命名分组",
    renameGroupPrompt: "重命名分组：",
    deleteGroup: "删除分组和其中对话",
    deleteGroupConfirm: "删除这个分组和其中所有对话？此操作无法撤销。",
    heroTitle: "你的营销团队 AI 助手",
    heroBody: "询问内容创作、活动分析或竞品研究。系统会分配给专门智能体并汇总结果。",
    inputPlaceholder: "向营销团队提问...（Enter 发送，Shift+Enter 换行）",
    send: "发送",
    attachFiles: "添加文件",
    uploading: "上传中...",
    fileTypes: "CSV · PDF · Word · PNG/JPG",
    removeFile: "移除文件",
    draftContent: "撰写内容",
    draftContentPrompt: "写 3 条自信的 LinkedIn 帖子，介绍我们的 AI 活动分析新功能。",
    analyzeData: "分析活动数据",
    analyzeDataPrompt: "分析上周活动表现，并告诉我哪些渠道值得加大投入。",
    researchCompetitors: "研究竞品",
    researchCompetitorsPrompt: "HubSpot 和 Marketo 最近发布了什么？总结它们的定位变化。",
    needsCsv: "需要附加 CSV",
    preview: "预览",
    trace: "追踪",
    live: "实时",
    noPreview: "无预览",
    expandPreview: "展开预览面板",
    collapsePreview: "收起预览面板",
    previewEmptyTitle: "生成的 PDF 和上传文件会显示在这里。",
    previewEmptyBody: "请求 PDF 交付物后，可以在这里预览并下载。",
    download: "下载",
    noInlinePreview: "此文件类型无法在线预览，请下载查看。",
    csvLoading: "加载中...",
    csvTruncated: "预览仅显示前 50 行。",
    traceEmpty: "智能体活动会实时显示在这里。",
    tokensIn: "输入 token",
    tokensOut: "输出 token",
    connected: "已连接。",
    startingWork: "开始处理...",
    delegating: "分配给",
    contentAgent: "内容智能体",
    analyticsAgent: "分析智能体",
    researchAgent: "研究智能体",
    specialistReturned: "已返回",
    specialistFailed: "执行失败",
    specialist: "智能体",
    synthesizing: "正在汇总回复...",
    generating: "正在生成",
    thinking: "思考中...",
    chars: "字符",
    orchestrator: "编排器",
    tokensShortIn: "输入",
    tokensShortOut: "输出",
    error: "错误",
    failedToStartSession: "无法开始会话",
    noTextReturned: "未返回文本。",
    noMessageReturned: "未返回消息。",
    connectionClosed: "连接已关闭。",
    streamCancelled: "流式连接已取消",
    artifactReady: "材料已生成",
    themeToggle: "切换主题",
    userAvatar: "用户头像",
    resizePanel: (side: string) => `调整${side === "left" ? "左侧" : "右侧"}面板宽度`,
  },
  en: {
    language: "Language",
    chinese: "中文",
    english: "English",
    appName: "Marketing Agent",
    authSubtitle: "Account workspace",
    loadingAccount: "Loading account...",
    accountLabel: "Account",
    account: "Email or phone",
    password: "Password",
    passwordInput: "Enter password",
    rememberMe: "Remember me",
    login: "Log in",
    loggingIn: "Logging in...",
    registerAccount: "Create account",
    deleteRememberedTitle: "Remove remembered account",
    deleteRememberedBody: (account: string) => `Remove ${account} from this device only. The database account will remain.`,
    deleteRememberedShortBody: (account: string) => `Remove ${account} from this device only.`,
    rememberedPasswordExpired: "The saved quick-login password on this device has expired. Please enter the password once.",
    delete: "Remove",
    registerTitle: "Create account",
    requiredHint: "Fields marked with * are required.",
    accountRequired: "Account *",
    passwordRequired: "Password *",
    passwordHint: "At least 8 chars",
    usernameRequired: "Username *",
    usernameHint: "Display name",
    realNameRequired: "Legal name *",
    realNameHint: "Legal name",
    idCardRequired: "Chinese ID *",
    idCardHint: "18-digit ID",
    idCardError: "Invalid ID format or checksum",
    phone: "Phone",
    phoneHint: "11-digit phone",
    email: "Email",
    emailHint: "name@example.com",
    company: "Company",
    companyHint: "Company name",
    title: "Title",
    titleHint: "Job title",
    bio: "Bio",
    bioHint: "Short bio",
    backToLogin: "Back to login",
    submitting: "Submitting...",
    finishRegister: "Create account",
    settings: "Settings",
    switchAccount: "Switch account",
    profile: "Profile",
    subscription: "Subscription",
    help: "Help",
    logout: "Log out",
    deleteAccount: "Delete account",
    placeholderBody: (title: string) => `${title} is reserved and can be connected to full business content later.`,
    close: "Close",
    noRememberedAccounts: "No remembered accounts on this device.",
    deleteRememberedRecord: "Remove remembered record",
    loginAccount: "Login account",
    realName: "Legal name",
    idCard: "ID card",
    changePassword: "Change password",
    keepBlankPassword: "Leave blank to keep",
    cancel: "Cancel",
    saving: "Saving...",
    save: "Save",
    deleteAccountNotice: "Deleting the account removes all chats, uploads, and generated materials. This cannot be undone.",
    deleteAccountConfirmLabel: "Type: I confirm account deletion",
    deleteAccountConfirmText: "I confirm account deletion",
    confirmDeleteAccount: "Delete account",
    setAvatar: "Set avatar",
    useDefaultAvatar: "Use default avatar",
    ok: "OK",
    chooseRememberedAccount: "Choose remembered account",
    navSubtitle: "Content · Analytics · Research",
    newChat: "New chat",
    newGroup: "New group",
    collapseSidebar: "Collapse sidebar",
    expandSidebar: "Expand sidebar",
    noChats: "No chats yet. Start one with “New chat”.",
    ungrouped: "Ungrouped",
    rename: "Rename",
    moveToGroup: "Move to group",
    deleteChat: "Delete",
    deleteChatConfirm: "Delete this chat? This cannot be undone.",
    groupNamePrompt: "Group name:",
    renameChatPrompt: "Rename chat:",
    renameGroup: "Rename group",
    renameGroupPrompt: "Rename group:",
    deleteGroup: "Delete group and chats",
    deleteGroupConfirm: "Delete this group and all chats inside it? This cannot be undone.",
    heroTitle: "Your marketing team's AI copilot",
    heroBody: "Ask for content, campaign analysis, or competitor research. The system routes work to specialists and synthesizes the result.",
    inputPlaceholder: "Ask the marketing team anything... (Enter to send, Shift+Enter for newline)",
    send: "Send",
    attachFiles: "Attach files",
    uploading: "Uploading...",
    fileTypes: "CSV · PDF · Word · PNG/JPG",
    removeFile: "Remove file",
    draftContent: "Draft content",
    draftContentPrompt: "Write 3 confident LinkedIn posts announcing our new AI-powered campaign analytics feature.",
    analyzeData: "Analyze campaign data",
    analyzeDataPrompt: "Analyze last week's campaign performance and tell me which channels to scale.",
    researchCompetitors: "Research competitors",
    researchCompetitorsPrompt: "What did HubSpot and Marketo announce recently? Summarize their positioning shifts.",
    needsCsv: "needs an attached CSV",
    preview: "Preview",
    trace: "Trace",
    live: "live",
    noPreview: "no preview",
    expandPreview: "Expand preview panel",
    collapsePreview: "Collapse preview panel",
    previewEmptyTitle: "Generated PDFs and uploaded files appear here.",
    previewEmptyBody: "Ask for a PDF deliverable and preview or download it here.",
    download: "Download",
    noInlinePreview: "No inline preview for this file type. Use Download.",
    csvLoading: "Loading...",
    csvTruncated: "Preview truncated to first 50 rows.",
    traceEmpty: "Specialist activity will appear here in real time.",
    tokensIn: "tokens in",
    tokensOut: "tokens out",
    connected: "Connected.",
    startingWork: "Starting work...",
    delegating: "Delegating to",
    contentAgent: "Content agent",
    analyticsAgent: "Analytics agent",
    researchAgent: "Research agent",
    specialistReturned: "returned",
    specialistFailed: "failed",
    specialist: "specialist",
    synthesizing: "Synthesizing response...",
    generating: "Generating",
    thinking: "Thinking...",
    chars: "chars",
    orchestrator: "orchestrator",
    tokensShortIn: "in",
    tokensShortOut: "out",
    error: "Error",
    failedToStartSession: "Failed to start session",
    noTextReturned: "No text was returned.",
    noMessageReturned: "No message was returned.",
    connectionClosed: "The connection was closed.",
    streamCancelled: "Stream cancelled",
    artifactReady: "Artifact ready",
    themeToggle: "Toggle theme",
    userAvatar: "User avatar",
    resizePanel: (side: string) => `Resize ${side} panel`,
  },
} as const;

export type I18nText = (typeof messages)[Locale];

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("zh");

  useEffect(() => {
    const stored = window.localStorage.getItem(LOCALE_KEY);
    if (stored === "zh" || stored === "en") setLocaleState(stored);
  }, []);

  const setLocale = (next: Locale) => {
    setLocaleState(next);
    window.localStorage.setItem(LOCALE_KEY, next);
  };

  const value = useMemo(
    () => ({ locale, setLocale, t: messages[locale] }),
    [locale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside I18nProvider");
  return ctx;
}

export function localizeError(error: unknown, locale: Locale): string {
  const raw = error instanceof Error ? error.message : String(error);
  if (locale === "zh") return raw;

  const exact: Record<string, string> = {
    "账号必须是有效邮箱或中国大陆手机号。": "Account must be a valid email or mainland China phone number.",
    "密码至少需要 8 位。": "Password must be at least 8 characters.",
    "密码长度不能超过 128 位。": "Password must be 128 characters or fewer.",
    "头像图片过大。": "Avatar image is too large.",
    "头像必须是图片 data URL。": "Avatar must be an image data URL.",
    "手机号格式不正确。": "Phone number format is invalid.",
    "邮箱格式不正确。": "Email format is invalid.",
    "身份证号格式不正确。": "Chinese ID format is invalid.",
    "身份证号出生日期不正确。": "Chinese ID birth date is invalid.",
    "身份证号校验位不正确。": "Chinese ID checksum is invalid.",
    "账号已存在。": "Account already exists.",
    "账号或密码不正确。": "Account or password is incorrect.",
    "账号不存在。": "Account does not exist. Please register it again.",
    "密码不正确。": "Password is incorrect.",
    "请输入确认文本。": "Please enter the confirmation text.",
    "用户名为必填项。": "Username is required.",
    "真实姓名为必填项。": "Legal name is required.",
    "身份证号为必填项。": "Chinese ID is required.",
  };
  if (exact[raw]) return exact[raw];

  const maxLenMatch = raw.match(/^(.+)不能超过 (\d+) 个字符。$/);
  if (maxLenMatch) return `${maxLenMatch[1]} must be ${maxLenMatch[2]} characters or fewer.`;

  return raw
    .replace("Authentication required.", "Please log in first.")
    .replace("Invalid or expired token.", "Your login has expired. Please log in again.")
    .replace("User not found.", "User not found.")
    .replace("Group not found.", "Group not found.")
    .replace("Session not found.", "Chat not found.")
    .replace("Missing filename.", "Missing filename.")
    .replace("Empty file.", "The file is empty.")
    .replace("Upload failed.", "Upload failed.")
    .replace("File not found.", "File not found.")
    .replace("Artifact not found.", "Generated material not found.")
    .replace("Empty prompt.", "Please enter a message.");
}

export function LanguageToggle({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n();
  const next = locale === "zh" ? "en" : "zh";
  return (
    <button
      type="button"
      onClick={() => setLocale(next)}
      className="rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-fg-muted hover:bg-bg-subtle hover:text-fg"
      title={t.language}
    >
      {compact ? (locale === "zh" ? "EN" : "中") : locale === "zh" ? "English" : "中文"}
    </button>
  );
}
