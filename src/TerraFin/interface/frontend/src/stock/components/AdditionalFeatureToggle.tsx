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
  background: '#ffffff',
  borderRadius: 14,
  border: '1px solid #e2e8f0',
  boxShadow: '0 8px 20px rgba(15, 23, 42, 0.04)',
  overflow: 'hidden',
};

const buttonStyle: React.CSSProperties = {
  width: '100%',
  border: 'none',
  background: 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)',
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
  fontSize: 11,
  fontWeight: 700,
  color: '#64748b',
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
  fontSize: 15,
  fontWeight: 700,
  color: '#0f172a',
};

const stateBadgeStyle = (open: boolean): React.CSSProperties => ({
  borderRadius: 999,
  padding: '5px 9px',
  background: open ? '#dcfce7' : '#f1f5f9',
  color: open ? '#166534' : '#475569',
  fontSize: 11,
  fontWeight: 700,
});

const subtitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 12,
  color: '#64748b',
  lineHeight: 1.5,
};

const chipStyle = (open: boolean): React.CSSProperties => ({
  flexShrink: 0,
  minWidth: 72,
  height: 36,
  borderRadius: 999,
  border: `1px solid ${open ? '#86efac' : '#cbd5e1'}`,
  background: open ? '#ecfdf5' : '#ffffff',
  color: open ? '#166534' : '#334155',
  fontSize: 12,
  fontWeight: 800,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
});

export default AdditionalFeatureToggle;
