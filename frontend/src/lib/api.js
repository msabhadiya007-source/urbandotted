import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const http = axios.create({ baseURL: API, withCredentials: true });

http.interceptors.request.use((config) => {
  const token = localStorage.getItem("ud_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export function formatApiErrorDetail(detail) {
  if (detail == null) return "Something went wrong. Please try again.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .filter(Boolean)
      .join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}

export const get = async (path, params) => (await http.get(path, { params })).data;
export const post = async (path, body) => (await http.post(path, body)).data;

export const fmt = {
  int: (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-AU")),
  dec: (n, d = 1) => (n === null || n === undefined ? "—" : Number(n).toFixed(d)),
  pct: (n, d = 1) => (n === null || n === undefined ? "—" : `${Number(n).toFixed(d)}%`),
  usd: (n, d = 2) => (n === null || n === undefined ? "—" : `$${Number(n).toFixed(d)}`),
  delta: (n, d = 1) =>
    n === null || n === undefined ? "—" : `${n > 0 ? "+" : ""}${Number(n).toFixed(d)}%`,
  time: (s) => (s ? new Date(s).toLocaleString("en-AU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"),
  ago: (s) => {
    if (!s) return "never";
    const mins = Math.round((Date.now() - new Date(s).getTime()) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
    return `${Math.round(mins / 1440)}d ago`;
  },
  path: (url) => {
    try {
      return new URL(url).pathname;
    } catch {
      return url;
    }
  },
};
