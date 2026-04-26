<template>
  <div class="transcripts-page">
    <div class="page-title">
      <h1>预期与场景解析</h1>
      <p>上传会议转写内容，自动生成预期和场景，审核后写入客户档案</p>
    </div>

    <!-- 文件上传区域 -->
    <div class="upload-section card">
      <h2>上传转写内容</h2>
      <div class="upload-area">
        <div 
          class="upload-box"
          @click="triggerFileSelect"
          @dragover.prevent
          @dragenter="dragover = true"
          @dragleave="dragover = false"
          @drop="handleDrop"
          :class="{ 'dragover': dragover }"
        >
          <div v-if="!file" class="upload-placeholder">
            <div class="upload-icon">📁</div>
            <p>点击上传转写文件，或拖拽文件到此处</p>
            <p class="upload-desc">支持 .txt, .srt, .vtt, .md, .pdf, .doc, .docx, .jpg, .png 格式</p>
          </div>
          <div v-else class="file-info">
            <div class="file-icon">📄</div>
            <div class="file-details">
              <p class="file-name">{{ file.name }}</p>
              <p class="file-size">{{ formatFileSize(file.size) }}</p>
            </div>
            <button class="remove-file" @click.stop="removeFile">✕</button>
          </div>
        </div>
        <input 
          ref="fileInput" 
          type="file" 
          class="file-input"
          multiple
          @change="handleFileSelect"
          accept=".txt,.srt,.vtt,.md,.pdf,.doc,.docx,.jpg,.jpeg,.png,.webp"
        >
      </div>
      
      <!-- 当前客户信息 -->
      <div class="customer-info" v-if="customerStore.currentCustomer">
        <label>当前客户：</label>
        <div class="customer-display">{{ customerStore.currentCustomer.company_name }}</div>
      </div>
      <div v-else class="customer-warning">
        <p>⚠️ 请先在侧边栏选择一个客户</p>
      </div>
      
      <!-- 转写标题 -->
      <div class="transcript-title">
        <label>转写标题：</label>
        <input type="text" v-model="transcriptTitle" class="title-input">
      </div>
      
      <!-- 转写内容预览（如果是文本文件） -->
      <div v-if="transcriptText" class="transcript-preview">
        <h3>转写内容预览</h3>
        <div class="preview-content">{{ transcriptText.slice(0, 500) }}{{ transcriptText.length > 500 ? '...' : '' }}</div>
      </div>
      
      <!-- 解析链路步骤条 -->
      <div v-if="analysisStatus !== 'idle' && analysisStatus !== 'pending'" class="pipeline-steps">
        <div class="step" :class="{ active: stepActive('upload'), done: stepDone('upload') }">
          <span class="step-icon">{{ stepDone('upload') ? '✓' : '1' }}</span>
          <span class="step-label">上传文件</span>
        </div>
        <div class="step-connector" :class="{ done: stepDone('upload') }"></div>
        <div class="step" :class="{ active: stepActive('extract'), done: stepDone('extract') }">
          <span class="step-icon">{{ stepDone('extract') ? '✓' : '2' }}</span>
          <span class="step-label">语义提取</span>
        </div>
        <div class="step-connector" :class="{ done: stepDone('extract') }"></div>
        <div class="step" :class="{ active: stepActive('compare'), done: stepDone('compare') }">
          <span class="step-icon">{{ stepDone('compare') ? '✓' : '3' }}</span>
          <span class="step-label">档案比对</span>
        </div>
        <div class="step-connector" :class="{ done: stepDone('compare') }"></div>
        <div class="step" :class="{ active: stepActive('completed'), done: stepDone('completed') }">
          <span class="step-icon">{{ stepDone('completed') ? '✓' : '4' }}</span>
          <span class="step-label">完成</span>
        </div>
      </div>
      
      <!-- 开始分析按钮 -->
      <div class="action-buttons">
        <button 
          class="primary-button" 
          :disabled="!canStartAnalysis"
          @click="startAnalysis"
        >
          开始分析
        </button>
      </div>
    </div>

    <!-- 分析结果区域 -->
    <div v-if="analysisResult" class="analysis-section card">
      <div class="result-header">
        <h2>分析结果</h2>
        <div class="analysis-status" :class="analysisStatus">
          {{ analysisStatusText }}
        </div>
      </div>
      
      <!-- 预期结果 -->
      <div v-if="analysisResult.expectations && analysisResult.expectations.length" class="result-area">
        <h3>客户预期 ({{ analysisResult.expectations.length }})</h3>
        <div class="result-cards">
          <div 
            v-for="(item, index) in analysisResult.expectations" 
            :key="index"
            class="result-card"
            :class="{ approved: item.approved, rejected: item.rejected }"
          >
            <div class="card-header">
              <div class="card-status">{{ item.status || '未启动' }}</div>
              <div class="card-actions">
                <button class="action-btn edit" @click="toggleEdit('expectation', index)">
                  {{ isEditing('expectation', index) ? '取消' : '编辑' }}
                </button>
                <button 
                  class="action-btn approve"
                  :class="{ active: item.approved }"
                  @click="markForApproval('expectation', index, 'approve')"
                >
                  ✓ 批准
                </button>
                <button 
                  class="action-btn reject"
                  :class="{ active: item.rejected }"
                  @click="markForApproval('expectation', index, 'reject')"
                >
                  ✗ 拒绝
                </button>
              </div>
            </div>
            <div class="card-content">
              <!-- 标题 -->
              <div v-if="isEditing('expectation', index)" class="edit-field">
                <label>标题</label>
                <input v-model="item.summary" type="text" class="edit-input">
              </div>
              <p v-else class="card-title">{{ item.summary || '未命名预期' }}</p>
              
              <!-- 描述 -->
              <div v-if="isEditing('expectation', index)" class="edit-field">
                <label>描述</label>
                <textarea v-model="item.description" class="edit-textarea" rows="3"></textarea>
              </div>
              <p v-else class="card-description">{{ item.description || '暂无描述' }}</p>
              
              <div class="card-quote" v-if="item.source_quote">
                <p class="quote-label">原文引用：</p>
                <p class="quote-content">"{{ item.source_quote }}"</p>
              </div>
            </div>
          </div>
        </div>
      </div>
      
      <!-- 场景结果 -->
      <div v-if="analysisResult.scenarios && analysisResult.scenarios.length" class="result-area">
        <h3>业务场景 ({{ analysisResult.scenarios.length }})</h3>
        <div class="result-cards">
          <div 
            v-for="(item, index) in analysisResult.scenarios" 
            :key="index"
            class="result-card"
            :class="{ approved: item.approved, rejected: item.rejected }"
          >
            <div class="card-header">
              <div class="card-status">{{ item.status || '未启动' }}</div>
              <div class="card-actions">
                <button class="action-btn edit" @click="toggleEdit('scenario', index)">
                  {{ isEditing('scenario', index) ? '取消' : '编辑' }}
                </button>
                <button 
                  class="action-btn approve"
                  :class="{ active: item.approved }"
                  @click="markForApproval('scenario', index, 'approve')"
                >
                  ✓ 批准
                </button>
                <button 
                  class="action-btn reject"
                  :class="{ active: item.rejected }"
                  @click="markForApproval('scenario', index, 'reject')"
                >
                  ✗ 拒绝
                </button>
              </div>
            </div>
            <div class="card-content">
              <!-- 标题 -->
              <div v-if="isEditing('scenario', index)" class="edit-field">
                <label>标题</label>
                <input v-model="item.title" type="text" class="edit-input">
              </div>
              <p v-else class="card-title">{{ item.title || '未命名场景' }}</p>
              
              <!-- 描述 -->
              <div v-if="isEditing('scenario', index)" class="edit-field">
                <label>描述</label>
                <textarea v-model="item.description" class="edit-textarea" rows="3"></textarea>
              </div>
              <p v-else class="card-description">{{ item.description || '暂无描述' }}</p>
              
              <div class="card-quote" v-if="item.source_quote">
                <p class="quote-label">原文引用：</p>
                <p class="quote-content">"{{ item.source_quote }}"</p>
              </div>
            </div>
          </div>
        </div>
      </div>
      
      <!-- 提交按钮 -->
      <div class="action-buttons">
        <button 
          class="primary-button" 
          :disabled="!canSubmit"
          @click="submitToJiandaoyun"
        >
          提交到客户档案
        </button>
      </div>
    </div>

    <!-- 执行日志 -->
    <div v-if="logs.length" class="logs-section card">
      <h3>执行过程</h3>
      <div class="log-content">
        <div v-for="(log, index) in logs" :key="index" class="log-item">
          <span class="log-time">{{ formatTime(log.time) }}</span>
          <span class="log-message">{{ log.message }}</span>
        </div>
      </div>
    </div>

    <!-- 提示消息 -->
    <div v-if="message" class="message" :class="messageType">
      {{ message }}
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { useCustomerStore } from '../stores/customer'

