import { useId, useState, type KeyboardEvent } from "react";

const MAX_GOALS = 10;

/** Free-text "chips" input for `JobOptions.learning_goals` (max 10, per the
 * contract). Enter or comma commits the current text as a chip; Backspace on
 * an empty field removes the last one. Entirely optional — the field starts
 * empty and an empty list is a valid, default-safe submission. */
export function LearningGoalsInput({
  value,
  onChange,
}: {
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const inputId = useId();

  function commit() {
    const trimmed = draft.trim();
    if (!trimmed) return;
    if (value.length >= MAX_GOALS) return;
    if (value.includes(trimmed)) {
      setDraft("");
      return;
    }
    onChange([...value, trimmed]);
    setDraft("");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commit();
    } else if (event.key === "Backspace" && draft === "" && value.length > 0) {
      onChange(value.slice(0, -1));
    }
  }

  function removeAt(idx: number) {
    onChange(value.filter((_, i) => i !== idx));
  }

  return (
    <div className="ef-field">
      <label htmlFor={inputId}>Learning goals for this unit (optional)</label>
      <div className="ef-chip-input">
        {value.map((goal, idx) => (
          <span className="ef-chip" key={goal}>
            {goal}
            <button
              type="button"
              className="ef-chip__remove"
              onClick={() => removeAt(idx)}
              aria-label={`Remove goal "${goal}"`}
            >
              ×
            </button>
          </span>
        ))}
        {value.length < MAX_GOALS ? (
          <input
            id={inputId}
            type="text"
            value={draft}
            placeholder={value.length === 0 ? "e.g. Students should be able to solve numerically…" : "Add another"}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={commit}
          />
        ) : null}
      </div>
      <p className="ef-field__hint">
        Press Enter to add. Merged with the objectives found in the document — up to {MAX_GOALS}.
      </p>
    </div>
  );
}
