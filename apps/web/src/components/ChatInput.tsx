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
      className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-sm transition focus-within:border-slate-400 focus-within:shadow-md"
    >
      <select
        value={docType}
        onChange={handleDocTypeChange}
        disabled={disabled}
        aria-label="Filter by document type"
        className="shrink-0 rounded-xl border-0 bg-slate-50 px-2 py-2 text-sm text-slate-600 focus:outline-none focus:ring-2 focus:ring-slate-300"
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
        className="max-h-40 flex-1 resize-none border-0 bg-transparent px-2 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
      />
      <button
        type="submit"
        disabled={disabled || question.trim().length === 0}
        className="shrink-0 rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-40"
      >
        Send
      </button>
    </form>
  );
}
