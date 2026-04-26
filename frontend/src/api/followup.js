/**
 * US-2 跟进记录生成 · 前端 API 层
 */
import { api } from '../api'

export const followupApi = {
  /**
   * 从截图或文字生成跟进记录
   */
  generate(payload) {
    return api.post('/api/v1/followup/generate', payload)
  },

  /**
   * 提交审核后的跟进记录到简道云
   */
  submit(payload) {
    return api.post('/api/v1/followup/submit', payload)
  },

  /**
   * 获取跟进标签三级体系
   */
  getTags() {
    return api.get('/api/v1/followup/tags')
  },

  /**
   * 获取商务行为和行为目的枚举值
   */
  getEnums() {
    return api.get('/api/v1/followup/enums')
  },
}
