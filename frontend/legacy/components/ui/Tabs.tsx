import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";

export interface TabDef {
  id: string;
  label: string;
  badge?: ReactNode;
  panel: ReactNode;
}

/** WAI-ARIA "tabs" pattern: roving tabindex, arrow-key navigation, Home/End,
 * panel association via `aria-controls`/`aria-labelledby`. Native `<button>`
 * elements throughout, so no click handling needs reinventing. */
export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: TabDef[];
  active: string;
  onChange: (id: string) => void;
}) {
  const baseId = useId();
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function focusTab(id: string) {
    onChange(id);
    tabRefs.current[id]?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, idx: number) {
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      focusTab(tabs[(idx + 1) % tabs.length].id);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      focusTab(tabs[(idx - 1 + tabs.length) % tabs.length].id);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusTab(tabs[0].id);
    } else if (event.key === "End") {
      event.preventDefault();
      focusTab(tabs[tabs.length - 1].id);
    }
  }

  const activeTab = tabs.find((t) => t.id === active) ?? tabs[0];

  return (
    <div className="ef-tabs">
      <div className="ef-tabs__list" role="tablist" aria-label="Package sections">
        {tabs.map((tab, idx) => {
          const selected = tab.id === activeTab.id;
          return (
            <button
              key={tab.id}
              ref={(el) => {
                tabRefs.current[tab.id] = el;
              }}
              id={`${baseId}-tab-${tab.id}`}
              role="tab"
              type="button"
              aria-selected={selected}
              aria-controls={`${baseId}-panel-${tab.id}`}
              tabIndex={selected ? 0 : -1}
              className={`ef-tabs__tab${selected ? " ef-tabs__tab--active" : ""}`}
              onClick={() => onChange(tab.id)}
              onKeyDown={(e) => handleKeyDown(e, idx)}
            >
              {tab.label}
              {tab.badge}
            </button>
          );
        })}
      </div>
      {tabs.map((tab) => (
        <div
          key={tab.id}
          id={`${baseId}-panel-${tab.id}`}
          role="tabpanel"
          aria-labelledby={`${baseId}-tab-${tab.id}`}
          hidden={tab.id !== activeTab.id}
          className="ef-tabs__panel"
          tabIndex={0}
        >
          {tab.id === activeTab.id ? tab.panel : null}
        </div>
      ))}
    </div>
  );
}
