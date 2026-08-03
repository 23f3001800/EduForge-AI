"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { FileUp, Loader2, Upload as UploadIcon, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/states";
import { createJob, getOptions, uploadDocument, type JobOptions } from "@/lib/api";
import { cn } from "@/lib/cn";
import { AccessKeyPrompt, isAccessKeyError } from "@/components/access-key";
import { describeError, traceIdOf } from "@/lib/errors";
import { formatBytes, labelFor } from "@/lib/format";

const ACCEPTED = [".pdf", ".docx", ".pptx", ".txt", ".md"];
const MAX_BYTES = 25 * 1024 * 1024;

/**
 * Upload, and the small number of optional questions the brief asks for.
 *
 * Every field has a working default and every one can be skipped — a teacher
 * who answers nothing still gets a good package. That is why the options sit
 * behind a disclosure rather than in front of the upload: the form should not
 * look like an interrogation before it has been given a file.
 */
export default function UploadPage() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [showOptions, setShowOptions] = useState(false);
  const [showKeyField, setShowKeyField] = useState(false);

  const [board, setBoard] = useState("generic");
  const [style, setStyle] = useState("balanced");
  const [periodMinutes, setPeriodMinutes] = useState("");
  const [language, setLanguage] = useState("en");
  const [goals, setGoals] = useState("");

  const { data: options } = useQuery({ queryKey: ["options"], queryFn: getOptions });

  const validate = useCallback((candidate: File): string | null => {
    const name = candidate.name.toLowerCase();
    if (!ACCEPTED.some((ext) => name.endsWith(ext))) {
      return `EduForge reads ${ACCEPTED.join(", ")}. This file doesn't match any of those.`;
    }
    if (candidate.size === 0) return "That file is empty.";
    if (candidate.size > MAX_BYTES) {
      return `That file is ${formatBytes(candidate.size)}, over the 25 MB limit.`;
    }
    return null;
  }, []);

  const accept = useCallback(
    (candidate: File | undefined) => {
      if (!candidate) return;
      const problem = validate(candidate);
      setFileError(problem);
      setFile(problem ? null : candidate);
    },
    [validate],
  );

  const submit = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("no file");
      const uploaded = await uploadDocument(file);

      const payload: JobOptions = {
        teaching_style: style,
        output_language: language.trim() || "en",
        // null, not a number: the backend reads null as "use the board's
        // convention", and sending a default here would silently beat it.
        period_duration_minutes: periodMinutes ? Number(periodMinutes) : null,
        curriculum_board: board === "generic" ? null : board,
      };
      const parsed = goals
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .slice(0, 10);
      if (parsed.length) payload.learning_goals = parsed;

      return createJob(uploaded.document_id, payload, crypto.randomUUID());
    },
    onSuccess: (job) => {
      toast.success("Run started", { description: "Watching progress live." });
      router.push(`/run?job=${job.job_id}`);
    },
    onError: (error) => {
      // A missing key already renders a panel explaining itself and offering
      // the field that fixes it; a toast saying the same thing worse would only
      // pull attention away from the input the visitor needs to reach.
      if (isAccessKeyError(error)) return;
      const { title, body } = describeError(error);
      toast.error(title, { description: body });
    },
  });

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">New package</h1>
        <p className="mt-2 text-fg-muted">
          Upload a chapter. Everything below is optional — the defaults produce a good package.
        </p>
      </div>

      <Card>
        <CardContent className="pt-5">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              accept(e.dataTransfer.files?.[0]);
            }}
            className={cn(
              "flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
              dragging ? "border-accent bg-accent-subtle" : "border-border",
            )}
          >
            <FileUp className="size-8 text-fg-faint" aria-hidden />
            {file ? (
              <div className="flex flex-wrap items-center justify-center gap-2">
                <span className="font-medium">{file.name}</span>
                <Badge>{formatBytes(file.size)}</Badge>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setFile(null);
                    setFileError(null);
                    if (inputRef.current) inputRef.current.value = "";
                  }}
                  aria-label="Remove selected file"
                >
                  <X /> Remove
                </Button>
              </div>
            ) : (
              <>
                <p className="font-medium">Drop a document here</p>
                <p className="text-sm text-fg-muted">
                  PDF, DOCX, PPTX, TXT or Markdown, up to 25 MB
                </p>
              </>
            )}

            <input
              ref={inputRef}
              id="file"
              type="file"
              accept={ACCEPTED.join(",")}
              className="sr-only"
              onChange={(e) => accept(e.target.files?.[0])}
            />
            <Button variant="secondary" onClick={() => inputRef.current?.click()}>
              {file ? "Choose a different file" : "Choose a file"}
            </Button>
          </div>

          {fileError ? (
            <p role="alert" className="mt-3 text-sm text-danger">
              {fileError}
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Options</CardTitle>
          <Button variant="ghost" size="sm" onClick={() => setShowOptions((v) => !v)}>
            {showOptions ? "Hide" : "Customise"}
          </Button>
        </CardHeader>
        {showOptions ? (
          <CardContent className="grid gap-5 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">Curriculum board</span>
              <select
                value={board}
                onChange={(e) => setBoard(e.target.value)}
                className="min-h-11 rounded-md border border-input bg-raised px-3"
              >
                {(options?.curriculum_boards ?? [{ value: "generic", label: "No specific board" }]).map(
                  (option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ),
                )}
              </select>
              <span className="text-xs text-fg-faint">
                Shifts the assessment mix and mark scheme. It cannot add question types the
                content does not support.
              </span>
            </label>

            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">Teaching style</span>
              <select
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                className="min-h-11 rounded-md border border-input bg-raised px-3"
              >
                {(options?.teaching_styles ?? ["balanced"]).map((option) => (
                  <option key={option} value={option}>
                    {labelFor(option)}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">Period length</span>
              <input
                type="number"
                min={5}
                max={240}
                value={periodMinutes}
                onChange={(e) => setPeriodMinutes(e.target.value)}
                placeholder="Use the board's default"
                className="min-h-11 rounded-md border border-input bg-raised px-3"
              />
              <span className="text-xs text-fg-faint">
                Left blank, the board decides — 40 minutes generally, 60 for IB.
              </span>
            </label>

            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">Output language</span>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="min-h-11 rounded-md border border-input bg-raised px-3"
              >
                {(options?.output_languages ?? [{ value: "en", label: "English", script: "Latin" }]).map(
                  (option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ),
                )}
              </select>
              <span className="text-xs text-fg-faint">
                Teaching content is written in this language. Source quotes stay in the
                document&apos;s own language, so citations still match it word for word.
              </span>
            </label>

            <label className="flex flex-col gap-1.5 text-sm sm:col-span-2">
              <span className="font-medium">Learning goals</span>
              <textarea
                rows={3}
                value={goals}
                onChange={(e) => setGoals(e.target.value)}
                placeholder="One per line. Optional."
                className="rounded-md border border-input bg-raised px-3 py-2"
              />
              <span className="text-xs text-fg-faint">
                Merged with the objectives found in the document, not substituted for them — a
                goal the source cannot support is reported rather than quietly dropped.
              </span>
            </label>
          </CardContent>
        ) : null}
      </Card>

      {/* A missing key is not an error to retry — retrying without one fails
          identically. It gets the field that fixes it instead. */}
      {submit.isError && isAccessKeyError(submit.error) ? (
        <AccessKeyPrompt onSaved={() => submit.reset()} />
      ) : submit.isError ? (
        <ErrorState
          title={describeError(submit.error).title}
          traceId={traceIdOf(submit.error)}
          onRetry={() => submit.mutate()}
        >
          {describeError(submit.error).body}
        </ErrorState>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          size="lg"
          disabled={!file || submit.isPending}
          loading={submit.isPending}
          onClick={() => submit.mutate()}
        >
          {submit.isPending ? (
            "Starting…"
          ) : (
            <>
              <UploadIcon /> Generate package
            </>
          )}
        </Button>
        {submit.isPending ? (
          <span className="flex items-center gap-2 text-sm text-fg-muted">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Uploading and queueing…
          </span>
        ) : null}

        {/* Findable before the refusal, not only after it. Most instances need
            no key, so this stays a quiet link rather than a field competing
            with the button — but someone handed a key and a link should not
            have to trigger a 401 to discover where the key goes. */}
        {!submit.isPending && !showKeyField ? (
          <button
            type="button"
            onClick={() => setShowKeyField(true)}
            className="text-sm font-medium text-accent underline-offset-4 hover:underline"
          >
            Have an access key?
          </button>
        ) : null}
      </div>

      {showKeyField && !isAccessKeyError(submit.error) ? (
        <AccessKeyPrompt onSaved={() => setShowKeyField(false)} />
      ) : null}
    </div>
  );
}