// 基础数据
const fileInput = ref(null)
const dragover = ref(false)
const file = ref(null)
const transcriptTitle = ref('')
const transcriptText = ref('')
const analysisResult = ref(null)
const approvalStatus = ref({}) // 记录用户对各项的批准/拒绝状态
const logs = ref([])
const message = ref('')
const messageType = ref('info')
const analysisTaskId = ref(null)
const analysisStatus = ref('idle')
const editingItems = ref(new Set()) // 跟踪正在编辑的卡片

// 客户 store
const customerStore = useCustomerStore()

// 计算属性
const canStartAnalysis = computed(() => {
  return !!file.value && !!customerStore.currentCustomer && !!transcriptTitle.value.trim()
})

const canSubmit = computed(() => {
  if (!analysisResult.value) return false
  
  const hasApprovedItems = Object.values(approvalStatus.value).some(status => status === 'approve')
  return hasApprovedItems || approvalStatus.value.all === 'approve'
})

const analysisStatusText = computed(() => {
  switch (analysisStatus.value) {
    case 'idle': return '未开始'
    case 'uploading': return '上传中'
    case 'extracting': return '语义提取中'
    case 'comparing': return '档案比对中'
    case 'completed': return '已完成'
    case 'error': return '分析失败'
    default: return '未知状态'
  }
})

