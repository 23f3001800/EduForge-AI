import { useState } from "react";
import { createJob, isMockMode, uploadDocument } from "../api";
import { ACCEPTED_EXTENSIONS, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB } from "../api/constants";
import { ApiError } from "../api/types";
import type { DocumentKind, JobOptions, TeachingStyle } from "../api/types";
import { Banner } from "../components/ui/Banner";
import { Spinner } from "../components/ui/Spinner";
import { DropZone } from "../components/upload/DropZone";
import { LearningGoalsInput } from "../components/upload/LearningGoalsInput";
import { navigate } from "../router/router";

const TEACHING_STYLES: { value: TeachingStyle; label: string }[] = [
  { value: "balanced", label: "Balanced" },
  { value: "lecture_led", label: "Lecture-led" },
  { value: "discussion_led", label: "Discussion-led" },
  { value: "activity_led", label: "Activity-led" },
  { value: "inquiry_led", label: "Inquiry-led" },
  { value: "exam_focused", label: "Exam-focused" },
];

const DOCUMENT_KINDS: { value: DocumentKind; label: string }[] = [
  { value: "unknown", label: "Not sure — let EduForge decide" },
  { value: "mostly_text", label: "Mostly text" },
  { value: "text_with_tables", label: "Text with tables" },
  { value: "text_with_diagrams", label: "Text with diagrams" },
  { value: "text_with_equations", label: "Text with equations" },
  { value: "scanned_pdf", label: "Scanned pages / photos" },
];

