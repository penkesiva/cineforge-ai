"use client";

import { useRef, type ReactNode } from "react";
import { Button } from "../ui";
import { IconAlert, IconCheck, IconInfo } from "../icons";
import { DialogShell } from "./DialogShell";

export type NoticeVariant = "success" | "error" | "info";

export interface AppNoticeDialogProps {
  open: boolean;
  variant?: NoticeVariant;
  title: ReactNode;
  message?: ReactNode;
  note?: ReactNode;
  noteLabel?: string;
  actionLabel?: string;
  onClose: () => void;
  /** Optional secondary action, e.g. "View production". */
  secondaryLabel?: string;
  onSecondary?: () => void;
}

const ICONS: Record<NoticeVariant, ReactNode> = {
  success: <IconCheck size={22} />,
  error: <IconAlert size={22} />,
  info: <IconInfo size={22} />,
};

/** Shared state shape for pages that show one notice at a time. */
export interface NoticeState {
  variant: NoticeVariant;
  title: string;
  message?: ReactNode;
  note?: ReactNode;
}

export function AppNoticeDialog({
  open,
  variant = "info",
  title,
  message,
  note,
  noteLabel,
  actionLabel = "Got it",
  onClose,
  secondaryLabel,
  onSecondary,
}: AppNoticeDialogProps) {
  const primaryRef = useRef<HTMLButtonElement>(null);
  return (
    <DialogShell
      open={open}
      role={variant === "error" ? "alertdialog" : "dialog"}
      tone={variant}
      variant={variant}
      icon={ICONS[variant]}
      title={title}
      message={message}
      note={note}
      noteLabel={noteLabel}
      onDismiss={onClose}
      initialFocusRef={primaryRef}
      footer={
        <>
          {secondaryLabel && onSecondary && (
            <Button variant="ghost" onClick={onSecondary}>
              {secondaryLabel}
            </Button>
          )}
          <Button ref={primaryRef} variant={variant === "error" ? "secondary" : "primary"} onClick={onClose}>
            {actionLabel}
          </Button>
        </>
      }
    />
  );
}
