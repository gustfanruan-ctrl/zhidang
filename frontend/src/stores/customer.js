import { defineStore } from 'pinia'
import { api } from '../api'

const CACHE_KEY_PREFIX = 'zhidang_customers_cache_v2'

function cacheKey() {
  const token = localStorage.getItem('zhidang_token')
  if (!token) return CACHE_KEY_PREFIX + '::anon'
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return CACHE_KEY_PREFIX + '::' + (payload.username || payload.user_name || 'anon')
  } catch { return CACHE_KEY_PREFIX + '::anon' }
}

function readStoredCustomer() {
  try {
    const raw = localStorage.getItem('zhidang_current_customer')
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export const useCustomerStore = defineStore('customer', {
  state: () => ({
    customers: [],
    currentCustomer: readStoredCustomer(),
    cacheAt: null,
    lastMode: '',
    lastWarning: '',
    cacheTotal: 0,
    resetVersion: 0,
  }),
  actions: {
    loadCache() {
      try {
        const raw = localStorage.getItem(cacheKey())
        if (!raw) return false
        const parsed = JSON.parse(raw)
        if (!parsed?.cacheAt || Date.now() - new Date(parsed.cacheAt).getTime() > CACHE_TTL_MS) return false
        this.customers = parsed.customers || []
        this.cacheAt = parsed.cacheAt
        return true
      } catch {
        return false
      }
    },
    saveCache() {
      localStorage.setItem(cacheKey(), JSON.stringify({ customers: this.customers, cacheAt: this.cacheAt }))
    },
    async fetchCustomers(force = false, keyword = '') {
      const normalizedKeyword = (keyword || '').trim()
      // 只有当缓存非空时才允许命中缓存（避免缓存空结果）
      if (!force && !normalizedKeyword && this.loadCache() && this.customers.length > 0) return
      const params = normalizedKeyword
        ? { keyword: normalizedKeyword, limit: 200 }
        : { limit: 500 }
      const { data } = await api.get('/api/v1/customers/list', { params })
      this.customers = data.customers || []
      this.cacheAt = data.cached_at || new Date().toISOString()
      this.lastMode = data.mode || ''
      this.lastWarning = data.warning || ''
      this.cacheTotal = Number(data.cache_total || this.customers.length || 0)
      if (!normalizedKeyword) {
        this.saveCache()
      }
      return data
    },
    async searchCustomersRemote(keyword, limit = 50) {
      // 从后端本地缓存索引中模糊搜索客户
      const { data } = await api.get('/api/v1/customers/search', {
        params: { keyword: keyword.trim(), limit }
      })
      return data
    },
    async switchCustomer(customer, trigger = 'manual') {
      const from = this.currentCustomer?.company_id || null
      this.currentCustomer = customer
      localStorage.setItem('zhidang_current_customer', JSON.stringify(customer))
      this.resetVersion += 1
      await api.post('/api/v1/customers/switch', {
        company_id_from: from,
        company_id_to: customer.company_id,
        trigger,
      }).catch(() => {})
    },
    hydrateCurrentCustomer() {
      this.currentCustomer = readStoredCustomer()
    },
    clearContext() {
      this.currentCustomer = null
      localStorage.removeItem('zhidang_current_customer')
      this.resetVersion += 1
    },
    clearCache() {
      this.customers = []
      this.cacheAt = null
      localStorage.removeItem(cacheKey())
    },
  },
})
