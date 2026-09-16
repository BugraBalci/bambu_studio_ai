import { filamentOptionLabel } from './api'

export default function ColorSlotMap({ colors, filaments, value, onChange, warnings }) {
  const warningByColor = new Map((warnings || []).map((w) => [w.color_id, w]))

  return (
    <div className="field color-map">
      <label>Renk → filament eşlemesi</label>
      <p className="hint">
        Modeldeki her temel renk için envanterindeki AMS/slot filamentini seç. Karışım ve sıcaklık
        kuralları otomatik kontrol edilir.
      </p>
      <div className="map-list">
        {(colors || []).map((color) => {
          const warning = warningByColor.get(color.id)
          return (
            <div key={color.id} className={`map-row ${warning ? `sev-${warning.severity}` : ''}`}>
              <span
                className="swatch"
                style={{ background: color.hex || '#888' }}
                title={color.hex}
              />
              <div className="map-color">
                <b>{color.name}</b>
                <span className="hex">{color.hex}</span>
              </div>
              <span className="map-arrow" aria-hidden="true">
                →
              </span>
              <select
                value={value[color.id] || ''}
                onChange={(e) => onChange(color.id, e.target.value)}
              >
                <option value="">Filament seç</option>
                {filaments.map((f) => (
                  <option key={f.id} value={f.id}>
                    {filamentOptionLabel(f)}
                  </option>
                ))}
              </select>
            </div>
          )
        })}
      </div>
    </div>
  )
}
