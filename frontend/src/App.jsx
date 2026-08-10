import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  analyzeStl,
  createFilament,
  deleteFilament,
  exportProfile,
  listFilaments,
  recommend,
} from './api'
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

const EMPTY_FILAMENT = {
  material: 'PLA',
  color: '',
  brand: '',
  slot: '',
  notes: '',
}

function formatBox(box) {
  if (!box?.length) return '—'
  return box.map((n) => `${n}`).join(' × ') + ' mm'
}

export default function App() {
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [geometry, setGeometry] = useState(null)
  const [purpose, setPurpose] = useState('functional')
  const [strength, setStrength] = useState('medium')
  const [colorPreference, setColorPreference] = useState('')
  const [notes, setNotes] = useState('')
  const [result, setResult] = useState(null)
  const [filaments, setFilaments] = useState([])
  const [filamentForm, setFilamentForm] = useState(EMPTY_FILAMENT)
  const [copied, setCopied] = useState(false)

  const refreshFilaments = useCallback(async () => {
    const rows = await listFilaments()
    setFilaments(rows)
  }, [])

  useEffect(() => {
    refreshFilaments().catch((e) => setError(e.message))
  }, [refreshFilaments])

  const recommendPayload = useMemo(() => {
    if (!geometry) return null
    return {
      file_id: geometry.file_id,
      purpose,
      strength,
      color_preference: colorPreference || null,
      notes: notes || null,
    }
  }, [geometry, purpose, strength, colorPreference, notes])

  async function onFile(file) {
    if (!file) return
    setError('')
    setResult(null)
    setBusy(true)
    try {
      const metrics = await analyzeStl(file)
      setGeometry(metrics)
    } catch (e) {
      setError(e.message)
      setGeometry(null)
    } finally {
      setBusy(false)
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
      await refreshFilaments()
    } catch (err) {
      setError(err.message)
    }
  }

  const rec = result?.recommendation

  return (
    <div className="shell">
      <header className="brand">
        <div className="brand-mark">Bambu Lab P2S</div>
        <h1>Akıllı Baskı Asistanı</h1>
        <p>
          STL yükle, kullanım amacını ve sağlamlık seviyesini seç — sistem filament ve dilimleme
          ayarlarını önerir. Faz A: öneri. Faz B için profil JSON indirilebilir.
        </p>
      </header>

      {error ? <div className="banner err">{error}</div> : null}

      <div className="grid">
        <section className="stack">
          <div className="panel stack">
            <h2>1. Model</h2>
            <div
              className={`drop ${drag ? 'drag' : ''}`}
              onDragOver={(e) => {
                e.preventDefault()
                setDrag(true)
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDrag(false)
                onFile(e.dataTransfer.files?.[0])
              }}
            >
              <strong>STL / OBJ sürükle bırak</strong>
              veya dosya seç
              <div className="row" style={{ justifyContent: 'center', marginTop: '0.8rem' }}>
                <label className="btn btn-primary">
                  Dosya seç
                  <input
                    type="file"
                    accept=".stl,.obj"
                    hidden
                    onChange={(e) => onFile(e.target.files?.[0])}
                  />
                </label>
              </div>
            </div>

            {geometry ? (
              <div className="metrics">
                <div className="metric">
                  <span>Dosya</span>
                  <b>{geometry.filename}</b>
                </div>
                <div className="metric">
                  <span>Üçgen</span>
                  <b>{geometry.triangle_count.toLocaleString('tr-TR')}</b>
                </div>
                <div className="metric">
                  <span>Kutu (X×Y×Z)</span>
                  <b>{formatBox(geometry.bounding_box_mm)}</b>
                </div>
                <div className="metric">
                  <span>Hacim</span>
                  <b>{geometry.volume_cm3} cm³</b>
                </div>
                <div className="metric">
                  <span>Watertight</span>
                  <b>{geometry.is_watertight ? 'evet' : 'hayır'}</b>
                </div>
                <div className="metric">
                  <span>İnce özellik</span>
                  <b>{geometry.thin_feature_hint ? 'var' : 'yok'}</b>
                </div>
              </div>
            ) : (
              <p className="status">Henüz model yüklenmedi.</p>
            )}
          </div>

          <div className="panel stack">
            <h2>2. Amaç ve sağlamlık</h2>
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
              <label>Renk tercihi (opsiyonel)</label>
              <input
                value={colorPreference}
                onChange={(e) => setColorPreference(e.target.value)}
                placeholder="ör. kırmızı, mat siyah"
              />
            </div>
            <div className="field">
              <label>Not</label>
              <textarea
                rows={2}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="ör. duvara asılacak raf, yük taşıyacak"
              />
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
              <span className="status">
                {result ? (result.used_llm ? 'kaynak: OpenAI + kurallar' : 'kaynak: kural motoru') : ''}
              </span>
            </div>
          </div>

          {rec ? (
            <div className="panel stack">
              <h2>3. Öneri</h2>
              {rec.missing_filament_warning ? (
                <div className="banner warn">{rec.missing_filament_warning}</div>
              ) : (
                <div className="banner ok">
                  Envanter eşleşmesi: slot {rec.matched_inventory_slot || '—'} (id{' '}
                  {rec.matched_inventory_id ?? '—'})
                </div>
              )}
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
                  <span>Sıcaklık</span>
                  <b>
                    {rec.nozzle_temp_c}° / {rec.bed_temp_c}°
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
                <div className="rec-item">
                  <span>Şema</span>
                  <b>{rec.schema_version}</b>
                </div>
              </div>
              <p className="rationale">{rec.rationale}</p>
              <div className="row">
                <button type="button" className="btn" onClick={onCopyJson}>
                  {copied ? 'Kopyalandı' : 'JSON kopyala'}
                </button>
                <button type="button" className="btn" onClick={onDownloadProfile}>
                  Profil JSON indir (Faz B)
                </button>
              </div>
            </div>
          ) : null}
        </section>

        <aside className="panel stack">
          <h2>Filament envanteri</h2>
          <p className="status">AMS slotlarını elle tut; canlı MQTT Faz C’de.</p>
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
