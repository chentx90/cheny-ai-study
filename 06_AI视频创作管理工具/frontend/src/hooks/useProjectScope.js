import { useCallback, useRef } from 'react';

export function useProjectScope(projectId) {
  const activeProjectRef = useRef(projectId || '');
  activeProjectRef.current = projectId || '';

  return useCallback(
    (expectedProjectId) => activeProjectRef.current === (expectedProjectId || ''),
    [],
  );
}
