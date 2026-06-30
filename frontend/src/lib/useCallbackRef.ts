import { useCallback, useEffect, useRef } from "react";

// Returns a stable function identity that always calls the latest callback.
// Lets effects depend on it without re-running, and avoids stale closures in
// long-lived listeners (the progress websocket).
export function useCallbackRef<A extends any[], R>(fn: (...args: A) => R) {
  const ref = useRef(fn);
  useEffect(() => { ref.current = fn; });
  return useCallback((...args: A): R => ref.current(...args), []);
}
