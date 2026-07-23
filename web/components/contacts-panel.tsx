"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Contact,
  Users,
  Building2,
  UserPlus,
  Star,
  Mail,
  UsersRound,
  MessageSquare,
  Trash2,
  Check,
  X,
  Copy,
  Loader2,
} from "lucide-react";
import {
  acceptContactRequest,
  addConversationMembers,
  addExternalContact,
  addOrgMember,
  createConversation,
  createOrg,
  deleteExternalContact,
  getOrg,
  getStarredContacts,
  joinOrg,
  leaveOrg,
  listContactRequests,
  listConversationMembers,
  listConversations,
  listExternalContacts,
  listOrgMembers,
  rejectContactRequest,
  starMember,
  unstarMember,
  updateExternalContact,
  type Conversation,
  type ContactRequest,
  type ExternalContact,
  type OrgInfo,
  type OrgMember,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";
import type { I18nText } from "@/lib/i18n";
import { Modal } from "@/components/modal";
import { Skeleton } from "@/components/ui/skeleton";

type CategoryKey = "org" | "external" | "new" | "starred" | "mailbox" | "groups";

type DialogKind =
  | null
  | "add-org"
  | "add-external"
  | "add-request"
  | "add-mailbox"
  | "star"
  | "create-group";

function categories(t: I18nText) {
  return [
    { key: "org" as const, label: t.contactsOrgMembers, icon: Users },
    { key: "external" as const, label: t.contactsExternal, icon: UserPlus },
    { key: "new" as const, label: t.contactsNew, icon: Contact },
    { key: "starred" as const, label: t.contactsStarred, icon: Star },
    { key: "mailbox" as const, label: t.contactsMailbox, icon: Mail },
    { key: "groups" as const, label: t.contactsMyGroups, icon: UsersRound },
  ];
}

function initial(name: string | null | undefined): string {
  const s = (name || "").trim();
  return s ? s[0].toUpperCase() : "?";
}

function headerAddLabel(category: CategoryKey, t: I18nText): string {
  switch (category) {
    case "org":
      return t.addMember;
    case "external":
      return t.addExternalContact;
    case "new":
      return t.addContactAction;
    case "mailbox":
      return t.addMailboxContact;
    case "starred":
      return t.chooseStarred;
    case "groups":
      return t.createGroupAction;
  }
}

export function ContactsPanel({
  onBack,
  halfWidth,
  meId,
  onMessageUser,
}: {
  onBack: () => void;
  halfWidth: number;
  meId: string;
  onMessageUser: (peerId: string) => void;
}) {
  const { locale, t } = useI18n();
  const [category, setCategory] = useState<CategoryKey>("org");
  const [org, setOrg] = useState<OrgInfo | null>(null);
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [externals, setExternals] = useState<ExternalContact[]>([]);
  const [requests, setRequests] = useState<{ incoming: ContactRequest[]; outgoing: ContactRequest[] }>({
    incoming: [],
    outgoing: [],
  });
  const [starred, setStarred] = useState<{ members: OrgMember[]; externals: ExternalContact[] }>({
    members: [],
    externals: [],
  });
  const [starredIds, setStarredIds] = useState<Set<string>>(new Set());
  const [groups, setGroups] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<DialogKind>(null);
  const [manageOpen, setManageOpen] = useState(false);
  const [groupDetail, setGroupDetail] = useState<Conversation | null>(null);

  const cats = categories(t);
  const active = cats.find((c) => c.key === category);

  const loadHeader = useCallback(async () => {
    try {
      setOrg(await getOrg());
    } catch (e) {
      setError(localizeError(e, locale));
    }
  }, [locale]);

  const load = useCallback(
    async (cat: CategoryKey) => {
      setLoading(true);
      setError(null);
      try {
        if (cat === "org") {
          const [r, s] = await Promise.all([listOrgMembers(), getStarredContacts()]);
          setOrg(r.org);
          setMembers(r.members);
          setStarredIds(new Set(s.members.map((m) => m.id)));
        } else if (cat === "external" || cat === "mailbox") {
          setExternals(await listExternalContacts());
        } else if (cat === "new") {
          setRequests(await listContactRequests());
        } else if (cat === "starred") {
          setStarred(await getStarredContacts());
        } else if (cat === "groups") {
          setGroups(await listConversations("group"));
        }
      } catch (e) {
        setError(localizeError(e, locale));
      } finally {
        setLoading(false);
      }
    },
    [locale],
  );

  useEffect(() => {
    void loadHeader();
  }, [loadHeader]);

  useEffect(() => {
    void load(category);
  }, [category, load]);

  async function toggleStarMember(memberId: string, on: boolean) {
    try {
      if (on) await starMember(memberId);
      else await unstarMember(memberId);
      await load(category);
    } catch (e) {
      setError(localizeError(e, locale));
    }
  }

  async function toggleStarExternal(c: ExternalContact) {
    try {
      await updateExternalContact(c.id, { starred: !c.starred });
      await load(category);
    } catch (e) {
      setError(localizeError(e, locale));
    }
  }

  async function removeExternal(id: string) {
    if (!window.confirm(t.imageDeleteConfirm)) return;
    try {
      await deleteExternalContact(id);
      await load(category);
    } catch (e) {
      setError(localizeError(e, locale));
    }
  }

  async function respondRequest(id: string, accept: boolean) {
    try {
      if (accept) await acceptContactRequest(id);
      else await rejectContactRequest(id);
      await load("new");
    } catch (e) {
      setError(localizeError(e, locale));
    }
  }

  return (
    <>
      <aside className="flex-1 min-w-0 flex flex-col panel-card">
        <header className="col-header">
          <button onClick={onBack} className="btn-ghost px-2.5 py-1.5 text-sm">
            <ArrowLeft size={15} />
            <span>{t.back}</span>
          </button>
          <div className="flex items-center gap-2 mx-auto text-sm font-medium">
            <Contact size={15} className="text-feature-image" />
            <span>{t.contacts}</span>
          </div>
          <div className="w-[64px]" aria-hidden />
        </header>

        <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border">
          <span className="w-6 h-6 rounded-md bg-accent/15 text-accent flex items-center justify-center shrink-0">
            <Building2 size={14} />
          </span>
          <span className="truncate flex-1 text-sm font-medium" title={org?.name}>
            {org?.name ?? t.contacts}
          </span>
          <button onClick={() => setManageOpen(true)} className="btn-ghost px-2 py-1 text-xs text-accent">
            {t.contactsManage}
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5">
          {cats.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setCategory(key)}
              className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left text-sm transition-colors ${
                category === key ? "bg-accent/15 text-fg" : "text-fg-muted hover:bg-bg-elevated hover:text-fg"
              }`}
            >
              <Icon size={15} className={`shrink-0 ${category === key ? "text-accent" : "opacity-70"}`} />
              <span className="truncate flex-1">{label}</span>
              {key === "new" && requests.incoming.length > 0 ? (
                <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-danger text-white text-[10px] font-semibold flex items-center justify-center">
                  {requests.incoming.length}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      </aside>

      <section className="shrink-0 flex flex-col panel-card" style={{ width: halfWidth }}>
        <header className="col-header">
          <div className="flex items-center gap-2 text-sm font-medium">
            {active ? <active.icon size={15} className="text-feature-image" /> : null}
            <span>{active?.label}</span>
          </div>
          <button
            onClick={() => {
              if (category === "org") setDialog("add-org");
              else if (category === "external") setDialog("add-external");
              else if (category === "new") setDialog("add-request");
              else if (category === "mailbox") setDialog("add-mailbox");
              else if (category === "starred") setDialog("star");
              else setDialog("create-group");
            }}
            className="btn-accent ml-auto px-3 py-1.5 text-xs"
          >
            <UserPlus size={13} />
            <span>{headerAddLabel(category, t)}</span>
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-3 py-3">
          {error ? <p className="mb-3 text-sm text-danger">{error}</p> : null}
          {loading ? (
            <ContactListSkeleton />
          ) : category === "org" ? (
            members.length === 0 ? (
              <Empty text={t.noMembers} />
            ) : (
              members.map((m) => (
                <PersonRow
                  key={m.id}
                  name={m.username || m.real_name || m.account || ""}
                  avatar={m.avatar}
                  subtitle={[m.company, roleLabel(m.role, t)].filter(Boolean).join(" · ")}
                  starred={starredIds.has(m.id)}
                  onStar={m.id === meId ? undefined : (on) => toggleStarMember(m.id, on)}
                  onMessage={m.id === meId ? undefined : () => onMessageUser(m.id)}
                />
              ))
            )
          ) : category === "external" ? (
            externals.length === 0 ? (
              <Empty text={t.noExternalContacts} />
            ) : (
              externals.map((c) => (
                <PersonRow
                  key={c.id}
                  name={c.name}
                  avatar={c.avatar}
                  subtitle={[c.company, c.email].filter(Boolean).join(" · ")}
                  starred={c.starred}
                  onStar={() => toggleStarExternal(c)}
                  onMessage={c.contact_user_id ? () => onMessageUser(c.contact_user_id!) : undefined}
                  onDelete={() => removeExternal(c.id)}
                />
              ))
            )
          ) : category === "mailbox" ? (
            externals.filter((c) => c.email).length === 0 ? (
              <Empty text={t.noMailboxContacts} />
            ) : (
              externals
                .filter((c) => c.email)
                .map((c) => (
                  <PersonRow
                    key={c.id}
                    name={c.name}
                    avatar={c.avatar}
                    subtitle={c.email || ""}
                    onMessage={c.contact_user_id ? () => onMessageUser(c.contact_user_id!) : undefined}
                  />
                ))
            )
          ) : category === "new" ? (
            requests.incoming.length === 0 && requests.outgoing.length === 0 ? (
              <Empty text={t.noNewContacts} />
            ) : (
              <>
                {requests.incoming.map((r) => (
                  <div key={r.id} className="flex items-center gap-2.5 px-2 py-2.5 border-b border-border/60">
                    <Avatar name={r.username || r.real_name} avatar={r.avatar} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{r.username || r.real_name}</div>
                      <div className="truncate text-xs text-fg-subtle">{t.requestFrom}</div>
                    </div>
                    <button onClick={() => respondRequest(r.id, true)} className="btn-accent px-2.5 py-1 text-xs">
                      <Check size={12} />
                      {t.accept}
                    </button>
                    <button
                      onClick={() => respondRequest(r.id, false)}
                      className="btn-ghost px-2.5 py-1 text-xs border border-border"
                    >
                      <X size={12} />
                      {t.reject}
                    </button>
                  </div>
                ))}
                {requests.outgoing.map((r) => (
                  <div key={r.id} className="flex items-center gap-2.5 px-2 py-2.5 border-b border-border/60">
                    <Avatar name={r.username || r.real_name} avatar={r.avatar} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{r.username || r.real_name}</div>
                      <div className="truncate text-xs text-fg-subtle">{t.requestPending}</div>
                    </div>
                  </div>
                ))}
              </>
            )
          ) : category === "starred" ? (
            starred.members.length === 0 && starred.externals.length === 0 ? (
              <Empty text={t.noStarredContacts} />
            ) : (
              <>
                {starred.members.map((m) => (
                  <PersonRow
                    key={`m-${m.id}`}
                    name={m.username || m.real_name || ""}
                    avatar={m.avatar}
                    subtitle={m.company || ""}
                    starred
                    onStar={m.id === meId ? undefined : () => toggleStarMember(m.id, false)}
                    onMessage={m.id === meId ? undefined : () => onMessageUser(m.id)}
                  />
                ))}
                {starred.externals.map((c) => (
                  <PersonRow
                    key={`e-${c.id}`}
                    name={c.name}
                    avatar={c.avatar}
                    subtitle={[c.company, c.email].filter(Boolean).join(" · ")}
                    starred
                    onStar={() => toggleStarExternal(c)}
                    onMessage={c.contact_user_id ? () => onMessageUser(c.contact_user_id!) : undefined}
                  />
                ))}
              </>
            )
          ) : groups.length === 0 ? (
            <Empty text={t.noGroups} />
          ) : (
            groups.map((g) => (
              <button
                key={g.id}
                onClick={() => setGroupDetail(g)}
                className="w-full flex items-center gap-2.5 px-2 py-2.5 border-b border-border/60 text-left hover:bg-bg-elevated rounded-lg"
              >
                <Avatar name={g.title} icon={<UsersRound size={16} />} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{g.title || "群聊"}</div>
                  <div className="truncate text-xs text-fg-subtle">{g.member_count}</div>
                </div>
              </button>
            ))
          )}
        </div>
      </section>

      {dialog === "add-org" ? (
        <AddMemberDialog
          onClose={() => setDialog(null)}
          onDone={async () => {
            setDialog(null);
            await loadHeader();
            await load("org");
          }}
        />
      ) : null}

      {dialog === "add-external" || dialog === "add-request" || dialog === "add-mailbox" ? (
        <AddContactDialog
          title={
            dialog === "add-external"
              ? t.addExternalContact
              : dialog === "add-request"
                ? t.addContactAction
                : t.addMailboxContact
          }
          accountOnly={dialog === "add-request"}
          onClose={() => setDialog(null)}
          onDone={async () => {
            setDialog(null);
            await load(category);
          }}
        />
      ) : null}

      {dialog === "star" ? (
        <StarPickerDialog
          meId={meId}
          onClose={async () => {
            setDialog(null);
            await load(category);
          }}
        />
      ) : null}

      {dialog === "create-group" ? (
        <CreateGroupDialog
          meId={meId}
          onClose={() => setDialog(null)}
          onDone={async () => {
            setDialog(null);
            await load("groups");
          }}
        />
      ) : null}

      {groupDetail ? (
        <GroupDetailDialog
          group={groupDetail}
          meId={meId}
          onEnter={() => {
            const id = groupDetail.id;
            setGroupDetail(null);
            onMessageUser(`conversation:${id}`);
          }}
          onClose={() => setGroupDetail(null)}
        />
      ) : null}

      {manageOpen && org ? (
        <ManageOrgDialog
          org={org}
          onClose={() => setManageOpen(false)}
          onChanged={async () => {
            await loadHeader();
            await load(category);
          }}
        />
      ) : null}
    </>
  );
}

function roleLabel(role: string | null, t: I18nText): string {
  if (role === "owner") return t.roleOwner;
  if (role === "admin") return t.roleAdmin;
  if (role === "member") return t.roleMember;
  return "";
}

function Empty({ text }: { text: string }) {
  return <p className="py-10 text-center text-sm text-fg-subtle">{text}</p>;
}

// Shimmer placeholder rows (same skeleton treatment as the news/image panels),
// staggered with a fade-in so loading feels lively rather than a static dash.
function ContactListSkeleton({ rows = 7 }: { rows?: number }) {
  return (
    <div className="space-y-0.5">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-2.5 px-2 py-2.5 animate-fade-in"
          style={{ animationDelay: `${i * 60}ms` }}
        >
          <Skeleton className="w-9 h-9 !rounded-full shrink-0" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5" style={{ width: `${45 + ((i * 13) % 30)}%` }} />
            <Skeleton className="h-2.5" style={{ width: `${60 + ((i * 7) % 25)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function Avatar({
  name,
  avatar,
  icon,
}: {
  name?: string | null;
  avatar?: string | null;
  icon?: React.ReactNode;
}) {
  if (avatar) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={avatar} alt="" className="w-9 h-9 rounded-full object-cover shrink-0" />;
  }
  return (
    <span className="w-9 h-9 rounded-full bg-accent/15 text-accent flex items-center justify-center text-sm font-medium shrink-0">
      {icon ?? initial(name)}
    </span>
  );
}

function PersonRow({
  name,
  subtitle,
  avatar,
  starred,
  icon,
  onStar,
  onMessage,
  onDelete,
}: {
  name: string;
  subtitle?: string;
  avatar?: string | null;
  starred?: boolean;
  icon?: React.ReactNode;
  onStar?: (on: boolean) => void;
  onMessage?: () => void;
  onDelete?: () => void;
}) {
  return (
    <div className="group flex items-center gap-2.5 px-2 py-2.5 border-b border-border/60">
      <Avatar name={name} avatar={avatar} icon={icon} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{name}</div>
        {subtitle ? <div className="truncate text-xs text-fg-subtle">{subtitle}</div> : null}
      </div>
      {onStar ? (
        <button onClick={() => onStar(!starred)} className="btn-ghost w-8 h-8" aria-label="star">
          <Star size={14} className={starred ? "fill-amber-400 text-amber-400" : "text-fg-subtle"} />
        </button>
      ) : null}
      {onMessage ? (
        <button onClick={onMessage} className="btn-ghost w-8 h-8" aria-label="message">
          <MessageSquare size={14} className="text-accent" />
        </button>
      ) : null}
      {onDelete ? (
        <button onClick={onDelete} className="btn-ghost w-8 h-8" aria-label="delete">
          <Trash2 size={14} className="text-danger" />
        </button>
      ) : null}
    </div>
  );
}

function AddMemberDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { locale, t } = useI18n();
  const [account, setAccount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (busy || !account.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await addOrgMember(account.trim());
      onDone();
    } catch (e) {
      setError(localizeError(e, locale));
      setBusy(false);
    }
  }

  return (
    <Modal title={t.addMember} onClose={onClose}>
      <div className="space-y-4">
        <label className="block text-xs font-medium text-fg-muted">
          {t.addContactByAccount}
          <input
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
          />
        </label>
        {error ? <p className="text-[11px] text-danger">{error}</p> : null}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle">
            {t.cancel}
          </button>
          <button onClick={() => void submit()} disabled={busy || !account.trim()} className="btn-accent px-4 py-2 text-sm">
            {busy ? <Loader2 size={14} className="animate-spin" /> : null}
            {t.addMember}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function AddContactDialog({
  title,
  accountOnly,
  onClose,
  onDone,
}: {
  title: string;
  accountOnly?: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const { locale, t } = useI18n();
  const [account, setAccount] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function submit() {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await addExternalContact({
        account: account.trim() || undefined,
        name: name.trim() || undefined,
        email: email.trim() || undefined,
        phone: phone.trim() || undefined,
      });
      if (res.mode === "request") {
        setNotice(t.contactRequestSent);
        setBusy(false);
        return;
      }
      onDone();
    } catch (e) {
      setError(localizeError(e, locale));
      setBusy(false);
    }
  }

  return (
    <Modal title={title} onClose={onClose}>
      <div className="space-y-4">
        <label className="block text-xs font-medium text-fg-muted">
          {t.addContactByAccount}
          <input
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
          />
        </label>
        {!accountOnly ? (
          <>
            <p className="text-[11px] text-fg-subtle">{t.addContactManualHint}</p>
            <label className="block text-xs font-medium text-fg-muted">
              {t.addContactName}
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
              />
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="block text-xs font-medium text-fg-muted">
                {t.email}
                <input
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
                />
              </label>
              <label className="block text-xs font-medium text-fg-muted">
                {t.phone}
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
                />
              </label>
            </div>
          </>
        ) : null}

        {error ? <p className="text-[11px] text-danger">{error}</p> : null}
        {notice ? <p className="text-[11px] text-success">{notice}</p> : null}

        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle">
            {t.close}
          </button>
          <button onClick={() => void submit()} disabled={busy} className="btn-accent px-4 py-2 text-sm">
            {busy ? <Loader2 size={14} className="animate-spin" /> : null}
            {title}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function StarPickerDialog({ meId, onClose }: { meId: string; onClose: () => void }) {
  const { locale, t } = useI18n();
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [externals, setExternals] = useState<ExternalContact[]>([]);
  const [starredMembers, setStarredMembers] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [r, ex, s] = await Promise.all([
        listOrgMembers(),
        listExternalContacts(),
        getStarredContacts(),
      ]);
      setMembers(r.members.filter((m) => m.id !== meId));
      setExternals(ex);
      setStarredMembers(new Set(s.members.map((m) => m.id)));
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setLoading(false);
    }
  }, [locale, meId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function toggleMember(id: string, on: boolean) {
    try {
      if (on) await starMember(id);
      else await unstarMember(id);
      await reload();
    } catch (e) {
      setError(localizeError(e, locale));
    }
  }

  async function toggleExternal(c: ExternalContact) {
    try {
      await updateExternalContact(c.id, { starred: !c.starred });
      await reload();
    } catch (e) {
      setError(localizeError(e, locale));
    }
  }

  const isEmpty = members.length === 0 && externals.length === 0;

  return (
    <Modal title={t.chooseStarred} onClose={onClose}>
      <div className="space-y-3">
        {error ? <p className="text-[11px] text-danger">{error}</p> : null}
        {loading ? (
          <p className="py-8 text-center text-sm text-fg-subtle">…</p>
        ) : isEmpty ? (
          <p className="py-8 text-center text-sm text-fg-subtle">{t.noContactsToStar}</p>
        ) : (
          <div className="max-h-72 overflow-y-auto rounded-lg border border-border divide-y divide-border">
            {members.map((m) => {
              const on = starredMembers.has(m.id);
              return (
                <StarRow
                  key={`m-${m.id}`}
                  name={m.username || m.real_name || ""}
                  avatar={m.avatar}
                  on={on}
                  onToggle={() => toggleMember(m.id, !on)}
                />
              );
            })}
            {externals.map((c) => (
              <StarRow
                key={`e-${c.id}`}
                name={c.name}
                avatar={c.avatar}
                on={c.starred}
                onToggle={() => toggleExternal(c)}
              />
            ))}
          </div>
        )}
        <div className="flex justify-end">
          <button onClick={onClose} className="btn-accent px-4 py-2 text-sm">
            {t.done}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function StarRow({
  name,
  avatar,
  on,
  onToggle,
}: {
  name: string;
  avatar?: string | null;
  on: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="flex items-center gap-2.5 px-3 py-2">
      <Avatar name={name} avatar={avatar} />
      <span className="flex-1 truncate text-sm">{name}</span>
      <button onClick={onToggle} className="btn-ghost w-8 h-8" aria-label="star">
        <Star size={15} className={on ? "fill-amber-400 text-amber-400" : "text-fg-subtle"} />
      </button>
    </div>
  );
}

function MemberPicker({
  meId,
  exclude,
  selected,
  onToggle,
}: {
  meId: string;
  exclude: Set<string>;
  selected: Set<string>;
  onToggle: (id: string) => void;
}) {
  const { t } = useI18n();
  const [all, setAll] = useState<OrgMember[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listOrgMembers()
      .then((r) => setAll(r.members.filter((m) => m.id !== meId)))
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, [meId]);

  // Filter at render time so just-invited members drop out immediately when the
  // parent's `exclude` set updates.
  const members = all.filter((m) => !exclude.has(m.id));

  if (loading) return <div className="p-4 text-center text-sm text-fg-subtle">…</div>;
  if (members.length === 0)
    return <div className="p-4 text-center text-sm text-fg-subtle">{t.noMembersToInvite}</div>;

  return (
    <>
      {members.map((m) => (
        <label key={m.id} className="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-bg-subtle">
          <input type="checkbox" checked={selected.has(m.id)} onChange={() => onToggle(m.id)} className="accent-accent" />
          <Avatar name={m.username || m.real_name} avatar={m.avatar} />
          <span className="text-sm text-fg">{m.username || m.real_name}</span>
        </label>
      ))}
    </>
  );
}

function CreateGroupDialog({
  meId,
  onClose,
  onDone,
}: {
  meId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { locale, t } = useI18n();
  const [title, setTitle] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const empty = useMemo(() => new Set<string>(), []);

  const canCreate = title.trim() && selected.size > 0;

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function submit() {
    if (!canCreate || busy) return;
    setBusy(true);
    setError(null);
    try {
      await createConversation({ type: "group", title: title.trim(), member_ids: Array.from(selected) });
      onDone();
    } catch (e) {
      setError(localizeError(e, locale));
      setBusy(false);
    }
  }

  return (
    <Modal title={t.createGroupAction} onClose={onClose}>
      <div className="space-y-4">
        <label className="block text-xs font-medium text-fg-muted">
          {t.groupChatName}
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
          />
        </label>
        <div className="text-xs font-medium text-fg-muted">{t.groupChatMembers}</div>
        <div className="max-h-56 overflow-y-auto rounded-lg border border-border divide-y divide-border">
          <MemberPicker meId={meId} exclude={empty} selected={selected} onToggle={toggle} />
        </div>
        {error ? <p className="text-[11px] text-danger">{error}</p> : null}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle">
            {t.cancel}
          </button>
          <button onClick={() => void submit()} disabled={!canCreate || busy} className="btn-accent px-4 py-2 text-sm">
            {busy ? <Loader2 size={14} className="animate-spin" /> : null}
            {t.createGroupAction}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function GroupDetailDialog({
  group,
  meId,
  onEnter,
  onClose,
}: {
  group: Conversation;
  meId: string;
  onEnter: () => void;
  onClose: () => void;
}) {
  const { locale, t } = useI18n();
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setMembers(await listConversationMembers(group.id));
    } catch (e) {
      setError(localizeError(e, locale));
    }
  }, [group.id, locale]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const memberIds = useMemo(() => new Set(members.map((m) => m.id)), [members]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function invite() {
    if (selected.size === 0 || busy) return;
    setBusy(true);
    setError(null);
    try {
      await addConversationMembers(group.id, { member_ids: Array.from(selected) });
      setSelected(new Set());
      await reload();
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={group.title || "群聊"} onClose={onClose}>
      <div className="space-y-4">
        <div className="text-xs font-medium text-fg-muted">
          {t.groupMembers} ({members.length})
        </div>
        <div className="max-h-40 overflow-y-auto rounded-lg border border-border divide-y divide-border">
          {members.map((m) => (
            <div key={m.id} className="flex items-center gap-2.5 px-3 py-2">
              <Avatar name={m.username || m.real_name} avatar={m.avatar} />
              <span className="flex-1 truncate text-sm">{m.username || m.real_name}</span>
              {m.role === "owner" ? <span className="text-[11px] text-fg-subtle">{t.roleOwner}</span> : null}
            </div>
          ))}
        </div>

        <div className="text-xs font-medium text-fg-muted">{t.inviteMembers}</div>
        <div className="max-h-40 overflow-y-auto rounded-lg border border-border divide-y divide-border">
          <MemberPicker meId={meId} exclude={memberIds} selected={selected} onToggle={toggle} />
        </div>

        {error ? <p className="text-[11px] text-danger">{error}</p> : null}

        <div className="flex items-center gap-2">
          <button onClick={onEnter} className="btn-ghost px-3 py-2 text-sm border border-border">
            <MessageSquare size={14} />
            {t.enterChat}
          </button>
          <div className="ml-auto flex gap-2">
            <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle">
              {t.close}
            </button>
            <button onClick={() => void invite()} disabled={selected.size === 0 || busy} className="btn-accent px-4 py-2 text-sm">
              {busy ? <Loader2 size={14} className="animate-spin" /> : null}
              {t.invite}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function ManageOrgDialog({
  org,
  onClose,
  onChanged,
}: {
  org: OrgInfo;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { locale, t } = useI18n();
  const [code, setCode] = useState("");
  const [newOrgName, setNewOrgName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function run(fn: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={t.contactsManage} onClose={onClose}>
      <div className="space-y-4 text-sm">
        <div>
          <div className="text-xs font-medium text-fg-muted">{org.name}</div>
          <div className="mt-1 flex items-center gap-2">
            <span className="text-xs text-fg-subtle">{t.inviteCode}:</span>
            <code className="rounded-md border border-border bg-bg-subtle px-2 py-1 text-xs">{org.invite_code}</code>
            <button
              onClick={() => {
                void navigator.clipboard?.writeText(org.invite_code);
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1500);
              }}
              className="btn-ghost px-2 py-1 text-xs"
            >
              <Copy size={12} />
              {copied ? t.inviteCodeCopied : t.copyInviteCode}
            </button>
          </div>
        </div>

        <div className="border-t border-border pt-3">
          <label className="block text-xs font-medium text-fg-muted">
            {t.joinOrg}
            <div className="mt-1 flex gap-2">
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder={t.inviteCode}
                className="flex-1 rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
              />
              <button onClick={() => void run(() => joinOrg(code.trim()))} disabled={busy || !code.trim()} className="btn-accent px-3 py-2 text-xs">
                {t.joinOrg}
              </button>
            </div>
          </label>
        </div>

        <div className="border-t border-border pt-3">
          <label className="block text-xs font-medium text-fg-muted">
            {t.createOrg}
            <div className="mt-1 flex gap-2">
              <input
                value={newOrgName}
                onChange={(e) => setNewOrgName(e.target.value)}
                className="flex-1 rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
              />
              <button onClick={() => void run(() => createOrg(newOrgName.trim()))} disabled={busy || !newOrgName.trim()} className="btn-ghost px-3 py-2 text-xs border border-border">
                {t.createOrg}
              </button>
            </div>
          </label>
        </div>

        {org.my_role !== "owner" ? (
          <div className="border-t border-border pt-3">
            <button
              onClick={() => {
                if (window.confirm(t.leaveOrgConfirm)) void run(() => leaveOrg());
              }}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-danger/40 px-4 py-2 text-sm text-danger hover:bg-danger/10"
            >
              {t.leaveOrg}
            </button>
          </div>
        ) : null}

        {error ? <p className="text-[11px] text-danger">{error}</p> : null}
      </div>
    </Modal>
  );
}