const LANGUAGES: { value: string; label: string }[] = [
  { value: "en", label: "English" },
  { value: "hi", label: "Hindi" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
];

type SubmitPhase = "idle" | "uploading" | "creating_job";

function describeApiError(err: unknown): string {
  if (err instanceof ApiError) {
    return err.message || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  return "Something went wrong. Please try again.";
}

function validateFile(file: File): string | null {
  const lower = file.name.toLowerCase();
  const hasAcceptedExtension = ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
  if (!hasAcceptedExtension) {
    return `Unsupported file type. Accepted: ${ACCEPTED_EXTENSIONS.join(", ")}.`;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `File is larger than the ${MAX_UPLOAD_MB} MB limit.`;
  }
  if (file.size === 0) {
    return "File is empty.";
  }
  return null;
}

export function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | undefined>();
  const [periodDuration, setPeriodDuration] = useState(40);
  const [teachingStyle, setTeachingStyle] = useState<TeachingStyle>("balanced");
  const [targetPeriodCount, setTargetPeriodCount] = useState<string>("");
  const [learningGoals, setLearningGoals] = useState<string[]>([]);
  const [documentKind, setDocumentKind] = useState<DocumentKind>("unknown");
  const [outputLanguage, setOutputLanguage] = useState("en");
  const [curriculumBoard, setCurriculumBoard] = useState("");

  const [phase, setPhase] = useState<SubmitPhase>("idle");
  const [submitError, setSubmitError] = useState<string | null>(null);

  function handleSelect(next: File | null) {
    setFile(next);
    setSubmitError(null);
    if (next) {
      setFileError(validateFile(next) ?? undefined);
    } else {
      setFileError(undefined);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setFileError("Choose a document to continue.");
      return;
    }
    const clientError = validateFile(file);
    if (clientError) {
      setFileError(clientError);
      return;
    }

    setSubmitError(null);
    setPhase("uploading");
    try {
      const uploaded = await uploadDocument(file);

      const options: JobOptions = {
        period_duration_minutes: periodDuration,
        teaching_style: teachingStyle,
        document_kind: documentKind,
        output_language: outputLanguage,
      };
      if (targetPeriodCount.trim() !== "") {
        const parsed = Number(targetPeriodCount);
        if (Number.isFinite(parsed)) options.target_period_count = parsed;
      }
      if (learningGoals.length > 0) options.learning_goals = learningGoals;
      if (curriculumBoard.trim() !== "") options.curriculum_board = curriculumBoard.trim();

      setPhase("creating_job");
      const idempotencyKey = crypto.randomUUID();
      const job = await createJob(uploaded.document_id, options, idempotencyKey);
      navigate(`/run/${job.job_id}`);
    } catch (err) {
      setSubmitError(describeApiError(err));
      setPhase("idle");
    }
  }

  const busy = phase !== "idle";

  return (
    <div className="ef-stack">
      <div>
        <h1 className="ef-page-title">Turn a chapter into a classroom-ready package</h1>
        <p className="ef-page-subtitle">
          Upload a document and EduForge AI builds a teaching plan, per-period lesson
          content, activities, an assessment bank, and a gap analysis — grounded in
          citations back to your source.
        </p>
      </div>

      {isMockMode() ? (
        <Banner tone="info" title="Demo data is on">
          No backend is called. Try filenames containing <code>partial</code> (succeeds with
          warnings) or <code>fail</code> (fails mid-run) to preview those states, or just pick
          any real file for a clean run.
        </Banner>
      ) : null}

      <form className="ef-card ef-stack" onSubmit={handleSubmit} noValidate>
        <DropZone file={file} onSelect={handleSelect} error={fileError} />

        <div className="ef-grid">
          <div className="ef-field">
            <label htmlFor="period-duration">Period length (minutes)</label>
            <input
              id="period-duration"
              type="number"
              min={5}
              max={240}
              value={periodDuration}
              onChange={(e) => setPeriodDuration(Number(e.target.value))}
            />
          </div>

          <div className="ef-field">
            <label htmlFor="teaching-style">Teaching style</label>
            <select
              id="teaching-style"
              value={teachingStyle}
              onChange={(e) => setTeachingStyle(e.target.value as TeachingStyle)}
            >
              {TEACHING_STYLES.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <details className="ef-more-options">
          <summary>More options (optional)</summary>
          <div className="ef-stack" style={{ marginTop: "var(--ef-space-4)" }}>
            <LearningGoalsInput value={learningGoals} onChange={setLearningGoals} />

            <div className="ef-grid">
              <div className="ef-field">
                <label htmlFor="target-periods">Number of periods</label>
                <input
                  id="target-periods"
                  type="number"
                  min={1}
                  max={20}
                  placeholder="Auto"
                  value={targetPeriodCount}
                  onChange={(e) => setTargetPeriodCount(e.target.value)}
                />
                <p className="ef-field__hint">Leave blank to let EduForge derive it from the content.</p>
              </div>

              <div className="ef-field">
                <label htmlFor="document-kind">What does the document mostly contain?</label>
                <select
                  id="document-kind"
                  value={documentKind}
                  onChange={(e) => setDocumentKind(e.target.value as DocumentKind)}
                >
                  {DOCUMENT_KINDS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="ef-field">
                <label htmlFor="output-language">Output language</label>
                <select
                  id="output-language"
                  value={outputLanguage}
                  onChange={(e) => setOutputLanguage(e.target.value)}
                >
                  {LANGUAGES.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="ef-field">
                <label htmlFor="curriculum-board">Curriculum board</label>
                <input
                  id="curriculum-board"
                  type="text"
                  placeholder="e.g. CBSE, ICSE, IB"
                  value={curriculumBoard}
                  onChange={(e) => setCurriculumBoard(e.target.value)}
                />
              </div>
            </div>
          </div>
        </details>

        {submitError ? (
          <Banner tone="danger" title="Could not start the job">
            {submitError}
          </Banner>
        ) : null}

        <div className="ef-row">
          <button type="submit" className="ef-btn ef-btn--primary" disabled={busy || !!fileError}>
            {busy ? <Spinner label="Starting" /> : "Generate teaching package"}
          </button>
          {phase === "uploading" ? <span className="ef-muted">Uploading document…</span> : null}
          {phase === "creating_job" ? <span className="ef-muted">Starting the pipeline…</span> : null}
        </div>
      </form>
    </div>
  );
}
