'use client';

import { useState, useEffect } from 'react';

interface DateTimePickerProps {
  value: string; // ISO format: "2026-05-10T14:30"
  onChange: (value: string) => void;
  label?: string;
}

function parseIsoDateTime(iso: string): { date: string; hour12: string; minute: string; ampm: 'AM' | 'PM' } | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;

  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const date = `${year}-${month}-${day}`;

  let hour24 = d.getHours();
  const minute = String(d.getMinutes()).padStart(2, '0');
  const ampm = hour24 >= 12 ? 'PM' : 'AM';
  let hour12 = hour24 % 12;
  if (hour12 === 0) hour12 = 12;

  return { date, hour12: String(hour12), minute, ampm };
}

function buildIsoDateTime(date: string, hour12: string, minute: string, ampm: 'AM' | 'PM'): string {
  if (!date) return '';
  let hour24 = parseInt(hour12, 10);
  if (isNaN(hour24)) hour24 = 12;
  if (ampm === 'PM' && hour24 !== 12) hour24 += 12;
  if (ampm === 'AM' && hour24 === 12) hour24 = 0;

  const h = String(hour24).padStart(2, '0');
  const m = String(parseInt(minute, 10) || 0).padStart(2, '0');
  return `${date}T${h}:${m}`;
}

export default function DateTimePicker({ value, onChange, label }: DateTimePickerProps) {
  const parsed = parseIsoDateTime(value);

  const [date, setDate] = useState(parsed?.date || '');
  const [hour, setHour] = useState(parsed?.hour12 || '12');
  const [minute, setMinute] = useState(parsed?.minute || '00');
  const [ampm, setAmpm] = useState<'AM' | 'PM'>(parsed?.ampm || 'AM');

  // Sync internal state when external value changes
  useEffect(() => {
    const p = parseIsoDateTime(value);
    if (p) {
      setDate(p.date);
      setHour(p.hour12);
      setMinute(p.minute);
      setAmpm(p.ampm);
    } else {
      setDate('');
      setHour('12');
      setMinute('00');
      setAmpm('AM');
    }
  }, [value]);

  // Notify parent when any field changes
  useEffect(() => {
    const iso = buildIsoDateTime(date, hour, minute, ampm);
    if (iso !== value) {
      onChange(iso);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date, hour, minute, ampm]);

  const hours = Array.from({ length: 12 }, (_, i) => String(i + 1));
  const minutes = ['00', '15', '30', '45'];

  return (
    <div className="space-y-2">
      {label && <label className="block text-sm font-medium text-text-secondary">{label}</label>}
      <div className="grid grid-cols-2 gap-2">
        <input
          type="date"
          value={date}
          onChange={e => setDate(e.target.value)}
          className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
        />
        <div className="flex gap-1">
          <select
            value={hour}
            onChange={e => setHour(e.target.value)}
            className="flex-1 px-2 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none text-sm"
          >
            {hours.map(h => (
              <option key={h} value={h}>{h}</option>
            ))}
          </select>
          <span className="self-center text-text-muted text-sm">:</span>
          <select
            value={minute}
            onChange={e => setMinute(e.target.value)}
            className="flex-1 px-2 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none text-sm"
          >
            {minutes.map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setAmpm(prev => prev === 'AM' ? 'PM' : 'AM')}
            className="px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary text-sm font-medium hover:bg-vault-800 transition-colors min-w-[48px]"
          >
            {ampm}
          </button>
        </div>
      </div>
    </div>
  );
}
