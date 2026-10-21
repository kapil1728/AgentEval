import type { ComparisonReport, VersionLabel } from './api'
import { versionKey, versionLabel } from './api'

export type VersionCompareViewProps = {
  versions: VersionLabel[]
  baselineKey: string
  candidateKey: string
  comparison: ComparisonReport | null
  loading: boolean
  error: string
  onBaselineChange: (key: string) => void
  onCandidateChange: (key: string) => void
  onCompare: () => void
}

export function VersionCompareView({
  versions,
  baselineKey,
  candidateKey,
  comparison,
  loading,
  error,
  onBaselineChange,
  onCandidateChange,
  onCompare,
}: VersionCompareViewProps) {
  return (
    <section className="panel-section" aria-labelledby="compare-heading">
      <div className="section-heading">
        <div>
          <h2 id="compare-heading">Version comparison</h2>
          <p className="section-subtitle">Test whether a candidate's pass rate regressed against its baseline.</p>
        </div>
        <span className="result-count">FISHER EXACT · HOLM ADJUSTED</span>
      </div>

      <div className="compare-controls">
        <label className="select-field">
          <span>BASELINE</span>
          <select value={baselineKey} onChange={(event) => onBaselineChange(event.target.value)}>
            <option value="">Select baseline version</option>
            {versions.map((version) => (
              <option key={versionKey(version)} value={versionKey(version)}>{versionLabel(version)}</option>
            ))}
          </select>
        </label>
        <span className="compare-arrow" aria-hidden="true">→</span>
        <label className="select-field">
          <span>CANDIDATE</span>
          <select value={candidateKey} onChange={(event) => onCandidateChange(event.target.value)}>
            <option value="">Select candidate version</option>
            {versions.map((version) => (
              <option key={versionKey(version)} value={versionKey(version)}>{versionLabel(version)}</option>
            ))}
          </select>
        </label>
        <button
          className="primary-button"
          onClick={onCompare}
          disabled={loading || !baselineKey || !candidateKey || baselineKey === candidateKey}
        >
          {loading ? 'Comparing…' : 'Compare versions'}
        </button>
      </div>

      {error && <div className="alert" role="alert">{error}</div>}
      {!comparison && !loading && !error && (
        <div className="empty-panel">Choose two recorded versions to compare task outcomes.</div>
      )}
      {comparison && (
        <>
          <article className={`overall-comparison ${comparison.overall.significant_regression ? 'regression' : ''}`}>
            <div>
              <span className="eyebrow">OVERALL PASS RATE</span>
              <div className="rate-pair">
                <strong>{(comparison.overall.baseline_pass_rate * 100).toFixed(1)}%</strong>
                <span aria-hidden="true">→</span>
                <strong className={comparison.overall.significant_regression ? 'rate low' : 'rate'}>
                  {(comparison.overall.candidate_pass_rate * 100).toFixed(1)}%
                </strong>
              </div>
              <p>{comparison.overall.baseline_runs} baseline runs · {comparison.overall.candidate_runs} candidate runs</p>
            </div>
            <div className="significance">
              <span className={`regression-flag ${comparison.overall.significant_regression ? 'flagged' : ''}`}>
                {comparison.overall.significant_regression ? 'SIGNIFICANT REGRESSION' : 'NO SIGNIFICANT REGRESSION'}
              </span>
              <span>p = {comparison.overall.p_value?.toPrecision(3) ?? 'n/a'} · α = {comparison.alpha}</span>
            </div>
          </article>
          <div className="table-wrap comparison-table">
            <table>
              <thead>
                <tr><th>TASK</th><th>BASELINE PASS</th><th>CANDIDATE PASS</th><th>RUNS</th><th>ADJ. P-VALUE</th><th>RESULT</th></tr>
              </thead>
              <tbody>
                {comparison.per_task.map((row) => (
                  <tr className={row.significant_regression ? 'regression-row' : ''} key={row.task_id ?? 'overall'}>
                    <td className="task-name">{row.task_id ?? 'Overall'}</td>
                    <td>{(row.baseline_pass_rate * 100).toFixed(1)}% <span className="muted-inline">({row.baseline_passed}/{row.baseline_runs})</span></td>
                    <td className={row.significant_regression ? 'rate low' : ''}>
                      {(row.candidate_pass_rate * 100).toFixed(1)}% <span className="muted-inline">({row.candidate_passed}/{row.candidate_runs})</span>
                    </td>
                    <td>{row.baseline_runs + row.candidate_runs}</td>
                    <td>{row.adjusted_p_value?.toPrecision(3) ?? 'n/a'}</td>
                    <td><span className={`status-badge ${row.significant_regression ? 'failed' : 'passed'}`}>
                      <i />{row.significant_regression ? 'regression' : 'stable'}
                    </span></td>
                  </tr>
                ))}
                {comparison.per_task.length === 0 && (
                  <tr><td className="empty-state" colSpan={6}>No overlapping task results for these versions.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
