import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from jinja2 import Environment, StrictUndefined

REPO_ROOT = Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "dns_deploy"
SECRET = "s3cr3t-token-value"

spec = importlib.util.spec_from_file_location("ddns_update", ROLE / "files" / "ddns_update.py")
ddns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ddns)

ZONE = "xn--wersdrfer-47a.de"
BASE = f"https://api.gandi.net/v5/livedns/domains/{ZONE}/records"


class FakeGandi:
    """In-memory Gandi LiveDNS plus IP echo services."""

    def __init__(self, records=None, status=None, ignore_puts=False):
        self.records = dict(records or {})
        self.status = status
        self.ignore_puts = ignore_puts
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        if url == "https://ipv4.icanhazip.com":
            return 200, b"2.243.94.187\n"
        if url == "https://ipv6.icanhazip.com":
            return 200, b"2a02:3100:41eb:df00:6afe:f7ff:fe0c:fc3\n"
        if self.status is not None:
            return self.status, b'{"code":403,"message":"Access was denied to this resource."}'
        assert url.startswith(BASE + "/"), url
        name, rtype = url[len(BASE) + 1:].rsplit("/", 1)
        if method == "GET":
            if (name, rtype) not in self.records:
                return 404, b"{}"
            return 200, json.dumps({"rrset_values": self.records[(name, rtype)]}).encode()
        if method == "PUT":
            if not self.ignore_puts:
                self.records[(name, rtype)] = json.loads(body)["rrset_values"]
            return 201, b'{"message":"DNS Record Created"}'
        return 405, b""


def make_resolver(public):
    def resolve(name, rtype, server):
        if rtype == "NS":
            return ["ns-a.example.", "ns-b.example."]
        return public.get((name, rtype))
    return resolve


NEW4, NEW6 = "2.243.94.187", "2a02:3100:41eb:df00:6afe:f7ff:fe0c:fc3"
OLD4, OLD6 = "80.171.217.153", "2a02:3100:3f53:1500:6afe:f7ff:fe0c:fc3"


def current_public(v4, v6):
    return {
        (f"home.{ZONE}", "A"): [v4], (f"home.{ZONE}", "AAAA"): [v6],
        (f"*.home.{ZONE}", "A"): [v4], (f"*.home.{ZONE}", "AAAA"): [v6],
    }


def config(**overrides):
    base = {"provider": "gandi", "zone": "wersdörfer.de", "names": ["home", "*.home"],
            "ttl": 300, "ipv4": True, "ipv6": True, "gandi": {"auth_scheme": "apikey"}}
    base.update(overrides)
    return base


