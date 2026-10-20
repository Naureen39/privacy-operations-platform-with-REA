"""Specification of the reference estate "Northbridge Group".

Everything in the estate (web pages, network captures, database snapshots, bundles, privacy
notices, questionnaires and ground truth) is generated from the data in this module, so the
ground truth matches the generated content by construction. Contradictions are seeded
deliberately and listed in CONTRADICTIONS; tests check that each one is really present in the
generated files and that nothing else deviates.

Column and field `src` values use the vocabulary documented in generators.py.
"""

from typing import Any

SystemSpec = dict[str, Any]


def col(
    name: str, sql_type: str, src: str, el: str | None = None, id_for: str | None = None
) -> dict[str, Any]:
    entry: dict[str, Any] = {"n": name, "t": sql_type, "src": src}
    if el:
        entry["el"] = el
    if id_for:
        entry["id_for"] = id_for
    return entry


def fld(
    name: str,
    src: str,
    el: str | None = None,
    *,
    type: str = "text",  # noqa: A002
    label: str | None = None,
    autocomplete: str | None = None,
    required: bool = False,
    checked: bool = False,
) -> dict[str, Any]:
    return {
        "name": name, "src": src, "el": el, "type": type, "label": label or name.replace("_", " ").title(),
        "autocomplete": autocomplete, "required": required, "checked": checked,
    }  # fmt: skip


def element(
    category: str,
    label: str,
    policy: bool = True,
    questionnaire: bool = True,
    special: bool = False,
) -> dict[str, Any]:
    return {
        "category": category,
        "label": label,
        "policy": policy,
        "questionnaire": questionnaire,
        "special": special,
    }


def recipient(
    rid: str,
    hosts: list[str],
    vendor: str,
    role: str,
    country: str,
    purpose: str,
    shares: list[str],
    *,
    policy: bool = True,
    questionnaire: bool = True,
    internal: bool = False,
    agreement_required: bool = True,
    agreement: bool = True,
    basis: str = "adequacy",
) -> dict[str, Any]:
    return {
        "id": rid, "hosts": hosts, "vendor": vendor, "role": role, "country": country, "purpose": purpose,
        "shares": shares, "declared_policy": policy, "declared_questionnaire": questionnaire,
        "internal": internal, "agreement_required": agreement_required, "agreement_on_file": agreement,
        "transfer_basis": basis,
    }  # fmt: skip


def beacon(
    bid: str,
    rcpt: str,
    host: str,
    method: str,
    path: str,
    *,
    query: dict[str, str] | None = None,
    body: dict[str, str] | None = None,
    body_type: str = "none",
    when: str = "submit",
    response: str = '{"status":"ok"}',
    elements: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "id": bid, "recipient": rcpt, "host": host, "method": method, "path": path, "query": query or {},
        "body": body or {}, "body_type": body_type, "when": when, "response": response,
        "elements": elements or {},
    }  # fmt: skip


# ---------------------------------------------------------------------------------------------
# 1. Web shop (WordPress with WooCommerce, modeled)
# ---------------------------------------------------------------------------------------------
WEB_SHOP: SystemSpec = {
    "id": "web_shop",
    "name": "Web shop",
    "stack": "WordPress with WooCommerce (modeled on the product's default checkout)",
    "modeled": True,
    "host": "shop.northbridge.example",
    "owner": "Priya Nair, Head of E-commerce",
    "population": "in_web_shop",
    "description": "Online store selling clothing and home goods to consumers in five countries.",
    "last_review_date": "2026-03-12",
    "elements": {
        "customer_name": element("name", "your name"),
        "customer_email": element("contact_email", "your e-mail address"),
        "customer_phone": element("contact_phone", "your telephone number"),
        "delivery_address": element("postal_address", "your delivery and billing address"),
        "date_of_birth": element(
            "date_of_birth", "your date of birth", policy=False, questionnaire=False
        ),
        "payment_card": element(
            "payment_card", "your payment card details (entered directly with our payment provider)"
        ),
        "order_history": element("purchase_history", "the items you order and the order total"),
        "ip_address": element("ip_address", "your IP address"),
        "account_password": element(
            "authentication_credentials", "your account password (stored only as a hash)"
        ),
        "marketing_consent": element("consent_record", "your marketing preferences"),
        "session_id": element("online_identifier", "a shopping session cookie"),
    },
    "tables": [
        {
            "name": "customers",
            "per_person": (1, 1),
            "columns": [
                col("customer_id", "INTEGER", "auto"),
                col("customer_email", "TEXT", "person.email", "customer_email", "email"),
                col("first_name", "TEXT", "person.first_name", "customer_name"),
                col("last_name", "TEXT", "person.last_name", "customer_name"),
                col("phone", "TEXT", "person.phone", "customer_phone"),
                col("address_1", "TEXT", "person.street_address", "delivery_address"),
                col("city", "TEXT", "person.city", "delivery_address"),
                col("postcode", "TEXT", "person.postal_code", "delivery_address"),
                col("country", "TEXT", "person.country", "delivery_address"),
                col("birthdate", "TEXT", "person.date_of_birth", "date_of_birth"),
                col("password_hash", "TEXT", "gen.password_hash", "account_password"),
                col("marketing_optin", "INTEGER", "gen.zero", "marketing_consent"),
                col("created_at", "TEXT", "gen.recent_ts"),
            ],
        },
        {
            "name": "orders",
            "per_person": (1, 3),
            "columns": [
                col("order_id", "INTEGER", "auto"),
                col("customer_email", "TEXT", "person.email", "customer_email", "email"),
                col("order_total", "REAL", "gen.order_total", "order_history"),
                col("currency", "TEXT", "gen.currency"),
                col("status", "TEXT", "gen.order_status"),
                col("customer_ip", "TEXT", "person.ip_address", "ip_address"),
                col("created_at", "TEXT", "gen.recent_ts"),
            ],
        },
    ],
    "pages": [
        {
            "path": "/checkout/",
            "title": "Checkout - Northbridge Shop",
            "heading": "Checkout",
            "intro": "Enter your details to complete the order.",
            "scripts": [
                "https://shop.northbridge.example/wp-content/themes/northbridge/assets/app.js",
                "https://js.stripe.com/v3/",
                "https://connect.facebook.net/en_US/fbevents.js",
                "https://analytics.northbridge.example/matomo.js",
            ],
            "styles": ["https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap"],
            "images": [],
            "iframes": [],
            "cookies": [
                {
                    "name": "wp_woocommerce_session",
                    "el": "session_id",
                    "http_only": True,
                    "max_age": 172800,
                }
            ],
        }
    ],
    "endpoints": [
        {
            "id": "checkout",
            "path": "/?wc-ajax=checkout",
            "method": "POST",
            "enctype": "form",
            "page": "/checkout/",
            "submit_label": "Place order",
            "fields": [
                fld(
                    "billing_first_name",
                    "person.first_name",
                    "customer_name",
                    label="First name",
                    autocomplete="given-name",
                    required=True,
                ),
                fld(
                    "billing_last_name",
                    "person.last_name",
                    "customer_name",
                    label="Last name",
                    autocomplete="family-name",
                    required=True,
                ),
                fld(
                    "billing_email",
                    "person.email",
                    "customer_email",
                    type="email",
                    label="Email address",
                    autocomplete="email",
                    required=True,
                ),
                fld(
                    "billing_phone",
                    "person.phone",
                    "customer_phone",
                    type="tel",
                    label="Phone",
                    autocomplete="tel",
                ),
                fld(
                    "billing_address_1",
                    "person.street_address",
                    "delivery_address",
                    label="Street address",
                    autocomplete="address-line1",
                    required=True,
                ),
                fld(
                    "billing_city",
                    "person.city",
                    "delivery_address",
                    label="Town / City",
                    autocomplete="address-level2",
                    required=True,
                ),
                fld(
                    "billing_postcode",
                    "person.postal_code",
                    "delivery_address",
                    label="Postcode",
                    autocomplete="postal-code",
                    required=True,
                ),
                fld(
                    "billing_country",
                    "person.country",
                    "delivery_address",
                    label="Country",
                    autocomplete="country",
                    required=True,
                ),
                fld(
                    "billing_birthdate",
                    "person.date_of_birth",
                    "date_of_birth",
                    type="date",
                    label="Date of birth",
                    autocomplete="bday",
                ),
                fld(
                    "account_password",
                    "gen.sample_password",
                    "account_password",
                    type="password",
                    label="Create account password",
                    autocomplete="new-password",
                ),
                fld(
                    "marketing_optin",
                    "gen.zero",
                    "marketing_consent",
                    type="checkbox",
                    label="Send me news and offers",
                ),
            ],
            "writes": [
                {
                    "table": "customers",
                    "map": {
                        "customer_email": "field:billing_email",
                        "first_name": "field:billing_first_name",
                        "last_name": "field:billing_last_name",
                        "phone": "field:billing_phone",
                        "address_1": "field:billing_address_1",
                        "city": "field:billing_city",
                        "postcode": "field:billing_postcode",
                        "country": "field:billing_country",
                        "birthdate": "field:billing_birthdate",
                        "password_hash": "gen:password_hash",
                        "marketing_optin": "field:marketing_optin",
                        "created_at": "now",
                    },
                },
                {
                    "table": "orders",
                    "map": {
                        "customer_email": "field:billing_email",
                        "order_total": "gen:order_total",
                        "currency": "const:EUR",
                        "status": "const:processing",
                        "customer_ip": "ip",
                        "created_at": "now",
                    },
                },
            ],
            "response": {
                "result": "success",
                "order_id": "$last_id",
                "redirect": "https://shop.northbridge.example/checkout/order-received/",
            },
        }
    ],
    "recipients": [
        recipient(
            "stripe",
            ["js.stripe.com", "api.stripe.com"],
            "Stripe",
            "processor",
            "US",
            "Payment processing",
            ["payment_card", "customer_name", "customer_email"],
            basis="scc",
        ),
        recipient(
            "meta",
            ["www.facebook.com", "connect.facebook.net"],
            "Meta Platforms",
            "joint_controller",
            "US",
            "Advertising measurement",
            ["customer_email", "customer_phone", "order_history"],
            policy=False,
            questionnaire=False,
            agreement_required=False,
            agreement=False,
            basis="none",
        ),
        recipient(
            "swiftparcel",
            ["api.swiftparcel.example"],
            "SwiftParcel Logistics",
            "controller",
            "GB",
            "Parcel delivery",
            ["customer_name", "delivery_address", "customer_phone", "customer_email"],
            agreement_required=False,
        ),
        recipient(
            "google_fonts",
            ["fonts.googleapis.com"],
            "Google Fonts",
            "processor",
            "US",
            "Web font delivery",
            ["ip_address"],
            basis="scc",
        ),
        recipient(
            "matomo_internal",
            ["analytics.northbridge.example"],
            "Northbridge web analytics",
            "controller",
            "IE",
            "Site analytics (our own system)",
            ["customer_email", "ip_address", "session_id"],
            internal=True,
            agreement_required=False,
        ),
    ],
    "beacons": [
        beacon(
            "stripe_payment_method",
            "stripe",
            "api.stripe.com",
            "POST",
            "/v1/payment_methods",
            body_type="form",
            body={
                "type": "const.card",
                "card[number]": "const.4242424242424242",
                "card[exp_month]": "const.12",
                "card[exp_year]": "const.2030",
                "card[cvc]": "const.123",
                "billing_details[name]": "person.full_name",
                "billing_details[email]": "person.email",
            },
            response='{"id":"pm_1Nxyz","object":"payment_method","type":"card"}',
            elements={
                "card[number]": "payment_card",
                "card[exp_month]": "payment_card",
                "card[cvc]": "payment_card",
            },
        ),
        beacon(
            "meta_pixel",
            "meta",
            "www.facebook.com",
            "GET",
            "/tr/",
            body_type="none",
            query={
                "id": "const.1100110011",
                "ev": "const.Purchase",
                "ud[em]": "gen.tracking_hash",
                "ud[ph]": "gen.phone_hash",
                "cd[value]": "gen.order_total",
                "cd[currency]": "const.EUR",
            },
            response="GIF89a",
            elements={
                "ud[em]": "customer_email",
                "ud[ph]": "customer_phone",
                "cd[value]": "order_history",
            },
        ),
        beacon(
            "matomo_hit",
            "matomo_internal",
            "analytics.northbridge.example",
            "GET",
            "/matomo.php",
            body_type="none",
            query={
                "idsite": "const.1",
                "rec": "const.1",
                "action_name": "const.Checkout",
                "_id": "gen.visitor_id",
                "uid": "person.email",
                "url": "const.https://shop.northbridge.example/checkout/",
            },
            response="GIF89a",
        ),
    ],
    "js": {
        "kind": "web",
        "title": "Northbridge Shop storefront bundle",
        "modules": ["react", "react-dom", "@stripe/stripe-js", "axios", "core-js"],
        "routes": ["/", "/shop/", "/cart/", "/checkout/", "/my-account/"],
        "endpoints": [
            "https://api.swiftparcel.example/v2/shipments",
            "https://api.stripe.com/v1/payment_methods",
            "https://www.facebook.com/tr/",
            "https://analytics.northbridge.example/matomo.php",
        ],
        "ipc": [],
        "init": ["fbq('init', '1100110011');", "Stripe('pk_test_northbridge_demo');"],
    },
    "policy": {
        "purposes": [
            "Processing and delivering your orders",
            "Managing your customer account",
            "Preventing fraud",
        ],
        "lawful_basis": "contract",
        "sharing_statement": "We do not share your personal data with any third party other than our payment provider and our delivery carrier, who process it only to complete your order.",
        "retention_statement": "We keep order records for seven years because tax law requires it. Account data is kept until you ask us to delete the account.",
        "transfer_statement": "Payments are processed by Stripe in the United States under standard contractual clauses.",
        "extra_claims": [],
    },
    "questionnaire": {
        "purposes": ["Order fulfilment", "Customer accounts", "Fraud prevention"],
        "data_subjects": ["customers"],
        "lawful_basis": "contract",
        "special_category_condition": None,
        "retention": "7 years for orders (tax law); accounts until deletion request",
        "security_measures": [
            "TLS everywhere",
            "Passwords hashed with bcrypt",
            "Role based admin access",
        ],
        "last_review_date": "2026-03-12",
        "notes": "Marketing pixel was added by the agency in spring; not yet reviewed.",
    },
    "dpia": {"criteria": ["large_scale"], "required": False},
}

