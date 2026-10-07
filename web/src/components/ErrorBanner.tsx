import type { ApiError } from "@/lib/api";

export function ErrorBanner({
  title,
  error,
  onRetry,
}: {
  title: string;
  error: ApiError;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm sm:flex-row sm:items-start sm:justify-between"
    >
      <div className="min-w-0">
        <p className="font-medium text-red-200">{title}</p>
        <p className="mt-0.5 text-red-300/90">{error.message}</p>
        <p className="mt-1 break-all font-mono text-xs text-red-300/70">
          Tried: {error.url}
        </p>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-md border border-red-800 px-3 py-1 text-red-200 hover:bg-red-900/40"
        >
          Retry
        </button>
      )}
    </div>
  );
}
