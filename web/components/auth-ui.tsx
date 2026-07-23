"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Modal } from "@/components/modal";
import {
  Brain,
  Check,
  ChevronDown,
  HelpCircle,
  Languages,
  LogOut,
  Minus,
  Palette,
  Settings,
  ShieldAlert,
  Sparkles,
  Trash2,
  UserRound,
  UserRoundCog,
  WalletCards,
} from "lucide-react";
import {
  clearMarketingMemory,
  deleteMe,
  getMarketingMemory,
  getMarketingMemoryEvidence,
  loginUser,
  lookupAvatar,
  registerUser,
  saveMarketingMemory,
  setAuthToken,
  updateMe,
  updateMarketingMemorySettings,
  type MarketingMemoryEvidenceItem,
  type MarketingMemoryProfile,
  type ProfilePayload,
  type UserProfile,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { LanguageToggle, localizeError, useI18n } from "@/lib/i18n";
import { useTheme } from "next-themes";
import { saveUserLocale, saveUserTheme, type UserTheme } from "@/lib/user-settings";

const REMEMBERED_KEY = "marketing-agent-remembered-accounts";
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_RE = /^1[3-9]\d{9}$/;

export type RememberedAccount = {
  account: string;
  username: string;
  avatar: string | null;
  password: string;
};

export function loadRememberedAccounts(): RememberedAccount[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(REMEMBERED_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveRememberedAccounts(items: RememberedAccount[]) {
  window.localStorage.setItem(REMEMBERED_KEY, JSON.stringify(items));
}

export function removeRememberedAccount(account: string) {
  saveRememberedAccounts(loadRememberedAccounts().filter((item) => item.account !== account));
}

function findRememberedAccount(account: string): RememberedAccount | undefined {
  return loadRememberedAccounts().find((item) => item.account === account);
}

export function rememberAccount(item: RememberedAccount) {
  const next = [item, ...loadRememberedAccounts().filter((old) => old.account !== item.account)];
  saveRememberedAccounts(next.slice(0, 8));
}

function updateRememberedAccount(account: string, patch: Partial<RememberedAccount>) {
  const existing = findRememberedAccount(account);
  if (!existing) return;
  rememberAccount({ ...existing, ...patch, account });
}

function contactFromAccount(account: string): Pick<ProfilePayload, "email" | "phone"> {
  const value = account.trim();
  if (EMAIL_RE.test(value)) return { email: value, phone: "" };
  if (PHONE_RE.test(value)) return { phone: value, email: "" };
  return { email: "", phone: "" };
}

export function DefaultAvatar({ className }: { className?: string }) {
  return (
    <div className={cn("rounded-full bg-accent/15 text-accent flex items-center justify-center", className)}>
      <UserRound size={22} />
    </div>
  );
}

export function AvatarImage({
  avatar,
  className,
  label,
}: {
  avatar?: string | null;
  className?: string;
  label?: string;
}) {
  const { locale, t } = useI18n();
  if (!avatar) return <DefaultAvatar className={className} />;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={avatar}
      alt={label ?? t.userAvatar}
      className={cn("rounded-full object-cover bg-bg-subtle", className)}
    />
  );
}

export function AuthScreen({ onAuthenticated }: { onAuthenticated: (token: string, user: UserProfile) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  return mode === "login" ? (
    <LoginPanel onAuthenticated={onAuthenticated} onRegister={() => setMode("register")} />
  ) : (
    <RegisterPanel onAuthenticated={onAuthenticated} onBack={() => setMode("login")} />
  );
}

function AuthShell({ children }: { children: React.ReactNode }) {
  const { locale, t } = useI18n();
  return (
    <main className="min-h-screen bg-bg text-fg flex flex-col">
      <header className="border-b border-border bg-bg-elevated/60 backdrop-blur">
        <div className="px-4 py-3 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-accent text-accent-fg flex items-center justify-center">
            <Sparkles size={16} />
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-tight">{t.appName}</h1>
            <p className="text-[11px] text-fg-subtle">{t.authSubtitle}</p>
          </div>
          <div className="ml-auto">
            <LanguageToggle />
          </div>
        </div>
      </header>
      <div className="flex-1 flex items-center justify-center px-4 py-10">{children}</div>
    </main>
  );
}

function LoginPanel({
  onAuthenticated,
  onRegister,
}: {
  onAuthenticated: (token: string, user: UserProfile) => void;
  onRegister: () => void;
}) {
  const { locale, t } = useI18n();
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [avatar, setAvatar] = useState<string | null>(null);
  const [avatarOpen, setAvatarOpen] = useState(false);
  const [remembered, setRemembered] = useState<RememberedAccount[]>([]);
  const [deleteTarget, setDeleteTarget] = useState<RememberedAccount | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setRemembered(loadRememberedAccounts());
  }, []);

  useEffect(() => {
    const trimmed = account.trim();
    if (!trimmed) {
      setAvatar(null);
      return;
    }
    const cached = remembered.find((item) => item.account === trimmed);
    if (cached) {
      setAvatar(cached.avatar);
      return;
    }
    const timer = window.setTimeout(() => {
      lookupAvatar(trimmed)
        .then((res) => setAvatar(res.avatar))
        .catch(() => setAvatar(null));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [account, remembered]);

  async function submit() {
    setError(null);
    setBusy(true);
    const trimmedAccount = account.trim();
    try {
      const res = await loginUser(trimmedAccount, password);
      setAuthToken(res.token);
      if (remember) {
        rememberAccount({
          account: res.user.account,
          username: res.user.username,
          avatar: res.user.avatar,
          password,
        });
      }
      onAuthenticated(res.token, res.user);
    } catch (err) {
      const cached = findRememberedAccount(trimmedAccount);
      if (cached?.password === password) {
        removeRememberedAccount(trimmedAccount);
        setRemembered(loadRememberedAccounts());
        setPassword("");
        const message = localizeError(err, locale);
        setError(message.includes("账号不存在") || message.includes("Account does not exist") ? message : t.rememberedPasswordExpired);
        return;
      }
      setError(localizeError(err, locale));
    } finally {
      setBusy(false);
    }
  }

  function pickRemembered(item: RememberedAccount) {
    setAccount(item.account);
    setPassword(item.password);
    setAvatar(item.avatar);
    setAvatarOpen(false);
  }

  return (
    <AuthShell>
      <section className="w-full max-w-sm rounded-xl border border-border bg-bg-elevated p-6 shadow-sm">
        <button
          type="button"
          onClick={() => setAvatarOpen((open) => !open)}
          className="relative mx-auto block"
          title={t.chooseRememberedAccount}
        >
          <AvatarImage avatar={avatar} className="h-20 w-20 ring-4 ring-bg-subtle" />
        </button>
        {avatarOpen ? (
          <RememberedPopover
            items={remembered}
            onPick={pickRemembered}
            onDelete={(item) => setDeleteTarget(item)}
            className="mt-3"
          />
        ) : null}
        <div className="mt-6 space-y-3">
          <TextInput label={t.accountLabel} value={account} onChange={setAccount} autoComplete="username" placeholder={t.account} />
          <TextInput label={t.password} value={password} onChange={setPassword} type="password" autoComplete="current-password" placeholder={t.passwordInput} />
          <label className="flex items-center gap-2 text-sm text-fg-muted">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="h-4 w-4 accent-accent"
            />
            {t.rememberMe}
          </label>
          {error ? <p className="text-xs text-danger">{error}</p> : null}
          <button
            type="button"
            onClick={submit}
            disabled={busy || !account.trim() || !password}
            className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-accent-fg disabled:opacity-40"
          >
            {busy ? t.loggingIn : t.login}
          </button>
          <button
            type="button"
            onClick={onRegister}
            className="w-full rounded-lg border border-border px-4 py-2.5 text-sm font-medium text-fg-muted hover:bg-bg-subtle"
          >
            {t.registerAccount}
          </button>
        </div>
      </section>
      {deleteTarget ? (
        <ConfirmDialog
          title={t.deleteRememberedTitle}
          body={t.deleteRememberedBody(deleteTarget.account)}
          confirmLabel={t.delete}
          danger
          onCancel={() => setDeleteTarget(null)}
          onConfirm={() => {
            removeRememberedAccount(deleteTarget.account);
            setRemembered(loadRememberedAccounts());
            setDeleteTarget(null);
          }}
        />
      ) : null}
    </AuthShell>
  );
}

function RegisterPanel({
  onAuthenticated,
  onBack,
}: {
  onAuthenticated: (token: string, user: UserProfile) => void;
  onBack: () => void;
}) {
  const { locale, t } = useI18n();
  const [form, setForm] = useState<ProfilePayload>({
    account: "",
    password: "",
    username: "",
    real_name: "",
    id_card: "",
    avatar: null,
    company: "",
    title: "",
    bio: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const idCardValid = useMemo(() => !form.id_card || isValidChinaId(form.id_card), [form.id_card]);

  function set<K extends keyof ProfilePayload>(key: K, value: ProfilePayload[K]) {
    setForm((old) => ({ ...old, [key]: value }));
  }

  async function submit() {
    setError(null);
    if (!idCardValid) {
      setError(t.idCardError);
      return;
    }
    setBusy(true);
    try {
      const res = await registerUser({
        ...form,
        ...contactFromAccount(form.account ?? ""),
      });
      setAuthToken(res.token);
      if (form.account && form.password && findRememberedAccount(form.account)) {
        rememberAccount({
          account: res.user.account,
          username: res.user.username,
          avatar: res.user.avatar,
          password: form.password,
        });
      }
      onAuthenticated(res.token, res.user);
    } catch (err) {
      setError(localizeError(err, locale));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell>
      <section className="w-full max-w-2xl rounded-xl border border-border bg-bg-elevated p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold">{t.registerTitle}</h2>
            <p className="text-xs text-fg-subtle">{t.requiredHint}</p>
          </div>
          <AvatarPicker avatar={form.avatar ?? null} onChange={(avatar) => set("avatar", avatar)} />
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          <TextInput label={t.accountRequired} value={form.account ?? ""} onChange={(v) => set("account", v)} placeholder={t.account} />
          <TextInput label={t.passwordRequired} type="password" value={form.password ?? ""} onChange={(v) => set("password", v)} placeholder={t.passwordHint} />
          <TextInput label={t.usernameRequired} value={form.username} onChange={(v) => set("username", v)} placeholder={t.usernameHint} />
          <TextInput label={t.realNameRequired} value={form.real_name ?? ""} onChange={(v) => set("real_name", v)} placeholder={t.realNameHint} />
          <TextInput label={t.idCardRequired} value={form.id_card ?? ""} onChange={(v) => set("id_card", v.toUpperCase())} placeholder={t.idCardHint} error={form.id_card && !idCardValid ? t.idCardError : undefined} />
          <TextInput label={t.company} value={form.company ?? ""} onChange={(v) => set("company", v)} placeholder={t.companyHint} />
          <TextInput label={t.title} value={form.title ?? ""} onChange={(v) => set("title", v)} placeholder={t.titleHint} />
          <label className="md:col-span-2 text-xs font-medium text-fg-muted">
            {t.bio}
            <textarea
              value={form.bio ?? ""}
              onChange={(e) => set("bio", e.target.value)}
              rows={3}
              placeholder={t.bioHint}
              className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
            />
          </label>
        </div>
        {error ? <p className="mt-3 text-xs text-danger">{error}</p> : null}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onBack} className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle">
            {t.backToLogin}
          </button>
          <button type="button" onClick={submit} disabled={busy} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-40">
            {busy ? t.submitting : t.finishRegister}
          </button>
        </div>
      </section>
    </AuthShell>
  );
}

export function UserMenu({
  user,
  onUserChange,
  onLogout,
  onSwitchAccount,
}: {
  user: UserProfile;
  onUserChange: (user: UserProfile) => void;
  onLogout: () => void;
  onSwitchAccount: () => void;
}) {
  const { locale, t } = useI18n();
  const [open, setOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [placeholder, setPlaceholder] = useState<string | null>(null);

  const menuItems = [
    { label: t.settings, icon: Settings, onClick: () => setSettingsOpen(true) },
    { label: t.switchAccount, icon: UserRoundCog, onClick: onSwitchAccount },
    { label: t.profile, icon: UserRound, onClick: () => setProfileOpen(true) },
    { label: t.subscription, icon: WalletCards, onClick: () => setPlaceholder(t.subscription) },
    { label: t.help, icon: HelpCircle, onClick: () => setPlaceholder(t.help) },
    { label: t.logout, icon: LogOut, onClick: onLogout },
    { label: t.deleteAccount, icon: ShieldAlert, danger: true, onClick: () => setDeleteOpen(true) },
  ];

  return (
    <>
      <div className="relative">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="user-menu-trigger inline-flex items-center gap-2 rounded-full border border-border bg-bg-elevated px-1.5 py-1 hover:bg-bg-subtle"
        >
          <AvatarImage avatar={user.avatar} className="h-8 w-8" label={user.username} />
          <ChevronDown size={14} className="text-fg-muted" />
        </button>
        {open ? (
          <div className="user-menu-popover absolute right-0 top-11 z-[60] w-52 rounded-xl border border-border bg-bg-elevated p-1.5 shadow-lg">
            <div className="px-3 py-2">
              <p className="truncate text-sm font-medium">{user.username}</p>
              <p className="truncate text-xs text-fg-subtle">{user.account}</p>
            </div>
            <div className="my-1 h-px bg-border" />
            {menuItems.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    item.onClick();
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-bg-subtle",
                    item.danger ? "text-danger" : "text-fg-muted hover:text-fg",
                  )}
                >
                  <Icon size={15} />
                  {item.label}
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
      {settingsOpen ? <SettingsDialog userAccount={user.account} onClose={() => setSettingsOpen(false)} /> : null}
      {profileOpen ? (
        <ProfileDialog
          user={user}
          onClose={() => setProfileOpen(false)}
          onSaved={(next) => {
            onUserChange(next);
            setProfileOpen(false);
          }}
        />
      ) : null}
      {deleteOpen ? <DeleteAccountDialog onClose={() => setDeleteOpen(false)} onDeleted={onLogout} account={user.account} /> : null}
      {placeholder ? (
        <InfoDialog
          title={placeholder}
          body={t.placeholderBody(placeholder)}
          onClose={() => setPlaceholder(null)}
        />
      ) : null}
    </>
  );
}

export function SwitchAccountPanel({
  open,
  onClose,
  onAuthenticated,
}: {
  open: boolean;
  onClose: () => void;
  onAuthenticated: (token: string, user: UserProfile) => void;
}) {
  const { locale, t } = useI18n();
  const [items, setItems] = useState<RememberedAccount[]>([]);
  const [deleteTarget, setDeleteTarget] = useState<RememberedAccount | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) setItems(loadRememberedAccounts());
  }, [open]);

  if (!open) return null;

  async function pick(item: RememberedAccount) {
    setError(null);
    try {
      const res = await loginUser(item.account, item.password);
      setAuthToken(res.token);
      onAuthenticated(res.token, res.user);
      onClose();
    } catch (err) {
      removeRememberedAccount(item.account);
      setItems(loadRememberedAccounts());
      const message = localizeError(err, locale);
      setError(message.includes("账号不存在") || message.includes("Account does not exist") ? message : t.rememberedPasswordExpired);
    }
  }

  return (
    <>
      <aside className="fixed right-4 top-20 z-30 w-72 rounded-xl border border-border bg-bg-elevated p-3 shadow-xl">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold">{t.switchAccount}</h3>
          <button type="button" onClick={onClose} className="text-xs text-fg-subtle hover:text-fg">
            {t.close}
          </button>
        </div>
        <RememberedList items={items} onPick={pick} onDelete={(item) => setDeleteTarget(item)} />
        {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}
      </aside>
      {deleteTarget ? (
        <ConfirmDialog
          title={t.deleteRememberedTitle}
          body={t.deleteRememberedShortBody(deleteTarget.account)}
          confirmLabel={t.delete}
          danger
          onCancel={() => setDeleteTarget(null)}
          onConfirm={() => {
            removeRememberedAccount(deleteTarget.account);
            setItems(loadRememberedAccounts());
            setDeleteTarget(null);
          }}
        />
      ) : null}
    </>
  );
}

function RememberedPopover({
  items,
  onPick,
  onDelete,
  className,
}: {
  items: RememberedAccount[];
  onPick: (item: RememberedAccount) => void;
  onDelete: (item: RememberedAccount) => void;
  className?: string;
}) {
  return (
    <div className={cn("rounded-xl border border-border bg-bg p-2 shadow-sm", className)}>
      <RememberedList items={items} onPick={onPick} onDelete={onDelete} />
    </div>
  );
}

function RememberedList({
  items,
  onPick,
  onDelete,
}: {
  items: RememberedAccount[];
  onPick: (item: RememberedAccount) => void;
  onDelete: (item: RememberedAccount) => void;
}) {
  const { locale, t } = useI18n();
  if (items.length === 0) {
    return <p className="px-2 py-4 text-center text-xs text-fg-subtle">{t.noRememberedAccounts}</p>;
  }
  return (
    <div className="space-y-1">
      {items.map((item) => (
        <div key={item.account} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-bg-subtle">
          <button type="button" onClick={() => onPick(item)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
            <AvatarImage avatar={item.avatar} className="h-8 w-8" />
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium">{item.username || item.account}</span>
              <span className="block truncate text-xs text-fg-subtle">{item.account}</span>
            </span>
          </button>
          <button
            type="button"
            onClick={() => onDelete(item)}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-fg-subtle hover:bg-danger/10 hover:text-danger"
            title={t.deleteRememberedRecord}
          >
            <Minus size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

const MARKETING_MEMORY_KEYS: (keyof MarketingMemoryProfile)[] = [
  "role_title",
  "industry",
  "company_brand",
  "products",
  "target_customers",
  "channels",
  "tone_preferences",
  "report_format_preferences",
  "kpi_data_preferences",
  "other_preferences",
];

const EMPTY_MARKETING_MEMORY = Object.fromEntries(MARKETING_MEMORY_KEYS.map((key) => [key, ""])) as Record<keyof MarketingMemoryProfile, string>;

const MEMORY_VALUE_LABELS: Record<string, { zh: string; en: string }> = {
  "Marketing or business owner": { zh: "营销或业务负责人", en: "Marketing or business owner" },
  "Marketing / growth / operations": { zh: "市场 / 增长 / 运营", en: "Marketing / growth / operations" },
  "Sales / business development": { zh: "销售 / 商务拓展", en: "Sales / business development" },
  "Fashion/apparel": { zh: "服装 / 时尚", en: "Fashion/apparel" },
  "B2B SaaS / enterprise services": { zh: "B2B SaaS / 企业服务", en: "B2B SaaS / enterprise services" },
  "Education/training": { zh: "教育 / 培训", en: "Education/training" },
  "Consumer goods / ecommerce": { zh: "消费品 / 电商", en: "Consumer goods / ecommerce" },
  "Company/brand context discussed": { zh: "已讨论公司 / 品牌背景", en: "Company/brand context discussed" },
  "Apparel products": { zh: "服装类产品", en: "Apparel products" },
  "Software / SaaS product": { zh: "软件 / SaaS 产品", en: "Software / SaaS product" },
  "Education product": { zh: "教育类产品", en: "Education product" },
  "B2B decision makers": { zh: "B2B 决策者", en: "B2B decision makers" },
  "Marketing / growth / sales teams": { zh: "市场 / 增长 / 销售团队", en: "Marketing / growth / sales teams" },
  "Consumer lifestyle audiences": { zh: "消费生活方式人群", en: "Consumer lifestyle audiences" },
  "Little Red Book": { zh: "小红书", en: "Little Red Book" },
  LinkedIn: { zh: "LinkedIn / 领英", en: "LinkedIn" },
  "WeChat / owned channels": { zh: "微信 / 私域渠道", en: "WeChat / owned channels" },
  "Short video": { zh: "短视频", en: "Short video" },
  "Email/newsletter": { zh: "邮件 / Newsletter", en: "Email/newsletter" },
  Professional: { zh: "专业正式", en: "Professional" },
  "Authentic and friendly": { zh: "真实亲切", en: "Authentic and friendly" },
  "Premium/refined": { zh: "高级精致", en: "Premium/refined" },
  "Playful/young": { zh: "年轻活泼", en: "Playful/young" },
  "Marketing copy": { zh: "营销文案", en: "Marketing copy" },
  "Report/brief": { zh: "报告 / 简报", en: "Report/brief" },
  "Campaign plan": { zh: "营销方案 / 活动计划", en: "Campaign plan" },
  Email: { zh: "邮件", en: "Email" },
  "Video script": { zh: "视频脚本", en: "Video script" },
  "Performance and conversion metrics": { zh: "表现与转化指标", en: "Performance and conversion metrics" },
  "Reach and engagement metrics": { zh: "曝光与互动指标", en: "Reach and engagement metrics" },
};

function localizeMemoryValue(value: string, locale: "zh" | "en"): string {
  const normalized = value.trim();
  const direct = MEMORY_VALUE_LABELS[normalized];
  if (direct) return direct[locale];
  const reverse = Object.values(MEMORY_VALUE_LABELS).find((item) => item.zh === normalized || item.en === normalized);
  return reverse ? reverse[locale] : normalized;
}

function memoryToForm(profile: Partial<MarketingMemoryProfile> | undefined, locale: "zh" | "en"): Record<keyof MarketingMemoryProfile, string> {
  return Object.fromEntries(
    MARKETING_MEMORY_KEYS.map((key) => [key, (profile?.[key] ?? []).map((value) => localizeMemoryValue(value, locale)).join("\n")]),
  ) as Record<keyof MarketingMemoryProfile, string>;
}

function formToMemory(form: Record<keyof MarketingMemoryProfile, string>): Partial<MarketingMemoryProfile> {
  return Object.fromEntries(
    MARKETING_MEMORY_KEYS.map((key) => [
      key,
      form[key]
        .split(/\n|,|，/)
        .map((item) => item.trim())
        .filter(Boolean),
    ]),
  ) as Partial<MarketingMemoryProfile>;
}

function SettingsDialog({ userAccount, onClose }: { userAccount: string; onClose: () => void }) {
  const { locale, setLocale, t } = useI18n();
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [memoryForm, setMemoryForm] = useState<Record<keyof MarketingMemoryProfile, string>>(EMPTY_MARKETING_MEMORY);
  const [memoryLoading, setMemoryLoading] = useState(true);
  const [memorySaving, setMemorySaving] = useState(false);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memorySaved, setMemorySaved] = useState(false);
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [memoryLearned, setMemoryLearned] = useState<Partial<MarketingMemoryProfile>>({});
  const [memoryEvidence, setMemoryEvidence] = useState<MarketingMemoryEvidenceItem[]>([]);
  const [memoryThreshold, setMemoryThreshold] = useState(3);
  const [confirmClearMemory, setConfirmClearMemory] = useState(false);
  const languageRef = useRef<HTMLDivElement>(null);
  const themeRef = useRef<HTMLDivElement>(null);
  const memoryRef = useRef<HTMLDivElement>(null);
  const activeTheme = mounted ? (theme === "system" ? resolvedTheme : theme) ?? "light" : "light";
  const labels =
    locale === "zh"
      ? {
          languageGroup: "语言与地区",
          languageBody: "选择界面显示语言。",
          themeGroup: "主题外观",
          themeBody: "选择工作台视觉主题。",
          memoryGroup: "长期记忆",
          memoryBody: "查看和修改自动总结出的企业营销用户画像。",
          memoryHint: "每行一个偏好或事实，系统会在后续对话中优先参考这些信息。",
          memoryAuto: "聊天中识别到的高相关营销信息会自动沉淀到这里，你也可以手动修正。",
          memoryEnabled: "自动长期记忆开关",
          memoryEnabledBody: "开启后，系统会在多次对话中逐步沉淀企业营销画像。",
          memorySave: "保存手动记忆",
          memoryClear: "清空手动记忆",
          memoryClearTitle: "清空手动填写的长期记忆？",
          memoryClearBody: "仅清空你手动填写的企业营销画像，自动学习到的内容不受影响。",
          memorySaved: "已保存",
          memoryManualTitle: "手动填写的画像",
          memoryLearnedTitle: "自动学习到的画像",
          memoryLearnedBody: "系统从历次对话中自动沉淀的信息（只读）。手动填写的内容会覆盖这里的对应字段。",
          memoryLearnedEmpty: "暂无自动学习到的内容，多聊几次后会自动积累。",
          memoryEvidenceTitle: "查看识别到的线索",
          memoryPromoted: "已采纳",
          memoryPending: "待确认",
          memoryExplicitTag: "明确声明",
          memoryMentions: (n: number) => `${n} 次提及`,
          memoryPendingHint: (n: number) => `信息需累计约 ${n} 次提及才会被采纳，单次提及仅保留在当前会话中。`,
          loading: "加载中...",
          roleTitle: "角色 / 职位",
          industry: "所属行业",
          companyBrand: "公司 / 品牌",
          products: "主要产品",
          targetCustomers: "目标客户",
          channels: "常用渠道",
          tonePreferences: "内容语气偏好",
          reportFormatPreferences: "报告格式偏好",
          kpiDataPreferences: "KPI / 数据口径偏好",
          otherPreferences: "其他长期偏好",
          light: "明亮",
          dark: "暗色",
          aurora: "极光",
          crystal: "晴空",
        }
      : {
          languageGroup: "Language",
          languageBody: "Choose the interface language.",
          themeGroup: "Appearance",
          themeBody: "Choose the workspace visual theme.",
          memoryGroup: "Long-Term Memory",
          memoryBody: "View and edit the enterprise marketing profile summarized from chats.",
          memoryHint: "Use one fact or preference per line. Future chats will use these details first.",
          memoryAuto: "Highly relevant marketing context can be captured from chat automatically, and you can correct it here.",
          memoryEnabled: "Auto memory",
          memoryEnabledBody: "When enabled, the system gradually builds the enterprise marketing profile across chats.",
          memorySave: "Save manual memory",
          memoryClear: "Clear manual memory",
          memoryClearTitle: "Clear manually-entered memory?",
          memoryClearBody: "This only clears the profile you filled in manually. Auto-learned memory is not affected.",
          memorySaved: "Saved",
          memoryManualTitle: "Manual profile",
          memoryLearnedTitle: "Auto-learned profile",
          memoryLearnedBody: "Details the system captured from past chats (read-only). Anything you fill in manually overrides the matching field here.",
          memoryLearnedEmpty: "Nothing learned yet — it builds up automatically as you chat more.",
          memoryEvidenceTitle: "View detected signals",
          memoryPromoted: "Applied",
          memoryPending: "Pending",
          memoryExplicitTag: "Stated",
          memoryMentions: (n: number) => `${n}×`,
          memoryPendingHint: (n: number) => `Signals apply after about ${n} mentions; a single mention stays only in the current session.`,
          loading: "Loading...",
          roleTitle: "Role / title",
          industry: "Industry",
          companyBrand: "Company / brand",
          products: "Main products",
          targetCustomers: "Target customers",
          channels: "Common channels",
          tonePreferences: "Tone preferences",
          reportFormatPreferences: "Report format preferences",
          kpiDataPreferences: "KPI / data definitions",
          otherPreferences: "Other long-term preferences",
          light: "Light",
          dark: "Dark",
          aurora: "Aurora",
          crystal: "Crystal",
        };
  const navItems = [
    { label: labels.languageGroup, icon: Languages, target: languageRef },
    { label: labels.themeGroup, icon: Palette, target: themeRef },
    { label: labels.memoryGroup, icon: Brain, target: memoryRef },
  ];
  const memoryFields = [
    { key: "role_title", label: labels.roleTitle },
    { key: "industry", label: labels.industry },
    { key: "company_brand", label: labels.companyBrand },
    { key: "products", label: labels.products },
    { key: "target_customers", label: labels.targetCustomers },
    { key: "channels", label: labels.channels },
    { key: "tone_preferences", label: labels.tonePreferences },
    { key: "report_format_preferences", label: labels.reportFormatPreferences },
    { key: "kpi_data_preferences", label: labels.kpiDataPreferences },
    { key: "other_preferences", label: labels.otherPreferences },
  ] as { key: keyof MarketingMemoryProfile; label: string }[];
  const memoryFieldLabels = Object.fromEntries(memoryFields.map((f) => [f.key, f.label])) as Record<
    keyof MarketingMemoryProfile,
    string
  >;
  const learnedEntries = memoryFields
    .map((f) => ({ key: f.key, label: f.label, values: (memoryLearned[f.key] ?? []) as string[] }))
    .filter((f) => f.values.length > 0);
  const themes = [
    { id: "light", label: labels.light, preview: "theme-preview-light" },
    { id: "dark", label: labels.dark, preview: "theme-preview-dark" },
    { id: "aurora", label: labels.aurora, preview: "theme-preview-aurora" },
    { id: "crystal", label: labels.crystal, preview: "theme-preview-crystal" },
  ] as const;

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    let cancelled = false;
    setMemoryLoading(true);
    setMemoryError(null);
    getMarketingMemory()
      .then((res) => {
        if (!cancelled) {
          setMemoryForm(memoryToForm(res.profile, locale));
          setMemoryEnabled(res.enabled);
          setMemoryLearned(res.learned ?? {});
        }
      })
      .catch((err) => {
        if (!cancelled) setMemoryError(localizeError(err, locale));
      })
      .finally(() => {
        if (!cancelled) setMemoryLoading(false);
      });
    getMarketingMemoryEvidence()
      .then((res) => {
        if (!cancelled) {
          setMemoryEvidence(res.evidence);
          setMemoryThreshold(res.threshold);
        }
      })
      .catch(() => {
        /* evidence is a non-critical enhancement */
      });
    return () => {
      cancelled = true;
    };
  }, [locale, userAccount]);

  function scrollTo(ref: React.RefObject<HTMLDivElement>) {
    ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function chooseLocale(next: "zh" | "en") {
    saveUserLocale(userAccount, next);
    setLocale(next);
  }

  function chooseTheme(next: UserTheme) {
    saveUserTheme(userAccount, next);
    setTheme(next);
  }

  function updateMemoryField(key: keyof MarketingMemoryProfile, value: string) {
    setMemorySaved(false);
    setMemoryForm((old) => ({ ...old, [key]: value }));
  }

  async function saveMemory() {
    setMemorySaving(true);
    setMemoryError(null);
    setMemorySaved(false);
    try {
      const res = await saveMarketingMemory(formToMemory(memoryForm));
      setMemoryForm(memoryToForm(res.profile, locale));
      setMemoryLearned(res.learned ?? {});
      setMemorySaved(true);
      // Saving the manual profile does not affect auto-learned memory/evidence.
    } catch (err) {
      setMemoryError(localizeError(err, locale));
    } finally {
      setMemorySaving(false);
    }
  }

  async function toggleMemoryEnabled() {
    const next = !memoryEnabled;
    setMemoryEnabled(next);
    setMemoryError(null);
    try {
      const res = await updateMarketingMemorySettings(next);
      setMemoryEnabled(res.enabled);
      setMemoryLearned(res.learned ?? {});
    } catch (err) {
      setMemoryEnabled(!next);
      setMemoryError(localizeError(err, locale));
    }
  }

  async function clearMemory() {
    setMemorySaving(true);
    setMemoryError(null);
    try {
      const res = await clearMarketingMemory();
      setMemoryForm(EMPTY_MARKETING_MEMORY);
      // Clearing the manual profile leaves auto-learned memory/evidence intact.
      setMemoryLearned(res.learned ?? {});
      setMemorySaved(false);
      setConfirmClearMemory(false);
    } catch (err) {
      setMemoryError(localizeError(err, locale));
    } finally {
      setMemorySaving(false);
    }
  }

  return (
    <Modal title={t.settings} onClose={onClose} size="settings">
      <div className="grid min-h-[520px] gap-5 md:grid-cols-[190px_minmax(0,1fr)]">
        <nav className="rounded-xl border border-border bg-bg/70 p-2">
          <div className="space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => scrollTo(item.target)}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-fg-muted transition hover:bg-bg-elevated hover:text-fg"
                >
                  <Icon size={15} />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </div>
        </nav>

        <div className="max-h-[64vh] space-y-4 overflow-y-auto pr-1">
          <section ref={languageRef} className="rounded-xl border border-border bg-bg/70 p-4 scroll-mt-2">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <p className="text-sm font-semibold">{labels.languageGroup}</p>
                <p className="mt-1 text-xs text-fg-subtle">{labels.languageBody}</p>
              </div>
              <div className="inline-flex rounded-lg border border-border bg-bg-elevated p-1">
                <button
                  type="button"
                  onClick={() => chooseLocale("zh")}
                  className={cn("rounded-md px-3 py-1.5 text-xs transition", locale === "zh" ? "bg-accent text-accent-fg shadow-sm" : "text-fg-muted hover:bg-bg-subtle hover:text-fg")}
                >
                  {t.chinese}
                </button>
                <button
                  type="button"
                  onClick={() => chooseLocale("en")}
                  className={cn("rounded-md px-3 py-1.5 text-xs transition", locale === "en" ? "bg-accent text-accent-fg shadow-sm" : "text-fg-muted hover:bg-bg-subtle hover:text-fg")}
                >
                  {t.english}
                </button>
              </div>
            </div>
            <div className="rounded-lg border border-border/70 bg-bg-subtle/60 px-3 py-2 text-xs text-fg-muted">
              {locale === "zh" ? t.chinese : t.english}
            </div>
          </section>

          <section ref={themeRef} className="rounded-xl border border-border bg-bg/70 p-4 scroll-mt-2">
            <div className="mb-4">
              <p className="text-sm font-semibold">{labels.themeGroup}</p>
              <p className="mt-1 text-xs text-fg-subtle">{labels.themeBody}</p>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {themes.map((item) => {
                const active = mounted && activeTheme === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => chooseTheme(item.id)}
                    className={cn(
                      "overflow-hidden rounded-xl border text-left hover-lift",
                      active ? "border-accent ring-1 ring-accent" : "border-border hover:bg-bg-elevated",
                    )}
                  >
                    <div className={cn("theme-preview h-28 w-full bg-bg-subtle", item.preview)}>
                      <div className="theme-preview-top" />
                      <div className="theme-preview-body">
                        <span />
                        <span />
                        <span />
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 px-2 py-2">
                      {active ? <Check size={13} className="text-accent" /> : null}
                      <span className="text-xs font-medium">{item.label}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          <section ref={memoryRef} className="rounded-xl border border-border bg-bg/70 p-4 scroll-mt-2">
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold">{labels.memoryGroup}</p>
                <p className="mt-1 text-xs text-fg-subtle">{labels.memoryBody}</p>
              </div>
              <div className="flex items-center gap-2">
                {memorySaved ? <span className="rounded-full bg-accent/10 px-2 py-1 text-[11px] font-medium text-accent">{labels.memorySaved}</span> : null}
                <span className="text-xs font-medium text-fg-muted">{labels.memoryEnabled}</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={memoryEnabled}
                  onClick={toggleMemoryEnabled}
                  disabled={memorySaving || memoryLoading}
                  className={cn(
                    "relative h-7 w-12 shrink-0 rounded-full border transition-all duration-200 ease-macos disabled:opacity-50",
                    memoryEnabled ? "border-accent bg-accent shadow-sm shadow-accent/30" : "border-border bg-bg-subtle",
                  )}
                >
                  <span
                    className={cn(
                      "absolute left-0.5 top-0.5 h-6 w-6 rounded-full bg-white shadow-md transition-transform duration-200 ease-macos",
                      memoryEnabled ? "translate-x-5" : "translate-x-0",
                    )}
                  />
                </button>
              </div>
            </div>
            {!memoryLoading ? (
              <div className="rounded-lg border border-border/70 bg-bg-subtle/40 p-3">
                <p className="text-xs font-semibold text-fg-muted">{labels.memoryLearnedTitle}</p>
                <p className="mt-0.5 text-[11px] text-fg-subtle">{labels.memoryLearnedBody}</p>
                {learnedEntries.length === 0 ? (
                  <p className="mt-2 text-xs text-fg-subtle">{labels.memoryLearnedEmpty}</p>
                ) : (
                  <div className="mt-2 space-y-1.5">
                    {learnedEntries.map((entry) => (
                      <div key={entry.key} className="flex flex-wrap items-center gap-1.5 text-xs">
                        <span className="shrink-0 text-fg-subtle">{entry.label}:</span>
                        {entry.values.map((value, idx) => (
                          <span key={idx} className="rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent">
                            {localizeMemoryValue(value, locale)}
                          </span>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
                {memoryEvidence.length > 0 ? (
                  <details className="mt-3">
                    <summary className="cursor-pointer select-none text-[11px] font-medium text-fg-muted">
                      {labels.memoryEvidenceTitle}
                    </summary>
                    <div className="mt-2 space-y-1">
                      {memoryEvidence.map((item, idx) => (
                        <div key={`${item.field}-${item.value}-${idx}`} className="flex flex-wrap items-center gap-1.5 text-[11px] text-fg-subtle">
                          <span className="text-fg-muted">{localizeMemoryValue(item.value, locale)}</span>
                          <span className="rounded bg-bg-subtle px-1.5 py-0.5">{memoryFieldLabels[item.field] ?? item.field}</span>
                          <span>{labels.memoryMentions(item.count)}</span>
                          {item.explicit ? (
                            <span className="rounded-full bg-accent/10 px-1.5 py-0.5 font-medium text-accent">{labels.memoryExplicitTag}</span>
                          ) : null}
                          <span
                            className={cn(
                              "rounded-full px-1.5 py-0.5 font-medium",
                              item.promoted ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "bg-amber-500/10 text-amber-600 dark:text-amber-400",
                            )}
                          >
                            {item.promoted ? labels.memoryPromoted : labels.memoryPending}
                          </span>
                        </div>
                      ))}
                    </div>
                    {memoryEvidence.some((item) => !item.promoted) ? (
                      <p className="mt-2 text-[11px] text-fg-subtle">{labels.memoryPendingHint(memoryThreshold)}</p>
                    ) : null}
                  </details>
                ) : null}
              </div>
            ) : null}
            <div className="mt-4">
              <p className="text-xs font-semibold text-fg-muted">{labels.memoryManualTitle}</p>
              <p className="mt-0.5 text-[11px] text-fg-subtle">{labels.memoryHint}</p>
            </div>
            <div className="mt-2 grid gap-3 md:grid-cols-2">
              {memoryFields.map((field) => (
                <label key={field.key} className={cn("block text-xs font-medium text-fg-muted", field.key === "other_preferences" ? "md:col-span-2" : "")}>
                  {field.label}
                  <textarea
                    value={memoryForm[field.key]}
                    onChange={(e) => updateMemoryField(field.key, e.target.value)}
                    rows={1}
                    disabled={memoryLoading}
                    placeholder={memoryLoading ? labels.loading : field.label}
                    className="mt-1 w-full resize-none rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-subtle focus:border-accent disabled:opacity-60"
                  />
                </label>
              ))}
            </div>
            {memoryError ? <p className="mt-3 text-xs text-danger">{memoryError}</p> : null}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmClearMemory(true)}
                disabled={memorySaving || memoryLoading}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-danger px-4 py-2 text-sm font-medium text-white transition-all duration-150 ease-macos hover:shadow-lg hover:shadow-danger/20 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Trash2 size={15} />
                {labels.memoryClear}
              </button>
              <button type="button" onClick={saveMemory} disabled={memorySaving || memoryLoading} className="btn-accent px-4 py-2 text-sm disabled:cursor-not-allowed">
                <Check size={15} />
                {memorySaving ? t.saving : labels.memorySave}
              </button>
            </div>
          </section>
        </div>
      </div>
      {confirmClearMemory ? (
        <ConfirmDialog
          title={labels.memoryClearTitle}
          body={labels.memoryClearBody}
          confirmLabel={labels.memoryClear}
          danger
          onCancel={() => setConfirmClearMemory(false)}
          onConfirm={clearMemory}
        />
      ) : null}
    </Modal>
  );
}

function ProfileDialog({
  user,
  onClose,
  onSaved,
}: {
  user: UserProfile;
  onClose: () => void;
  onSaved: (user: UserProfile) => void;
}) {
  const { locale, t } = useI18n();
  const accountContact = contactFromAccount(user.account);
  const [form, setForm] = useState<ProfilePayload>({
    username: user.username,
    avatar: user.avatar,
    phone: user.phone ?? accountContact.phone ?? "",
    email: user.email ?? accountContact.email ?? "",
    company: user.company ?? "",
    title: user.title ?? "",
    bio: user.bio ?? "",
    password: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function set<K extends keyof ProfilePayload>(key: K, value: ProfilePayload[K]) {
    setForm((old) => ({ ...old, [key]: value }));
  }

  async function save() {
    setError(null);
    setBusy(true);
    try {
      const next = await updateMe(form);
      if (form.password) {
        updateRememberedAccount(user.account, {
          username: next.username,
          avatar: next.avatar,
          password: form.password,
        });
      } else {
        updateRememberedAccount(user.account, {
          username: next.username,
          avatar: next.avatar,
        });
      }
      onSaved(next);
    } catch (err) {
      setError(localizeError(err, locale));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={t.profile} onClose={onClose}>
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm text-fg-muted">{t.loginAccount}: {user.account}</p>
          <p className="text-sm text-fg-muted">{t.realName}: {user.real_name}</p>
          <p className="text-sm text-fg-muted">{t.idCard}: {user.id_card_masked}</p>
        </div>
        <AvatarPicker avatar={form.avatar ?? null} onChange={(avatar) => set("avatar", avatar)} />
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <TextInput label={t.usernameHint} value={form.username} onChange={(v) => set("username", v)} placeholder={t.usernameHint} />
        <TextInput label={t.changePassword} type="password" value={form.password ?? ""} onChange={(v) => set("password", v)} placeholder={t.keepBlankPassword} />
        <TextInput label={t.phone} value={form.phone ?? ""} onChange={(v) => set("phone", v)} placeholder={t.phoneHint} />
        <TextInput label={t.email} value={form.email ?? ""} onChange={(v) => set("email", v)} placeholder={t.emailHint} />
        <TextInput label={t.company} value={form.company ?? ""} onChange={(v) => set("company", v)} placeholder={t.companyHint} />
        <TextInput label={t.title} value={form.title ?? ""} onChange={(v) => set("title", v)} placeholder={t.titleHint} />
        <label className="md:col-span-2 text-xs font-medium text-fg-muted">
          {t.bio}
          <textarea
            value={form.bio ?? ""}
            onChange={(e) => set("bio", e.target.value)}
            rows={3}
            placeholder={t.bioHint}
            className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
          />
        </label>
      </div>
      {error ? <p className="mt-3 text-xs text-danger">{error}</p> : null}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle">
          {t.cancel}
        </button>
        <button type="button" onClick={save} disabled={busy} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-40">
          {busy ? t.saving : t.save}
        </button>
      </div>
    </Modal>
  );
}

function DeleteAccountDialog({
  account,
  onClose,
  onDeleted,
}: {
  account: string;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const { locale, t } = useI18n();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const enabled = text.trim() === t.deleteAccountConfirmText;

  async function submit() {
    setError(null);
    try {
      await deleteMe("我确认注销账号");
      removeRememberedAccount(account);
      onDeleted();
    } catch (err) {
      setError(localizeError(err, locale));
    }
  }

  return (
    <Modal title={t.deleteAccount} onClose={onClose}>
      <div className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-fg-muted">
        {t.deleteAccountNotice}
      </div>
      <TextInput label={t.deleteAccountConfirmLabel} value={text} onChange={setText} className="mt-4" />
      {error ? <p className="mt-3 text-xs text-danger">{error}</p> : null}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle">
          {t.cancel}
        </button>
        <button type="button" onClick={submit} disabled={!enabled} className="rounded-lg bg-danger px-4 py-2 text-sm font-medium text-white disabled:opacity-40">
          {t.confirmDeleteAccount}
        </button>
      </div>
    </Modal>
  );
}

function AvatarPicker({ avatar, onChange }: { avatar: string | null; onChange: (avatar: string | null) => void }) {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div className="flex items-center gap-3">
      <AvatarImage avatar={avatar} className="h-14 w-14" />
      <div className="space-y-1">
        <button type="button" onClick={() => inputRef.current?.click()} className="block rounded-lg border border-border px-3 py-1.5 text-xs text-fg-muted hover:bg-bg-subtle">
          {t.setAvatar}
        </button>
        {avatar ? (
          <button type="button" onClick={() => onChange(null)} className="block text-xs text-fg-subtle hover:text-danger">
            {t.useDefaultAvatar}
          </button>
        ) : null}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          const reader = new FileReader();
          reader.onload = () => onChange(String(reader.result));
          reader.readAsDataURL(file);
        }}
      />
    </div>
  );
}

function TextInput({
  label,
  value,
  onChange,
  type = "text",
  autoComplete,
  placeholder,
  error,
  className,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  autoComplete?: string;
  placeholder?: string;
  error?: string;
  className?: string;
}) {
  return (
    <label className={cn("block text-xs font-medium text-fg-muted", className)}>
      {label}
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        placeholder={placeholder}
        className={cn(
          "mt-1 w-full rounded-lg border bg-bg px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-subtle focus:border-accent",
          error ? "border-danger" : "border-border",
        )}
      />
      {error ? <span className="mt-1 block text-[11px] text-danger">{error}</span> : null}
    </label>
  );
}

function InfoDialog({ title, body, onClose }: { title: string; body: string; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <Modal title={title} onClose={onClose}>
      <p className="text-sm text-fg-muted">{body}</p>
      <div className="mt-5 flex justify-end">
        <button type="button" onClick={onClose} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg">
          {t.ok}
        </button>
      </div>
    </Modal>
  );
}

function ConfirmDialog({
  title,
  body,
  confirmLabel,
  danger,
  onCancel,
  onConfirm,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  danger?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  return (
    <Modal title={title} onClose={onCancel}>
      <p className="text-sm text-fg-muted">{body}</p>
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle">
          {t.cancel}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          className={cn("rounded-lg px-4 py-2 text-sm font-medium text-white", danger ? "bg-danger" : "bg-accent")}
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

function isValidChinaId(id: string): boolean {
  const value = id.trim().toUpperCase();
  if (!/^\d{17}[\dX]$/.test(value)) return false;
  const birth = value.slice(6, 14);
  const year = Number(birth.slice(0, 4));
  const month = Number(birth.slice(4, 6));
  const day = Number(birth.slice(6, 8));
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return false;
  const weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2];
  const checks = "10X98765432";
  const total = weights.reduce((sum, weight, index) => sum + Number(value[index]) * weight, 0);
  return checks[total % 11] === value[17];
}