# ---------------------------------------------------------------------------------------------
# 2. Web analytics (Matomo, modeled)
# ---------------------------------------------------------------------------------------------
WEB_ANALYTICS: SystemSpec = {
    "id": "web_analytics",
    "name": "Web analytics",
    "stack": "Matomo, self hosted (modeled on the product's tracking API and schema)",
    "modeled": True,
    "host": "analytics.northbridge.example",
    "owner": "Daniel Okoye, Digital Marketing Manager",
    "population": "in_web_analytics",
    "description": "Self hosted analytics for the shop, the newsletter site and the blog.",
    "last_review_date": "2026-02-20",
    "elements": {
        "visitor_id": element(
            "online_identifier", "a random visitor identifier stored in a cookie"
        ),
        "ip_address": element("ip_address", "your IP address, shortened before it is stored"),
        "user_agent": element("device_identifier", "your browser and operating system"),
        "page_url": element("browsing_behavior", "the pages you view"),
        "referrer": element("browsing_behavior", "the page that referred you to us"),
        "location_city": element("geolocation", "your approximate location (country level)"),
        "user_email": element(
            "contact_email", "an account identifier", policy=False, questionnaire=False
        ),
    },
    "tables": [
        {
            "name": "visits",
            "per_person": (1, 4),
            "columns": [
                col("idvisit", "INTEGER", "auto"),
                col("idvisitor", "TEXT", "gen.visitor_id", "visitor_id"),
                col("user_id", "TEXT", "person.email_if:in_web_shop", "user_email", "email"),
                col("location_ip", "TEXT", "person.ip_address", "ip_address"),
                col("location_city", "TEXT", "person.city", "location_city"),
                col("config_os", "TEXT", "gen.os", "user_agent"),
                col("config_browser", "TEXT", "gen.browser", "user_agent"),
                col("referer_url", "TEXT", "gen.referrer", "referrer"),
                col("page_url", "TEXT", "gen.page", "page_url"),
                col("visit_total_actions", "INTEGER", "gen.actions"),
                col("visit_first_action_time", "TEXT", "gen.recent_ts"),
            ],
        }
    ],
    "pages": [
        {
            "path": "/",
            "title": "Web analytics - opt out",
            "heading": "Analytics privacy",
            "intro": "You can opt out of analytics tracking on this page.",
            "scripts": ["https://analytics.northbridge.example/matomo.js"],
            "styles": [],
            "images": [],
            "iframes": ["https://dashboards.brightlens.example/embed/northbridge?site=1"],
            "cookies": [
                {"name": "_pk_id", "el": "visitor_id", "http_only": False, "max_age": 33955200}
            ],
        }
    ],
    "endpoints": [
        {
            "id": "tracker",
            "path": "/matomo.php",
            "method": "GET",
            "enctype": "query",
            "page": None,
            "fields": [
                fld("idsite", "const.1"),
                fld("rec", "const.1"),
                fld("_id", "gen.visitor_id", "visitor_id"),
                fld("uid", "person.email_if:in_web_shop", "user_email"),
                fld("urlref", "gen.referrer", "referrer"),
                fld("url", "gen.page", "page_url"),
            ],
            "writes": [
                {
                    "table": "visits",
                    "map": {
                        "idvisitor": "field:_id",
                        "user_id": "field:uid",
                        "location_ip": "ip",
                        "location_city": "person:city",
                        "config_os": "gen:os",
                        "config_browser": "gen:browser",
                        "referer_url": "field:urlref",
                        "page_url": "field:url",
                        "visit_total_actions": "const:1",
                        "visit_first_action_time": "now",
                    },
                }
            ],
            "response": {},
        }
    ],
    "recipients": [
        recipient(
            "brightlens",
            ["dashboards.brightlens.example"],
            "BrightLens Agency",
            "processor",
            "GB",
            "Marketing reporting dashboards",
            ["visitor_id", "ip_address", "page_url"],
            agreement=False,
        ),
    ],
    "beacons": [
        beacon(
            "brightlens_embed",
            "brightlens",
            "dashboards.brightlens.example",
            "GET",
            "/embed/northbridge",
            body_type="none",
            when="load",
            query={
                "site": "const.1",
                "visitor": "gen.visitor_id",
                "ip": "person.ip_address",
                "url": "gen.page",
            },
            response="<html></html>",
            elements={"visitor": "visitor_id", "ip": "ip_address", "url": "page_url"},
        ),
    ],
    "js": {
        "kind": "web",
        "title": "Matomo tracker (matomo.js)",
        "modules": ["matomo-tracker"],
        "routes": ["/matomo.php", "/index.php"],
        "endpoints": [
            "https://analytics.northbridge.example/matomo.php",
            "https://dashboards.brightlens.example/embed/northbridge",
        ],
        "ipc": [],
        "init": ["_paq.push(['setSiteId', 1]);", "_paq.push(['setUserId', userEmail]);"],
    },
    "policy": {
        "purposes": ["Understanding how the site is used", "Improving page performance"],
        "lawful_basis": "legitimate_interests",
        "sharing_statement": "Analytics data is processed on our own servers. Aggregated reports are shown to our reporting agency BrightLens, which acts as our service provider.",
        "retention_statement": "Visit records are kept for 25 months.",
        "transfer_statement": "Analytics data stays in the European Economic Area. Our reporting agency is based in the United Kingdom.",
        "extra_claims": [
            "We anonymise your IP address by removing the last two bytes before anything is stored, so we never store a full IP address."
        ],
    },
    "questionnaire": {
        "purposes": ["Site analytics", "Marketing reporting"],
        "data_subjects": ["website visitors"],
        "lawful_basis": "legitimate_interests",
        "special_category_condition": None,
        "retention": "25 months",
        "security_measures": ["Hosted in our EU data centre", "Access limited to marketing team"],
        "last_review_date": "2026-02-20",
        "notes": "BrightLens receives dashboards only. Agreement being renegotiated.",
    },
    "dpia": {"criteria": ["systematic_monitoring", "large_scale"], "required": True},
}

