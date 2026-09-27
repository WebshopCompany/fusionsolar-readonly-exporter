# Third-party notices

## FusionSolarPy

This project depends on `fusion-solar-py==0.1.2` (MIT licence) and was engineered against upstream
`jgriss/FusionSolarPy` commit `3e02b9f5d831673070e0f7ddac7d9db53ca2368b`.

Only the upstream password-encryption helper is invoked directly. The exporter intentionally does not
instantiate or expose `FusionSolarClient`, because that client also contains a configuration write path.
The frozen module-signal catalogue in `signals.py` is reproduced from the inspected MIT-licensed
upstream state to make offline parsing/safety tests deterministic; runtime prefers the pinned package.

FusionSolarPy copyright and licence terms remain those of its authors. See the upstream repository for
its full MIT licence and notices.

## Reference implementations

Authentication/region design was informed by public MIT-licensed FusionSolar community integrations,
including `hcraveiro/Home-Assistant-FusionSolar-App`. No Home Assistant integration is vendored or
forked here.


### Pack SOH signal identifiers

The additional module-1 pack SOH identifiers `230320154`, `230320170`, and `230320186`
are bounded constants reproduced from
`hcraveiro/Home-Assistant-FusionSolar-App`,
`custom_components/fusion_solar_app/api/signal_maps.py`, inspected commit
`d04e0fc8f455b31d464427952bd3463e288ac492` (MIT licence, Copyright (c) 2024
Henrique Craveiro). No Home Assistant source module is vendored or forked.
