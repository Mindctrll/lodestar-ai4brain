import { GaugeChart, HeatmapChart, LineChart, RadarChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  RadarComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import ReactEChartsCore from 'echarts-for-react/esm/core'

import type { AcsView, ForecastView, ProgressView, Registry, TwinView } from '../api/types'

echarts.use([
  RadarChart,
  LineChart,
  HeatmapChart,
  GaugeChart,
  RadarComponent,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  VisualMapComponent,
  MarkAreaComponent,
  SVGRenderer,
])

const ACCENT = '#2f6fed'
const BAND = 'rgba(47, 111, 237, 0.16)'
const MUTED = '#6b6b76'
const reducedMotion =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

type Series = Record<string, unknown> & { name?: string }
type Option = Record<string, unknown> & { series: Series[] }

/** One chart. `data-series` lists its series, so tests can check every chart draws its range. */
function Chart({
  option,
  label,
  height = 300,
}: {
  option: Option
  label: string
  height?: number
}) {
  return (
    <div
      className="chart"
      role="img"
      aria-label={label}
      data-testid="chart"
      data-series={option.series.map((s) => s.name ?? '').join('|')}
    >
      <ReactEChartsCore
        echarts={echarts}
        option={{ animation: !reducedMotion, ...option }}
        style={{ height }}
        opts={{ renderer: 'svg' }}
        notMerge
      />
    </div>
  )
}

const round = (x: number) => Math.round(x)

/** Radar with an uncertainty ring: the shaded ring between the inner and outer outline is the
 * 80% range; the line is the estimate (docs/plan/13, chart 1). */
export function Radar({ twin, registry }: { twin: TwinView; registry: Registry }) {
  const dims = twin.dims.filter((d) => {
    const def = registry.dimensions.find((x) => x.id === d.dim)
    return d.n > 0 && def && !def.style
  })
  if (dims.length < 3)
    return <p className="muted">The radar appears after three skills are measured.</p>
  const name = (id: string) => registry.dimensions.find((x) => x.id === id)?.name ?? id
  const option: Option = {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, data: ['80% range', 'Estimate'] },
    radar: {
      indicator: dims.map((d) => ({ name: name(d.dim), max: 100 })),
      radius: '62%',
      splitArea: { show: false },
      axisName: { color: MUTED },
    },
    series: [
      {
        name: '80% range',
        type: 'radar',
        symbol: 'none',
        data: [
          {
            value: dims.map((d) => round(d.percent_high)),
            name: '80% range',
            lineStyle: { color: ACCENT, opacity: 0.35 },
            areaStyle: { color: BAND },
          },
          {
            value: dims.map((d) => round(d.percent_low)),
            name: '80% range (low)',
            lineStyle: { color: ACCENT, opacity: 0.35 },
            areaStyle: { color: '#ffffff', opacity: 1 },
          },
        ],
      },
      {
        name: 'Estimate',
        type: 'radar',
        data: [
          {
            value: dims.map((d) => round(d.percent)),
            name: 'Estimate',
            lineStyle: { color: ACCENT, width: 2 },
            itemStyle: { color: ACCENT },
          },
        ],
      },
    ],
  }
  return <Chart option={option} label="Radar of your skills with their 80% ranges" height={340} />
}

/** A skill's progress: estimate line with its range band, a dot per practice day, life-context
 * strips, and the growth forecast continuing as a dashed, hatched band (chart 2). */
