"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

const countries = ["India", "United States", "United Kingdom", "Canada", "Australia", "Germany", "Singapore", "United Arab Emirates", "Japan", "Other"];

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [country, setCountry] = useState("India");
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    if (mode === "signin") {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      setLoading(false);
      if (error) { setError(error.message); return; }
      router.push("/dashboard");
      return;
    }

    if (!fullName.trim()) { setLoading(false); setError("Please enter your name."); return; }

    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: { data: { full_name: fullName.trim(), country } },
    });
    if (error) { setLoading(false); setError(error.message); return; }

    if (data.user) {
      const { error: profileError } = await supabase.from("profiles").upsert({
        id: data.user.id,
        email,
        full_name: fullName.trim(),
        country,
        region: country === "India" ? "IN" : "INTL",
      });
      if (profileError) { setLoading(false); setError(`Account created, but profile setup failed: ${profileError.message}`); return; }
    }

    setLoading(false);
    router.push("/dashboard");
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4 py-8">
      <div className="w-full max-w-sm rounded-lg border border-border bg-bg-panel p-8">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-dim text-accent"><span className="text-sm font-bold">M</span></div>
          <span className="font-semibold tracking-tight">ManiQuantAI</span>
        </div>
        <h1 className="mb-1 text-lg font-semibold">{mode === "signin" ? "Welcome back" : "Create your account"}</h1>
        <p className="mb-6 text-sm text-text-muted">{mode === "signin" ? "Sign in to your strategies." : "Tell us a little about yourself to personalize your workspace."}</p>
        <form onSubmit={handleSubmit} className="space-y-3">
          {mode === "signup" && <>
            <input type="text" required placeholder="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-faint outline-none focus:border-accent" />
            <select required value={country} onChange={(e) => setCountry(e.target.value)} className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"><option value="" disabled>Country</option>{countries.map((c) => <option key={c} value={c}>{c}</option>)}</select>
          </>}
          <input type="email" required placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-faint outline-none focus:border-accent" />
          <input type="password" required minLength={8} placeholder="Password (8+ characters)" value={password} onChange={(e) => setPassword(e.target.value)} className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-faint outline-none focus:border-accent" />
          {mode === "signup" && <p className="text-xs text-text-faint">Your password is securely managed by Supabase Auth and is never stored in your profile table.</p>}
          {error && <p className="text-sm text-danger">{error}</p>}
          <button type="submit" disabled={loading} className="w-full rounded-lg bg-accent py-2 text-sm font-medium text-bg disabled:opacity-50">{loading ? "Please wait…" : mode === "signin" ? "Sign in" : "Sign up"}</button>
        </form>
        <button onClick={() => { setMode(mode === "signin" ? "signup" : "signin"); setError(null); }} className="mt-4 w-full text-center text-xs text-text-muted hover:text-text">{mode === "signin" ? "Need an account? Sign up" : "Already have an account? Sign in"}</button>
      </div>
    </div>
  );
}
