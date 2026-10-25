import unittest
from unittest.mock import Mock, patch

from szu_sentinel.security import (
    SecurityAuditResult,
    audit_security,
    get_firewall_profiles_status,
    is_lan_shield_active,
)


class SecurityTests(unittest.TestCase):
    @patch("szu_sentinel.security.get_default_gateway_and_if_index")
    @patch("szu_sentinel.security.query_live_gateway_mac")
    @patch("szu_sentinel.security.get_cached_gateway_mac_and_type")
    @patch("szu_sentinel.security.get_firewall_profiles_status")
    @patch("szu_sentinel.security.is_lan_shield_active")
    def test_audit_detects_arp_spoofing(
        self,
        mock_shield,
        mock_fw,
        mock_cached,
        mock_live,
        mock_gw,
    ):
        mock_gw.return_value = ("172.30.48.1", 13)
        mock_live.return_value = "70-f9-6d-70-34-8f"
        mock_cached.return_value = ("aa-bb-cc-dd-ee-ff", "dynamic")
        mock_fw.return_value = {"Private": True, "Public": True}
        mock_shield.return_value = True

        report = audit_security()
        self.assertTrue(report.arp_spoofed)
        self.assertEqual(report.risk_level, "DANGER")
        self.assertIn("ARP", report.summary)

    @patch("szu_sentinel.security.get_default_gateway_and_if_index")
    @patch("szu_sentinel.security.query_live_gateway_mac")
    @patch("szu_sentinel.security.get_cached_gateway_mac_and_type")
    @patch("szu_sentinel.security.get_firewall_profiles_status")
    @patch("szu_sentinel.security.is_lan_shield_active")
    def test_audit_reports_safe_when_shield_active(
        self,
        mock_shield,
        mock_fw,
        mock_cached,
        mock_live,
        mock_gw,
    ):
        mock_gw.return_value = ("172.30.48.1", 13)
        mock_live.return_value = "70-f9-6d-70-34-8f"
        mock_cached.return_value = ("70-f9-6d-70-34-8f", "static")
        mock_fw.return_value = {"Private": True, "Public": True}
        mock_shield.return_value = True

        report = audit_security()
        self.assertFalse(report.arp_spoofed)
        self.assertEqual(report.risk_level, "SAFE")
        self.assertEqual(report.arp_type, "static")
        self.assertIn("防护正常运行中", report.summary)

    @patch("szu_sentinel.security.get_default_gateway_and_if_index")
    @patch("szu_sentinel.security.query_live_gateway_mac")
    @patch("szu_sentinel.security.get_cached_gateway_mac_and_type")
    @patch("szu_sentinel.security.get_firewall_profiles_status")
    @patch("szu_sentinel.security.is_lan_shield_active")
    def test_audit_reports_warning_when_firewall_off(
        self,
        mock_shield,
        mock_fw,
        mock_cached,
        mock_live,
        mock_gw,
    ):
        mock_gw.return_value = ("172.30.48.1", 13)
        mock_live.return_value = "70-f9-6d-70-34-8f"
        mock_cached.return_value = ("70-f9-6d-70-34-8f", "dynamic")
        mock_fw.return_value = {"Private": False, "Public": True}
        mock_shield.return_value = False

        report = audit_security()
        self.assertFalse(report.arp_spoofed)
        self.assertEqual(report.risk_level, "WARNING")
        self.assertIn("445/135", report.summary)


if __name__ == "__main__":
    unittest.main()
