<template>
  <div class="app">
    <header class="header">
      <div class="container">
        <h1>📦 Community Archival System</h1>
        <p class="subtitle">Decentralized storage with cryptographic proofs</p>
      </div>
    </header>

    <main class="container main-content">
      <!-- Status Dashboard -->
      <section class="status-section">
        <h2>System Status</h2>
        <div class="status-grid">
          <div class="status-card">
            <div class="status-label">Pending Files</div>
            <div class="status-value">{{ status.pending_files || 0 }}</div>
            <div class="status-sublabel">{{ formatBytes(status.pending_size || 0) }}</div>
          </div>
          <div class="status-card">
            <div class="status-label">Total Commits</div>
            <div class="status-value">{{ status.total_commits || 0 }}</div>
            <div class="status-sublabel">Archived batches</div>
          </div>
          <div class="status-card">
            <div class="status-label">Latest Commit</div>
            <div class="status-value" style="font-size: 0.9rem;">
              {{ status.latest_commit ? status.latest_commit.id.substring(0, 19) : 'None' }}
            </div>
            <div class="status-sublabel">
              {{ status.latest_commit ? status.latest_commit.leaf_count + ' files' : '-' }}
            </div>
          </div>
        </div>
      </section>

      <!-- Upload Section -->
      <section class="upload-section">
        <h2>Upload Files</h2>
        <div
          class="dropzone"
          :class="{ 'dropzone-active': isDragging }"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="handleDrop"
          @click="triggerFileInput"
        >
          <input
            ref="fileInput"
            type="file"
            multiple
            @change="handleFileSelect"
            style="display: none"
          />
          <div class="dropzone-content">
            <svg class="upload-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />
            </svg>
            <p class="dropzone-text">Drag & drop files here or click to browse</p>
            <p class="dropzone-subtext">Files will be cataloged and archived to IPFS cluster</p>
          </div>
        </div>

        <div v-if="uploads.length > 0" class="uploads-list">
          <h3>Recent Uploads</h3>
          <div v-for="upload in uploads" :key="upload.filename" class="upload-item">
            <span class="upload-filename">{{ upload.filename }}</span>
            <span class="upload-size">{{ formatBytes(upload.size) }}</span>
            <span class="upload-status" :class="upload.status">{{ upload.status }}</span>
          </div>
        </div>
      </section>

      <!-- Actions Section -->
      <section class="actions-section">
        <h2>Archival Actions</h2>
        <div class="actions-grid">
          <button @click="runCatalog" :disabled="isProcessing" class="btn btn-primary">
            📋 Run Catalog
            <span class="btn-subtitle">Scan uploaded files</span>
          </button>
          <button @click="runArchive" :disabled="isProcessing" class="btn btn-primary">
            📦 Run Archive
            <span class="btn-subtitle">Create commit & archive to IPFS</span>
          </button>
        </div>
        <div v-if="actionResult" class="action-result" :class="actionResult.type">
          {{ actionResult.message }}
        </div>
      </section>

      <!-- Files List -->
      <section class="files-section">
        <div class="section-header">
          <h2>Cataloged Files</h2>
          <button @click="toggleArchivedOnly" class="btn btn-small">
            {{ archivedOnly ? '📁 Show All' : '✅ Show Archived Only' }}
          </button>
        </div>
        <div class="files-list">
          <div v-if="files.length === 0" class="empty-state">
            No files cataloged yet. Upload files and run catalog to see them here.
          </div>
          <div v-for="file in files" :key="file.path" class="file-item">
            <div class="file-main">
              <span class="file-path">{{ file.path }}</span>
              <span class="file-size">{{ formatBytes(file.size) }}</span>
            </div>
            <div class="file-meta">
              <span v-if="file.cid_enc" class="file-cid">CID: {{ file.cid_enc.substring(0, 20) }}...</span>
              <span v-if="file.commit_id" class="file-commit">Commit: {{ file.commit_id.substring(0, 19) }}</span>
              <span v-if="!file.cid_enc" class="file-status pending">⏳ Pending</span>
              <span v-else class="file-status archived">✅ Archived</span>
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<script>
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default {
  name: 'App',
  data() {
    return {
      status: {},
      files: [],
      uploads: [],
      isDragging: false,
      isProcessing: false,
      actionResult: null,
      archivedOnly: false,
    }
  },
  mounted() {
    this.loadStatus()
    this.loadFiles()
    // Auto-refresh every 5 seconds
    setInterval(() => {
      this.loadStatus()
      this.loadFiles()
    }, 5000)
  },
  methods: {
    async loadStatus() {
      try {
        const response = await axios.get(`${API_URL}/status`)
        this.status = response.data
      } catch (error) {
        console.error('Failed to load status:', error)
      }
    },
    async loadFiles() {
      try {
        const response = await axios.get(`${API_URL}/files`, {
          params: {
            limit: 100,
            archived_only: this.archivedOnly
          }
        })
        this.files = response.data.files
      } catch (error) {
        console.error('Failed to load files:', error)
      }
    },
    triggerFileInput() {
      this.$refs.fileInput.click()
    },
    handleFileSelect(event) {
      this.uploadFiles(event.target.files)
    },
    handleDrop(event) {
      this.isDragging = false
      this.uploadFiles(event.dataTransfer.files)
    },
    async uploadFiles(fileList) {
      for (const file of fileList) {
        const upload = {
          filename: file.name,
          size: file.size,
          status: 'uploading'
        }
        this.uploads.unshift(upload)

        try {
          const formData = new FormData()
          formData.append('file', file)

          await axios.post(`${API_URL}/upload`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
          })

          upload.status = 'success'
          this.loadStatus()
        } catch (error) {
          upload.status = 'error'
          console.error('Upload failed:', error)
        }
      }
    },
    async runCatalog() {
      this.isProcessing = true
      this.actionResult = null
      try {
        const response = await axios.post(`${API_URL}/catalog`)
        this.actionResult = {
          type: 'success',
          message: response.data.message
        }
        await this.loadStatus()
        await this.loadFiles()
      } catch (error) {
        this.actionResult = {
          type: 'error',
          message: 'Catalog failed: ' + error.message
        }
      } finally {
        this.isProcessing = false
      }
    },
    async runArchive() {
      this.isProcessing = true
      this.actionResult = null
      try {
        const response = await axios.post(`${API_URL}/archive`)
        this.actionResult = {
          type: 'success',
          message: response.data.message
        }
        await this.loadStatus()
        await this.loadFiles()
      } catch (error) {
        this.actionResult = {
          type: 'error',
          message: 'Archive failed: ' + error.message
        }
      } finally {
        this.isProcessing = false
      }
    },
    toggleArchivedOnly() {
      this.archivedOnly = !this.archivedOnly
      this.loadFiles()
    },
    formatBytes(bytes) {
      if (bytes === 0) return '0 B'
      const k = 1024
      const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
      const i = Math.floor(Math.log(bytes) / Math.log(k))
      return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
    }
  }
}
</script>

