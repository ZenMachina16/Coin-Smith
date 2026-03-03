import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'
import { readdirSync, copyFileSync, mkdirSync } from 'fs'
import { fileURLToPath } from 'url'
import { dirname } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Copy fixtures into dist/fixtures/ during build
function copyFixturesPlugin() {
  return {
    name: 'copy-fixtures',
    closeBundle() {
      const fixturesDir = resolve(__dirname, '../fixtures')
      const destDir = resolve(__dirname, 'dist/fixtures')
      mkdirSync(destDir, { recursive: true })
      readdirSync(fixturesDir).forEach(f => {
        if (f.endsWith('.json')) {
          copyFileSync(`${fixturesDir}/${f}`, `${destDir}/${f}`)
        }
      })
    }
  }
}

export default defineConfig({
  plugins: [react(), copyFixturesPlugin()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:3000',
      '/fixtures': 'http://127.0.0.1:3000',
    }
  }
})
