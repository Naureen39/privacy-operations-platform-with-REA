/** The price list and the cost calculator. The formula is the one the invoice run uses: the base
 *  fee, plus systems and requests beyond the allowance at the plan's unit price. A plan with no
 *  unit price (Starter) cannot take more than it includes. */

import { api } from "./api";

export interface Plan {
  code: string;
  name: string;
  monthly_fee_cents: number;
  included_systems: number;
  included_requests: number;
  extra_system_cents: number;
  extra_request_cents: number;
}

/** Shown if the price list cannot be loaded (for example a static preview with no API). The same
 *  values the database migration seeds. */
export const FALLBACK_PLANS: Plan[] = [
  {
    code: "starter",
    name: "Starter",
    monthly_fee_cents: 0,
    included_systems: 3,
    included_requests: 5,
    extra_system_cents: 0,
    extra_request_cents: 0,
  },
  {
    code: "professional",
    name: "Professional",
    monthly_fee_cents: 39900,
    included_systems: 25,
    included_requests: 50,
    extra_system_cents: 1500,
    extra_request_cents: 800,
  },
  {
    code: "enterprise",
    name: "Enterprise",
    monthly_fee_cents: 180000,
    included_systems: 150,
    included_requests: 500,
    extra_system_cents: 600,
    extra_request_cents: 400,
  },
];

export const fetchPlans = () => api.get<Plan[]>("/api/v1/public/plans");

export interface Estimate {
  plan: Plan;
  fits: boolean;
  baseCents: number;
  extraSystems: number;
  extraRequests: number;
  extraSystemsCents: number;
  extraRequestsCents: number;
  totalCents: number;
}

export function estimate(plan: Plan, systems: number, requests: number): Estimate {
  const extraSystems = Math.max(0, systems - plan.included_systems);
  const extraRequests = Math.max(0, requests - plan.included_requests);
  const billsExtras = plan.extra_system_cents > 0 || plan.extra_request_cents > 0;
  const fits = billsExtras || (extraSystems === 0 && extraRequests === 0);
  const extraSystemsCents = extraSystems * plan.extra_system_cents;
  const extraRequestsCents = extraRequests * plan.extra_request_cents;
  return {
    plan,
    fits,
    baseCents: plan.monthly_fee_cents,
    extraSystems,
    extraRequests,
    extraSystemsCents,
    extraRequestsCents,
    totalCents: plan.monthly_fee_cents + extraSystemsCents + extraRequestsCents,
  };
}

/** The cheapest plan that can take the usage. */
export function recommend(plans: Plan[], systems: number, requests: number): Estimate | null {
  const options = plans.map((p) => estimate(p, systems, requests)).filter((e) => e.fits);
  if (options.length === 0) return null;
  return options.reduce((best, e) => (e.totalCents < best.totalCents ? e : best));
}

export function formatMoney(cents: number): string {
  const dollars = cents / 100;
  const whole = Number.isInteger(dollars);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(dollars);
}
