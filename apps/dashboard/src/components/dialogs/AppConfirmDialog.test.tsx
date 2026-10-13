import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AppConfirmDialog, type AppConfirmDialogProps } from "./AppConfirmDialog";

function renderDialog(props: Partial<AppConfirmDialogProps> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const utils = render(
    <AppConfirmDialog
      open
      title="Cancel this production?"
      message="All remaining work stops."
      noteLabel="Spent so far"
      note="$1.88 actual (simulated)"
      confirmLabel="Cancel production"
      cancelLabel="Keep production"
      variant="danger"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...props}
    />,
  );
  return { ...utils, onConfirm, onCancel };
}

describe("AppConfirmDialog", () => {
  it("renders an accessible modal with title, message and note", () => {
    renderDialog();
    const dialog = screen.getByRole("alertdialog", { name: "Cancel this production?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription("All remaining work stops.");
    expect(dialog).toHaveTextContent("Spent so far");
    expect(dialog).toHaveTextContent("$1.88 actual (simulated)");
    expect(screen.getByTestId("dialog-icon")).toBeInTheDocument();
  });

  it("exposes the variant for styling", () => {
    renderDialog({ variant: "danger" });
    expect(screen.getByRole("alertdialog")).toHaveAttribute("data-variant", "danger");
  });

  it.each(["default", "warning"] as const)("supports the %s variant", (variant) => {
    renderDialog({ variant });
    expect(screen.getByRole("alertdialog")).toHaveAttribute("data-variant", variant);
  });

  it("focuses the primary action when opened", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "Cancel production" })).toHaveFocus();
  });

  it("calls onConfirm and onCancel", async () => {
    const user = userEvent.setup();
    const { onConfirm, onCancel } = renderDialog();
    await user.click(screen.getByRole("button", { name: "Cancel production" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Keep production" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape and on backdrop click", async () => {
    const user = userEvent.setup();
    const { onCancel } = renderDialog();
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
    await user.click(screen.getByTestId("dialog-backdrop"));
    expect(onCancel).toHaveBeenCalledTimes(2);
  });

  it("keeps focus inside the dialog when tabbing", async () => {
    const user = userEvent.setup();
    renderDialog();
    const dialog = screen.getByRole("alertdialog");
    for (let i = 0; i < 5; i += 1) {
      await user.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
  });

  it("ignores dismissal while busy", async () => {
    const user = userEvent.setup();
    const { onCancel } = renderDialog({ busy: true });
    await user.keyboard("{Escape}");
    expect(onCancel).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Cancel production" })).toBeDisabled();
  });

  it("renders nothing when closed", () => {
    renderDialog({ open: false });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
