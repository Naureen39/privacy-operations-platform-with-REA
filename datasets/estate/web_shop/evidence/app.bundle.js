/*! Northbridge Shop storefront bundle - generated for the Northbridge demonstration estate */
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
  "./node_modules/@stripe/stripe-js/index.js": function (module, exports) { /* @stripe/stripe-js */ },
  "./node_modules/axios/index.js": function (module, exports) { /* axios */ },
  "./node_modules/core-js/index.js": function (module, exports) { /* core-js */ },
  "./src/index.js": function (module, exports, __require) {
  var react = require("react");
  var react_dom = require("react-dom");
  var stripe_js = require("@stripe/stripe-js");
  var axios = require("axios");
  var core_js = require("core-js");
  var ROUTES = [
    { path: "/", component: "page" },
    { path: "/shop/", component: "page" },
    { path: "/cart/", component: "page" },
    { path: "/checkout/", component: "page" },
    { path: "/my-account/", component: "page" }
  ];
  var ENDPOINT_0 = "https://api.swiftparcel.example/v2/shipments";
  var ENDPOINT_1 = "https://api.stripe.com/v1/payment_methods";
  var ENDPOINT_2 = "https://www.facebook.com/tr/";
  var ENDPOINT_3 = "https://analytics.northbridge.example/matomo.php";
  function send_0(payload) { return fetch(ENDPOINT_0, { method: "POST", body: JSON.stringify(payload) }); }
  function send_1(payload) { return fetch(ENDPOINT_1, { method: "POST", body: JSON.stringify(payload) }); }
  function send_2(payload) { return fetch(ENDPOINT_2, { method: "POST", body: JSON.stringify(payload) }); }
  function send_3(payload) { return fetch(ENDPOINT_3, { method: "POST", body: JSON.stringify(payload) }); }
  fbq('init', '1100110011');
  Stripe('pk_test_northbridge_demo');
  }
});
