<script setup>
import { computed, onMounted, ref, watch } from 'vue'

import {
  DEFAULT_API_BASE_URL,
  chatWithSession,
  clearChatHistory,
  createSession,
  listDocuments,
  loginUser,
  retrieveDocuments,
} from './api.js'
import { buildRagPrompt, extractAssistantMessage } from './prompt.js'

const STORAGE_KEYS = {
  apiBaseUrl: 'company-agent.frontend.apiBaseUrl',
  loginEmail: 'company-agent.frontend.loginEmail',
  userToken: 'company-agent.frontend.userToken',
  userTokenExpiresAt: 'company-agent.frontend.userTokenExpiresAt',
  sessionToken: 'company-agent.frontend.sessionToken',
  sessionTokenExpiresAt: 'company-agent.frontend.sessionTokenExpiresAt',
  sessionId: 'company-agent.frontend.sessionId',
  selectedDocumentIds: 'company-agent.frontend.selectedDocumentIds',
  question: 'company-agent.frontend.question',
  topK: 'company-agent.frontend.topK',
}

function readStorage(key, fallback = '') {
  try {
    const value = window.localStorage.getItem(key)
    return value === null ? fallback : value
  } catch {
    return fallback
  }
}

function readJsonStorage(key, fallback = []) {
  try {
    const value = window.localStorage.getItem(key)
    if (!value) {
      return fallback
    }
    const parsed = JSON.parse(value)
    return Array.isArray(parsed) ? parsed : fallback
  } catch {
    return fallback
  }
}

function writeStorage(key, value) {
  try {
    window.localStorage.setItem(key, String(value ?? ''))
  } catch {
    // Ignore storage failures in private/incognito sessions.
  }
}

function writeJsonStorage(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Ignore storage failures in private/incognito sessions.
  }
}

function normalizeIdList(value) {
  if (!Array.isArray(value)) {
    return []
  }

  return [...new Set(value.map((item) => Number(item)).filter((item) => Number.isInteger(item) && item > 0))]
}

function formatDate(value) {
  if (!value) {
    return '—'
  }

  try {
    return new Intl.DateTimeFormat('zh-CN', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(value))
  } catch {
    return String(value)
  }
}

function truncateText(value, maxLength = 180) {
  const text = String(value ?? '').trim().replace(/\s+/g, ' ')
  if (text.length <= maxLength) {
    return text
  }
  return `${text.slice(0, maxLength)}…`
}

function shortToken(token) {
  const value = String(token ?? '')
  if (!value) {
    return '—'
  }

  if (value.length <= 28) {
    return value
  }

  return `${value.slice(0, 14)}…${value.slice(-12)}`
}

function normalizeTopK(value) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) {
    return 5
  }
  return Math.min(20, Math.max(1, Math.trunc(parsed)))
}

const apiBaseUrl = ref(readStorage(STORAGE_KEYS.apiBaseUrl, DEFAULT_API_BASE_URL))
const loginEmail = ref(readStorage(STORAGE_KEYS.loginEmail, ''))
const loginPassword = ref('')
const userToken = ref(readStorage(STORAGE_KEYS.userToken, ''))
const userTokenExpiresAt = ref(readStorage(STORAGE_KEYS.userTokenExpiresAt, ''))
const sessionToken = ref(readStorage(STORAGE_KEYS.sessionToken, ''))
const sessionTokenExpiresAt = ref(readStorage(STORAGE_KEYS.sessionTokenExpiresAt, ''))
const sessionId = ref(readStorage(STORAGE_KEYS.sessionId, ''))
const documents = ref([])
const selectedDocumentIds = ref(normalizeIdList(readJsonStorage(STORAGE_KEYS.selectedDocumentIds, [])))
const question = ref(readStorage(STORAGE_KEYS.question, '员工手册里报销审批流程是怎样的？'))
const topK = ref(normalizeTopK(readStorage(STORAGE_KEYS.topK, '5')))
const retrievalResults = ref([])
const answer = ref('')
const conversationHistory = ref([])
const statusMessage = ref('等待连接后端')
const errorMessage = ref('')
const loadingDocuments = ref(false)
const loadingAuth = ref(false)
const loadingAsk = ref(false)
const copiedMarker = ref('')