# ---------------------------------------------------------------------------------------------
# 3. Helpdesk and chat widget (Chatwoot, modeled)
# ---------------------------------------------------------------------------------------------
HELPDESK: SystemSpec = {
    "id": "helpdesk",
    "name": "Helpdesk and chat widget",
    "stack": "Chatwoot (modeled on the product's website widget and schema)",
    "modeled": True,
    "host": "support.northbridge.example",
    "owner": "Imogen Clarke, Customer Care Lead",
    "population": "in_helpdesk",
    "description": "Customer support tickets and live chat for the shop.",
    "last_review_date": "2026-04-02",
    "elements": {
        "contact_name": element("name", "your name"),
        "contact_email": element("contact_email", "your e-mail address"),
        "contact_phone": element("contact_phone", "your telephone number"),
        "message_content": element("communications_content", "the messages you send us"),
        "ticket_subject": element("communications_content", "the subject of your request"),
        "ip_address": element("ip_address", "your IP address"),
        "browser_info": element("device_identifier", "your browser and device type"),
    },
    "tables": [
        {
            "name": "contacts",
            "per_person": (1, 1),
            "columns": [
                col("id", "INTEGER", "auto"),
                col("name", "TEXT", "person.full_name", "contact_name"),
                col("email", "TEXT", "person.email", "contact_email", "email"),
                col("phone_number", "TEXT", "person.phone", "contact_phone"),
                col("last_ip", "TEXT", "person.ip_address", "ip_address"),
                col("created_at", "TEXT", "gen.old_ts"),
            ],
        },
        {
            "name": "conversations",
            "per_person": (1, 3),
            "columns": [
                col("id", "INTEGER", "auto"),
                col("contact_email", "TEXT", "person.email", "contact_email", "email"),
                col("subject", "TEXT", "gen.ticket_subject", "ticket_subject"),
                col("status", "TEXT", "gen.ticket_status"),
                col("browser", "TEXT", "gen.browser", "browser_info"),
                col("created_at", "TEXT", "gen.old_ts"),
            ],
        },
        {
            "name": "messages",
            "per_person": (2, 6),
            "columns": [
                col("id", "INTEGER", "auto"),
                col("sender_email", "TEXT", "person.email", "contact_email", "email"),
                col("content", "TEXT", "gen.chat_line", "message_content"),
                col("created_at", "TEXT", "gen.old_ts"),
            ],
        },
    ],
    "pages": [
        {
            "path": "/",
            "title": "Northbridge Support",
            "heading": "How can we help?",
            "intro": "Start a chat or send us a message.",
            "scripts": ["https://support.northbridge.example/packs/js/sdk.js"],
            "styles": [],
            "images": [],
            "iframes": [],
            "cookies": [
                {"name": "cw_conversation", "el": None, "http_only": False, "max_age": 86400}
            ],
        }
    ],
    "endpoints": [
        {
            "id": "widget_conversation",
            "path": "/api/v1/widget/conversations",
            "method": "POST",
            "enctype": "json",
            "page": "/",
            "submit_label": "Send",
            "fields": [
                fld(
                    "contact.name",
                    "person.full_name",
                    "contact_name",
                    label="Your name",
                    autocomplete="name",
                    required=True,
                ),
                fld(
                    "contact.email",
                    "person.email",
                    "contact_email",
                    type="email",
                    label="Email",
                    autocomplete="email",
                    required=True,
                ),
                fld(
                    "contact.phone_number",
                    "person.phone",
                    "contact_phone",
                    type="tel",
                    label="Phone (optional)",
                    autocomplete="tel",
                ),
                fld("message.subject", "gen.ticket_subject", "ticket_subject", label="Subject"),
                fld(
                    "message.content",
                    "gen.chat_line",
                    "message_content",
                    type="textarea",
                    label="Message",
                    required=True,
                ),
            ],
            "writes": [
                {
                    "table": "contacts",
                    "map": {
                        "name": "field:contact.name",
                        "email": "field:contact.email",
                        "phone_number": "field:contact.phone_number",
                        "last_ip": "ip",
                        "created_at": "now",
                    },
                },
                {
                    "table": "conversations",
                    "map": {
                        "contact_email": "field:contact.email",
                        "subject": "field:message.subject",
                        "status": "const:open",
                        "browser": "gen:browser",
                        "created_at": "now",
                    },
                },
                {
                    "table": "messages",
                    "map": {
                        "sender_email": "field:contact.email",
                        "content": "field:message.content",
                        "created_at": "now",
                    },
                },
            ],
            "response": {
                "id": "$last_id",
                "status": "open",
                "contact": {"email": "$field:contact.email"},
            },
        }
    ],
    "recipients": [
        recipient(
            "chatrelay",
            ["api.chatrelay.example"],
            "ChatRelay",
            "processor",
            "DE",
            "Message translation",
            ["message_content"],
        ),
        recipient(
            "mailsend_help",
            ["api.mailsend.example"],
            "MailSend Europe",
            "processor",
            "IE",
            "Ticket notification e-mails",
            ["contact_name", "contact_email", "ticket_subject"],
        ),
    ],
    "beacons": [
        beacon(
            "chatrelay_translate",
            "chatrelay",
            "api.chatrelay.example",
            "POST",
            "/v1/translate",
            body_type="json",
            body={"text": "gen.chat_line", "source_lang": "const.auto", "target_lang": "const.en"},
            response='{"translation":"ok"}',
        ),
    ],
    "js": {
        "kind": "web",
        "title": "Support widget SDK bundle",
        "modules": ["vue", "axios", "@chatwoot/sdk"],
        "routes": ["/", "/api/v1/widget/conversations", "/api/v1/widget/messages"],
        "endpoints": [
            "https://api.chatrelay.example/v1/translate",
            "https://api.mailsend.example/v3/send",
        ],
        "ipc": [],
        "init": [],
    },
    "policy": {
        "purposes": ["Answering your support requests", "Improving our customer service"],
        "lawful_basis": "legitimate_interests",
        "sharing_statement": "We use ChatRelay to translate messages and MailSend Europe to send notification e-mails. Both act only on our instructions.",
        "retention_statement": "Support conversations are deleted twelve months after they are closed.",
        "transfer_statement": "All support data is processed inside the European Economic Area.",
        "extra_claims": ["Chat transcripts are not stored after the conversation ends."],
    },
    "questionnaire": {
        "purposes": ["Customer support"],
        "data_subjects": ["customers", "prospects"],
        "lawful_basis": "legitimate_interests",
        "special_category_condition": None,
        "retention": "12 months after the ticket is closed",
        "security_measures": ["Encrypted database", "SSO for agents"],
        "last_review_date": "2026-04-02",
        "notes": "A clean-up job was planned but has not been built.",
    },
    "dpia": {"criteria": [], "required": False},
}

