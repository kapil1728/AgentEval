import type { ScoringRun } from './api'

export type RunTableProps = {
  runs: ScoringRun[]
  loading: boolean
  error: string
  onSelectRun: (run: ScoringRun) => void
}

export function RunTable({ runs, loading, error, onSelectRun }: RunTableProps) {
  return (
    <section className="panel-section" aria-labelledby="runs-heading">
      <div className="section-heading">
        <div>
          <h2 id="runs-heading">Run history</h2>
          <p className="section-subtitle">Select a run to inspect its task result, logs, and patch.</p>
        </div>
        <span className="result-count">{runs.length} LOADED</span>
      </div>
      {error && <div className="alert" role="alert">{error}</div>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>TASK</th><th>AGENT / MODEL</th><th>GIT</th><th>RESULT</th>
              <th>TESTS</th><th>DIFF</th><th>COST</th><th>TIME</th><th />
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id}>
                <td>
                  <span className="task-name">{run.task_id}</span>
                  <span className="run-id">RUN-{String(run.id).padStart(4, '0')}</span>
                </td>
                <td>
                  <span>{run.agent_version}</span>
                  <span className="muted-line">{run.model_version}</span>
                </td>
                <td><span className="version-tag">{run.git_sha.slice(0, 8)}</span></td>
                <td><span className={`status-badge ${run.status}`}><i />{run.status}</span></td>
                <td>{run.tests_passed}/{run.tests_total}</td>
                <td>{run.diff_size} lines</td>
                <td>${run.estimated_cost_usd.toFixed(3)}</td>
                <td>{run.wall_time_seconds.toFixed(1)}s</td>
                <td>
                  <button className="text-action" onClick={() => onSelectRun(run)}>
                    Inspect <span aria-hidden="true">↗</span>
                  </button>
                </td>
              </tr>
            ))}
            {loading && <tr><td className="empty-state" colSpan={9}>Loading run records…</td></tr>}
            {!loading && !error && runs.length === 0 && (
              <tr><td className="empty-state" colSpan={9}>No scoring runs have been recorded.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
