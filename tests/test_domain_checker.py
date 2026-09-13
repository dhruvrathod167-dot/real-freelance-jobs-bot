"""
Unit tests for Domain & Website Checker.
"""

import unittest
from services.domain_checker import (
    extract_root_domain,
    is_url_shortener,
    check_domain_integrity,
)


class TestDomainChecker(unittest.TestCase):

    def test_extract_root_domain(self):
        self.assertEqual(extract_root_domain("www.example.com"), "example.com")
        self.assertEqual(extract_root_domain("careers.techcorp.io:443"), "careers.techcorp.io")
        self.assertEqual(extract_root_domain("https://www.google.com/jobs"), "google.com")

    def test_url_shortener_detection(self):
        self.assertTrue(is_url_shortener("https://bit.ly/3xJobLink"))
        self.assertTrue(is_url_shortener("http://tinyurl.com/fast-cash"))
        self.assertFalse(is_url_shortener("https://careers.google.com"))

    def test_free_email_corporate_mismatch(self):
        flags, risk = check_domain_integrity(
            company_website="https://microsoft.com",
            contact_email="hiring.hr@gmail.com",
            company_name="Microsoft"
        )
        self.assertGreater(risk, 0)
        self.assertTrue(any("free/public provider" in f for f in flags))

    def test_domain_mismatch_detection(self):
        flags, risk = check_domain_integrity(
            company_website="https://acmecorp.com",
            contact_email="recruiter@fakejobsportal.xyz",
            company_name="Acme Corp"
        )
        self.assertGreater(risk, 0)
        self.assertTrue(any("mismatch" in f.lower() for f in flags))

    def test_valid_corporate_domain_match(self):
        flags, risk = check_domain_integrity(
            company_website="https://stripe.com",
            contact_email="talent@stripe.com",
            company_name="Stripe"
        )
        self.assertEqual(risk, 0.0)
        self.assertEqual(len(flags), 0)


if __name__ == "__main__":
    unittest.main()
