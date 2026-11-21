import { QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router'
import { AppShell } from './app/AppShell'
import { NAV } from './app/nav'
import { makeQueryClient } from './lib/queryClient'
import { Dashboard } from './pages/Dashboard'
import { Placeholder } from './pages/Placeholder'
import { SourceDetail } from './pages/SourceDetail'
import { Sources } from './pages/Sources'

const queryClient = makeQueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Dashboard />} />
            <Route path="sources" element={<Sources />} />
            <Route path="sources/:id" element={<SourceDetail />} />
            {NAV.filter((n) => n.phase).map((n) => (
              <Route
                key={n.to}
                path={n.to.slice(1)}
                element={<Placeholder navKey={n.key} phase={n.phase!} />}
              />
            ))}
            <Route path="*" element={<Dashboard />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