# ---------------------------------------------------------------------------------------------
# 4. CRM (SuiteCRM, modeled)
# ---------------------------------------------------------------------------------------------
CRM: SystemSpec = {
    "id": "crm",
    "name": "CRM",
    "stack": "SuiteCRM (modeled on the product's web-to-lead form and schema)",
    "modeled": True,
    "host": "crm.northbridge.example",
    "owner": "Marcus Weber, Head of Sales",
    "population": "in_crm",
    "description": "Business customers, leads and sales opportunities.",
    "last_review_date": "2026-05-18",
    "elements": {
        "lead_name": element("name", "your name"),
        "lead_email": element("contact_email", "your business e-mail address"),
        "lead_phone": element("contact_phone", "your business telephone number"),
        "company": element("employment_data", "your employer"),
        "job_title": element("employment_data", "your job title"),
        "lead_source": element("preferences", "how you found us"),
        "notes": element("communications_content", "notes our sales team records about you"),
        "enriched_profile": element(
            "employment_data", "seniority and company size added from business data sources"
        ),
    },
    "tables": [
        {
            "name": "leads",
            "per_person": (1, 1),
            "columns": [
                col("id", "INTEGER", "auto"),
                col("first_name", "TEXT", "person.first_name", "lead_name"),
                col("last_name", "TEXT", "person.last_name", "lead_name"),
                col("email1", "TEXT", "person.email", "lead_email", "email"),
                col("phone_work", "TEXT", "person.phone", "lead_phone"),
                col("account_name", "TEXT", "gen.company", "company"),
                col("title", "TEXT", "gen.job_title", "job_title"),
                col("lead_source", "TEXT", "gen.lead_source", "lead_source"),
                col("description", "TEXT", "gen.crm_note", "notes"),
                col("enriched_seniority", "TEXT", "gen.seniority", "enriched_profile"),
                col("enriched_company_size", "TEXT", "gen.company_size", "enriched_profile"),
                col("date_entered", "TEXT", "gen.recent_ts"),
            ],
        },
        {
            "name": "opportunities",
            "per_person": (0, 2),
            "columns": [
                col("id", "INTEGER", "auto"),
                col("lead_email", "TEXT", "person.email", "lead_email", "email"),
                col("amount", "REAL", "gen.amount"),
                col("sales_stage", "TEXT", "gen.stage"),
                col("date_entered", "TEXT", "gen.recent_ts"),
            ],
        },
    ],
    "pages": [
        {
            "path": "/index.php",
            "title": "Request a quote - Northbridge Business",
            "heading": "Request a quote",
            "intro": "Tell us about your business and we will get back to you.",
            "scripts": ["https://crm.northbridge.example/include/javascript/webtolead.js"],
            "styles": [],
            "images": [],
            "iframes": [],
            "cookies": [{"name": "PHPSESSID", "el": None, "http_only": True, "max_age": 3600}],
        }
    ],
    "endpoints": [
        {
            "id": "web_to_lead",
            "path": "/index.php?entryPoint=WebToLeadCapture",
            "method": "POST",
            "enctype": "form",
            "page": "/index.php",
            "submit_label": "Submit",
            "fields": [
                fld(
                    "first_name",
                    "person.first_name",
                    "lead_name",
                    label="First name",
                    autocomplete="given-name",
                    required=True,
                ),
                fld(
                    "last_name",
                    "person.last_name",
                    "lead_name",
                    label="Last name",
                    autocomplete="family-name",
                    required=True,
                ),
                fld(
                    "email1",
                    "person.email",
                    "lead_email",
                    type="email",
                    label="Work email",
                    autocomplete="email",
                    required=True,
                ),
                fld(
                    "phone_work",
                    "person.phone",
                    "lead_phone",
                    type="tel",
                    label="Work phone",
                    autocomplete="tel",
                ),
                fld(
                    "account_name",
                    "gen.company",
                    "company",
                    label="Company",
                    autocomplete="organization",
                ),
                fld(
                    "title",
                    "gen.job_title",
                    "job_title",
                    label="Job title",
                    autocomplete="organization-title",
                ),
                fld(
                    "lead_source",
                    "gen.lead_source",
                    "lead_source",
                    type="hidden",
                    label="Lead source",
                ),
                fld(
                    "description",
                    "gen.crm_note",
                    "notes",
                    type="textarea",
                    label="How can we help?",
                ),
            ],
            "writes": [
                {
                    "table": "leads",
                    "map": {
                        "first_name": "field:first_name",
                        "last_name": "field:last_name",
                        "email1": "field:email1",
                        "phone_work": "field:phone_work",
                        "account_name": "field:account_name",
                        "title": "field:title",
                        "lead_source": "field:lead_source",
                        "description": "field:description",
                        "enriched_seniority": "gen:seniority",
                        "enriched_company_size": "gen:company_size",
                        "date_entered": "now",
                    },
                }
            ],
            "response": {"result": "lead created", "id": "$last_id"},
        }
    ],
    "recipients": [
        recipient(
            "leadscope",
            ["enrich.leadscope.example"],
            "LeadScope Data",
            "processor",
            "IN",
            "Lead enrichment",
            ["lead_name", "lead_email", "company"],
            basis="none",
        ),
        recipient(
            "mailsend_crm",
            ["api.mailsend.example"],
            "MailSend Europe",
            "processor",
            "IE",
            "Quote confirmation e-mails",
            ["lead_name", "lead_email"],
        ),
    ],
    "beacons": [
        beacon(
            "leadscope_enrich",
            "leadscope",
            "enrich.leadscope.example",
            "POST",
            "/v1/person",
            body_type="json",
            body={
                "email": "person.email",
                "first_name": "person.first_name",
                "last_name": "person.last_name",
                "company": "gen.company",
            },
            response='{"seniority":"senior","company_size":"51-200"}',
        ),
    ],
    "js": {
        "kind": "web",
        "title": "SuiteCRM web-to-lead bundle",
        "modules": ["jquery", "axios"],
        "routes": ["/index.php", "/index.php?entryPoint=WebToLeadCapture"],
        "endpoints": [
            "https://enrich.leadscope.example/v1/person",
            "https://api.mailsend.example/v3/send",
        ],
        "ipc": [],
        "init": [],
    },
    "policy": {
        "purposes": ["Responding to quote requests", "Managing business customer relationships"],
        "lawful_basis": "legitimate_interests",
        "sharing_statement": "We use MailSend Europe to send confirmation e-mails and LeadScope Data to complete business contact details.",
        "retention_statement": "Lead and customer records are kept while the business relationship lasts.",
        "transfer_statement": "LeadScope Data processes business contact data in India.",
        "extra_claims": [],
    },
    "questionnaire": {
        "purposes": ["Sales and account management"],
        "data_subjects": ["business contacts"],
        "lawful_basis": "legitimate_interests",
        "special_category_condition": None,
        "retention": None,
        "security_measures": ["Role based access", "Daily encrypted backups"],
        "last_review_date": "2026-05-18",
        "notes": "Transfer mechanism for LeadScope still to be confirmed with legal.",
    },
    "dpia": {"criteria": ["combining_datasets"], "required": False},
}

