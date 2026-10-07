import { ZodError } from 'zod'
import { ApiError } from './api/client'
import { UploadError } from './api/upload'

const dateFmt = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
const dateTimeFmt = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

/** Format an ISO calendar date ("2025-03-01") without shifting it across time zones. */
export function formatDate(iso: string): string {
  return dateFmt.format(new Date(`${iso}T00:00:00`))
}

export function formatDateTime(iso: string): string {
  return dateTimeFmt.format(new Date(iso))
}

/** A message that is safe and useful to show for any error a query or mutation can throw. */
export function errorText(error: unknown): string {
  if (error instanceof ApiError || error instanceof UploadError) return error.message
  if (error instanceof ZodError) return 'The server sent an unexpected response. Please try again later.'
  return 'Something went wrong. Check your connection and try again.'
}

const ISSUE_TEXT: Record<string, string> = {
  unrecognised_marker: 'Test not recognised',
  unit_mismatch: 'Unit not valid for this test',
  implausible_value: 'Value outside the possible range (often a misread decimal point)',
  duplicate_marker: 'Same test appears twice',
}

export function issueText(issue: string): string {
  return ISSUE_TEXT[issue] ?? issue
}

const MAX_DECIMALS = 2

/** Up to two decimals, without trailing zeros after the point ("12.50" → "12.5", "20" stays "20"). */
export function formatValue(value: number): string {
  const fixed = Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(MAX_DECIMALS)
  return fixed.includes('.') ? fixed.replace(/0+$/, '').replace(/\.$/, '') : fixed
}
