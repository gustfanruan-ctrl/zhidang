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
          <option value="线上跟进">线上跟进</option>
          <option value="线下跟进">线下跟进</option>
          <option value="内部沟通">内部沟通</option>
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
      // 文件上传相关
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
        // 图片文件：生成预览并设置占位文本
        const reader = new FileReader()
        reader.onload = (e) => {
          this.filePreview = e.target.result
          this.transcriptText = `[图片上传: ${file.name}]`
          this.showMessage('图片上传成功，请确认后生成', 'success')
          this.currentStep = 1
        }
        reader.onerror = () => {
          this.showMessage('读取图片文件失败', 'error')
        }
        reader.readAsDataURL(file)
      }
    },

    removeFile() {
      this.uploadedFile = null
      this.filePreview = null
      this.transcriptText = ''
      this.$refs.fileInput.value = ''
    },
    // --- 文件上传方法结束 ---

    async loadTagTree() {
      try {
        const response = await api.get('/api/v1/review/tags')
        this.tagTree = response.data
      } catch (error) {
        this.showMessage('加载跟进标签失败', 'error')
      }
    },

    async loadConfig() {
      try {
        const response = await api.get('/api/v1/admin/config')
        // admin config 返回的是扁平结构
        this.config.review_entry_id = response.data.main_entry_id || '670a28334883adafb152a869'
      } catch (error) {
        // 使用默认值
      }
    },
    
    async generateReview() {
      if (!this.canGenerate) {
        this.showMessage('请先在顶部选择客户并输入转写内容', 'error')
        return
      }

      this.generating = true
      this.currentStep = 2

      try {
        const response = await api.post('/api/v1/review/generate', {
          transcript_text: this.transcriptText,
          company_id: this.companyId,
          company_name: this.companyName
        })

        if (response.data.error) {
          this.showMessage(`生成失败: ${response.data.error}`, 'error')
          this.currentStep = 1
        } else {
          this.reviewData = response.data
          // 为新生成的数据添加空的标签
          if (!this.reviewData.genjin_tags) {
            this.reviewData.genjin_tags = []
          }
          this.showMessage('跟进记录生成成功', 'success')
          this.currentStep = 3
        }
      } catch (error) {
        this.showMessage('生成跟进记录失败', 'error')
        this.currentStep = 1
      } finally {
        this.generating = false
      }
    },
    
    addTag() {
      this.reviewData.genjin_tags.push({
        level1: '',
        level2: '',
        level3: ''
      })
    },
    
    removeTag(index) {
      this.reviewData.genjin_tags.splice(index, 1)
    },
    
    updateTagLevel2(index) {
      // 当一级标签变化时，将二级标签清空
      this.reviewData.genjin_tags[index].level2 = ''
      this.reviewData.genjin_tags[index].level3 = ''
    },
    
    updateTagLevel3(index) {
      // 当二级标签变化时，保持三级标签清空
      this.reviewData.genjin_tags[index].level3 = ''
    },
    
    getLevel2Options(level1) {
      if (!level1) return []
      const level1Item = this.tagTree.find(item => item.level1 === level1)
      return level1Item ? level1Item.children : []
    },
    
    getLevel3Options(level1, level2) {
      if (!level1 || !level2) return []
      const level1Item = this.tagTree.find(item => item.level1 === level1)
      if (!level1Item) return []
      const level2Item = level1Item.children.find(item => item.label === level2)
      return level2Item ? level2Item.children : []
    },
    
    async submitReview() {
      if (!this.canSubmit) return
      if (this.submitting) return

      this.submitting = true
      this.currentStep = 4

      try {
        const payload = {
          ...this.reviewData,
          com_name: this.companyName,
          comid: this.companyId
        }

        const response = await api.post('/api/v1/review/submit', payload)
        this.showMessage('跟进记录已成功提交到简道云', 'success')
      } catch (error) {
        this.showMessage('提交到简道云失败', 'error')
        this.currentStep = 3
      } finally {
        this.submitting = false
      }
    },
    
    toggleAdvancedSettings() {
      this.showAdvanced = !this.showAdvanced
    },
    
    async saveConfig() {
      try {
        await api.put('/api/v1/admin/config', {
          jiandaoyun: {
            review_entry_id: this.config.review_entry_id
          },
          review_system_prompt: this.config.review_system_prompt
        })
        this.showMessage('配置保存成功', 'success')
      } catch (error) {
        this.showMessage('保存配置失败', 'error')
      }
    },
    
    showMessage(msg, type) {
      this.message = msg
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
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.review-header {
  margin-bottom: 30px;
  text-align: center;
}

.review-input-section {
  margin-bottom: 30px;
  padding: 20px;
  border: 1px solid #eee;
  border-radius: 5px;
}

/* 步骤进度指示器 */
.step-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 30px;
  padding: 0 20px;
}

.step {
  display: flex;
  flex-direction: column;
  align-items: center;
  color: #999;
}

