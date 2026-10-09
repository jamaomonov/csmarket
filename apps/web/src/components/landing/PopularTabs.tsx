"use client";

/** Switches between server-rendered panels; every panel is in the HTML (crawlable). */
import { type ReactNode, useState } from "react";

export interface TabPanel {
  key: string;
  label: string;
  node: ReactNode;
}

interface Props {
  title: ReactNode;
  label: string;
  panels: TabPanel[];
  footer: ReactNode;
}

export function PopularTabs({ title, label, panels, footer }: Props) {
  const [active, setActive] = useState(panels[0]?.key ?? "");
  return (
    <div className="wrap">
      <div className="sec-h">
        {title}
        <div className="tabs" role="tablist" aria-label={label}>
          {panels.map((p) => (
            <button
              key={p.key}
              type="button"
              role="tab"
              id={`lp-tab-${p.key}`}
              aria-selected={p.key === active}
              aria-controls={`lp-panel-${p.key}`}
              className="tab"
              onClick={() => {
                setActive(p.key);
              }}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      {panels.map((p) => (
        <div
          key={p.key}
          id={`lp-panel-${p.key}`}
          role="tabpanel"
          aria-labelledby={`lp-tab-${p.key}`}
          className="grid"
          hidden={p.key !== active}
        >
          {p.node}
        </div>
      ))}
      {footer}
    </div>
  );
}
