import React from 'react';
import { useViewportTier } from '../../shared/responsive';
import { DashboardWidgetDefinition } from '../layout';

export interface DashboardWidgetPlacement extends DashboardWidgetDefinition {
  element: React.ReactNode;
}

interface DashboardLayoutProps {
  widgets: DashboardWidgetPlacement[];
}

const sortByOrder = (widgets: DashboardWidgetPlacement[], key: 'order' | 'mobileOrder') =>
  [...widgets].sort((left, right) => left[key] - right[key]);

const renderWidget = (widget: DashboardWidgetPlacement) => {
  const classes = [
    'tf-dashboard-layout__widget',
    `tf-dashboard-layout__widget--${widget.slot}`,
    widget.fill ? 'tf-dashboard-layout__widget--fill' : '',
  ]
    .filter(Boolean)
    .join(' ');

  const style = (
    widget.minHeight != null
      ? ({
          ['--tf-dashboard-widget-min-height' as const]: `${widget.minHeight}px`,
        } as React.CSSProperties)
      : undefined
  );

  return (
    <div key={widget.id} className={classes} style={style}>
      {widget.element}
    </div>
  );
};

const DashboardLayout: React.FC<DashboardLayoutProps> = ({ widgets }) => {
  const { tier } = useViewportTier();

  const heroWidgets = sortByOrder(
    widgets.filter((widget) => widget.slot === 'hero'),
    'order'
  );
  const primaryWidgets = sortByOrder(
    widgets.filter((widget) => widget.slot === 'primary'),
    'order'
  );
  const railWidgets = sortByOrder(
    widgets.filter((widget) => widget.slot === 'rail'),
    'order'
  );

  if (tier === 'mobile') {
    return (
      <div className="tf-dashboard-layout tf-dashboard-layout--mobile">
        {sortByOrder(widgets, 'mobileOrder').map(renderWidget)}
      </div>
    );
  }

  if (tier === 'tablet') {
    return (
      <div className="tf-dashboard-layout tf-dashboard-layout--tablet">
        <div className="tf-dashboard-layout__hero">{heroWidgets.map(renderWidget)}</div>
        <div className="tf-dashboard-layout__primary">{primaryWidgets.map(renderWidget)}</div>
        <div className="tf-dashboard-layout__rail tf-dashboard-layout__rail--grid">
          {railWidgets.map(renderWidget)}
        </div>
      </div>
    );
  }

  return (
    <div className="tf-dashboard-layout tf-dashboard-layout--desktop">
      <div className="tf-dashboard-layout__hero">{heroWidgets.map(renderWidget)}</div>
      <div className="tf-dashboard-layout__body">
        <div className="tf-dashboard-layout__primary">{primaryWidgets.map(renderWidget)}</div>
        <div className="tf-dashboard-layout__rail">{railWidgets.map(renderWidget)}</div>
      </div>
    </div>
  );
};

export default DashboardLayout;
