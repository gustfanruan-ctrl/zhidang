<template>
  <div class="review-page">
    <!-- 顶部输入区 -->
    <div class="review-header">
      <h1>跟进记录生成</h1>
    </div>

    <!-- 步骤进度指示器 -->
    <div class="step-indicator">
      <div class="step" :class="{ active: currentStep >= 1, current: currentStep === 1 }">
        <div class="step-number">1</div>
        <div class="step-label">上传文件</div>
      </div>
      <div class="step-line" :class="{ active: currentStep >= 2 }"></div>
      <div class="step" :class="{ active: currentStep >= 2, current: currentStep === 2 }">
        <div class="step-number">2</div>
        <div class="step-label">LLM生成</div>
      </div>
      <div class="step-line" :class="{ active: currentStep >= 3 }"></div>
      <div class="step" :class="{ active: currentStep >= 3, current: currentStep === 3 }">
        <div class="step-number">3</div>
        <div class="step-label">审核编辑</div>
      </div>
      <div class="step-line" :class="{ active: currentStep >= 4 }"></div>
      <div class="step" :class="{ active: currentStep >= 4, current: currentStep === 4 }">
        <div class="step-number">4</div>
        <div class="step-label">提交</div>
      </div>
    </div>

    <div class="review-input-section">
      <!-- 当前选中的客户名称 -->
      <div class="form-row">
        <label>当前客户：</label>
        <input type="text" :value="companyName" readonly />
      </div>

      <!-- 文件上传区域 -->
      <div class="form-row">
        <label>上传文件：</label>
        <div class="upload-area-wrapper">
          <div
            class="upload-area"
            :class="{ 'drag-over': isDragOver, 'has-file': uploadedFile }"
            @dragover.prevent="onDragOver"
            @dragleave.prevent="onDragLeave"
            @drop.prevent="onFileDrop"
            @click="triggerFileInput"
          >
            <input
              ref="fileInput"
              type="file"
              accept=".txt,.jpg,.jpeg,.png,.webp"
              style="display: none"
              @change="onFileSelect"
            />
            <div v-if="!uploadedFile" class="upload-placeholder">
              <div class="upload-icon">+</div>
              <div class="upload-text">点击或拖拽上传文件</div>
              <div class="upload-hint">支持 .txt, .jpg, .jpeg, .png, .webp</div>
            </div>
            <div v-else class="file-info">
              <div class="file-name">{{ uploadedFile.name }}</div>
              <button class="remove-file-btn" @click.stop="removeFile">移除</button>
            </div>
          </div>

          <!-- 图片预览 -->
          <div v-if="filePreview && isImageFile" class="image-preview">
            <img :src="filePreview" alt="预览" />
          </div>
        </div>
      </div>

      <!-- 转写内容 -->
      <div class="form-row">
        <label>转写内容：</label>
        <textarea
          v-model="transcriptText"
          placeholder="粘贴会议转写内容，或上传 txt 文件自动填充..."
          rows="10"
        ></textarea>
      </div>

      <!-- 生成按钮 -->
      <div class="form-row">
        <button @click="generateReview" :disabled="!canGenerate || generating" :class="{ 'loading': generating }">
          {{ generating ? '生成中...' : '生成跟进记录' }}
        </button>
      </div>
    </div>
    
    <!-- 中部预览编辑区 -->
    <div v-if="reviewData" class="review-preview-section">
      <h2>跟进记录预览</h2>
      
      <!-- 跟进类型 -->
      <div class="form-row">
        <label>跟进类型：</label>
        <select v-model="reviewData.follow_type">
          <option value="线上沟通">线上沟通</option>
          <option value="电话沟通">电话沟通</option>
          <option value="邮件跟进">邮件跟进</option>
          <option value="现场拜访">现场拜访</option>
          <option value="问题处理">问题处理</option>
          <option value="需求跟进">需求跟进</option>
          <option value="资料发送">资料发送</option>
          <option value="其他">其他</option>
        </select>
      </div>
      
      <!-- 跟进日期 -->
      <div class="form-row">
        <label>跟进日期：</label>
        <input type="date" v-model="reviewData.review_date">
      </div>
      
      <!-- 跟进记录 -->
      <div class="form-row">
        <label>跟进记录：</label>
        <textarea v-model="reviewData.review_record" rows="15"></textarea>
      </div>
      
      <!-- 联系人 -->
      <div class="form-row">
        <label>客户方参与人：</label>
        <input type="text" v-model="reviewData.contact_names" placeholder="如：张经理（采购部）">
      </div>
      
      <!-- 推送前方 -->
      <div class="form-row">
        <label>推送前方：</label>
        <div class="radio-group">
          <label><input type="radio" v-model="reviewData.if_tuisong" value="是"> 是</label>
          <label><input type="radio" v-model="reviewData.if_tuisong" value="否"> 否</label>
        </div>
      </div>
      
      <!-- 跟进标签 -->
      <div class="form-row">
        <label>跟进标签：</label>
        <div class="tag-table">
          <table>
            <thead>
              <tr>
                <th>一级标签</th>
                <th>二级标签</th>
                <th>三级标签</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(tag, index) in reviewData.genjin_tags" :key="index">
                <td>
                  <select v-model="tag.level1" @change="updateTagLevel2(index)">
                    <option value="">请选择</option>
                    <option v-for="level1 in tagTree" :key="level1.level1" :value="level1.level1">
                      {{ level1.level1 }}
                    </option>
                  </select>
                </td>
                <td>
                  <select v-model="tag.level2" @change="updateTagLevel3(index)" :disabled="!tag.level1">
                    <option value="">请选择</option>
                    <option 
                      v-for="level2 in getLevel2Options(tag.level1)" 
                      :key="level2.label" 
                      :value="level2.label"
                    >
                      {{ level2.label }}
                    </option>
                  </select>
                </td>
                <td>
                  <select v-model="tag.level3" :disabled="!tag.level2">
                    <option value="">请选择</option>
                    <option 
                      v-for="level3 in getLevel3Options(tag.level1, tag.level2)" 
                      :key="level3" 
                      :value="level3"
                    >
                      {{ level3 }}
                    </option>
                  </select>
                </td>
                <td>
                  <button @click="removeTag(index)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
          <button @click="addTag">新增标签</button>
        </div>
      </div>
      
      <!-- 提交按钮 -->
      <div class="form-row">
        <button @click="submitReview" :disabled="!canSubmit || submitting" class="submit-btn">{{ submitting ? '提交中...' : '提交到简道云' }}</button>
      </div>
    </div>
    
    <!-- 提示信息 -->
    <div v-if="message" class="message" :class="messageType">
      {{ message }}
    </div>
  </div>
