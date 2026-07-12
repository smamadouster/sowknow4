'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect, useMemo, useRef } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useIsMobile } from '@/hooks/useIsMobile';
import MobileSheet from '@/components/mobile/MobileSheet';
import FAB from '@/components/mobile/FAB';
import { api } from '@/lib/api';

interface Subscription {
  id: string;
  name: string;
  domain: string;
  price: number;
  billingCycle: 'monthly' | 'yearly';
  description: string;
  lastPayment: string;
  status: 'active' | 'unused';
  color: string;
}

const PRESET_COLORS = [
  'from-emerald-500 to-teal-600',
  'from-blue-500 to-indigo-600',
  'from-violet-500 to-purple-600',
  'from-rose-500 to-pink-600',
  'from-amber-500 to-orange-600',
  'from-cyan-500 to-sky-600',
  'from-lime-500 to-green-600',
  'from-fuchsia-500 to-purple-600',
];

const CURRENCIES = [
  { code: 'INR', symbol: '₹', label: 'INR (₹)' },
  { code: 'USD', symbol: '$', label: 'USD ($)' },
  { code: 'EUR', symbol: '€', label: 'EUR (€)' },
  { code: 'GBP', symbol: '£', label: 'GBP (£)' },
];

async function syncToBackend(items: Subscription[]) {
  try {
    await api.syncSubscriptions(
      items.map((s) => ({
        id: s.id,
        name: s.name,
        domain: s.domain,
        price: s.price,
        billing_cycle: s.billingCycle,
        description: s.description,
        last_payment: s.lastPayment,
        status: s.status,
        color: s.color,
      }))
    );
  } catch {
    // Backend is the source of truth; localStorage is only a local cache.
  }
}

function getInitials(name: string) {
  return name
    .split(/\s+/)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();
}

function getDaysUntilDue(sub: Subscription): { days: number; dueDate: Date; overdue: boolean } {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const last = new Date(sub.lastPayment);
  last.setHours(0, 0, 0, 0);

  let due = new Date(last);
  if (sub.billingCycle === 'monthly') {
    due.setMonth(due.getMonth() + 1);
  } else {
    due.setFullYear(due.getFullYear() + 1);
  }

  // Advance until we find a future due date
  while (due < today) {
    if (sub.billingCycle === 'monthly') {
      due.setMonth(due.getMonth() + 1);
    } else {
      due.setFullYear(due.getFullYear() + 1);
    }
  }

  const diffMs = due.getTime() - today.getTime();
  const days = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
  return { days, dueDate: due, overdue: days < 0 };
}

function dueBadgeColor(days: number): string {
  if (days <= 3) return 'bg-rose-500/20 text-rose-400 border-rose-500/30';
  if (days <= 7) return 'bg-amber-500/20 text-amber-400 border-amber-500/30';
  return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
}

