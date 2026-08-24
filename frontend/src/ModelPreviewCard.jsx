import { formatBytes, formatCount } from './meshPreview'
import ModelViewport from './ModelViewport'

function CubeIcon() {
  return (
    <svg className="preview-icon" viewBox="0 0 64 64" aria-hidden="true">
      <path
        d="M32 8 54 20v24L32 56 10 44V20L32 8Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
      <path d="M32 8v48M10 20l22 12 22-12" fill="none" stroke="currentColor" strokeWidth="2.2" />
    </svg>
  )
}

function badgeFor({ status, analyzing, backendReady }) {
  if (status === 'loading') return { label: 'Model yükleniyor', tone: 'load' }
  if (analyzing) return { label: 'Analiz ediliyor', tone: 'load' }
  if (backendReady) return { label: 'Hazır', tone: 'ok' }
  if (status === 'error') return { label: 'Önizleme başarısız', tone: 'err' }
  if (status === 'ready') return { label: 'Model yüklendi', tone: 'ok' }
  return { label: 'Model seçilmedi', tone: 'idle' }
}

export default function ModelPreviewCard({
  status = 'idle',
  file = null,
  fileName,
  fileSize,
  triangleCount,
  vertexCount,
  previewUrl,
  errorMessage,
  analyzing = false,
  backendReady = false,
  drag = false,
  onDragOver,
  onDragLeave,
  onDrop,
  onPickFile,
  onViewportReady,
  onViewportError,
}) {
  const badge = badgeFor({ status, analyzing, backendReady })
  const showMeta = status !== 'idle'
  const isBusy = status === 'loading' || analyzing

  return (
    <div
      className={`preview-card drop ${drag ? 'drag' : ''} ${status === 'error' ? 'preview-error' : ''}`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <div className="preview-stage" aria-busy={isBusy}>
        {status === 'idle' && !file ? (
          <div className="preview-empty">
            <CubeIcon />
            <strong>3D model sürükle bırak</strong>
            <span>GLB, GLTF, OBJ, STL veya 3MF</span>
          </div>
        ) : null}

        {file && status !== 'error' ? (
          <>
            <ModelViewport file={file} onReady={onViewportReady} onError={onViewportError} />
            {status === 'loading' ? (
              <div className="preview-skeleton preview-overlay">
                <div className="spinner" />
                <span>Mesh okunuyor…</span>
              </div>
            ) : null}
            {status === 'ready' ? (
              <span className="preview-orbit-hint">Sürükle: döndür · Sağ tık: kaydır · Tekerlek: yakınlaş</span>
            ) : null}
          </>
        ) : null}

        {!file && status === 'loading' ? (
          <div className="preview-skeleton">
            <div className="spinner" />
            <span>Mesh okunuyor…</span>
          </div>
        ) : null}

        {!file && status === 'ready' && previewUrl ? (
          <img className="preview-shot" src={previewUrl} alt={`${fileName || 'Model'} önizlemesi`} />
        ) : null}

        {status === 'error' ? (
          <div className="preview-empty preview-fail">
            <CubeIcon />
            <strong>Önizleme oluşturulamadı</strong>
            <span>{errorMessage || 'Dosya okunamadı veya bozuk.'}</span>
          </div>
        ) : null}

        <span className={`preview-badge ${badge.tone}`}>{badge.label}</span>
      </div>

      <div className="preview-body">
        {showMeta ? (
          <>
            <div className="preview-filename" title={fileName}>
              {fileName || 'model'}
            </div>
            <div className="preview-stats">
              <div>
                <span>Boyut</span>
                <b>{formatBytes(fileSize)}</b>
              </div>
              <div>
                <span>Üçgen</span>
                <b>{isBusy && triangleCount == null ? '…' : formatCount(triangleCount)}</b>
              </div>
              <div>
                <span>Köşe</span>
                <b>{isBusy && vertexCount == null ? '…' : formatCount(vertexCount)}</b>
              </div>
            </div>
          </>
        ) : (
          <p className="preview-hint">Dosya seçince anında önizleme ve temel bilgiler görünür.</p>
        )}

        <div className="row" style={{ justifyContent: 'center' }}>
          <label className="btn btn-primary">
            {showMeta ? 'Başka dosya seç' : 'Dosya seç'}
            <input
              type="file"
              accept=".glb,.gltf,.obj,.stl,.3mf"
              hidden
              onChange={(e) => {
                onPickFile?.(e.target.files?.[0])
                e.target.value = ''
              }}
            />
          </label>
        </div>
      </div>
    </div>
  )
}
