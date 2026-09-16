export default function WarningModal({ open, warnings, onChangeSelection, onProceed }) {
  if (!open || !warnings?.length) return null
  const primary = warnings[0]
  const reasons = [...new Set(warnings.flatMap((w) => w.reasons || []))]
  const colorName = primary.color_name || 'bu renk'
  const filamentLabel = primary.filament_label || 'seçilen filament'

  return (
    <div className="modal-backdrop" role="presentation" onClick={onChangeSelection}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="filament-warn-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="filament-warn-title">Uyarı</h3>
        <p>
          <strong>{colorName}</strong> için <strong>{filamentLabel}</strong> seçmek önerilmez.
        </p>
        <ul className="warn-reasons">
          {reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
        <p className="hint">Yine de devam etmek istiyor musun?</p>
        <div className="row">
          <button type="button" className="btn" onClick={onChangeSelection}>
            Seçimi değiştir
          </button>
          <button type="button" className="btn btn-primary" onClick={onProceed}>
            Yine de devam et
          </button>
        </div>
      </div>
    </div>
  )
}
