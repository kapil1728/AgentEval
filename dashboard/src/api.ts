export type RunStatus = 'passed' | 'failed' | 'timeout'

export type ScoringRun = {
  id: number
  task_id: string
  agent_version: string
  model_version: string
  prompt_hash: string
  git_sha: string
  passed: boolean
  status: RunStatus
  tests_passed: number
  tests_total: number
  diff_size: number
  wall_time_seconds: number
  input_tokens: number
  output_tokens: number
  tool_call_count: number
  estimated_cost_usd: number
  started_at: string
  output: string
  diff: string
}

export type VersionLabel = {
  agent_version: string
  model_version: string
  prompt_hash: string
  git_sha: string
}

export type RegressionStats = {
  task_id: string | null
  baseline_runs: number
  baseline_passed: number
  baseline_pass_rate: number
  candidate_runs: number
  candidate_passed: number
  candidate_pass_rate: number
  p_value: number | null
  adjusted_p_value: number | null
  significant_regression: boolean
}

export type ComparisonReport = {
  baseline: VersionLabel
  candidate: VersionLabel
  alpha: number
  overall: RegressionStats
  per_task: RegressionStats[]
}

export type RunTrend = {
  day: string
  task_id: string | null
  runs: number
  passed: number
  pass_rate: number
  average_latency_seconds: number
  average_cost_usd: number
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(body?.detail ?? `Request failed (${response.status})`)
  }
  return (await response.json()) as T
}

export function fetchRuns(): Promise<ScoringRun[]> {
  return requestJson<ScoringRun[]>('/scoring/runs?limit=500')
}

export function fetchRun(runId: number): Promise<ScoringRun> {
  return requestJson<ScoringRun>(`/scoring/runs/${runId}`)
}

export function compareVersions(
  baseline: VersionLabel,
  candidate: VersionLabel,
): Promise<ComparisonReport> {
  return requestJson<ComparisonReport>('/scoring/compare', {
    method: 'POST',
    body: JSON.stringify({ baseline, candidate }),
  })
}

export function fetchTrends(days = 30): Promise<RunTrend[]> {
  return requestJson<RunTrend[]>(`/scoring/trends?days=${days}`)
}

export function versionKey(version: VersionLabel): string {
  return [
    version.agent_version,
    version.model_version,
    version.prompt_hash,
    version.git_sha,
  ].join('|')
}

export function versionLabel(version: VersionLabel): string {
  return `${version.agent_version} · ${version.model_version} · ${version.prompt_hash.slice(0, 8)} · ${version.git_sha.slice(0, 8)}`
}
