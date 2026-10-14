import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { AppNoticeDialog } from "./AppNoticeDialog";

function Harness({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(true);
  return (
    <AppNoticeDialog
      open={open}
      variant="success"
      title="Production delivered"
      message="READY -> DELIVERED"
      note="Master render 1080x1920"
      onClose={() => {
        onClose();
        setOpen(false);
      }}
    />
  );
}

describe("AppNoticeDialog", () => {
  it("renders a modal dialog and closes from the primary action", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    const dialog = screen.getByRole("dialog", { name: "Production delivered" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("data-variant", "success");
    expect(dialog).toHaveTextContent("Master render 1080x1920");
    const ok = screen.getByRole("button", { name: "Got it" });
    expect(ok).toHaveFocus();
    await user.click(ok);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("uses an alertdialog for errors", () => {
    render(<AppNoticeDialog open variant="error" title="Could not run production" onClose={() => {}} />);
    expect(screen.getByRole("alertdialog", { name: "Could not run production" })).toHaveAttribute(
      "data-variant",
      "error",
    );
  });
});
