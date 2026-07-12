import type { ReactNode } from "react";

// Claude's tool-forced answers come back as plain text, but the model still naturally reaches
// for markdown emphasis (**bold**) -- rendered literally as asterisks otherwise. This handles
// just that plus paragraph breaks, not a full markdown parser: no headers/links/lists/raw
// HTML, so there's no markdown dependency or HTML-injection surface to worry about.
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  return text
    .split(/(\*\*[^*]+\*\*)/g)
    .filter(Boolean)
    .map((part, i) =>
      part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
        <strong key={`${keyPrefix}-${i}`}>{part.slice(2, -2)}</strong>
      ) : (
        <span key={`${keyPrefix}-${i}`}>{part}</span>
      ),
    );
}

export function AnswerText({ text }: { text: string }) {
  const paragraphs = text.split(/\n{2,}/).filter((p) => p.trim().length > 0);
  const source = paragraphs.length > 0 ? paragraphs : [text];

  return (
    <>
      {source.map((paragraph, i) => (
        <p key={i} className={i > 0 ? "mt-2" : undefined}>
          {renderInline(paragraph, `p${i}`)}
        </p>
      ))}
    </>
  );
}
