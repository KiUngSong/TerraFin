import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { PanelDef, WidgetId } from '../layout';

interface PanelFrameProps {
  panel: PanelDef;
  catalog: Record<WidgetId, React.ReactNode>;
  height?: number | string;
}

const PanelFrame: React.FC<PanelFrameProps> = ({ panel, catalog, height }) => {
  const [activeId, setActiveId] = useState<WidgetId>(panel.tabs[0].id);
  const rootRef = useRef<HTMLDivElement>(null);
  const activeTab = panel.tabs.find((t) => t.id === activeId) ?? panel.tabs[0];
  // Tape (panel 1) headerless — the marquee is self-labeling.
  const headerless = panel.number === 1;

  const focusPanel = useCallback(() => {
    rootRef.current?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (!event.altKey || event.metaKey || event.ctrlKey) return;
      const num = parseInt(event.key, 10);
      if (Number.isNaN(num) || num !== panel.number) return;
      event.preventDefault();
      focusPanel();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [focusPanel, panel.number]);

  const onTabKey = (event: React.KeyboardEvent) => {
    if (event.ctrlKey && event.key === 'Tab') {
      event.preventDefault();
      const idx = panel.tabs.findIndex((t) => t.id === activeId);
      const next = panel.tabs[(idx + 1) % panel.tabs.length];
      setActiveId(next.id);
    }
  };

  return (
    <div
      ref={rootRef}
      className="tf-panel"
      style={{ gridArea: panel.area, height }}
      tabIndex={-1}
      data-panel-number={panel.number}
      onKeyDown={onTabKey}
    >
      {headerless ? null : (
      <div className="tf-panel__header">
        <div className="tf-panel__tabs" role="tablist">
          {panel.tabs.map((tab) => {
            const active = tab.id === activeId;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={active}
                className={`tf-panel__tab${active ? ' tf-panel__tab--active' : ''}`}
                onClick={() => {
                  setActiveId(tab.id);
                  focusPanel();
                }}
                title={tab.href ? `open ${tab.href}` : undefined}
              >
                <span className="tf-panel__tab-label">{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>
      )}
      <div className="tf-panel__body">{catalog[activeId] ?? null}</div>
    </div>
  );
};

export default PanelFrame;
