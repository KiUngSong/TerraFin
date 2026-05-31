import React from 'react';

interface Props {
  title: string;
  subtitle: React.ReactNode;
  open: boolean;
  onToggle: () => void;
}

const AdditionalFeatureToggle: React.FC<Props> = ({ title, subtitle, open, onToggle }) => (
  <section style={cardStyle}>
    <button
      type="button"
      aria-expanded={open}
      onClick={onToggle}
      style={buttonStyle}
    >
      <div style={textBlockStyle}>
        <div style={eyebrowStyle}>Additional Feature</div>
        <div style={titleRowStyle}>
          <h3 style={titleStyle}>{title}</h3>
          <span style={stateBadgeStyle(open)}>{open ? 'Expanded' : 'Collapsed'}</span>
        </div>
        <p style={subtitleStyle}>{subtitle}</p>
      </div>
      <span style={chipStyle(open)}>{open ? 'Hide' : 'Show'}</span>
    </button>
  </section>
);

const cardStyle: React.CSSProperties = {
  background: 'var(--tf-bg-pane)',
  borderRadius: 'var(--tf-radius)',
  border: '1px solid var(--tf-border)',
  overflow: 'hidden',
};

const buttonStyle: React.CSSProperties = {
  width: '100%',
  border: 'none',
  background: 'var(--tf-bg-elevated)',
  padding: 16,
  display: 'flex',
  alignItems: 'flex-start',
  justifyContent: 'space-between',
  gap: 16,
  flexWrap: 'wrap',
  textAlign: 'left',
  cursor: 'pointer',
};

const textBlockStyle: React.CSSProperties = {
  display: 'grid',
  gap: 6,
  minWidth: 0,
};

const eyebrowStyle: React.CSSProperties = {
  fontSize: "var(--tf-fs-xs)",
  fontWeight: 700,
  color: 'var(--tf-muted)',
  letterSpacing: '0.06em',
  textTransform: 'uppercase',
};

const titleRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  flexWrap: 'wrap',
};

const titleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: "var(--tf-fs-md)",
  fontWeight: 700,
  color: 'var(--tf-text-strong)',
};

const stateBadgeStyle = (open: boolean): React.CSSProperties => ({
  borderRadius: 999,
  padding: '5px 9px',
  background: 'var(--tf-bg-pane)',
  color: open ? 'var(--tf-up)' : 'var(--tf-muted)',
  fontSize: "var(--tf-fs-xs)",
  fontWeight: 700,
});

const subtitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: "var(--tf-fs-xs)",
  color: 'var(--tf-muted)',
  lineHeight: 1.5,
};

const chipStyle = (open: boolean): React.CSSProperties => ({
  flexShrink: 0,
  minWidth: 72,
  height: 36,
  borderRadius: 999,
  border: `1px solid ${open ? 'var(--tf-up)' : 'var(--tf-border)'}`,
  background: open ? 'var(--tf-bg-pane)' : 'var(--tf-bg-elevated)',
  color: open ? 'var(--tf-up)' : 'var(--tf-text)',
  fontSize: "var(--tf-fs-xs)",
  fontWeight: 700,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
});

export default AdditionalFeatureToggle;
