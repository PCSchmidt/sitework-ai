import { useEffect, useState } from 'react'
import { assetUrl } from '../config'
import type { Showcase, ShowcaseIndexRow } from './model'

const cache = new Map<string, Promise<Showcase>>()
let indexPromise: Promise<ShowcaseIndexRow[]> | null = null

async function getJson<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`)
  return (await resp.json()) as T
}

export function loadShowcaseIndex(): Promise<ShowcaseIndexRow[]> {
  indexPromise ??= getJson<ShowcaseIndexRow[]>(assetUrl('showcase/index.json')).catch((e) => {
    indexPromise = null
    throw e
  })
  return indexPromise
}

export function loadShowcase(cameraId: string): Promise<Showcase> {
  let p = cache.get(cameraId)
  if (!p) {
    p = getJson<Showcase>(assetUrl(`showcase/${cameraId}/showcase.json`))
    p.catch(() => cache.delete(cameraId))
    cache.set(cameraId, p)
  }
  return p
}

export function showcaseVideoUrl(showcase: Showcase): string {
  return assetUrl(`showcase/${showcase.camera_id}/${showcase.video}`)
}

export function useShowcaseIndex() {
  const [rows, setRows] = useState<ShowcaseIndexRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    loadShowcaseIndex().then(setRows).catch((e) => setError(String(e)))
  }, [])
  return { rows, error }
}

export function useShowcase(cameraId: string | null) {
  const [showcase, setShowcase] = useState<Showcase | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setShowcase(null)
    setError(null)
    if (!cameraId) return
    let live = true
    loadShowcase(cameraId)
      .then((s) => live && setShowcase(s))
      .catch((e) => live && setError(String(e)))
    return () => {
      live = false
    }
  }, [cameraId])
  return { showcase, error }
}
