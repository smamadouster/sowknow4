'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { useVoiceRecorder, RecordingState } from '@/hooks/useVoiceRecorder';

interface VoiceRecorderProps {
  mode: 'journal' | 'note' | 'search';
  onTranscript?: (text: string) => void;
  onAudioReady?: (blob: Blob, transcript: string) => void;
  onCancel?: () => void;
  className?: string;
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

export default function VoiceRecorder({ mode, onTranscript, onAudioReady, onCancel, className = '' }: VoiceRecorderProps) {
  const t = useTranslations('voice');
  const [privateMode, setPrivateMode] = useState(mode === 'journal');
  const [isHolding, setIsHolding] = useState(false);
  const [slideCancel, setSlideCancel] = useState(false);
  const holdTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startXRef = useRef(0);

  const {
    state, transcript, interimTranscript, audioBlob, audioUrl,
    analyserNode, startRecording, stopRecording, cancelRecording,
    send, reRecord, isSupported, error,
  } = useVoiceRecorder({
    privateMode,
    onTranscript: mode === 'search' ? onTranscript : undefined,
    onAudioReady: mode !== 'search' ? onAudioReady : undefined,
  });

  const handleStopForSearch = useCallback(() => {
    stopRecording();
    if (mode === 'search') {
      setTimeout(() => {
        onTranscript?.(transcript || interimTranscript);
      }, 300);
    }
  }, [mode, stopRecording, onTranscript, transcript, interimTranscript]);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (state === 'recording') {
      if (mode === 'search') handleStopForSearch();
      else stopRecording();
      return;
    }
    if (state !== 'idle') return;

    startXRef.current = e.clientX;
    setSlideCancel(false);

    holdTimerRef.current = setTimeout(() => {
      setIsHolding(true);
    }, 200);
    startRecording();
  }, [state, startRecording, stopRecording, handleStopForSearch, mode]);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!isHolding || state !== 'recording') return;
    const dx = startXRef.current - e.clientX;
    setSlideCancel(dx > 80);
  }, [isHolding, state]);

  const handlePointerUp = useCallback(() => {
    if (holdTimerRef.current) {
      clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
    }

    if (isHolding && state === 'recording') {
      if (slideCancel) {
        cancelRecording();
      } else if (mode === 'search') {
        handleStopForSearch();
      } else {
        stopRecording();
      }
      setIsHolding(false);
      setSlideCancel(false);
    }
  }, [isHolding, state, slideCancel, cancelRecording, stopRecording, handleStopForSearch, mode]);

  if (!isSupported) {
    return (
      <div className={`text-vault-400 text-sm ${className}`}>
        {t('micNotSupported')}
      </div>
    );
  }

  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      {error && <p className="text-red-400 text-xs">{error}</p>}

      {/* Privacy toggle (journal & notes only) */}
      {mode !== 'search' && state === 'idle' && (
        <button
          onClick={() => setPrivateMode(!privateMode)}
          className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded-full w-fit transition-colors ${
            privateMode ? 'bg-green-900/30 text-green-400' : 'bg-vault-800 text-vault-400'
          }`}
          title={privateMode ? t('privateOn') : t('privateOff')}
        >
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
          {privateMode ? t('privateTranscription') : t('cloudTranscription')}
        </button>
      )}

      {/* Main recording area */}
      <div className="flex items-center gap-3">
        <button
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
          className={`relative flex items-center justify-center w-12 h-12 rounded-full transition-all select-none touch-none ${
            state === 'recording'
              ? 'bg-red-500 shadow-lg shadow-red-500/30 animate-pulse-slow'
              : state === 'transcribing'
              ? 'bg-vault-700 cursor-wait'
              : 'bg-amber-450 hover:bg-amber-400 cursor-pointer'
          }`}
          disabled={state === 'transcribing' || state === 'preview'}
        >
          {state === 'transcribing' ? (
            <svg className="w-5 h-5 text-white animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            <svg className="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
              <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
            </svg>
          )}
        </button>

        {/* Waveform + slide-to-cancel */}
        {state === 'recording' && (
          <div className="flex items-center gap-3 flex-1">
            <WaveformBars analyserNode={analyserNode} />
            {isHolding && (
              <span className={`text-xs transition-colors ${slideCancel ? 'text-red-400' : 'text-vault-400'}`}>
                {slideCancel ? t('releaseToCancel') : t('slideToCancel')}
              </span>
            )}
          </div>
        )}

        {/* Preview state */}
        {state === 'preview' && audioUrl && (
          <div className="flex items-center gap-2 flex-1">
            <audio src={audioUrl} controls className="h-8 flex-1" />
            <button onClick={send} className="px-3 py-1.5 bg-amber-450 text-white rounded-lg text-sm font-medium hover:bg-amber-400">
              {t('send')}
            </button>
            <button onClick={reRecord} className="px-3 py-1.5 bg-vault-700 text-vault-300 rounded-lg text-sm hover:bg-vault-600">
              {t('reRecord')}
            </button>
            <button onClick={cancelRecording} className="px-2 py-1.5 text-vault-500 hover:text-red-400 text-sm">
              {t('cancel')}
            </button>
          </div>
        )}

        {state === 'transcribing' && (
          <span className="text-vault-400 text-sm animate-pulse">{t('transcribing')}</span>
        )}
      </div>

      {/* Transcript display */}
      {(state === 'recording' || state === 'preview') && (transcript || interimTranscript) && (
        <div className="text-sm pl-15">
          {transcript && <span className="text-vault-200">{transcript}</span>}
          {interimTranscript && <span className="text-vault-500 italic"> {interimTranscript}</span>}
        </div>
      )}

      {/* Private mode hint during recording */}
      {state === 'recording' && privateMode && (
        <p className="text-xs text-vault-500 pl-15">
          {t('privateHint')}
        </p>
      )}
    </div>
  );
}