const readyDocuments = computed(() => documents.value.filter((doc) => doc?.status === 'ready'))
const selectedReadyDocuments = computed(() =>
  readyDocuments.value.filter((doc) => selectedDocumentIds.value.includes(doc.id)),
)
const selectedCount = computed(() => selectedReadyDocuments.value.length)
const totalChunks = computed(() => documents.value.reduce((sum, doc) => sum + (Number(doc?.chunk_count) || 0), 0))
const hasUserToken = computed(() => Boolean(userToken.value))
const hasSessionToken = computed(() => Boolean(sessionToken.value))
const sessionSummary = computed(() => sessionId.value || '未创建')

watch(apiBaseUrl, (value) => writeStorage(STORAGE_KEYS.apiBaseUrl, value))
watch(loginEmail, (value) => writeStorage(STORAGE_KEYS.loginEmail, value))
watch(userToken, (value) => writeStorage(STORAGE_KEYS.userToken, value))
watch(userTokenExpiresAt, (value) => writeStorage(STORAGE_KEYS.userTokenExpiresAt, value))
watch(sessionToken, (value) => writeStorage(STORAGE_KEYS.sessionToken, value))
watch(sessionTokenExpiresAt, (value) => writeStorage(STORAGE_KEYS.sessionTokenExpiresAt, value))
watch(sessionId, (value) => writeStorage(STORAGE_KEYS.sessionId, value))
watch(question, (value) => writeStorage(STORAGE_KEYS.question, value))
watch(topK, (value) => writeStorage(STORAGE_KEYS.topK, normalizeTopK(value)))
watch(
  selectedDocumentIds,
  (value) => writeJsonStorage(STORAGE_KEYS.selectedDocumentIds, normalizeIdList(value)),
  { deep: true },
)

function normalizeSelectedDocumentIds() {
  const readyIds = new Set(readyDocuments.value.map((doc) => doc.id))
  selectedDocumentIds.value = normalizeIdList(selectedDocumentIds.value.filter((id) => readyIds.has(id)))
}

function setBanner(message, isError = false) {
  statusMessage.value = isError ? '操作失败' : message
  errorMessage.value = isError ? message : ''
}

async function refreshDocuments() {
  loadingDocuments.value = true
  errorMessage.value = ''

  try {
    const response = await listDocuments(apiBaseUrl.value, { skip: 0, limit: 100 })
    documents.value = Array.isArray(response?.items) ? response.items : []
    normalizeSelectedDocumentIds()
    statusMessage.value = `已加载 ${documents.value.length} 个文档，其中 ${readyDocuments.value.length} 个可检索。`
  } catch (error) {
    setBanner(`加载文档失败：${error?.message || '未知错误'}`, true)
  } finally {
    loadingDocuments.value = false
  }
}

function toggleDocumentSelection(doc) {
  if (!doc || doc.status !== 'ready') {
    return
  }

  const id = Number(doc.id)
  if (selectedDocumentIds.value.includes(id)) {
    selectedDocumentIds.value = selectedDocumentIds.value.filter((currentId) => currentId !== id)
  } else {
    selectedDocumentIds.value = [...selectedDocumentIds.value, id]
  }
}

function selectAllReadyDocuments() {
  selectedDocumentIds.value = readyDocuments.value.map((doc) => doc.id)
}

function clearSelectedDocuments() {
  selectedDocumentIds.value = []
}

function buildHistorySourceSummary(results) {
  return results.slice(0, 3).map((source, index) => ({
    label: index + 1,
    filename: source.filename,
    chunk_index: source.chunk_index,
    score: source.score,
    preview: truncateText(source.content, 140),
  }))
}

async function issueSession() {
  const response = await createSession(apiBaseUrl.value, userToken.value)
  sessionToken.value = response?.token?.access_token || ''
  sessionTokenExpiresAt.value = response?.token?.expires_at || ''
  sessionId.value = response?.session_id || ''
  answer.value = ''
  retrievalResults.value = []
  conversationHistory.value = []
  statusMessage.value = `会话已创建：${sessionSummary.value}`
}

