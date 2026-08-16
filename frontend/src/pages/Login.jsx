import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, ShieldCheck } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

export default function Login() {
  const { login, mode } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    const res = await login(email, password);
    setBusy(false);
    if (res.ok) navigate("/");
    else setError(res.error);
  };

  return (
    <div className="grain flex min-h-screen flex-col justify-center bg-[#0a0a0a] px-6 py-12 sm:px-12 lg:px-24">
      <div className="relative z-10 grid w-full max-w-5xl gap-12 lg:grid-cols-[1.1fr_1fr]">
        <div>
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 bg-[#34C759]" />
            <span className="label-caps">UrbanDotted · SEO Intelligence</span>
          </div>
          <h1 className="mt-6 text-4xl font-medium tracking-tighter sm:text-5xl">
            Stage 1 read-only
            <br />
            intelligence console.
          </h1>
          <p className="mt-4 max-w-md text-sm text-[#a3a3a3]">
            AU + NZ organic performance, opportunity scoring, dynamic tiering, technical monitoring and
            budget-gated agent operations. Zero Shopify writes.
          </p>
          <dl className="mt-8 grid max-w-md grid-cols-2 gap-px border border-[#262626] bg-[#262626]">
            {[
              ["Markets active", mode?.active_markets?.join(" · ") || "AU · NZ"],
              ["Schema markets", `${mode?.schema_markets?.length || 5} ready`],
              ["Shopify writes", "DENY"],
              ["Data mode", mode?.data_mode || "—"],
            ].map(([k, v]) => (
              <div key={k} className="bg-[#141414] p-4">
                <dt className="label-caps">{k}</dt>
                <dd className="num mt-1 text-sm">{v}</dd>
              </div>
            ))}
          </dl>
        </div>

        <form onSubmit={submit} className="panel h-fit p-6" data-testid="login-form">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-[#007AFF]" />
            <h2 className="text-lg font-medium">Administrator sign in</h2>
          </div>
          <p className="mt-1 text-xs text-[#a3a3a3]">
            Single admin in Stage 1. RBAC schema supports multi-admin.
          </p>

          <label className="label-caps mt-6 block">Email</label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            data-testid="login-email-input"
            autoComplete="username"
            className="num mt-1.5 w-full border border-[#262626] bg-[#0a0a0a] px-3 py-2 text-sm outline-none transition-colors duration-150 focus:border-[#007AFF] focus:ring-2 focus:ring-[#007AFF]/30"
          />

          <label className="label-caps mt-4 block">Password</label>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            data-testid="login-password-input"
            autoComplete="current-password"
            className="num mt-1.5 w-full border border-[#262626] bg-[#0a0a0a] px-3 py-2 text-sm outline-none transition-colors duration-150 focus:border-[#007AFF] focus:ring-2 focus:ring-[#007AFF]/30"
          />

          {error && (
            <p className="mt-4 border border-[#FF3B30]/40 bg-[#FF3B30]/10 px-3 py-2 text-xs text-[#FF6B62]" data-testid="login-error">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy}
            data-testid="login-submit-button"
            className="mt-6 flex w-full items-center justify-center gap-2 bg-white px-4 py-2.5 text-sm font-medium text-black transition-colors duration-150 hover:bg-[#d4d4d4] disabled:opacity-60"
          >
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            Sign in
          </button>
          <p className="mt-4 text-[11px] leading-relaxed text-[#525252]">
            Five failed attempts locks the account for 15 minutes. Every sign in is written to the
            hash-chained audit log.
          </p>
        </form>
      </div>
    </div>
  );
}
