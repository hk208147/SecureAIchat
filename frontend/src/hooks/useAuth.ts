import { useEffect, useState, useCallback } from 'react';
import { getCurrentUser, fetchAuthSession, signOut as amplifySignOut } from 'aws-amplify/auth';

interface UseAuthResult {
  isAuthenticated: boolean;
  isLoading: boolean;
  getAccessToken: () => Promise<string | null>;
  signOut: () => Promise<void>;
}

export function useAuth(): UseAuthResult {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function checkAuth() {
      try {
        await getCurrentUser();
        if (!cancelled) setIsAuthenticated(true);
      } catch {
        if (!cancelled) setIsAuthenticated(false);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void checkAuth();
    return () => { cancelled = true; };
  }, []);

  const getAccessToken = useCallback(async (): Promise<string | null> => {
    try {
      const session = await fetchAuthSession();
      return session.tokens?.accessToken?.toString() ?? null;
    } catch {
      setIsAuthenticated(false);
      return null;
    }
  }, []);

  const signOut = useCallback(async () => {
    await amplifySignOut();
    setIsAuthenticated(false);
  }, []);

  return { isAuthenticated, isLoading, getAccessToken, signOut };
}
