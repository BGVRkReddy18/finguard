"use client";

/**
 * Chart primitives on Recharts. Conventions (data-viz method):
 * one y-axis per chart, 2px lines, rounded bar ends, recessive grid, hover tooltip on every chart,
 * series colours from validated tokens, text always in ink tokens (never the series colour).
 */
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, LabelList, Legend, Line, LineChart, ResponsiveContainer, Tooltip,
  XAxis, YAxis,
} from "recharts";

const AXIS = { stroke: "var(--ink-3)", fontSize: 12, tickLine: false, axisLine: false } as const;

function ChartTooltip({ active, payload, label, valueFormat, labelFormat }: {
  active?: boolean;
  payload?: { name?: string; value?: number; color?: string }[];
  label?: string | number;
  valueFormat?: (v: number) => string;
  labelFormat?: (l: string | number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-sm">
      <div className="mb-1 font-medium text-ink">{labelFormat && label != null ? labelFormat(label) : label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2 text-ink-2">
          <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span>{p.name}</span>
          <span className="ml-auto pl-3 font-medium tabular-nums text-ink">
            {valueFormat && p.value != null ? valueFormat(p.value) : p.value}
          </span>
        </div>
      ))}
    </div>
  );
}

export function AreaTimeChart<T extends Record<string, unknown>>({ data, x, y, name, height = 220, xFormat, yFormat }: {
  data: T[]; x: keyof T & string; y: keyof T & string; name: string; height?: number;
  xFormat?: (v: string | number) => string; yFormat?: (v: number) => string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 4 }}>
        <defs>
          <linearGradient id={`fill-${y}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--series-1)" stopOpacity={0.22} />
            <stop offset="100%" stopColor="var(--series-1)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="var(--grid)" strokeDasharray="3 3" />
        <XAxis dataKey={String(x)} {...AXIS} tickFormatter={xFormat} minTickGap={40} />
        <YAxis {...AXIS} width={52} tickFormatter={yFormat} allowDecimals={false} />
        <Tooltip content={<ChartTooltip valueFormat={yFormat} labelFormat={xFormat} />}
          cursor={{ stroke: "var(--ink-3)", strokeDasharray: "3 3" }} />
        <Area isAnimationActive={false} type="monotone" dataKey={String(y)} name={name} stroke="var(--series-1)" strokeWidth={2}
          fill={`url(#fill-${y})`} activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function ColumnChart<T extends Record<string, unknown>>({ data, x, y, name, color = "var(--series-2)", height = 200, xFormat, yFormat }: {
  data: T[]; x: keyof T & string; y: keyof T & string; name: string; color?: string; height?: number;
  xFormat?: (v: string | number) => string; yFormat?: (v: number) => string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 4 }} barCategoryGap={2}>
        <CartesianGrid vertical={false} stroke="var(--grid)" strokeDasharray="3 3" />
        <XAxis dataKey={String(x)} {...AXIS} tickFormatter={xFormat} minTickGap={40} />
        <YAxis {...AXIS} width={52} tickFormatter={yFormat} allowDecimals={false} />
        <Tooltip content={<ChartTooltip valueFormat={yFormat} labelFormat={xFormat} />} cursor={{ fill: "var(--surface-2)" }} />
        <Bar isAnimationActive={false} dataKey={String(y)} name={name} fill={color} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Horizontal bars with direct value labels — for ranked categories. */
export function RankedBars<T extends Record<string, unknown>>({ data, label, value, name, color = "var(--series-1)", valueFormat, height }: {
  data: T[]; label: keyof T & string; value: keyof T & string; name: string; color?: string;
  valueFormat?: (v: number) => string; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height ?? Math.max(120, data.length * 34)}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 48, bottom: 0, left: 0 }} barCategoryGap={6}>
        <XAxis type="number" hide />
        <YAxis type="category" dataKey={String(label)} {...AXIS} width={140} stroke="var(--ink-2)" />
        <Tooltip content={<ChartTooltip valueFormat={valueFormat} />} cursor={{ fill: "var(--surface-2)" }} />
        <Bar isAnimationActive={false} dataKey={String(value)} name={name} fill={color} radius={[0, 4, 4, 0]}>
          <LabelList dataKey={String(value)} position="right" fill="var(--ink-2)" fontSize={12}
            formatter={(v: unknown) => (valueFormat ? valueFormat(Number(v)) : String(v))} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Two series side by side on one shared 0–1 scale (e.g. rules vs model), legend + direct labels. */
export function CompareBars<T extends Record<string, unknown>>({ data, label, a, b, height = 260, valueFormat }: {
  data: T[]; label: keyof T & string; a: { key: keyof T & string; name: string }; b: { key: keyof T & string; name: string };
  height?: number; valueFormat?: (v: number) => string;
}) {
  const fmt = (v: unknown) => (valueFormat ? valueFormat(Number(v)) : String(v));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 20, right: 8, bottom: 0, left: -8 }} barGap={2} barCategoryGap="22%">
        <CartesianGrid vertical={false} stroke="var(--grid)" strokeDasharray="3 3" />
        <XAxis dataKey={String(label)} {...AXIS} stroke="var(--ink-2)" interval={0} />
        <YAxis {...AXIS} width={52} domain={[0, 1]} tickFormatter={valueFormat} />
        <Tooltip content={<ChartTooltip valueFormat={valueFormat} />} cursor={{ fill: "var(--surface-2)" }} />
        <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: "var(--ink-2)" }} />
        <Bar isAnimationActive={false} dataKey={String(a.key)} name={a.name} fill="var(--series-2)" radius={[4, 4, 0, 0]}>
          <LabelList dataKey={String(a.key)} position="top" fill="var(--ink-3)" fontSize={11} formatter={fmt} />
        </Bar>
        <Bar isAnimationActive={false} dataKey={String(b.key)} name={b.name} fill="var(--series-1)" radius={[4, 4, 0, 0]}>
          <LabelList dataKey={String(b.key)} position="top" fill="var(--ink-2)" fontSize={11} formatter={fmt} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function SimpleLine<T extends Record<string, unknown>>({ data, x, y, name, height = 240 }: {
  data: T[]; x: keyof T & string; y: keyof T & string; name: string; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 4 }}>
        <CartesianGrid vertical={false} stroke="var(--grid)" strokeDasharray="3 3" />
        <XAxis dataKey={String(x)} {...AXIS} minTickGap={30} />
        <YAxis {...AXIS} width={52} />
        <Tooltip content={<ChartTooltip />} cursor={{ stroke: "var(--ink-3)", strokeDasharray: "3 3" }} />
        <Line isAnimationActive={false} type="monotone" dataKey={String(y)} name={name} stroke="var(--series-1)" strokeWidth={2}
          dot={false} activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}
