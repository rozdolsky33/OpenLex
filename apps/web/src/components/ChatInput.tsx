import type { ChangeEvent, FormEvent, KeyboardEvent } from "react";
import type { DocType } from "../api/types";

interface ChatInputProps {
  question: string;
  onQuestionChange: (value: string) => void;
  docType: DocType | "";
  onDocTypeChange: (value: DocType | "") => void;
  onSubmit: () => void;
  disabled: boolean;
}

export function ChatInput({
  question,
  onQuestionChange,
  docType,
  onDocTypeChange,
  onSubmit,
  disabled,
}: ChatInputProps) {
  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onSubmit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSubmit();
    }
  }

  function handleDocTypeChange(event: ChangeEvent<HTMLSelectElement>) {
    onDocTypeChange(event.target.value as DocType | "");
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-end gap-2 border-t border-slate-200 bg-white p-3"
    >
      <select
        value={docType}
        onChange={handleDocTypeChange}
        disabled={disabled}
        aria-label="Filter by document type"
        className="rounded border border-slate-300 px-2 py-2 text-sm"
      >
        <option value="">All sources</option>
        <option value="statute">Statutes only</option>
        <option value="case">Case law only</option>
      </select>
      <textarea
        value={question}
        onChange={(event) => onQuestionChange(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        rows={1}
        placeholder="Ask about NY landlord-tenant law…"
        aria-label="Question"
        className="flex-1 resize-none rounded border border-slate-300 px-3 py-2 text-sm"
      />
      <button
        type="submit"
        disabled={disabled || question.trim().length === 0}
        className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        Send
      </button>
    </form>
  );
}
