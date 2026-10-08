"use client";

import { useRef, useState } from "react";
import { ErrorBanner } from "@/components/ErrorBanner";
import { controlClass, primaryButtonClass } from "@/components/Field";
import { Notice, Spinner } from "@/components/Notice";
import { API_BASE_URL, ask, toApiError, type ApiError } from "@/lib/api";
import type { AskEffort, AskResponse } from "@/lib/types";
import { AskAnswer } from "./AskAnswer";
import { ExampleChips } from "./ExampleChips";

const MAX_QUESTION_CHARS = 1000;

type AskState =
  | { status: "idle" }
  | { status: "loading"; question: string }
  | { status: "error"; error: ApiError; question: string }
  | { status: "done"; response: AskResponse };

export default function AskClient() {
  const [question, setQuestion] = useState("");
  const [effort, setEffort] = useState<AskEffort>("medium");
  const [state, setState] = useState<AskState>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);
  const loading = state.status === "loading";

  const submit = async (text: string) => {
    const q = text.trim();
    if (!q) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ status: "loading", question: q });
    try {
      const response = await ask({ question: q, effort }, controller.signal);
      if (!controller.signal.aborted) setState({ status: "done", response });
    } catch (err) {
      if (!controller.signal.aborted) {
        setState({ status: "error", error: toApiError(err, "/api/ask"), question: q });
      }
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Ask the Pit Wall</h1>
        <p className="mt-1 text-sm text-muted">
          Ask about laps, gaps, telemetry or strategy. Answers are built from the same data as the other tools, and
          every figure is checked against it.
        </p>
      </div>

      <form
        className="space-y-3 rounded-xl border border-border bg-surface p-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit(question);
        }}
      >
        <label className="sr-only" htmlFor="ask-question">
          Question
        </label>
        <textarea
          id="ask-question"
          rows={3}
          maxLength={MAX_QUESTION_CHARS}
          placeholder="e.g. Where did Lando Norris lose time to Max Verstappen in qualifying at the 2025 Chinese Grand Prix?"
          className={`${controlClass} h-auto resize-y py-2 leading-relaxed`}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void submit(question);
            }
          }}
        />
        <ExampleChips
          disabled={loading}
          onPick={(q) => {
            setQuestion(q);
            void submit(q);
          }}
        />
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" disabled={loading || question.trim() === ""} className={primaryButtonClass}>
            {loading ? "Thinking..." : "Ask"}
          </button>
          <label className="flex items-center gap-2 text-xs text-muted">
            Effort
            <select
              className={`${controlClass} h-8 w-auto`}
              value={effort}
              disabled={loading}
              onChange={(e) => setEffort(e.target.value as AskEffort)}
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
          <span className="hidden text-xs text-muted sm:inline">Ctrl/Cmd + Enter to send</span>
          <span className="ml-auto font-mono text-xs text-muted">API: {API_BASE_URL}</span>
        </div>
      </form>

      <div aria-live="polite">
        {state.status === "idle" && (
          <Notice title="Ask a question or pick an example">
            Questions should name a season and race, e.g. &ldquo;the 2025 Chinese Grand Prix&rdquo;.
          </Notice>
        )}
        {state.status === "loading" && (
          <div className="rounded-xl border border-border bg-surface px-4 py-12 text-center">
            <Spinner label="Looking it up..." />
          </div>
        )}
        {state.status === "error" && state.error.status === 503 && (
          <div role="status" className="rounded-lg border border-amber-800/60 bg-amber-950/30 px-4 py-3 text-sm">
            <p className="font-medium text-amber-200">Ask the Pit Wall is unavailable</p>
            <p className="mt-0.5 text-amber-200/80">
              {state.error.detail ?? "The question-answering service is not configured on this server."}
            </p>
          </div>
        )}
        {state.status === "error" && state.error.status !== 503 && (
          <ErrorBanner
            title="Could not answer that"
            error={state.error}
            onRetry={() => void submit(state.question)}
          />
        )}
        {state.status === "done" && <AskAnswer response={state.response} />}
      </div>
    </div>
  );
}
