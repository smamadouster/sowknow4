'use client';

import { useCallback, useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { useVoiceRecorder } from '@/hooks/useVoiceRecorder';

interface VoiceRecorderProps {
  mode: 'journal' | 'note' | 'search';
  onAudioReady?: (blob: Blob, transcript: string) => void;
  onCancel?: () => void;
  className?: string;
  lang?: string;
}

function formatTime(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, '0');
  const s = (totalSeconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function WaveformBars({ analyserNode }: { analyserNode: AnalyserNode | null }) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const barsRef = useRef<number[]>(new Array(20).fill(4));
  const rafRef = useRef<number>(0);

  useEffect(() => {
    if (!analyserNode || !canvasRef.current) return;
    const dataArray = new Uint8Array(analyserNode.frequencyBinCount);

    const animate = () => {
      analyserNode.getByteFrequencyData(dataArray);
      const bars = barsRef.current;
      const step = Math.floor(dataArray.length / bars.length);
      for (let i = 0; i < bars.length; i++) {
        const val = dataArray[i * step] / 255;
        bars[i] = Math.max(4, val * 32);
      }
      if (canvasRef.current) {
        const children = canvasRef.current.children;
        for (let i = 0; i < children.length; i++) {
          (children[i] as HTMLElement).style.height = `${bars[i]}px`;
        }
      }
      rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [analyserNode]);

  return (
    <div ref={canvasRef} className="flex items-center gap-[2px] h-8">
      {Array.from({ length: 20 }).map((_, i) => (
        <div
          key={i}
          className="w-1 bg-amber-450 rounded-full transition-all duration-75"
          style={{ height: '4px' }}
        />
      ))}
    </div>
  );
}

export default function VoiceRecorder({ mode, onAudioReady, onCancel, className = '', lang }: VoiceRecorderProps) {
  const t = useTranslations('voice');

  const {
    state,
    audioBlob,
    audioUrl,
    analyserNode,
    recordingSeconds,
    engineName,
    startRecording,
    stopRecording,
    cancelRecording,
    send,
    isSupported,
    error,
  } = useVoiceRecorder({
    onAudioReady,
    lang,
  });

  const handleToggle = useCallback(() => {
    if (state === 'idle' || state === 'requesting') {
      startRecording();
    } else if (state === 'recording') {
      stopRecording();
    }
  }, [state, startRecording, stopRecording]);

  const handleSend = useCallback(async () => {
    await send();
  }, [send]);

  const handleReRecord = useCallback(() => {
    cancelRecording();
    // Small delay to let the browser release the mic before re-acquiring
    setTimeout(() => startRecording(), 150);
  }, [cancelRecording, startRecording]);

  if (!isSupported) {
    return (
      <div className={`text-vault-400 text-sm ${className}`}>
        {t('micNotSupported')}
      </div>
    );
  }

  return (
    <div className={`flex flex-col gap-3 ${className}`}>
      {error && (
        <div className="flex items-start gap-2 text-red-400 text-xs bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          <span className="mt-0.5 flex-shrink-0">⚠</span>
          <span>{error}</span>
        </div>
      )}

      <div className="flex items-center gap-3">
        {/* Main record / stop button */}
        <button
          onClick={handleToggle}
          disabled={state === 'transcribing'}
          className={`relative flex items-center justify-center w-14 h-14 rounded-full transition-all select-none touch-manipulation ${
            state === 'recording'
              ? 'bg-red-500 shadow-lg shadow-red-500/30 animate-pulse-slow'
              : state === 'requesting'
              ? 'bg-amber-450/60 cursor-wait'
              : state === 'transcribing'
              ? 'bg-vault-700 cursor-wait'
              : 'bg-amber-450 hover:bg-amber-400 cursor-pointer'
          }`}
          style={{ touchAction: 'manipulation' }}
          aria-label={state === 'recording' ? t('tapToStop') : t('tapToRecord')}
        >
          {state === 'requesting' ? (
            <svg className="w-5 h-5 text-white animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : state === 'transcribing' ? (
            <svg className="w-5 h-5 text-white animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : state === 'recording' ? (
            <svg className="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 24 24">
              <rect x="6" y="6" width="12" height="12" rx="2" />
            </svg>
          ) : (
            <svg className="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
              <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
            </svg>
          )}
        </button>

        {/* Recording state: waveform + timer */}
        {state === 'recording' && (
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <WaveformBars analyserNode={analyserNode} />
            <span className="text-sm font-mono text-red-400 flex-shrink-0 tabular-nums">
              {formatTime(recordingSeconds)}
            </span>
            <span className="text-xs text-vault-400 flex-shrink-0 hidden sm:inline">
              {t('tapToStop')}
            </span>
            {engineName && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-vault-800 text-vault-500 flex-shrink-0">
                {engineName}
              </span>
            )}
          </div>
        )}

        {/* Requesting state */}
        {state === 'requesting' && (
          <span className="text-vault-400 text-sm animate-pulse">{t('recording')}</span>
        )}

        {/* Transcribing state */}
        {state === 'transcribing' && (
          <span className="text-vault-400 text-sm animate-pulse">{t('transcribing')}</span>
        )}

        {/* Preview state: audio player + actions */}
        {state === 'preview' && audioUrl && (
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <audio src={audioUrl} controls className="h-8 flex-1 min-w-0" />
            <button
              onClick={handleSend}
              className="px-3 py-1.5 bg-amber-450 text-white rounded-lg text-sm font-medium hover:bg-amber-400 flex-shrink-0"
            >
              {t('send')}
            </button>
            <button
              onClick={handleReRecord}
              className="px-3 py-1.5 bg-vault-700 text-vault-300 rounded-lg text-sm hover:bg-vault-600 flex-shrink-0"
            >
              {t('reRecord')}
            </button>
            <button
              onClick={() => {
                cancelRecording();
                onCancel?.();
              }}
              className="px-2 py-1.5 text-vault-500 hover:text-red-400 text-sm flex-shrink-0"
            >
              {t('cancel')}
            </button>
          </div>
        )}
      </div>

      {/* Idle helper text */}
      {state === 'idle' && !error && (
        <p className="text-xs text-vault-500 pl-[4.25rem]">{t('tapToRecord')}</p>
      )}
    </div>
  );
}
