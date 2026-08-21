import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  analyzeMesh,
  createFilament,
  deleteFilament,
  export3mf,
  exportProfile,
  listFilaments,
  recommend,
} from './api'
import ModelPreviewCard from './ModelPreviewCard'
import { renderMeshThumbnail } from './meshPreview'
import './App.css'

const PURPOSES = [
  { id: 'decorative', label: 'Süs / dekor' },
  { id: 'functional', label: 'Fonksiyonel' },
  { id: 'outdoor', label: 'Dış mekan' },
]

const STRENGTHS = [
  { id: 'weak', label: 'Zayıf' },
  { id: 'medium', label: 'Orta' },
  { id: 'strong', label: 'Sağlam' },
]

const DETAIL_LABELS = {
  low: 'Düşük (hızlı basılabilir)',
  medium: 'Orta',
  high: 'Yüksek (yavaş / ince)',
}

const EMPTY_FILAMENT = {
  material: 'PLA',
  color: '',
  brand: '',
  slot: '',
  notes: '',
}

const MESH_EXTS = ['.glb', '.gltf', '.obj', '.stl']

function isSupportedMesh(file) {
  const name = file?.name || ''
  const dot = name.lastIndexOf('.')
  if (dot < 0) return false
  return MESH_EXTS.includes(name.slice(dot).toLowerCase())
}

function formatBox(box) {
  if (!box?.length) return '—'
  return box.map((n) => `${n}`).join(' × ') + ' mm'
}

