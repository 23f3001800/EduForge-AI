import type { Activity, Concept, KnowledgeBase, LearningObjective } from "../api/types";

/** Resolves the id-reference soup in a TKP (`concept_ids`, `objective_ids`,
 * `activity_refs`) into display names, so the viewer never shows a raw
 * `concept_second_law` token to a teacher. */
export interface PackageLookups {
  conceptName: (id: string) => string;
  objectiveStatement: (id: string) => string;
  activityById: (id: string) => Activity | undefined;
}

export function buildLookups(knowledge: KnowledgeBase, activities: Activity[]): PackageLookups {
  const concepts = new Map<string, Concept>(knowledge.concepts.map((c) => [c.concept_id, c]));
  const objectives = new Map<string, LearningObjective>(
    knowledge.learning_objectives.map((o) => [o.objective_id, o]),
  );
  const activityMap = new Map<string, Activity>(activities.map((a) => [a.activity_id, a]));

  return {
    conceptName: (id) => concepts.get(id)?.name ?? id,
    objectiveStatement: (id) => objectives.get(id)?.statement ?? id,
    activityById: (id) => activityMap.get(id),
  };
}

export function resolveNames(ids: string[], resolve: (id: string) => string): string[] {
  return ids.map(resolve);
}
