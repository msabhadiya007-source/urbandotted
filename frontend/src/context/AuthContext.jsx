import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { formatApiErrorDetail, get, http, post } from "@/lib/api";

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null); // null = checking, false = anonymous
  const [mode, setMode] = useState(null);

  const loadMode = useCallback(async () => {
    try {
      setMode(await get("/meta/mode"));
    } catch {
      setMode(null);
    }
  }, []);

  useEffect(() => {
    (async () => {
      await loadMode();
      try {
        setUser(await get("/auth/me"));
      } catch {
        setUser(false);
      }
    })();
  }, [loadMode]);

  const login = async (email, password) => {
    try {
      const data = await post("/auth/login", { email, password });
      if (data.access_token) localStorage.setItem("ud_token", data.access_token);
      setUser(data);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: formatApiErrorDetail(e.response?.data?.detail) || e.message };
    }
  };

  const logout = async () => {
    try {
      await http.post("/auth/logout");
    } catch {
      /* ignore */
    }
    localStorage.removeItem("ud_token");
    setUser(false);
  };

  return (
    <AuthContext.Provider value={{ user, mode, login, logout }}>{children}</AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
