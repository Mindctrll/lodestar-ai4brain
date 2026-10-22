import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './app/App'
import '@fontsource-variable/schibsted-grotesk'
import '@fontsource-variable/jetbrains-mono'
import './index.css'
import './games/games.css'

const root = document.getElementById('root')
if (!root) throw new Error('Missing #root element')

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
