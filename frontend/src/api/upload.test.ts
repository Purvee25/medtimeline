import { describe, expect, it, vi } from 'vitest'
import { checkFile, MAX_UPLOAD_BYTES, uploadReport } from './upload'

const pdf = (bytes = '%PDF-1.7 body', name = 'cbc.pdf') => new File([bytes], name, { type: 'application/pdf' })

const report = {
  id: 'r1',
  patient: 'alice',
  center: null,
  original_filename: 'cbc.pdf',
  size_bytes: 13,
  status: 'uploaded',
  collected_on: null,
  error: '',
  created_at: '2026-10-07T10:00:00Z',
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('checkFile', () => {
  it('accepts a real PDF', async () => {
    await expect(checkFile(pdf())).resolves.toBeUndefined()
  })

  it.each([
    ['wrong extension', pdf('%PDF-1.7', 'report.exe'), 'Only PDF'],
    ['empty file', pdf(''), 'empty'],
    ['renamed non-PDF', pdf('MZ\x90 not a pdf'), 'not a valid PDF'],
  ])('rejects %s', async (_case, file, message) => {
    await expect(checkFile(file)).rejects.toThrow(message)
  })

  it('rejects files over the size cap', async () => {
    const big = pdf('%PDF-'.padEnd(MAX_UPLOAD_BYTES + 1, ' '))
    await expect(checkFile(big)).rejects.toThrow('larger than 10 MB')
  })
})

describe('uploadReport', () => {
  it('registers, posts to storage with fields before the file, then completes', async () => {
    const calls: { url: string; init?: RequestInit }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, init })
        if (url === '/api/auth/token/refresh/') return json({}, 401)
        if (url === '/api/reports/') {
          return json({ report, upload: { url: 'https://s3.test/bucket', fields: { key: 'reports/1/a.pdf', policy: 'p' } } }, 201)
        }
        if (url === 'https://s3.test/bucket') return new Response(null, { status: 204 })
        if (url === '/api/reports/r1/complete/') return json(report)
        throw new Error(`unexpected ${url}`)
      }),
    )

    const result = await uploadReport(pdf())

    expect(result.status).toBe('uploaded')
    expect(calls.map((c) => c.url)).toEqual(['/api/reports/', 'https://s3.test/bucket', '/api/reports/r1/complete/'])
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ original_filename: 'cbc.pdf', size_bytes: 13 })
    const form = calls[1]?.init?.body as FormData
    expect([...form.keys()]).toEqual(['key', 'policy', 'file'])
  })

  it('stops if storage rejects the file', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        url === '/api/reports/'
          ? json({ report, upload: { url: 'https://s3.test/bucket', fields: {} } }, 201)
          : new Response('denied', { status: 403 }),
      ),
    )
    await expect(uploadReport(pdf())).rejects.toThrow('Storage rejected the upload (403)')
  })
})
