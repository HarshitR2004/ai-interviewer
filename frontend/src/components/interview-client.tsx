"use client";
import dynamic from "next/dynamic";
const InterviewApp = dynamic(() => import("./interview-app"), {
  ssr: false,
  loading: () => (
    <main className="boot" role="status">
      Opening your interview room…
    </main>
  ),
});
export default function InterviewClient({
  jobDescription,
}: {
  jobDescription: string;
}) {
  return <InterviewApp jobDescription={jobDescription} />;
}
