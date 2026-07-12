import type { Citation } from "../api/types";

export function CitationList({ citations }: { citations: Citation[] }) {
  return (
    <ul className="mt-3 flex flex-col gap-2 border-t border-slate-100 pt-3">
      {citations.map((citation, index) => (
        <li key={`${citation.citation}-${index}`} className="text-xs text-slate-600">
          <div className="font-medium text-slate-800">
            {citation.url ? (
              <a href={citation.url} target="_blank" rel="noreferrer" className="underline">
                {citation.citation}
              </a>
            ) : (
              citation.citation
            )}
            {citation.title && <span className="text-slate-500"> — {citation.title}</span>}
          </div>
          {(citation.court || citation.date) && (
            <div className="text-slate-400">
              {[citation.court, citation.date].filter(Boolean).join(" · ")}
            </div>
          )}
          <p className="mt-1 text-slate-500">{citation.snippet}</p>
        </li>
      ))}
    </ul>
  );
}
