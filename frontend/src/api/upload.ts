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
 * Upload a report in three steps: register it, PUT the file straight to storage with the
 * pre-signed URL, then ask the API to verify it (which also queues extraction).
 */
export async function uploadReport(file: File, patient?: string): Promise<Report> {
  await checkFile(file)
  const ticket = await api('/api/reports/', UploadTicket, {
    method: 'POST',
    body: { original_filename: file.name, size_bytes: file.size, ...(patient ? { patient } : {}) },
  })

  // The URL is signed over Content-Type and Content-Length, so the body must be the exact file registered.
  const stored = await fetch(ticket.upload.url, { method: 'PUT', headers: ticket.upload.headers, body: file })
  if (!stored.ok) throw new UploadError(`Storage rejected the upload (${stored.status}).`)

  return api(`/api/reports/${ticket.report.id}/complete/`, Report, { method: 'POST' })
}