</template>

<script>
import { api } from '../api'
import { useCustomerStore } from '../stores/customer'

export default {
  name: 'ReviewPage',
  data() {
    return {
      // 页面数据
      transcriptText: '',
      reviewData: null,
      tagTree: [],
      config: {
        review_entry_id: '670a28334883adafb152a869',
        review_system_prompt: ''
      },
      generating: false,
      submitting: false,
      showAdvanced: false,
      message: '',
      messageType: 'info',
      // 文延上传相关
      uploadedFile: null,
      filePreview: null,
      isDragOver: false,
      currentStep: 1
    }
  },
  computed: {
    companyId() {
      const store = useCustomerStore()
      return store.currentCustomer?.company_id || ''
    },
    companyName() {
      const store = useCustomerStore()
      return store.currentCustomer?.company_name || ''
    },
    canGenerate() {
      return this.transcriptText.trim() && this.companyName
    },
    isImageFile() {
      if (!this.uploadedFile) return false
      const ext = this.uploadedFile.name.split('.').pop().toLowerCase()
      return ['jpg', 'jpeg', 'png', 'webp'].includes(ext)
    },
    canSubmit() {
      return this.reviewData && this.reviewData.follow_type && this.reviewData.review_date && this.reviewData.review_record
    }
  },
  async mounted() {
    await this.loadTagTree()
    await this.loadConfig()
  },
  methods: {
    // --- 文件上传相关方法 ---
    triggerFileInput() {
      this.$refs.fileInput.click()
    },

    onDragOver(e) {
      this.isDragOver = true
    },

    onDragLeave(e) {
      this.isDragOver = false
    },

    onFileDrop(e) {
      this.isDragOver = false
      const files = e.dataTransfer.files
      if (files.length > 0) {
        this.handleFile(files[0])
      }
    },

    onFileSelect(e) {
      const files = e.target.files
      if (files.length > 0) {
        this.handleFile(files[0])
      }
    },

    validateFile(file) {
      const allowedTypes = ['.txt', '.jpg', '.jpeg', '.png', '.webp']
      const ext = '.' + file.name.split('.').pop().toLowerCase()
      return allowedTypes.includes(ext)
    },

    handleFile(file) {
      if (!this.validateFile(file)) {
        this.showMessage('不支持的文件类型，请上传 .txt, .jpg, .jpeg, .png, .webp 文件', 'error')
        return
      }

      this.uploadedFile = file
      this.filePreview = null

      const ext = file.name.split('.').pop().toLowerCase()

      if (ext === 'txt') {
        // 读取文本内容
        const reader = new FileReader()
        reader.onload = (e) => {
          this.transcriptText = e.target.result
          this.showMessage('文本文件读取成功', 'success')
          this.currentStep = 1
        }
        reader.onerror = () => {
          this.showMessage('读取文本文件失败', 'error')
        }
        reader.readAsText(file)
      } else {
        // 图片文件：生成预览并设置位文本
        const reader = new FileReader()
        reader.onload = (e) => {
          this.filePreview = e.target.result
          this.transcriptText = `[图片上传: ${file.name}]`
          this.showMessage('图片上传成功，请确认后生成', 'success')
          this.currentStep = 1
        }
        reader.readAsDataURL(file)
      }
    },

    removeFile() {
      this.uploadedFile = null
      this.filePreview = null
      this.transcriptText = ''
      this.currentStep = 1
    },

    // --- 标签劳数据方法 ---
    async loadTagTree() {
      try {
        const response = await api.get('/api/v1/followup/tags')
        // 后端返回 {&#34;使用推进&#34;: {&#34;常态化跟进&#34;: [], ...}}
        // 转为前端需要的 [{level1, children: [{label, children}]}]
        const raw = response.data.tags || {}
        this.tagTree = Object.entries(raw).map(([level1, children]) => ({
          level1,
          children: Object.entries(children).map(([label, subChildren]) => ({
            label,
            children: subChildren || []
          }))
        }))
      } catch (error) {
        console.error('初始化标签失败', error)
        this.tagTree = []
      }
    },

    getLevel2Options(level1) {
      const level1Item = this.tagTree.find(item => item.level1 === level1)
      return level1Item ? level1Item.children : []
    },

    getLevel3Options(level1, level2) {
      const level1Item = this.tagTree.find(item => item.level1 === level1)
      if (!level1Item) return []
      const level2Item = level1Item.children.find(item => item.label === level2)
      return level2Item ? level2Item.children : []
    },

    updateTagLevel2(index) {
      this.reviewData.genjin_tags[index].level2 = ''
      this.reviewData.genjin_tags[index].level3 = ''
    },

    updateTagLevel3(index) {
      this.reviewData.genjin_tags[index].level3 = ''
    },

    addTag() {
      if (!this.reviewData) return
      if (!this.reviewData.genjin_tags) {
        this.reviewData.genjin_tags = []
      }
      this.reviewData.genjin_tags.push({ level1: '', level2: '', level3: '' })
    },

    removeTag(index) {
      this.reviewData.genjin_tags.splice(index, 1)
    },

    // --- 配置方法 ---
    async loadConfig() {
      try {
        const response = await api.get('/api/v1/admin/config')
        if (response.data.field_mappings) {
          this.config = {
            ...this.config,
            ...response.data.field_mappings
          }
        }
      } catch (error) {
        console.error('自定义配置失败', error)
      }
    },

    // --- 生成跟进记录 ---
    async generateReview() {
      if (!this.canGenerate) return

      this.generating = true
      this.message = ''
      this.currentStep = 2

      try {
        const response = await api.post('/api/v1/followup/generate', {
          input_type: this.uploadedFile && this.isImageFile ? 'screenshot' : 'text',
          content: this.transcriptText,
          company_id: this.companyId,
          company_name: this.companyName
        })

        this.reviewData = response.data
        this.currentStep = 3
        this.showMessage('跟进记录生成成功，请审核后提交', 'success')
      } catch (error) {
        console.error('生成失败', error)
        this.showMessage('生成失败：' + (error.response?.data?.detail || error.message), 'error')
        this.currentStep = 1
      } finally {
        this.generating = false
      }
    },

    // --- 提交到简道云 ---
    async submitReview() {
      if (!this.canSubmit) return

      this.submitting = true
      this.message = ''
      this.currentStep = 4

      try {
        const payload = {
          company_id: this.companyId,
          follower: this.reviewData.follower || '',
          follow_type: this.reviewData.follow_type,
          review_date: this.reviewData.review_date,
          review_record: this.reviewData.review_record,
          genjin_tags: this.reviewData.genjin_tags || [],
          if_tuisong: this.reviewData.if_tuisong || '否',
          contname: this.reviewData.contact_names || '',
          contid: '',
          yuqi_id: ''
        }

        await api.post('/api/v1/followup/submit', payload)
        this.showMessage('成功提交到简道云', 'success')
      } catch (error) {
        console.error('提交失败', error)
        this.showMessage('提交失败：' + (error.response?.data?.detail || error.message), 'error')
        this.currentStep = 3
      } finally {
        this.submitting = false
      }
    },

    // --- 关闭方法 ---
    showMessage(text, type = 'info') {
      this.message = text
      this.messageType = type
      setTimeout(() => {
        this.message = ''
      }, 3000)
    }
  }
}
</script>

