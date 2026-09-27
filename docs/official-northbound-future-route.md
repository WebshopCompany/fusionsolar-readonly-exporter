# Official Huawei Northbound/OpenAPI: separate future route

The current exporter targets the owner-account FusionSolar **web/frontend** interface (`/rest/...`).
It is reverse-engineered/community-supported behaviour and must not be described as Huawei's official
API.

As of 2026-09-27, Huawei's SmartPVMS 26.2.0 Northbound API documentation describes both conventional
API Account access and an OAuth 2.0 third-party application integration model. Huawei also publishes
an Agreement on Use of Huawei APIs for third-party API use.

Conventional Northbound API access remains a separately provisioned route; Huawei's current FAQ says
northbound API applications are made by the company's administrator. Huawei's July 2026 EU Data Act
FusionSolar disclosure also describes an owner-authorised OAuth flow in which a third party registers
an OAuth client and the user authorises data sharing.

The EU Data Act disclosure does **not** establish that the same owner-authorised OAuth route is
available to a UK residential owner. UK eligibility, application approval, contractual terms and
actual provisioning therefore remain unverified and must not be inferred from EU-law documentation.

A future official backend should remain separate from this owner-web backend while sharing only the
normalised storage/provenance model where semantics genuinely align. Do not require Northbound/OAuth
credentials for the current owner-web exporter.
