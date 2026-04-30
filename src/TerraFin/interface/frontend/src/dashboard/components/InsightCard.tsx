import React from 'react';

interface InsightCardProps {
  title: string;
  subtitle: string;
  children?: React.ReactNode;
  minHeight?: number;
  fillContent?: boolean;
  href?: string;
  allowOverflow?: boolean;
  className?: string;
  contentClassName?: string;
}

const InsightCard: React.FC<InsightCardProps> = ({
  title,
  subtitle,
  children,
  minHeight = 156,
  fillContent = false,
  href,
  allowOverflow = false,
  className = '',
  contentClassName = '',
}) => {
  const cardClassName = [
    'tf-insight-card',
    href ? 'tf-insight-card--interactive' : '',
    allowOverflow ? 'tf-insight-card--overflow' : '',
    fillContent ? 'tf-insight-card--fill' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const contentClassNames = [
    'tf-insight-card__content',
    fillContent ? 'tf-insight-card__content--fill' : '',
    allowOverflow ? 'tf-insight-card__content--overflow' : '',
    contentClassName,
  ]
    .filter(Boolean)
    .join(' ');

  const cardStyle = {
    ['--tf-insight-card-min-height' as const]: `${minHeight}px`,
  } as React.CSSProperties;

  const content = (
    <>
      {title ? (
        <div className="tf-insight-card__header">
          <h3 className="tf-insight-card__title">{title}</h3>
          {subtitle ? <p className="tf-insight-card__subtitle">{subtitle}</p> : null}
        </div>
      ) : null}
      <div className={contentClassNames}>{children}</div>
    </>
  );

  if (href) {
    return (
      <a
        href={href}
        aria-label={`${title} - open in Market Insights`}
        className={cardClassName}
        style={cardStyle}
      >
        {content}
      </a>
    );
  }

  return (
    <section className={cardClassName} style={cardStyle}>
      {content}
    </section>
  );
};

export default InsightCard;
