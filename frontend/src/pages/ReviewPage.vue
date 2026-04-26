<template>
  <div class="review-page">
    <!-- 顶部输入区 -->
    <div class="review-header">
      <h1>跟进记录生成</h1>
    </div>
    
    <div class="review-input-section">
      <!-- 当前选中的客户名称 -->
      <div class="form-row">
        <label>当前客户：</label>
        <input type="text" :value="companyName" readonly />
      </div>
      
      <!-- 转写内容 -->
      <div class="form-row">
        <label>转写内容：</label>
        <textarea 
          v-model="transcriptText" 
          placeholder="粘贴会议转写内容..."
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
        <button @click="submitReview" :disabled="!canSubmit" class="submit-btn">提交到简道云</button>
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

export default {
  name: 'ReviewPage',
  data() {
    return {
      // 从路由或全局状态获取的客户信息
      companyId: this.$route.query.company_id || localStorage.getItem('zhidang_company_id') || '',
      companyName: this.$route.query.company_name || localStorage.getItem('zhidang_company_name') || '',
      
      // 页面数据
      transcriptText: '',
      reviewData: null,
      tagTree: [],
      config: {
        review_entry_id: '670a28334883adafb152a869',
        review_system_prompt: ''
      },
      generating: false,
      showAdvanced: false,
      message: '',
      messageType: 'info'
    }
  },
  computed: {
    canGenerate() {
      return this.transcriptText.trim() && this.companyName
    },
    canSubmit() {
      return this.reviewData && 
             this.reviewData.follow_type && 
             this.reviewData.review_date && 
             this.reviewData.review_record
    }
  },
  async mounted() {
    await this.loadTagTree()
    await this.loadConfig()
  },
  methods: {
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
        this.config.review_entry_id = response.data.jiandaoyun.review_entry_id || '670a28334883adafb152a869'
        this.config.review_system_prompt = response.data.review_system_prompt || ''
      } catch (error) {
        // 如果加载失败，使用默认值
      }
    },
    
    async generateReview() {
      if (!this.canGenerate) {
        this.showMessage('请先在顶部选择客户', 'error')
        return
      }
      
      this.generating = true
      
      try {
        const response = await api.post('/api/v1/review/generate', {
          transcript_text: this.transcriptText,
          company_id: this.companyId,
          company_name: this.companyName
        })
        
        if (response.data.error) {
          this.showMessage(`生成失败: ${response.data.error}`, 'error')
        } else {
          this.reviewData = response.data
          // 为新生成的数据添加空的标签
          if (!this.reviewData.genjin_tags) {
            this.reviewData.genjin_tags = []
          }
          this.showMessage('跟进记录生成成功', 'success')
        }
      } catch (error) {
        this.showMessage('生成跟进记录失败', 'error')
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