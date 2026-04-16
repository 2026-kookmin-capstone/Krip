import axios from 'axios'
 
const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  timeout: 10000,
})
 
// 테스트용 임시 토큰 (나중에 로그인 flow 완성되면 제거)
const TEST_TOKEN = 'krip3accesss1secret2token0'

// 모든 요청에 자동으로 토큰 붙이기
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('accessToken') || TEST_TOKEN
  config.headers.Authorization = `Bearer ${token}`
  return config
})
 
// 에러 처리
// TODO: 로그인 페이지 합치면 window.location.href = '/login' 다시 활성화
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('accessToken')
      // 로그인 페이지 준비되면 아래 주석 해제
      // window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)
 
export default client