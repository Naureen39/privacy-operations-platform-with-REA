/*! Clinic booking bundle - generated for the Northbridge demonstration estate */
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
  "./node_modules/@bookwell/widget/index.js": function (module, exports) { /* @bookwell/widget */ },
  "./node_modules/axios/index.js": function (module, exports) { /* axios */ },
  "./src/index.js": function (module, exports, __require) {
  var m0 = __require("./node_modules/react/index.js");
  var m1 = __require("./node_modules/react-dom/index.js");
  var m2 = __require("./node_modules/@bookwell/widget/index.js");
  var m3 = __require("./node_modules/axios/index.js");
  var ROUTES = [
    { path: "/", component: "page" },
    { path: "/appointments", component: "page" },
    { path: "/my-appointments", component: "page" }
  ];
  var ENDPOINT_0 = "https://cal.bookwell.example/api/slots/reserve";
  var ENDPOINT_1 = "https://api.smsgate.example/v1/messages";
  function send_0(payload) { return fetch(ENDPOINT_0, { method: "POST", body: JSON.stringify(payload) }); }
  function send_1(payload) { return fetch(ENDPOINT_1, { method: "POST", body: JSON.stringify(payload) }); }
  BookWell.init({ clinic: 'northbridge-health' });
  }
});
