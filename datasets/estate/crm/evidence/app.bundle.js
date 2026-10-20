/*! SuiteCRM web-to-lead bundle - generated for the Northbridge demonstration estate */
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
  "./node_modules/jquery/index.js": function (module, exports) { /* jquery */ },
  "./node_modules/axios/index.js": function (module, exports) { /* axios */ },
  "./src/index.js": function (module, exports, __require) {
  var m0 = __require("./node_modules/jquery/index.js");
  var m1 = __require("./node_modules/axios/index.js");
  var ROUTES = [
    { path: "/index.php", component: "page" },
    { path: "/index.php?entryPoint=WebToLeadCapture", component: "page" }
  ];
  var ENDPOINT_0 = "https://enrich.leadscope.example/v1/person";
  var ENDPOINT_1 = "https://api.mailsend.example/v3/send";
  function send_0(payload) { return fetch(ENDPOINT_0, { method: "POST", body: JSON.stringify(payload) }); }
  function send_1(payload) { return fetch(ENDPOINT_1, { method: "POST", body: JSON.stringify(payload) }); }

  }
});