.step.active {
  color: #007bff;
}

.step.current .step-number {
  background-color: #007bff;
  color: white;
  border-color: #007bff;
}

.step-number {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 2px solid #ccc;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  margin-bottom: 5px;
  background-color: white;
}

.step.active .step-number {
  border-color: #007bff;
  color: #007bff;
}

.step.current .step-number {
  color: white;
}

.step-label {
  font-size: 12px;
}

.step-line {
  flex: 1;
  height: 2px;
  background-color: #ccc;
  margin: 0 10px;
  margin-bottom: 20px;
  max-width: 80px;
}

.step-line.active {
  background-color: #007bff;
}

/* 文件上传区域 */
.upload-area-wrapper {
  flex: 1;
}

.upload-area {
  border: 2px dashed #ccc;
  border-radius: 8px;
  padding: 30px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
  background-color: #fafafa;
}

.upload-area:hover {
  border-color: #007bff;
  background-color: #f0f8ff;
}

.upload-area.drag-over {
  border-color: #007bff;
  background-color: #e6f2ff;
}

.upload-area.has-file {
  border-style: solid;
  border-color: #28a745;
  background-color: #f0fff4;
  padding: 15px 30px;
}

.upload-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.upload-icon {
  font-size: 36px;
  color: #999;
  line-height: 1;
}

.upload-text {
  font-size: 14px;
  color: #666;
}

.upload-hint {
  font-size: 12px;
  color: #999;
}

.file-info {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 15px;
}

.file-name {
  font-size: 14px;
  color: #333;
  font-weight: 500;
}

.remove-file-btn {
  padding: 4px 12px;
  font-size: 12px;
  background-color: #dc3545;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.remove-file-btn:hover {
  background-color: #c82333;
}

/* 图片预览 */
.image-preview {
  margin-top: 15px;
  border: 1px solid #eee;
  border-radius: 8px;
  padding: 10px;
  background-color: #fafafa;
  text-align: center;
}

.image-preview img {
  max-width: 100%;
  max-height: 300px;
  border-radius: 4px;
}

.review-preview-section {
  margin-bottom: 30px;
  padding: 20px;
  border: 1px solid #eee;
  border-radius: 5px;
}

.advanced-settings {
  margin-bottom: 30px;
  padding: 20px;
  border: 1px solid #eee;
  border-radius: 5px;
}

.toggle-btn {
  padding: 8px 15px;
  background-color: #f8f9fa;
  border: 1px solid #dee2e6;
  border-radius: 4px;
  cursor: pointer;
  margin-bottom: 15px;
}

.settings-content h3 {
  margin-top: 0;
}

.form-row {
  margin-bottom: 15px;
  display: flex;
  align-items: flex-start;
}

.form-row label {
  width: 150px;
  margin-right: 15px;
  font-weight: bold;
  margin-top: 5px;
  flex-shrink: 0;
}

.form-row input,
.form-row select,
.form-row textarea {
  flex: 1;
  padding: 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
  box-sizing: border-box;
}

.form-row input[type="radio"] {
  width: auto;
  margin-right: 10px;
}

.radio-group {
  display: flex;
  align-items: center;
}

.radio-group label {
  margin-right: 20px;
  display: flex;
  align-items: center;
  cursor: pointer;
}

.radio-group input[type="radio"] {
  margin-right: 5px;
}

.tag-table table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 10px;
}

.tag-table th,
.tag-table td {
  border: 1px solid #ddd;
  padding: 8px;
  text-align: left;
}

.tag-table th {
  background-color: #f2f2f2;
}

.tag-table select {
  width: 100%;
}

.tag-table button {
  padding: 4px 8px;
  font-size: 12px;
}

.tag-table button {
  background-color: #dc3545;
  color: white;
  border: none;
  border-radius: 3px;
  cursor: pointer;
}

.tag-table button:hover {
  background-color: #c82333;
}

button {
  padding: 10px 20px;
  background-color: #007bff;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

button:disabled {
  background-color: #ccc;
  cursor: not-allowed;
}

button.loading {
  opacity: 0.7;
}

button.submit-btn {
  background-color: #28a745;
}

button.submit-btn:hover {
  background-color: #218838;
}

button.save-config-btn {
  background-color: #6c757d;
}

button.save-config-btn:hover {
  background-color: #5a6268;
}

.message {
  padding: 10px;
  margin-top: 20px;
  border-radius: 4px;
  text-align: center;
}

.message.success {
  background-color: #d4edda;
  color: #155724;
  border: 1px solid #c3e6cb;
}

.message.error {
  background-color: #f8d7da;
  color: #721c24;
  border: 1px solid #f5c6cb;
}

.message.info {
  background-color: #d1ecf1;
  color: #0c5460;
  border: 1px solid #bee5eb;
}

@media (max-width: 768px) {
  .form-row {
    flex-direction: column;
  }
  
  .form-row label {
    width: 100%;
    margin-bottom: 5px;
  }
}
</style>