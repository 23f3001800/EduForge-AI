import type { KnowledgeBase } from "../api/types";
import { Badge } from "../components/ui/Badge";
import { titleCase } from "../utils/format";
import type { PackageLookups } from "../utils/lookups";
import { EvidenceList } from "./EvidenceList";

const IMPORTANCE_TONE = { core: "success", supporting: "info", enrichment: "neutral" } as const;

const RELATION_LABEL: Record<string, string> = {
  prerequisite_of: "is a prerequisite of",
  part_of: "is part of",
  contrasts_with: "contrasts with",
};

export function KnowledgeTab({ knowledge, lookups }: { knowledge: KnowledgeBase; lookups: PackageLookups }) {
  const {
    concepts,
    definitions,
    formulae,
    examples,
    applications,
    misconceptions,
    keywords,
    prerequisites,
    concept_graph,
  } = knowledge;

  return (
    <div className="ef-stack">
      {concepts.length > 0 ? (
        <section>
          <h3 className="ef-section-title">Concepts</h3>
          <div className="ef-stack">
            {concepts.map((c) => (
              <article className="ef-card" key={c.concept_id}>
                <div className="ef-row" style={{ justifyContent: "space-between" }}>
                  <h4 className="ef-subheading">{c.name}</h4>
                  <Badge tone={IMPORTANCE_TONE[c.importance]}>{titleCase(c.importance)}</Badge>
                </div>
                <p>{c.summary}</p>
                <EvidenceList evidence={c.evidence} />
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {definitions.length > 0 ? (
        <section>
          <h3 className="ef-section-title">Definitions</h3>
          <div className="ef-stack">
            {definitions.map((d) => (
              <article className="ef-card" key={d.term}>
                <h4 className="ef-subheading">{d.term}</h4>
                <p>{d.definition}</p>
                <EvidenceList evidence={d.evidence} />
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {formulae.length > 0 ? (
        <section>
          <h3 className="ef-section-title">Formulae</h3>
          <div className="ef-stack">
            {formulae.map((f, i) => (
              <article className="ef-card" key={i}>
                {f.name ? <h4 className="ef-subheading">{f.name}</h4> : null}
                <p className="ef-formula">{f.latex}</p>
                <p className="ef-muted">{f.plain}</p>
                {f.variables.length > 0 ? (
                  <table className="ef-variable-table">
                    <caption className="ef-visually-hidden">Variables</caption>
                    <tbody>
                      {f.variables.map((v) => (
                        <tr key={v.symbol}>
                          <td>
                            <code>{v.symbol}</code>
                          </td>
                          <td>{v.meaning}</td>
                          <td className="ef-muted">{v.unit ?? ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : null}
                <EvidenceList evidence={f.evidence} />
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {examples.length > 0 ? (
        <section>
          <h3 className="ef-section-title">Examples</h3>
          <div className="ef-stack">
            {examples.map((ex, i) => (
              <article className="ef-card" key={i}>
                <h4 className="ef-subheading">{ex.title}</h4>
                <p>{ex.body}</p>
                <EvidenceList evidence={ex.evidence} />
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {applications.length > 0 ? (
        <section>
          <h3 className="ef-section-title">Real-world applications</h3>
          <div className="ef-stack">
            {applications.map((app, i) => (
              <article className="ef-card" key={i}>
                <h4 className="ef-subheading">{app.context}</h4>
                <p>{app.description}</p>
                <EvidenceList evidence={app.evidence} />
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {misconceptions.length > 0 ? (
        <section>
          <h3 className="ef-section-title">Common misconceptions</h3>
          <div className="ef-stack">
            {misconceptions.map((m) => (
              <article className="ef-card" key={m.misconception_id}>
                <p className="ef-assessment-item__stem">{m.statement}</p>
                <p>
                  <strong>Why it happens:</strong> {m.why_it_happens}
                </p>
                <p>
                  <strong>Correction:</strong> {m.correction}
                </p>
                <EvidenceList evidence={m.evidence} />
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {prerequisites.length > 0 ? (
        <section>
          <h3 className="ef-section-title">Prerequisites</h3>
          <ul className="ef-bullet-list">
            {prerequisites.map((p, i) => (
              <li key={i}>{p.statement}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {concept_graph.edges.length > 0 ? (
        <section>
          <h3 className="ef-section-title">Concept relationships</h3>
          <ul className="ef-bullet-list">
            {concept_graph.edges.map((edge, i) => (
              <li key={i}>
                {lookups.conceptName(edge.from_id)} {RELATION_LABEL[edge.relation] ?? edge.relation}{" "}
                {lookups.conceptName(edge.to_id)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {keywords.length > 0 ? (
        <section>
          <h3 className="ef-section-title">Keywords</h3>
          <div className="ef-row">
            {keywords.map((k) => (
              <span className="ef-tag" key={k}>
                {k}
              </span>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
