/**
 * useBookProgress.ts
 * React hook that connects a WebSocket to /api/v1/books/:id/ws
 * and provides real-time progress updates.
 *
 * Usage:
 *   const ws = useBookProgress(bookId, initialStatus);
 *   ws.status   // current pipeline status
 *   ws.progress // 0..1
 *   ws.message  // human-readable step description
 *   ws.connected // WebSocket connected
 *   ws.error    // error string if failed
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { createProgressWebSocket } from '../api/client';

type ProgressMsg = {
  type: 'progress';
  status: string;
  progress: number;
  message: string;
};
type CompletedMsg = { type: 'completed'; export_url: string; duration: string };
type ErrorMsg     = { type: 'error';     error: string };
type WsMsg = ProgressMsg | CompletedMsg | ErrorMsg;

export function useBookProgress(bookId: string | undefined, initialStatus: string) {
  const [status,    setStatus]    = useState(initialStatus);
  const [progress,  setProgress]  = useState(0);
  const [message,   setMessage]   = useState('');
  const [connected, setConnected] = useState(false);
  const [error,     setError]     = useState<string | null>(null);

  const wsRef     = useRef<WebSocket | null>(null);
  const pingRef   = useRef<ReturnType<typeof setInterval> | null>(null);

  // Only connect when processing is in-flight
  const shouldConnect = bookId != null && !['completed', 'failed'].includes(initialStatus);

  const teardown = useCallback(() => {
    if (pingRef.current) clearInterval(pingRef.current);
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
  }, []);

  useEffect(() => {
    if (!shouldConnect) return;

    const ws = createProgressWebSocket(bookId!);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      setError(null);
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping');
      }, 20_000);
    };

    ws.onmessage = (evt) => {
      if (evt.data === 'pong') return;
      try {
        const msg: WsMsg = JSON.parse(evt.data);
        if (msg.type === 'progress') {
          setStatus(msg.status);
          setProgress(msg.progress);
          setMessage(msg.message);
        } else if (msg.type === 'completed') {
          setStatus('completed');
          setProgress(1);
          teardown();
        } else if (msg.type === 'error') {
          setStatus('failed');
          setError(msg.error);
          teardown();
        }
      } catch { /* ignore malformed */ }
    };

    ws.onclose  = () => { setConnected(false); clearInterval(pingRef.current!); };
    ws.onerror  = () => { setConnected(false); };

    return teardown;
  }, [bookId, shouldConnect, teardown]);

  return { status, progress, message, connected, error };
}