# ---------------------------------------------------------------------------------------------
# 5. Clinic appointment portal (purpose-built, health data on purpose)
# ---------------------------------------------------------------------------------------------
CLINIC_PORTAL: SystemSpec = {
    "id": "clinic_portal",
    "name": "Clinic appointment portal",
    "stack": "FastAPI application (purpose-built for the estate)",
    "modeled": False,
    "host": "clinic.northbridge-health.example",
    "owner": "Dr. Helena Voss, Clinic Director",
    "population": "in_clinic_portal",
    "description": "Appointment booking for the Northbridge Health clinic arm.",
    "last_review_date": "2023-02-01",
    "elements": {
        "patient_name": element("name", "your name"),
        "patient_email": element("contact_email", "your e-mail address"),
        "patient_phone": element("contact_phone", "your telephone number"),
        "date_of_birth": element("date_of_birth", "your date of birth"),
        "insurance_number": element("national_id", "your insurance number"),
        "insurer": element("insurance_data", "your insurance provider"),
        "reason_for_visit": element("health_data", "your reason for visiting", special=True),
        "symptoms": element("health_data", "the symptoms you describe", special=True),
        "diagnosis": element("health_data", "diagnoses recorded by your doctor", special=True),
        "appointment_datetime": element(
            "health_data", "the date and time of your appointment", special=True
        ),
        "ip_address": element("ip_address", "your IP address"),
    },
    "tables": [
        {
            "name": "patients",
            "per_person": (1, 1),
            "columns": [
                col("patient_id", "INTEGER", "auto"),
                col("full_name", "TEXT", "person.full_name", "patient_name"),
                col("email", "TEXT", "person.email", "patient_email", "email"),
                col("phone", "TEXT", "person.phone", "patient_phone"),
                col("dob", "TEXT", "person.date_of_birth", "date_of_birth"),
                col("insurance_number", "TEXT", "gen.insurance_number", "insurance_number"),
                col("insurer", "TEXT", "gen.insurer", "insurer"),
                col("created_at", "TEXT", "gen.recent_ts"),
            ],
        },
        {
            "name": "appointments",
            "per_person": (1, 3),
            "columns": [
                col("appointment_id", "INTEGER", "auto"),
                col("patient_email", "TEXT", "person.email", "patient_email", "email"),
                col("doctor", "TEXT", "gen.doctor"),
                col("appointment_at", "TEXT", "gen.appointment_ts", "appointment_datetime"),
                col("reason_for_visit", "TEXT", "gen.reason", "reason_for_visit"),
                col("symptoms", "TEXT", "gen.symptoms", "symptoms"),
                col("status", "TEXT", "gen.appointment_status"),
                col("booked_from_ip", "TEXT", "person.ip_address", "ip_address"),
            ],
        },
        {
            "name": "consultation_notes",
            "per_person": (0, 2),
            "columns": [
                col("note_id", "INTEGER", "auto"),
                col("patient_email", "TEXT", "person.email", "patient_email", "email"),
                col("diagnosis", "TEXT", "gen.diagnosis", "diagnosis"),
                col("created_at", "TEXT", "gen.recent_ts"),
            ],
        },
    ],
    "pages": [
        {
            "path": "/",
            "title": "Book an appointment - Northbridge Health",
            "heading": "Book an appointment",
            "intro": "Choose a doctor and tell us why you would like to visit.",
            "scripts": [
                "https://clinic.northbridge-health.example/static/booking.js",
                "https://cal.bookwell.example/widget.js",
            ],
            "styles": [],
            "images": [],
            "iframes": [],
            "cookies": [{"name": "clinic_session", "el": None, "http_only": True, "max_age": 3600}],
        }
    ],
    "endpoints": [
        {
            "id": "book_appointment",
            "path": "/appointments",
            "method": "POST",
            "enctype": "form",
            "page": "/",
            "submit_label": "Book appointment",
            "fields": [
                fld(
                    "full_name",
                    "person.full_name",
                    "patient_name",
                    label="Full name",
                    autocomplete="name",
                    required=True,
                ),
                fld(
                    "email",
                    "person.email",
                    "patient_email",
                    type="email",
                    label="Email",
                    autocomplete="email",
                    required=True,
                ),
                fld(
                    "phone",
                    "person.phone",
                    "patient_phone",
                    type="tel",
                    label="Mobile phone",
                    autocomplete="tel",
                    required=True,
                ),
                fld(
                    "dob",
                    "person.date_of_birth",
                    "date_of_birth",
                    type="date",
                    label="Date of birth",
                    autocomplete="bday",
                    required=True,
                ),
                fld(
                    "insurance_number",
                    "gen.insurance_number",
                    "insurance_number",
                    label="Insurance number",
                ),
                fld("insurer", "gen.insurer", "insurer", label="Insurance provider"),
                fld(
                    "reason_for_visit",
                    "gen.reason",
                    "reason_for_visit",
                    type="textarea",
                    label="Reason for your visit",
                    required=True,
                ),
                fld("symptoms", "gen.symptoms", "symptoms", type="textarea", label="Symptoms"),
                fld(
                    "terms",
                    "gen.one",
                    None,
                    type="checkbox",
                    label="I accept the terms of use",
                    required=True,
                ),
            ],
            "writes": [
                {
                    "table": "patients",
                    "map": {
                        "full_name": "field:full_name",
                        "email": "field:email",
                        "phone": "field:phone",
                        "dob": "field:dob",
                        "insurance_number": "field:insurance_number",
                        "insurer": "field:insurer",
                        "created_at": "now",
                    },
                },
                {
                    "table": "appointments",
                    "map": {
                        "patient_email": "field:email",
                        "doctor": "gen:doctor",
                        "appointment_at": "gen:appointment_ts",
                        "reason_for_visit": "field:reason_for_visit",
                        "symptoms": "field:symptoms",
                        "status": "const:booked",
                        "booked_from_ip": "ip",
                    },
                },
            ],
            "response": {"appointment_id": "$last_id", "status": "booked", "email": "$field:email"},
        }
    ],
    "recipients": [
        recipient(
            "bookwell",
            ["cal.bookwell.example"],
            "BookWell Scheduling",
            "processor",
            "NL",
            "Appointment slot booking",
            ["patient_name", "patient_email", "appointment_datetime"],
        ),
        recipient(
            "smsgate",
            ["api.smsgate.example"],
            "SMSGate",
            "processor",
            "IN",
            "Appointment reminder text messages",
            ["patient_phone", "appointment_datetime"],
            basis="none",
        ),
    ],
    "beacons": [
        beacon(
            "bookwell_reserve",
            "bookwell",
            "cal.bookwell.example",
            "POST",
            "/api/slots/reserve",
            body_type="json",
            body={
                "name": "person.full_name",
                "email": "person.email",
                "slot": "gen.appointment_ts",
            },
            response='{"reserved":true}',
        ),
    ],
    "js": {
        "kind": "web",
        "title": "Clinic booking bundle",
        "modules": ["react", "react-dom", "@bookwell/widget", "axios"],
        "routes": ["/", "/appointments", "/my-appointments"],
        "endpoints": [
            "https://cal.bookwell.example/api/slots/reserve",
            "https://api.smsgate.example/v1/messages",
        ],
        "ipc": [],
        "init": ["BookWell.init({ clinic: 'northbridge-health' });"],
    },
    "policy": {
        "purposes": ["Booking and managing your appointments", "Sending appointment reminders"],
        "lawful_basis": "legitimate_interests",
        "sharing_statement": "We use BookWell Scheduling to reserve appointment slots and SMSGate to send reminders by text message.",
        "retention_statement": "Appointment records are kept for ten years.",
        "transfer_statement": "BookWell is based in the Netherlands. SMSGate sends reminders from India.",
        "extra_claims": [],
    },
    "questionnaire": {
        "purposes": ["Appointment management"],
        "data_subjects": ["patients"],
        "lawful_basis": "legitimate_interests",
        "special_category_condition": None,
        "retention": "10 years",
        "security_measures": ["Encryption at rest", "Two person access to clinical notes"],
        "last_review_date": "2023-02-01",
        "notes": "Portal built in-house; no review since launch.",
    },
    "dpia": {"criteria": ["sensitive_data", "vulnerable_subjects"], "required": True},
}

