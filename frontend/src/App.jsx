import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  analyzeMesh,
  createFilament,
  deleteFilament,
  export3mf,
  exportProfile,
  filamentOptionLabel,
  listFilaments,
  recommend,
  validateFilamentMap,
} from './api'
import ColorSlotMap from './ColorSlotMap'
import ModelPreviewCard from './ModelPreviewCard'
import WarningModal from './WarningModal'
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

const MESH_EXTS = ['.glb', '.gltf', '.obj', '.stl', '.3mf']

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

const SUPPORT_TYPE_LABELS = {
  'tree(auto)': 'Tree (otomatik)',
  'normal(auto)': 'Grid / normal',
  none: 'Kapalı',
}

function RecItem({ label, value, reason }) {
  return (
    <div className="rec-item">
      <span>{label}</span>
      <b>{value}</b>
      {reason ? <p className="rec-why">{reason}</p> : null}
    </div>
  )
}

function autoMapColors(colors, filaments) {
  const used = new Set()
  const map = {}
  for (const color of colors || []) {
    const names = [color.name, ...(color.aliases || [])].map((s) => String(s).toLowerCase())
    const match = filaments.find((f) => {
      if (used.has(f.id)) return false
      const fc = String(f.color || '').toLowerCase()
      return fc && names.some((n) => fc === n || fc.includes(n) || n.includes(fc))
    })
    if (match) {
      map[color.id] = String(match.id)
      used.add(match.id)
    }
  }
  return map
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
  const [colorMap, setColorMap] = useState({})
  const [mapWarnings, setMapWarnings] = useState([])
  const [pendingChange, setPendingChange] = useState(null)
  const [warningsAcked, setWarningsAcked] = useState(false)
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

  const colorFilamentMap = useMemo(() => {
    if (!geometry?.colors?.length) return []
    return geometry.colors.map((c) => ({
      color_id: c.id,
      filament_id: colorMap[c.id] ? Number(colorMap[c.id]) : null,
    }))
  }, [geometry, colorMap])

  const isMultiColor =
    (geometry?.colors?.length || 0) >= 2 || (geometry?.color_count || 0) >= 2

  const recommendPayload = useMemo(() => {
    if (!geometry) return null
    return {
      file_id: geometry.file_id,
      purpose,
      strength,
      preferred_filament_id: preferredFilamentId ? Number(preferredFilamentId) : null,
      color_preference: selectedFilament?.color || null,
      notes: notes || null,
      color_filament_map: colorFilamentMap,
      acknowledge_filament_warnings: warningsAcked,
    }
  }, [
    geometry,
    purpose,
    strength,
    preferredFilamentId,
    selectedFilament,
    notes,
    colorFilamentMap,
    warningsAcked,
  ])

  async function onFile(file) {
    if (!file) return
    if (!isSupportedMesh(file)) {
      setError('Yalnızca .3mf, .glb, .gltf, .obj veya .stl desteklenir.')
      return
    }
    const token = ++fileGen.current
    setError('')
    setResult(null)
    setGeometry(null)
    setColorMap({})
    setMapWarnings([])
    setPendingChange(null)
    setWarningsAcked(false)
    setSelectedFile(file)
    setPreviewUrl('')
    setPreviewStats(null)
    setPreviewError('')
    setPreviewStatus('loading')
    setBusy(true)

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
    }
  }

  const onViewportReady = useCallback((stats) => {
    setPreviewStats(stats)
    setPreviewStatus('ready')
    setPreviewError('')
  }, [])

  const onViewportError = useCallback((message) => {
    setPreviewStatus('error')
    setPreviewError(message || 'Önizleme oluşturulamadı.')
  }, [])

  useEffect(() => {
    if (!geometry?.colors?.length || !filaments.length) return
    setColorMap((prev) => (Object.keys(prev).length ? prev : autoMapColors(geometry.colors, filaments)))
  }, [geometry?.file_id, filaments])

  function mapValidateBody(nextMap = colorMap) {
    return {
      file_id: geometry.file_id,
      purpose,
      strength,
      color_filament_map: (geometry.colors || []).map((c) => ({
        color_id: c.id,
        filament_id: nextMap[c.id] ? Number(nextMap[c.id]) : null,
      })),
    }
  }

  async function onColorMapChange(colorId, filamentId) {
    const next = { ...colorMap, [colorId]: filamentId }
    setWarningsAcked(false)
    if (!geometry) {
      setColorMap(next)
      return
    }
    try {
      const res = await validateFilamentMap(mapValidateBody(next))
      const warnings = res.warnings || []
      if (warnings.length) {
        setPendingChange({ nextMap: next, warnings, resume: null })
        return
      }
      setColorMap(next)
      setMapWarnings([])
    } catch (e) {
      setColorMap(next)
      setError(e.message)
    }
  }

  async function confirmThen(action) {
    if (!geometry || !isMultiColor) {
      await action()
      return
    }
    try {
      const res = await validateFilamentMap(mapValidateBody())
      const warnings = res.warnings || []
      setMapWarnings(warnings)
      if (warnings.length && !warningsAcked) {
        setPendingChange({ nextMap: colorMap, warnings, resume: action })
        return
      }
      await action()
    } catch (e) {
      setError(e.message)
    }
  }

  function onChangeSelection() {
    setPendingChange(null)
  }

  async function onProceedAnyway() {
    const pending = pendingChange
    setPendingChange(null)
    if (!pending) return
    setColorMap(pending.nextMap)
    setMapWarnings(pending.warnings || [])
    setWarningsAcked(true)
    if (pending.resume) await pending.resume()
  }

  async function onRecommend() {
    if (!recommendPayload) return
    await confirmThen(async () => {
      setError('')
      setBusy(true)
      try {
        const data = await recommend(recommendPayload)
        setResult(data)
        setMapWarnings(data.recommendation?.filament_warnings || [])
      } catch (e) {
        setError(e.message)
      } finally {
        setBusy(false)
      }
    })
  }

  async function onCopyJson() {
    if (!result?.recommendation) return
    await navigator.clipboard.writeText(JSON.stringify(result.recommendation, null, 2))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  async function onDownloadProfile() {
    if (!recommendPayload) return
    await confirmThen(async () => {
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
    })
  }

  async function onDownload3mf() {
    if (!recommendPayload) return
    await confirmThen(async () => {
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
    })
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
          GLB / OBJ / 3MF yükle → amaç / sağlamlık / eldeki filament seç → sistem P2S Combo için baskı ayarı
          önerir. Meshy `.3mf` renk ve gövde ayrımı korunur.
        </p>
      </header>

      {error ? <div className="banner err">{error}</div> : null}

      <div className="grid">
        <section className="stack">
          <div className="panel stack">
            <h2>1. Model</h2>
            <ModelPreviewCard
              status={previewStatus}
              file={selectedFile}
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
              onViewportReady={onViewportReady}
              onViewportError={onViewportError}
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
                    <span>Renk paleti</span>
                    <b className="palette">
                      {(geometry.colors || []).length
                        ? geometry.colors.map((c) => (
                            <span key={c.id} className="swatch sm" style={{ background: c.hex }} title={`${c.name} ${c.hex}`} />
                          ))
                        : geometry.color_count || 1}
                    </b>
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
                  <div className="metric">
                    <span>Support</span>
                    <b>
                      {geometry.support_required
                        ? SUPPORT_TYPE_LABELS[geometry.recommended_support_type] ||
                          geometry.recommended_support_type
                        : 'Gerekmez'}
                      {geometry.overhang_area_ratio > 0.01
                        ? ` · %${(geometry.overhang_area_ratio * 100).toFixed(0)} overhang`
                        : ''}
                    </b>
                  </div>
                </div>
                {geometry.support_reason ? (
                  <div className={`banner ${geometry.support_required ? 'warn' : 'ok'}`}>
                    {geometry.support_reason}
                  </div>
                ) : null}
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
            {isMultiColor && geometry?.colors?.length ? (
              <ColorSlotMap
                colors={geometry.colors}
                filaments={filaments}
                value={colorMap}
                onChange={onColorMapChange}
                warnings={mapWarnings}
              />
            ) : (
              <div className="field">
                <label>Hangi filamentle basmak istiyorsun?</label>
                <select
                  value={preferredFilamentId}
                  onChange={(e) => setPreferredFilamentId(e.target.value)}
                >
                  <option value="">Otomatik eşleştir (önerilen malzemeye göre)</option>
                  {filaments.map((f) => (
                    <option key={f.id} value={f.id}>
                      {filamentOptionLabel(f)}
                    </option>
                  ))}
                </select>
                <p className="hint">
                  Listede yalnızca envanterindeki renkler var. Önerilen malzemeyle çakışırsa uyarı
                  çıkar.
                </p>
              </div>
            )}
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
              {(rec.filament_warnings || mapWarnings).length
                ? (rec.filament_warnings || mapWarnings).map((w) => (
                    <div key={`${w.code}-${w.color_id || w.message}`} className={`banner ${w.severity === 'high' ? 'err' : 'warn'}`}>
                      {w.message}
                    </div>
                  ))
                : null}
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
                <RecItem label="Malzeme" value={rec.material} reason={rec.setting_reasons?.material} />
                <RecItem
                  label="Nozzle"
                  value={`${rec.nozzle_mm} mm`}
                  reason={rec.setting_reasons?.nozzle}
                />
                <RecItem
                  label="Katman"
                  value={`${rec.layer_height_mm} mm`}
                  reason={rec.setting_reasons?.layer_height}
                />
                <RecItem label="Duvar" value={rec.wall_loops} reason={rec.setting_reasons?.walls} />
                <RecItem
                  label="Dolgu"
                  value={`%${rec.infill_percent} ${rec.infill_pattern}`}
                  reason={rec.setting_reasons?.infill}
                />
                <RecItem
                  label="Sıcaklık (noz / tabla)"
                  value={`${rec.nozzle_temp_c}° / ${rec.bed_temp_c}°`}
                  reason={rec.setting_reasons?.temperature}
                />
                <RecItem
                  label="Genel hız"
                  value={rec.print_speed_mm_s != null ? `${rec.print_speed_mm_s} mm/s` : '—'}
                  reason={rec.setting_reasons?.print_speed}
                />
                <RecItem
                  label="Dış duvar hızı"
                  value={
                    rec.outer_wall_speed_mm_s != null ? `${rec.outer_wall_speed_mm_s} mm/s` : '—'
                  }
                  reason={rec.setting_reasons?.outer_wall_speed}
                />
                <RecItem
                  label="Dolgu hızı"
                  value={
                    rec.sparse_infill_speed_mm_s != null
                      ? `${rec.sparse_infill_speed_mm_s} mm/s`
                      : '—'
                  }
                  reason={rec.setting_reasons?.infill_speed}
                />
                <RecItem
                  label="Support"
                  value={
                    rec.supports
                      ? SUPPORT_TYPE_LABELS[rec.support_type] || rec.support_type || 'Açık'
                      : 'Kapalı'
                  }
                  reason={rec.setting_reasons?.supports || rec.support_reason}
                />
                <RecItem
                  label="Brim"
                  value={rec.brim ? 'evet' : 'hayır'}
                  reason={rec.setting_reasons?.brim}
                />
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

        <aside className="panel stack inv-panel">
          <div className="inv-head">
            <div>
              <h2>Filament envanteri</h2>
              <p className="status">AMS / harici slot · {filaments.length} kayıt</p>
            </div>
          </div>
          <form className="inv-toolbar" onSubmit={onAddFilament}>
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
            <button type="submit" className="btn btn-primary btn-add" title="Filament ekle">
              +
            </button>
          </form>

          {filaments.length ? (
            <div className="inv-cards">
              {filaments.map((f) => (
                <div key={f.id} className="inv-card">
                  <div className="inv-card-top">
                    <b>{f.material}</b>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => onDeleteFilament(f.id)}
                      aria-label="Filament sil"
                    >
                      ×
                    </button>
                  </div>
                  <span className="inv-color">{f.color}</span>
                  <span className="inv-slot">{f.slot || 'slot yok'}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="status">Envanter boş — öneri yine çalışır, uyarı verir.</p>
          )}
        </aside>
      </div>
      <WarningModal
        open={Boolean(pendingChange)}
        warnings={pendingChange?.warnings}
        onChangeSelection={onChangeSelection}
        onProceed={onProceedAnyway}
      />
    </div>
  )
}