<style scoped>
.review-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
}

.review-header {
  margin-bottom: 20px;
}

.review-header h1 {
  font-size: 24px;
  color: #333;
}

/* -- 步骤进度指示器 -- */
.step-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 30px;
  padding: 20px 0;
  background: #f8f9fa;
  border-radius: 8px;
}

.step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.step-number {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 18px;
  background: #ddd;
  color: #999;
}

.step.active .step-number {
  background: #4285f4;
  color: white;
}

.step.current .step-number {
  background: #1a73e8;
  color: white;
}

.step-label {
  font-size: 14px;
  color: #999;
}

.step.active .step-label {
  color: #333;
}

.step.current .step-label {
  color: #1a73e8;
  font-weight: bold;
}

.step-line {
  width: 80px;
  height: 2px;
  background: #ddd;
  margin: 0 10px;
}

.step-line.active {
  background: #4285f4;
}

/* -- 输入区 -- */
.review-input-section {
  background: white;
  padding: 24px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  margin-bottom: 24px;
}

.form-row {
  margin-bottom: 16px;
}

.form-row label {
  display: block;
  font-weight: 600;
  margin-bottom: 8px;
  color: #555;
}

.form-row input[type="text"],
.form-row input[type="date"],
.form-row textarea,
.form-row select {
  width: 100%;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
}

