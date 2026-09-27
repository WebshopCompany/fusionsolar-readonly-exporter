# Official Huawei Northbound/OpenAPI: separate future route

The current exporter targets the owner-account FusionSolar **web/frontend** interface (`/rest/...`). It
is reverse-engineered/community-supported behaviour and must not be described as Huawei's official API.

Huawei's official Northbound/OpenAPI uses a separate `/thirdData/...` interface, installer/company
provisioning model, permissions and documented rate/session constraints. That route may be preferable
for a later supported integration, but it is intentionally not required for this owner-account exporter.
