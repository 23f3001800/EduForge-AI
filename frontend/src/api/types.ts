/**
 * Domain types mirroring `backend/contracts/` (see docs/03-lld.md §1 and
 * docs/06-api-spec.md). The frontend does not own these definitions — if the
 * contract changes, this file must follow. Kept close to the Pydantic model
 * shapes so a diff against `contracts/schema/tkp-1.0.0.json` stays cheap.
 */

// ---------------------------------------------------------------- primitives

export interface Evidence {
  chunk_id: string;
  page: number | null;
  quote: string;
  confidence: number;
}

export type BloomLevel =
  | "remember"
  | "understand"
  | "apply"
  | "analyze"
  | "evaluate"
  | "create";

export type PedagogyProfile =
  | "quantitative"
  | "conceptual"
  | "narrative"
  | "procedural"
  | "mixed";

export type Difficulty = "foundational" | "intermediate" | "advanced";
export type Severity = "low" | "medium" | "high";

// ------------------------------------------------------------ classification

export interface CurriculumAlignment {
  board: "CBSE" | "ICSE" | "CommonCore" | "IB" | "Other";
  mapped_standards: unknown[];
  confidence: number;
}

export interface Classification {
  subject: string;
  grade_band: string;
  difficulty: Difficulty;
  topic: string;
  chapter: string | null;
  category: string;
  language: string;
  pedagogy_profile: PedagogyProfile;
  curriculum_alignment: CurriculumAlignment | null;
  confidences: Record<string, number>;
  low_confidence_fields: string[];
}

// ------------------------------------------------------------------- knowledge

export interface Concept {
  concept_id: string;
  name: string;
  summary: string;
  importance: "core" | "supporting" | "enrichment";
  evidence: Evidence[];
}

export interface Definition {
  term: string;
  definition: string;
  concept_ids: string[];
  evidence: Evidence[];
}

export interface VariableDef {
  symbol: string;
  meaning: string;
  unit: string | null;
}

export interface Formula {
  name: string | null;
  latex: string;
  plain: string;
  variables: VariableDef[];
  concept_ids: string[];
  evidence: Evidence[];
}

export interface LearningObjective {
  objective_id: string;
  statement: string;
  bloom_level: BloomLevel;
  concept_ids: string[];
}

export interface Misconception {
  misconception_id: string;
  statement: string;
  why_it_happens: string;
  correction: string;
  concept_ids: string[];
  evidence: Evidence[];
}

export interface Example {
  title: string;
  body: string;
  concept_ids: string[];
  evidence: Evidence[];
}

export interface Application {
  context: string;
  description: string;
  concept_ids: string[];
  evidence: Evidence[];
}

export interface Prerequisite {
  statement: string;
  concept_ids: string[];
}

export interface ConceptEdge {
  from_id: string;
  to_id: string;
  relation: "prerequisite_of" | "part_of" | "contrasts_with";
  confidence: number;
}

export interface ConceptGraph {
  node_ids: string[];
  edges: ConceptEdge[];
}

export interface KnowledgeBase {
  learning_objectives: LearningObjective[];
  prerequisites: Prerequisite[];
  concepts: Concept[];
  definitions: Definition[];
  formulae: Formula[];
  keywords: string[];
  examples: Example[];
  applications: Application[];
  misconceptions: Misconception[];
  concept_graph: ConceptGraph;
}

// --------------------------------------------------------------- teaching plan

export interface TimeSlot {
  label: string;
  minutes: number;
}

export interface Period {
  period_no: number;
  title: string;
  objective_ids: string[];
  concept_ids: string[];
  time_allocation: TimeSlot[];
  sequence_rationale: string;
}

export interface TeachingPlan {
  total_periods: number;
  period_duration_minutes: number;
  periods: Period[];
  unmapped_objective_ids: string[];
}

// -------------------------------------------------------------- period content

export interface EntryTicket {
  prompt: string;
  duration_minutes: number;
  expected_response: string;
}

export interface ScriptSegment {
  heading: string;
  minute_start: number;
  minute_end: number;
  speaker_notes: string;
  board_action: string | null;
  anticipated_questions: string[];
}

export interface BlackboardNotes {
  headings: string[];
  bullet_points: string[];
  formulae_latex: string[];
  diagrams_to_draw: string[];
}

export interface CheckpointQuestion {
  question: string;
  expected_answer: string;
  bloom_level: BloomLevel;
  concept_ids: string[];
}

export interface ExitTicket {
  prompt: string;
  duration_minutes: number;
  success_indicator: string;
}

export interface Homework {
  tasks: string[];
  estimated_minutes: number;
  submission_format: string;
}

export interface MentorMoment {
  title: string;
  story: string;
  takeaway: string;
  grounded: false;
}

