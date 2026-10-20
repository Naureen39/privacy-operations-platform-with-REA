/**
 * Server side request forgery protection for website observation. This mirrors
 * backend/app/core/urlguard.py: the API validates a URL when it is registered and this
 * runner validates it again immediately before the browser connects.
 */
import { lookup } from "node:dns/promises";
import { isIP } from "node:net";
import { RunnerError } from "./errors.mjs";

function ipv4ToInt(address) {
  return address.split(".").reduce((acc, part) => acc * 256 + Number(part), 0);
}

function inCidr4(address, cidr) {
  const [base, bits = "32"] = cidr.split("/");
  const size = 2 ** (32 - Number(bits));
  const start = Math.floor(ipv4ToInt(base) / size) * size;
  const value = ipv4ToInt(address);
  return value >= start && value < start + size;
}

/** Expand an IPv6 address to 8 groups of 16 bits. */
function expandIPv6(address) {
  let text = address.split("%")[0].toLowerCase();
  const dotted = text.match(/^(.*:)(\d+\.\d+\.\d+\.\d+)$/);
  if (dotted) {
    const parts = dotted[2].split(".").map(Number);
    text = dotted[1] + ((parts[0] << 8) | parts[1]).toString(16) + ":" + ((parts[2] << 8) | parts[3]).toString(16);
  }
  const [head, tail] = text.split("::");
  const left = head ? head.split(":") : [];
  const right = tail ? tail.split(":") : [];
  const fill = text.includes("::") ? Array(8 - left.length - right.length).fill("0") : [];
  return [...left, ...fill, ...right].map((g) => parseInt(g || "0", 16));
}

/** Returns an IPv4 string when the IPv6 address embeds one (::ffff:a.b.c.d), else null. */
function mappedIPv4(groups) {
  const isMapped = groups.slice(0, 5).every((g) => g === 0) && groups[5] === 0xffff;
  if (!isMapped) return null;
  return [groups[6] >> 8, groups[6] & 255, groups[7] >> 8, groups[7] & 255].join(".");
}

function checkIPv4(address, allowedNetworks) {
  const always = ["0.0.0.0/8", "127.0.0.0/8", "169.254.0.0/16", "224.0.0.0/4", "240.0.0.0/4"];
  if (always.some((c) => inCidr4(address, c))) throw new RunnerError("url_rejected", `address ${address} is not permitted`);
  if (allowedNetworks.some((c) => !c.includes(":") && inCidr4(address, c))) return;
  const privateRanges = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "192.0.0.0/24", "192.0.2.0/24",
    "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24"];
  if (privateRanges.some((c) => inCidr4(address, c))) {
    throw new RunnerError("url_rejected", `address ${address} is in a private range outside the demo network`);
  }
}

export function checkAddress(address, allowedNetworks = []) {
  if (isIP(address) === 4) return checkIPv4(address, allowedNetworks);
  const groups = expandIPv6(address);
  const mapped = mappedIPv4(groups);
  if (mapped) return checkIPv4(mapped, allowedNetworks);
  const first = groups[0];
  const loopbackOrUnspecified = groups.slice(0, 7).every((g) => g === 0) && groups[7] <= 1;
  if (loopbackOrUnspecified || (first & 0xffc0) === 0xfe80 || (first & 0xff00) === 0xff00) {
    throw new RunnerError("url_rejected", `address ${address} is not permitted`);
  }
  if ((first & 0xfe00) === 0xfc00) throw new RunnerError("url_rejected", `address ${address} is in a private range`);
}

function hostAllowed(host, allowedHosts) {
  return allowedHosts.some((entry) => {
    const pattern = entry.toLowerCase().replace(/\.$/, "");
    if (pattern.startsWith("*.")) return host.endsWith(pattern.slice(1)) && host !== pattern.slice(2);
    return host === pattern;
  });
}

/**
 * @returns {Promise<{url: string, host: string, port: number, addresses: string[]}>}
 */
export async function validateObservationUrl(url, { allowedHosts = [], allowedNetworks = [], allowedPorts = [80, 443], resolver } = {}) {
  if (typeof url !== "string" || url.length > 2048) throw new RunnerError("url_rejected", "URL is missing or too long");
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    throw new RunnerError("url_rejected", "URL is malformed");
  }
  if (!["http:", "https:"].includes(parsed.protocol)) throw new RunnerError("url_rejected", "only http and https URLs are accepted");
  if (parsed.username || parsed.password) throw new RunnerError("url_rejected", "credentials in the URL are not accepted");
  const host = parsed.hostname.toLowerCase().replace(/\.$/, "").replace(/^\[|\]$/g, "");
  if (!host) throw new RunnerError("url_rejected", "URL has no host");
  if (!hostAllowed(host, allowedHosts)) throw new RunnerError("url_rejected", "host is not on the allowlist");
  const port = Number(parsed.port || (parsed.protocol === "https:" ? 443 : 80));
  if (!allowedPorts.includes(port)) throw new RunnerError("url_rejected", "port is not permitted");

  let addresses;
  try {
    addresses = resolver ? await resolver(host) : (await lookup(host, { all: true })).map((a) => a.address);
  } catch {
    throw new RunnerError("url_rejected", "host could not be resolved");
  }
  if (!addresses.length) throw new RunnerError("url_rejected", "host did not resolve");
  for (const address of addresses) checkAddress(address, allowedNetworks);
  return { url, host, port, addresses: [...new Set(addresses)] };
}
