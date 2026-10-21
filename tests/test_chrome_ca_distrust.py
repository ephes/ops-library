import base64
import hashlib
import json
from pathlib import Path
import ssl
import unittest

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT=Path(__file__).parents[1]/'roles/chrome_ca_distrust/files'


class TestChromePolicy(unittest.TestCase):
    def test_exact_eight_incident_certificates_and_unique_keys(self):
        policy=json.loads((ROOT/'99-emudhra.json').read_text())
        manifest=json.loads((ROOT/'incident-certificate-manifest.json').read_text())
        self.assertEqual(set(policy),{'CADistrustedCertificates'})
        entries=policy['CADistrustedCertificates']
        self.assertEqual(len(entries),8)
        self.assertEqual(len({item['spki_sha256'] for item in manifest['certificates']}),8)
        expected={item['sha256'].lower() for item in manifest['certificates']}
        actual=set()
        actual_spki=set()
        for value in entries:
            der=base64.b64decode(value,validate=True)
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(der))
            actual.add(hashlib.sha256(der).hexdigest())
            spki=x509.load_der_x509_certificate(der).public_key().public_bytes(Encoding.DER,PublicFormat.SubjectPublicKeyInfo)
            actual_spki.add(hashlib.sha256(spki).hexdigest())
        self.assertEqual(actual,expected)
        self.assertEqual(actual_spki,{item["spki_sha256"].lower() for item in manifest["certificates"]})
