import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";

import { ApiError } from "@/lib/api";
import { a11yViolations, mockFetch, renderAt } from "@/test/render";
import Login, { loginMessage } from "./Login";

afterEach(() => vi.unstubAllGlobals());

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function page() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="*" element={<Where />} />
    </Routes>
  );
}

const session = (role: string) => ({
  status: 200,
  body: { user: { id: "u", email: "a@b.test", full_name: "A" }, org_id: "o", role, memberships: [] },
});

async function fill(email = "admin@example.test", password = "a-long-passphrase") {
  await userEvent.type(screen.getByLabelText("Email"), email);
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("Login", () => {
  it("validates before sending", async () => {
    const fetchMock = mockFetch({});
    renderAt(page(), "/login");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your email address")).toBeInTheDocument();
    expect(screen.getByText("Enter your password")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends an administrator to the console", async () => {
    mockFetch({ "/api/v1/auth/login": session("admin") });
    renderAt(page(), "/login");
    await fill();
    expect(await screen.findByTestId("where")).toHaveTextContent("/app");
  });

  it("sends a viewer to the records area", async () => {
    mockFetch({ "/api/v1/auth/login": session("viewer") });
    renderAt(page(), "/login");
    await fill();
    expect(await screen.findByTestId("where")).toHaveTextContent("/app/records");
  });

  it("shows one message for wrong credentials and keeps the email", async () => {
    mockFetch({ "/api/v1/auth/login": { status: 401, body: { detail: "Invalid credentials" } } });
    renderAt(page(), "/login");
    await fill();
    expect(await screen.findByRole("alert")).toHaveTextContent("The email or password is not correct.");
    expect(screen.getByLabelText("Email")).toHaveValue("admin@example.test");
  });

  it("toggles password visibility and explains the forgot password placeholder", async () => {
    renderAt(page(), "/login");
    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(password).toHaveAttribute("type", "text");
    await userEvent.click(screen.getByRole("button", { name: "Forgot your password?" }));
    expect(screen.getByText(/not available in the demonstration/)).toBeInTheDocument();
  });

  it("has no structural accessibility violations", async () => {
    const { container } = renderAt(page(), "/login");
    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe("loginMessage", () => {
  it("maps statuses to plain messages", () => {
    expect(loginMessage(new ApiError("x", 429))).toMatch(/Too many attempts/);
    expect(loginMessage(new ApiError("x", 403))).toMatch(/no access/);
    expect(loginMessage(new ApiError("down", 0))).toBe("down");
    expect(loginMessage(new Error("boom"))).toMatch(/Sign in failed/);
  });
});
