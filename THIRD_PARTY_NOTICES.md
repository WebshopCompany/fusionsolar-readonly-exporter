# Third-party notices

## FusionSolarPy

This project depends on `fusion-solar-py==0.1.2` and was engineered against upstream
`jgriss/FusionSolarPy` commit `3e02b9f5d831673070e0f7ddac7d9db53ca2368b`.

Only the upstream password-encryption helper is invoked directly. The exporter intentionally does not
instantiate or expose `FusionSolarClient`, because that client also contains a configuration write path.
The frozen module-signal catalogue in `signals.py` is reproduced from the inspected upstream state to
make offline parsing and safety tests deterministic; runtime prefers the pinned package.

### FusionSolarPy MIT licence

Copyright (c) 2025 Johannes Griss

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Home-Assistant-FusionSolar-App reference constants

Authentication and region design was informed by the MIT-licensed
`hcraveiro/Home-Assistant-FusionSolar-App`. No Home Assistant integration is vendored or forked here.

The additional module-1 pack SOH identifiers `230320154`, `230320170`, and `230320186` are bounded
constants reproduced from `custom_components/fusion_solar_app/api/signal_maps.py` at inspected commit
`d04e0fc8f455b31d464427952bd3463e288ac492`.

### Home-Assistant-FusionSolar-App MIT licence

MIT License

Copyright (c) 2024 Henrique Craveiro

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
