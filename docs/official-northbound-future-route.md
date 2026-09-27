# Official Huawei Northbound/OpenAPI: separate future route

The current exporter targets the owner-account FusionSolar **web/frontend** interface (`/rest/...`).
It is reverse-engineered/community-supported behaviour and must not be described as Huawei's official
API.

Huawei's Northbound API documentation distinguishes API Account access from OAuth Connect
third-party application access. Current Huawei FusionSolar FAQs also state that Northbound API
applications are made by the company's administrator. These are separate provisioning and access
models from the owner-web interface used by this exporter.

Huawei's EU Data Act disclosure, last updated 3 July 2026, describes an owner-authorised data-sharing
flow in which a third party registers as an OAuth client, enters into the Agreement on Use of Huawei
APIs, and the user authorises data sharing.

The EU Data Act disclosure does **not** establish that the same owner-authorised OAuth route is
available to a UK residential owner. UK eligibility, application approval, contractual terms and
actual provisioning therefore remain unverified and must not be inferred from EU-law documentation.

A future official backend should remain separate from this owner-web backend while sharing only the
normalised storage/provenance model where semantics genuinely align. Do not require Northbound/OAuth
credentials for the current owner-web exporter.

## Huawei source references

- Northbound API reference FAQ: https://info.support.huawei.com/enterprise/en/doc/EDOC1100427895/2065e9cf/faqs
- FusionSolar FAQ (Northbound applications): https://info.support.huawei.com/DpinfoAppDoc/pro_erp_slice001/doc/fusion_solar/faq/installer/en/en-us_topic_0000001867081537.html
- EU Data Act disclosure: https://digitalpower.huawei.com/en/eu-data-act
