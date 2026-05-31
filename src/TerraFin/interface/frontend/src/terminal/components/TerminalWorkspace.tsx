import React from 'react';
import PanelFrame from './PanelFrame';
import type { PresetDef, WidgetId } from '../layout';

interface TerminalWorkspaceProps {
  preset: PresetDef;
  catalog: Record<WidgetId, React.ReactNode>;
}

const TerminalWorkspace: React.FC<TerminalWorkspaceProps> = ({ preset, catalog }) => {
  const style: React.CSSProperties = {
    gridTemplateColumns: preset.gridTemplate.columns,
    gridTemplateRows: preset.gridTemplate.rows,
    gridTemplateAreas: preset.gridTemplate.areas,
  };

  return (
    <div className="tf-workspace" style={style}>
      {preset.panels.map((panel) => (
        <PanelFrame key={panel.number} panel={panel} catalog={catalog} />
      ))}
    </div>
  );
};

export default TerminalWorkspace;
