import { useEffect, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { fetchTrends, type RunTrend } from './api'

function MetricChart({
  title,
  data,
  dataKey,
  color,
  formatter,
  domain,
}: {
  title: string
  data: RunTrend[]
  dataKey: 'pass_rate' | 'average_cost_usd' | 'average_latency_seconds'
  color: string
  formatter: (value: number) => string
  domain?: [number | 'auto', number | 'auto']
}) {
  return (
    <article className="trend-panel">
      <div className="trend-heading"><h3>{title}</h3><span className="trend-key"><i style={{ background: color }} /> DAILY AVERAGE</span></div>
      <div className="chart-area" role="img" aria-label={`${title} trend chart`}>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#e8eee9" vertical={false} />
            <XAxis dataKey="day" tick={{ fill: '#829088', fontSize: 10 }} tickLine={false} axisLine={false} />
            <YAxis
              domain={domain}
              tickFormatter={(value: number) => formatter(value)}
              tick={{ fill: '#829088', fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              width={54}
            />
            <Tooltip formatter={(value) => formatter(Number(value))} />
            <Line dataKey={dataKey} type="monotone" stroke={color} strokeWidth={2.5} dot={{ r: 3 }} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </article>
  )
}

export function TrendsView() {
  const [trends, setTrends] = useState<RunTrend[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    fetchTrends(30)
      .then((result) => {
        if (active) setTrends(result)
      })
      .catch((requestError: unknown) => {
        if (active) {
          setError(requestError instanceof Error ? requestError.message : 'Could not load trends.')
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [])

  if (loading) return <div className="loading-panel" role="status">Loading 30-day trends…</div>
  if (error) return <div className="alert" role="alert">{error}</div>
  if (trends.length === 0) return <div className="empty-panel">Trend charts appear when scoring runs are recorded.</div>

  return (
    <section className="panel-section" aria-labelledby="trends-heading">
      <div className="section-heading">
        <div>
          <h2 id="trends-heading">Run trends</h2>
          <p className="section-subtitle">Daily performance over the last 30 days.</p>
        </div>
        <span className="result-count">{trends.length} DAYS</span>
      </div>
      <div className="trend-grid">
        <MetricChart
          title="Pass rate"
          data={trends}
          dataKey="pass_rate"
          color="#4c8b5c"
          formatter={(value) => `${(value * 100).toFixed(0)}%`}
          domain={[0, 1]}
        />
        <MetricChart
          title="Average cost"
          data={trends}
          dataKey="average_cost_usd"
          color="#c16b4e"
          formatter={(value) => `$${value.toFixed(3)}`}
        />
        <MetricChart
          title="Average latency"
          data={trends}
          dataKey="average_latency_seconds"
          color="#557b91"
          formatter={(value) => `${value.toFixed(1)}s`}
        />
      </div>
    </section>
  )
}
