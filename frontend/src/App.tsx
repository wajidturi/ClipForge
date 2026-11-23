import { QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router'
import { AppShell } from './app/AppShell'
import { NAV } from './app/nav'
import { makeQueryClient } from './lib/queryClient'
import { Create } from './pages/Create'
import { Dashboard } from './pages/Dashboard'
import { Library } from './pages/Library'
import { Review } from './pages/Review'
import { RunDetail } from './pages/RunDetail'
import { Settings } from './pages/Settings'
import { Studio } from './pages/Studio'
import { Welcome } from './pages/Welcome'
import { Placeholder } from './pages/Placeholder'
import { SourceDetail } from './pages/SourceDetail'
import { Sources } from './pages/Sources'

const queryClient = makeQueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="welcome" element={<Welcome />} />
          <Route element={<AppShell />}>
            <Route index element={<Dashboard />} />
            <Route path="sources" element={<Sources />} />
            <Route path="sources/:id" element={<SourceDetail />} />
            <Route path="create" element={<Create />} />
            <Route path="runs/:id" element={<RunDetail />} />
            <Route path="shorts" element={<Library />} />
            <Route path="shorts/:id" element={<Studio />} />
            <Route path="review" element={<Review />} />
            <Route path="settings" element={<Settings />} />
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
