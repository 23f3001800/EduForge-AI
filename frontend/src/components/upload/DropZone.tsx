import { useId, useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import { ACCEPTED_EXTENSIONS, MAX_UPLOAD_MB } from "../../api/constants";
import { formatBytes } from "../../utils/format";

export function DropZone({
  file,
  onSelect,
  error,
}: {
  file: File | null;
  onSelect: (file: File | null) => void;
  error?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const describedById = useId();

  function openPicker() {
    inputRef.current?.click();
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) onSelect(dropped);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openPicker();
    }
  }

  return (
    <div className="ef-field">
      <span id={`${describedById}-label`} className="ef-field__label-text">
        Document
      </span>
      <div
        className={`ef-dropzone${dragging ? " ef-dropzone--active" : ""}${error ? " ef-dropzone--error" : ""}`}
        role="button"
        tabIndex={0}
        aria-labelledby={`${describedById}-label`}
        aria-describedby={describedById}
        onClick={openPicker}
        onKeyDown={handleKeyDown}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          className="ef-visually-hidden"
          onChange={(e) => onSelect(e.target.files?.[0] ?? null)}
          aria-hidden="true"
          tabIndex={-1}
        />
        {file ? (
          <div className="ef-dropzone__file">
            <strong>{file.name}</strong>
            <span className="ef-muted">{formatBytes(file.size)}</span>
            <button
              type="button"
              className="ef-btn ef-btn--secondary ef-btn--sm"
              onClick={(e) => {
                e.stopPropagation();
                onSelect(null);
              }}
            >
              Remove
            </button>
          </div>
        ) : (
          <div className="ef-dropzone__prompt">
            <p>
              <strong>Click to choose a file</strong> or drag it here
            </p>
            <p className="ef-muted" id={describedById}>
              PDF, DOCX, PPTX, TXT or MD, up to {MAX_UPLOAD_MB} MB.
            </p>
          </div>
        )}
      </div>
      {error ? (
        <p className="ef-field__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
