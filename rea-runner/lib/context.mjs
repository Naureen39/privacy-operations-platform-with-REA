/** Runner settings, read once from the environment. */
function list(name, fallback = []) {
  const raw = process.env[name];
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

export function buildContext() {
  const mode = process.env.REA_RUNNER_ROLE || "all"; // offline | browser | all
  return {
    inputRoot: process.env.REA_INPUT_DIR || "/input",
    reaTimeoutMs: Number(process.env.REA_TIMEOUT_SECONDS || 120) * 1000,
    browserTimeoutMs: Number(process.env.REA_BROWSER_TIMEOUT_SECONDS || 60) * 1000,
    allowOffline: mode === "offline" || mode === "all",
    allowBrowser: mode === "browser" || mode === "all",
    urlPolicy: {
      allowedHosts: list("OBSERVATION_ALLOWED_HOSTS"),
      allowedNetworks: list("OBSERVATION_ALLOWED_NETWORKS"),
      allowedPorts: list("OBSERVATION_ALLOWED_PORTS", [80, 443]),
    },
  };
}