async function handleLogin() {
  loadingAuth.value = true
  errorMessage.value = ''

  try {
    const response = await loginUser(apiBaseUrl.value, loginEmail.value.trim(), loginPassword.value)
    userToken.value = response?.access_token || ''
    userTokenExpiresAt.value = response?.expires_at || ''
    await issueSession()
    await refreshDocuments()
    statusMessage.value = `登录成功，且已创建会话：${sessionSummary.value}`
  } catch (error) {
    setBanner(`登录失败：${error?.message || '未知错误'}`, true)
  } finally {
    loadingAuth.value = false
    loginPassword.value = ''
  }
}

async function handleCreateSession() {
  if (!hasUserToken.value) {
    setBanner('请先登录，获取用户 token 后再创建会话。', true)
    return
  }

  loadingAuth.value = true
  errorMessage.value = ''

  try {
    await issueSession()
    statusMessage.value = `会话已刷新：${sessionSummary.value}`
  } catch (error) {
    setBanner(`创建会话失败：${error?.message || '未知错误'}`, true)
  } finally {
    loadingAuth.value = false
  }
}

async function copyText(text, marker) {
  const value = String(text ?? '')
  if (!value) {
    return
  }

  try {
    await navigator.clipboard.writeText(value)
    copiedMarker.value = marker
    statusMessage.value = '已复制到剪贴板'
    window.setTimeout(() => {
      if (copiedMarker.value === marker) {
        copiedMarker.value = ''
      }
    }, 1400)
  } catch (error) {
    setBanner(`复制失败：${error?.message || '未知错误'}`, true)
  }
}

async function clearConversation() {
  errorMessage.value = ''

  try {
    if (hasSessionToken.value) {
      await clearChatHistory(apiBaseUrl.value, sessionToken.value)
    }
    answer.value = ''
    retrievalResults.value = []
    conversationHistory.value = []
    statusMessage.value = '会话历史已清空'
  } catch (error) {
    setBanner(`清空会话失败：${error?.message || '未知错误'}`, true)
  }
}

async function handleAsk() {
  const query = question.value.trim()
  if (!query) {
    setBanner('请输入问题。', true)
    return
  }

  if (!hasSessionToken.value) {
    setBanner('请先登录并创建会话，再开始提问。', true)
    return
  }

  loadingAsk.value = true
  errorMessage.value = ''

  try {
    const retrieved = await retrieveDocuments(apiBaseUrl.value, {
      query,
      topK: normalizeTopK(topK.value),
      documentIds: selectedDocumentIds.value,
    })
    retrievalResults.value = Array.isArray(retrieved?.results) ? retrieved.results : []

    const prompt = buildRagPrompt(query, retrievalResults.value)
    const response = await chatWithSession(apiBaseUrl.value, sessionToken.value, [
      {
        role: 'user',
        content: prompt,
      },
    ])

    const assistantAnswer = extractAssistantMessage(response?.messages)
    answer.value = assistantAnswer || '模型已返回消息，但未检测到 assistant 文本内容。'

    conversationHistory.value = [
      {
        question: query,
        answer: answer.value,
        created_at: new Date().toISOString(),
        sources: buildHistorySourceSummary(retrievalResults.value),
      },
      ...conversationHistory.value,
    ].slice(0, 5)

    statusMessage.value = `问答完成，召回 ${retrievalResults.value.length} 条资料。`
  } catch (error) {
    setBanner(`问答失败：${error?.message || '未知错误'}`, true)
  } finally {
    loadingAsk.value = false
  }
}

onMounted(async () => {
  await refreshDocuments()
  if (hasSessionToken.value) {
    statusMessage.value = '已恢复本地会话，可以直接提问。'
  }
})
</script>