export interface PeriodContent {
  period_no: number;
  entry_ticket: EntryTicket;
  teacher_script: ScriptSegment[];
  blackboard_notes: BlackboardNotes;
  activity_refs: string[];
  checkpoint_questions: CheckpointQuestion[];
  exit_ticket: ExitTicket;
  homework: Homework;
  mentor_moment: MentorMoment;
}

// ------------------------------------------------------------------- activity

export type ActivityType = string;

export interface Differentiation {
  support: string;
  extension: string;
}

export interface Activity {
  activity_id: string;
  period_no: number;
  type: ActivityType;
  title: string;
  duration_minutes: number;
  materials: string[];
  teacher_instructions: string[];
  student_instructions: string[];
  success_criteria: string[];
  differentiation: Differentiation;
  concept_ids: string[];
}

// ----------------------------------------------------------------- assessment

export interface MCQOption {
  label: string;
  text: string;
  is_correct: boolean;
  rationale: string | null;
}

export interface RubricLevel {
  label: string;
  descriptor: string;
  marks: number;
}

export interface Rubric {
  criteria: string;
  levels: RubricLevel[];
}

export type AssessmentKind = "mcq" | "short_answer" | "long_answer" | "numerical";

export interface AssessmentItem {
  item_id: string;
  kind: AssessmentKind;
  stem: string;
  options: MCQOption[] | null;
  answer: string;
  working: string | null;
  marks: number;
  bloom_level: BloomLevel;
  concept_ids: string[];
  rubric: Rubric | null;
  linked_misconception_id: string | null;
}

export interface AssessmentBlueprint {
  items_by_kind: Record<string, number>;
  items_by_bloom: Record<string, number>;
  marks_by_concept: Record<string, number>;
}

export interface AssessmentBank {
  items: AssessmentItem[];
  blueprint: AssessmentBlueprint;
  total_marks: number;
}

// -------------------------------------------------------------- learning gaps

export interface DiagnosticQuestion {
  question: string;
  expected_wrong_answer: string;
  reveals: string;
}

export interface RemediationStep {
  action: string;
  rationale: string;
  estimated_minutes: number;
}

export interface LearningGap {
  gap_id: string;
  misconception: string;
  concept_ids: string[];
  severity: Severity;
  diagnostic_questions: DiagnosticQuestion[];
  remediation: RemediationStep[];
  evidence: Evidence[];
}

// --------------------------------------------------------------- validation

export interface ValidationIssue {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
  path: string;
  stage: string;
}

export interface CoverageReport {
  concepts_total: number;
  concepts_taught: number;
  objectives_total: number;
  objectives_planned?: number;
  objectives_assessed: number;
  unassessed_objective_ids?: string[];
  untaught_concept_ids?: string[];
}

export interface ConsistencyReport {
  duplicate_concept_ids?: string[];
  duplicate_concepts?: string[];
  prerequisite_violations: unknown[];
  timing_ok: boolean;
  dangling_activity_refs?: string[];
}

export interface UnsupportedClaim {
  path: string;
  claim: string;
  reason: string;
}

export type ValidationStatus = "pass" | "pass_with_warnings" | "fail";

export interface ValidationReport {
  status: ValidationStatus;
  schema_ok: boolean;
  coverage: CoverageReport;
  consistency: ConsistencyReport;
  grounding_score: number;
  unsupported_claims: UnsupportedClaim[];
  issues: ValidationIssue[];
  checked_at: string;
  profile_ruleset?: string;
  attempts?: number;
}

// ------------------------------------------------------------------ package

export interface DocumentMetadata {
  filename: string;
  mime: string;
  sha256: string;
  page_count: number;
  word_count: number;
  title: string | null;
  author: string | null;
  created_at: string | null;
  detected_language: string | null;
  size_bytes?: number;
}

export interface GeneratorInfo {
  app_version: string;
  models_by_stage: Record<string, string>;
  providers_by_stage: Record<string, string>;
}

export interface StageTiming {
  stage: string;
  attempts: number;
  degraded: boolean;
  duration_ms: number;
  tokens_in: number;
  tokens_out: number;
  tokens_cached: number;
}

export interface Provenance {
  citations: unknown[];
  stage_timings: StageTiming[];
  total_cost_usd: number;
  total_duration_ms: number;
  total_tokens_in: number;
  total_tokens_out: number;
}

export interface TeacherKnowledgePackage {
  schema_version: string;
  tkp_id: string;
  generated_at: string;
  generator: GeneratorInfo;
  source: DocumentMetadata;
  classification: Classification;
  knowledge: KnowledgeBase;
  teaching_plan: TeachingPlan;
  classroom_content: PeriodContent[];
  activities: Activity[];
  assessments: AssessmentBank;
  learning_gaps: LearningGap[];
  validation: ValidationReport;
  provenance: Provenance;
}

// --------------------------------------------------------------------- jobs

export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "succeeded_partial"
  | "failed"
  | "cancelled";

export type StageStatus = "pending" | "running" | "completed" | "failed" | "skipped";

