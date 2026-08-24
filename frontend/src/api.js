const API = '/api'

async function request(path, options = {}) {
  const res = await fetch(`${API}${path}`, options)
  if (res.status === 204) return null
  const text = await res.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { detail: text }
  }
  if (!res.ok) {
    const detail = data?.detail
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail || data)
    throw new Error(message || `HTTP ${res.status}`)
  }
  return data
}

export function analyzeMesh(file) {
  const body = new FormData()
  body.append('file', file)
  return request('/analyze', { method: 'POST', body })
}

export function recommend(payload) {
  return request('/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function exportProfile(payload) {
  return request('/recommend/export-profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function export3mf(payload) {
  const res = await fetch(`${API}/recommend/export-3mf`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const data = await res.json()
      message = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data)
    } catch {
      /* ignore */
    }
    throw new Error(message)
  }
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') || ''
  const match = cd.match(/filename="([^"]+)"/)
  return { blob, filename: match?.[1] || 'p2s_project.3mf' }
}

export function filamentOptionLabel(f) {
  const slot = (f.slot || '').trim() || 'Envanter'
  const brand = (f.brand || '').trim()
  const core = [slot, brand, f.material].filter(Boolean).join(' ')
  return f.color ? `${core} — ${f.color}` : core
}

export function validateFilamentMap(payload) {
  return request('/filament-map/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function listFilaments() {
  return request('/filaments')
}

export function createFilament(payload) {
  return request('/filaments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteFilament(id) {
  return request(`/filaments/${id}`, { method: 'DELETE' })
}
