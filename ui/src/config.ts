// Build-time mode switch. `VITE_STATIC_DEMO=1 npm run build` produces the
// GitHub Pages build: no API, no WebSocket -- incidents, KPIs and camera
// recordings all come from the files under public/showcase/.
export const STATIC_DEMO = import.meta.env.VITE_STATIC_DEMO === '1'

export const REPO_URL = 'https://github.com/PCSchmidt/sitework-ai'

/** URL for a file under public/, respecting Vite's base path (e.g. /sitework-ai/ on Pages). */
export function assetUrl(path: string): string {
  return `${import.meta.env.BASE_URL}${path.replace(/^\//, '')}`
}