/** Kept for the demo-mode timeline visualisation only — the real
 * `GET /jobs/{id}` response does not return a per-stage status list, just
 * `completed_stages` (see `JobSnapshot` below). */
export interface JobStageSnapshot {
  stage: string;
  status: StageStatus;
  duration_ms?: number;
  completed_items?: number;
  total_items?: number;
}

/** Mirrors the literal dict `jobs.py::get_job` returns — `{tokens, cost_usd}`,
 * not the richer token breakdown a `JobOptions`-shaped usage object might
 * suggest. */
export interface JobUsage {
  tokens: number;
  cost_usd: number;
}

/** Mirrors `JobRecord.error` (`core/storage/base.py`): `{type, message}`,
 * set verbatim from `type(exc).__name__` and `str(exc)`. There is no
 * `code`/`details` envelope on this path — that shape only exists on the
 * HTTP `ApiErrorBody` for request-time failures. */
export interface JobErrorInfo {
  type: string;
  message: string;
}

/** Wire shape of `GET /jobs/{id}` (`backend/api/routes/jobs.py::get_job`). */
export interface JobSnapshot {
  job_id: string;
  document_id: string;
  status: JobStatus;
  current_stage: string | null;
  progress: number;
  /** Stage names with a persisted checkpoint — order not guaranteed, the
   * route sorts alphabetically, not pipeline order. */
  completed_stages: string[];
  package_id: string | null;
  usage: JobUsage;
  warnings: string[];
  error: JobErrorInfo | null;
  created_at: string;
  finished_at: string | null;
}

export interface CreateJobResponse {
  job_id: string;
  status: JobStatus;
  progress: number;
  events_url: string;
  created_at: string;
}

// --------------------------------------------------------------- SSE events

export interface ProgressEventData {
  stage: string;
  progress: number;
  message?: string;
  ts?: string;
  completed_items?: number;
  total_items?: number;
  [key: string]: unknown;
}

export interface CompletedEventData extends ProgressEventData {
  package_id: string;
  status: ValidationStatus | JobStatus;
}

export interface FailedEventData extends ProgressEventData {
  error: JobErrorInfo;
}

export type JobEventName = "progress" | "warning" | "completed" | "failed";

export interface JobEvent {
  seq: number;
  event: JobEventName;
  data: ProgressEventData | CompletedEventData | FailedEventData;
}

// --------------------------------------------------------------- documents

export interface UploadDocumentResponse {
  document_id: string;
  sha256: string;
  filename: string;
  mime: string;
  page_count: number;
  word_count: number;
  detected_language: string;
  deduplicated: boolean;
}

export interface DocumentDetail extends UploadDocumentResponse {
  outline: unknown[];
  stats: { equations: number; tables: number; figures: number; headings: number };
  chunk_count: number;
}

// ----------------------------------------------------------------- artifacts

export type ArtifactKind =
  | "tkp_json"
  | "lesson_plan_pdf"
  | "teacher_guide_pdf"
  | "assessment_book_pdf"
  | "markdown_bundle";

export interface Artifact {
  kind: ArtifactKind;
  mime: string;
  bytes: number;
  status: "ready" | "failed";
  url: string;
}

export interface ArtifactListing {
  artifacts: Artifact[];
}

// ------------------------------------------------------------------- samples

export interface SampleSummary {
  package_id: string;
  title: string;
  subject: string;
  pedagogy_profile: PedagogyProfile;
  periods: number;
  validation_status: ValidationStatus;
}

export interface SamplesResponse {
  samples: SampleSummary[];
}

// ---------------------------------------------------------------- error envelope

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    trace_id?: string;
  };
}

export class ApiError extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown>;
  traceId?: string;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.error.code;
    this.details = body.error.details;
    this.traceId = body.error.trace_id;
  }
}

// ------------------------------------------------------------------- options

/** Mirrors `backend/contracts/jobs.py::TeachingStyle`. */
export type TeachingStyle =
  | "balanced"
  | "lecture_led"
  | "discussion_led"
  | "activity_led"
  | "inquiry_led"
  | "exam_focused";

/** Mirrors `backend/contracts/jobs.py::DocumentKind`. */
export type DocumentKind =
  | "mostly_text"
  | "text_with_tables"
  | "text_with_diagrams"
  | "text_with_equations"
  | "scanned_pdf"
  | "unknown";

/** Mirrors `backend/contracts/jobs.py::JobOptions`. Every field is optional
 * with a server-side default — the point of the contract (FAQ Q5) is that a
 * teacher who answers nothing still gets a good package. */
export interface JobOptions {
  period_duration_minutes?: number;
  teaching_style?: TeachingStyle;
  learning_goals?: string[];
  document_kind?: DocumentKind;
  target_period_count?: number | null;
  output_language?: string;
  curriculum_board?: string | null;
  include_artifacts?: ArtifactKind[];
}
