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

export function analyzeStl(file) {
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
