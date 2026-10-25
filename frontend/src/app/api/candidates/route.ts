import { readJobDescription } from "@/lib/job-description";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const form = await request.formData();
    const resumes = form.getAll("resume");
    const files = Array.from(form.values()).filter((value) => typeof value !== "string");
    if (resumes.length !== 1 || typeof resumes[0] === "string" || files.length !== 1) {
      return Response.json(
        { detail: "Upload exactly one PDF resume." },
        { status: 422 },
      );
    }
    // The browser cannot override the role used to prepare this interview.
    form.set("job_description", await readJobDescription());
    const response = await fetch("http://127.0.0.1:8000/api/candidates", {
      method: "POST",
      body: form,
      signal: AbortSignal.timeout(600_000),
    });
    if (!response.ok) {
      return Response.json(
        { detail: "We couldn’t prepare your interview. Please try again." },
        { status: response.status },
      );
    }
    const result = await response.json();
    // Keep the preparation plan and assessment internals on the server.
    return Response.json(
      { candidate_id: result.candidate_id },
      { status: response.status },
    );
  } catch {
    return Response.json(
      { detail: "We couldn’t prepare your interview. Please try again." },
      { status: 503 },
    );
  }
}
