import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Activity, AlertTriangle, BarChart3, Boxes, Brain, Coins, FlaskConical, Gauge,
  LayoutGrid, LogOut, Plug, Radar, Search, ShieldCheck, Target, TriangleAlert, Wrench,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const NAV = [
  { section: "Command" },
  { to: "/", label: "Overview", icon: LayoutGrid, testId: "nav-overview" },
  { to: "/war-room/AU", label: "AU War Room", icon: Radar, testId: "nav-warroom-au" },
  { to: "/war-room/NZ", label: "NZ War Room", icon: Radar, testId: "nav-warroom-nz" },
  { section: "Intelligence" },
  { to: "/opportunities", label: "Opportunities", icon: Target, testId: "nav-opportunities" },
  { to: "/keywords", label: "Keywords / GSC", icon: Search, testId: "nav-keywords" },
  { to: "/technical", label: "Technical SEO", icon: Wrench, testId: "nav-technical" },
  { section: "Operations" },
  { to: "/ai-operations", label: "AI Operations", icon: Brain, testId: "nav-ai-operations" },
  { to: "/cost", label: "Cost", icon: Coins, testId: "nav-cost" },
  { to: "/connections", label: "Connections", icon: Plug, testId: "nav-connections" },
  { section: "Stage 1 backlog" },
  { label: "Products", icon: Boxes, disabled: true },
  { label: "Collections", icon: BarChart3, disabled: true },
  { label: "Competitors", icon: Gauge, disabled: true },
  { label: "Approvals", icon: ShieldCheck, disabled: true },
  { label: "Experiments", icon: FlaskConical, disabled: true },
];

export default function Layout() {
  const { user, mode, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="grain flex h-screen overflow-hidden bg-[#0a0a0a]">
      <aside className="hidden w-[236px] shrink-0 flex-col border-r border-[#262626] bg-[#0a0a0a] lg:flex">
        <div className="border-b border-[#262626] px-5 py-4">
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 bg-[#34C759]" />
            <span className="text-sm font-semibold tracking-tight">UrbanDotted</span>
          </div>
          <p className="label-caps mt-1">SEO Intelligence · Stage 1</p>
        </div>

        <nav className="flex-1 overflow-y-auto py-2" data-testid="sidebar-nav">
          {NAV.map((item, i) =>
            item.section ? (
              <p key={`s${i}`} className="label-caps px-5 pb-1 pt-4">
                {item.section}
              </p>
            ) : item.disabled ? (
              <div
                key={item.label}
                title="Implemented in the next dashboard milestone"
                className="flex cursor-not-allowed items-center gap-2.5 px-5 py-2 text-sm text-[#525252] opacity-50"
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </div>
            ) : (
              <NavLink
                key={item.to}
                to={item.to}
                data-testid={item.testId}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 border-l-2 px-5 py-2 text-sm transition-colors duration-150 ${
                    isActive
                      ? "border-white bg-[#141414] text-white"
                      : "border-transparent text-[#a3a3a3] hover:bg-[#141414] hover:text-white"
                  }`
                }
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </NavLink>
            )
          )}
        </nav>

        <div className="border-t border-[#262626] px-5 py-3">
          <p className="num truncate text-xs text-[#a3a3a3]" data-testid="sidebar-user-email">
            {user?.email}
          </p>
          <div className="mt-1 flex items-center justify-between">
            <span className="label-caps">{user?.role}</span>
            <button
              onClick={async () => {
                await logout();
                navigate("/login");
              }}
              data-testid="logout-button"
              className="flex items-center gap-1 text-xs text-[#a3a3a3] transition-colors duration-150 hover:text-white"
            >
              <LogOut className="h-3.5 w-3.5" /> Sign out
            </button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {mode?.data_mode === "DEMO" && (
          <div
            className="flex flex-wrap items-center gap-x-3 gap-y-1 bg-[#FFCC00] px-4 py-1.5 text-[11px] font-semibold text-black"
            data-testid="demo-banner"
          >
            <span className="flex items-center gap-1.5">
              <TriangleAlert className="h-3.5 w-3.5" /> DEMO DATA ACTIVE
            </span>
            <span className="font-normal">
              Development fixtures · adapter {mode.database_adapter} · queue {mode.queue_backend} · live
              sources pending: {mode.missing_live_sources?.join(", ") || "none"}
            </span>
            <a href="/connections" className="ml-auto underline">Connect live data →</a>
          </div>
        )}
        <div className="flex items-center justify-between border-b border-[#262626] px-4 py-2 lg:hidden">
          <span className="text-sm font-semibold">UrbanDotted SEO</span>
          <span className="label-caps">Stage 1</span>
        </div>
        <nav className="flex gap-1 overflow-x-auto border-b border-[#262626] px-2 py-1.5 lg:hidden" data-testid="mobile-nav">
          {NAV.filter((n) => n.to).map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `whitespace-nowrap border px-2.5 py-1 text-xs transition-colors duration-150 ${
                  isActive ? "border-white bg-[#141414] text-white" : "border-[#262626] text-[#a3a3a3]"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <main className="relative z-10 flex-1 overflow-y-auto" data-testid="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export const PageHeader = ({ title, description, right, testId }) => (
  <header className="flex flex-col gap-3 border-b border-[#262626] px-4 py-5 sm:px-6 md:flex-row md:items-end md:justify-between">
    <div>
      <h1 className="text-3xl font-medium tracking-tighter sm:text-4xl" data-testid={testId}>
        {title}
      </h1>
      {description && <p className="mt-1.5 max-w-2xl text-sm text-[#a3a3a3]">{description}</p>}
    </div>
    {right}
  </header>
);

export const StageNotice = () => (
  <div className="flex items-start gap-2 border border-[#262626] bg-[#141414] px-4 py-2.5 text-xs text-[#a3a3a3]">
    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#FFCC00]" />
    <span>
      Stage 1 is read-only. Every Shopify write policy compiles to DENY and no write route exists in the
      API. Proposed actions are logged with evidence for Stage 2.
    </span>
  </div>
);

export const ActivityDot = ({ status }) => (
  <span
    className={`inline-block h-1.5 w-1.5 ${
      status === "success" || status === "healthy"
        ? "bg-[#34C759]"
        : status === "failed" || status === "degraded"
          ? "bg-[#FF3B30]"
          : status === "running"
            ? "bg-[#007AFF]"
            : "bg-[#525252]"
    }`}
  />
);

export { Activity };
