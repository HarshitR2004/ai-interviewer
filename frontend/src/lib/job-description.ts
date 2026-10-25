import { readFile } from "node:fs/promises";
import path from "node:path";

// Server-only filesystem access: only the configured job posting is read.
export async function readJobDescription(): Promise<string> {
  const description = (
    await readFile(
      path.resolve(process.cwd(), "../sample_data/job_description.txt"),
      "utf8",
    )
  ).trim();
  if (description.length < 40 || description.length > 12000) {
    throw new Error("The configured job description is unavailable.");
  }
  return description;
}