// 生命周期钩子
onMounted(async () => {
  // 恢复当前选中的客户
  customerStore.hydrateCurrentCustomer()
  // 确保客户列表已加载
  await customerStore.fetchCustomers()
  // 自动更新标题
  updateTranscriptTitle()
})

// 方法
// 这里不再需要 loadCustomers 函数，使用 customerStore

function triggerFileSelect() {
  fileInput.value.click()
}

function handleFileSelect(event) {
  const selectedFile = event.target.files[0]
  if (selectedFile) {
    processFile(selectedFile)
  }
}

function handleDrop(event) {
  event.preventDefault()
  dragover.value = false
  
  const droppedFile = event.dataTransfer.files[0]
  if (droppedFile) {
    processFile(droppedFile)
  }
}

function removeFile() {
  file.value = null
  transcriptText.value = ''
}

async function processFile(fileObj) {
  file.value = fileObj
  
  // 如果是文本文件，直接读取内容
  const textTypes = ['txt', 'srt', 'vtt', 'md']
  const ext = fileObj.name.split('.').pop().toLowerCase()
  
  if (textTypes.includes(ext)) {
    try {
      transcriptText.value = await fileObj.text()
    } catch (error) {
      showErrorMessage('读取文件内容失败')
      return
    }
  } else {
    // 如果是图片等二进制文件，标记为已上传
    transcriptText.value = '图片文件已上传，将在分析时处理'
  }
  
  // 如果未设置标题，使用文件名
  if (!transcriptTitle.value) {
    transcriptTitle.value = fileObj.name.replace(/\.[^/.]+$/, '')
  }
}

// 监听当前客户变化，自动更新标题
watch(() => customerStore.currentCustomer, () => {
  updateTranscriptTitle()
})

function updateTranscriptTitle() {
  if (!transcriptTitle.value && customerStore.currentCustomer) {
    transcriptTitle.value = `${customerStore.currentCustomer.company_name} 会议转写`
  }
}

function formatFileSize(bytes) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function addLog(message) {
  logs.value.push({
    time: new Date(),
    message
  })
}

function showErrorMessage(msg) {
  message.value = msg
  messageType.value = 'error'
  setTimeout(() => {
    message.value = ''
  }, 5000)
}

function showSuccessMessage(msg) {
  message.value = msg
  messageType.value = 'success'
  setTimeout(() => {
    message.value = ''
  }, 3000)
}

// 步骤条相关
function stepActive(step) {
  const map = {
    'upload': ['uploading'],
    'extract': ['extracting'],
    'compare': ['comparing'],
    'completed': ['completed']
  }
  return map[step]?.includes(analysisStatus.value) || false
}

