import { z } from 'zod'

// Every API response is parsed with these schemas: the server is external input, and a shape
// change should fail loudly here rather than as `undefined` deep inside a component.

// DRF serialises DecimalField as a string.
const decimal = z.union([z.number(), z.string()]).transform(Number).pipe(z.number().finite())

export const Tokens = z.object({ access: z.string(), refresh: z.string() })
export const RefreshedTokens = z.object({ access: z.string(), refresh: z.string() })

export const Role = z.enum(['patient', 'center_staff'])
export const Me = z.object({
  id: z.number(),
  username: z.string(),
  email: z.string(),
  role: Role,
  center: z.number().nullable(),
  email_verified: z.boolean().default(false),
})
export type Me = z.infer<typeof Me>

export const Registration = z.object({
  username: z.string(),
  email: z.string().email(),
  password: z.string(),
  consent_store_reports: z.boolean(),
  consent_llm_extraction: z.boolean(),
})
export type Registration = z.infer<typeof Registration>

export const ReportStatus = z.enum([
  'awaiting_upload',
  'uploaded',
  'processing',
  'extracted',
  'needs_review',
  'failed',
  'rejected',
])
export type ReportStatus = z.infer<typeof ReportStatus>

export const Report = z.object({
  id: z.string(),
  patient: z.string(),
  center: z.string().nullable(),
  original_filename: z.string(),
  size_bytes: z.number(),
  status: ReportStatus,
  collected_on: z.string().nullable(),
  error: z.string(),
  created_at: z.string(),
})
export type Report = z.infer<typeof Report>

export const ReportPage = z.object({
  count: z.number(),
  next: z.string().nullable(),
  previous: z.string().nullable(),
  results: z.array(Report),
})

export const UploadTicket = z.object({
  report: Report,
  upload: z.object({ url: z.string(), fields: z.record(z.string(), z.string()) }),
})

export const Observation = z.object({
  id: z.number(),
  marker_code: z.string(),
  loinc: z.string(),
  value: decimal,
  unit: z.string(),
  canonical_value: decimal,
  canonical_unit: z.string(),
  effective_date: z.string(),
  verified: z.boolean(),
})
export type Observation = z.infer<typeof Observation>

export const ExtractedRow = z.object({
  marker: z.string(),
  printed_name: z.string(),
  value: z.number(),
  unit: z.string(),
  canonical_value: z.number().nullable(),
  issues: z.array(z.string()),
})
export type ExtractedRow = z.infer<typeof ExtractedRow>

export const Extraction = z.object({
  status: z.string(),
  collected_on: z.string().nullable().optional(),
  skipped: z.string().optional(),
  error: z.string().optional(),
  results: z.array(ExtractedRow),
})

export const ReportObservations = z.object({
  report: Report,
  extraction: Extraction.nullable(),
  observations: z.array(Observation),
})
export type ReportObservations = z.infer<typeof ReportObservations>

export const Marker = z.object({
  code: z.string(),
  name: z.string(),
  loinc: z.string(),
  unit: z.string(),
  units: z.array(z.string()),
})
export type Marker = z.infer<typeof Marker>

export const TrendPoint = z.object({
  date: z.string(),
  value: z.number(),
  verified: z.boolean(),
  report_id: z.string(),
  center: z.string().nullable(),
})
export type TrendPoint = z.infer<typeof TrendPoint>

export const Trend = z.object({
  marker: z.string(),
  name: z.string(),
  loinc: z.string(),
  unit: z.string(),
  reference_range: z.object({ low: z.number(), high: z.number(), approximate: z.boolean() }),
  points: z.array(TrendPoint),
})
export type Trend = z.infer<typeof Trend>

export const ConsentPurpose = z.enum(['store_reports', 'llm_extraction'])
export type ConsentPurpose = z.infer<typeof ConsentPurpose>
export const Consent = z.object({
  purpose: ConsentPurpose,
  policy_version: z.string(),
  granted_at: z.string(),
  withdrawn_at: z.string().nullable(),
})
export type Consent = z.infer<typeof Consent>

export const DownloadLink = z.object({ url: z.string() })
