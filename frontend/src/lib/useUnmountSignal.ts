import { useCallback, useEffect, useRef } from "react";

/**
 * Returns a getter for an AbortSignal that aborts when the component unmounts.
 *
 * Use it for long waits started from event handlers (job polling): `await waitForFitCurveJob(id, { signal: getSignal() })`.
 * The controller is created in the effect so React StrictMode's mount / unmount / mount cycle gets a fresh one.
 */
export function useUnmountSignal(): () => AbortSignal {
  const ref = useRef<AbortController | null>(null);
  useEffect(() => {
    ref.current = new AbortController();
    return () => {
      ref.current?.abort();
      ref.current = null;
    };
  }, []);
  return useCallback(() => {
    if (!ref.current) ref.current = new AbortController();
    return ref.current.signal;
  }, []);
}
