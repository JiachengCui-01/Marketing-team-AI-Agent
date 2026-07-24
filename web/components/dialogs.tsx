"use client";

import { useCallback, useRef, useState } from "react";
import { Modal } from "@/components/modal";
import { useI18n } from "@/lib/i18n";

type PromptOpts = { title: string; defaultValue?: string; placeholder?: string; confirmLabel?: string };
type ConfirmOpts = { title: string; body?: string; confirmLabel?: string; danger?: boolean };

type DialogState =
  | ({ kind: "prompt"; value: string } & PromptOpts)
  | ({ kind: "confirm" } & ConfirmOpts)
  | null;

/**
 * In-app replacements for window.prompt / window.confirm, rendered with the project
 * Modal so dialogs match the app's look instead of the browser's native popups.
 * Returns promise-based helpers plus a `host` node to render once in the component.
 */
export function useDialogs() {
  const { t } = useI18n();
  const [state, setState] = useState<DialogState>(null);
  const resolver = useRef<((v: unknown) => void) | null>(null);

  const settle = useCallback((v: unknown) => {
    setState(null);
    resolver.current?.(v);
    resolver.current = null;
  }, []);

  const promptDialog = useCallback((opts: PromptOpts) => {
    return new Promise<string | null>((resolve) => {
      resolver.current = resolve as (v: unknown) => void;
      setState({ kind: "prompt", value: opts.defaultValue ?? "", ...opts });
    });
  }, []);

  const confirmDialog = useCallback((opts: ConfirmOpts) => {
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve as (v: unknown) => void;
      setState({ kind: "confirm", ...opts });
    });
  }, []);

  let host: React.ReactNode = null;
  if (state?.kind === "prompt") {
    host = (
      <Modal title={state.title} onClose={() => settle(null)}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            settle(state.value.trim() ? state.value : null);
          }}
        >
          <input
            autoFocus
            value={state.value}
            placeholder={state.placeholder}
            onChange={(e) => setState({ ...state, value: e.target.value })}
            className="w-full h-10 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
          />
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" onClick={() => settle(null)} className="btn-ghost px-4 py-2 text-sm border border-border">
              {t.cancel}
            </button>
            <button type="submit" className="btn-accent px-4 py-2 text-sm">
              {state.confirmLabel ?? t.confirm}
            </button>
          </div>
        </form>
      </Modal>
    );
  } else if (state?.kind === "confirm") {
    host = (
      <Modal title={state.title} onClose={() => settle(false)}>
        {state.body ? <p className="text-sm text-fg-muted">{state.body}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={() => settle(false)} className="btn-ghost px-4 py-2 text-sm border border-border">
            {t.cancel}
          </button>
          <button
            onClick={() => settle(true)}
            className={
              state.danger
                ? "rounded-lg bg-danger px-4 py-2 text-sm font-medium text-white"
                : "btn-accent px-4 py-2 text-sm"
            }
          >
            {state.confirmLabel ?? t.confirm}
          </button>
        </div>
      </Modal>
    );
  }

  return { promptDialog, confirmDialog, host };
}
