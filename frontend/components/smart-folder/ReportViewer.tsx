"use client";

import { useState, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import ChartRenderer from "./ChartRenderer";

interface CitationIndex {
  [key: string]: {
    number: number;
    asset_id: string;
    preview: string;
    document_name?: string;
  };
}

interface ReportData {
  title: string;
  summary: string;
  timeline: Array<Record<string, unknown>>;
  patterns: string[];
  trends: string[];
  issues: string[];
  learnings: string[];
  recommendations: string[];
  raw_markdown?: string;
}

interface ReportViewerProps {
  report: ReportData;
  citationIndex: CitationIndex;
  visualisations?: Array<{
    type: string;
    title: string;
    data?: Array<Record<string, number | string>>;
    chart_type?: "bar" | "line" | "pie";
    x_field?: string;
    y_field?: string;
    category_field?: string;
    value_field?: string;
  }>;
  onCitationClick: (number: string) => void;
}

function CitationLink({ number, onClick }: { number: string; onClick: () => void }) {
  return (
    <sup
      onClick={onClick}
      className="inline-flex items-center justify-center mx-0.5 px-1.5 py-0.5 text-[10px] font-bold text-white bg-blue-600 rounded cursor-pointer hover:bg-blue-700 transition"
      title={`Citation [${number}]`}
    >
      {number}
    </sup>
  );
}

function Section({
  title,
  children,
  id,
}: {
  title: string;
  children: React.ReactNode;
  id: string;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div id={id} className="border-b border-gray-200 dark:border-gray-700 last:border-0">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between py-4 text-left"
      >
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{title}</h3>
        <svg
          className={`w-5 h-5 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && <div className="pb-6">{children}</div>}
    </div>
  );
}

export default function ReportViewer({ report, citationIndex, visualisations, onCitationClick }: ReportViewerProps) {
  const processedMarkdown = useMemo(() => {
    if (report.raw_markdown) return report.raw_markdown;
    // Build markdown from structured sections
    const parts: string[] = [`# ${report.title}`, "", report.summary, ""];
    if (report.timeline?.length) {
      parts.push("## Timeline", "");
      report.timeline.forEach((item) => {
        const date = item.date || item.date_precision || "Undated";
        parts.push(`- **${date}**: ${item.title || item.description || ""}`);
      });
      parts.push("");
    }
    [
      ["Patterns", report.patterns],
      ["Trends", report.trends],
      ["Issues", report.issues],
      ["Learnings", report.learnings],
      ["Recommendations", report.recommendations],
    ].forEach(([title, items]) => {
      const arr = items as string[];
      if (arr?.length) {
        parts.push(`## ${title}`, "");
        arr.forEach((item) => parts.push(`- ${item}`));
        parts.push("");
      }
    });
    return parts.join("\n");
  }, [report]);

  const toc = useMemo(() => {
    const items = [
      { id: "summary", label: "Summary" },
      ...(report.timeline?.length ? [{ id: "timeline", label: "Timeline" }] : []),
      ...(report.patterns?.length ? [{ id: "patterns", label: "Patterns" }] : []),
      ...(report.trends?.length ? [{ id: "trends", label: "Trends" }] : []),
      ...(report.issues?.length ? [{ id: "issues", label: "Issues" }] : []),
      ...(report.learnings?.length ? [{ id: "learnings", label: "Learnings" }] : []),
      ...(report.recommendations?.length ? [{ id: "recommendations", label: "Recommendations" }] : []),
      ...(visualisations?.length ? [{ id: "charts", label: "Charts" }] : []),
    ];
    return items;
  }, [report, visualisations]);

  const renderMarkdownWithCitations = (text: string) => {
    // Split text by citation markers like [1], [12], etc.
    const parts = text.split(/(\[\d+\])/g);
    return parts.map((part, idx) => {
      const match = part.match(/^\[(\d+)\]$/);
      if (match) {
        return (
          <CitationLink
            key={idx}
            number={match[1]}
            onClick={() => onCitationClick(match[1])}
          />
        );
      }
      return <span key={idx}>{part}</span>;
    });
  };

  return (
    <div className="flex gap-8">
      {/* Floating TOC */}
      <div className="hidden lg:block w-48 flex-shrink-0">
        <div className="sticky top-24">
          <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
            Contents
          </h4>
          <nav className="space-y-1">
            {toc.map((item) => (
              <a
                key={item.id}
                href={`#${item.id}`}
                className="block text-sm text-gray-600 dark:text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 transition"
              >
                {item.label}
              </a>
            ))}
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 min-w-0">
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
          {/* Title */}
          <div className="px-6 py-5 border-b border-gray-200 dark:border-gray-700">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{report.title}</h1>
          </div>

          <div className="px-6 py-4">
            {/* Summary */}
            <Section title="Executive Summary" id="summary">
              <div className="prose dark:prose-invert max-w-none text-gray-700 dark:text-gray-300 text-sm leading-relaxed">
                {renderMarkdownWithCitations(report.summary)}
              </div>
            </Section>

            {/* Timeline */}
            {report.timeline?.length > 0 && (
              <Section title="Timeline of Key Milestones" id="timeline">
                <div className="space-y-3">
                  {report.timeline.map((item, idx) => (
                    <div key={idx} className="flex gap-4 p-3 bg-gray-50 dark:bg-gray-900/50 rounded-lg">
                      <div className="text-xs font-mono text-gray-500 dark:text-gray-400 w-24 flex-shrink-0">
                        {(item.date as string) || "Undated"}
                      </div>
                      <div>
                        <p className="text-sm font-medium text-gray-900 dark:text-white">
                          {(item.title as string) || ""}
                        </p>
                        <p className="text-sm text-gray-600 dark:text-gray-400 mt-0.5">
                          {renderMarkdownWithCitations(String(item.description || ""))}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Patterns */}
            {report.patterns?.length > 0 && (
              <Section title="Pattern Analysis" id="patterns">
                <ul className="space-y-2">
                  {report.patterns.map((item, idx) => (
                    <li key={idx} className="text-sm text-gray-700 dark:text-gray-300 flex items-start gap-2">
                      <span className="text-blue-600 mt-0.5">•</span>
                      {renderMarkdownWithCitations(item)}
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            {/* Trends */}
            {report.trends?.length > 0 && (
              <Section title="Trend Analysis" id="trends">
                <ul className="space-y-2">
                  {report.trends.map((item, idx) => (
                    <li key={idx} className="text-sm text-gray-700 dark:text-gray-300 flex items-start gap-2">
                      <span className="text-blue-600 mt-0.5">•</span>
                      {renderMarkdownWithCitations(item)}
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            {/* Issues */}
            {report.issues?.length > 0 && (
              <Section title="Issues & Risks" id="issues">
                <ul className="space-y-2">
                  {report.issues.map((item, idx) => (
                    <li key={idx} className="text-sm text-gray-700 dark:text-gray-300 flex items-start gap-2">
                      <span className="text-red-500 mt-0.5">•</span>
                      {renderMarkdownWithCitations(item)}
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            {/* Learnings */}
            {report.learnings?.length > 0 && (
              <Section title="Personal Learnings" id="learnings">
                <ul className="space-y-2">
                  {report.learnings.map((item, idx) => (
                    <li key={idx} className="text-sm text-gray-700 dark:text-gray-300 flex items-start gap-2">
                      <span className="text-green-500 mt-0.5">•</span>
                      {renderMarkdownWithCitations(item)}
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            {/* Recommendations */}
            {report.recommendations?.length > 0 && (
              <Section title="Recommendations" id="recommendations">
                <ul className="space-y-2">
                  {report.recommendations.map((item, idx) => (
                    <li key={idx} className="text-sm text-gray-700 dark:text-gray-300 flex items-start gap-2">
                      <span className="text-purple-500 mt-0.5">•</span>
                      {renderMarkdownWithCitations(item)}
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            {/* Charts */}
            {visualisations && visualisations.length > 0 && (
              <Section title="Charts & Visualisations" id="charts">
                <div className="grid grid-cols-1 gap-4">
                  {visualisations.map((viz, idx) => (
                    <ChartRenderer key={idx} visualisation={viz} />
                  ))}
                </div>
              </Section>
            )}

            {/* Raw markdown fallback */}
            {report.raw_markdown && !report.summary && (
              <div className="prose dark:prose-invert max-w-none text-sm">
                <ReactMarkdown>{processedMarkdown}</ReactMarkdown>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
