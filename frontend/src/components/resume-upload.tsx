"use client";

import { FileDropzone } from "./arc/file-dropzone/file-dropzone";

export function ResumeUpload({
  disabled,
  onFilesChange,
}: {
  disabled: boolean;
  onFilesChange: (files: File[]) => void;
}) {
  return (
    <fieldset
      className="resume-upload"
      disabled={disabled}
      aria-label="Resume upload"
    >
      <FileDropzone
        disabled={disabled}
        inputLabel="Upload resume (PDF)"
        label="Upload resume"
        description="Drop your file here or click to browse"
        note="PDF · up to 10 MB"
        dropLabel="Drop your resume here"
        accept=".pdf,application/pdf"
        multiple={false}
        maxFiles={1}
        maxSize={10 * 1024 * 1024}
        compactAt={1}
        onFilesChange={onFilesChange}
      />
    </fieldset>
  );
}
