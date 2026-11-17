import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Navigate, useLocation } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LogoMark } from "@/components/layout/Logo";
import { ApiError } from "@/lib/api";
import { useAuth } from "./AuthContext";

const schema = z.object({ username: z.string().min(1, "Enter your username"), password: z.string().min(1, "Enter your password") });
type Values = z.infer<typeof schema>;

export function LoginPage() {
  const { user, signIn } = useAuth();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { username: "admin", password: "admin" }
  });

  if (user) return <Navigate to={(location.state as { from?: string } | null)?.from ?? "/"} replace />;

  const onSubmit = async (v: Values) => {
    setError(null);
    try {
      await signIn(v.username, v.password);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Can't reach the server. Try again.");
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-3">
          <LogoMark className="size-10" />
          <div>
            <p className="text-lg font-semibold tracking-tight">NetPulse</p>
            <p className="text-sm text-muted-foreground">Real-time network monitoring</p>
          </div>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4 rounded-lg border bg-card p-6">
          <h1 className="text-base font-medium">Sign in</h1>
          {error && <p role="alert" className="rounded-md border border-status-down/30 bg-status-down/10 px-3 py-2 text-sm text-status-down">{error}</p>}
          <div className="space-y-1.5">
            <Label htmlFor="username">Username</Label>
            <Input id="username" autoComplete="username" autoFocus aria-invalid={!!errors.username} {...register("username")} />
            {errors.username && <p className="text-xs text-status-down">{errors.username.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" autoComplete="current-password" aria-invalid={!!errors.password} {...register("password")} />
            {errors.password && <p className="text-xs text-status-down">{errors.password.message}</p>}
          </div>
          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="animate-spin" />} Sign in
          </Button>
        </form>
      </div>
    </main>
  );
}
