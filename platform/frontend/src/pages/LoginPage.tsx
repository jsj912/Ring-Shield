/** Login (FR-D01-03): POST /auth/login; the token stays in memory; one generic failure message. */
import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Loader2, Shield } from "lucide-react";
import { api } from "@/api/endpoints";
import { peekNotice, setSession, takeNotice } from "@/api/session";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Notice, errorText } from "@/components/shared";
import { useSession } from "@/app/session";

export function LoginPage() {
  const session = useSession();
  const location = useLocation();
  const [notice] = useState(peekNotice);          // read once, then cleared after the first render
  useEffect(() => {
    takeNotice();
  }, []);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({ mutationFn: api.login, onSuccess: (data) => setSession(data) });

  if (session) {
    const from = (location.state as { from?: string } | null)?.from;
    return <Navigate to={from && from !== "/login" ? from : "/rings"} replace />;
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate({ email, password });
  };

  return (
    <div className="bg-sidebar relative flex min-h-screen items-center justify-center overflow-hidden p-4">
      <div className="pointer-events-none absolute inset-0 opacity-40 [background:radial-gradient(60rem_40rem_at_20%_-10%,oklch(0.45_0.18_264/.6),transparent),radial-gradient(40rem_30rem_at_110%_110%,oklch(0.45_0.15_200/.4),transparent)]" />
      <div className="relative w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="bg-primary/20 text-primary rounded-xl p-3 ring-1 ring-white/10">
            <Shield className="size-7" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-white">RingShield Investigator</h1>
            <p className="text-sidebar-muted mt-1 text-sm">Sign in to view your bank's ring queue.</p>
          </div>
        </div>
        <Card className="shadow-xl">
          <CardContent className="pt-6">
            <form className="space-y-4" onSubmit={submit} aria-label="Sign in">
              {notice ? <Notice tone="info">{notice}</Notice> : null}
              {login.isError ? <Notice tone="error">{errorText(login.error)}</Notice> : null}
              <div className="space-y-1.5">
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
              </div>
              <Button type="submit" className="w-full" disabled={login.isPending}>
                {login.isPending ? <Loader2 className="animate-spin" /> : null}
                Sign in
              </Button>
            </form>
          </CardContent>
        </Card>
        <p className="text-sidebar-muted text-center text-xs">Your session is held in memory only; reloading the page signs you out.</p>
      </div>
    </div>
  );
}