class DdnsUpdateTests(unittest.TestCase):
    def run_ddns(self, http, public, cfg=None, now=1_000_000):
        lines = []
        code, status = ddns.run(cfg or config(), {"GANDI_API_TOKEN": SECRET}, http=http,
                                resolve=make_resolver(public), log=lines.append, now=lambda: now)
        for line in lines:
            self.assertNotIn(SECRET, line)
        self.assertNotIn(SECRET, json.dumps(status))
        return code, status, lines

    def test_forbidden_fails_run_and_logs_records(self):
        http = FakeGandi(status=403)
        code, status, lines = self.run_ddns(http, current_public(OLD4, OLD6))
        self.assertEqual(code, 1)
        self.assertFalse(status["summary"]["run_ok"])
        self.assertEqual(len(status["errors"]), 4)
        self.assertTrue(any("HTTP 403" in line for line in lines))
        self.assertFalse(status["summary"]["public_ok"])
        self.assertEqual(status["summary"]["consecutive_failures"], 1)

    def test_updates_changed_records_and_reads_back(self):
        http = FakeGandi({("home", "A"): [OLD4], ("home", "AAAA"): [OLD6],
                          ("*.home", "A"): [OLD4]})
        code, status, lines = self.run_ddns(http, current_public(NEW4, NEW6))
        self.assertEqual(code, 0, status["errors"])
        self.assertEqual(status["summary"]["records_updated"], 4)
        self.assertEqual(http.records[("*.home", "AAAA")], [NEW6])
        self.assertIn(f"updated A home.{ZONE}: ['{OLD4}'] -> {NEW4}", lines)
        puts = [c for c in http.calls if c[0] == "PUT"]
        self.assertEqual(json.loads(puts[0][3]), {"rrset_ttl": 300, "rrset_values": [NEW4]})
        self.assertEqual(puts[0][2]["Authorization"], f"Apikey {SECRET}")
        self.assertTrue(status["summary"]["public_ok"])
        self.assertEqual(status["summary"]["public_mismatch_seconds"], 0)

    def test_unchanged_records_are_not_written(self):
        http = FakeGandi({(n, t): [v] for n in ("home", "*.home")
                          for t, v in (("A", NEW4), ("AAAA", NEW6))})
        code, status, lines = self.run_ddns(http, current_public(NEW4, NEW6))
        self.assertEqual(code, 0)
        self.assertFalse([c for c in http.calls if c[0] == "PUT"])
        self.assertIn(f"unchanged AAAA *.home.{ZONE} = {NEW6}", lines)

    def test_read_back_mismatch_fails(self):
        http = FakeGandi({("home", "A"): [OLD4]}, ignore_puts=True)
        code, status, _ = self.run_ddns(http, current_public(OLD4, OLD6))
        self.assertEqual(code, 1)
        self.assertTrue(any("read-back" in e for e in status["errors"]))

    def test_bearer_is_default_scheme(self):
        http = FakeGandi({})
        self.run_ddns(http, {}, cfg=config(gandi={}))
        auth = [c[2]["Authorization"] for c in http.calls if "livedns" in c[1]]
        self.assertTrue(auth and all(a == f"Bearer {SECRET}" for a in auth))

    def test_public_mismatch_duration_persists_between_runs(self):
        http = FakeGandi({})
        public = current_public(OLD4, OLD6)
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "status.json")
            cfg = config(status_path=path)
            _, first, _ = self.run_ddns(http, public, cfg, now=1000)
            ddns.write_status(path, first)
            _, second, _ = self.run_ddns(http, public, cfg, now=4700)
            self.assertEqual(second["summary"]["public_mismatch_since_epoch"], 1000)
            self.assertEqual(second["summary"]["public_mismatch_seconds"], 3700)
            ddns.write_status(path, second)
            _, third, _ = self.run_ddns(http, current_public(NEW4, NEW6), cfg, now=5000)
            self.assertIsNone(third["summary"]["public_mismatch_since_epoch"])

    def test_unanswered_nameserver_is_not_ok(self):
        http = FakeGandi({})
        public = current_public(NEW4, NEW6)

        def resolve(name, rtype, server):
            if rtype == "NS":
                return ["ns-a.example.", "ns-b.example."]
            return None if server == "ns-b.example." else public.get((name, rtype))

        code, status = ddns.run(config(), {"GANDI_API_TOKEN": SECRET}, http=http,
                                resolve=resolve, log=lambda _: None, now=lambda: 1)
        self.assertEqual(code, 0)
        self.assertFalse(status["summary"]["public_ok"])

    def test_unknown_provider_and_missing_credential_fail(self):
        code, status = ddns.run(config(provider="nope"), {}, http=FakeGandi({}),
                                resolve=make_resolver({}), log=lambda _: None)
        self.assertEqual(code, 1)
        self.assertIn("unknown provider", status["errors"][0])
        code, status = ddns.run(config(), {}, http=FakeGandi({}),
                                resolve=make_resolver({}), log=lambda _: None)
        self.assertEqual(code, 1)
        self.assertIn("GANDI_API_TOKEN", status["errors"][0])

    def test_bad_ip_detection_fails(self):
        def http(method, url, headers, body):
            if "icanhazip" in url:
                return 200, b"192.168.1.10\n"
            return FakeGandi({})(method, url, headers, body)

        code, status, _ = self.run_ddns(http, {}, cfg=config(ipv6=False))
        self.assertEqual(code, 1)
        self.assertTrue(any("unusable address" in e for e in status["errors"]))

    def test_idna_zone(self):
        self.assertEqual(ddns.idna_zone("wersdörfer.de."), ZONE)
        self.assertEqual(ddns.idna_zone(ZONE), ZONE)


TSIG = "FAKEKEYFORTESTSONLYNOTREALAAAAAAAAAAAAAAAAA="


