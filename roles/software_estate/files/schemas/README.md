# Vendored CycloneDX schemas

Unmodified schemas from the official CycloneDX specification tag `1.6`.
Source: <https://github.com/CycloneDX/specification/tree/1.6/schema>
License: Apache-2.0, included as LICENSE. These are validation inputs only.

SHA-256:

- `bom-1.6.schema.json`: `3e92dddbc30cf7f6a02b80f0942b1a4cfd4fb1c26f1dfc4310afa9d613cafb93`
- `jsf-0.82.schema.json`: `8bae002c25e723db7ee1f26afde680ae1a2b1a8f6b4b4b0fd65dc3becb090aae`
- `spdx.schema.json`: `baa9d3bd1ed57b6751b0887edead6b5063ff53ff7429cf85d476c6c94af0166e`

The repository secret-scan baseline records only three reviewed false positives
in the unmodified CycloneDX schema: its example hash and the definitions of
`shared-secret` and `password`. New findings remain subject to the normal hook.
