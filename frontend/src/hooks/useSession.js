import { useEffect, useState } from "react";
import { AUTH_STORAGE_KEY } from "@/appConfig";
import { fetchSession, loginRequest, logoutRequest, readStoredToken, registerRequest, writeStoredToken } from "@/lib/session";

const initialState = {
  status: "booting",
  user: null,
  token: "",
  error: "",
};

export function useSession() {
  const [state, setState] = useState(initialState);
  const [storageReady, setStorageReady] = useState(typeof window === "undefined");

  useEffect(() => {
    let active = true;
    async function restoreFromStorage() {
      const storedToken = typeof window !== "undefined" ? await readStoredToken() : "";
      if (!active) {
        return;
      }

      setStorageReady(true);
      setState({
        status: storedToken ? "booting" : "anonymous",
        user: null,
        token: storedToken,
        error: "",
      });
    }

    restoreFromStorage();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!storageReady || state.status !== "booting") {
      return;
    }

    const controller = new AbortController();
    const token = state.token;

    async function hydrate() {
      if (!token) {
        setState((current) => ({ ...current, status: "anonymous", error: "" }));
        return;
      }

      setState((current) => ({ ...current, status: "booting", error: "" }));
      try {
        const payload = await fetchSession(token, controller.signal);
        await writeStoredToken(token);
        if (controller.signal.aborted) {
          return;
        }
        setState({
          status: "authenticated",
          user: payload?.data?.user || null,
          token,
          error: "",
        });
      } catch (error) {
        if (controller.signal.aborted || error?.name === "AbortError") {
          return;
        }
        await writeStoredToken("");
        setState({
          status: "anonymous",
          user: null,
          token: "",
          error: error.message || "会话已失效，请重新登录。",
        });
      }
    }

    hydrate();
    return () => controller.abort();
  }, [state.status, state.token, storageReady]);

  useEffect(() => {
    async function syncTokenFromStorage() {
      const nextToken = await readStoredToken();
      if (!nextToken) {
        setState({
          status: "anonymous",
          user: null,
          token: "",
          error: "",
        });
        return;
      }

      setState((current) => ({ ...current, status: "booting", token: nextToken, error: "" }));
    }

    function handleStorage(event) {
      if (event.key !== AUTH_STORAGE_KEY) {
        return;
      }
      syncTokenFromStorage();
    }

    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, []);

  async function completeAuth(payload) {
    const nextToken = payload?.data?.token || "";
    const nextUser = payload?.data?.user || null;
    await writeStoredToken(nextToken);
    setState({
      status: "authenticated",
      user: nextUser,
      token: nextToken,
      error: "",
    });
    return payload;
  }

  async function login(credentials) {
    setState((current) => ({ ...current, status: "authenticating", error: "" }));
    try {
      const payload = await loginRequest(credentials);
      return await completeAuth(payload);
    } catch (error) {
      setState((current) => ({ ...current, status: "anonymous", error: error.message || "登录失败" }));
      throw error;
    }
  }

  async function register(credentials) {
    setState((current) => ({ ...current, status: "authenticating", error: "" }));
    try {
      const payload = await registerRequest(credentials);
      return await completeAuth(payload);
    } catch (error) {
      setState((current) => ({ ...current, status: "anonymous", error: error.message || "注册失败" }));
      throw error;
    }
  }

  async function logout() {
    const activeToken = state.token;
    try {
      if (activeToken) {
        await logoutRequest(activeToken);
      }
    } catch {
      // 退出登录时优先清理本地会话。
    } finally {
      await writeStoredToken("");
      setState({
        status: "anonymous",
        user: null,
        token: "",
        error: "",
      });
    }
  }

  return {
    ...state,
    isReady: state.status !== "booting",
    isAuthenticated: state.status === "authenticated",
    login,
    register,
    logout,
  };
}
