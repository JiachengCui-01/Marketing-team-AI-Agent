"use client";

import { createContext, useContext } from "react";

/** Lets deeply-nested citation links and knowledge-base chips open a source in the
 * right-side preview panel (as a browser-like tab) instead of navigating away. */
export type PreviewOpener = {
  openWeb: (url: string, title?: string) => void;
  openKb: (docId: string, title?: string) => void;
};

const PreviewOpenerContext = createContext<PreviewOpener | null>(null);

export const PreviewOpenerProvider = PreviewOpenerContext.Provider;

export function usePreviewOpener(): PreviewOpener | null {
  return useContext(PreviewOpenerContext);
}