<template>
  <main class="app-shell">
    <section class="hero">
      <div class="hero-copy">
        <p class="eyebrow">Phase 3 · 基础问答</p>
        <h1>公司知识库小前端</h1>
        <p>
          这个页面先做“检索 → 组装上下文 → 问答”的最小闭环，方便你验证文档入库后的 RAG 效果和引用来源。
        </p>
      </div>

      <div class="hero-stats">
        <div class="stat-card">
          <span>总文档</span>
          <strong>{{ documents.length }}</strong>
          <small>{{ readyDocuments.length }} 个可检索</small>
        </div>
        <div class="stat-card">
          <span>已选文档</span>
          <strong>{{ selectedCount }}</strong>
          <small>{{ totalChunks }} chunks</small>
        </div>
        <div class="stat-card">
          <span>当前会话</span>
          <strong>{{ sessionSummary }}</strong>
          <small>{{ hasSessionToken ? '可直接提问' : '需要先登录' }}</small>
        </div>
      </div>
    </section>

    <section v-if="statusMessage" class="banner banner-info">
      {{ statusMessage }}
    </section>

    <section v-if="errorMessage" class="banner banner-error">
      {{ errorMessage }}
    </section>

    <section class="grid">
      <article class="panel auth-panel">
        <div class="panel-header">
          <div>
            <p class="panel-kicker">Step 1</p>
            <h2>认证与会话</h2>
          </div>
          <button class="ghost-button" type="button" @click="refreshDocuments" :disabled="loadingDocuments">
            {{ loadingDocuments ? '刷新中…' : '刷新文档' }}
          </button>
        </div>

        <div class="field-grid">
          <label>
            <span>API Base URL</span>
            <input v-model="apiBaseUrl" type="text" spellcheck="false" />
          </label>

          <label>
            <span>登录邮箱</span>
            <input v-model="loginEmail" type="email" autocomplete="email" placeholder="name@example.com" />
          </label>

          <label>
            <span>登录密码</span>
            <input v-model="loginPassword" type="password" autocomplete="current-password" placeholder="输入密码" />
          </label>
        </div>

        <div class="button-row">
          <button class="primary-button" type="button" @click="handleLogin" :disabled="loadingAuth">
            {{ loadingAuth ? '处理中…' : '登录并创建会话' }}
          </button>
          <button class="secondary-button" type="button" @click="handleCreateSession" :disabled="loadingAuth || !hasUserToken">
            仅创建新会话
          </button>
        </div>

        <div class="token-stack">
          <div class="token-item">
            <div class="token-meta">
              <span>用户 Token</span>
              <code>{{ shortToken(userToken) }}</code>
              <small v-if="userTokenExpiresAt">过期：{{ formatDate(userTokenExpiresAt) }}</small>
            </div>
            <button class="ghost-button" type="button" @click="copyText(userToken, 'user')" :disabled="!userToken">
              {{ copiedMarker === 'user' ? '已复制' : '复制' }}
            </button>
          </div>

          <div class="token-item">
            <div class="token-meta">
              <span>会话 Token</span>
              <code>{{ shortToken(sessionToken) }}</code>
              <small v-if="sessionTokenExpiresAt">过期：{{ formatDate(sessionTokenExpiresAt) }}</small>
            </div>
            <button class="ghost-button" type="button" @click="copyText(sessionToken, 'session')" :disabled="!sessionToken">
              {{ copiedMarker === 'session' ? '已复制' : '复制' }}
            </button>
          </div>
        </div>

        <div class="inline-meta">
          <span>会话 ID：<code>{{ sessionSummary }}</code></span>
          <span>会话状态：{{ hasSessionToken ? '已激活' : '未激活' }}</span>
        </div>
      </article>

      <article class="panel docs-panel">
        <div class="panel-header">
          <div>
            <p class="panel-kicker">Step 2</p>
            <h2>选择检索文档</h2>
          </div>
          <span class="chip">{{ selectedCount }} / {{ readyDocuments.length }} 已选</span>
        </div>

        <div class="button-row compact">
          <button class="secondary-button" type="button" @click="selectAllReadyDocuments" :disabled="!readyDocuments.length">
            全选可检索文档
          </button>
          <button class="secondary-button" type="button" @click="clearSelectedDocuments" :disabled="!selectedDocumentIds.length">
            清空选择
          </button>
        </div>

        <div class="doc-list">
          <button
            v-for="doc in documents"
            :key="doc.id"
            type="button"
            class="doc-card"
            :class="{ selected: selectedDocumentIds.includes(doc.id), ready: doc.status === 'ready' }"
            :disabled="doc.status !== 'ready'"
            @click="toggleDocumentSelection(doc)"
          >
            <div class="doc-main">
              <strong>{{ doc.filename }}</strong>
              <p>{{ String(doc.file_type || '').toUpperCase() }} · {{ doc.chunk_count }} chunks</p>
            </div>

            <div class="doc-meta">
              <span class="status-badge" :class="doc.status">{{ doc.status }}</span>
              <small>{{ formatDate(doc.updated_at) }}</small>
            </div>
          </button>
        </div>
      </article>

      <article class="panel qa-panel">
        <div class="panel-header">
          <div>
            <p class="panel-kicker">Step 3</p>
            <h2>检索增强问答</h2>
          </div>
          <button class="ghost-button" type="button" @click="clearConversation" :disabled="loadingAsk">
            清空会话
          </button>
        </div>

        <div class="qa-layout">
          <label class="question-field">
            <span>你的问题</span>
            <textarea
              v-model="question"
              rows="5"
              placeholder="例如：公司员工手册里差旅报销要走哪些审批？"
            ></textarea>
          </label>

          <div class="qa-controls">
            <label>
              <span>Top K</span>
              <input v-model.number="topK" type="number" min="1" max="20" />
            </label>

            <div class="control-hint">
              <span>当前会话可直接提问</span>
              <small>选择文档后，检索结果会只限定在这些文档中。</small>
            </div>

            <div class="button-row compact">
              <button class="primary-button" type="button" @click="handleAsk" :disabled="loadingAsk || !hasSessionToken">
                {{ loadingAsk ? '检索中…' : '检索并提问' }}
              </button>
              <button class="secondary-button" type="button" @click="copyText(answer, 'answer')" :disabled="!answer">
                {{ copiedMarker === 'answer' ? '已复制回答' : '复制回答' }}
              </button>
            </div>
          </div>
        </div>

        <div v-if="answer" class="answer-box">
          <div class="answer-box-header">
            <h3>回答</h3>
            <small>{{ retrievalResults.length }} 条参考资料</small>
          </div>
          <p>{{ answer }}</p>
        </div>

        <div v-if="retrievalResults.length" class="result-block">
          <div class="result-block-header">
            <h3>引用来源 / 检索片段</h3>
            <small>这些片段会被拼进问答上下文中。</small>
          </div>

          <div class="source-grid">
            <article v-for="(source, index) in retrievalResults" :key="source.chunk_id" class="source-card">
              <div class="source-card-header">
                <strong>[{{ index + 1 }}] {{ source.filename }}</strong>
                <span>{{ source.score?.toFixed?.(3) ?? Number(source.score || 0).toFixed(3) }}</span>
              </div>
              <div class="source-meta">
                <span>chunk {{ source.chunk_index }}</span>
                <span>ID {{ source.chunk_id }}</span>
              </div>
              <p>{{ source.content }}</p>
            </article>
          </div>
        </div>

        <div v-else class="empty-state">
          还没有检索结果。输入问题后，页面会先调用 `retrieve`，再把来源拼进问答上下文。
        </div>

        <div v-if="conversationHistory.length" class="history-block">
          <div class="result-block-header">
            <h3>最近问答记录</h3>
            <small>当前页面只保留最近 5 条本地历史。</small>
          </div>

          <details v-for="item in conversationHistory" :key="item.created_at" class="history-item">
            <summary>
              <span>{{ formatDate(item.created_at) }}</span>
              <strong>{{ item.question }}</strong>
              <small>{{ item.sources.length }} 条参考资料</small>
            </summary>
            <p class="history-answer">{{ item.answer }}</p>
            <div v-if="item.sources.length" class="history-sources">
              <span v-for="source in item.sources" :key="`${item.created_at}-${source.label}`" class="history-chip">
                [{{ source.label }}] {{ source.filename }} · chunk {{ source.chunk_index }}
              </span>
            </div>
          </details>
        </div>
      </article>
    </section>
  </main>
</template>

