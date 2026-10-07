import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api, apiRaw } from './client'
import {
  Consent,
  type ConsentPurpose,
  DownloadLink,
  Marker,
  Observation,
  type ReportStatus,
  ReportObservations,
  ReportPage,
  Trend,
} from './schemas'
import { uploadReport } from './upload'

/**
 * Statuses the worker hasn't finished with; their views poll until they settle. `awaiting_upload`
 * is excluded: if the browser never finished the S3 upload, nothing will ever move it on.
 */
const IN_FLIGHT: ReadonlySet<ReportStatus> = new Set(['uploaded', 'processing'])
const POLL_MS = 3000
// Some browsers start a download asynchronously; revoking the blob URL immediately can cancel it.
const BLOB_URL_LIFETIME_MS = 60_000

export const keys = {
  reports: ['reports'] as const,
  report: (id: string) => ['reports', id] as const,
  markers: ['markers'] as const,
  trend: (marker: string, patient: string, verifiedOnly: boolean) =>
    ['trend', marker, patient, verifiedOnly] as const,
  consents: ['consents'] as const,
}

export function useReports() {
  return useQuery({
    queryKey: keys.reports,
    queryFn: () => api('/api/reports/', ReportPage),
    refetchInterval: (query) =>
      query.state.data?.results.some((r) => IN_FLIGHT.has(r.status)) ? POLL_MS : false,
  })
}

export function useReport(id: string) {
  return useQuery({
    queryKey: keys.report(id),
    queryFn: () => api(`/api/reports/${id}/observations/`, ReportObservations),
    refetchInterval: (query) => (query.state.data && IN_FLIGHT.has(query.state.data.report.status) ? POLL_MS : false),
  })
}

export function useUpload() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ file, patient }: { file: File; patient?: string }) => uploadReport(file, patient),
    onSettled: () => client.invalidateQueries({ queryKey: keys.reports }),
  })
}

export type ReviewedValue = { marker_code: string; value: number; unit: string }

export function useReview(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { collected_on: string; observations: ReviewedValue[] }) =>
      api(`/api/reports/${id}/review/`, z.array(Observation), { method: 'POST', body }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.reports })
      void client.invalidateQueries({ queryKey: ['trend'] })
    },
  })
}

export async function openReportFile(id: string): Promise<void> {
  const { url } = await api(`/api/reports/${id}/download/`, DownloadLink)
  window.open(url, '_blank', 'noopener,noreferrer')
}

export function useMarkers() {
  return useQuery({
    queryKey: keys.markers,
    queryFn: () => api('/api/markers/', z.array(Marker)),
    staleTime: Infinity,
  })
}

export function useTrend(marker: string, patient: string, verifiedOnly: boolean, enabled: boolean) {
  const params = new URLSearchParams({ marker })
  if (patient) params.set('patient', patient)
  if (verifiedOnly) params.set('verified_only', 'true')
  return useQuery({
    queryKey: keys.trend(marker, patient, verifiedOnly),
    queryFn: () => api(`/api/trends/?${params.toString()}`, Trend),
    enabled,
  })
}

export function useConsents() {
  return useQuery({ queryKey: keys.consents, queryFn: () => api('/api/auth/consents/', z.array(Consent)) })
}

export function useSetConsent() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { purpose: ConsentPurpose; granted: boolean }) =>
      api('/api/auth/consents/', z.array(Consent), { method: 'POST', body }),
    onSuccess: (consents) => client.setQueryData(keys.consents, consents),
  })
}

/** Download the caller's FHIR bundle as a file. */
export async function downloadFhirBundle(): Promise<void> {
  const response = await apiRaw('/api/fhir/Patient/$everything')
  const blob = new Blob([await response.text()], { type: 'application/fhir+json' })
  const url = URL.createObjectURL(blob)
  const link = Object.assign(document.createElement('a'), { href: url, download: 'medtimeline-fhir.json' })
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), BLOB_URL_LIFETIME_MS)
}

export async function eraseAccount(): Promise<void> {
  await apiRaw('/api/auth/me/', { method: 'DELETE' })
}