# ---------------------------------------------------------------------------------------------
# 6. Newsletter service (purpose-built, collects more than its policy states)
# ---------------------------------------------------------------------------------------------
NEWSLETTER: SystemSpec = {
    "id": "newsletter",
    "name": "Newsletter service",
    "stack": "FastAPI application (purpose-built for the estate)",
    "modeled": False,
    "host": "newsletter.northbridge.example",
    "owner": "Daniel Okoye, Digital Marketing Manager",
    "population": "in_newsletter",
    "description": "Subscription page and list management for the marketing newsletter.",
    "last_review_date": "2026-01-14",
    "elements": {
        "subscriber_email": element("contact_email", "your e-mail address"),
        "first_name": element("name", "your first name"),
        "phone": element(
            "contact_phone", "your telephone number", policy=False, questionnaire=False
        ),
        "postcode": element("postal_address", "your postcode"),
        "interests": element("preferences", "the topics you are interested in"),
        "signup_ip": element("ip_address", "your IP address when you subscribe"),
        "marketing_consent": element("consent_record", "your consent and when you gave it"),
    },
    "tables": [
        {
            "name": "subscribers",
            "per_person": (1, 1),
            "columns": [
                col("id", "INTEGER", "auto"),
                col("email", "TEXT", "person.email", "subscriber_email", "email"),
                col("first_name", "TEXT", "person.first_name", "first_name"),
                col("phone", "TEXT", "person.phone", "phone"),
                col("postcode", "TEXT", "person.postal_code", "postcode"),
                col("interests", "TEXT", "gen.interests", "interests"),
                col("signup_ip", "TEXT", "person.ip_address", "signup_ip"),
                col("consent_marketing", "INTEGER", "gen.one", "marketing_consent"),
                col("consent_at", "TEXT", "gen.recent_ts", "marketing_consent"),
                col("created_at", "TEXT", "gen.recent_ts"),
            ],
        }
    ],
    "pages": [
        {
            "path": "/",
            "title": "Subscribe - Northbridge Newsletter",
            "heading": "Our newsletter",
            "intro": "News, offers and events, about twice a month.",
            "scripts": [
                "https://newsletter.northbridge.example/static/subscribe.js",
                "https://track.openpulse.example/pixel.js",
            ],
            "styles": [],
            "images": [],
            "iframes": [],
            "cookies": [],
        }
    ],
    "endpoints": [
        {
            "id": "subscribe",
            "path": "/subscribe",
            "method": "POST",
            "enctype": "form",
            "page": "/",
            "submit_label": "Subscribe",
            "fields": [
                fld(
                    "email",
                    "person.email",
                    "subscriber_email",
                    type="email",
                    label="Email address",
                    autocomplete="email",
                    required=True,
                ),
                fld(
                    "first_name",
                    "person.first_name",
                    "first_name",
                    label="First name",
                    autocomplete="given-name",
                ),
                fld(
                    "phone",
                    "person.phone",
                    "phone",
                    type="tel",
                    label="Mobile phone",
                    autocomplete="tel",
                ),
                fld(
                    "postcode",
                    "person.postal_code",
                    "postcode",
                    label="Postcode",
                    autocomplete="postal-code",
                ),
                fld("interests", "gen.interests", "interests", label="Interests"),
                fld(
                    "consent_marketing",
                    "gen.one",
                    "marketing_consent",
                    type="checkbox",
                    label="Yes, send me marketing e-mails",
                    checked=True,
                ),
            ],
            "writes": [
                {
                    "table": "subscribers",
                    "map": {
                        "email": "field:email",
                        "first_name": "field:first_name",
                        "phone": "field:phone",
                        "postcode": "field:postcode",
                        "interests": "field:interests",
                        "signup_ip": "ip",
                        "consent_marketing": "field:consent_marketing",
                        "consent_at": "now",
                        "created_at": "now",
                    },
                }
            ],
            "response": {"subscribed": True, "id": "$last_id"},
        }
    ],
    "recipients": [
        recipient(
            "mailsend_news",
            ["api.mailsend.example"],
            "MailSend Europe",
            "processor",
            "IE",
            "Newsletter delivery",
            ["subscriber_email", "first_name", "interests"],
        ),
        recipient(
            "openpulse",
            ["track.openpulse.example"],
            "OpenPulse Tracking",
            "processor",
            "US",
            "E-mail open tracking",
            ["subscriber_email"],
            policy=False,
            questionnaire=False,
            agreement=False,
            basis="none",
        ),
    ],
    "beacons": [
        beacon(
            "mailsend_contact",
            "mailsend_news",
            "api.mailsend.example",
            "POST",
            "/v3/contacts",
            body_type="json",
            body={
                "email": "person.email",
                "first_name": "person.first_name",
                "list": "const.northbridge-news",
            },
            response='{"created":true}',
        ),
        beacon(
            "openpulse_pixel",
            "openpulse",
            "track.openpulse.example",
            "GET",
            "/p.gif",
            body_type="none",
            query={"e": "gen.tracking_hash", "c": "const.welcome"},
            response="GIF89a",
            elements={"e": "subscriber_email"},
        ),
    ],
    "js": {
        "kind": "web",
        "title": "Newsletter subscribe bundle",
        "modules": ["axios"],
        "routes": ["/", "/subscribe", "/unsubscribe"],
        "endpoints": [
            "https://api.mailsend.example/v3/contacts",
            "https://track.openpulse.example/p.gif",
        ],
        "ipc": [],
        "init": [],
    },
    "policy": {
        "purposes": ["Sending you our newsletter"],
        "lawful_basis": "consent",
        "sharing_statement": "We use MailSend Europe to deliver the newsletter. We do not share your data with anyone else.",
        "retention_statement": "We keep your subscription until you unsubscribe, then delete it within 30 days.",
        "transfer_statement": "Newsletter data stays in the European Economic Area.",
        "extra_claims": [
            "We only send marketing e-mails if you actively opt in. No box is ticked for you."
        ],
    },
    "questionnaire": {
        "purposes": ["Email marketing"],
        "data_subjects": ["subscribers"],
        "lawful_basis": "consent",
        "special_category_condition": None,
        "retention": "Until unsubscribe plus 30 days",
        "security_measures": ["Double encrypted backups", "Admin access via SSO"],
        "last_review_date": "2026-01-14",
        "notes": "Phone number was added for a text message campaign.",
    },
    "dpia": {"criteria": [], "required": False},
}

# ---------------------------------------------------------------------------------------------
# 7. Staff desktop client (Electron app with a local SQLite store, purpose-built)
# ---------------------------------------------------------------------------------------------
STAFF_DESKTOP: SystemSpec = {
    "id": "staff_desktop",
    "name": "Staff desktop client",
    "stack": "Electron application with a local SQLite store (purpose-built for the estate)",
    "modeled": False,
    "host": "hr-api.northbridge.example",
    "owner": "Nadia Rahman, IT Manager",
    "population": "in_staff_desktop",
    "description": "Desktop client for staff to view their profile, clock in and out, and submit timesheets.",
    "last_review_date": "2026-06-30",
    "elements": {
        "employee_id": element("employment_data", "your employee number"),
        "employee_name": element("name", "your name"),
        "work_email": element("contact_email", "your work e-mail address"),
        "phone": element("contact_phone", "your work telephone number"),
        "department": element("employment_data", "your department and manager"),
        "hours_worked": element("employment_data", "your working hours"),
        "clock_in_location": element("geolocation", "your location when you clock in or out"),
        "device_id": element("device_identifier", "an identifier of your computer"),
        "last_login_ip": element("ip_address", "the IP address of your last sign in"),
    },
    "tables": [
        {
            "name": "employee_profile",
            "per_person": (1, 1),
            "columns": [
                col("employee_id", "TEXT", "person.employee_id", "employee_id"),
                col("full_name", "TEXT", "person.full_name", "employee_name"),
                col("work_email", "TEXT", "person.email", "work_email", "email"),
                col("phone", "TEXT", "person.phone", "phone"),
                col("department", "TEXT", "gen.department", "department"),
                col("manager", "TEXT", "gen.manager", "department"),
                col("last_login_ip", "TEXT", "person.ip_address", "last_login_ip"),
            ],
        },
        {
            "name": "timesheets",
            "per_person": (3, 8),
            "columns": [
                col("id", "INTEGER", "auto"),
                col("work_email", "TEXT", "person.email", "work_email", "email"),
                col("work_date", "TEXT", "gen.work_date"),
                col("hours", "REAL", "gen.hours", "hours_worked"),
            ],
        },
        {
            "name": "clock_events",
            "per_person": (4, 10),
            "columns": [
                col("id", "INTEGER", "auto"),
                col("work_email", "TEXT", "person.email", "work_email", "email"),
                col("event", "TEXT", "gen.clock_event"),
                col("latitude", "REAL", "gen.lat", "clock_in_location"),
                col("longitude", "REAL", "gen.lon", "clock_in_location"),
                col("device_id", "TEXT", "gen.device_id", "device_id"),
                col("occurred_at", "TEXT", "gen.recent_ts"),
            ],
        },
    ],
    "pages": [
        {
            "path": "/renderer/index.html",
            "title": "Northbridge Staff Hub",
            "heading": "Staff Hub",
            "intro": "Signed in. Use the buttons below to clock in or submit your timesheet.",
            "scripts": ["app://staff-hub/main.bundle.js"],
            "styles": [],
            "images": [],
            "iframes": [],
            "cookies": [],
        }
    ],
    "endpoints": [
        {
            "id": "clock",
            "path": "/api/v1/clock",
            "method": "POST",
            "enctype": "json",
            "page": None,
            "fields": [
                fld("employee_id", "person.employee_id", "employee_id"),
                fld("event", "gen.clock_event"),
                fld("latitude", "gen.lat", "clock_in_location"),
                fld("longitude", "gen.lon", "clock_in_location"),
                fld("device_id", "gen.device_id", "device_id"),
            ],
            "writes": [
                {
                    "table": "clock_events",
                    "map": {
                        "work_email": "person:email",
                        "event": "field:event",
                        "latitude": "field:latitude",
                        "longitude": "field:longitude",
                        "device_id": "field:device_id",
                        "occurred_at": "now",
                    },
                }
            ],
            "response": {"id": "$last_id", "accepted": True},
        },
        {
            "id": "timesheet",
            "path": "/api/v1/timesheets",
            "method": "POST",
            "enctype": "json",
            "page": None,
            "fields": [
                fld("employee_id", "person.employee_id", "employee_id"),
                fld("work_date", "gen.work_date"),
                fld("hours", "gen.hours", "hours_worked"),
            ],
            "writes": [
                {
                    "table": "timesheets",
                    "map": {
                        "work_email": "person:email",
                        "work_date": "field:work_date",
                        "hours": "field:hours",
                    },
                }
            ],
            "response": {"id": "$last_id", "accepted": True},
        },
        {
            "id": "profile",
            "path": "/api/v1/me",
            "method": "GET",
            "enctype": "query",
            "page": None,
            "fields": [fld("employee_id", "person.employee_id", "employee_id")],
            "writes": [],
            "response": {
                "employee_id": "$field:employee_id",
                "full_name": "$person:full_name",
                "work_email": "$person:email",
                "phone": "$person:phone",
                "department": "Store Operations",
            },
        },
    ],
    "recipients": [
        recipient(
            "sentry",
            ["o4501.ingest.sentry.io"],
            "Sentry",
            "processor",
            "US",
            "Error monitoring",
            ["work_email", "device_id", "last_login_ip"],
            policy=False,
            questionnaire=False,
            agreement=False,
            basis="none",
        ),
    ],
    "beacons": [
        beacon(
            "sentry_envelope",
            "sentry",
            "o4501.ingest.sentry.io",
            "POST",
            "/api/1/envelope/",
            body_type="json",
            body={
                "user.email": "person.email",
                "user.ip_address": "person.ip_address",
                "contexts.device.id": "gen.device_id",
                "exception.value": "const.TypeError: cannot read properties of undefined",
            },
            response='{"id":"ab12cd34"}',
            elements={
                "user.email": "work_email",
                "user.ip_address": "last_login_ip",
                "contexts.device.id": "device_id",
            },
        ),
    ],
    "js": {
        "kind": "electron",
        "title": "Northbridge Staff Hub (main, preload and renderer)",
        "modules": ["electron", "better-sqlite3", "electron-store", "axios", "@sentry/electron"],
        "routes": ["/home", "/clock", "/timesheets", "/profile"],
        "endpoints": [
            "https://hr-api.northbridge.example/api/v1/clock",
            "https://hr-api.northbridge.example/api/v1/timesheets",
            "https://hr-api.northbridge.example/api/v1/me",
            "https://o4501.ingest.sentry.io/api/1/envelope/",
        ],
        "ipc": ["clock:in", "clock:out", "timesheet:submit", "profile:get"],
        "init": [
            "Sentry.init({ dsn: 'https://examplekey@o4501.ingest.sentry.io/1', sendDefaultPii: true });",
            "Sentry.setUser({ email: profile.work_email, ip_address: '{{auto}}' });",
        ],
    },
    "policy": {
        "purposes": [
            "Recording working time",
            "Running payroll",
            "Showing you your own staff profile",
        ],
        "lawful_basis": "legal_obligation",
        "sharing_statement": "Working time data is passed to our HR system. We do not share it with anyone outside Northbridge.",
        "retention_statement": "Timesheets are kept for six years.",
        "transfer_statement": "All data is processed inside the European Economic Area.",
        "extra_claims": [],
    },
    "questionnaire": {
        "purposes": ["Working time recording"],
        "data_subjects": ["employees"],
        "lawful_basis": "legal_obligation",
        "special_category_condition": None,
        "retention": "6 years",
        "security_measures": ["Signed application builds", "Encrypted local database"],
        "last_review_date": "2026-06-30",
        "notes": "Error reporting added in the last release.",
    },
    "dpia": {"criteria": ["systematic_monitoring", "vulnerable_subjects"], "required": True},
}

