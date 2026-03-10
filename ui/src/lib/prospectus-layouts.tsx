/**
 * Reusable layout primitives for the prospectus PDF.
 *
 * Built on @react-pdf/renderer's flexbox layout engine.
 * These components provide magazine-style layouts with text flowing
 * alongside charts, metrics, and data tables.
 */
import { View, Text, StyleSheet } from '@react-pdf/renderer';
import type { ReactNode } from 'react';

// ---------------------------------------------------------------------------
// Colors (shared with prospectus-pdf.tsx)
// ---------------------------------------------------------------------------

export const C = {
  amber: '#D97706',
  amberLight: '#FEF3C7',
  amberBg: '#FFFBEB',
  green: '#059669',
  greenBg: '#ECFDF5',
  red: '#DC2626',
  gray900: '#111827',
  gray700: '#374151',
  gray600: '#4B5563',
  gray500: '#6B7280',
  gray400: '#9CA3AF',
  gray200: '#E5E7EB',
  gray100: '#F3F4F6',
  gray50: '#F9FAFB',
  white: '#FFFFFF',
};

// ---------------------------------------------------------------------------
// Shared PDF styles
// ---------------------------------------------------------------------------

export const s = StyleSheet.create({
  page: {
    fontFamily: 'Helvetica',
    fontSize: 9,
    color: C.gray700,
    paddingTop: 54,
    paddingBottom: 54,
    paddingHorizontal: 54,
  },
  sectionHeader: {
    fontSize: 11,
    fontFamily: 'Helvetica-Bold',
    color: C.amber,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginTop: 18,
    marginBottom: 4,
    paddingBottom: 4,
    borderBottomWidth: 1,
    borderBottomColor: C.amber,
  },
  kvRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 2,
  },
  kvLabel: { color: C.gray500, fontSize: 9 },
  kvValue: { fontFamily: 'Helvetica-Bold', fontSize: 9, color: C.gray900 },
  tableHeader: {
    flexDirection: 'row',
    borderBottomWidth: 1,
    borderBottomColor: C.gray200,
    paddingBottom: 3,
    marginBottom: 3,
  },
  tableHeaderText: {
    fontFamily: 'Helvetica-Bold',
    fontSize: 8,
    color: C.gray500,
    textTransform: 'uppercase',
  },
  tableRow: {
    flexDirection: 'row',
    paddingVertical: 2,
    borderBottomWidth: 0.5,
    borderBottomColor: C.gray100,
  },
  tableRowHighlight: {
    backgroundColor: '#ECFDF5',
  },
  tableCell: { fontSize: 8.5, color: C.gray700 },
  footer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    borderTopWidth: 0.5,
    borderTopColor: C.gray200,
    paddingTop: 4,
    marginTop: 'auto',
  },
  footerText: { fontSize: 7, color: C.gray400 },
  metricsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginTop: 6,
    gap: 0,
  },
  metricCell: {
    width: '25%',
    paddingVertical: 6,
    alignItems: 'center',
  },
  metricLabel: {
    fontSize: 7.5,
    color: C.gray500,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  metricValue: {
    fontSize: 13,
    fontFamily: 'Helvetica-Bold',
    color: C.gray900,
    marginTop: 2,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 10,
    marginRight: 6,
    marginBottom: 4,
  },
  badgeEligible: { backgroundColor: '#ECFDF5', borderWidth: 0.5, borderColor: '#A7F3D0' },
  badgeIneligible: { backgroundColor: C.gray50, borderWidth: 0.5, borderColor: C.gray200 },
  badgeText: { fontSize: 8 },
});

// ---------------------------------------------------------------------------
// Format helpers
// ---------------------------------------------------------------------------

export function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return '\u2014';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(n);
}

export function fmtPct(pct: number | null | undefined, showSign = false): string {
  if (pct == null) return '\u2014';
  const prefix = showSign && pct > 0 ? '+' : '';
  return `${prefix}${pct.toFixed(1)}%`;
}

export function fmtDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '\u2014';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

export function fmtNumber(n: number | null | undefined): string {
  if (n == null) return '\u2014';
  return new Intl.NumberFormat('en-US').format(n);
}

// ---------------------------------------------------------------------------
// TwoColumn
// ---------------------------------------------------------------------------

interface TwoColumnProps {
  left: ReactNode;
  right: ReactNode;
  /** Width ratio for left column, e.g. 0.4 means 40% left, 60% right */
  ratio?: number;
  /** Gap between columns in pt */
  gap?: number;
  /** Vertical alignment */
  align?: 'flex-start' | 'center' | 'flex-end';
  /** Top margin */
  marginTop?: number;
}

