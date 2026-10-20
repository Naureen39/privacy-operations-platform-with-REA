/*! Matomo tracker (matomo.js) - generated for the Northbridge demonstration estate */
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
  "./node_modules/matomo-tracker/index.js": function (module, exports) { /* matomo-tracker */ },
  "./src/index.js": function (module, exports, __require) {
  var m0 = __require("./node_modules/matomo-tracker/index.js");
  var ROUTES = [
    { path: "/matomo.php", component: "page" },
    { path: "/index.php", component: "page" }
  ];
  var ENDPOINT_0 = "https://analytics.northbridge.example/matomo.php";
  var ENDPOINT_1 = "https://dashboards.brightlens.example/embed/northbridge";
  function send_0(payload) { return fetch(ENDPOINT_0, { method: "POST", body: JSON.stringify(payload) }); }
  function send_1(payload) { return fetch(ENDPOINT_1, { method: "POST", body: JSON.stringify(payload) }); }
  _paq.push(['setSiteId', 1]);
  _paq.push(['setUserId', userEmail]);
  }
});
