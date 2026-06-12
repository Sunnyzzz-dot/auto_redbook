<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import {
  CheckCircle2,
  Image,
  KeyRound,
  Loader2,
  LogIn,
  Play,
  RefreshCw,
  Send,
  ShieldCheck,
  UserPlus
} from 'lucide-vue-next'
import { AgentRun, WS_BASE, api, setToken, state } from './stores/api'

const auth = reactive({ email: 'operator@example.com', password: 'password123' })
const keyForm = reactive({ apiKey: '' })
const accountForm = reactive({ displayName: '小红书主账号', workerId: 'local-worker' })
const createForm = reactive({
  instruction: '帮我写一篇介绍 AI 自动化小红书运营工作流的笔记',
  imageCount: 3,
  imageRatio: '2K',
  styleHint: '专业但亲切，适合收藏',
  targetAudienceHint: '内容运营、独立开发者、小团队创业者',
  mode: 'advanced'
})
const publishForm = reactive({ accountId: '', publishMode: 'manual_approve' })
const loading = ref('')
const error = ref('')
const run = ref<AgentRun | null>(null)
const modelKeys = ref<Array<{ id: string; provider: string; status: string }>>([])
const accounts = ref<Array<{ id: string; display_name: string; login_status: string; bound_worker_id: string | null }>>([])
const publishJob = ref<Record<string, unknown> | null>(null)
const browserFrame = ref('')
const browserFrameWidth = ref(0)
const browserFrameHeight = ref(0)
const browserSessionId = ref('')
const browserStatus = ref('')
const browserError = ref('')
const browserLastFrameAt = ref('')
const remoteText = ref('')
const remoteDismissed = ref(false)
const remoteViewScale = ref(1)
const lastRemoteClickText = ref('')
const brokenImageUrls = ref<string[]>([])
let browserSocket: WebSocket | null = null

const isAuthed = computed(() => Boolean(state.token))
const selectedDraft = computed(() => run.value?.draft)
const needsBrowserSession = computed(() =>
  ['requires_human_intervention', 'awaiting_manual_approval'].includes(String(publishJob.value?.status || ''))
)
const showRemoteControl = computed(() => !remoteDismissed.value && (needsBrowserSession.value || Boolean(browserSessionId.value)))

async function withLoading<T>(name: string, fn: () => Promise<T>) {
  if (loading.value) return
  loading.value = name
  error.value = ''
  try {
    return await fn()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = ''
  }
}

async function register() {
  await withLoading('register', async () => {
    const response = await api<{ access_token: string }>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify(auth)
    })
    setToken(response.access_token)
    await refreshSettings()
  })
}

async function login() {
  await withLoading('login', async () => {
    const response = await api<{ access_token: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(auth)
    })
    setToken(response.access_token)
    await refreshSettings()
  })
}

async function refreshSettings() {
  if (!state.token) return
  modelKeys.value = await api<Array<{ id: string; provider: string; status: string }>>('/api/model-keys')
  accounts.value = await api<
    Array<{ id: string; display_name: string; login_status: string; bound_worker_id: string | null }>
  >('/api/xhs-accounts')
  if (!publishForm.accountId && accounts.value[0]) publishForm.accountId = accounts.value[0].id
}

async function saveKey() {
  await withLoading('key', async () => {
    await api('/api/model-keys', {
      method: 'POST',
      body: JSON.stringify({ api_key: keyForm.apiKey })
    })
    keyForm.apiKey = ''
    await refreshSettings()
  })
}

async function addAccount() {
  await withLoading('account', async () => {
    await api('/api/xhs-accounts', {
      method: 'POST',
      body: JSON.stringify({
        display_name: accountForm.displayName,
        bound_worker_id: accountForm.workerId || null
      })
    })
    await refreshSettings()
  })
}

