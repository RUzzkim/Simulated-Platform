import { createApp } from 'vue'
import './assets/tailwind.css'
import App from './App.vue'
import router, { redirectToLogin } from './router'
import { setUnauthorizedHandler } from './api/request'

setUnauthorizedHandler(redirectToLogin)

createApp(App).use(router).mount('#app')