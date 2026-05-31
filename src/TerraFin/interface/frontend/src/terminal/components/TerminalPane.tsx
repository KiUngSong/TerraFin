import React from 'react';

interface TerminalPaneProps {
  title: string;
  subtitle?: string;
  children?: React.ReactNode;
  minHeight?: number;
  fillContent?: boolean;
  href?: string;
  allowOverflow?: boolean;
  className?: string;
  contentClassName?: string;
  /**
   * Right-aligned slot in the pane header. Use this for `<SourceTag>` /
   * `<SignedDelta>` headline values that summarize what's inside the pane —
   * Bloomberg-DNA prefers a single dense header line over a sub-title block.
   */
  meta?: React.ReactNode;
  /**
   * Used by the command palette's "Panels" group to scroll to and highlight
   * this pane via `document.getElementById(paneId)`.
   */
  paneId?: string;
}

/**
 * TerminalPane — replaces the rounded white `InsightCard` chrome with a
 * sharp-cornered, mono-typed, dark-surface pane keyed off `--tf-*` tokens.
 * Prop surface mirrors `InsightCard` so widget migration in Phase 4 is a
 * mechanical import swap.
 */
const TerminalPane: React.FC<TerminalPaneProps> = ({
  title,
  subtitle,
  children,
  minHeight = 156,
  fillContent = false,
  href,
  allowOverflow = false,
  className = '',
  contentClassName = '',
  meta,
  paneId,
}) => {
  const paneClassName = [
    'tf-pane',
    href ? 'tf-pane--interactive' : '',
    allowOverflow ? 'tf-pane--overflow' : '',
    fillContent ? 'tf-pane--fill' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const contentClassNames = [
    'tf-pane__content',
    fillContent ? 'tf-pane__content--fill' : '',
    allowOverflow ? 'tf-pane__content--overflow' : '',
    contentClassName,
  ]
    .filter(Boolean)
    .join(' ');

  const paneStyle = {
    ['--tf-pane-min-height' as const]: `${minHeight}px`,
  } as React.CSSProperties;

  const headerNode = (
    <div className="tf-pane__header">
      <div className="tf-pane__title-group">
        <h3 className="tf-pane__title">{title}</h3>
        {subtitle ? <p className="tf-pane__subtitle">{subtitle}</p> : null}
      </div>
      {meta ? <div className="tf-pane__meta">{meta}</div> : null}
    </div>
  );

  const body = (
    <>
      {headerNode}
      <div className={contentClassNames}>{children}</div>
    </>
  );

  if (href) {
    return (
      <a
        id={paneId}
        href={href}
        aria-label={`${title} — open`}
        className={paneClassName}
        style={paneStyle}
      >
        {body}
      </a>
    );
  }

  return (
    <section id={paneId} className={paneClassName} style={paneStyle}>
      {body}
    </section>
  );
};

export default TerminalPane;
