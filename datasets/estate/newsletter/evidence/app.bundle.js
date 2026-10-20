/*! Newsletter subscribe bundle - generated for the Northbridge demonstration estate */
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
  "./node_modules/axios/index.js": function (module, exports) { /* axios */ },
  "./src/index.js": function (module, exports, __require) {
  var axios = require("axios");
  var ROUTES = [
    { path: "/", component: "page" },
    { path: "/subscribe", component: "page" },
    { path: "/unsubscribe", component: "page" }
  ];
  var ENDPOINT_0 = "https://api.mailsend.example/v3/contacts";
  var ENDPOINT_1 = "https://track.openpulse.example/p.gif";
  function send_0(payload) { return fetch(ENDPOINT_0, { method: "POST", body: JSON.stringify(payload) }); }
  function send_1(payload) { return fetch(ENDPOINT_1, { method: "POST", body: JSON.stringify(payload) }); }

  }
});
