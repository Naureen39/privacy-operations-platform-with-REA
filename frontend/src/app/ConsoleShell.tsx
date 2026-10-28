import { RequireSession } from "./session";
import { ConsoleLayout } from "./layout/ConsoleLayout";
import { ToastProvider } from "./ui/toast";

/** The signed in console: a session is required, and toasts are available everywhere inside it. */
export default function ConsoleShell() {
  return (
    <RequireSession>
      <ToastProvider>
        <ConsoleLayout />
      </ToastProvider>
    </RequireSession>
  );
}
