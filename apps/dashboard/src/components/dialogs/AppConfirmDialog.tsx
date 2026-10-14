"use client";

import { useRef, type ReactNode } from "react";
import { Button } from "../ui";
import { IconAlert, IconInfo, IconStop } from "../icons";
import { DialogShell } from "./DialogShell";

export type ConfirmVariant = "default" | "warning" | "danger";

export interface AppConfirmDialogProps {
  open: boolean;
  title: ReactNode;
  message?: ReactNode;
  note?: ReactNode;
  noteLabel?: string;
  variant?: ConfirmVariant;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Shows a spinner on the primary action and blocks dismissal. */
  busy?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  /** Extra form content (e.g. a raised budget input). */
  children?: ReactNode;
}

const ICONS: Record<ConfirmVariant, ReactNode> = {
  default: <IconInfo size={22} />,
  warning: <IconAlert size={22} />,
  danger: <IconStop size={22} />,
};

const PRIMARY: Record<ConfirmVariant, "primary" | "warning" | "danger"> = {
  default: "primary",
  warning: "warning",
  danger: "danger",
};

export function AppConfirmDialog({
  open,
  title,
  message,
  note,
  noteLabel,
  variant = "default",
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  busy = false,
  confirmDisabled = false,
  onConfirm,
  onCancel,
  children,
}: AppConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  return (
    <DialogShell
      open={open}
      role="alertdialog"
      tone={variant}
      variant={variant}
      icon={ICONS[variant]}
      title={title}
      message={message}
      note={note}
      noteLabel={noteLabel}
      onDismiss={onCancel}
      dismissDisabled={busy}
      initialFocusRef={confirmRef}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            ref={confirmRef}
            variant={PRIMARY[variant]}
            onClick={onConfirm}
            busy={busy}
            disabled={confirmDisabled}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </DialogShell>
  );
}
