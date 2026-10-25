// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { ResumeUpload } from "./resume-upload";

beforeEach(() => {
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: true,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("selects a PDF and removes it without uploading immediately", async () => {
  const change = vi.fn();
  render(<ResumeUpload disabled={false} onFilesChange={change} />);
  const file = new File(["test PDF"], "resume.pdf", {
    type: "application/pdf",
  });
  fireEvent.change(screen.getByLabelText("Upload resume (PDF)"), {
    target: { files: [file] },
  });
  expect(change).toHaveBeenLastCalledWith([file]);
  expect(screen.queryByRole("progressbar")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Remove resume.pdf" }));
  await waitFor(() => expect(change).toHaveBeenLastCalledWith([]));
});

it("accepts drag-and-drop and replaces the previous resume", async () => {
  const change = vi.fn();
  render(<ResumeUpload disabled={false} onFilesChange={change} />);
  const target = screen.getByRole("button", {
    name: "Upload resume",
  }).parentElement!;
  const first = new File(["first"], "first.pdf", { type: "application/pdf" });
  const second = new File(["second"], "second.pdf", {
    type: "application/pdf",
  });
  fireEvent.drop(target, {
    dataTransfer: { files: [first], types: ["Files"] },
  });
  expect((screen.getByLabelText("Upload resume (PDF)") as HTMLInputElement).multiple).toBe(false);
  const calls = change.mock.calls.length;
  fireEvent.drop(target, {
    dataTransfer: { files: [first, second], types: ["Files"] },
  });
  expect(change).toHaveBeenCalledTimes(calls);
  expect(change).toHaveBeenLastCalledWith([first]);
  expect(screen.getByRole("alert").textContent).toContain("Choose one PDF resume");
  fireEvent.drop(target, {
    dataTransfer: { files: [second], types: ["Files"] },
  });
  expect(change).toHaveBeenLastCalledWith([second]);
  await waitFor(() => expect(screen.queryByRole("button", { name: "Remove first.pdf" })).toBeNull());
});

it("rejects non-PDF and multi-file selections", () => {
  const change = vi.fn();
  render(<ResumeUpload disabled={false} onFilesChange={change} />);
  const input = screen.getByLabelText("Upload resume (PDF)");
  fireEvent.change(input, {
    target: {
      files: [new File(["image"], "photo.png", { type: "image/png" })],
    },
  });
  expect(change).not.toHaveBeenCalled();
  expect(screen.getByRole("alert").textContent).toContain(
    "not an accepted file type",
  );
  fireEvent.change(input, {
    target: {
      files: [new File(["pdf"], "one.pdf"), new File(["pdf"], "two.pdf")],
    },
  });
  expect(change).not.toHaveBeenCalled();
  expect(screen.getByRole("alert").textContent).toContain(
    "Choose one PDF resume",
  );
});

it.each([0, 10 * 1024 * 1024 + 1])(
  "excludes invalid-size files from preparation (%i bytes)",
  (size) => {
    const change = vi.fn();
    render(<ResumeUpload disabled={false} onFilesChange={change} />);
    const file = new File([new Uint8Array(size)], "resume.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(screen.getByLabelText("Upload resume (PDF)"), {
      target: { files: [file] },
    });
    expect(change).toHaveBeenLastCalledWith([]);
  },
);

it("ignores drops when disabled", () => {
  const change = vi.fn();
  render(<ResumeUpload disabled={true} onFilesChange={change} />);
  const trigger = screen.getByRole("button", { name: "Upload resume" });
  expect((trigger as HTMLButtonElement).disabled).toBe(true);
  fireEvent.drop(trigger.parentElement!, {
    dataTransfer: {
      files: [new File(["pdf"], "resume.pdf")],
      types: ["Files"],
    },
  });
  expect(change).not.toHaveBeenCalled();
});