function stepDone(step) {
  const order = ['upload', 'extract', 'compare', 'completed']
  const current = analysisStatus.value
  const currentIdx = order.findIndex(s => stepActive(s))
  const stepIdx = order.indexOf(step)
  if (current === 'error') return false
  return stepIdx < currentIdx
}

// 编辑相关
function isEditing(type, index) {
  return editingItems.value.has(`${type}_${index}`)
}

function toggleEdit(type, index) {
  const key = `${type}_${index}`
  if (editingItems.value.has(key)) {
    editingItems.value.delete(key)
  } else {
    editingItems.value.add(key)
  }
}

async function startAnalysis() {
  if (!canStartAnalysis.value) return
  
  addLog('开始分析转写内容')
  analysisStatus.value = 'uploading'
  
  try {
    // 获取客户名称
    const customer = customerStore.currentCustomer
    const companyName = customer ? customer.company_name : '未知客户'
    
    // 上传转写文件
    let uploadResult = null
    
    if (file.value) {
      addLog('上传转写文件')
      
      const formData = new FormData()
      formData.append('file', file.value)
      formData.append('company_name_hint', companyName)
      
      const uploadResponse = await api.post('/api/v1/transcript/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      })
      
      uploadResult = uploadResponse.data
      analysisTaskId.value = uploadResult.transcript_id
      addLog(`文件上传成功，转写ID: ${uploadResult.transcript_id}`)
    }
    
    // 执行提取任务
    analysisStatus.value = 'extracting'
    addLog('启动预期和场景提取任务')
    
    const extractionResponse = await api.post('/api/v1/agent/extraction/task', {
      transcript_id: analysisTaskId.value,
      input_type: file.value.name.endsWith('.pdf') || file.value.name.endsWith('.doc') || file.value.name.endsWith('.docx') ? 'text' : 
                   file.value.name.endsWith('.jpg') || file.value.name.endsWith('.jpeg') || file.value.name.endsWith('.png') || file.value.name.endsWith('.webp') ? 'image' : 'text',
      content: transcriptText.value,
      transcript: uploadResult ? { id: uploadResult.transcript_id, raw_text: transcriptText.value } : { raw_text: transcriptText.value }
    }, { timeout: 300000 })
    
    addLog('提取任务完成')
    
    // 执行比对任务
    analysisStatus.value = 'comparing'
    addLog('启动与客户档案比对任务')
    
    const comparisonResponse = await api.post('/api/v1/agent/comparison/task', {
      transcript_id: analysisTaskId.value,
      company_id: customerStore.currentCustomer.company_id,
      existing_record: customer,
      extraction_result: extractionResponse.data.result
    }, { timeout: 300000 })
    
    addLog('比对任务完成')
    analysisStatus.value = 'completed'
    
    // 设置分析结果：从 change_items 中提取字段值
    const result = comparisonResponse.data.result
    const cards = comparisonResponse.data.cards_with_safety || result.operation_cards || []
    const expectations = []
    const scenarios = []
    for (const card of cards) {
      const tf = card.target_form || ''
      const items = card.change_items || []
      const getVal = (name) => {
        const ci = items.find(i => i.field_name === name || i.widget_name === name)
        return ci ? ci.new_value : ''
      }
      const item = {
        summary: getVal('预期简述') || getVal('detail_brief'),
        description: getVal('预期详情') || getVal('detail'),
        title: getVal('场景标题') || getVal('title'),
        solve_what_ques: getVal('解决什么问题') || getVal('solve_what_ques'),
        solve_what_ans: getVal('怎样解决') || getVal('solve_what_ans'),
        status: getVal('预期状态') || getVal('yuqi_status') || '未启动',
        source_quote: card.source_quote || '',
        operationId: card.card_id,
        operationType: card.operation_type,
        approved: false,
        rejected: false,
        safety_status: card.safety_status,
      }
      if (tf === '预期表') expectations.push(item)
      else if (tf === '场景表') scenarios.push(item)
    }
    analysisResult.value = { ...result, expectations, scenarios }
    
    showSuccessMessage('分析完成，请审核各项内容')
    addLog('分析流程完成')
  } catch (error) {
    analysisStatus.value = 'error'
    const errorMsg = error?.response?.data?.detail || '分析失败'
    showErrorMessage(errorMsg)
    addLog(`分析失败: ${errorMsg}`)
  }
}

function markForApproval(type, index, status) {
  if (!analysisResult.value) return
  
  const item = analysisResult.value[`${type}s`][index]
  if (!item) return
  
  // 记录审批状态
  approvalStatus.value[`${type}_${index}`] = status
  
  // 更新项的状态
  if (status === 'approve') {
    item.approved = true
    item.rejected = false
  } else if (status === 'reject') {
    item.approved = false
    item.rejected = true
  }
  
  addLog(`${type === 'expectation' ? '预期' : '场景'} "${item.summary || item.title}" 被标记为${status === 'approve' ? '批准' : '拒绝'}`)
}

async function submitToJiandaoyun() {
  if (!canSubmit.value) return
  if (!analysisResult.value || !analysisTaskId.value) return
  
  addLog('准备提交到简道云')
  
  try {
    // 获取已批准的操作卡片
    const approvedOperations = []
    
    if (analysisResult.value.expectations) {
      analysisResult.value.expectations.forEach((item, index) => {
        if (item.approved && approvalStatus.value[`expectation_${index}`] !== 'reject') {
          approvedOperations.push(item.operationId)
        }
      })
    }
    
    if (analysisResult.value.scenarios) {
      analysisResult.value.scenarios.forEach((item, index) => {
        if (item.approved && approvalStatus.value[`scenario_${index}`] !== 'reject') {
          approvedOperations.push(item.operationId)
        }
      })
    }
    
    if (approvedOperations.length === 0) {
      showErrorMessage('请至少选择一个批准的项目')
      return
    }
    
    // 执行操作
    addLog(`提交 ${approvedOperations.length} 个项目到简道云`)
    
    const response = await api.post('/api/v1/operations/execute', {
      transcript_id: analysisTaskId.value,
      card_ids: approvedOperations
    })
    
    const results = response.data.results
    let successCount = 0
    let failCount = 0
    
    results.forEach(result => {
      if (result.execute_status === 'success') {
        successCount++
      } else {
        failCount++
      }
    })
    
    addLog(`提交完成：成功 ${successCount} 个，失败 ${failCount} 个`)
    showSuccessMessage(`成功提交 ${successCount} 个项目到客户档案`)
    
    // 更新状态
    if (successCount > 0) {
      analysisResult.value.submitted = true
    }
  } catch (error) {
    const errorMsg = error?.response?.data?.detail || '提交失败'
    showErrorMessage(errorMsg)
    addLog(`提交失败: ${errorMsg}`)
  }
}

function formatTime(date) {
  return new Date(date).toLocaleTimeString()
}
</script>

<style scoped>
.transcripts-page {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.page-title {
  margin-bottom: 30px;
  text-align: center;
}

.page-title h1 {
  margin-bottom: 10px;
  color: var(--text, #333);
}

.page-title p {
  color: var(--muted, #666);
  font-size: 16px;
}

.card {
  background: var(--surface, #fff);
  border: 1px solid var(--line, #e1e5e9);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 24px;
  box-shadow: var(--shadow, 0 2px 8px rgba(0,0,0,0.05));
}

.card h2 {
  margin-top: 0;
  margin-bottom: 20px;
  color: var(--text, #333);
  font-size: 18px;
  border-bottom: 1px solid var(--line, #e1e5e9);
  padding-bottom: 10px;
}

.upload-area {
  margin-bottom: 20px;
}

.upload-box {
  border: 2px dashed var(--line, #e1e5e9);
  border-radius: 12px;
  padding: 40px 20px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
}

.upload-box:hover, .upload-box.dragover {
  border-color: var(--primary, #007bff);
  background-color: rgba(0, 123, 255, 0.05);
}

.upload-icon {
  font-size: 48px;
  margin-bottom: 15px;
}

.upload-placeholder p {
  margin: 6px 0;
  color: var(--muted, #666);
}

.upload-desc {
  font-size: 14px !important;
  color: var(--muted-light, #999) !important;
}

.file-input {
  display: none;
}

.file-info {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 15px;
}

.file-icon {
  font-size: 36px;
}

.file-details {
  text-align: left;
}

.file-name {
  margin: 0 0 5px 0;
  font-weight: 600;
}

.file-size {
  margin: 0;
  font-size: 14px;
  color: var(--muted, #666);
}

.remove-file {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background-color: var(--error, #f44336);
  color: white;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.2s;
}

.remove-file:hover {
  background-color: var(--error-dark, #d32f2f);
}

.customer-select, .transcript-title {
  margin-bottom: 20px;
}

.customer-select label, .transcript-title label {
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
}

.customer-select select, .transcript-title input, .title-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--line, #e1e5e9);
  border-radius: 6px;
  box-sizing: border-box;
  font-size: 15px;
}

.transcript-preview {
  margin-bottom: 20px;
}

.transcript-preview h3 {
  margin-bottom: 10px;
}

.preview-content {
  background-color: var(--surface-soft, #f5f7fa);
  border: 1px solid var(--line, #e1e5e9);
  border-radius: 6px;
  padding: 12px;
  font-size: 14px;
  max-height: 150px;
  overflow-y: auto;
  white-space: pre-wrap;
  line-height: 1.5;
}

/* 解析链路步骤条 */
.pipeline-steps {
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 20px 0;
  padding: 16px;
  background: var(--surface-soft, #f5f7fa);
  border-radius: 10px;
  gap: 0;
}

.step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
}

.step-icon {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--muted, #ccc);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  transition: all 0.3s;
}

.step-label {
  font-size: 12px;
  color: var(--muted-dark, #757575);
  white-space: nowrap;
}

.step.active .step-icon {
  background: var(--primary, #007bff);
  animation: pulse 1.5s infinite;
}

.step.active .step-label {
  color: var(--primary, #007bff);
  font-weight: 600;
}

.step.done .step-icon {
  background: var(--success, #4caf50);
}

.step.done .step-label {
  color: var(--success-dark, #388e3c);
}

.step-connector {
  width: 40px;
  height: 2px;
  background: var(--muted, #ccc);
  margin: 0 4px;
  transition: all 0.3s;
}

.step-connector.done {
  background: var(--success, #4caf50);
}

@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(0, 123, 255, 0.4); }
  70% { box-shadow: 0 0 0 8px rgba(0, 123, 255, 0); }
  100% { box-shadow: 0 0 0 0 rgba(0, 123, 255, 0); }
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.analysis-status {
  padding: 5px 10px;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 500;
}

.analysis-status.idle, .analysis-status.pending {
  background-color: var(--muted, #f5f5f5);
  color: var(--muted-dark, #757575);
}

.analysis-status.uploading, .analysis-status.extracting, .analysis-status.comparing {
  background-color: var(--info-light, #e1f5fe);
  color: var(--info-dark, #0277bd);
}

.analysis-status.completed {
  background-color: var(--success-light, #e8f5e9);
  color: var(--success-dark, #2e7d32);
}

.analysis-status.error {
  background-color: var(--error-light, #ffebee);
  color: var(--error-dark, #c62828);
}

.result-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.result-card {
  border: 1px solid var(--line, #e1e5e9);
  border-radius: 8px;
  overflow: hidden;
  transition: all 0.2s;
}

.result-card.approved {
  border-color: var(--success, #4caf50);
  box-shadow: 0 0 0 1px var(--success, #4caf50);
}

.result-card.rejected {
  border-color: var(--error, #f44336);
  box-shadow: 0 0 0 1px var(--error, #f44336);
  opacity: 0.7;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 15px;
  background-color: var(--surface-soft, #f5f7fa);
  border-bottom: 1px solid var(--line, #e1e5e9);
}

.card-status {
  padding: 3px 8px;
  border-radius: 12px;
  font-size: 12px;
  background-color: var(--muted, #f5f5f5);
  color: var(--muted-dark, #757575);
}

.card-actions {
  display: flex;
  gap: 8px;
}

.action-btn {
  padding: 4px 8px;
  font-size: 12px;
  border-radius: 4px;
  border: none;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn.approve {
  background-color: var(--success-weak, #e8f5e9);
  color: var(--success-dark, #2e7d32);
  border: 1px solid var(--success, #4caf50);
}

.action-btn.approve.active,
.action-btn.approve:hover {
  background-color: var(--success, #4caf50);
  color: white;
}

.action-btn.reject {
  background-color: var(--error-weak, #ffebee);
  color: var(--error-dark, #c62828);
  border: 1px solid var(--error, #f44336);
}

.action-btn.reject.active,
.action-btn.reject:hover {
  background-color: var(--error, #f44336);
  color: white;
}

.action-btn.edit {
  background-color: var(--surface-soft, #f5f7fa);
  color: var(--text, #333);
  border: 1px solid var(--line, #e1e5e9);
}

.action-btn.edit:hover {
  background-color: var(--primary-weak, #e3f2fd);
  color: var(--primary, #007bff);
  border-color: var(--primary, #007bff);
}

.card-content {
  padding: 15px;
}

.card-title {
  font-weight: 600;
  margin: 0 0 10px 0;
}

.card-description {
  margin: 0 0 15px 0;
  color: var(--text, #333);
}

.card-quote {
  background-color: var(--surface-soft, #f5f7fa);
  border-left: 3px solid var(--primary, #007bff);
  padding: 10px;
  border-radius: 0 4px 4px 0;
}

.quote-label {
  font-size: 12px;
  font-weight: 600;
  margin: 0 0 5px 0;
  color: var(--muted-dark, #757575);
}

.quote-content {
  margin: 0;
  font-style: italic;
  font-size: 14px;
  color: var(--text-secondary, #555);
}

/* 编辑区域 */
.edit-field {
  margin-bottom: 10px;
}

.edit-field label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--muted-dark, #757575);
  margin-bottom: 4px;
}

.edit-input, .edit-textarea {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--primary, #007bff);
  border-radius: 6px;
  font-size: 14px;
  box-sizing: border-box;
  background: var(--surface, #fff);
  color: var(--text, #333);
}

.edit-input:focus, .edit-textarea:focus {
  outline: none;
  box-shadow: 0 0 0 2px rgba(0, 123, 255, 0.2);
}

.edit-textarea {
  resize: vertical;
  min-height: 60px;
}

.action-buttons {
  display: flex;
  justify-content: center;
  margin: 20px 0;
}

.primary-button {
  padding: 10px 20px;
  background-color: var(--primary, #007bff);
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 16px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.primary-button:hover:not(:disabled) {
  background-color: var(--primary-dark, #0069d9);
}

.primary-button:disabled {
  background-color: var(--muted, #ccc);
  cursor: not-allowed;
}

.logs-section h3 {
  margin-bottom: 15px;
}

.log-content {
  background-color: var(--surface-soft, #f5f7fa);
  border: 1px solid var(--line, #e1e5e9);
  border-radius: 6px;
  padding: 15px;
  max-height: 200px;
  overflow-y: auto;
}

.log-item {
  margin-bottom: 8px;
  font-size: 14px;
}

.log-time {
  color: var(--muted-dark, #757575);
  margin-right: 10px;
}

.log-message {
  color: var(--text, #333);
}

.message {
  padding: 12px 20px;
  margin: 20px 0;
  border-radius: 6px;
  text-align: center;
}

.message.success {
  background-color: var(--success-light, #e8f5e9);
  color: var(--success-dark, #2e7d32);
  border: 1px solid var(--success, #4caf50);
}

.message.error {
  background-color: var(--error-light, #ffebee);
  color: var(--error-dark, #c62828);
  border: 1px solid var(--error, #f44336);
}

.message.info {
  background-color: var(--info-light, #e1f5fe);
  color: var(--info-dark, #0277bd);
  border: 1px solid var(--info, #03a9f4);
}

@media (max-width: 768px) {
  .result-cards {
    grid-template-columns: 1fr;
  }
  
  .result-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }
  
  .card-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }
  
  .action-buttons {
    flex-direction: column;
    align-items: center;
  }
  
  .primary-button {
    width: 100%;
    max-width: 300px;
  }
  
  .customer-info {
    margin: 15px 0;
    padding: 10px;
    background-color: #f8f9fa;
    border-radius: 4px;
  }
  
  .customer-info label {
    display: block;
    font-weight: bold;
    margin-bottom: 5px;
  }
  
  .customer-display {
    padding: 5px 10px;
    background-color: #e9ecef;
    border-radius: 4px;
    font-weight: normal;
  }
  
  .customer-warning {
    margin: 15px 0;
    padding: 10px;
    background-color: #fff3cd;
    border: 1px solid #ffeaa7;
    border-radius: 4px;
    color: #856404;
  }

  .pipeline-steps {
    flex-wrap: wrap;
    gap: 8px;
  }

  .step-connector {
    width: 20px;
  }
}
</style>