function formatCurrency(amount: number, symbol: string) {
  return `${symbol}${amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function SubscriptionsPage() {
  const t = useTranslations('subscriptions');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  const isMobile = useIsMobile();

  const [subs, setSubs] = useState<Subscription[]>([]);
  const [filter, setFilter] = useState<'all' | 'active' | 'unused'>('all');
  const [currency, setCurrency] = useState(CURRENCIES[0]);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const hasLoaded = useRef(false);

  // Form state
  const [formName, setFormName] = useState('');
  const [formDomain, setFormDomain] = useState('');
  const [formPrice, setFormPrice] = useState('');
  const [formCycle, setFormCycle] = useState<'monthly' | 'yearly'>('monthly');
  const [formDescription, setFormDescription] = useState('');
  const [formLastPayment, setFormLastPayment] = useState('');
  const [formStatus, setFormStatus] = useState<'active' | 'unused'>('active');
  const [testLoading, setTestLoading] = useState(false);

  // Load subscriptions: backend is the source of truth.
  // If the backend has no records but localStorage has cached data (e.g. first
  // login after this feature was added), push the cache to the backend once.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      const raw = typeof window !== 'undefined' ? localStorage.getItem('sowknow_subscriptions') : null;
      let localSubs: Subscription[] = [];
      if (raw) {
        try { localSubs = JSON.parse(raw); } catch { /* ignore */ }
      }

      const res = await api.listSubscriptions();
      if (!cancelled) {
        if (res.status === 200 && res.data && res.data.subscriptions.length > 0) {
          const mapped = res.data.subscriptions.map((s) => ({
            id: s.id,
            name: s.name,
            domain: s.domain || s.name.toLowerCase().replace(/\s+/g, '') + '.com',
            price: Number(s.price),
            billingCycle: (s.billing_cycle === 'yearly' ? 'yearly' : 'monthly') as 'monthly' | 'yearly',
            description: s.description || '',
            lastPayment: s.last_payment,
            status: (s.status === 'unused' ? 'unused' : 'active') as 'active' | 'unused',
            color: s.color || PRESET_COLORS[Math.floor(Math.random() * PRESET_COLORS.length)],
          }));
          setSubs(mapped);
          localStorage.setItem('sowknow_subscriptions', JSON.stringify(mapped));
        } else if (localSubs.length > 0) {
          // One-time migration: push cached localStorage data to backend
          setSubs(localSubs);
          syncToBackend(localSubs);
        } else {
          setSubs([]);
        }
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  // Persist to localStorage and backend on change
  useEffect(() => {
    if (!hasLoaded.current) {
      hasLoaded.current = true;
      return;
    }
    localStorage.setItem('sowknow_subscriptions', JSON.stringify(subs));
    syncToBackend(subs);
  }, [subs]);

  const filteredSubs = useMemo(() => {
    if (filter === 'all') return subs;
    return subs.filter((s) => s.status === filter);
  }, [subs, filter]);

  const stats = useMemo(() => {
    const total = subs.length;
    const active = subs.filter((s) => s.status === 'active').length;
    const unused = subs.filter((s) => s.status === 'unused').length;
    const monthlyCost = subs.reduce((sum, s) => {
      if (s.billingCycle === 'monthly') return sum + s.price;
      return sum + s.price / 12;
    }, 0);
    const yearlyCost = subs.reduce((sum, s) => {
      if (s.billingCycle === 'yearly') return sum + s.price;
      return sum + s.price * 12;
    }, 0);
    return { total, active, unused, monthlyCost, yearlyCost };
  }, [subs]);

  const resetForm = () => {
    setFormName('');
    setFormDomain('');
    setFormPrice('');
    setFormCycle('monthly');
    setFormDescription('');
    setFormLastPayment('');
    setFormStatus('active');
    setEditingId(null);
  };

  const openCreate = () => {
    resetForm();
    setFormLastPayment(new Date().toISOString().slice(0, 10));
    setShowForm(true);
  };

  const openEdit = (sub: Subscription) => {
    setFormName(sub.name);
    setFormDomain(sub.domain);
    setFormPrice(String(sub.price));
    setFormCycle(sub.billingCycle);
    setFormDescription(sub.description);
    setFormLastPayment(sub.lastPayment);
    setFormStatus(sub.status);
    setEditingId(sub.id);
    setShowForm(true);
  };

  const handleSave = () => {
    const priceNum = parseFloat(formPrice);
    if (!formName || isNaN(priceNum) || priceNum <= 0) return;

    if (editingId) {
      setSubs((prev) =>
        prev.map((s) =>
          s.id === editingId
            ? {
                ...s,
                name: formName,
                domain: formDomain || formName.toLowerCase().replace(/\s+/g, '') + '.com',
                price: priceNum,
                billingCycle: formCycle,
                description: formDescription,
                lastPayment: formLastPayment,
                status: formStatus,
              }
            : s
        )
      );
    } else {
      const newSub: Subscription = {
        id: crypto.randomUUID(),
        name: formName,
        domain: formDomain || formName.toLowerCase().replace(/\s+/g, '') + '.com',
        price: priceNum,
        billingCycle: formCycle,
        description: formDescription,
        lastPayment: formLastPayment,
        status: formStatus,
        color: PRESET_COLORS[Math.floor(Math.random() * PRESET_COLORS.length)],
      };
      setSubs((prev) => [...prev, newSub]);
    }
    setShowForm(false);
    resetForm();
  };

  const handleDelete = (id: string) => {
    if (!confirm(t('delete_confirm'))) return;
    setSubs((prev) => prev.filter((s) => s.id !== id));
  };

  const formContent = (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-text-secondary mb-1">{t('name_label')} *</label>
        <input
          type="text"
          value={formName}
          onChange={(e) => setFormName(e.target.value)}
          className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-text-secondary mb-1">{t('domain_label')}</label>
        <input
          type="text"
          value={formDomain}
          onChange={(e) => setFormDomain(e.target.value)}
          placeholder={t('domain_placeholder')}
          className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">{t('price_label')} *</label>
          <input
            type="number"
            min={0}
            step="0.01"
            value={formPrice}
            onChange={(e) => setFormPrice(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">{t('cycle_label')}</label>
          <select
            value={formCycle}
            onChange={(e) => setFormCycle(e.target.value as 'monthly' | 'yearly')}
            className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
          >
            <option value="monthly">{t('monthly')}</option>
            <option value="yearly">{t('yearly')}</option>
          </select>
        </div>
      </div>
      <div>
        <label className="block text-sm font-medium text-text-secondary mb-1">{t('description_label')}</label>
        <textarea
          value={formDescription}
          onChange={(e) => setFormDescription(e.target.value)}
          rows={2}
          className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none resize-none"
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">{t('last_payment_label')}</label>
          <input
            type="date"
            value={formLastPayment}
            onChange={(e) => setFormLastPayment(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">{t('status_label')}</label>
          <select
            value={formStatus}
            onChange={(e) => setFormStatus(e.target.value as 'active' | 'unused')}
            className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
          >
            <option value="active">{t('active')}</option>
            <option value="unused">{t('unused')}</option>
          </select>
        </div>
      </div>
    </div>
  );

  const handleTestReminder = async () => {
    setTestLoading(true);
    const res = await api.testSubscriptionReminder();
    setTestLoading(false);
    if (res.status === 200 && res.data?.sent) {
      alert(`Test reminder sent to ${res.data.recipient}`);
    } else {
      alert(res.error || 'Failed to send test reminder');
    }
  };

  const filterTabs = (
    <div className="flex items-center gap-2">
      {(['all', 'active', 'unused'] as const).map((f) => (
        <button
          key={f}
          onClick={() => setFilter(f)}
          className={`px-4 py-1.5 rounded-full text-sm font-medium transition-all border ${
            filter === f
              ? 'bg-amber-500 text-vault-1000 border-amber-500'
              : 'bg-transparent text-text-secondary border-white/[0.12] hover:border-white/[0.25] hover:text-text-primary'
          }`}
        >
          {t(`filter_${f}`)}
        </button>
      ))}
    </div>
  );

  return (
    <div className="min-h-screen bg-vault-950">
      <div className="max-w-7xl mx-auto px-4 py-8 pb-20 md:pb-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl font-bold text-text-primary font-display flex items-center gap-2">
              <span className="inline-block w-3 h-3 rounded-sm bg-amber-500" />
              {t('title')}
            </h1>
            <p className="text-sm text-text-muted mt-1">{t('subtitle')}</p>
          </div>
          <div className="flex items-center gap-3">
            {subs.length > 0 && (
              <button
                onClick={() => {
                  if (confirm(t('clear_all_confirm'))) {
                    setSubs([]);
                    localStorage.removeItem('sowknow_subscriptions');
                  }
                }}
                className="hidden md:inline-flex px-3 py-2 text-xs text-rose-400 border border-rose-500/30 rounded-lg hover:bg-rose-500/10 transition-colors font-medium"
              >
                {t('clear_all')}
              </button>
            )}
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-muted">{t('currency')}</span>
              <select
                value={currency.code}
                onChange={(e) => {
                  const c = CURRENCIES.find((x) => x.code === e.target.value);
                  if (c) setCurrency(c);
                }}
                className="px-2 py-1.5 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary text-sm focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
              >
                {CURRENCIES.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
            <button
              onClick={handleTestReminder}
              disabled={testLoading}
              className="hidden md:inline-flex px-3 py-2 text-xs text-emerald-400 border border-emerald-500/30 rounded-lg hover:bg-emerald-500/10 transition-colors font-medium disabled:opacity-50"
            >
              {testLoading ? 'Sending…' : 'Test Reminder'}
            </button>
            <button
              onClick={openCreate}
              className="hidden md:inline-flex px-4 py-2 bg-amber-500 text-vault-1000 rounded-lg hover:bg-amber-400 transition-colors font-medium"
            >
              {t('add')}
            </button>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-8">
          <div className="p-4 bg-vault-900/60 rounded-xl border border-white/[0.06]">
            <p className="text-2xl font-bold text-amber-400">{stats.total}</p>
            <p className="text-xs text-text-muted mt-0.5">{t('stat_total')}</p>
          </div>
          <div className="p-4 bg-vault-900/60 rounded-xl border border-white/[0.06]">
            <p className="text-2xl font-bold text-amber-400">{formatCurrency(stats.monthlyCost, currency.symbol)}</p>
            <p className="text-xs text-text-muted mt-0.5">{t('stat_monthly')}</p>
          </div>
          <div className="p-4 bg-vault-900/60 rounded-xl border border-white/[0.06]">
            <p className="text-2xl font-bold text-amber-400">{formatCurrency(stats.yearlyCost, currency.symbol)}</p>
            <p className="text-xs text-text-muted mt-0.5">{t('stat_yearly')}</p>
          </div>
          <div className="p-4 bg-vault-900/60 rounded-xl border border-white/[0.06]">
            <p className="text-2xl font-bold text-emerald-400">{stats.active}</p>
            <p className="text-xs text-text-muted mt-0.5">{t('stat_active')}</p>
          </div>
          <div className="p-4 bg-vault-900/60 rounded-xl border border-white/[0.06]">
            <p className="text-2xl font-bold text-rose-400">{stats.unused}</p>
            <p className="text-xs text-text-muted mt-0.5">{t('stat_unused')}</p>
          </div>
        </div>

        {/* Filters */}
        <div className="mb-6 p-3 bg-vault-900/40 rounded-xl border border-white/[0.06]">
          {filterTabs}
        </div>

        {/* Subscriptions Grid */}
        {subs.length === 0 ? (
          <p className="text-center text-text-muted py-12">{t('empty')}</p>
        ) : filteredSubs.length === 0 ? (
          <p className="text-center text-text-muted py-12">{t('empty_filtered')}</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filteredSubs.map((sub) => (
              <div
                key={sub.id}
                className="group bg-vault-900/60 rounded-xl border border-white/[0.06] hover:border-white/[0.12] hover:bg-vault-900/80 transition-all overflow-hidden"
              >
                {/* Top colored bar with icon */}
                <div className={`relative h-16 bg-gradient-to-r ${sub.color} flex items-center px-4`}>
                  <div className="w-10 h-10 rounded-lg bg-white/20 backdrop-blur-sm flex items-center justify-center text-white font-bold text-sm shadow-sm">
                    {getInitials(sub.name)}
                  </div>
                  <div className="ml-3 min-w-0">
                    <p className="text-white font-semibold text-sm truncate leading-tight">{sub.name}</p>
                    <p className="text-white/80 text-xs truncate">{sub.domain}</p>
                  </div>
                  <button
                    onClick={() => openEdit(sub)}
                    className="absolute top-2 right-2 p-1.5 rounded-md bg-black/20 text-white/80 hover:bg-black/30 hover:text-white transition-colors opacity-0 group-hover:opacity-100"
                    aria-label={tCommon('edit')}
                  >
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                    </svg>
                  </button>
                </div>

                {/* Body */}
                <div className="p-4">
                  <p className="text-lg font-bold text-amber-400 mb-1">
                    {formatCurrency(sub.price, currency.symbol)}
                    <span className="text-xs font-medium text-text-muted ml-1">
                      /{sub.billingCycle === 'monthly' ? t('mo') : t('yr')}
                    </span>
                  </p>
                  {(() => {
                    const { days } = getDaysUntilDue(sub);
                    const badgeClass = dueBadgeColor(days);
                    return (
                      <span className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold border mb-2 ${badgeClass}`}>
                        {days === 0 ? 'Due today' : days === 1 ? 'Due tomorrow' : `${days} days left`}
                      </span>
                    );
                  })()}
                  <p className="text-sm text-text-secondary line-clamp-2 min-h-[2.5rem]">{sub.description}</p>
                </div>

                {/* Footer */}
                <div className="px-4 pb-4 pt-0 flex items-center justify-between">
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-text-muted">{t('last_payment')}</p>
                    <p className="text-xs text-text-secondary font-medium">{sub.lastPayment}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] uppercase tracking-wider text-text-muted">{t('usage_status')}</p>
                    <span
                      className={`inline-block mt-0.5 px-2 py-0.5 rounded-full text-xs font-medium ${
                        sub.status === 'active'
                          ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/25'
                          : 'bg-rose-500/15 text-rose-400 border border-rose-500/25'
                      }`}
                    >
                      {sub.status === 'active' ? t('using') : t('unused')}
                    </span>
                  </div>
                </div>

                {/* Delete */}
                <div className="px-4 pb-3 flex justify-end">
                  <button
                    onClick={() => handleDelete(sub.id)}
                    className="text-[10px] text-text-muted hover:text-red-400 transition-colors flex items-center gap-1"
                  >
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                    {tCommon('delete')}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* FAB — mobile only */}
      {isMobile && <FAB onClick={openCreate} label={t('add')} />}

      {/* Create/Edit — Mobile: MobileSheet */}
      {isMobile && (
        <MobileSheet
          open={showForm}
          onClose={() => { setShowForm(false); resetForm(); }}
          title={editingId ? t('edit') : t('add')}
          footer={
            <div className="flex gap-3">
              <button
                onClick={() => { setShowForm(false); resetForm(); }}
                className="flex-1 rounded-lg border border-white/[0.08] text-text-secondary hover:bg-white/[0.04] transition-colors font-medium"
                style={{ minHeight: '44px' }}
              >
                {tCommon('cancel')}
              </button>
              <button
                onClick={handleSave}
                disabled={!formName || !formPrice || isNaN(parseFloat(formPrice)) || parseFloat(formPrice) <= 0}
                className="flex-1 rounded-lg bg-amber-500 text-vault-1000 hover:bg-amber-400 disabled:opacity-50 font-medium transition-colors"
                style={{ minHeight: '44px' }}
              >
                {tCommon('save')}
              </button>
            </div>
          }
        >
          {formContent}
        </MobileSheet>
      )}

      {/* Create/Edit — Desktop: Modal */}
      {!isMobile && showForm && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-vault-900 border border-white/[0.08] rounded-xl shadow-2xl max-w-lg w-full p-6 max-h-[90vh] overflow-y-auto">
            <h2 className="text-xl font-bold text-text-primary font-display mb-4">
              {editingId ? t('edit') : t('add')}
            </h2>
            {formContent}
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => { setShowForm(false); resetForm(); }}
                className="px-4 py-2 rounded-lg border border-white/[0.08] text-text-secondary hover:bg-white/[0.04] transition-colors"
              >
                {tCommon('cancel')}
              </button>
              <button
                onClick={handleSave}
                disabled={!formName || !formPrice || isNaN(parseFloat(formPrice)) || parseFloat(formPrice) <= 0}
                className="px-4 py-2 rounded-lg bg-amber-500 text-vault-1000 hover:bg-amber-400 disabled:opacity-50 font-medium transition-colors"
              >
                {tCommon('save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