<style scoped>
.app {
  min-height: 100vh;
  background: #f5f5f5;
}

.header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 2rem 0;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
}

.header h1 {
  font-size: 2rem;
  margin-bottom: 0.5rem;
}

.subtitle {
  opacity: 0.9;
  font-size: 1rem;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 1rem;
}

.main-content {
  padding: 2rem 1rem;
}

section {
  background: white;
  border-radius: 8px;
  padding: 1.5rem;
  margin-bottom: 2rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

section h2 {
  margin-bottom: 1rem;
  color: #333;
  font-size: 1.5rem;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
}

.status-card {
  padding: 1rem;
  background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%);
  border-radius: 6px;
  text-align: center;
}

.status-label {
  font-size: 0.875rem;
  color: #666;
  margin-bottom: 0.5rem;
}

.status-value {
  font-size: 2rem;
  font-weight: bold;
  color: #667eea;
  margin-bottom: 0.25rem;
}

.status-sublabel {
  font-size: 0.75rem;
  color: #999;
}

.dropzone {
  border: 2px dashed #ccc;
  border-radius: 8px;
  padding: 3rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s;
}

.dropzone:hover, .dropzone-active {
  border-color: #667eea;
  background: #667eea05;
}

.upload-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto 1rem;
  color: #667eea;
}

.dropzone-text {
  font-size: 1.125rem;
  color: #333;
  margin-bottom: 0.5rem;
}

.dropzone-subtext {
  font-size: 0.875rem;
  color: #666;
}

.uploads-list {
  margin-top: 1.5rem;
}

.uploads-list h3 {
  font-size: 1rem;
  margin-bottom: 1rem;
  color: #666;
}

.upload-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem;
  background: #f8f8f8;
  border-radius: 4px;
  margin-bottom: 0.5rem;
}

.upload-filename {
  flex: 1;
  font-weight: 500;
}

.upload-size {
  color: #666;
  font-size: 0.875rem;
}

.upload-status {
  padding: 0.25rem 0.75rem;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 500;
}

.upload-status.uploading {
  background: #ffc107;
  color: white;
}

.upload-status.success {
  background: #4caf50;
  color: white;
}

.upload-status.error {
  background: #f44336;
  color: white;
}

.actions-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
}

.btn {
  padding: 1rem 1.5rem;
  border: none;
  border-radius: 6px;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-subtitle {
  font-size: 0.75rem;
  opacity: 0.9;
}

.btn-small {
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  background: #f0f0f0;
  color: #333;
}

.btn-small:hover {
  background: #e0e0e0;
}

.action-result {
  margin-top: 1rem;
  padding: 1rem;
  border-radius: 4px;
  font-size: 0.875rem;
}

.action-result.success {
  background: #4caf5020;
  color: #2e7d32;
  border: 1px solid #4caf50;
}

.action-result.error {
  background: #f4433620;
  color: #c62828;
  border: 1px solid #f44336;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.files-list {
  max-height: 600px;
  overflow-y: auto;
}

.empty-state {
  text-align: center;
  padding: 3rem;
  color: #999;
}

.file-item {
  padding: 1rem;
  border-bottom: 1px solid #f0f0f0;
}

.file-item:last-child {
  border-bottom: none;
}

.file-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.file-path {
  font-family: monospace;
  font-size: 0.875rem;
  color: #333;
}

.file-size {
  color: #666;
  font-size: 0.875rem;
}

.file-meta {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
  font-size: 0.75rem;
}

.file-cid, .file-commit {
  font-family: monospace;
  color: #666;
  background: #f8f8f8;
  padding: 0.25rem 0.5rem;
  border-radius: 3px;
}

.file-status {
  padding: 0.25rem 0.5rem;
  border-radius: 3px;
  font-weight: 500;
}

.file-status.pending {
  background: #ffc10720;
  color: #f57c00;
}

.file-status.archived {
  background: #4caf5020;
  color: #2e7d32;
}
</style>
