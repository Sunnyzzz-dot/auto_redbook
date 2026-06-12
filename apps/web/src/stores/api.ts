import { reactive } from 'vue'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''
export const WS_BASE = API_BASE
  ? API_BASE.replace(/^http/, 'ws')
  : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

export type ApiState = {
  token: string
}

export const state = reactive<ApiState>({
  token: localStorage.getItem('redbook_token') || ''
})

export function setToken(token: string) {
  state.token = token
  localStorage.setItem('redbook_token', token)
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Content-Type', 'application/json')
  if (state.token) headers.set('Authorization', `Bearer ${state.token}`)
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || response.statusText)
  }
  return response.json() as Promise<T>
}

export type DraftImage = {
  id: string
  image_url: string
  prompt: string
  sort_order: number
  is_selected: boolean
}

export type Draft = {
  id: string
  title_candidates: string[]
  selected_title: string
  body: string
  hashtags: string[]
  style: string
  target_audience: string
  safety_report: Record<string, unknown>
  images: DraftImage[]
}

export type AgentRun = {
  id: string
  instruction: string
  status: string
  config: Record<string, unknown>
  failure_reason: string | null
  steps: Array<{
    id: string
    step: string
    thought_summary: string
    action: string
    status: string
    error: string | null
  }>
  draft: Draft | null
}
