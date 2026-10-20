/*! Support widget SDK bundle - generated for the Northbridge demonstration estate */
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
  "./node_modules/vue/index.js": function (module, exports) { /* vue */ },
  "./node_modules/axios/index.js": function (module, exports) { /* axios */ },
  "./node_modules/@chatwoot/sdk/index.js": function (module, exports) { /* @chatwoot/sdk */ },
  "./src/index.js": function (module, exports, __require) {
  var vue = require("vue");
  var axios = require("axios");
  var sdk = require("@chatwoot/sdk");
  var ROUTES = [
    { path: "/", component: "page" },
    { path: "/api/v1/widget/conversations", component: "page" },
    { path: "/api/v1/widget/messages", component: "page" }
  ];
  var ENDPOINT_0 = "https://api.chatrelay.example/v1/translate";
  var ENDPOINT_1 = "https://api.mailsend.example/v3/send";
  function send_0(payload) { return fetch(ENDPOINT_0, { method: "POST", body: JSON.stringify(payload) }); }
  function send_1(payload) { return fetch(ENDPOINT_1, { method: "POST", body: JSON.stringify(payload) }); }

  }
});
