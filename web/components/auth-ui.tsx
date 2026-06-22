"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
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

const REMEMBERED_KEY = "marketing-agent-remembered-accounts";

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

export function rememberAccount(item: RememberedAccount) {
  const next = [item, ...loadRememberedAccounts().filter((old) => old.account !== item.account)];
  saveRememberedAccounts(next.slice(0, 8));
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
  if (!avatar) return <DefaultAvatar className={className} />;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={avatar}
      alt={label ?? "User avatar"}
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
  return (
    <main className="min-h-screen bg-bg text-fg flex flex-col">
      <header className="border-b border-border bg-bg-elevated/60 backdrop-blur">
        <div className="px-4 py-3 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-accent text-accent-fg flex items-center justify-center">
            <Sparkles size={16} />
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-tight">Marketing Agent</h1>
            <p className="text-[11px] text-fg-subtle">Account workspace</p>
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
    try {
      const res = await loginUser(account.trim(), password);
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
      setError(err instanceof Error ? err.message : String(err));
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
          title="选择记住的账号"
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
          <TextInput label="账号" value={account} onChange={setAccount} autoComplete="username" />
          <TextInput label="密码" value={password} onChange={setPassword} type="password" autoComplete="current-password" />
          <label className="flex items-center gap-2 text-sm text-fg-muted">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="h-4 w-4 accent-accent"
            />
            记住我
          </label>
          {error ? <p className="text-xs text-danger">{error}</p> : null}
          <button
            type="button"
            onClick={submit}
            disabled={busy || !account.trim() || !password}
            className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-accent-fg disabled:opacity-40"
          >
            {busy ? "登录中..." : "登录"}
          </button>
          <button
            type="button"
            onClick={onRegister}
            className="w-full rounded-lg border border-border px-4 py-2.5 text-sm font-medium text-fg-muted hover:bg-bg-subtle"
          >
            注册账号
          </button>
        </div>
      </section>
      {deleteTarget ? (
        <ConfirmDialog
          title="删除记住的账号"
          body={`仅从当前设备删除 ${deleteTarget.account} 的记住记录，数据库账号不会被删除。`}
          confirmLabel="删除"
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
  const [form, setForm] = useState<ProfilePayload>({
    account: "",
    password: "",
    username: "",
    real_name: "",
    id_card: "",
    avatar: null,
    phone: "",
    email: "",
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
      setError("身份证号格式或校验位不正确。");
      return;
    }
    setBusy(true);
    try {
      const res = await registerUser(form);
      setAuthToken(res.token);
      onAuthenticated(res.token, res.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell>
      <section className="w-full max-w-2xl rounded-xl border border-border bg-bg-elevated p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold">注册账号</h2>
            <p className="text-xs text-fg-subtle">带 * 的项目为必填。</p>
          </div>
          <AvatarPicker avatar={form.avatar ?? null} onChange={(avatar) => set("avatar", avatar)} />
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          <TextInput label="账号 *" value={form.account ?? ""} onChange={(v) => set("account", v)} />
          <TextInput label="密码 *" type="password" value={form.password ?? ""} onChange={(v) => set("password", v)} />
          <TextInput label="用户名 *" value={form.username} onChange={(v) => set("username", v)} />
          <TextInput label="真实姓名 *" value={form.real_name ?? ""} onChange={(v) => set("real_name", v)} />
          <TextInput label="身份证号 *" value={form.id_card ?? ""} onChange={(v) => set("id_card", v.toUpperCase())} error={form.id_card && !idCardValid ? "身份证号格式或校验位不正确" : undefined} />
          <TextInput label="手机号" value={form.phone ?? ""} onChange={(v) => set("phone", v)} />
          <TextInput label="邮箱" value={form.email ?? ""} onChange={(v) => set("email", v)} />
          <TextInput label="公司" value={form.company ?? ""} onChange={(v) => set("company", v)} />
          <TextInput label="职位" value={form.title ?? ""} onChange={(v) => set("title", v)} />
          <label className="md:col-span-2 text-xs font-medium text-fg-muted">
            简介
            <textarea
              value={form.bio ?? ""}
              onChange={(e) => set("bio", e.target.value)}
              rows={3}
              className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
            />
          </label>
        </div>
        {error ? <p className="mt-3 text-xs text-danger">{error}</p> : null}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onBack} className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle">
            返回登录
          </button>
          <button type="button" onClick={submit} disabled={busy} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-40">
            {busy ? "提交中..." : "完成注册"}
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
  const [open, setOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [placeholder, setPlaceholder] = useState<string | null>(null);

  const menuItems = [
    { label: "设置", icon: Settings, onClick: () => setPlaceholder("设置") },
    { label: "切换账号", icon: UserRoundCog, onClick: onSwitchAccount },
    { label: "个人信息", icon: UserRound, onClick: () => setProfileOpen(true) },
    { label: "订阅套餐", icon: WalletCards, onClick: () => setPlaceholder("订阅套餐") },
    { label: "帮助", icon: HelpCircle, onClick: () => setPlaceholder("帮助") },
    { label: "退出登录", icon: LogOut, onClick: onLogout },
    { label: "注销账号", icon: ShieldAlert, danger: true, onClick: () => setDeleteOpen(true) },
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
          body={`${placeholder}功能入口已预留，后续可在这里接入完整业务内容。`}
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
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <aside className="fixed right-4 top-20 z-30 w-72 rounded-xl border border-border bg-bg-elevated p-3 shadow-xl">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold">切换账号</h3>
          <button type="button" onClick={onClose} className="text-xs text-fg-subtle hover:text-fg">
            关闭
          </button>
        </div>
        <RememberedList items={items} onPick={pick} onDelete={(item) => setDeleteTarget(item)} />
        {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}
      </aside>
      {deleteTarget ? (
        <ConfirmDialog
          title="删除记住的账号"
          body={`仅从当前设备删除 ${deleteTarget.account} 的记住记录。`}
          confirmLabel="删除"
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
  if (items.length === 0) {
    return <p className="px-2 py-4 text-center text-xs text-fg-subtle">当前设备暂无记住的账号。</p>;
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
            title="删除记住记录"
          >
            <Minus size={14} />
          </button>
        </div>
      ))}
    </div>
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
  const [form, setForm] = useState<ProfilePayload>({
    username: user.username,
    avatar: user.avatar,
    phone: user.phone ?? "",
    email: user.email ?? "",
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
      onSaved(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="个人信息" onClose={onClose}>
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm text-fg-muted">账号：{user.account}</p>
          <p className="text-sm text-fg-muted">实名：{user.real_name}</p>
          <p className="text-sm text-fg-muted">身份证：{user.id_card_masked}</p>
        </div>
        <AvatarPicker avatar={form.avatar ?? null} onChange={(avatar) => set("avatar", avatar)} />
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <TextInput label="用户名" value={form.username} onChange={(v) => set("username", v)} />
        <TextInput label="修改密码" type="password" value={form.password ?? ""} onChange={(v) => set("password", v)} placeholder="留空则不修改" />
        <TextInput label="手机号" value={form.phone ?? ""} onChange={(v) => set("phone", v)} />
        <TextInput label="邮箱" value={form.email ?? ""} onChange={(v) => set("email", v)} />
        <TextInput label="公司" value={form.company ?? ""} onChange={(v) => set("company", v)} />
        <TextInput label="职位" value={form.title ?? ""} onChange={(v) => set("title", v)} />
        <label className="md:col-span-2 text-xs font-medium text-fg-muted">
          简介
          <textarea
            value={form.bio ?? ""}
            onChange={(e) => set("bio", e.target.value)}
            rows={3}
            className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
          />
        </label>
      </div>
      {error ? <p className="mt-3 text-xs text-danger">{error}</p> : null}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle">
          取消
        </button>
        <button type="button" onClick={save} disabled={busy} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-40">
          {busy ? "保存中..." : "保存"}
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
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const enabled = text.trim() === "我确认注销账号";

  async function submit() {
    setError(null);
    try {
      await deleteMe(text.trim());
      removeRememberedAccount(account);
      onDeleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <Modal title="注销账号" onClose={onClose}>
      <div className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-fg-muted">
        注销后会删除该账号和所有会话、上传文件、生成材料，且无法恢复。
      </div>
      <TextInput label="请输入：我确认注销账号" value={text} onChange={setText} className="mt-4" />
      {error ? <p className="mt-3 text-xs text-danger">{error}</p> : null}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle">
          取消
        </button>
        <button type="button" onClick={submit} disabled={!enabled} className="rounded-lg bg-danger px-4 py-2 text-sm font-medium text-white disabled:opacity-40">
          确认注销
        </button>
      </div>
    </Modal>
  );
}

function AvatarPicker({ avatar, onChange }: { avatar: string | null; onChange: (avatar: string | null) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div className="flex items-center gap-3">
      <AvatarImage avatar={avatar} className="h-14 w-14" />
      <div className="space-y-1">
        <button type="button" onClick={() => inputRef.current?.click()} className="block rounded-lg border border-border px-3 py-1.5 text-xs text-fg-muted hover:bg-bg-subtle">
          设置头像
        </button>
        {avatar ? (
          <button type="button" onClick={() => onChange(null)} className="block text-xs text-fg-subtle hover:text-danger">
            使用默认头像
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
          "mt-1 w-full rounded-lg border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent",
          error ? "border-danger" : "border-border",
        )}
      />
      {error ? <span className="mt-1 block text-[11px] text-danger">{error}</span> : null}
    </label>
  );
}

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <section className="w-full max-w-2xl rounded-xl border border-border bg-bg-elevated p-5 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">{title}</h2>
          <button type="button" onClick={onClose} className="text-sm text-fg-subtle hover:text-fg">
            关闭
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

function InfoDialog({ title, body, onClose }: { title: string; body: string; onClose: () => void }) {
  return (
    <Modal title={title} onClose={onClose}>
      <p className="text-sm text-fg-muted">{body}</p>
      <div className="mt-5 flex justify-end">
        <button type="button" onClick={onClose} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg">
          知道了
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
  return (
    <Modal title={title} onClose={onCancel}>
      <p className="text-sm text-fg-muted">{body}</p>
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle">
          取消
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
