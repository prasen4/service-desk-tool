import { useEffect, useState } from "react";
import { api, AuthStatus } from "../api";

const DISABLED: AuthStatus = { enabled: false, logged_in: false, user: null };

/** Fetches Okta login status once on mount. Returns `DISABLED` (safe default)
 * until the request resolves or if Okta login isn't configured. */
export function useAuthStatus(): AuthStatus {
  const [status, setStatus] = useState<AuthStatus>(DISABLED);

  useEffect(() => {
    let cancelled = false;
    api
      .get<AuthStatus>("/api/auth/status")
      .then((res) => {
        if (!cancelled) setStatus(res);
      })
      .catch(() => {
        /* auth status is best-effort UI only — ignore failures */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return status;
}
