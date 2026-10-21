import type { ScoringRun } from './api'

function DiffBlock({ diff }: { diff: string }) {
  if (!diff) return <>No tracked file changes for this run.</>
  return diff.split('\n').map((line, index) => {
    const className = line.startsWith('+++') || line.startsWith('---') || line.startsWith('@@')
      ? 'header'
      : line.startsWith('+')
        ? 'added'
        : line.startsWith('-')
          ? 'removed'
          : ''
    return <span className={`diff-line ${className}`} key={`${index}-${line}`}>{line || ' '}{'\n'}</span>
  })
}

export type TaskResultsViewProps = {
  taskIds: string[]
  taskId: string
  runs: ScoringRun[]
  selectedRun: ScoringRun | null
  detailLoading: boolean
  detailError: string
  onTaskChange: (taskId: string) => void
  onSelectRun: (runId: number) => void
}

export function TaskResultsView({
  taskIds,
  taskId,
  runs,
  selectedRun,
  detailLoading,
  detailError,
  onTaskChange,
  onSelectRun,
}: TaskResultsViewProps) {
  const taskRuns = runs.filter((run) => run.task_id === taskId)

  return (
    <section className="panel-section" aria-labelledby="task-results-heading">
      <div className="section-heading task-heading">
        <div>
          <h2 id="task-results-heading">Task results</h2>
          <p className="section-subtitle">Review repeated evaluations and the agent's workspace changes.</p>
        </div>
        <label className="select-field">
          <span>TASK</span>
          <select value={taskId} onChange={(event) => onTaskChange(event.target.value)}>
            {taskIds.map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
        </label>
      </div>

      {taskIds.length === 0 ? (
        <div className="empty-panel">Task results appear after the first scoring run.</div>
      ) : (
        <div className="task-layout">
          <div className="task-run-list" aria-label={`Runs for ${taskId}`}>
            {taskRuns.map((run) => (
              <button
                className={`task-run ${selectedRun?.id === run.id ? 'selected' : ''}`}
                key={run.id}
                onClick={() => onSelectRun(run.id)}
              >
                <span className="task-run-top"><strong>RUN-{String(run.id).padStart(4, '0')}</strong><i className={`status-badge ${run.status}`}>{run.status}</i></span>
                <span className="task-run-meta">{new Date(run.started_at).toLocaleString()}</span>
                <span className="task-run-meta">{run.tests_passed}/{run.tests_total} tests · {run.diff_size} changed lines</span>
              </button>
            ))}
            {taskRuns.length === 0 && <div className="empty-panel">No runs for this task.</div>}
          </div>

          <div className="result-detail" aria-live="polite">
            {detailError && <div className="alert" role="alert">{detailError}</div>}
            {detailLoading && <div className="empty-panel">Loading run details…</div>}
            {!detailLoading && !selectedRun && !detailError && (
              <div className="empty-panel">Choose a run to inspect its logs and patch.</div>
            )}
            {!detailLoading && selectedRun && (
              <>
                <div className="detail-summary">
                  <div>
                    <span className="eyebrow">{selectedRun.agent_version} · {selectedRun.model_version}</span>
                    <h3>Run {String(selectedRun.id).padStart(4, '0')}</h3>
                  </div>
                  <span className={`status-badge ${selectedRun.status}`}><i />{selectedRun.status}</span>
                </div>
                <div className="detail-metrics">
                  <span><b>{selectedRun.tests_passed}/{selectedRun.tests_total}</b> tests</span>
                  <span><b>{selectedRun.diff_size}</b> changed lines</span>
                  <span><b>${selectedRun.estimated_cost_usd.toFixed(3)}</b> cost</span>
                  <span><b>{selectedRun.wall_time_seconds.toFixed(1)}s</b> latency</span>
                </div>
                <section className="detail-block" aria-labelledby="diff-heading">
                  <div className="detail-block-title"><h4 id="diff-heading">Agent diff</h4><span>UNIFIED PATCH</span></div>
                  <pre className="code-panel diff-panel"><DiffBlock diff={selectedRun.diff} /></pre>
                </section>
                <section className="detail-block" aria-labelledby="logs-heading">
                  <div className="detail-block-title"><h4 id="logs-heading">Run logs</h4><span>SETUP · AGENT · TESTS</span></div>
                  <pre className="code-panel log-panel">{selectedRun.output || 'No output recorded.'}</pre>
                </section>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
