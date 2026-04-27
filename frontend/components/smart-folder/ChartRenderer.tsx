"use client";

import { useMemo } from "react";
import dynamic from "next/dynamic";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

// Dynamically import VegaLiteChart to avoid SSR/build issues with node-canvas
const VegaLiteChart = dynamic(
  () => import("./VegaLiteChart"),
  { ssr: false, loading: () => <div className="h-64 animate-pulse bg-gray-100 dark:bg-gray-700 rounded-lg" /> }
);

interface ChartRendererProps {
  visualisation: {
    type: string;
    title: string;
    spec?: Record<string, unknown>;
    data?: Array<Record<string, number | string>>;
    chart_type?: "bar" | "line" | "pie" | "vega-lite";
    x_field?: string;
    y_field?: string;
    category_field?: string;
    value_field?: string;
  };
}

const COLORS = ["#4c78a8", "#f58518", "#e45756", "#72b7b2", "#54a24b", "#eeca3b", "#b279a2", "#ff9da6"];

export default function ChartRenderer({ visualisation }: ChartRendererProps) {
  const data = visualisation.data || [];
  const chartType = visualisation.chart_type || "bar";
  const title = visualisation.title || "Chart";
  const vegaSpec = visualisation.spec;

  const xField = visualisation.x_field || Object.keys(data[0] || {})[0] || "x";
  const yField = visualisation.y_field || Object.keys(data[0] || {})[1] || "y";
  const categoryField = visualisation.category_field || Object.keys(data[0] || {})[0] || "name";
  const valueField = visualisation.value_field || Object.keys(data[0] || {})[1] || "value";

  const chart = useMemo(() => {
    if (chartType === "line") {
      return (
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={xField} />
            <YAxis />
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey={yField} stroke="#4c78a8" strokeWidth={2} dot />
          </LineChart>
        </ResponsiveContainer>
      );
    }

    if (chartType === "pie") {
      return (
        <ResponsiveContainer width="100%" height={300}>
          <PieChart>
            <Tooltip />
            <Legend />
            <Pie
              data={data}
              dataKey={valueField}
              nameKey={categoryField}
              cx="50%"
              cy="50%"
              outerRadius={100}
              label
            >
              {data.map((_, index) => (
                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      );
    }

    // Default bar
    return (
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={xField} />
          <YAxis />
          <Tooltip />
          <Legend />
          <Bar dataKey={yField} fill="#4c78a8" />
        </BarChart>
      </ResponsiveContainer>
    );
  }, [data, chartType, xField, yField, categoryField, valueField]);

  // If Vega-Lite spec is provided, render it via dynamically-imported component
  if (vegaSpec && chartType === "vega-lite") {
    return <VegaLiteChart spec={vegaSpec} title={title} />;
  }

  if (!data.length && !vegaSpec) {
    return (
      <div className="p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
        <p className="text-sm text-gray-500 dark:text-gray-400">Chart data unavailable.</p>
      </div>
    );
  }

  return (
    <div className="p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm">
      <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">{title}</h4>
      {chart}
    </div>
  );
}