export default function App() {
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [selectedFile, setSelectedFile] = useState(null)
  const [previewStatus, setPreviewStatus] = useState('idle')
  const [previewUrl, setPreviewUrl] = useState('')
  const [previewError, setPreviewError] = useState('')
  const [previewStats, setPreviewStats] = useState(null)
  const [geometry, setGeometry] = useState(null)
  const [purpose, setPurpose] = useState('functional')
  const [strength, setStrength] = useState('medium')
  const [preferredFilamentId, setPreferredFilamentId] = useState('')
  const [notes, setNotes] = useState('')
  const [result, setResult] = useState(null)
  const [filaments, setFilaments] = useState([])
  const [filamentForm, setFilamentForm] = useState(EMPTY_FILAMENT)
  const [copied, setCopied] = useState(false)
  const fileGen = useRef(0)

  const refreshFilaments = useCallback(async () => {
    const rows = await listFilaments()
    setFilaments(rows)
  }, [])

  useEffect(() => {
    refreshFilaments().catch((e) => setError(e.message))
  }, [refreshFilaments])

  const selectedFilament = useMemo(
    () => filaments.find((f) => String(f.id) === String(preferredFilamentId)) || null,
    [filaments, preferredFilamentId],
  )

  const recommendPayload = useMemo(() => {
    if (!geometry) return null
    return {
      file_id: geometry.file_id,
      purpose,
      strength,
      preferred_filament_id: preferredFilamentId ? Number(preferredFilamentId) : null,
      color_preference: selectedFilament?.color || null,
      notes: notes || null,
    }
  }, [geometry, purpose, strength, preferredFilamentId, selectedFilament, notes])

  async function onFile(file) {
    if (!file) return
    if (!isSupportedMesh(file)) {
      setError('Yalnızca .glb, .gltf, .obj veya .stl desteklenir.')
      return
    }
    const token = ++fileGen.current
    setError('')
    setResult(null)
    setGeometry(null)
    setSelectedFile(file)
    setPreviewUrl('')
    setPreviewStats(null)
    setPreviewError('')
    setPreviewStatus('loading')
    setBusy(true)

    const previewTask = renderMeshThumbnail(file)
      .then((shot) => {
        if (token !== fileGen.current) return
        setPreviewUrl(shot.dataUrl)
        setPreviewStats({
          triangleCount: shot.triangleCount,
          vertexCount: shot.vertexCount,
        })
        setPreviewStatus('ready')
      })
      .catch((e) => {
        if (token !== fileGen.current) return
        setPreviewStatus('error')
        setPreviewError(e.message || 'Önizleme oluşturulamadı.')
      })

    try {
      const metrics = await analyzeMesh(file)
      if (token !== fileGen.current) return
      setGeometry(metrics)
    } catch (e) {
      if (token !== fileGen.current) return
      setError(e.message)
      setGeometry(null)
    } finally {
      if (token === fileGen.current) setBusy(false)
      await previewTask
    }
  }

  async function onRecommend() {
    if (!recommendPayload) return
    setError('')
    setBusy(true)
    try {
      const data = await recommend(recommendPayload)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function onCopyJson() {
    if (!result?.recommendation) return
    await navigator.clipboard.writeText(JSON.stringify(result.recommendation, null, 2))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  async function onDownloadProfile() {
    if (!recommendPayload) return
    setBusy(true)
    setError('')
    try {
      const profile = await exportProfile(recommendPayload)
      const blob = new Blob([JSON.stringify(profile, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `p2s_${geometry.file_id.slice(0, 8)}_profile.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function onDownload3mf() {
    if (!recommendPayload) return
    setBusy(true)
    setError('')
    try {
      const { blob, filename } = await export3mf(recommendPayload)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function onAddFilament(e) {
    e.preventDefault()
    setError('')
    try {
      await createFilament({
        ...filamentForm,
        diameter_mm: 1.75,
      })
      setFilamentForm(EMPTY_FILAMENT)
      await refreshFilaments()
    } catch (err) {
      setError(err.message)
    }
  }

  async function onDeleteFilament(id) {
    setError('')
    try {
      await deleteFilament(id)
      if (String(preferredFilamentId) === String(id)) setPreferredFilamentId('')
      await refreshFilaments()
    } catch (err) {
      setError(err.message)
    }
  }

  const rec = result?.recommendation

  return (
    <div className="shell">
      <header className="brand">
        <div className="brand-mark">Bambu Lab P2S Combo</div>
        <h1>Akıllı Baskı Asistanı</h1>
        <p>
          GLB / OBJ yükle → amaç / sağlamlık / eldeki filament seç → sistem P2S Combo için baskı ayarı
          önerir. Öneri şu an ekranda; Bambu Studio’ya otomatik yazılmaz.
        </p>
      </header>

      {error ? <div className="banner err">{error}</div> : null}

      <div className="grid">
        <section className="stack">
          <div className="panel stack">
            <h2>1. Model</h2>
            <ModelPreviewCard
              status={previewStatus}
              fileName={selectedFile?.name || geometry?.filename}
              fileSize={selectedFile?.size}
              triangleCount={geometry?.triangle_count ?? previewStats?.triangleCount}
              vertexCount={geometry?.vertex_count ?? previewStats?.vertexCount}
              previewUrl={previewUrl}
              errorMessage={previewError}
              analyzing={busy && !geometry}
              backendReady={Boolean(geometry)}
              drag={drag}
              onDragOver={(e) => {
                e.preventDefault()
                setDrag(true)
              }}
              onDragLeave={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget)) setDrag(false)
              }}
              onDrop={(e) => {
                e.preventDefault()
                setDrag(false)
                onFile(e.dataTransfer.files?.[0])
              }}
              onPickFile={onFile}
            />

            {geometry ? (
              <>
                <div className={`banner ${geometry.fits_p2s_bed ? 'ok' : 'warn'}`}>
                  {geometry.bed_fit_note ||
                    (geometry.fits_p2s_bed
                      ? 'Model P2S Combo tablasına sığar.'
                      : 'Model tabla limitini aşıyor olabilir.')}
                </div>
                <div className="metrics">
                  <div className="metric">
                    <span>Dosya</span>
                    <b>{geometry.filename}</b>
                  </div>
                  <div className="metric">
                    <span>Model boyutu</span>
                    <b>{formatBox(geometry.bounding_box_mm)}</b>
                  </div>
                  <div className="metric">
                    <span>P2S tabla limiti</span>
                    <b>{formatBox(geometry.printer_bed_mm || [256, 256, 256])}</b>
                  </div>
                  <div className="metric">
                    <span>Yaklaşık plastik hacmi</span>
                    <b>{geometry.volume_cm3} cm³</b>
                  </div>
                  <div className="metric">
                    <span>Detay seviyesi</span>
                    <b>{DETAIL_LABELS[geometry.detail_tier] || geometry.detail_tier || '—'}</b>
                  </div>
                  <div className="metric">
                    <span>Üçgen / köşe</span>
                    <b>
                      {geometry.triangle_count.toLocaleString('tr-TR')}
                      {geometry.vertex_count
                        ? ` / ${geometry.vertex_count.toLocaleString('tr-TR')}`
                        : ''}
                    </b>
                  </div>
                  <div className="metric">
                    <span>Mesh yoğunluğu</span>
                    <b>
                      {geometry.triangles_per_cm2 != null
                        ? `${geometry.triangles_per_cm2} üçgen/cm²`
                        : `${geometry.triangle_count.toLocaleString('tr-TR')} üçgen`}
                      {geometry.thin_feature_hint ? ' · ince yer' : ''}
                    </b>
                  </div>
                </div>
                {geometry.detail_note ? <p className="hint">{geometry.detail_note}</p> : null}
                <p className="hint">
                  Boyutlar yazıcı ayarı değil — yüklediğin 3D modelin mm cinsinden büyüklüğü.
                  Detay seviyesi üçgen yoğunluğundan hesaplanır; öneride hız/katman buna göre
                  ayarlanır.
                </p>
              </>
            ) : selectedFile || previewStatus !== 'idle' ? (
              <p className="status">
                {busy ? 'Geometri analizi sürüyor…' : 'Analiz bekleniyor veya tamamlanamadı.'}
              </p>
            ) : (
              <p className="status">Henüz model yüklenmedi.</p>
            )}
          </div>

          <div className="panel stack">
            <h2>2. Amaç ve filament</h2>
            <div className="field">
              <label>Kullanım amacı</label>
              <div className="chips">
                {PURPOSES.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    className={`chip ${purpose === p.id ? 'active' : ''}`}
                    onClick={() => setPurpose(p.id)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="field">
              <label>Sağlamlık profili</label>
              <div className="chips">
                {STRENGTHS.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className={`chip ${strength === s.id ? 'active' : ''}`}
                    onClick={() => setStrength(s.id)}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="field">
              <label>Hangi filamentle basmak istiyorsun?</label>
              <select
                value={preferredFilamentId}
                onChange={(e) => setPreferredFilamentId(e.target.value)}
              >
                <option value="">Otomatik eşleştir (önerilen malzemeye göre)</option>
                {filaments.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.color} — {f.brand ? `${f.brand} ` : ''}
                    {f.material}
                    {f.slot ? ` (${f.slot})` : ''}
                  </option>
                ))}
              </select>
              <p className="hint">
                Listede yalnızca envanterindeki renkler var. Önerilen malzemeyle çakışırsa uyarı
                çıkar.
              </p>
            </div>
            <div className="field">
              <label>Not (öneriye eklenir)</label>
              <textarea
                rows={2}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="ör. duvara asılacak raf, yük taşıyacak"
              />
              <p className="hint">
                Bu metin öneri gerekçesine yazılır; AI açıksa malzeme/ayar seçiminde de kullanılır
                (kanca, dış mekan, süs vb.).
              </p>
            </div>
            <div className="row">
              <button
                type="button"
                className="btn btn-primary"
                disabled={!geometry || busy}
                onClick={onRecommend}
              >
                {busy ? 'Hesaplanıyor…' : 'Ayarları öner'}
              </button>
            </div>
          </div>

          {rec ? (
            <div className="panel stack">
              <h2>3. Öneri</h2>
              <div className="banner ok">
                <strong>Kim öneriyor?</strong> {result.source_label}
                <div className="hint" style={{ marginTop: '0.35rem' }}>
                  {result.source_explanation}
                </div>
              </div>

              {rec.color_conflict_warning ? (
                <div className="banner warn">{rec.color_conflict_warning}</div>
              ) : null}
              {rec.missing_filament_warning ? (
                <div className="banner warn">{rec.missing_filament_warning}</div>
              ) : (
                <div className="banner ok">
                  Eşleşen filament:{' '}
                  {rec.matched_filament_label ||
                    `${rec.material} / slot ${rec.matched_inventory_slot || '—'}`}
                  {rec.ideal_material && rec.ideal_material !== rec.material
                    ? ` · ideal malzeme ${rec.ideal_material} idi`
                    : ''}
                </div>
              )}

              {rec.user_notes_applied ? (
                <div className="banner ok">Notun işlendi: “{rec.user_notes_applied}”</div>
              ) : null}

              {rec.speed_rationale ? (
                <div className="banner ok">
                  <strong>Hız profili:</strong> {DETAIL_LABELS[rec.detail_tier] || rec.detail_tier}
                  <div className="hint" style={{ marginTop: '0.35rem' }}>
                    {rec.speed_rationale}
                  </div>
                </div>
              ) : null}

              <div className="rec-grid">
                <div className="rec-item">
                  <span>Malzeme</span>
                  <b>{rec.material}</b>
                </div>
                <div className="rec-item">
                  <span>Nozzle</span>
                  <b>{rec.nozzle_mm} mm</b>
                </div>
                <div className="rec-item">
                  <span>Katman</span>
                  <b>{rec.layer_height_mm} mm</b>
                </div>
                <div className="rec-item">
                  <span>Duvar</span>
                  <b>{rec.wall_loops}</b>
                </div>
                <div className="rec-item">
                  <span>Dolgu</span>
                  <b>
                    %{rec.infill_percent} {rec.infill_pattern}
                  </b>
                </div>
                <div className="rec-item">
                  <span>Sıcaklık (noz / tabla)</span>
                  <b>
                    {rec.nozzle_temp_c}° / {rec.bed_temp_c}°
                  </b>
                </div>
                <div className="rec-item">
                  <span>Genel hız</span>
                  <b>{rec.print_speed_mm_s != null ? `${rec.print_speed_mm_s} mm/s` : '—'}</b>
                </div>
                <div className="rec-item">
                  <span>Dış duvar hızı</span>
                  <b>
                    {rec.outer_wall_speed_mm_s != null ? `${rec.outer_wall_speed_mm_s} mm/s` : '—'}
                  </b>
                </div>
                <div className="rec-item">
                  <span>Dolgu hızı</span>
                  <b>
                    {rec.sparse_infill_speed_mm_s != null
                      ? `${rec.sparse_infill_speed_mm_s} mm/s`
                      : '—'}
                  </b>
                </div>
                <div className="rec-item">
                  <span>Support</span>
                  <b>{rec.supports ? 'evet' : 'hayır'}</b>
                </div>
                <div className="rec-item">
                  <span>Brim</span>
                  <b>{rec.brim ? 'evet' : 'hayır'}</b>
                </div>
              </div>
              <p className="rationale">{rec.rationale}</p>

              <div className="json-box">
                <strong>Bambu Studio dosyası (.3mf)</strong>
                <p className="hint">
                  İndirdiğin <code>.3mf</code> dosyasını Bambu Studio’da aç → Slice → Print.
                  Model + önerilen ayarlar (katman, dolgu, hız, sıcaklık…) gömülü. Bu henüz
                  dilimlenmiş gcode değil; Studio’da bir kez Slice etmen gerekir.
                </p>
                <div className="row">
                  <button type="button" className="btn btn-primary" onClick={onDownload3mf} disabled={busy}>
                    .3mf indir (Studio)
                  </button>
                  <button type="button" className="btn" onClick={onCopyJson}>
                    {copied ? 'Kopyalandı' : 'Ayar JSON kopyala'}
                  </button>
                  <button type="button" className="btn" onClick={onDownloadProfile}>
                    Profil JSON indir
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </section>

        <aside className="panel stack">
          <h2>Filament envanteri</h2>
          <p className="status">AMS / harici slotlarını elle tut; canlı okuma sonra gelecek.</p>
          <form className="form-inline" onSubmit={onAddFilament}>
            <div className="field">
              <label>Malzeme</label>
              <select
                value={filamentForm.material}
                onChange={(e) => setFilamentForm((f) => ({ ...f, material: e.target.value }))}
              >
                {['PLA', 'PLA+', 'PETG', 'ABS', 'ASA', 'TPU'].map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Renk</label>
              <input
                required
                value={filamentForm.color}
                onChange={(e) => setFilamentForm((f) => ({ ...f, color: e.target.value }))}
                placeholder="siyah"
              />
            </div>
            <div className="field">
              <label>Marka</label>
              <input
                value={filamentForm.brand}
                onChange={(e) => setFilamentForm((f) => ({ ...f, brand: e.target.value }))}
              />
            </div>
            <div className="field">
              <label>Slot</label>
              <input
                value={filamentForm.slot}
                onChange={(e) => setFilamentForm((f) => ({ ...f, slot: e.target.value }))}
                placeholder="AMS-1"
              />
            </div>
            <div className="field wide">
              <button type="submit" className="btn btn-primary">
                Ekle
              </button>
            </div>
          </form>

          {filaments.length ? (
            <table className="table">
              <thead>
                <tr>
                  <th>Malzeme</th>
                  <th>Renk</th>
                  <th>Slot</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filaments.map((f) => (
                  <tr key={f.id}>
                    <td>{f.material}</td>
                    <td>{f.color}</td>
                    <td>{f.slot || '—'}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        onClick={() => onDeleteFilament(f.id)}
                      >
                        sil
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="status">Envanter boş — öneri yine çalışır, uyarı verir.</p>
          )}
        </aside>
      </div>
    </div>
  )
}
