import { useCallback, useEffect, useRef } from 'react';

export function useStickyBottom({ scopeId = '', contentKey = '', active = false, threshold = 48 }) {
  const containerRef = useRef(null);
  const stickToBottomRef = useRef(true);
  const renderedScopeRef = useRef('');

  const pinToBottom = useCallback(() => {
    stickToBottomRef.current = true;
  }, []);

  const onScroll = useCallback((event) => {
    const container = event.currentTarget;
    const remaining = container.scrollHeight - container.scrollTop - container.clientHeight;
    stickToBottomRef.current = remaining <= threshold;
  }, [threshold]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const scopeChanged = renderedScopeRef.current !== scopeId;
    if (scopeChanged) {
      renderedScopeRef.current = scopeId;
      stickToBottomRef.current = true;
    }
    if (!scopeChanged && !stickToBottomRef.current) return undefined;
    const frame = window.requestAnimationFrame(() => {
      container.scrollTop = container.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [active, contentKey, scopeId]);

  return { containerRef, onScroll, pinToBottom };
}
