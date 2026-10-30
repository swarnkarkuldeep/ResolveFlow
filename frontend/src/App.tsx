import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { StatusPage } from './pages/StatusPage'

const queryClient = new QueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <StatusPage />
    </QueryClientProvider>
  )
}