def dig_output(status, name="", rtype="A", answers=(), aa=True):
    """What `dig +noall +comments +answer` prints (format of BIND 9.18/9.20)."""
    lines = [
        ";; Got answer:",
        f";; ->>HEADER<<- opcode: QUERY, status: {status}, id: 34895",
        f";; flags: {'qr aa' if aa else 'qr'}; QUERY: 1, ANSWER: {len(answers)}, "
        "AUTHORITY: 2, ADDITIONAL: 1",
        "",
        ";; OPT PSEUDOSECTION:",
        "; EDNS: version: 0, flags:; udp: 1232",
    ]
    if answers:
        lines.append(";; ANSWER SECTION:")
        lines += [f"{name}.\t300\tIN\t{rtype}\t{value}" for value in answers]
    return "\n".join(lines) + "\n"


class FakeNameserver:
    """In-memory primary answering dig queries and applying nsupdate scripts.

    Like BIND it synthesizes answers from a wildcard owner for names that own no
    record at all, and answers NODATA for an existing name without that type.
    """

    def __init__(self, records=None, refuse=False, ignore_updates=False, dig_status=None,
                 dig_aa=True):
        self.records = {k: list(v) for k, v in (records or {}).items()}
        self.refuse = refuse
        self.ignore_updates = ignore_updates
        self.dig_status = dig_status
        self.dig_aa = dig_aa
        self.calls = []
        self.updates = []

    def lookup(self, name, rtype):
        if (name, rtype) in self.records:
            return "NOERROR", self.records[(name, rtype)]
        if any(owner == name for owner, _ in self.records):
            return "NOERROR", []
        if not name.startswith("*.") and "." in name:
            wildcard = "*." + name.split(".", 1)[1]
            if any(owner == wildcard for owner, _ in self.records):
                return "NOERROR", self.records.get((wildcard, rtype), [])
        return "NXDOMAIN", []

    def __call__(self, argv, stdin):
        self.calls.append((list(argv), stdin))
        if argv[0] == "dig":
            name, rtype = argv[-2].rstrip("."), argv[-1]
            if self.dig_status:
                return 0, dig_output(self.dig_status, aa=self.dig_aa)
            status, values = self.lookup(name, rtype)
            return 0, dig_output(status, name, rtype, values, aa=self.dig_aa)
        assert argv == ["nsupdate", "-v"], argv
        if self.refuse:
            return 2, f"update failed: REFUSED (key {TSIG})"
        if self.ignore_updates:
            return 0, ""
        for line in stdin.splitlines():
            parts = line.split()
            if parts[:2] == ["update", "delete"]:
                self.records.pop((parts[2].rstrip("."), parts[3]), None)
                self.updates.append(("delete", parts[2].rstrip("."), parts[3]))
            elif parts[:2] == ["update", "add"]:
                self.records.setdefault((parts[2].rstrip("."), parts[4]), []).append(parts[5])
        return 0, ""


