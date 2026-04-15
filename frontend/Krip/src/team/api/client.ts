import axios from 'axios'
 
const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  timeout: 10000,
})
 
const TEST_TOKEN = 'krip3accesss1secret2token0'

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('accessToken') || TEST_TOKEN
  config.headers.Authorization = `Bearer ${token}`
  return config
})
 
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('accessToken')
    }
    return Promise.reject(error)
  }
)
 
export default client