# ---------------------------------------------------------------------------------------------
# 8. HR onboarding form (purpose-built, special category fields)
# ---------------------------------------------------------------------------------------------
HR_ONBOARDING: SystemSpec = {
    "id": "hr_onboarding",
    "name": "HR onboarding form",
    "stack": "FastAPI application (purpose-built for the estate)",
    "modeled": False,
    "host": "hr.northbridge.example",
    "owner": "Grace Lindqvist, HR Director",
    "population": "in_hr_onboarding",
    "description": "Onboarding form completed by new employees before their start date.",
    "last_review_date": "2026-07-09",
    "elements": {
        "employee_name": element("name", "your name"),
        "personal_email": element("contact_email", "your personal e-mail address"),
        "phone": element("contact_phone", "your telephone number"),
        "date_of_birth": element("date_of_birth", "your date of birth"),
        "home_address": element("postal_address", "your home address"),
        "national_id": element("national_id", "your national identification number"),
        "bank_iban": element("bank_account", "your bank account number for salary payments"),
        "emergency_contact": element(
            "family_data", "the name and phone number of your emergency contact"
        ),
        "nationality": element("nationality", "your nationality and right to work"),
        "disability_status": element(
            "health_data",
            "whether you have a disability that needs workplace adjustments",
            special=True,
        ),
        "union_membership": element(
            "trade_union_membership",
            "whether you are a trade union member (for dues deduction)",
            special=True,
        ),
        "ethnic_origin": element(
            "racial_ethnic_origin",
            "your ethnic origin (equality monitoring, optional)",
            special=True,
        ),
    },
    "tables": [
        {
            "name": "onboarding_records",
            "per_person": (1, 1),
            "columns": [
                col("id", "INTEGER", "auto"),
                col("full_name", "TEXT", "person.full_name", "employee_name"),
                col("email", "TEXT", "person.email", "personal_email", "email"),
                col("phone", "TEXT", "person.phone", "phone"),
                col("dob", "TEXT", "person.date_of_birth", "date_of_birth"),
                col("address", "TEXT", "person.street_address", "home_address"),
                col("national_id", "TEXT", "person.national_id", "national_id"),
                col("iban", "TEXT", "person.iban", "bank_iban"),
                col("emergency_contact_name", "TEXT", "gen.emergency_name", "emergency_contact"),
                col("emergency_contact_phone", "TEXT", "gen.emergency_phone", "emergency_contact"),
                col("nationality", "TEXT", "gen.nationality", "nationality"),
                col("disability_status", "TEXT", "gen.disability", "disability_status"),
                col("union_member", "TEXT", "gen.union_member", "union_membership"),
                col("ethnic_origin", "TEXT", "gen.ethnic_origin", "ethnic_origin"),
                col("submitted_at", "TEXT", "gen.recent_ts"),
            ],
        }
    ],
    "pages": [
        {
            "path": "/onboarding",
            "title": "New employee onboarding - Northbridge",
            "heading": "Welcome to Northbridge",
            "intro": "Please complete this form before your first day.",
            "scripts": ["https://hr.northbridge.example/static/onboarding.js"],
            "styles": [],
            "images": [],
            "iframes": [],
            "cookies": [{"name": "hr_session", "el": None, "http_only": True, "max_age": 3600}],
        }
    ],
    "endpoints": [
        {
            "id": "submit_onboarding",
            "path": "/onboarding/submit",
            "method": "POST",
            "enctype": "form",
            "page": "/onboarding",
            "submit_label": "Submit",
            "fields": [
                fld(
                    "full_name",
                    "person.full_name",
                    "employee_name",
                    label="Full name",
                    autocomplete="name",
                    required=True,
                ),
                fld(
                    "email",
                    "person.email",
                    "personal_email",
                    type="email",
                    label="Personal email",
                    autocomplete="email",
                    required=True,
                ),
                fld(
                    "phone",
                    "person.phone",
                    "phone",
                    type="tel",
                    label="Phone",
                    autocomplete="tel",
                    required=True,
                ),
                fld(
                    "dob",
                    "person.date_of_birth",
                    "date_of_birth",
                    type="date",
                    label="Date of birth",
                    autocomplete="bday",
                    required=True,
                ),
                fld(
                    "address",
                    "person.street_address",
                    "home_address",
                    label="Home address",
                    autocomplete="street-address",
                    required=True,
                ),
                fld(
                    "national_id",
                    "person.national_id",
                    "national_id",
                    label="National ID number",
                    required=True,
                ),
                fld("iban", "person.iban", "bank_iban", label="IBAN for salary", required=True),
                fld(
                    "emergency_contact_name",
                    "gen.emergency_name",
                    "emergency_contact",
                    label="Emergency contact name",
                ),
                fld(
                    "emergency_contact_phone",
                    "gen.emergency_phone",
                    "emergency_contact",
                    type="tel",
                    label="Emergency contact phone",
                ),
                fld("nationality", "gen.nationality", "nationality", label="Nationality"),
                fld(
                    "disability_status",
                    "gen.disability",
                    "disability_status",
                    label="Disability needing adjustments",
                ),
                fld(
                    "union_member",
                    "gen.union_member",
                    "union_membership",
                    label="Trade union member",
                ),
                fld(
                    "ethnic_origin",
                    "gen.ethnic_origin",
                    "ethnic_origin",
                    label="Ethnic origin (optional)",
                ),
            ],
            "writes": [
                {
                    "table": "onboarding_records",
                    "map": {
                        "full_name": "field:full_name",
                        "email": "field:email",
                        "phone": "field:phone",
                        "dob": "field:dob",
                        "address": "field:address",
                        "national_id": "field:national_id",
                        "iban": "field:iban",
                        "emergency_contact_name": "field:emergency_contact_name",
                        "emergency_contact_phone": "field:emergency_contact_phone",
                        "nationality": "field:nationality",
                        "disability_status": "field:disability_status",
                        "union_member": "field:union_member",
                        "ethnic_origin": "field:ethnic_origin",
                        "submitted_at": "now",
                    },
                }
            ],
            "response": {"id": "$last_id", "status": "received"},
        }
    ],
    "recipients": [
        recipient(
            "payrollhub",
            ["api.payrollhub.example"],
            "PayrollHub",
            "processor",
            "PL",
            "Payroll processing",
            ["employee_name", "bank_iban", "national_id", "union_membership"],
        ),
        recipient(
            "verifycheck",
            ["api.verifycheck.example"],
            "VerifyCheck",
            "processor",
            "GB",
            "Pre-employment identity check",
            ["employee_name", "date_of_birth", "national_id"],
        ),
    ],
    "beacons": [
        beacon(
            "payrollhub_employee",
            "payrollhub",
            "api.payrollhub.example",
            "POST",
            "/v2/employees",
            body_type="json",
            body={
                "name": "person.full_name",
                "iban": "person.iban",
                "national_id": "person.national_id",
                "union_member": "gen.union_member",
            },
            response='{"created":true}',
        ),
        beacon(
            "verifycheck_request",
            "verifycheck",
            "api.verifycheck.example",
            "POST",
            "/v1/checks",
            body_type="json",
            body={
                "name": "person.full_name",
                "dob": "person.date_of_birth",
                "national_id": "person.national_id",
            },
            response='{"check_id":"vc_001"}',
        ),
    ],
    "js": {
        "kind": "web",
        "title": "Onboarding form bundle",
        "modules": ["react", "react-dom", "axios", "zod"],
        "routes": ["/onboarding", "/onboarding/submit", "/onboarding/thanks"],
        "endpoints": [
            "https://api.payrollhub.example/v2/employees",
            "https://api.verifycheck.example/v1/checks",
        ],
        "ipc": [],
        "init": [],
    },
    "policy": {
        "purposes": [
            "Setting up your employment record",
            "Paying your salary",
            "Meeting our legal duties as an employer",
        ],
        "lawful_basis": "contract",
        "sharing_statement": "We share payroll data with PayrollHub and identity data with VerifyCheck. Both act only on our instructions.",
        "retention_statement": "Employment records are kept for the duration of employment plus six years.",
        "transfer_statement": "PayrollHub processes data in Poland and VerifyCheck in the United Kingdom.",
        "extra_claims": [],
    },
    "questionnaire": {
        "purposes": ["Onboarding", "Payroll"],
        "data_subjects": ["employees"],
        "lawful_basis": "contract",
        "special_category_condition": None,
        "retention": "Employment plus 6 years",
        "security_measures": ["Encryption at rest", "HR-only access"],
        "last_review_date": "2026-07-09",
        "notes": "Equality monitoring question added at the request of the board.",
    },
    "dpia": {"criteria": ["sensitive_data", "vulnerable_subjects"], "required": True},
}

