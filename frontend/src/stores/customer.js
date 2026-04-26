import { defineStore } from 'pinia'
import { api } from '../api'

const CACHE_KEY = 'zhidang_customers_cache_v1'
const CACHE_TTL_MS = 24 * 60 * 60 * 1000

export const useCustomerStore = defineStore('customer', {
  state: () => ({
    customers: [],
    currentCustomer: null,
    cacheAt: null,
    lastMode: '',
    lastWarning: '',
    cacheTotal: 0,
    resetVersion: 0,
  }),
  actions: {
    loadCache() {
      try {
        const raw = localStorage.getItem(CACHE_KEY)
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
      localStorage.setItem(CACHE_KEY, JSON.stringify({ customers: this.customers, cacheAt: this.cacheAt }))
    },
    async fetchCustomers(force = false, keyword = '') {
      const normalizedKeyword = (keyword || '').trim()
      if (!force && !normalizedKeyword && this.loadCache()) return
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
      try {
        const raw = localStorage.getItem('zhidang_current_customer')
        if (!raw) return
        this.currentCustomer = JSON.parse(raw)
      } catch {
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
      localStorage.removeItem(CACHE_KEY)
    },
  },
})
