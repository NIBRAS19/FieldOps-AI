import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import './style.css'
import './store'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/overview' },
    { path: '/overview', component: () => import('./views/OverviewView.vue'), meta: { title: 'Overview' } },
    { path: '/tickets', component: () => import('./views/TicketsView.vue'), meta: { title: 'Tickets' } },
    { path: '/tickets/:id', component: () => import('./views/TicketView.vue'), meta: { title: 'Ticket', nav: '/tickets' } },
    { path: '/reviews', component: () => import('./views/ReviewsView.vue'), meta: { title: 'Reviews' } },
    { path: '/reviews/:id', component: () => import('./views/ReviewDetailView.vue'), meta: { title: 'Review', nav: '/reviews' } },
    { path: '/runs', component: () => import('./views/RunsView.vue'), meta: { title: 'Runs' } },
    { path: '/runs/:id', component: () => import('./views/RunView.vue'), meta: { title: 'Run', nav: '/runs' } },
    { path: '/knowledge', component: () => import('./views/KnowledgeView.vue'), meta: { title: 'Knowledge' } },
    { path: '/evaluations', component: () => import('./views/EvalsView.vue'), meta: { title: 'Evaluations' } },
    { path: '/audit', component: () => import('./views/AuditView.vue'), meta: { title: 'Audit Log' } },
    { path: '/settings', component: () => import('./views/SettingsView.vue'), meta: { title: 'Settings' } },
    { path: '/tour', component: () => import('./views/TourView.vue'), meta: { title: 'Guided Demo' } },
    { path: '/:pathMatch(.*)*', redirect: '/overview' }
  ]
})
createApp(App).use(router).mount('#app')
