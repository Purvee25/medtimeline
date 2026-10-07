import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { ApiError } from './api/client'
import { App } from './App'
import { AuthProvider } from './auth'
import './index.css'

const MAX_QUERY_RETRIES = 2

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Client errors (403/404/400) won't fix themselves; only retry network and 5xx failures.
      retry: (failures, error) =>
        failures < MAX_QUERY_RETRIES && !(error instanceof ApiError && error.status < 500),
      refetchOnWindowFocus: false,
    },
  },
})

const root = document.getElementById('root')
if (!root) throw new Error('Missing #root element')

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
