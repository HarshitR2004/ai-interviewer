import { afterEach, expect, it, vi } from "vitest";
import { remaining, request, RequestError } from "./api";
afterEach(() => vi.unstubAllGlobals());
it("does not start the interview clock during model warmup", () =>
  expect(remaining(0, 100)).toBe("Not started"));
it("clamps expired interview timers and formats minutes", () => {
  expect(remaining(105, 100)).toBe("0:05");
  expect(remaining(99, 100)).toBe("0:00");
});
it("never forwards backend error payloads to the interface", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: false,
      status: 422,
      json: async () => ({ detail: "internal schema model=secret id=123" }),
    })),
  );
  await expect(request("/api/candidates")).rejects.toMatchObject({
    status: 422,
    message:
      "Please check that your resume is a readable PDF and your job description is complete.",
  });
});
it("retains missing-session status for recovery without exposing identifiers", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 404 })),
  );
  await expect(request("/api/live-sessions/private-id")).rejects.toBeInstanceOf(
    RequestError,
  );
  await expect(request("/api/live-sessions/private-id")).rejects.toMatchObject({
    status: 404,
  });
});
