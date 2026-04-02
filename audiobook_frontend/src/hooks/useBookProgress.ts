/**
 * useBookProgress.ts
 * React hook that connects a WebSocket to /api/v1/books/:id/ws
 * and provides real-time progress updates.
 *
 * Resilience strategy:
 *   1. WS auto-reconnect with exponential back-off (up to MAX_RETRIES = 5).
 *      Delays: 1 s → 2 s → 4 s → 8 s → 16 s (capped at 30 s).
 *   2. After exhausting retries the hook falls back to REST polling every
 *      FALLBACK_INTERVAL_MS (3 s) via GET /api/v1/books/:id/progress.
 *   3. If WS reconnects while polling is active the interval is cleared.
 *   4. `wsMessageReceived` – true once the WS (or fallback) has delivered at
 *      least one authoritative status update.  BookDetailPage uses this flag
 *      to decide whether the WS status should override the REST cache status,
 *      preventing a stale initial "pending" from shadowing a real REST status.
 *
 * Usage:
 *   const ws = useBookProgress(bookId, initialStatus);
 *   ws.status           // current pipeline status
 *   ws.progress         // 0..1
 *   ws.message          // human-readable step description
 *   ws.connected        // WebSocket currently open
 *   ws.usingFallback    // true while REST-polling (WS down)
 *   ws.error            // error string if failed
 *   ws.wsMessageReceived // true once a real status was received
 */
import { useEffect, useRef, useState } from 'react';
import { createProgressWebSocket } from '../api/client';
import { booksApi } from '../api/books';

const MAX_RETRIES = 5;
const FALLBACK_INTERVAL_MS = 3_000;
const PING_INTERVAL_MS = 20_000;

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
  const [status,             setStatus]             = useState(initialStatus);
  const [progress,           setProgress]           = useState(0);
  const [message,            setMessage]            = useState('');
  const [connected,          setConnected]          = useState(false);
  const [usingFallback,      setUsingFallback]      = useState(false);
  const [error,              setError]              = useState<string | null>(null);
  const [wsMessageReceived,  setWsMessageReceived]  = useState(false);

  // ── Stable ref so effect cleanup can always reach the latest setState calls ──
  const stateRef = useRef({ setStatus, setProgress, setMessage, setConnected,
                             setUsingFallback, setError, setWsMessageReceived });

  useEffect(() => {
    // ── Guard: skip connecting for already-terminal books ──────────────────────
    if (!bookId) return;
    if (['completed', 'failed'].includes(initialStatus)) return;

    // Local mutable state (no re-render cost, safe inside closure)
    let alive       = true;   // becomes false on cleanup → prevents stale setState
    let retryCount  = 0;
    let ws:              WebSocket | null = null;
    let pingTimer:       ReturnType<typeof setInterval>  | null = null;
    let retryTimer:      ReturnType<typeof setTimeout>   | null = null;
    let fallbackTimer:   ReturnType<typeof setInterval>  | null = null;

    // ── Helpers ────────────────────────────────────────────────────────────────
    const stopPing = () => {
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
    };

    const stopFallback = () => {
      if (fallbackTimer) { clearInterval(fallbackTimer); fallbackTimer = null; }
      stateRef.current.setUsingFallback(false);
    };

    const stopRetry = () => {
      if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
    };

    const teardownWs = () => {
      stopPing();
      ws?.close();
      ws = null;
      stateRef.current.setConnected(false);
    };

    // ── REST polling fallback ─────────────────────────────────────────────────
    const startFallback = () => {
      if (!alive || fallbackTimer) return;
      stateRef.current.setUsingFallback(true);

      const poll = async () => {
        if (!alive) return stopFallback();
        try {
          const data = await booksApi.getProgress(bookId);
          if (!alive) return;
          if (data?.status) {
            stateRef.current.setWsMessageReceived(true);
            stateRef.current.setStatus(data.status);
            if (typeof data.progress === 'number') stateRef.current.setProgress(data.progress);
            if (data.message)  stateRef.current.setMessage(data.message);
            if (data.error)    stateRef.current.setError(data.error);
            if (['completed', 'failed'].includes(data.status)) {
              alive = false;
              stopFallback();
            }
          }
        } catch { /* ignore transient network errors */ }
      };

      poll(); // immediate first call
      fallbackTimer = setInterval(poll, FALLBACK_INTERVAL_MS);
    };

    // ── WebSocket connect (called on initial mount + each retry) ──────────────
    const connect = () => {
      if (!alive) return;

      ws = createProgressWebSocket(bookId);

      ws.onopen = () => {
        if (!alive) { ws?.close(); return; }

        stateRef.current.setConnected(true);
        stateRef.current.setError(null);
        retryCount = 0;         // reset back-off counter on successful open

        // Cancel any active fallback polling
        stopFallback();

        // Keep-alive ping
        pingTimer = setInterval(() => {
          if (ws?.readyState === WebSocket.OPEN) ws.send('ping');
        }, PING_INTERVAL_MS);
      };

      ws.onmessage = (evt) => {
        if (!alive) return;
        if (evt.data === 'pong') return;
        try {
          const msg: WsMsg = JSON.parse(evt.data as string);
          stateRef.current.setWsMessageReceived(true);

          if (msg.type === 'progress') {
            stateRef.current.setStatus(msg.status);
            stateRef.current.setProgress(msg.progress);
            stateRef.current.setMessage(msg.message);

          } else if (msg.type === 'completed') {
            stateRef.current.setStatus('completed');
            stateRef.current.setProgress(1);
            alive = false;
            teardownWs();

          } else if (msg.type === 'error') {
            stateRef.current.setStatus('failed');
            stateRef.current.setError(msg.error);
            alive = false;
            teardownWs();
          }
        } catch { /* ignore malformed frames */ }
      };

      ws.onerror = () => {
        // onclose fires right after onerror; reconnect logic lives there
        stateRef.current.setConnected(false);
      };

      ws.onclose = () => {
        stopPing();
        stateRef.current.setConnected(false);
        if (!alive) return;

        if (retryCount < MAX_RETRIES) {
          // Exponential back-off: 1 s, 2 s, 4 s, 8 s, 16 s (cap 30 s)
          const delay = Math.min(1_000 * Math.pow(2, retryCount), 30_000);
          retryCount++;
          retryTimer = setTimeout(connect, delay);
        } else {
          // All retries exhausted → fall back to REST polling
          startFallback();
        }
      };
    };

    // ── Kick off ───────────────────────────────────────────────────────────────
    connect();

    // ── Cleanup on unmount or bookId change ───────────────────────────────────
    return () => {
      alive = false;
      stopRetry();
      stopFallback();
      teardownWs();
    };
  }, [bookId]); // eslint-disable-line react-hooks/exhaustive-deps
  // NOTE: `initialStatus` is intentionally read once at mount time only.
  // Re-subscribing on every REST-poll-triggered status change would thrash the WS.

  return { status, progress, message, connected, usingFallback, error, wsMessageReceived };
}
