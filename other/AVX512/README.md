# Thorium AVX-512

This directory contains Thorium AVX-512 release configurations and product
metadata:

- [`AVX512_args.gn`](AVX512_args.gn): Linux x64;
- [`win_AVX512_args.gn`](win_AVX512_args.gn): Windows x64.

Both release files select:

```gn
thorium_x86_profile = "avx512_skx"
```

The profile requires AVX2, FMA, F16C, AVX-512F/CD/VL/BW/DQ, and the complete
operating-system state support needed by those instructions. It does not imply
later extensions such as VNNI, IFMA, or VBMI. Its
`-mtune=skylake-avx512` tuning choice does not add instruction sets beyond the
explicit profile.

Linux AVX-512 builds retain source-level `O3`, PGO, CFI, and ThinLTO `O2`, but
disable SLP vectorization during the final link. LLVM 23 can otherwise produce
invalid masked-load IR for Blink AVX-512 code. Front-end vectorization, Windows
AVX-512, and the other x86 profiles are unchanged.

Prepare the Chromium tree and AVX-512 product metadata from the Thorium
repository root with:

```shell
python3 setup.py --avx512
```

`setup.py` does not install either GN args file. Copy or review the matching
file as Chromium's `out/thorium/args.gn`, then run `gn gen out/thorium` from
Chromium `src`.

AVX-512 product names alone are not a compatibility test. Use
[`check_simd.py`](../../check_simd.py) and consult the
[release profile guide](../../docs/ABOUT_RELEASES.md) before running the
result.

<img src="https://raw.githubusercontent.com/Alex313031/thorium/main/logos/STAGING/AVX2.png" alt="SIMD profile" width="86">
