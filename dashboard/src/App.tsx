import { useEffect, useMemo, useState } from 'react'

import {
  compareVersions,
  fetchRun,
  fetchRuns,
  type ComparisonReport,
  type ScoringRun,
  type VersionLabel,
  versionKey,
} from './api'
import { RunTable } from './RunTable'
import { TaskResultsView } from './TaskResultsView'
import { TrendsView } from './TrendsView'
import { VersionCompareView } from './VersionCompareView'

type View = 'runs' | 'tasks' | 'compare' | 'trends'

const views: { id: View; label: string; glyph: string }[] = [
  { id: 'runs', label: 'Runs', glyph: '▤' },
  { id: 'tasks', label: 'Tasks', glyph: '⌘' },
  { id: 'compare', label: 'Compare', glyph: '⇄' },
  { id: 'trends', label: 'Trends', glyph: '⌁' },
]

function App() {
  const [view, setView] = useState<View>('runs')
  const [runs, setRuns] = useState<ScoringRun[]>([])
  const [runsLoading, setRunsLoading] = useState(true)
  const [runsError, setRunsError] = useState('')
  const [selectedTaskId, setSelectedTaskId] = useState('')
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null)
  const [selectedRun, setSelectedRun] = useState<ScoringRun | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [baselineKey, setBaselineKey] = useState('')
  const [candidateKey, setCandidateKey] = useState('')
  const [comparison, setComparison] = useState<ComparisonReport | null>(null)
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [comparisonError, setComparisonError] = useState('')

  async function refreshRuns() {
    setRunsLoading(true)
    try {
      const results = await fetchRuns()
      setRuns(results)
      setRunsError('')
    } catch (error) {
      setRunsError(error instanceof Error ? error.message : 'Could not load scoring runs.')
    } finally {
      setRunsLoading(false)
    }
  }

  useEffect(() => {
    void refreshRuns()
  }, [])

  const taskIds = useMemo(
    () => [...new Set(runs.map((run) => run.task_id))].sort(),
    [runs],
  )
  const versions = useMemo(() => {
    const unique = new Map<string, VersionLabel>()
    for (const run of runs) {
      const version = {
        agent_version: run.agent_version,
        model_version: run.model_version,
        prompt_hash: run.prompt_hash,
        git_sha: run.git_sha,
      }
      unique.set(versionKey(version), version)
    }
    return [...unique.values()]
  }, [runs])

  useEffect(() => {
    if (taskIds.length > 0 && !taskIds.includes(selectedTaskId)) {
      setSelectedTaskId(taskIds[0])
    }
  }, [selectedTaskId, taskIds])

  useEffect(() => {
    if (versions.length < 2) return
    const keys = versions.map(versionKey)
    if (!keys.includes(baselineKey)) setBaselineKey(keys[keys.length - 1])
    if (!keys.includes(candidateKey)) setCandidateKey(keys[0])
  }, [baselineKey, candidateKey, versions])

  useEffect(() => {
    if (selectedRunId === null) {
      setSelectedRun(null)
      setDetailError('')
      return
    }
    let active = true
    setDetailLoading(true)
    fetchRun(selectedRunId)
      .then((result) => {
        if (active) {
          setSelectedRun(result)
          setDetailError('')
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setDetailError(error instanceof Error ? error.message : 'Could not load run detail.')
          setSelectedRun(null)
        }
      })
      .finally(() => {
        if (active) setDetailLoading(false)
      })
    return () => { active = false }
  }, [selectedRunId])

  const versionByKey = (key: string) => versions.find((version) => versionKey(version) === key)

  async function runComparison() {
    const baseline = versionByKey(baselineKey)
    const candidate = versionByKey(candidateKey)
    if (!baseline || !candidate) return
    setComparisonLoading(true)
    setComparisonError('')
    try {
      setComparison(await compareVersions(baseline, candidate))
    } catch (error) {
      setComparisonError(error instanceof Error ? error.message : 'Could not compare versions.')
      setComparison(null)
    } finally {
      setComparisonLoading(false)
    }
  }

  function inspectRun(run: ScoringRun) {
    setSelectedTaskId(run.task_id)
    setSelectedRunId(run.id)
    setView('tasks')
  }

  const heading: Record<View, { title: string; subtitle: string }> = {
    runs: { title: 'Evaluation runs', subtitle: 'Recent task outcomes across agent and model versions.' },
    tasks: { title: 'Task results', subtitle: 'Inspect individual attempts, agent output, and workspace diffs.' },
    compare: { title: 'Version comparison', subtitle: 'Identify statistically significant pass-rate regressions.' },
    trends: { title: 'Run trends', subtitle: 'Track quality, estimated cost, and latency over time.' },
  }

  return (
    <main className="shell">
      <aside className="rail">
        <a className="brand" href="#runs" onClick={(event) => { event.preventDefault(); setView('runs') }} aria-label="AgentEval home">
          <span className="brand-mark">A<span>/</span>E</span>
          <span className="brand-name">AgentEval</span>
        </a>
        <nav aria-label="Primary navigation" role="tablist">
          {views.map((item) => (
            <button
              aria-selected={view === item.id}
              className={`nav-link ${view === item.id ? 'active' : ''}`}
              key={item.id}
              onClick={() => setView(item.id)}
              role="tab"
            >
              <span className="nav-glyph" aria-hidden="true">{item.glyph}</span>{item.label}
            </button>
          ))}
        </nav>
        <div className="rail-bottom"><span className="status-dot" /><span>Evaluation workspace</span></div>
      </aside>

      <section className="content">
        <header className="topbar">
          <div className="crumb">WORKSPACE <span>/</span> {view.toUpperCase()}</div>
          <button className="refresh-button" onClick={() => void refreshRuns()} disabled={runsLoading}>
            <span aria-hidden="true">↻</span> Refresh runs
          </button>
        </header>

        <div className="page-heading">
          <div>
            <p className="eyebrow">AGENT BENCHMARKS <span>•</span> LIVE</p>
            <h1>{heading[view].title}</h1>
            <p className="lede">{heading[view].subtitle}</p>
          </div>
          <div className="run-count"><strong>{runs.length.toLocaleString()}</strong><span>loaded runs</span></div>
        </div>

        {runsError && view !== 'trends' && view !== 'runs' && (
          <div className="alert" role="alert">{runsError}</div>
        )}
        {view === 'runs' && (
          <RunTable runs={runs} loading={runsLoading} error={runsError} onSelectRun={inspectRun} />
        )}
        {view === 'tasks' && (
          <TaskResultsView
            taskIds={taskIds}
            taskId={selectedTaskId}
            runs={runs}
            selectedRun={selectedRun}
            detailLoading={detailLoading}
            detailError={detailError}
            onTaskChange={(taskId) => { setSelectedTaskId(taskId); setSelectedRunId(null) }}
            onSelectRun={setSelectedRunId}
          />
        )}
        {view === 'compare' && (
          <VersionCompareView
            versions={versions}
            baselineKey={baselineKey}
            candidateKey={candidateKey}
            comparison={comparison}
            loading={comparisonLoading}
            error={comparisonError}
            onBaselineChange={setBaselineKey}
            onCandidateChange={setCandidateKey}
            onCompare={() => void runComparison()}
          />
        )}
        {view === 'trends' && <TrendsView />}
        <footer><span>AGENTEVAL</span><span>Docker-isolated scoring · SQLite history</span></footer>
      </section>
    </main>
  )
}

export default App