SYSTEMS: list[SystemSpec] = [
    WEB_SHOP, WEB_ANALYTICS, HELPDESK, CRM, CLINIC_PORTAL, NEWSLETTER, STAFF_DESKTOP, HR_ONBOARDING,
]  # fmt: skip

# ---------------------------------------------------------------------------------------------
# Seeded contradictions. `types` are the finding types a correct fusion step should report.
# `subject` identifies the element or recipient (or "policy"/"questionnaire" statements).
# ---------------------------------------------------------------------------------------------
CONTRADICTIONS: list[dict[str, Any]] = [
    {
        "id": "C01",
        "system": "web_shop",
        "types": ["element_not_in_policy"],
        "subject": "date_of_birth",
        "summary": "The checkout form collects a date of birth that the privacy notice does not list.",
    },
    {
        "id": "C02",
        "system": "web_shop",
        "types": ["policy_contradiction"],
        "subject": "meta",
        "summary": "The privacy notice says data is shared with no one except the payment provider and carrier, yet the checkout sends hashed e-mail, phone and order value to Meta.",
    },
    {
        "id": "C03",
        "system": "web_shop",
        "types": ["undeclared_recipient", "third_country_no_safeguard"],
        "subject": "meta",
        "summary": "Meta Platforms receives personal data in the United States but is neither declared nor covered by a transfer safeguard.",
    },
    {
        "id": "C04",
        "system": "web_shop",
        "types": ["retention_conflict"],
        "subject": "retention",
        "summary": "The company privacy policy promises deletion after 24 months while the shop keeps orders for seven years.",
    },
    {
        "id": "C05",
        "system": "web_analytics",
        "types": ["policy_contradiction"],
        "subject": "ip_address",
        "summary": "The notice says IP addresses are shortened before storage, but full addresses are stored and sent to the agency.",
    },
    {
        "id": "C06",
        "system": "web_analytics",
        "types": ["missing_agreement"],
        "subject": "brightlens",
        "summary": "BrightLens processes visitor data but no processor agreement is on file.",
    },
    {
        "id": "C07",
        "system": "web_analytics",
        "types": ["element_not_in_policy"],
        "subject": "user_email",
        "summary": "Logged in customers' e-mail addresses are stored as the user id, which the notice and questionnaire do not mention.",
    },
    {
        "id": "C08",
        "system": "helpdesk",
        "types": ["retention_conflict"],
        "subject": "retention",
        "summary": "Policy and questionnaire say twelve months after closure, but tickets back to 2022 are retained and no deletion exists.",
    },
    {
        "id": "C09",
        "system": "helpdesk",
        "types": ["policy_contradiction"],
        "subject": "message_content",
        "summary": "The notice says chat transcripts are not stored, but every message is stored in the messages table.",
    },
    {
        "id": "C10",
        "system": "crm",
        "types": ["third_country_no_safeguard"],
        "subject": "leadscope",
        "summary": "LeadScope Data receives contact data in India, which has no adequacy decision, and no safeguard is recorded.",
    },
    {
        "id": "C11",
        "system": "crm",
        "types": ["missing_retention"],
        "subject": "retention",
        "summary": "The questionnaire gives no retention period.",
    },
    {
        "id": "C12",
        "system": "clinic_portal",
        "types": ["missing_art9_condition"],
        "subject": "health_data",
        "summary": "Health data is processed with no Article 9 condition recorded, and the notice cites legitimate interests.",
    },
    {
        "id": "C13",
        "system": "clinic_portal",
        "types": ["third_country_no_safeguard"],
        "subject": "smsgate",
        "summary": "SMSGate receives phone numbers and appointment times in India with no adequacy decision or safeguard.",
    },
    {
        "id": "C14",
        "system": "clinic_portal",
        "types": ["stale_review"],
        "subject": "last_review_date",
        "summary": "The record was last reviewed on 2023-02-01, more than twelve months before the reference date.",
    },
    {
        "id": "C15",
        "system": "newsletter",
        "types": ["element_not_in_policy"],
        "subject": "phone",
        "summary": "The subscribe form collects a phone number that the privacy notice does not list.",
    },
    {
        "id": "C16",
        "system": "newsletter",
        "types": ["consent_defect"],
        "subject": "marketing_consent",
        "summary": "The marketing consent box is ticked by default although the notice promises an active opt in.",
    },
    {
        "id": "C17",
        "system": "newsletter",
        "types": ["undeclared_recipient", "third_country_no_safeguard", "missing_agreement"],
        "subject": "openpulse",
        "summary": "OpenPulse Tracking receives hashed subscriber e-mails in the United States; it is undeclared, has no safeguard and no agreement.",
    },
    {
        "id": "C18",
        "system": "staff_desktop",
        "types": ["undeclared_recipient", "third_country_no_safeguard", "missing_agreement"],
        "subject": "sentry",
        "summary": "The desktop app sends staff e-mail, device id and IP address to Sentry, which is undeclared, has no safeguard and no agreement.",
    },
    {
        "id": "C19",
        "system": "hr_onboarding",
        "types": ["missing_art9_condition"],
        "subject": "special_categories",
        "summary": "Disability, trade union and ethnic origin data are collected with no Article 9 condition recorded.",
    },
]

# Vendor agreements for processors that have one on file are generated from the recipients
# that set agreement_on_file and agreement_required.
