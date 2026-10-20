/*! Onboarding form bundle - generated for the Northbridge demonstration estate */
(function (modules) {
  var cache = {};
  function __require(id) {
    if (cache[id]) return cache[id].exports;
    var module = (cache[id] = { exports: {} });
    modules[id](module, module.exports, __require);
    return module.exports;
  }
  __require("./src/index.js");
})({
  "./node_modules/react/index.js": function (module, exports) { /* react */ },
  "./node_modules/react-dom/index.js": function (module, exports) { /* react-dom */ },
  "./node_modules/axios/index.js": function (module, exports) { /* axios */ },
  "./node_modules/zod/index.js": function (module, exports) { /* zod */ },
  "./src/index.js": function (module, exports, __require) {
  var m0 = __require("./node_modules/react/index.js");
  var m1 = __require("./node_modules/react-dom/index.js");
  var m2 = __require("./node_modules/axios/index.js");
  var m3 = __require("./node_modules/zod/index.js");
  var ROUTES = [
    { path: "/onboarding", component: "page" },
    { path: "/onboarding/submit", component: "page" },
    { path: "/onboarding/thanks", component: "page" }
  ];
  var ENDPOINT_0 = "https://api.payrollhub.example/v2/employees";
  var ENDPOINT_1 = "https://api.verifycheck.example/v1/checks";
  function send_0(payload) { return fetch(ENDPOINT_0, { method: "POST", body: JSON.stringify(payload) }); }
  function send_1(payload) { return fetch(ENDPOINT_1, { method: "POST", body: JSON.stringify(payload) }); }

  }
});
