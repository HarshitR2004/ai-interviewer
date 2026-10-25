import { afterEach, expect, it, vi } from "vitest";
const configuredJob =
  "Artificial Intelligence Intern at Medinex Workforce. Python and machine learning.";
vi.mock("@/lib/job-description", () => ({
  readJobDescription: vi.fn(async () => configuredJob),
}));
import { POST } from "./route";
import { readJobDescription } from "@/lib/job-description";
afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(readJobDescription).mockReset().mockResolvedValue(configuredJob);
});

it("overwrites a supplied JD with the configured posting and preserves the resume", async () => {
  const upstream = vi.fn(async () =>
    Response.json(
      {
        candidate_id: "candidate",
        plan: { private: "hidden" },
        profile: { private: "hidden" },
      },
      { status: 201 },
    ),
  );
  vi.stubGlobal("fetch", upstream);
  const form = new FormData();
  form.append(
    "resume",
    new File(["synthetic resume"], "resume.pdf", { type: "application/pdf" }),
  );
  form.append(
    "job_description",
    "A different job injected through the browser",
  );
  form.append("job_description", "A second injected description");
  form.append("duration", "30");
  form.append("seniority", "junior");
  const response = await POST(
    new Request("http://localhost/api/candidates", {
      method: "POST",
      body: form,
    }),
  );
  const [, options] = upstream.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  const sent = options.body as FormData;
  expect(sent.getAll("job_description")).toEqual([configuredJob]);
  expect(sent.get("duration")).toBe("30");
  expect(await (sent.get("resume") as File).text()).toBe("synthetic resume");
  expect(response.status).toBe(201);
  expect(await response.json()).toEqual({ candidate_id: "candidate" });
});

it("does not fall back to a browser-supplied JD if the configured file is unavailable", async () => {
  vi.mocked(readJobDescription).mockRejectedValueOnce(
    new Error("private filesystem path"),
  );
  const upstream = vi.fn();
  vi.stubGlobal("fetch", upstream);
  const form = new FormData();
  form.append("resume", new File(["resume"], "resume.pdf"));
  const response = await POST(
    new Request("http://localhost/api/candidates", {
      method: "POST",
      body: form,
    }),
  );
  expect(response.status).toBe(503);
  expect(upstream).not.toHaveBeenCalled();
  expect(await response.text()).not.toContain("private filesystem path");
});

it.each(["missing", "text", "duplicate", "extra attachment"])(
  "rejects an invalid single-file request: %s",
  async (scenario) => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    const form = new FormData();
    if (scenario === "text") form.append("resume", "resume.pdf");
    if (scenario === "duplicate" || scenario === "extra attachment") {
      form.append("resume", new File(["first"], "first.pdf"));
      form.append(
        scenario === "duplicate" ? "resume" : "attachment",
        new File(["second"], "second.pdf"),
      );
    }
    const response = await POST(new Request("http://localhost/api/candidates", {
      method: "POST",
      body: form,
    }));
    expect(response.status).toBe(422);
    expect(await response.json()).toEqual({ detail: "Upload exactly one PDF resume." });
    expect(upstream).not.toHaveBeenCalled();
  },
);
