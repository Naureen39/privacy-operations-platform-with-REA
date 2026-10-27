import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import { ApiError, submitLead, type LeadInput } from "@/lib/api";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const schema = z.object({
  name: z.string().trim().min(2, "Enter your name (at least 2 characters)").max(200),
  email: z.string().trim().regex(EMAIL, "Enter a valid email address").max(320),
  company: z.string().max(200).optional(),
  message: z.string().max(4000, "Keep the message under 4000 characters").optional(),
  website: z.string().max(200).optional(), // hidden field that bots fill in
});
type Values = z.infer<typeof schema>;

interface Props {
  kind: LeadInput["kind"];
  /** Footer variant: only an email and a short message. */
  compact?: boolean;
  idPrefix: string;
  /** Accessible name of the form; each form on a page needs a different one. */
  label?: string;
  submitLabel?: string;
  messageLabel?: string;
}

export function LeadForm({
  kind,
  compact = false,
  idPrefix,
  label,
  submitLabel = "Send",
  messageLabel = "Message",
}: Props) {
  const [done, setDone] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: compact ? { name: "Website visitor" } : {},
  });

  async function onSubmit(values: Values) {
    setFailure(null);
    try {
      const lead: LeadInput = { kind, name: values.name, email: values.email };
      if (values.company) lead.company = values.company;
      if (values.message) lead.message = values.message;
      if (values.website) lead.website = values.website;
      await submitLead(lead);
      setDone(true);
      reset();
    } catch (error) {
      setFailure(
        error instanceof ApiError && error.status === 429
          ? "Too many requests. Please wait a minute and try again."
          : error instanceof ApiError
            ? error.message
            : "Something went wrong. Please try again.",
      );
    }
  }

  if (done) {
    return (
      <div
        role="status"
        className="flex items-start gap-3 rounded-md border border-success/40 bg-success/10 p-4 text-sm text-foreground"
      >
        <CheckCircle2 aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-success" />
        <div>
          <p className="font-semibold text-navy">Thank you. Your message was received.</p>
          <p className="text-muted-foreground">This is a demonstration site, so no one will reply to it.</p>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit(onSubmit)}
      noValidate
      className="space-y-4"
      aria-label={label ?? (kind === "demo_request" ? "Demo request form" : "Contact form")}
    >
      {!compact && (
        <Field id={`${idPrefix}-name`} label="Full name" error={errors.name?.message}>
          {(p) => <Input autoComplete="name" {...p} {...register("name")} />}
        </Field>
      )}
      <Field id={`${idPrefix}-email`} label="Work email" error={errors.email?.message}>
        {(p) => <Input type="email" autoComplete="email" {...p} {...register("email")} />}
      </Field>
      {!compact && (
        <Field id={`${idPrefix}-company`} label="Company (optional)" error={errors.company?.message}>
          {(p) => <Input autoComplete="organization" {...p} {...register("company")} />}
        </Field>
      )}
      <Field id={`${idPrefix}-message`} label={messageLabel} error={errors.message?.message}>
        {(p) => <Textarea className={compact ? "min-h-20" : undefined} {...p} {...register("message")} />}
      </Field>
      {/* Humans never see this field; a bot that fills it in is dropped by the API. */}
      <div aria-hidden="true" className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
        <label htmlFor={`${idPrefix}-website`}>Leave this field empty</label>
        <input id={`${idPrefix}-website`} tabIndex={-1} autoComplete="off" {...register("website")} />
      </div>
      {failure && (
        <p role="alert" className="rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          {failure}
        </p>
      )}
      <Button type="submit" disabled={isSubmitting} className={compact ? "w-full" : undefined}>
        {isSubmitting ? "Sending..." : submitLabel}
      </Button>
    </form>
  );
}
