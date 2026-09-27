# Signal semantics

Huawei/source signal IDs and labels are preserved. The exporter does not silently promote a community label into a scientific meaning.

## Battery 30001 / 30002

Community clients label 30001 and 30002 as charging/discharging power, but observed owner-account exports can show daily monotonic/resetting behaviour that is inconsistent with an instantaneous-power interpretation. These fields are therefore emitted with semantic status `SOURCE_LABEL_CONTRADICTED_BY_OBSERVED_BEHAVIOUR` until stronger source evidence establishes their meaning. The exporter does not rename them to energy as certainty.

## Charge/discharge sign

Signed charge/discharge series can use opposite conventions at different FusionSolar endpoints. The exporter preserves endpoint-specific signs, records the source endpoint and reports any observed relationship; it does not silently flip signs.

## Five-minute points versus daily aggregates

Naive integration of five-minute point samples must not be assumed to reproduce Huawei daily energy aggregates. Point samples may not represent interval averages. Vendor daily aggregates are retained as separate source values. Any numerical integration is placed under `derived/`, names its rule, and reports discrepancies rather than replacing vendor aggregates.

## Current-only diagnostics

SOH, module/pack status, temperatures, currents and similar fields are captured as current diagnostics when exposed by read-only endpoints. They are not represented as historical unless historical probing independently confirms historical availability.
