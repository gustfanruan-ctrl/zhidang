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
    return raw ? normalizeCustomer(JSON.parse(raw)) : null
  } catch {
    return null
  }
}

function normalizeCustomer(customer) {
  if (!customer || typeof customer !== 'object') return null
  const companyName = String(
    customer.company_name
    || customer.comname_01
    || customer.com_name
    || customer['客户名称']
    || customer['企业名称']
    || customer['公司名称']
    || ''
  ).trim()
  const comName = String(customer.com_name || companyName || '').trim()
  const comId = String(customer.com_id || customer.customer_com_id || '').trim()
  const companyId = String(customer.company_id || customer._id || customer.id || comId || '').trim()
  return {
    ...customer,
    company_id: companyId,
    company_name: companyName,
    com_name: comName,
    com_id: comId,
  }
}

function normalizeCustomers(customers) {
  return (customers || []).map(normalizeCustomer).filter(Boolean)
}

function persistLegacyCustomerId(customer) {
  const value = String(customer?.company_id || customer?.com_id || '').trim()
  if (value) {
    localStorage.setItem('zhidang_company_id', value)
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
        this.customers = normalizeCustomers(parsed.customers)
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
      this.customers = normalizeCustomers(data.customers)
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
      data.customers = normalizeCustomers(data.customers)
      return data
    },
    async switchCustomer(customer, trigger = 'manual') {
      const normalized = normalizeCustomer(customer)
      if (!normalized) return
      const from = this.currentCustomer?.company_id || null
      this.currentCustomer = normalized
      localStorage.setItem('zhidang_current_customer', JSON.stringify(normalized))
      persistLegacyCustomerId(normalized)
      this.resetVersion += 1
      await api.post('/api/v1/customers/switch', {
        company_id_from: from,
        company_id_to: normalized.company_id,
        trigger,
      }).catch(() => {})
    },
    hydrateCurrentCustomer() {
      const stored = readStoredCustomer()
      if (stored) {
        this.currentCustomer = stored
        persistLegacyCustomerId(stored)
      } else {
        this.currentCustomer = null
      }
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