class Rfc2136Tests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(ddns.Rfc2136Backend, "command", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_ddns(self, server, cfg, env=None, public=None):
        ddns.Rfc2136Backend.command = staticmethod(server)
        lines = []
        code, status = ddns.run(
            cfg, env if env is not None else {"DDNS_TSIG_SECRET": TSIG, "GANDI_API_TOKEN": SECRET},
            http=FakeGandi(), resolve=make_resolver(public or current_public(NEW4, NEW6)),
            log=lines.append, now=lambda: 1_000_000,
        )
        return code, status, lines

    def rfc_config(self, **overrides):
        settings = {"server": "192.0.2.53", "key_name": "ddns-home", "key_algorithm": "hmac-sha256"}
        settings.update(overrides)
        return config(provider="rfc2136", rfc2136=settings)

    def test_updates_via_nsupdate_with_secret_on_stdin_only(self):
        server = FakeNameserver({(f"home.{ZONE}", "A"): [OLD4]})
        code, status, lines = self.run_ddns(server, self.rfc_config(update_zone=f"home.{ZONE}"))
        self.assertEqual(code, 0, lines)
        self.assertEqual(server.records[(f"home.{ZONE}", "A")], [NEW4])
        self.assertEqual(server.records[(f"*.home.{ZONE}", "AAAA")], [NEW6])
        updates = [stdin for argv, stdin in server.calls if argv[0] == "nsupdate"]
        self.assertEqual(len(updates), 4)
        self.assertIn("server 192.0.2.53 53\n", updates[0])
        self.assertIn(f"zone home.{ZONE}\n", updates[0])
        self.assertIn(f"key hmac-sha256:ddns-home {TSIG}\n", updates[0])
        self.assertIn(f"update delete home.{ZONE}. A\n", updates[0])
        self.assertIn(f"update add home.{ZONE}. 300 A {NEW4}\n", updates[0])
        for argv, _stdin in server.calls:
            self.assertNotIn(TSIG, " ".join(argv))
        self.assertNotIn(TSIG, "\n".join(lines))
        self.assertNotIn(TSIG, json.dumps(status))
        digs = [argv for argv, _ in server.calls if argv[0] == "dig"]
        self.assertIn("+norecurse", digs[0])
        self.assertIn("@192.0.2.53", digs[0])
        self.assertNotIn("+short", digs[0])
        self.assertIn("+comments", digs[0])

    def test_failed_or_unauthoritative_query_is_an_error_not_an_empty_set(self):
        for status, aa in (("REFUSED", False), ("SERVFAIL", False), ("NOERROR", False)):
            with self.subTest(status=status, aa=aa):
                server = FakeNameserver(current_public(NEW4, NEW6), dig_status=status, dig_aa=aa)
                code, status_json, _ = self.run_ddns(server, self.rfc_config())
                self.assertEqual(code, 1)
                self.assertFalse([c for c in server.calls if c[0][0] == "nsupdate"])
                self.assertEqual(status_json["records"]["home_A"]["action"], "failed")

    def test_unchanged_records_send_no_update(self):
        server = FakeNameserver(current_public(NEW4, NEW6))
        code, status, _ = self.run_ddns(server, self.rfc_config())
        self.assertEqual(code, 0)
        self.assertFalse([c for c in server.calls if c[0][0] == "nsupdate"])
        self.assertEqual(status["records"]["home_A"]["action"], "unchanged")

    def test_refused_update_fails_and_redacts_secret(self):
        code, status, lines = self.run_ddns(FakeNameserver(refuse=True), self.rfc_config())
        self.assertEqual(code, 1)
        self.assertTrue(any("REFUSED" in e for e in status["errors"]))
        self.assertNotIn(TSIG, json.dumps(status))
        self.assertNotIn(TSIG, "\n".join(lines))

    def test_ignored_update_fails_read_back(self):
        code, status, _ = self.run_ddns(FakeNameserver(ignore_updates=True), self.rfc_config())
        self.assertEqual(code, 1)
        self.assertTrue(any("read-back" in e for e in status["errors"]))

    def test_missing_secret_and_settings_fail(self):
        code, status, _ = self.run_ddns(FakeNameserver(), self.rfc_config(), env={})
        self.assertEqual(code, 1)
        self.assertIn("DDNS_TSIG_SECRET", " ".join(status["errors"]))
        code, status, _ = self.run_ddns(FakeNameserver(), self.rfc_config(key_name=""))
        self.assertEqual(code, 1)
        code, status, _ = self.run_ddns(FakeNameserver(), self.rfc_config(key_algorithm="hmac-md5"))
        self.assertEqual(code, 1)

    def test_dual_write_updates_both_providers(self):
        server = FakeNameserver()
        gandi = FakeGandi({("home", "A"): [OLD4]})
        cfg = self.rfc_config()
        cfg["providers"] = ["gandi", "rfc2136"]
        ddns.Rfc2136Backend.command = staticmethod(server)
        lines = []
        code, status = ddns.run(cfg, {"DDNS_TSIG_SECRET": TSIG, "GANDI_API_TOKEN": SECRET},
                                http=gandi, resolve=make_resolver(current_public(NEW4, NEW6)),
                                log=lines.append, now=lambda: 1_000_000)
        self.assertEqual(code, 0, lines)
        self.assertEqual(gandi.records[("home", "A")], [NEW4])
        self.assertEqual(server.records[(f"home.{ZONE}", "A")], [NEW4])
        record = status["records"]["home_A"]
        self.assertEqual(record["providers"]["gandi"]["action"], "updated")
        self.assertEqual(record["providers"]["rfc2136"]["action"], "updated")
        self.assertEqual(status["provider"], "gandi")
        self.assertEqual(status["providers"], ["gandi", "rfc2136"])
        self.assertIn(f"updated rfc2136 A home.{ZONE}: [] -> {NEW4}", lines)

    def test_single_provider_log_header_is_unchanged(self):
        _code, _status, lines = self.run_ddns(FakeNameserver(), self.rfc_config())
        self.assertEqual(lines[0], f"DDNS run: provider=rfc2136 zone={ZONE} names=home,*.home")

    def test_public_view_uses_the_delegated_child_zone_servers(self):
        asked = []

        def resolve(name, rtype, server):
            if rtype == "NS":
                return {f"home.{ZONE}": ["ns1.child."], ZONE: ["ns-a.parent."]}.get(name, [])
            asked.append((name, server))
            return current_public(NEW4, NEW6).get((name, rtype)) if server == "ns1.child." else None

        ddns.Rfc2136Backend.command = staticmethod(FakeNameserver(current_public(NEW4, NEW6)))
        code, status = ddns.run(self.rfc_config(), {"DDNS_TSIG_SECRET": TSIG}, http=FakeGandi(),
                                resolve=resolve, log=lambda _l: None, now=lambda: 1_000_000)
        self.assertEqual(code, 0)
        self.assertTrue(status["summary"]["public_ok"])
        self.assertEqual({server for _n, server in asked}, {"ns1.child."})
        self.assertEqual(status["nameservers"], ["ns1.child."])

    def test_public_view_falls_back_to_parent_before_delegation(self):
        def resolve(name, rtype, server):
            if rtype == "NS":
                return {ZONE: ["ns-a.parent."]}.get(name, [])
            return current_public(NEW4, NEW6).get((name, rtype))

        ddns.Rfc2136Backend.command = staticmethod(FakeNameserver(current_public(NEW4, NEW6)))
        code, status = ddns.run(self.rfc_config(), {"DDNS_TSIG_SECRET": TSIG}, http=FakeGandi(),
                                resolve=resolve, log=lambda _l: None, now=lambda: 1_000_000)
        self.assertEqual(code, 0)
        self.assertEqual(status["nameservers"], ["ns-a.parent."])
        self.assertTrue(status["summary"]["public_ok"])

    def test_dual_write_fails_when_one_provider_fails(self):
        cfg = self.rfc_config()
        cfg["providers"] = ["gandi", "rfc2136"]
        code, status, _ = self.run_ddns(FakeNameserver(refuse=True), cfg)
        self.assertEqual(code, 1)
        self.assertEqual(status["records"]["home_A"]["action"], "failed")
        self.assertEqual(status["records"]["home_A"]["providers"]["gandi"]["action"], "updated")


TS4 = "100.93.155.101"
S3 = f"s3.home.{ZONE}"


def static_public(a=(TS4,), aaaa=()):
    public = current_public(NEW4, NEW6)
    public[(S3, "A")] = list(a)
    public[(S3, "AAAA")] = list(aaaa)
    return public


class StaticRecordTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(ddns.Rfc2136Backend, "command", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def cfg(self, static=None, **overrides):
        base = config(provider="rfc2136",
                      rfc2136={"server": "192.0.2.53", "key_name": "ddns-home"},
                      static_records=static if static is not None
                      else [{"name": "s3.home", "a": [TS4], "aaaa": []}])
        base.update(overrides)
        return base

    def run_ddns(self, server, cfg, public=None, resolve=None):
        ddns.Rfc2136Backend.command = staticmethod(server)
        lines = []
        code, status = ddns.run(cfg, {"DDNS_TSIG_SECRET": TSIG}, http=FakeGandi(),
                                resolve=resolve or make_resolver(public or static_public()),
                                log=lines.append, now=lambda: 1_000_000)
        return code, status, lines

    def test_creates_explicit_name_over_the_wildcard(self):
        server = FakeNameserver(current_public(NEW4, NEW6))
        self.assertEqual(server.lookup(S3, "AAAA"), ("NOERROR", [NEW6]))
        code, status, lines = self.run_ddns(server, self.cfg())
        self.assertEqual(code, 0, status["errors"])
        self.assertEqual(server.records[(S3, "A")], [TS4])
        self.assertNotIn((S3, "AAAA"), server.records)
        self.assertEqual(server.lookup(S3, "AAAA"), ("NOERROR", []))
        # The A set is written first; the name then exists and AAAA reads back empty.
        self.assertEqual([u for u in server.updates if u[1] == S3], [("delete", S3, "A")])
        self.assertEqual(status["records"]["s3.home_A"]["action"], "updated")
        self.assertEqual(status["records"]["s3.home_AAAA"]["action"], "unchanged")
        self.assertTrue(status["records"]["s3.home_A"]["static"])
        self.assertEqual(status["records"]["s3.home_A"]["desired"], [TS4])
        self.assertNotIn("static", status["records"]["home_A"])
        self.assertEqual(status["summary"]["records_total"], 6)
        self.assertTrue(status["summary"]["public_ok"])
        self.assertIn(f"DDNS run: provider=rfc2136 zone={ZONE} names=home,*.home static=s3.home",
                      lines)
        # Other names keep following the wildcard.
        self.assertEqual(server.lookup(f"archive.home.{ZONE}", "A"), ("NOERROR", [NEW4]))
        self.assertEqual(server.records[(f"*.home.{ZONE}", "AAAA")], [NEW6])

    def test_second_run_writes_nothing(self):
        server = FakeNameserver(current_public(NEW4, NEW6))
        self.run_ddns(server, self.cfg())
        server.calls.clear()
        code, status, _ = self.run_ddns(server, self.cfg())
        self.assertEqual(code, 0)
        self.assertFalse([c for c in server.calls if c[0][0] == "nsupdate"])
        self.assertEqual(status["summary"]["records_updated"], 0)

    def test_repairs_drift_and_removes_an_unwanted_aaaa(self):
        records = current_public(NEW4, NEW6)
        records[(S3, "A")] = ["100.64.0.9"]
        records[(S3, "AAAA")] = [OLD6]
        server = FakeNameserver(records)
        code, status, _ = self.run_ddns(server, self.cfg())
        self.assertEqual(code, 0, status["errors"])
        self.assertEqual(server.records[(S3, "A")], [TS4])
        self.assertNotIn((S3, "AAAA"), server.records)
        self.assertEqual(status["records"]["s3.home_AAAA"]["action"], "updated")
        aaaa_update = [stdin for argv, stdin in server.calls
                       if argv[0] == "nsupdate" and f"{S3}. AAAA" in stdin][0]
        self.assertNotIn("update add", aaaa_update)

    def test_static_names_ignore_family_switches_and_wan_detection(self):
        server = FakeNameserver(current_public(NEW4, NEW6))
        records = [{"name": "s3.home", "a": [TS4], "aaaa": ["2001:DB8::0:1"]}]
        public = static_public(aaaa=["2001:db8::1"])
        code, status, _ = self.run_ddns(server, self.cfg(records, ipv6=False), public=public)
        self.assertEqual(code, 0, status["errors"])
        self.assertEqual(server.records[(S3, "AAAA")], ["2001:db8::1"])
        self.assertNotIn("home_AAAA", status["records"])

    def test_public_view_needs_empty_answers_from_every_nameserver(self):
        server = FakeNameserver(current_public(NEW4, NEW6))
        public = static_public()

        def resolve(name, rtype, ns):
            if rtype == "NS":
                return ["ns-a.example.", "ns-b.example."]
            if (name, rtype) == (S3, "AAAA") and ns == "ns-b.example.":
                return None  # failed query, e.g. SERVFAIL
            return public.get((name, rtype))

        code, status, _ = self.run_ddns(server, self.cfg(), resolve=resolve)
        self.assertEqual(code, 0)
        self.assertFalse(status["records"]["s3.home_AAAA"]["public_ok"])
        self.assertTrue(status["records"]["s3.home_A"]["public_ok"])
        self.assertFalse(status["summary"]["public_ok"])
        _, status, _ = self.run_ddns(server, self.cfg(), public=static_public(aaaa=[NEW6]))
        self.assertFalse(status["records"]["s3.home_AAAA"]["public_ok"])

    def test_invalid_entries_fail_the_run_and_valid_ones_still_apply(self):
        bad = [
            {"name": "home", "a": [TS4], "aaaa": []},
            {"name": "*.x.home", "a": [TS4], "aaaa": []},
            {"name": "v6.home", "a": [NEW6], "aaaa": []},
            {"name": "v4.home", "a": [], "aaaa": [TS4]},
            {"name": "empty.home", "a": [], "aaaa": []},
            {"name": "bad.home", "a": "100.64.0.1", "aaaa": []},
            {"name": "extra.home", "a": [TS4], "aaaa": [], "ttl": 5},
            {"name": "noaaaa.home", "a": [TS4]},
            {"name": "s3.home.", "a": [TS4], "aaaa": []},
            {"name": "s3.home", "a": [TS4], "aaaa": []},
            {"name": "S3.HOME", "a": [TS4], "aaaa": []},
            "s3.home",
        ]
        server = FakeNameserver(current_public(NEW4, NEW6))
        code, status, _ = self.run_ddns(server, self.cfg(bad))
        self.assertEqual(code, 1)
        self.assertEqual(len(status["errors"]), len(bad) - 1, status["errors"])
        self.assertEqual(server.records[(S3, "A")], [TS4])
        self.assertTrue(all(e.startswith("static_records[") for e in status["errors"]))
        code, status, _ = self.run_ddns(server, self.cfg({"name": "s3.home"}))
        self.assertEqual(code, 1)
        self.assertIn("static_records must be a list", status["errors"])

    def test_gandi_empty_set_is_a_delete(self):
        gandi = FakeGandi({("s3.home", "AAAA"): [NEW6], ("s3.home", "A"): [TS4]})
        original = gandi.__call__

        def http(method, url, headers, body):
            if method == "DELETE":
                gandi.calls.append((method, url, dict(headers), body))
                name, rtype = url[len(BASE) + 1:].rsplit("/", 1)
                gandi.records.pop((name, rtype), None)
                return 204, b""
            return original(method, url, headers, body)

        cfg = config(static_records=[{"name": "s3.home", "a": [TS4], "aaaa": []}])
        code, status = ddns.run(cfg, {"GANDI_API_TOKEN": SECRET}, http=http,
                                resolve=make_resolver(static_public()), log=lambda _l: None,
                                now=lambda: 1)
        self.assertEqual(code, 0, status["errors"])
        self.assertNotIn(("s3.home", "AAAA"), gandi.records)
        self.assertEqual([c[0] for c in gandi.calls if "s3.home" in c[1]],
                         ["GET", "GET", "DELETE", "GET"])


class ParseDigTests(unittest.TestCase):
    def test_statuses(self):
        answer = dig_output("NOERROR", S3, "AAAA", [NEW6])
        self.assertEqual(ddns.parse_dig(answer, "AAAA", authoritative=True), [NEW6])
        self.assertEqual(ddns.parse_dig(answer, "A", authoritative=True), [])
        nodata = dig_output("NOERROR", S3, "AAAA")
        self.assertEqual(ddns.parse_dig(nodata, "AAAA", authoritative=True), [])
        self.assertEqual(ddns.parse_dig(dig_output("NXDOMAIN"), "A", authoritative=True), [])
        for status in ("SERVFAIL", "REFUSED", "NOTAUTH", "FORMERR"):
            with self.subTest(status=status), self.assertRaises(ddns.DdnsError):
                ddns.parse_dig(dig_output(status), "A", authoritative=False)
        with self.assertRaises(ddns.DdnsError):
            ddns.parse_dig(";; connection timed out; no servers could be reached\n", "A", False)
        with self.assertRaises(ddns.DdnsError):
            ddns.parse_dig("", "A", False)

    def test_authoritative_flag(self):
        recursive = dig_output("NOERROR", ZONE, "NS", ["ns1.example.", "ns2.example."], aa=False)
        self.assertEqual(ddns.parse_dig(recursive, "NS", authoritative=False),
                         ["ns1.example", "ns2.example"])
        with self.assertRaises(ddns.DdnsError):
            ddns.parse_dig(recursive, "NS", authoritative=True)

    def test_cname_and_tcp_retry(self):
        output = (";; Truncated, retrying in TCP mode.\n"
                  + dig_output("NOERROR", S3, "A", [TS4]).replace(
                      ";; ANSWER SECTION:\n",
                      f";; ANSWER SECTION:\n{S3}.\t300\tIN\tCNAME\tother.example.\n"))
        self.assertEqual(ddns.parse_dig(output, "A", authoritative=True), [TS4])

    def test_dig_helper_maps_failures_to_none(self):
        def fake_run(stdout, code=0):
            return mock.Mock(returncode=code, stdout=stdout, stderr="")

        with mock.patch.object(ddns.subprocess, "run",
                               return_value=fake_run(dig_output("REFUSED"))) as run:
            self.assertIsNone(ddns.dig(S3, "AAAA", "ns1.example."))
        argv = run.call_args.args[0]
        self.assertEqual(argv[-2:], [S3, "AAAA"])
        self.assertIn("+norecurse", argv)
        with mock.patch.object(ddns.subprocess, "run",
                               return_value=fake_run(dig_output("NOERROR", S3, "AAAA"))):
            self.assertEqual(ddns.dig(S3, "AAAA", "ns1.example."), [])
        with mock.patch.object(ddns.subprocess, "run",
                               return_value=fake_run(dig_output("NOERROR", S3, "AAAA"), 9)):
            self.assertIsNone(ddns.dig(S3, "AAAA", "ns1.example."))


class TemplateTests(unittest.TestCase):
    def render(self, name, **variables):
        env = Environment(undefined=StrictUndefined, trim_blocks=True, keep_trailing_newline=True)
        env.filters["to_nice_json"] = lambda v: json.dumps(v, indent=4, sort_keys=True)
        env.filters["bool"] = bool
        env.filters["dirname"] = lambda p: str(Path(p).parent)
        return env.from_string((ROLE / "templates" / name).read_text()).render(**variables)

    def test_config_template_renders_names_and_scheme(self):
        rendered = json.loads(self.render(
            "ddns-config.json.j2",
            dns_ddns_provider="gandi", dns_ddns_domain="wersdörfer.de",
            dns_ddns_subdomain="home", dns_ddns_update_wildcard=True, dns_ddns_ttl=300,
            dns_ddns_ipv4_enabled=True, dns_ddns_ipv6_enabled=True,
            dns_ddns_ipv4_source_url="https://ipv4.icanhazip.com",
            dns_ddns_ipv6_source_url="https://ipv6.icanhazip.com",
            dns_ddns_verify_nameservers=[], dns_ddns_status_path="/var/lib/ddns/status.json",
            dns_ddns_log_dir="/var/log/ddns", dns_ddns_log_max_size_mb=10,
            dns_ddns_gandi_auth_scheme="apikey",
            dns_ddns_gandi_api_base="https://api.gandi.net/v5/livedns",
            dns_ddns_effective_providers=["gandi"],
            dns_ddns_rfc2136_server="CHANGEME", dns_ddns_rfc2136_port=53,
            dns_ddns_rfc2136_key_name="CHANGEME", dns_ddns_rfc2136_key_algorithm="hmac-sha256",
            dns_ddns_rfc2136_update_zone="",
            dns_ddns_static_records=[{"name": "s3.home", "a": [TS4], "aaaa": []}],
        ))
        self.assertEqual(rendered["static_records"],
                         [{"name": "s3.home", "a": [TS4], "aaaa": []}])
        self.assertEqual(rendered["names"], ["home", "*.home"])
        self.assertEqual(rendered["providers"], ["gandi"])
        self.assertEqual(rendered["gandi"]["auth_scheme"], "apikey")
        self.assertNotIn("api_token", json.dumps(rendered))

    def test_main_writes_status_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.json"
            status_path = Path(tmp) / "status.json"
            cfg_path.write_text(json.dumps(config(provider="nope", status_path=str(status_path),
                                                  log_file=str(Path(tmp) / "log"))))
            with mock.patch.object(ddns, "http_request", FakeGandi({})), \
                    mock.patch.object(ddns, "dig", make_resolver({})):
                self.assertEqual(ddns.main(["--config", str(cfg_path)]), 1)
            self.assertFalse(json.loads(status_path.read_text())["summary"]["run_ok"])


if __name__ == "__main__":
    unittest.main()
