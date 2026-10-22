# chrome_ca_distrust

Prepare Chrome’s supported `CADistrustedCertificates` managed policy, available
since Chrome 132, to distrust exactly the eight compromised eMudhra intermediate
public keys (including their cross-signs). This preserves unrelated root trust
and the pinned application/browser versions. No user NSS database, profile or
signed runtime binary is edited.

The role writes `/var/lib/managed-container-ca/chrome/99-emudhra.json` as
root:root 0644. Mount that file read-only at
`/etc/opt/chrome/policies/managed/99-emudhra.json` in the Chrome container,
preserving other policy files. Policy entries contain base64 X.509 certificates;
Chrome matches their SPKI, so separate cross-signed certificates are not needed.
The adjacent repository manifest records the source certificate/SPKI hashes.
No remote content is fetched when applying the role or starting Chrome.

This role does not claim protection until the actual browser with the actual
launch flags rejects both bad chain families and accepts an unaffected site.
Restart affected browser sessions after policy changes. Chrome Root Store and
revocation component updates remain separate from native/OpenSSL CA bundles.

No configurable variables. Evidence: LiveKit Egress’s pinned Chrome 146 accepted
the direct G3 tracker page with a disposable profile and its existing background
network flags; its AAA test failed, and python.org succeeded. The native CA env
override cannot repair Chrome’s independent root store.

Sources: [Chromium policy definition](https://raw.githubusercontent.com/chromium/chromium/main/components/policy/resources/templates/policy_definitions/CertificateManagement/CADistrustedCertificates.yaml),
[incident certificates](https://emudhra.we-have-a-problem.com/impacted-intermediates.json).
