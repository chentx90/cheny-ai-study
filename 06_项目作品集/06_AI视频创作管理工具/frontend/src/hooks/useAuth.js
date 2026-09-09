import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchMe, fetchSetupStatus } from '../api/auth';

export function useAuth() {
  const [user, setUser] = useState(null);
  const [projectRole, setProjectRole] = useState(null);
  const [capabilities, setCapabilities] = useState(null);
  const [authDisabled, setAuthDisabled] = useState(true);
  const [authState, setAuthState] = useState('checking');
  const authRequestIdRef = useRef(0);

  const refreshMe = useCallback(async (projectId = '') => {
    const requestId = ++authRequestIdRef.current;
    try {
      const data = await fetchMe(projectId);
      if (requestId !== authRequestIdRef.current) return data.user || null;
      setUser(data.user || null);
      setProjectRole(data.user?.project_role || null);
      setCapabilities(data.capabilities || null);
      setAuthDisabled(true);
      setAuthState(data.user ? 'authenticated' : 'anonymous');
      return data.user || null;
    } catch (_error) {
      if (requestId !== authRequestIdRef.current) return null;
      setUser(null);
      setProjectRole(null);
      setCapabilities(null);
      setAuthDisabled(true);
      setAuthState('anonymous');
      return null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await fetchSetupStatus();
        if (cancelled) return;
        setAuthDisabled(true);
        if (status.auth_disabled === false) {
          setAuthState('anonymous');
          return;
        }
        await refreshMe();
      } catch (_error) {
        if (!cancelled) setAuthState('anonymous');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshMe]);

  const isAdmin = user?.role === 'admin';
  const canWriteProject = isAdmin || projectRole === 'owner' || projectRole === 'editor';
  const canDeleteProject = isAdmin || projectRole === 'owner';

  return {
    user,
    projectRole,
    capabilities,
    authState,
    authDisabled,
    isAdmin,
    canWriteProject,
    canDeleteProject,
    canManageMembers: false,
    refreshMe,
    setProjectRole,
  };
}
