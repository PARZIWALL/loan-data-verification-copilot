"use client";

/**
 * Session state and role-based route guarding.
 *
 * The backend is the real authority on permissions -- every mutating endpoint checks
 * the role itself and returns 403. This guard exists so the UI never *offers* an
 * action the user cannot take, and so an expired token routes cleanly back to login
 * instead of surfacing a raw 401 on every panel.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api, tokenStore } from "./api";
import type { Role, User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    // Restore an existing session, and confirm the token is still valid rather than
    // trusting whatever is in localStorage.
    const cached = tokenStore.getUser();
    if (!cached) {
      setLoading(false);
      return;
    }
    setUser(cached);
    api
      .me()
      .then(setUser)
      .catch(() => {
        tokenStore.clear();
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const result = await api.login(username, password);
    tokenStore.set(result.access_token, result.user);
    setUser(result.user);
    return result.user;
  }, []);

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
    router.push("/login");
  }, [router]);

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

/** Send an expired session back to login; leave other errors to the caller. */
export function useApiErrorHandler() {
  const { logout } = useAuth();
  return useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.isUnauthorized) logout();
    },
    [logout],
  );
}

export const ROLE_LABELS: Record<Role, string> = {
  data_operator: "Data Operator",
  reviewer: "Reviewer",
  data_consumer: "Data Consumer",
};

export interface NavItem {
  href: string;
  label: string;
  roles: Role[];
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", roles: ["data_operator", "reviewer", "data_consumer"] },
  { href: "/upload", label: "Upload", roles: ["data_operator"] },
  { href: "/loans", label: "Loans", roles: ["data_operator", "reviewer"] },
  { href: "/exceptions", label: "Exception Queue", roles: ["reviewer"] },
  { href: "/verified-loans", label: "Verified Records", roles: ["data_consumer", "reviewer"] },
  { href: "/audit", label: "Audit Trail", roles: ["data_consumer"] },
];

export function navFor(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role));
}