.form-row textarea {
  resize: vertical;
  min-height: 120px;
}

/* -- 上传区域 -- */
.upload-area-wrapper {
  display: flex;
  gap: 20px;
  align-items: flex-start;
}

.upload-area {
  flex: 1;
  border: 2px dashed #ccc;
  border-radius: 8px;
  padding: 30px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.3s;
}

.upload-area:hover {
  border-color: #1a73e8;
}

.upload-area.drag-over {
  border-color: #1a73e8;
  background: #e8f0fe;
}

.upload-placeholder {
  color: #999;
}

.upload-icon {
  font-size: 32px;
  margin-bottom: 10px;
}

.upload-text {
  font-size: 16px;
  margin-bottom: 8px;
}

.upload-hint {
  font-size: 12px;
  color: #bbb;
}

.file-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.file-name {
  font-size: 14px;
  color: #333;
}

.remove-file-btn {
  padding: 4px 12px;
  background: #e74c3c;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.image-preview {
  width: 200px;
}

.image-preview img {
  width: 100%;
  border-radius: 8px;
  border: 1px solid #ddd;
}

/* -- 预览编辑区 -- */
.review-preview-section {
  background: white;
  padding: 24px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.review-preview-section h2 {
  margin-bottom: 20px;
  color: #333;
}

/* -- 标签表格 -- */
.tag-table {
  margin-top: 10px;
}

.tag-table table {
  width: 100%;
  border-collapse: collapse;
}

.tag-table th,
.tag-table td {
  padding: 8px 12px;
  border: 1px solid #ddd;
  text-align: left;
}

.tag-table th {
  background: #f5f5f5;
  font-weight: 600;
}

.tag-table select {
  width: 100%;
  padding: 6px;
  border: 1px solid #ddd;
  border-radius: 4px;
}

/* -- 提交按钮 -- */
.subit-btn {
  width: 100%;
  padding: 12px;
  background: #27ae60;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 16px;
  cursor: pointer;
  transition: background 0.3s;
}

.submit-btn:hover:not(:disabled) {
  background: #219a52;
}

.submit-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* -- 提示信息 -- */
.message {
  padding: 12px;
  border-radius: 6px;
  margin-top: 16px;
  font-size: 14px;
}

.message.info {
  background: #e3f2fd;
  color: #1565c0;
}

.message.success {
  background: #e8f5e9;
  color: #2e7d32;
}

.message.error {
  background: #fdecea;
  color: #c62828;
}

/* -- 攻用按钮 -- */
button {
  padding: 8px 20px;
  background: #1a73e8;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}

button:hover:not(:disabled) {
  background: #1557b0;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.radio-group {
  display: flex;
  gap: 20px;
}

.radio-group label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
</style>
