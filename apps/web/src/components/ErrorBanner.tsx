// Alert styling -- must look visually distinct from AbstainedNotice, which is an expected
// outcome, not an error.
export function ErrorBanner({ message }: { message: string }) {
  return (
    <div role="alert" className="border-t border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
      {message}
    </div>
  );
}
