import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import {
  compareVersions,
  fetchRun,
  fetchRuns,
  fetchTrends,
  type ComparisonReport,
  type ScoringRun,
  type VersionLabel,
} from './api'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return {
    ...actual,
    compareVersions: vi.fn(),
    fetchRun: vi.fn(),
    fetchRuns: vi.fn(),
    fetchTrends: vi.fn(),
  }
})

const runA: ScoringRun = {
  id: 11,
  task_id: 'bugfix-clamp',
  agent_version: 'agent-a',
  model_version: 'model-x',
  prompt_hash: 'prompt-a1b2c3d4',
  git_sha: 'git-a1b2c3d4',
  passed: true,
  status: 'passed',
  tests_passed: 4,
  tests_total: 4,
  diff_size: 2,
  wall_time_seconds: 8.4,
  input_tokens: 100,
  output_tokens: 25,
  tool_call_count: 3,
  estimated_cost_usd: 0.004,
  started_at: '2026-10-15T09:20:00Z',
  output: 'agent completed change',
  diff: '--- /dev/null\n+++ b/bounds.py\n@@ -0,0 +1,2 @@\n+def clamp():\n+    return 0\n',
}

const runB: ScoringRun = {
  ...runA,
  id: 12,
  agent_version: 'agent-b',
  prompt_hash: 'prompt-b1b2c3d4',
  git_sha: 'git-b1b2c3d4',
  passed: false,
  status: 'failed',
  tests_passed: 2,
  output: 'tests failed',
}

const regression: ComparisonReport = {
  baseline: versionOf(runA),
  candidate: versionOf(runB),
  alpha: 0.05,
  overall: {
    task_id: null,
    baseline_runs: 10,
    baseline_passed: 10,
    baseline_pass_rate: 1,
    candidate_runs: 10,
    candidate_passed: 2,
    candidate_pass_rate: 0.2,
    p_value: 0.0001,
    adjusted_p_value: 0.0001,
    significant_regression: true,
  },
  per_task: [],
}

function versionOf(run: ScoringRun): VersionLabel {
  return {
    agent_version: run.agent_version,
    model_version: run.model_version,
    prompt_hash: run.prompt_hash,
    git_sha: run.git_sha,
  }
}

const mockedFetchRuns = vi.mocked(fetchRuns)
const mockedFetchRun = vi.mocked(fetchRun)
const mockedCompareVersions = vi.mocked(compareVersions)
const mockedFetchTrends = vi.mocked(fetchTrends)

beforeEach(() => {
  vi.resetAllMocks()
  mockedFetchRuns.mockResolvedValue([runB, runA])
  mockedFetchRun.mockResolvedValue(runA)
  mockedCompareVersions.mockResolvedValue(regression)
  mockedFetchTrends.mockResolvedValue([
    {
      day: '2026-10-15',
      task_id: null,
      runs: 12,
      passed: 9,
      pass_rate: 0.75,
      average_latency_seconds: 8.4,
      average_cost_usd: 0.004,
    },
  ])
})

describe('AgentEval dashboard', () => {
  it('shows loading then scoring runs from the API', async () => {
    let resolveRuns: (runs: ScoringRun[]) => void = () => undefined
    mockedFetchRuns.mockReturnValue(new Promise((resolve) => { resolveRuns = resolve }))
    render(<App />)

    expect(screen.getByText('Loading run records…')).toBeInTheDocument()
    resolveRuns([runA])

    expect(await screen.findByText('bugfix-clamp')).toBeInTheDocument()
    expect(screen.getByText('4/4')).toBeInTheDocument()
  })

  it('shows API errors without hiding the runs view', async () => {
    mockedFetchRuns.mockRejectedValue(new Error('Database is unavailable'))
    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Database is unavailable')
    expect(screen.getByRole('heading', { name: 'Evaluation runs' })).toBeInTheDocument()
  })

  it('loads per-run detail and displays its diff and logs', async () => {
    render(<App />)
    const inspectButtons = await screen.findAllByRole('button', { name: /Inspect/ })
    fireEvent.click(inspectButtons[1])

    expect(await screen.findByRole('heading', { name: 'Run 0011' })).toBeInTheDocument()
    expect(screen.getByText('+def clamp():')).toBeInTheDocument()
    expect(screen.getByText('agent completed change')).toBeInTheDocument()
    expect(mockedFetchRun).toHaveBeenCalledWith(11)
  })

  it('highlights a significant regression in version comparison', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('tab', { name: 'Compare' }))
    const compareButton = await screen.findByRole('button', { name: 'Compare versions' })
    await waitFor(() => expect(compareButton).toBeEnabled())
    fireEvent.click(compareButton)

    expect(await screen.findByText('SIGNIFICANT REGRESSION')).toBeInTheDocument()
    expect(mockedCompareVersions).toHaveBeenCalledWith(versionOf(runA), versionOf(runB))
  })

  it('renders pass-rate, cost, and latency trend charts', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('tab', { name: 'Trends' }))

    await waitFor(() => expect(mockedFetchTrends).toHaveBeenCalledWith(30))
    expect(await screen.findByRole('img', { name: 'Pass rate trend chart' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Average cost trend chart' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Average latency trend chart' })).toBeInTheDocument()
  })
})
