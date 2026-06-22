"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ChevronDown,
  HelpCircle,
  LogOut,
  Minus,
  Settings,
  ShieldAlert,
  Sparkles,
  UserRound,
  UserRoundCog,
  WalletCards,
} from "lucide-react";
import {
  deleteMe,
  loginUser,
  lookupAvatar,
  registerUser,
  setAuthToken,
  updateMe,
  type ProfilePayload,
  type UserProfile,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { LanguageToggle, localizeError, useI18n } from "@/lib/i18n";

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
        setError(t.rememberedPasswordExpired);
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
          className="inline-flex items-center gap-2 rounded-full border border-border bg-bg-elevated px-1.5 py-1 hover:bg-bg-subtle"
        >
          <AvatarImage avatar={user.avatar} className="h-8 w-8" label={user.username} />
          <ChevronDown size={14} className="text-fg-muted" />
        </button>
        {open ? (
          <div className="absolute right-0 top-11 z-30 w-52 rounded-xl border border-border bg-bg-elevated p-1.5 shadow-lg">
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
      {settingsOpen ? <SettingsDialog onClose={() => setSettingsOpen(false)} /> : null}
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
      setError(t.rememberedPasswordExpired);
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

function SettingsDialog({ onClose }: { onClose: () => void }) {
  const { locale, setLocale, t } = useI18n();
  return (
    <Modal title={t.settings} onClose={onClose}>
      <div className="flex items-center justify-between rounded-lg border border-border bg-bg p-3">
        <div>
          <p className="text-sm font-medium">{t.language}</p>
          <p className="text-xs text-fg-subtle">{locale === "zh" ? t.chinese : t.english}</p>
        </div>
        <div className="inline-flex rounded-lg border border-border bg-bg-elevated p-1">
          <button
            type="button"
            onClick={() => setLocale("zh")}
            className={cn("rounded-md px-3 py-1.5 text-xs", locale === "zh" ? "bg-accent text-accent-fg" : "text-fg-muted")}
          >
            {t.chinese}
          </button>
          <button
            type="button"
            onClick={() => setLocale("en")}
            className={cn("rounded-md px-3 py-1.5 text-xs", locale === "en" ? "bg-accent text-accent-fg" : "text-fg-muted")}
          >
            {t.english}
          </button>
        </div>
      </div>
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

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  const { t } = useI18n();
  if (typeof document === "undefined") return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <section className="w-full max-w-2xl max-h-[calc(100vh-2rem)] overflow-y-auto rounded-xl border border-border bg-bg-elevated p-5 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">{title}</h2>
          <button type="button" onClick={onClose} className="text-sm text-fg-subtle hover:text-fg">
            {t.close}
          </button>
        </div>
        {children}
      </section>
    </div>,
    document.body,
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
