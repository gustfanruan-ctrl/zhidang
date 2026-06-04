import { api } from '../api'

export async function getCustomerProfile(companyId) {
  const { data } = await api.get(`/api/v1/customers/${companyId}/profile`)
  return data
}

export async function getYuqiList(companyId) {
  const { data } = await api.get(`/api/v1/customers/${companyId}/yuqi`)
  return data
}

export async function getChangjingList(companyId) {
  const { data } = await api.get(`/api/v1/customers/${companyId}/changjing`)
  return data
}

