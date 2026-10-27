import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { a11yViolations, mockFetch, renderAt } from "@/test/render";
import { LeadForm } from "./LeadForm";

afterEach(() => vi.unstubAllGlobals());

describe("LeadForm", () => {
  it("shows a message for each invalid field and sends nothing", async () => {
    const fetchMock = mockFetch({});
    renderAt(<LeadForm kind="contact" idPrefix="t" />);
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/Enter your name/)).toBeInTheDocument();
    expect(screen.getByText(/valid email address/)).toBeInTheDocument();
    expect(screen.getByLabelText("Full name")).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends the lead and confirms", async () => {
    const fetchMock = mockFetch({ "/api/v1/public/leads": { status: 202, body: { status: "accepted" } } });
    renderAt(<LeadForm kind="demo_request" idPrefix="t" submitLabel="Request a demo" />);
    await userEvent.type(screen.getByLabelText("Full name"), "Alex Example");
    await userEvent.type(screen.getByLabelText("Work email"), "alex@example.test");
    await userEvent.type(screen.getByLabelText("Company (optional)"), "Example Ltd");
    await userEvent.click(screen.getByRole("button", { name: "Request a demo" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Thank you");
    const body = JSON.parse((fetchMock.mock.calls[0]?.[1] as RequestInit).body as string);
    expect(body).toMatchObject({
      kind: "demo_request",
      name: "Alex Example",
      email: "alex@example.test",
      company: "Example Ltd",
    });
    expect(body.website).toBeUndefined();
  });

  it("uses a default name in the compact footer form", async () => {
    const fetchMock = mockFetch({ "/api/v1/public/leads": { status: 202, body: { status: "accepted" } } });
    renderAt(<LeadForm kind="contact" compact idPrefix="f" />);
    expect(screen.queryByLabelText("Full name")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Work email"), "pat@example.test");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("status");
    expect(JSON.parse((fetchMock.mock.calls[0]?.[1] as RequestInit).body as string).name).toBe("Website visitor");
  });

  it("explains a rate limit and keeps the form", async () => {
    mockFetch({ "/api/v1/public/leads": { status: 429, body: { detail: "Too many" } } });
    renderAt(<LeadForm kind="contact" idPrefix="t" />);
    await userEvent.type(screen.getByLabelText("Full name"), "Alex Example");
    await userEvent.type(screen.getByLabelText("Work email"), "alex@example.test");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Too many requests/);
    expect(screen.getByLabelText("Full name")).toHaveValue("Alex Example");
  });

  it("reports an unreachable service", async () => {
    mockFetch({});
    renderAt(<LeadForm kind="contact" idPrefix="t" />);
    await userEvent.type(screen.getByLabelText("Full name"), "Alex Example");
    await userEvent.type(screen.getByLabelText("Work email"), "alex@example.test");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/cannot be reached/));
  });

  it("has no structural accessibility violations", async () => {
    const { container } = renderAt(<LeadForm kind="contact" idPrefix="t" />);
    expect(await a11yViolations(container)).toEqual([]);
  });
});
