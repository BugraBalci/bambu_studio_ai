const FLUSH_BLURB =
  'Pürüzsüz (Gömülü) Seçildi: Yazı modelin üst katmanlarına gömülür, çıkıntı yapmaz ve sürtünmeye dayanıklı dümdüz bir yüzey sağlar.'
const EMBOSSED_BLURB =
  'Kabartmalı Seçildi: Yazı model yüzeyinden 0.6 mm dışarı taşırılarak belirgin 3D dokunsal derinlik kazandırılır.'
const WRAP_BLURB =
  'Çevreleyen Yüzey Aktif: Yazı kavisli/silindirik modelin eğimini otomatik takip ederek yüzeye tam oturur.'

export default function TextCustomizePanel({
  enabled,
  content,
  style,
  surfaceMode,
  filamentId,
  extruder,
  filaments,
  wrapRecommended,
  surfaceNote,
  preview,
  onChange,
}) {
  const styleBlurb =
    preview?.explanations?.active || (style === 'embossed' ? EMBOSSED_BLURB : FLUSH_BLURB)
  const wrapOn = preview?.wrap_applied || surfaceMode === 'curved' || (surfaceMode === 'auto' && wrapRecommended)
  const surfaceBlurb = wrapOn ? preview?.explanations?.surface || WRAP_BLURB : preview?.surface_note || surfaceNote

  return (
    <div className="panel stack">
      <h2>Yazı ve rozet</h2>
      <p className="hint">
        Bambu Studio’daki Metin aracı gibi: gömülü yazı ikinci AMS rengiyle üst katmana işlenir, kabartma ise
        ayrı parça olarak dışarı taşar. Kavisli modellerde çevreleyen yüzey sargısı harfleri kontura oturtur.
      </p>
      <label className="rule-toggle">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onChange({ enabled: e.target.checked })}
        />
        Modele yazı / rozet ekle
      </label>
      {enabled ? (
        <>
          <div className="field">
            <label>Yazı</label>
            <textarea
              rows={2}
              value={content}
              maxLength={48}
              onChange={(e) => onChange({ content: e.target.value })}
              placeholder="ör. BAMBU"
            />
          </div>
          <div className="field">
            <label>Stil</label>
            <div className="chips">
              <button
                type="button"
                className={`chip ${style === 'flush' ? 'active' : ''}`}
                onClick={() => onChange({ style: 'flush' })}
              >
                Pürüzsüz / Gömülü
              </button>
              <button
                type="button"
                className={`chip ${style === 'embossed' ? 'active' : ''}`}
                onClick={() => onChange({ style: 'embossed' })}
              >
                Kabartmalı
              </button>
            </div>
          </div>
          <div className="eng-card">
            <div className="rule-card-head">
              <strong>{style === 'embossed' ? 'Kabartmalı (Parça)' : 'Pürüzsüz (Değiştir / Modifier)'}</strong>
              <span className="rule-pill">{style === 'embossed' ? 'Part · +0.6 mm' : 'Flush inlay'}</span>
            </div>
            <p className="rec-why">{styleBlurb}</p>
          </div>
          <div className="field">
            <label>Yüzey</label>
            <div className="chips">
              <button
                type="button"
                className={`chip ${surfaceMode === 'auto' ? 'active' : ''}`}
                onClick={() => onChange({ surfaceMode: 'auto' })}
              >
                Otomatik
              </button>
              <button
                type="button"
                className={`chip ${surfaceMode === 'planar' ? 'active' : ''}`}
                onClick={() => onChange({ surfaceMode: 'planar' })}
              >
                Düzlem
              </button>
              <button
                type="button"
                className={`chip ${surfaceMode === 'curved' ? 'active' : ''}`}
                onClick={() => onChange({ surfaceMode: 'curved' })}
              >
                Kıvrımlı / Çevreleyen yüzey
              </button>
            </div>
            {wrapRecommended && surfaceMode !== 'planar' ? (
              <p className="hint">Model kavisli/silindirik görünüyor — çevreleyen sargı önerilir.</p>
            ) : null}
          </div>
          {wrapOn ? (
            <div className="eng-card">
              <div className="rule-card-head">
                <strong>Çevreleyen yüzey</strong>
                <span className="rule-pill">Conformal wrap</span>
              </div>
              <p className="rec-why">{surfaceBlurb}</p>
            </div>
          ) : surfaceBlurb ? (
            <p className="hint">{surfaceBlurb}</p>
          ) : null}
          <div className="form-inline">
            <div className="field">
              <label>Yazı filamenti (AMS)</label>
              <select value={filamentId} onChange={(e) => onChange({ filamentId: e.target.value })}>
                <option value="">Varsayılan kontrast (siyah)</option>
                {filaments.map((f) => (
                  <option key={f.id} value={f.id}>
                    {(f.slot || 'Envanter') + ' · ' + f.material + (f.color ? ` — ${f.color}` : '')}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>AMS yuvası</label>
              <select value={extruder} onChange={(e) => onChange({ extruder: e.target.value })}>
                <option value="">Otomatik (sonraki boş)</option>
                {[1, 2, 3, 4].map((slot) => (
                  <option key={slot} value={String(slot)}>
                    AMS {slot}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {preview?.enabled ? (
            <p className="status">
              Önizleme · {preview.letter_height_mm} mm harf · {preview.triangle_count} üçgen · slot{' '}
              {preview.extruder}
              {preview.wrap_applied ? ' · sargı' : ' · düzlem'}
            </p>
          ) : content.trim() ? (
            <p className="status">Yazı önizlemesi hazırlanıyor…</p>
          ) : (
            <p className="hint">Yazıyı girince 3D önizlemede harfler modelin üzerine oturur.</p>
          )}
        </>
      ) : null}
    </div>
  )
}
