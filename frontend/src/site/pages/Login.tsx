import { zodResolver } from "@hookform/resolvers/zod";
import { Eye, EyeOff, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ApiError, landingPath, login } from "@/lib/api";
import { usePageMeta } from "@/lib/queries";
import { Logo } from "../art/Logo";

const schema = z.object({
  email: z
    .string()
    .trim()
    .min(1, "Enter your email address")
    .regex(/^[^@\s]+@[^@\s]+\.[^@\s]+$/, "Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});
type Values = z.infer<typeof schema>;

export function loginMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "The email or password is not correct.";
    if (error.status === 429) return "Too many attempts. Please wait a minute and try again.";
    if (error.status === 403) return "This account has no access to an organization.";
    if (error.status === 0) return error.message;
  }
  return "Sign in failed. Please try again.";
}

export default function Login() {
  usePageMeta("Sign in", "Sign in to the ProcessLedger console.");
  const navigate = useNavigate();
  const [show, setShow] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [forgot, setForgot] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  async function onSubmit(values: Values) {
    setFailure(null);
    try {
      const session = await login(values.email, values.password);
      navigate(landingPath(session.role), { replace: true });
    } catch (error) {
      setFailure(loginMessage(error));
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-navy p-12 text-white lg:flex">
        <div aria-hidden="true" className="absolute -right-24 -top-24 size-96 rounded-full bg-primary/40 blur-3xl" />
        <Link to="/" aria-label="ProcessLedger home" className="relative">
          <Logo inverse />
        </Link>
        <div className="relative max-w-md">
          <ShieldCheck aria-hidden="true" className="mb-6 size-10 text-accent" />
          <h2 className="text-3xl text-white">Know where personal data lives. Prove it with evidence.</h2>
          <p className="mt-4 text-white/80">
            Sign in to the demonstration console to explore records, findings, assessments and requests for a fictional
            retailer.
          </p>
        </div>
        <p className="relative text-sm text-white/70">Demonstration environment. Sample data only.</p>
      </aside>
      <main id="main" className="flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-md">
          <Link to="/" className="mb-8 inline-block lg:hidden" aria-label="ProcessLedger home">
            <Logo />
          </Link>
          <h1 className="text-3xl">Sign in</h1>
          <p className="mt-2 text-muted-foreground">Use the account you were given for the demonstration.</p>
          <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-8 space-y-5" aria-label="Sign in">
            <Field id="login-email" label="Email" error={errors.email?.message}>
              {(p) => <Input type="email" autoComplete="username" {...p} {...register("email")} />}
            </Field>
            <Field id="login-password" label="Password" error={errors.password?.message}>
              {(p) => (
                <div className="relative">
                  <Input
                    type={show ? "text" : "password"}
                    autoComplete="current-password"
                    className="pr-12"
                    {...p}
                    {...register("password")}
                  />
                  <button
                    type="button"
                    onClick={() => setShow((s) => !s)}
                    aria-label={show ? "Hide password" : "Show password"}
                    aria-pressed={show}
                    className="absolute right-1 top-1 inline-flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
                  >
                    {show ? (
                      <EyeOff aria-hidden="true" className="size-5" />
                    ) : (
                      <Eye aria-hidden="true" className="size-5" />
                    )}
                  </button>
                </div>
              )}
            </Field>
            {failure && (
              <p role="alert" className="rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
                {failure}
              </p>
            )}
            <Button type="submit" size="lg" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? "Signing in..." : "Sign in"}
            </Button>
          </form>
          <div className="mt-6 text-sm">
            <button
              type="button"
              onClick={() => setForgot((f) => !f)}
              aria-expanded={forgot}
              className="font-semibold text-primary hover:underline"
            >
              Forgot your password?
            </button>
            {forgot && (
              <p className="mt-2 rounded-md bg-muted p-3 text-muted-foreground">
                Password reset is not available in the demonstration. Ask the administrator of your organization to
                provision a new password.
              </p>
            )}
          </div>
          <p className="mt-8 text-sm text-muted-foreground">
            Registration is disabled. Accounts are created by an administrator.{" "}
            <Link to="/contact?tab=demo" className="font-semibold text-primary hover:underline">
              Request a demo
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
}
