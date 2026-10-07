import type { ReportStatus } from '../api/schemas'

type Tone = 'good' | 'warning' | 'critical' | 'neutral'

const STATUS: Record<ReportStatus, { label: string; tone: Tone }> = {
  awaiting_upload: { label: 'Awaiting upload', tone: 'neutral' },
  uploaded: { label: 'Queued', tone: 'neutral' },
  processing: { label: 'Processing', tone: 'neutral' },
  extracted: { label: 'Extracted', tone: 'good' },
  needs_review: { label: 'Needs review', tone: 'warning' },
  failed: { label: 'Failed', tone: 'critical' },
  rejected: { label: 'Rejected', tone: 'critical' },
}

// Status is never colour alone: each tone carries its own icon and a text label.
const ICON: Record<Tone, string> = {
  good: 'M3 8.5l3 3 7-7',
  warning: 'M8 3v6M8 12.5v.5',
  critical: 'M4 4l8 8M12 4l-8 8',
  neutral: 'M8 4v4l3 2',
}

export function StatusBadge({ status }: { status: ReportStatus }) {
  const { label, tone } = STATUS[status]
  return (
    <span className={`badge ${tone}`}>
      <svg viewBox="0 0 16 16" aria-hidden="true">
        {tone === 'neutral' && <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.5" />}
        <path d={ICON[tone]} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
      {label}
    </span>
  )
}

