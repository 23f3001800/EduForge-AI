import { useState } from "react";
import type { AssessmentBank, AssessmentItem } from "../api/types";
import { Badge } from "../components/ui/Badge";
import { titleCase } from "../utils/format";
import type { PackageLookups } from "../utils/lookups";

const KIND_LABELS: Record<string, string> = {
  mcq: "Multiple choice",
  short_answer: "Short answer",
  long_answer: "Long answer",
  numerical: "Numerical",
};

function AnswerKeyPanel({ item }: { item: AssessmentItem }) {
  return (
    <div className="ef-answer-key">
      <div className="ef-answer-key__label">
        <span aria-hidden="true">🔑</span> Answer key — teacher copy only
      </div>
      {item.options ? (
        <ul className="ef-bullet-list">
          {item.options.map((opt) => (
            <li key={opt.label} className={opt.is_correct ? "ef-answer-key__correct" : undefined}>
              <strong>{opt.label}.</strong> {opt.text}
              {opt.is_correct ? <Badge tone="success">Correct</Badge> : null}
              {opt.rationale ? <div className="ef-muted">{opt.rationale}</div> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p>
          <strong>Answer:</strong> {item.answer}
        </p>
      )}
      {item.working ? (
        <p>
          <strong>Working:</strong> {item.working}
        </p>
      ) : null}
      {item.rubric ? (
        <div>
          <strong>Rubric — {item.rubric.criteria}</strong>
          <ul className="ef-bullet-list">
            {item.rubric.levels.map((level) => (
              <li key={level.label}>
                {level.label} ({level.marks} marks): {level.descriptor}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function AssessmentItemCard({
  item,
  showAnswers,
  lookups,
}: {
  item: AssessmentItem;
  showAnswers: boolean;
  lookups: PackageLookups;
}) {
  return (
    <article className="ef-card ef-assessment-item">
      <div className="ef-row" style={{ justifyContent: "space-between" }}>
        <div className="ef-row" style={{ gap: "var(--ef-space-1)" }}>
          <Badge tone="info">{KIND_LABELS[item.kind] ?? titleCase(item.kind)}</Badge>
          <Badge tone="neutral">{titleCase(item.bloom_level)}</Badge>
          <Badge tone="neutral">
            {item.marks} mark{item.marks === 1 ? "" : "s"}
          </Badge>
        </div>
      </div>

      <p className="ef-assessment-item__stem">{item.stem}</p>

      {item.options ? (
        <ul className="ef-bullet-list">
          {item.options.map((opt) => (
            <li key={opt.label}>
              <strong>{opt.label}.</strong> {opt.text}
            </li>
          ))}
        </ul>
      ) : null}

      {item.concept_ids.length > 0 ? (
        <div className="ef-row">
          {item.concept_ids.map((id) => (
            <span className="ef-tag" key={id}>
              {lookups.conceptName(id)}
            </span>
          ))}
        </div>
      ) : null}

      {showAnswers ? <AnswerKeyPanel item={item} /> : null}
    </article>
  );
}

export function AssessmentsTab({ bank, lookups }: { bank: AssessmentBank; lookups: PackageLookups }) {
  const [showAnswers, setShowAnswers] = useState(false);

  if (bank.items.length === 0) return null;

  const kindEntries = Object.entries(bank.blueprint.items_by_kind).filter(([, count]) => count > 0);
  const bloomEntries = Object.entries(bank.blueprint.items_by_bloom).filter(([, count]) => count > 0);
  const conceptMarkEntries = Object.entries(bank.blueprint.marks_by_concept);

  return (
    <div className="ef-stack">
      <div className="ef-card">
        <div className="ef-row" style={{ justifyContent: "space-between" }}>
          <h3 className="ef-section-title">Blueprint</h3>
          <strong>{bank.total_marks} total marks</strong>
        </div>
        <div className="ef-grid">
          {kindEntries.length > 0 ? (
            <div>
              <h4 className="ef-subheading ef-subheading--sm">By type</h4>
              <div className="ef-row">
                {kindEntries.map(([kind, count]) => (
                  <Badge tone="neutral" key={kind}>
                    {KIND_LABELS[kind] ?? titleCase(kind)}: {count}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}
          {bloomEntries.length > 0 ? (
            <div>
              <h4 className="ef-subheading ef-subheading--sm">By Bloom level</h4>
              <div className="ef-row">
                {bloomEntries.map(([level, count]) => (
                  <Badge tone="neutral" key={level}>
                    {titleCase(level)}: {count}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}
          {conceptMarkEntries.length > 0 ? (
            <div>
              <h4 className="ef-subheading ef-subheading--sm">Marks by concept</h4>
              <div className="ef-row">
                {conceptMarkEntries.map(([conceptId, marks]) => (
                  <Badge tone="neutral" key={conceptId}>
                    {lookups.conceptName(conceptId)}: {marks}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <div className="ef-row" style={{ justifyContent: "flex-end" }}>
        <label className="ef-toggle">
          <input type="checkbox" checked={showAnswers} onChange={(e) => setShowAnswers(e.target.checked)} />
          <span>Show answer key</span>
        </label>
      </div>

      {bank.items.map((item) => (
        <AssessmentItemCard key={item.item_id} item={item} showAnswers={showAnswers} lookups={lookups} />
      ))}
    </div>
  );
}
