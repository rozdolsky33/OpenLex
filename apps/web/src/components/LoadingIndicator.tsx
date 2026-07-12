export function LoadingIndicator() {
  return (
    <div
      role="status"
      aria-label="Waiting for answer"
      className="mr-auto flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-4 py-3"
    >
      <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.3s]" />
      <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.15s]" />
      <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400" />
    </div>
  );
}
