export const DEFAULT_API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1'

function normalizeBaseUrl(baseUrl = DEFAULT_API_BASE_URL) {
  const value = String(baseUrl ?? DEFAULT_API_BASE_URL).trim()
  return value.replace(/\/+$/, '') || DEFAULT_API_BASE_URL
}

function buildUrl(baseUrl, path) {
  return `${normalizeBaseUrl(baseUrl)}${path}`
}

async function parseResponseBody(response) {
  const contentType = response.headers.get('content-type') || ''

  if (contentType.includes('application/json')) {
    try {
      return await response.json()
    } catch {
      return null
    }
  }

  try {
    return await response.text()
  } catch {
    return null
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      Accept: 'application/json',
      ...options.headers,
    },
    ...options,
  })

  const body = await parseResponseBody(response)
  if (!response.ok) {
    const detail =
      typeof body === 'string'
        ? body
        : body?.detail || body?.message || body?.error || response.statusText || '请求失败'
    const error = new Error(detail)
    error.status = response.status
    error.payload = body
    throw error
  }

  return body
}

export async function loginUser(baseUrl, email, password) {
  const form = new URLSearchParams()
  form.set('username', email)
  form.set('password', password)
  form.set('grant_type', 'password')

  return requestJson(buildUrl(baseUrl, '/auth/login'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: form,
  })
}

export async function createSession(baseUrl, userToken) {
  return requestJson(buildUrl(baseUrl, '/auth/session'), {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${userToken}`,
    },
  })
}

export async function clearChatHistory(baseUrl, sessionToken) {
  return requestJson(buildUrl(baseUrl, '/chatbot/messages'), {
    method: 'DELETE',
    headers: {
      Authorization: `Bearer ${sessionToken}`,
    },
  })
}

export async function listDocuments(baseUrl, { skip = 0, limit = 100, status = null } = {}) {
  const params = new URLSearchParams({
    skip: String(skip),
    limit: String(limit),
  })

  if (status) {
    params.set('status', status)
  }

  return requestJson(buildUrl(baseUrl, `/documents/documents?${params.toString()}`), {
    method: 'GET',
  })
}

export async function retrieveDocuments(baseUrl, { query, topK = 5, documentIds = [] }) {
  const payload = {
    query,
    top_k: topK,
  }

  if (Array.isArray(documentIds) && documentIds.length > 0) {
    payload.document_ids = documentIds
  }

  return requestJson(buildUrl(baseUrl, '/documents/retrieve'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

export async function chatWithSession(baseUrl, sessionToken, messages) {
  return requestJson(buildUrl(baseUrl, '/chatbot/chat'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${sessionToken}`,
    },
    body: JSON.stringify({ messages }),
  })
}


