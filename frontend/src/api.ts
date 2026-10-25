export type Session = {
  session_id: string;
  status: "waiting" | "active" | "completed" | "failed";
  current_prompt: { id: string; text: string } | null;
  question_number: number;
  question_count: number;
  deadline_at: number;
  completion_reason: string | null;
};
export type History = {
  events: { kind: string; text: string; interrupted?: boolean }[];
  evidence: unknown[];
};
export class RequestError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new RequestError(
      "We couldn’t reach your interview. Check your connection and try again.",
      0,
    );
  }
  if (!response.ok) {
    // Backend errors may contain model names, validation schemas, or internal paths.
    // Only product-level messages cross into the interface.
    const message =
      response.status === 404
        ? "This interview is no longer available. Start a new interview to continue."
        : response.status === 409
          ? "An interview is already in progress. Reconnect or end it before starting another."
          : response.status === 413
            ? "Your resume is too large. Please choose a smaller PDF."
            : response.status === 422 || response.status === 400
              ? "Please check that your resume is a readable PDF and your job description is complete."
              : "We couldn’t complete that step. Please try again in a moment.";
    throw new RequestError(message, response.status);
  }
  try {
    return await response.json();
  } catch {
    throw new RequestError(
      "Your interview returned an unexpected response. Please try again.",
      0,
    );
  }
}
export function remaining(deadline: number, now: number): string {
  if (!deadline) return "Not started";
  const seconds = Math.max(0, Math.ceil(deadline - now));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
