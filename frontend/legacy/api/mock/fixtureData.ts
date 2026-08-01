import rawFixture from "../../fixtures/teacher_knowledge_package.json";
import type { SampleSummary, TeacherKnowledgePackage } from "../types";

/**
 * The one hand-authored, schema-valid fixture TKP (from M0, copied verbatim
 * from `backend/tests/fixtures/json/teacher_knowledge_package.json`). Every
 * mock response in this module is derived from this object rather than
 * invented, so the demo never shows content the pipeline wouldn't actually
 * produce.
 */
export const FIXTURE_TKP = rawFixture as unknown as TeacherKnowledgePackage;

export const FIXTURE_PACKAGE_ID = FIXTURE_TKP.tkp_id;

/** Stable synthetic document id standing in for "the document that produced
 * the fixture above" — there is no real upload behind it in mock mode. */
export const FIXTURE_DOCUMENT_ID = "11111111-1111-4111-8111-111111111111";

export const FIXTURE_SAMPLE: SampleSummary = {
  package_id: FIXTURE_PACKAGE_ID,
  title: `${FIXTURE_TKP.source.title ?? FIXTURE_TKP.classification.topic} (Grade ${
    FIXTURE_TKP.classification.grade_band
  } ${FIXTURE_TKP.classification.subject})`,
  subject: FIXTURE_TKP.classification.subject,
  pedagogy_profile: FIXTURE_TKP.classification.pedagogy_profile,
  periods: FIXTURE_TKP.teaching_plan.total_periods,
  validation_status: FIXTURE_TKP.validation.status,
};
