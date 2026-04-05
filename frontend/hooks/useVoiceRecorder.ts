import { useCallback, useEffect, useRef, useState } from 'react';

export type RecordingState = 'idle' | 'recording' | 'preview' | 'transcribing';

interface UseVoiceRecorderOptions {
  onTranscript?: (text: string) => void;
  onAudioReady?: (blob: Blob, transcript: string) => void;
  privateMode?: boolean;
  apiBaseUrl?: string;
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
  const { onTranscript, onAudioReady, privateMode = false, apiBaseUrl = '' } = options;

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

      // MediaRecorder
      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
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
        // Leave lang unset for auto-detect FR/EN
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

    if (privateMode && !transcript) {
      setState('transcribing');
      try {
        const formData = new FormData();
        formData.append('file', audioBlob, 'voice.webm');
        const res = await fetch(`${apiBaseUrl}/api/v1/voice/transcribe`, {
          method: 'POST',
          body: formData,
          credentials: 'include',
        });
        if (!res.ok) throw new Error('Transcription failed');
        const data = await res.json();
        setTranscript(data.transcript);
        onAudioReady?.(audioBlob, data.transcript);
      } catch (err) {
        setError('Server transcription failed');
        setState('preview');
        return;
      }
    } else {
      onAudioReady?.(audioBlob, transcript);
    }

    onTranscript?.(transcript);
    setState('idle');
    cleanup();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    setAudioBlob(null);
    setTranscript('');
  }, [audioBlob, transcript, privateMode, apiBaseUrl, onTranscript, onAudioReady, cleanup, audioUrl]);

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