async function createRun() {
  if (loading.value) return
  loading.value = 'run'
  error.value = ''
  try {
    run.value = await api<AgentRun>('/api/agent/runs', {
      method: 'POST',
      body: JSON.stringify({
        instruction: createForm.instruction,
        image_count: createForm.imageCount,
        image_ratio: createForm.imageRatio,
        style_hint: createForm.styleHint,
        target_audience_hint: createForm.targetAudienceHint,
        mode: createForm.mode
      })
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    loading.value = ''
    return
  }
  loading.value = ''
  await pollAgentRun(run.value.id)
}

async function pollAgentRun(runId: string) {
  const terminalStatuses = new Set(['draft_ready', 'failed'])
  for (let index = 0; index < 240; index += 1) {
    if (terminalStatuses.has(String(run.value?.status))) return
    await new Promise((resolve) => window.setTimeout(resolve, 1000))
    try {
      run.value = await api<AgentRun>(`/api/agent/runs/${runId}`)
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
      return
    }
  }
  error.value = '生成仍在运行，请稍后刷新结果'
}

async function regenerate(target: string) {
  if (!run.value) return
  await withLoading(`regen-${target}`, async () => {
    if (target === 'images') brokenImageUrls.value = []
    run.value = await api<AgentRun>(`/api/agent/runs/${run.value?.id}/regenerate`, {
      method: 'POST',
      body: JSON.stringify({ target, image_count: createForm.imageCount })
    })
  })
}

async function saveDraft() {
  if (!selectedDraft.value) return
  await withLoading('draft', async () => {
    const draft = selectedDraft.value
    if (!draft) return
    const updated = await api<AgentRun['draft']>(`/api/drafts/${draft.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        selected_title: limitTitle(draft.selected_title),
        body: draft.body,
        hashtags: draft.hashtags
      })
    })
    if (run.value) run.value.draft = updated as AgentRun['draft']
  })
}

async function publish() {
  if (!selectedDraft.value || !publishForm.accountId) return
  await withLoading('publish', async () => {
    remoteDismissed.value = false
    browserFrame.value = ''
    browserSessionId.value = ''
    publishJob.value = await api<Record<string, unknown>>('/api/publish-jobs', {
      method: 'POST',
      body: JSON.stringify({
        draft_id: selectedDraft.value?.id,
        account_id: publishForm.accountId,
        publish_mode: publishForm.publishMode
      })
    })
    await pollPublishJob(String(publishJob.value.id))
  })
}

async function pollPublishJob(jobId: string) {
  const terminalStatuses = new Set([
    'failed',
    'published',
    'requires_human_intervention',
    'awaiting_manual_approval'
  ])
  for (let index = 0; index < 30; index += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 1000))
    publishJob.value = await api<Record<string, unknown>>(`/api/publish-jobs/${jobId}`)
    if (terminalStatuses.has(String(publishJob.value.status))) return
  }
}

async function openRemoteControl() {
  const jobId = publishJob.value?.id
  if (!jobId) return
  await withLoading('remote', async () => {
    remoteDismissed.value = false
    browserError.value = ''
    browserStatus.value = '连接中'
    if (typeof publishJob.value?.screenshot_url === 'string') {
      browserFrame.value = publishJob.value.screenshot_url
    }
    const session = await api<{ id: string }>(`/api/publish-jobs/${jobId}/browser-session`)
    browserSessionId.value = session.id
    browserSocket?.close()
    browserSocket = new WebSocket(`${WS_BASE}/api/browser-sessions/${session.id}?token=${encodeURIComponent(state.token)}`)
    const socket = browserSocket
    browserSocket.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.type === 'session_ready') {
        browserStatus.value = '已连接'
      }
      if (message.image) {
        browserFrame.value = message.image
        browserFrameWidth.value = Number(message.width || 0)
        browserFrameHeight.value = Number(message.height || 0)
        browserLastFrameAt.value = new Date().toLocaleTimeString()
        const click = message.last_click
        if (click) {
          lastRemoteClickText.value =
            ` · 点击 ${Math.round(Number(click.x))},${Math.round(Number(click.y))}` +
            ` / 基准 ${Math.round(Number(click.basis_width || 0))}x${Math.round(Number(click.basis_height || 0))}` +
            ` / 源图 ${Math.round(Number(click.source_width || 0))}x${Math.round(Number(click.source_height || 0))}`
        }
        browserStatus.value = `已更新画面 · 查看缩放 ${Math.round(remoteViewScale.value * 100)}%${lastRemoteClickText.value}`
      }
      if (message.error) browserError.value = String(message.error)
      if (message.type === 'job_status') {
        browserStatus.value = `任务状态：${message.status}`
        publishJob.value = {
          ...(publishJob.value || {}),
          status: message.status,
          failure_reason: message.failure_reason,
          result_url: message.result_url,
          screenshot_url: message.screenshot_url
        }
      }
    }
    browserSocket.onclose = (event) => {
      if (browserSocket === socket) {
        browserStatus.value = '已断开'
        if (!event.wasClean) browserError.value = `远程连接已关闭：${event.code || 'unknown'}`
      }
    }
    browserSocket.onerror = () => {
      browserError.value = '远程连接失败'
    }
    try {
      await waitForSocketOpen(socket)
    } catch (err) {
      browserError.value = err instanceof Error ? err.message : String(err)
      throw err
    }
    browserStatus.value = '已连接'
    socket.send(JSON.stringify({ type: 'reset_zoom' }))
  })
}

async function sendBrowserEvent(event: Record<string, unknown>) {
  browserError.value = ''
  if (!browserSocket || browserSocket.readyState !== WebSocket.OPEN) {
    await openRemoteControl()
  }
  if (!browserSocket || browserSocket.readyState !== WebSocket.OPEN) {
    browserError.value = '远程连接未就绪'
    return
  }
  browserStatus.value = `已发送：${String(event.type)}`
  browserSocket.send(JSON.stringify(event))
  if (event.type !== 'continue' && event.type !== 'screenshot') {
    window.setTimeout(() => {
      if (browserSocket?.readyState === WebSocket.OPEN) {
        browserSocket.send(JSON.stringify({ type: 'screenshot' }))
      }
    }, 700)
  }
  if (event.type === 'continue' && publishJob.value?.id) {
    await pollPublishJob(String(publishJob.value.id))
  }
}

async function typeRemoteText() {
  const text = remoteText.value
  if (!text) return
  await sendBrowserEvent({ type: 'type', text })
}

async function closeRemoteControl() {
  if (browserSocket?.readyState === WebSocket.OPEN) {
    browserSocket.send(JSON.stringify({ type: 'close' }))
  }
  browserSocket?.close()
  browserSocket = null
  browserSessionId.value = ''
  browserFrame.value = ''
  browserFrameWidth.value = 0
  browserFrameHeight.value = 0
  browserStatus.value = ''
  browserError.value = ''
  remoteText.value = ''
  remoteViewScale.value = 1
  lastRemoteClickText.value = ''
  remoteDismissed.value = true
  if (publishJob.value) {
    publishJob.value = {
      ...publishJob.value,
      status: 'remote_closed',
      failure_reason: 'remote_session_closed'
    }
  }
}

function waitForSocketOpen(socket: WebSocket) {
  if (socket.readyState === WebSocket.OPEN) return Promise.resolve()
  return new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      window.clearTimeout(timer)
      socket.removeEventListener('open', handleOpen)
      socket.removeEventListener('error', handleError)
      socket.removeEventListener('close', handleClose)
    }
    const handleOpen = () => {
      cleanup()
      resolve()
    }
    const handleError = () => {
      cleanup()
      reject(new Error('远程连接失败'))
    }
    const handleClose = (event: CloseEvent) => {
      cleanup()
      reject(new Error(`远程连接已关闭：${event.code || 'unknown'}`))
    }
    const timer = window.setTimeout(() => {
      cleanup()
      reject(new Error('远程连接超时'))
    }, 8000)
    socket.addEventListener('open', handleOpen)
    socket.addEventListener('error', handleError)
    socket.addEventListener('close', handleClose)
  })
}

function adjustRemoteViewScale(delta: number) {
  remoteViewScale.value = Math.max(0.6, Math.min(2.2, Number((remoteViewScale.value + delta).toFixed(2))))
  browserStatus.value = `查看缩放 ${Math.round(remoteViewScale.value * 100)}%`
}

function clickRemoteFrame(event: MouseEvent) {
  const image = event.currentTarget as HTMLImageElement
  const rect = image.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const rx = (event.clientX - rect.left) / rect.width
  const ry = (event.clientY - rect.top) / rect.height
  const naturalWidth = image.naturalWidth || browserFrameWidth.value || rect.width
  const naturalHeight = image.naturalHeight || browserFrameHeight.value || rect.height
  lastRemoteClickText.value =
    ` · 已发送点击 ${Math.round(rx * naturalWidth)},${Math.round(ry * naturalHeight)}`
  sendBrowserEvent({
    type: 'click',
    rx: Math.max(0, Math.min(1, rx)),
    ry: Math.max(0, Math.min(1, ry)),
    display_width: rect.width,
    display_height: rect.height,
    natural_width: naturalWidth,
    natural_height: naturalHeight
  })
}

function limitTitle(title: string) {
  return title.replace(/\s+/g, ' ').trim().slice(0, 20)
}

function markImageBroken(url: string) {
  if (!brokenImageUrls.value.includes(url)) brokenImageUrls.value.push(url)
}

refreshSettings()
</script>

<template>
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">RB</div>
        <div>
          <h1>Red Book Agent</h1>
          <p>小红书笔记生成与发布工作台</p>
        </div>
      </div>

      <section class="panel auth-panel">
        <h2>登录</h2>
        <input v-model="auth.email" placeholder="邮箱" />
        <input v-model="auth.password" type="password" placeholder="密码" />
        <div class="toolbar">
          <button :disabled="!!loading" @click="login"><LogIn />登录</button>
          <button class="secondary" :disabled="!!loading" @click="register"><UserPlus />注册</button>
        </div>
      </section>

      <section class="panel">
        <h2>模型 Key</h2>
        <input v-model="keyForm.apiKey" placeholder="火山方舟 API Key" />
        <button :disabled="!isAuthed || !!loading" @click="saveKey"><KeyRound />保存</button>
        <p class="metric">已保存 {{ modelKeys.length }} 个 Key</p>
      </section>

      <section class="panel">
        <h2>小红书账号</h2>
        <input v-model="accountForm.displayName" placeholder="账号名称" />
        <input v-model="accountForm.workerId" placeholder="绑定 Worker ID" />
        <button :disabled="!isAuthed || !!loading" @click="addAccount"><CheckCircle2 />绑定</button>
        <select v-model="publishForm.accountId">
          <option value="">选择发布账号</option>
          <option v-for="account in accounts" :key="account.id" :value="account.id">
            {{ account.display_name }} · {{ account.login_status }}
          </option>
        </select>
      </section>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div>
          <h2>创作任务</h2>
          <p>一句话开始，Agent 会按 ReAct 步骤生成、检查并准备发布。</p>
        </div>
        <div class="status" :class="{ active: loading }">
          <Loader2 v-if="loading" class="spin" />
          {{ loading ? '运行中' : '就绪' }}
        </div>
      </header>

      <section class="band composer">
        <textarea v-model="createForm.instruction" rows="3" />
        <div class="form-grid">
          <label>
            图片数量
            <input v-model.number="createForm.imageCount" min="1" max="9" type="number" />
          </label>
          <label>
            风格
            <input v-model="createForm.styleHint" />
          </label>
          <label>
            目标人群
            <input v-model="createForm.targetAudienceHint" />
          </label>
        </div>
        <button class="primary" :disabled="!isAuthed || !!loading" @click="createRun">
          <Play />生成笔记
        </button>
      </section>

      <p v-if="error" class="error">{{ error }}</p>

      <section v-if="run" class="grid">
        <div class="band trace">
          <div class="section-head">
            <h2>ReAct Trace</h2>
            <span>{{ run.status }}</span>
          </div>
          <p v-if="run.failure_reason" class="error">{{ run.failure_reason }}</p>
          <ol>
            <li v-for="step in run.steps" :key="step.id">
              <strong>{{ step.step }}</strong>
              <span>{{ step.thought_summary }}</span>
              <em>{{ step.status }}</em>
              <code v-if="step.error">{{ step.error }}</code>
            </li>
          </ol>
        </div>

        <div v-if="selectedDraft" class="band draft">
          <div class="section-head">
            <h2>草稿编辑</h2>
            <div class="toolbar">
              <button class="secondary" :disabled="!!loading" @click="regenerate('titles')">
                <RefreshCw />标题
              </button>
              <button class="secondary" :disabled="!!loading" @click="regenerate('images')">
                <Image />图片
              </button>
              <button :disabled="!!loading" @click="saveDraft"><CheckCircle2 />保存</button>
            </div>
          </div>

          <div class="title-list">
            <button
              v-for="title in selectedDraft.title_candidates"
              :key="title"
              :class="{ selected: selectedDraft.selected_title === title }"
              @click="selectedDraft.selected_title = limitTitle(title)"
            >
              {{ limitTitle(title) }}
            </button>
          </div>

          <textarea v-model="selectedDraft.body" rows="12" />
          <input
            :value="selectedDraft.hashtags.join(' ')"
            @input="selectedDraft.hashtags = ($event.target as HTMLInputElement).value.split(/\s+/).filter(Boolean)"
          />

          <div class="image-grid">
            <figure v-for="image in selectedDraft.images" :key="image.id">
              <img :src="image.image_url" :alt="image.prompt" @error="markImageBroken(image.image_url)" />
              <figcaption>{{ image.prompt }}</figcaption>
            </figure>
          </div>
          <p v-if="brokenImageUrls.length" class="error">
            图片加载失败：{{ brokenImageUrls.join('，') }}
          </p>

          <div class="safety">
            <ShieldCheck />
            <pre>{{ JSON.stringify(selectedDraft.safety_report, null, 2) }}</pre>
          </div>

          <div class="publish-row">
            <select v-model="publishForm.publishMode">
              <option value="manual_approve">人工确认发布</option>
              <option value="auto_publish">自动点击发布</option>
            </select>
            <button class="primary" :disabled="!publishForm.accountId || !!loading" @click="publish">
              <Send />创建发布任务
            </button>
          </div>

          <pre v-if="publishJob" class="job">{{ JSON.stringify(publishJob, null, 2) }}</pre>

          <div v-if="showRemoteControl" class="remote">
            <div class="section-head">
              <h2>远程接管</h2>
              <div class="toolbar compact">
                <button class="secondary" @click="openRemoteControl"><Play />连接</button>
                <button class="secondary" :disabled="!browserSessionId" @click="sendBrowserEvent({ type: 'screenshot' })">
                  <RefreshCw />刷新
                </button>
              </div>
            </div>
            <p v-if="browserStatus" class="metric">
              {{ browserStatus }}
              <span v-if="browserLastFrameAt"> · {{ browserLastFrameAt }}</span>
              <span v-if="browserFrameWidth && browserFrameHeight"> · {{ browserFrameWidth }}×{{ browserFrameHeight }}</span>
            </p>
            <p v-if="browserError" class="error">{{ browserError }}</p>
            <div v-if="browserFrame" class="remote-frame">
              <img
                :src="browserFrame"
                :style="{ width: `${remoteViewScale * 100}%` }"
                alt="远程浏览器画面"
                @click="clickRemoteFrame"
              />
            </div>
            <div class="remote-input">
              <input v-model="remoteText" placeholder="输入到远程浏览器" @keyup.enter="typeRemoteText" />
              <button class="secondary" @click="typeRemoteText">输入</button>
            </div>
            <div class="toolbar remote-actions">
              <button class="secondary" @click="sendBrowserEvent({ type: 'scroll', dy: -600 })">向上</button>
              <button class="secondary" @click="sendBrowserEvent({ type: 'scroll', dy: 700 })">向下</button>
              <button class="secondary" @click="adjustRemoteViewScale(-0.15)">缩小</button>
              <button class="secondary" @click="adjustRemoteViewScale(0.15)">放大</button>
              <button class="secondary" @click="sendBrowserEvent({ type: 'backspace', count: 1 })">退格</button>
              <button class="secondary" @click="sendBrowserEvent({ type: 'backspace', count: 10 })">退格10</button>
              <button class="secondary" @click="sendBrowserEvent({ type: 'press', key: 'Enter' })">回车</button>
              <button @click="sendBrowserEvent({ type: 'continue' })"><CheckCircle2 />继续任务</button>
              <button class="secondary danger" @click="closeRemoteControl">关闭接管</button>
            </div>
          </div>
        </div>
      </section>
    </section>
  </main>
</template>