export function SkillCurve({
  twin,
  dim,
  forecast,
  strips,
  name,
}: {
  twin: TwinView
  dim: string
  forecast: ForecastView | undefined
  strips: ProgressView['life_context']
  name: string
}) {
  const points = (twin.curves ?? []).filter((c) => c.dim === dim)
  if (points.length === 0) return <p className="muted">No practice days yet for {name}.</p>
  const days = points.map((p) => p.day)
  const last = points[points.length - 1]
  const ahead = forecast ? new Date(`${String(last?.day)}T00:00:00Z`) : null
  if (ahead && forecast) ahead.setUTCDate(ahead.getUTCDate() + forecast.sessions_ahead)
  const future = ahead ? ahead.toISOString().slice(0, 10) : null
  const axis = future ? [...days, future] : days
  const at = (values: (number | null)[]) => [...values, ...(future ? [null] : [])]
  const series: Option['series'] = [
    {
      name: 'Range low',
      type: 'line',
      data: at(points.map((p) => round(p.low))),
      stack: 'range',
      lineStyle: { opacity: 0 },
      symbol: 'none',
      silent: true,
    },
    {
      name: '80% range',
      type: 'line',
      data: at(points.map((p) => round(p.high - p.low))),
      stack: 'range',
      lineStyle: { opacity: 0 },
      areaStyle: { color: BAND },
      symbol: 'none',
    },
    {
      name: 'Estimate',
      type: 'line',
      data: at(points.map((p) => round(p.percent))),
      lineStyle: { color: ACCENT, width: 2 },
      itemStyle: { color: ACCENT },
      symbolSize: 7,
      markArea: {
        silent: true,
        itemStyle: { color: 'rgba(240, 160, 60, 0.12)' },
        label: { color: MUTED, fontSize: 11 },
        // Only strips that overlap the chart, snapped to its days (a category axis).
        data: strips.flatMap((s) => {
          const from = axis.find((d) => d >= s.start.slice(0, 10))
          const to = [...axis].reverse().find((d) => d < s.end.slice(0, 10))
          return from && to && from <= to ? [[{ name: s.label, xAxis: from }, { xAxis: to }]] : []
        }),
      },
    },
  ]
  if (forecast && future && last) {
    const base = days.map(() => null)
    series.push(
      {
        name: 'Forecast range low',
        type: 'line',
        data: [...base.slice(0, -1), round(last.percent), round(forecast.low)],
        stack: 'forecast',
        lineStyle: { opacity: 0 },
        symbol: 'none',
        silent: true,
      },
      {
        name: 'Forecast 80% range',
        type: 'line',
        data: [...base.slice(0, -1), 0, round(forecast.high - forecast.low)],
        stack: 'forecast',
        lineStyle: { color: ACCENT, type: 'dashed', opacity: 0.5 },
        areaStyle: { color: 'rgba(47, 111, 237, 0.08)', decal: { symbol: 'line', dashArrayX: 4 } },
        symbol: 'none',
      },
      {
        name: 'Forecast',
        type: 'line',
        data: [...base.slice(0, -1), round(last.percent), round(forecast.median)],
        lineStyle: { color: ACCENT, type: 'dashed' },
        itemStyle: { color: '#ffffff', borderColor: ACCENT },
        symbol: 'emptyCircle',
      },
    )
  }
  const option: Option = {
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 16, top: 16, bottom: 30 },
    xAxis: { type: 'category', data: axis, boundaryGap: false },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
    series,
  }
  return (
    <Chart
      option={option}
      label={`${name}: estimate over time with its 80% range${forecast ? ', and the forecast range' : ''}`}
      height={260}
    />
  )
}

/** Skill x week: change in the estimate (colour) and rounds played (number) (chart 3a). */
export function WeekHeatmap({
  progress,
  name,
}: {
  progress: ProgressView
  name: (id: string) => string
}) {
  const h = progress.by_week
  if (h.skills.length === 0) return <p className="muted">Play a few rounds to see this.</p>
  const data = h.skills.flatMap((_, s) =>
    h.weeks.map((_, w) => [w, s, h.change[s]?.[w] ?? null, h.rounds[s]?.[w] ?? 0]),
  )
  const option: Option = {
    tooltip: {
      formatter: (p: { value: [number, number, number | null, number] }) => {
        const [w, s, change, rounds] = p.value
        const what =
          change === null
            ? 'no change measured'
            : `${change > 0 ? '+' : ''}${String(change)} points`
        return `${name(h.skills[s] ?? '')}, week of ${h.weeks[w] ?? ''}: ${what}, ${String(rounds)} rounds`
      },
    },
    grid: { left: 130, right: 16, top: 10, bottom: 70 },
    xAxis: { type: 'category', data: h.weeks.map((w) => w.slice(5)) },
    yAxis: { type: 'category', data: h.skills.map(name) },
    visualMap: {
      min: -10,
      max: 10,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemWidth: 10,
      itemHeight: 140,
      inRange: { color: ['#f2b8a2', '#f7f7f8', '#9cb8f5'] },
      text: ['up 10 points', 'down 10'],
      textStyle: { color: MUTED, fontSize: 11 },
    },
    series: [
      {
        name: 'Change per week (rounds as labels)',
        type: 'heatmap',
        data,
        label: {
          show: true,
          formatter: (p: { value: number[] }) => (p.value[3] ? String(p.value[3]) : ''),
        },
      },
    ],
  }
  return (
    <Chart
      option={option}
      label="Heatmap of change per skill and week"
      height={Math.max(220, h.skills.length * 30 + 90)}
    />
  )
}

