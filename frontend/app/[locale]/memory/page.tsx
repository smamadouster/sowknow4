"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { api, type MemoryListResponse, type MemoryAtomView, type MemoryProfileView } from "@/lib/api";

export const dynamic = "force-dynamic";

const KIND_LABELS: Record<string, string> = {
  fact: "fact",
  preference: "preference",
  constraint: "constraint",
  decision: "decision",
};

export default function MemoryPage() {
  const t = useTranslations("memory");
  const tCommon = useTranslations("common");

  const [data, setData] = useState<MemoryListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "pending" | "reviewed" | "rejected">("all");
  const [profile, setProfile] = useState<MemoryProfileView | null>(null);
  const [profileBusy, setProfileBusy] = useState(false);

  const loadProfile = useCallback(async () => {
    try {
      const res = await api.getMemoryProfile();
      setProfile(res.data ?? null);
    } catch (e) {
      console.error("memory.profile load failed", e);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listMemoryAtoms();
      setData(res.data ?? { atoms: [], scenarios: [], total_atoms: 0, total_scenarios: 0 });
    } catch (e) {
      setError(t("load_error"));
      console.error("memory.load failed", e);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
    loadProfile();
  }, [load, loadProfile]);

  const buildProfile = useCallback(async () => {
    setProfileBusy(true);
    setError(null);
    try {
      const res = await api.buildMemoryProfile();
      setProfile(res.data ?? null);
    } catch (e) {
      setError(t("profile_build_error"));
      console.error("memory.profile build failed", e);
    } finally {
      setProfileBusy(false);
    }
  }, [t]);

  const review = useCallback(
    async (atom: MemoryAtomView, status: "pending" | "reviewed" | "rejected") => {
      setBusyId(atom.id);
      setError(null);
      try {
        await api.reviewMemoryAtom(atom.id, status);
        await load();
      } catch (e) {
        setError(t("review_error"));
        console.error("memory.review failed", e);
      } finally {
        setBusyId(null);
      }
    },
    [load, t]
  );

  const pendingCount = (data?.atoms ?? []).filter((a) => a.status === "pending").length;
  const reviewedCount = (data?.atoms ?? []).filter((a) => a.status === "reviewed").length;

  const visibleAtoms = (data?.atoms ?? []).filter(
    (a) => filter === "all" || a.status === filter
  );

  const statusBadge = (status: string) => {
    const base =
      "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium";
    if (status === "reviewed") return `${base} bg-emerald-100 text-emerald-700`;
    if (status === "rejected") return `${base} bg-rose-100 text-rose-600`;
    return `${base} bg-amber-100 text-amber-700`;
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <main className="mx-auto max-w-5xl px-4 py-8">
        <header className="mb-8">
          <h1 className="text-2xl font-semibold text-slate-900">{t("title")}</h1>
          <p className="mt-1 text-sm text-slate-500">{t("subtitle")}</p>
        </header>

        {error && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        )}

        <section className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
              {t("count_pending")}
            </p>
            <p className="mt-1 text-2xl font-semibold text-amber-600">{pendingCount}</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
              {t("count_reviewed")}
            </p>
            <p className="mt-1 text-2xl font-semibold text-emerald-600">{reviewedCount}</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
              {t("count_total")}
            </p>
            <p className="mt-1 text-2xl font-semibold text-slate-800">
              {data?.total_atoms ?? 0}
            </p>
          </div>
        </section>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          {(["all", "pending", "reviewed", "rejected"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                filter === f
                  ? "bg-slate-900 text-white"
                  : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-100"
              }`}
            >
              {t(`filter_${f}`)}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-400">
            {tCommon("loading")}
          </div>
        ) : visibleAtoms.length === 0 ? (
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
            {t("empty")}
          </div>
        ) : (
          <ul className="space-y-3">
            {visibleAtoms.map((atom) => (
              <li
                key={atom.id}
                className="rounded-xl border border-slate-200 bg-white p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                        {t(`kind_${atom.kind}`) ?? KIND_LABELS[atom.kind] ?? atom.kind}
                      </span>
                      <span className={statusBadge(atom.status)}>
                        {t(`status_${atom.status}`)}
                      </span>
                      <span className="text-xs text-slate-400">
                        {t("confidence")}: {atom.confidence}
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-relaxed text-slate-800">
                      {atom.statement}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {atom.source_session_ids.length > 0
                        ? `${atom.source_session_ids.length} ${t("source_sessions")}`
                        : ""}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    {atom.status !== "reviewed" && (
                      <button
                        onClick={() => review(atom, "reviewed")}
                        disabled={busyId === atom.id}
                        className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
                      >
                        {t("approve")}
                      </button>
                    )}
                    {atom.status !== "rejected" && (
                      <button
                        onClick={() => review(atom, "rejected")}
                        disabled={busyId === atom.id}
                        className="rounded-lg bg-white px-3 py-1.5 text-sm font-medium text-rose-600 ring-1 ring-rose-200 transition-colors hover:bg-rose-50 disabled:opacity-50"
                      >
                        {t("reject")}
                      </button>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}

        {(data?.scenarios ?? []).length > 0 && (
          <section className="mt-8">
            <h2 className="mb-3 text-lg font-semibold text-slate-900">{t("scenarios_title")}</h2>
            <ul className="space-y-3">
              {(data?.scenarios ?? []).map((scen) => (
                <li key={scen.id} className="rounded-xl border border-slate-200 bg-white p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-md bg-cyan-100 px-2 py-0.5 text-xs font-medium text-cyan-700">
                      {scen.scope || t("kind_scenario")}
                    </span>
                    <span className={statusBadge(scen.status)}>
                      {t(`status_${scen.status}`)}
                    </span>
                  </div>
                  <p className="mt-2 text-sm font-semibold text-slate-800">{scen.title}</p>
                  <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-slate-600">
                    {scen.summary}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="mt-8 rounded-xl border border-slate-200 bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">{t("profile_title")}</h2>
              <p className="text-sm text-slate-500">
                {t("profile_subtitle")}
                {profile?.version ? ` — v${profile.version}` : ""}
              </p>
            </div>
            <button
              onClick={buildProfile}
              disabled={profileBusy}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:opacity-50"
            >
              {profileBusy ? t("profile_building") : t("profile_build")}
            </button>
          </div>
          {profile && profile.version > 0 ? (
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <h3 className="text-xs font-medium uppercase tracking-wide text-slate-400">
                  {t("profile_persona")}
                </h3>
                <ul className="mt-2 space-y-1 text-sm text-slate-700">
                  {Object.entries(profile.persona ?? {}).map(([k, v]) => (
                    <li key={k} className="flex gap-2">
                      <span className="font-medium capitalize text-slate-500">{k}:</span>
                      <span>{Array.isArray(v) ? (v as string[]).join(", ") : String(v)}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="text-xs font-medium uppercase tracking-wide text-slate-400">
                  {t("profile_patterns")}
                </h3>
                <ul className="mt-2 space-y-1 text-sm text-slate-700">
                  {(profile.stable_patterns ?? []).map((p, i) => (
                    <li key={i}>• {p}</li>
                  ))}
                  {(profile.stable_patterns ?? []).length === 0 && (
                    <li className="text-slate-400">{t("profile_empty")}</li>
                  )}
                </ul>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-400">{t("profile_none")}</p>
          )}
        </section>
      </main>
    </div>
  );
}
