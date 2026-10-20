import assert from "node:assert/strict";
import { test } from "node:test";
import { validateObservationUrl } from "../lib/urlguard.mjs";

const policy = (extra = {}) => ({
  allowedHosts: ["shop.northbridge.test", "*.northbridge.test"],
  allowedNetworks: [],
  allowedPorts: [80, 443],
  ...extra,
});
const resolveTo = (...addresses) => async () => addresses;
const rejects = (url, options, resolver) =>
  assert.rejects(() => validateObservationUrl(url, { ...options, resolver }), { code: "url_rejected" });

test("accepts a public address and pins it", async () => {
  const result = await validateObservationUrl("https://shop.northbridge.test/checkout", {
    ...policy(),
    resolver: resolveTo("93.184.216.34"),
  });
  assert.deepEqual(result.addresses, ["93.184.216.34"]);
  assert.equal(result.port, 443);
});

test("accepts a wildcard host inside the demo network", async () => {
  const result = await validateObservationUrl("http://cms.northbridge.test", {
    ...policy({ allowedNetworks: ["172.28.0.0/16"] }),
    resolver: resolveTo("172.28.0.7"),
  });
  assert.deepEqual(result.addresses, ["172.28.0.7"]);
});

for (const address of [
  "127.0.0.1", "127.9.9.9", "::1", "169.254.169.254", "fe80::1", "10.1.2.3", "192.168.0.10", "172.16.5.5",
  "0.0.0.0", "224.0.0.1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "fc00::1", "100.64.0.1",
]) {
  test(`rejects ${address}`, () => rejects("https://shop.northbridge.test", policy(), resolveTo(address)));
}

test("a private address outside the demo network is rejected, loopback never is allowed", async () => {
  await rejects("https://shop.northbridge.test", policy({ allowedNetworks: ["172.28.0.0/16"] }), resolveTo("10.9.9.9"));
  await rejects("https://shop.northbridge.test", policy({ allowedNetworks: ["127.0.0.0/8"] }), resolveTo("127.0.0.1"));
});

test("one unsafe address among safe ones rejects the URL", () =>
  rejects("https://shop.northbridge.test", policy(), resolveTo("93.184.216.34", "169.254.169.254")));

for (const url of [
  "ftp://shop.northbridge.test/",
  "file:///etc/passwd",
  "https://evil.test/",
  "https://northbridge.test.evil.test/",
  "https://user:pw@shop.northbridge.test/",
  "https://shop.northbridge.test:8443/",
  "https://localhost/",
  "not a url",
  "",
  `https://${"a".repeat(3000)}.northbridge.test`,
]) {
  test(`rejects before resolving: ${url.slice(0, 40)}`, () =>
    rejects(url, policy(), async () => {
      throw new Error("must not resolve");
    }));
}

test("the apex is not matched by a wildcard and unresolvable hosts are rejected", async () => {
  await rejects("https://northbridge.test", { allowedHosts: ["*.northbridge.test"] }, resolveTo("93.184.216.34"));
  await rejects("https://shop.northbridge.test", policy(), async () => {
    throw new Error("nxdomain");
  });
  await rejects("https://shop.northbridge.test", policy(), resolveTo());
});
