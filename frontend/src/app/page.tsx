import { connection } from "next/server";
import InterviewClient from "@/components/interview-client";
import { readJobDescription } from "@/lib/job-description";

export default async function Page() {
  await connection();
  const jobDescription = await readJobDescription();
  return <InterviewClient jobDescription={jobDescription} />;
}
