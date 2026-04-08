import React from 'react';

interface InsightCardProps {
  title: string;
  subtitle: string;
  children?: React.ReactNode;
  minHeight?: number;
  fillContent?: boolean;
  href?: string;
  allowOverflow?: boolean;
}

const InsightCard: React.FC<InsightCardProps> = ({
  title,
  subtitle,
  children,
  minHeight = 156,
  fillContent = false,
  href,
  allowOverflow = false,
}) => {
  const cardStyle: React.CSSProperties = {
    background: '#ffffff',
    borderRadius: 14,
    border: '1px solid #e2e8f0',
    boxShadow: '0 8px 20px rgba(15, 23, 42, 0.04)',
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    minHeight,
    minWidth: 0,
    overflow: allowOverflow ? 'visible' : 'hidden',
    ...(fillContent ? { height: '100%', boxSizing: 'border-box' as const } : {}),
    ...(href
      ? {
          textDecoration: 'none',
          color: 'inherit',
          cursor: 'pointer',
          transition: 'transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease',
        }
      : {}),
  };

  const content = (
    <>
      <div>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: '#0f172a' }}>{title}</h3>
        <p style={{ margin: '6px 0 0', fontSize: 12, color: '#64748b' }}>{subtitle}</p>
      </div>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflow: allowOverflow ? 'visible' : 'hidden',
          ...(fillContent ? { display: 'flex', flexDirection: 'column' as const } : {}),
        }}
      >
        {children}
      </div>
    </>
  );

  if (href) {
    return (
      <a
        href={href}
        aria-label={`${title} - open in Market Insights`}
        style={cardStyle}
        onMouseEnter={(event) => {
          event.currentTarget.style.transform = 'translateY(-1px)';
          event.currentTarget.style.boxShadow = '0 14px 28px rgba(15, 23, 42, 0.08)';
          event.currentTarget.style.borderColor = '#bfdbfe';
        }}
        onMouseLeave={(event) => {
          event.currentTarget.style.transform = 'translateY(0)';
          event.currentTarget.style.boxShadow = '0 8px 20px rgba(15, 23, 42, 0.04)';
          event.currentTarget.style.borderColor = '#e2e8f0';
        }}
      >
        {content}
      </a>
    );
  }

  return <section style={cardStyle}>{content}</section>;
};

export default InsightCard;