/** Time of day x weekday: share of answers right, in the user's time zone (chart 3b). */
export function HourHeatmap({ progress }: { progress: ProgressView }) {
  const h = progress.by_hour
  const data = h.hours.flatMap((_, b) =>
    h.weekdays.map((_, d) => [d, b, h.accuracy[b]?.[d] ?? null, h.answers[b]?.[d] ?? 0]),
  )
  const option: Option = {
    tooltip: {
      formatter: (p: { value: [number, number, number | null, number] }) => {
        const [d, b, acc, n] = p.value
        const where = `${h.weekdays[d] ?? ''} ${h.hours[b] ?? ''}`
        return acc === null
          ? `${where}: fewer than ${String(h.min_answers)} answers`
          : `${where}: ${String(Math.round(acc * 100))}% right of ${String(n)} answers`
      },
    },
    grid: { left: 60, right: 16, top: 10, bottom: 70 },
    xAxis: { type: 'category', data: h.weekdays },
    yAxis: { type: 'category', data: h.hours },
    visualMap: {
      min: 0.5,
      max: 1,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemWidth: 10,
      itemHeight: 140,
      inRange: { color: ['#fbe3d6', '#eef2fd', '#7fa2f0'] },
      text: ['100% right', '50%'],
      textStyle: { color: MUTED, fontSize: 11 },
    },
    series: [
      {
        name: 'Share right (with answer counts)',
        type: 'heatmap',
        data,
        label: {
          show: true,
          color: '#16161a',
          formatter: (p: { value: (number | null)[] }) =>
            p.value[2] === null || p.value[2] === undefined
              ? ''
              : `${String(Math.round(p.value[2] * 100))}%`,
        },
      },
    ],
  }
  return (
    <Chart option={option} label="Heatmap of how often you are right by time of day and weekday" />
  )
}

/** The AI Collaboration Score as a gauge, with its 80% range shaded on the dial (chart 5). */
export function AcsGauge({ acs }: { acs: AcsView }) {
  if (acs.score === null || acs.low === null || acs.high === null)
    return <p className="muted">Not enough collaboration moments yet to give a score.</p>
  const option: Option = {
    series: [
      {
        name: 'Score with 80% range',
        type: 'gauge',
        min: 0,
        max: 100,
        startAngle: 200,
        endAngle: -20,
        axisLine: {
          lineStyle: {
            width: 16,
            color: [
              [acs.low / 100, '#e6e6ea'],
              [acs.high / 100, '#9cb8f5'],
              [1, '#e6e6ea'],
            ],
          },
        },
        pointer: { itemStyle: { color: ACCENT }, width: 5 },
        splitNumber: 5,
        axisTick: { show: false },
        splitLine: { length: 10, lineStyle: { color: '#c9ccd6' } },
        axisLabel: { distance: 22, color: MUTED, fontSize: 11 },
        detail: {
          formatter: () =>
            `${String(round(acs.score ?? 0))}\n${String(round(acs.low ?? 0))}-${String(round(acs.high ?? 0))}`,
          fontSize: 18,
          color: '#16161a',
          offsetCenter: [0, '55%'],
        },
        data: [{ value: round(acs.score) }],
      },
    ],
  }
  return <Chart option={option} label="AI Collaboration Score with its 80% range" height={260} />
}
