import { useCallback, useEffect, useRef, useState } from 'react';

export type RecordingState = 'idle' | 'recording' | 'preview' | 'transcribing';

// Locale → BCP-47 for Web Speech API (e.g. fr → fr-FR)
const BCP47: Record<string, string> = { fr: 'fr-FR', en: 'en-US' };
const toBcp47 = (l?: string) => (l && BCP47[l]) ?? l;

interface UseVoiceRecorderOptions {
  onTranscript?: (text: string) => void;
  onAudioReady?: (blob: Blob, transcript: string) => void;
  privateMode?: boolean;
  apiBaseUrl?: string;
  lang?: string;
}

interface UseVoiceRecorderReturn {
  state: RecordingState;
  transcript: string;
  interimTranscript: string;
  audioBlob: Blob | null;
  audioUrl: string | null;
  analyserNode: AnalyserNode | null;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  cancelRecording: () => void;
  send: () => void;
  reRecord: () => void;
  isSupported: boolean;
  isSpeechSupported: boolean;
  error: string | null;
}

export function useVoiceRecorder(options: UseVoiceRecorderOptions = {}): UseVoiceRecorderReturn {
  const { onTranscript, onAudioReady, privateMode = false, apiBaseUrl = '', lang } = options;

  const [state, setState] = useState<RecordingState>('idle');
  const [transcript, setTranscript] = useState('');
  const [interimTranscript, setInterimTranscript] = useState('');
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [analyserNode, setAnalyserNode] = useState<AnalyserNode | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const isSupported = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
  const isSpeechSupported = typeof window !== 'undefined' && !!(
    window.SpeechRecognition || window.webkitSpeechRecognition
  );

  const cleanup = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    mediaRecorderRef.current = null;
    recognitionRef.current = null;
    chunksRef.current = [];
    setAnalyserNode(null);
  }, []);

  const startRecording = useCallback(async () => {
    setError(null);
    setTranscript('');
    setInterimTranscript('');
    setAudioBlob(null);
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    chunksRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // AudioContext + AnalyserNode for waveform
      const audioCtx = new AudioContext();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      audioContextRef.current = audioCtx;
      setAnalyserNode(analyser);

      // MediaRecorder — Safari/iOS doesn't support webm, so pick a supported mimeType
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/mp4')
        ? 'audio/mp4'
        : undefined;
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        setAudioBlob(blob);
        setAudioUrl(URL.createObjectURL(blob));
        stream.getTracks().forEach(t => t.stop());
      };
      mediaRecorderRef.current = recorder;
      recorder.start(250);

      // Web Speech API (if not private mode)
      if (!privateMode && isSpeechSupported) {
        const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new SpeechRecognitionCtor!();
        recognition.continuous = true;
        recognition.interimResults = true;
        if (lang) {
          recognition.lang = toBcp47(lang) ?? lang;
        }
        recognition.onresult = (event: SpeechRecognitionEvent) => {
          let interim = '';
          let final_ = '';
          for (let i = 0; i < event.results.length; i++) {
            const result = event.results[i];
            if (result.isFinal) {
              final_ += result[0].transcript + ' ';
            } else {
              interim += result[0].transcript;
            }
          }
          if (final_) setTranscript(prev => (prev + final_).trim());
          setInterimTranscript(interim);
        };
        recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
          if (event.error !== 'aborted') {
            console.warn('Speech recognition error:', event.error);
          }
        };
        recognitionRef.current = recognition;
        recognition.start();
      }

      setState('recording');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Microphone access denied');
      setState('idle');
    }
  }, [privateMode, isSpeechSupported, audioUrl]);

  const stopRecording = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      recognitionRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    setAnalyserNode(null);
    setState('preview');
  }, []);

  const cancelRecording = useCallback(() => {
    cleanup();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    setAudioBlob(null);
    setTranscript('');
    setInterimTranscript('');
    setState('idle');
  }, [cleanup, audioUrl]);

  const send = useCallback(async () => {
    if (!audioBlob) return;

    // Always use backend whisper for accuracy. iOS Safari Web Speech API
    // is unreliable with non-default languages — sending FR audio comes
    // back as EN text. Whisper auto-detects the spoken language so we
    // always send 'auto' rather than locking to the UI locale.
    setState('transcribing');
    let finalTranscript = transcript;
    try {
      const formData = new FormData();
      const ext = audioBlob.type.includes('mp4') ? 'm4a' : audioBlob.type.includes('ogg') ? 'ogg' : 'webm';
      formData.append('file', audioBlob, `voice.${ext}`);
      formData.append('language', 'auto');
      const res = await fetch(`${apiBaseUrl}/api/v1/voice/transcribe`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });
      if (!res.ok) throw new Error('Transcription failed');
      const data = await res.json();
      finalTranscript = data.transcript;
      setTranscript(finalTranscript);
    } catch {
      // Fall back to web speech transcript if backend whisper fails
      if (!finalTranscript) {
        setError('Server transcription failed');
        setState('preview');
        return;
      }
    }

    onAudioReady?.(audioBlob, finalTranscript);
    onTranscript?.(finalTranscript);
    setState('idle');
    cleanup();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    setAudioBlob(null);
    setTranscript('');
  }, [audioBlob, transcript, apiBaseUrl, onTranscript, onAudioReady, cleanup, audioUrl]);

  const reRecord = useCallback(() => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    setAudioBlob(null);
    setTranscript('');
    setInterimTranscript('');
    setState('idle');
  }, [audioUrl]);

  useEffect(() => {
    return () => {
      cleanup();
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
  }, []);

  return {
    state, transcript, interimTranscript, audioBlob, audioUrl,
    analyserNode, startRecording, stopRecording, cancelRecording,
    send, reRecord, isSupported, isSpeechSupported, error,
  };
}