export function TwoColumn({
  left,
  right,
  ratio = 0.5,
  gap = 16,
  align = 'flex-start',
  marginTop = 0,
}: TwoColumnProps) {
  const leftPct = `${(ratio * 100).toFixed(0)}%`;
  const rightPct = `${((1 - ratio) * 100).toFixed(0)}%`;

  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: align,
        marginTop,
      }}
    >
      <View style={{ width: leftPct as any, paddingRight: gap / 2 }}>{left}</View>
      <View style={{ width: rightPct as any, paddingLeft: gap / 2 }}>{right}</View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// NarrativeBlock — styled text block with optional accent bar
// ---------------------------------------------------------------------------

interface NarrativeBlockProps {
  /** Optional small title above the narrative */
  title?: string;
  /** The narrative text content */
  content: string | null | undefined;
  /** Accent color for the left bar (defaults to amber) */
  accentColor?: string;
  /** Background color */
  bgColor?: string;
  /** Font size for content */
  fontSize?: number;
  /** Top margin */
  marginTop?: number;
}

export function NarrativeBlock({
  title,
  content,
  accentColor = C.amber,
  bgColor,
  fontSize = 8.5,
  marginTop = 6,
}: NarrativeBlockProps) {
  if (!content) return null;

  return (
    <View
      style={{
        flexDirection: 'row',
        marginTop,
        backgroundColor: bgColor,
        borderRadius: bgColor ? 3 : 0,
        padding: bgColor ? 8 : 0,
      }}
    >
      {/* Accent bar */}
      <View
        style={{
          width: 2.5,
          backgroundColor: accentColor,
          borderRadius: 1,
          marginRight: 8,
        }}
      />
      <View style={{ flex: 1 }}>
        {title && (
          <Text
            style={{
              fontSize: 8,
              fontFamily: 'Helvetica-Bold',
              color: C.gray700,
              marginBottom: 3,
              textTransform: 'uppercase',
              letterSpacing: 0.5,
            }}
          >
            {title}
          </Text>
        )}
        <Text style={{ fontSize, color: C.gray600, lineHeight: 1.5 }}>{content}</Text>
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// MetricCard — compact metric display with optional color + sublabel
// ---------------------------------------------------------------------------

interface MetricCardProps {
  label: string;
  value: string;
  sublabel?: string;
  color?: string;
  /** Width as CSS string, e.g. '25%' or '33%' */
  width?: string;
}

export function MetricCard({
  label,
  value,
  sublabel,
  color,
  width = '25%',
}: MetricCardProps) {
  return (
    <View
      style={{
        width: width as any,
        paddingVertical: 6,
        paddingHorizontal: 4,
        alignItems: 'center',
      }}
    >
      <Text
        style={{
          fontSize: 7,
          color: C.gray500,
          textTransform: 'uppercase',
          letterSpacing: 0.5,
          textAlign: 'center',
        }}
      >
        {label}
      </Text>
      <Text
        style={{
          fontSize: 14,
          fontFamily: 'Helvetica-Bold',
          color: color || C.gray900,
          marginTop: 2,
        }}
      >
        {value}
      </Text>
      {sublabel && (
        <Text style={{ fontSize: 6.5, color: C.gray400, marginTop: 1 }}>{sublabel}</Text>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// CalloutBox — highlighted info box
// ---------------------------------------------------------------------------

interface CalloutBoxProps {
  children: ReactNode;
  bgColor?: string;
  borderColor?: string;
}

export function CalloutBox({
  children,
  bgColor = C.greenBg,
  borderColor = '#A7F3D0',
}: CalloutBoxProps) {
  return (
    <View
      style={{
        backgroundColor: bgColor,
        borderRadius: 4,
        borderWidth: 0.5,
        borderColor,
        padding: 10,
        marginTop: 4,
        marginBottom: 4,
      }}
    >
      {children}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

export function PageFooter({ disclaimer }: { disclaimer?: string }) {
  return (
    <View style={s.footer}>
      <Text style={s.footerText}>{disclaimer || 'For informational purposes only.'}</Text>
      <Text style={s.footerText}>HomeBuyer AI</Text>
    </View>
  );
}

export function KVRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={s.kvRow}>
      <Text style={s.kvLabel}>{label}</Text>
      <Text style={s.kvValue}>{value}</Text>
    </View>
  );
}

export function SectionHeader({ children }: { children: string }) {
  return <Text style={s.sectionHeader}>{children}</Text>;
}

export function MetricBox({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <View style={s.metricCell}>
      <Text style={s.metricLabel}>{label}</Text>
      <Text style={[s.metricValue, color ? { color } : {}]}>{value}</Text>
    </View>
  );
}

export function DevBadge({
  label,
  eligible,
  detail,
}: {
  label: string;
  eligible: boolean;
  detail?: string;
}) {
  return (
    <View style={[s.badge, eligible ? s.badgeEligible : s.badgeIneligible]}>
      <Text style={[s.badgeText, { color: eligible ? C.green : C.gray400 }]}>
        {eligible ? '\u2713' : '\u2014'} {label}
        {eligible && detail ? ` (${detail})` : ''}
      </Text>
    </View>
  );
}
