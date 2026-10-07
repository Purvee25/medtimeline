import { api } from './client'
import { Report, UploadTicket } from './schemas'

export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
const PDF_MAGIC = '%PDF-'

export class UploadError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'UploadError'
  }
}

/** Client-side checks so obvious mistakes fail before any network call. The server re-checks. */
export async function checkFile(file: File): Promise<void> {
  if (!file.name.toLowerCase().endsWith('.pdf')) throw new UploadError('Only PDF reports are accepted.')
  if (file.size === 0) throw new UploadError('The file is empty.')
  if (file.size > MAX_UPLOAD_BYTES) throw new UploadError('The file is larger than 10 MB.')
  const head = new TextDecoder().decode(await file.slice(0, PDF_MAGIC.length).arrayBuffer())
  if (head !== PDF_MAGIC) throw new UploadError('This file is not a valid PDF.')
}

/**
 * Upload a report in three steps: register it, POST the file straight to S3 with the
 * pre-signed form, then ask the API to verify it (which also queues extraction).
 */
export async function uploadReport(file: File, patient?: string): Promise<Report> {
  await checkFile(file)
  const ticket = await api('/api/reports/', UploadTicket, {
    method: 'POST',
    body: { original_filename: file.name, size_bytes: file.size, ...(patient ? { patient } : {}) },
  })

  const form = new FormData()
  for (const [key, value] of Object.entries(ticket.upload.fields)) form.append(key, value)
  form.append('file', file) // S3 requires the file to be the last field.
  const stored = await fetch(ticket.upload.url, { method: 'POST', body: form })
  if (!stored.ok) throw new UploadError(`Storage rejected the upload (${stored.status}).`)

  return api(`/api/reports/${ticket.report.id}/complete/`, Report, { method: 'POST' })
}
