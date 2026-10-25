import type { ReactNode } from "react";

function inline(text: string): ReactNode {
  return text
    .split(/(\*\*.*?\*\*)/g)
    .map((part, index) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={index}>{part.slice(2, -2)}</strong>
      ) : (
        part
      ),
    );
}

export function JobDescription({ text }: { text: string }) {
  return (
    <section className="job-posting" aria-label="Job description">
      <div
        className="job-document"
        role="region"
        aria-label="Full job description"
      >
        {text.split(/\r?\n\s*\r?\n/).map((block, index) => {
          if (/^#{1,6}\s/.test(block))
            return (
              <h4 key={index}>{inline(block.replace(/^#{1,6}\s+/, ""))}</h4>
            );
          if (block.startsWith("- "))
            return (
              <ul key={index}>
                {block.split(/\r?\n/).map((line, item) => (
                  <li key={item}>{inline(line.replace(/^-\s+/, ""))}</li>
                ))}
              </ul>
            );
          return <p key={index}>{inline(block)}</p>;
        })}
      </div>
    </section>
  );
}
