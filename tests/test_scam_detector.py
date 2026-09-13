"""
Unit tests for Heuristic Scam Detection Engine.
Verifies transparent risk scoring, strong scam indicators, composite combination detection,
and non-defamatory HIGH RISK / REVIEW REQUIRED classifications.
"""

import unittest
from services.scam_detector import scan_job_heuristics, compute_content_hash


class TestScamDetector(unittest.TestCase):

    def test_clean_legitimate_job(self):
        """A genuine job posting should have 0 or very low risk."""
        result = scan_job_heuristics(
            job_title="Senior Python Backend Developer",
            job_description=(
                "We are looking for an experienced Python developer to assist with building "
                "RESTful APIs and microservices. Must have 3+ years experience with FastAPI, "
                "PostgreSQL, and Docker. Contract duration: 3 months with extension potential."
            ),
            payment_rate="$50 - $70/hr",
            expected_work="Build API endpoints, write automated tests, participate in code reviews.",
            application_method="Submit resume and GitHub profile to jobs@examplecorp.com",
        )
        self.assertEqual(result.risk_level, "low")
        self.assertLessEqual(result.risk_score, 20.0)
        self.assertEqual(len(result.flags), 0)
        self.assertTrue(result.auto_publish_allowed)
        self.assertEqual(result.classification, "LOW RISK")

    def test_upfront_fee_detection(self):
        """Detects upfront registration, training, or equipment fee extortion."""
        result = scan_job_heuristics(
            job_title="Virtual Assistant",
            job_description=(
                "Work from home assistant. Candidate must pay a mandatory registration fee "
                "of $50 for onboarding materials and buy laptop from our certified vendor."
            ),
            payment_rate="$30/hr",
            expected_work="Administrative tasks and calendar management.",
            application_method="Contact telegram manager",
        )
        self.assertIn(result.risk_level, ["high", "very_high"])
        self.assertGreater(result.risk_score, 50.0)
        flags_str = " ".join(result.flags).lower()
        self.assertTrue("registration" in flags_str or "fee" in flags_str or "equipment" in flags_str)

    def test_crypto_only_scam_detection(self):
        """Detects untraceable cryptocurrency payment schemes."""
        result = scan_job_heuristics(
            job_title="Crypto Data Reviewer",
            job_description="Deposit crypto into our wallet to unlock daily commission tasks. Daily payout in USDT TRC20.",
            payment_rate="500 USDT per day",
            expected_work="Perform daily review tasks.",
            application_method="DM on Telegram",
        )
        self.assertGreaterEqual(result.risk_score, 50.0)
        flags_str = " ".join(result.flags).lower()
        self.assertTrue("usdt" in flags_str or "crypto" in flags_str)

    def test_credential_phishing_detection(self):
        """Detects critical requests for OTP, SMS verification code, or seed phrases."""
        result = scan_job_heuristics(
            job_title="Account Manager",
            job_description="Please provide your Telegram OTP verification code and your wallet seed phrase to verify identity.",
            payment_rate="$1000/week",
            expected_work="Manage social media accounts.",
            application_method="Email us",
        )
        self.assertIn(result.risk_level, ["high", "very_high"])
        self.assertGreaterEqual(result.risk_score, 65.0)
        flags_str = " ".join(result.flags).lower()
        self.assertTrue("otp" in flags_str or "seed" in flags_str)

    def test_unrealistic_salary_promise(self):
        """Detects exorbitant compensation for low skill retyping tasks."""
        result = scan_job_heuristics(
            job_title="Simple Data Entry / Typing Job",
            job_description="Earn easy money! Retyping simple PDF pages into Word documents. Guaranteed income.",
            payment_rate="$500 per day",
            expected_work="Typing 3 pages per day.",
            application_method="Apply now",
        )
        self.assertGreaterEqual(result.risk_score, 20.0)
        flags_str = " ".join(result.flags).lower()
        self.assertTrue("compensation" in flags_str or "typing" in flags_str or "guaranteed" in flags_str)

    def test_content_hashing_consistency(self):
        """Verifies content hash is deterministic and whitespace-insensitive."""
        text1 = "Senior Developer $50/hr Remote"
        text2 = "  senior   developer   $50/hr   remote  "
        self.assertEqual(compute_content_hash(text1), compute_content_hash(text2))

    # =========================================================================
    # SPECIFIC REQUIRED TESTS: 1. Registration Fee
    # =========================================================================
    def test_registration_fee_scam(self):
        """1. Registration fee: Substantially increases risk score, flags High Risk / Review Required."""
        result = scan_job_heuristics(
            job_title="Remote Administrative Assistant",
            job_description="We are seeking an assistant for data support. Candidate must pay a mandatory registration fee of $45 for processing.",
            payment_rate="$30/hr",
            expected_work="Schedule meetings and organize emails.",
            application_method="Apply via email",
        )
        self.assertIn(result.risk_level, ["high", "very_high"])
        self.assertGreaterEqual(result.risk_score, 70.0)
        self.assertFalse(result.auto_publish_allowed)
        self.assertEqual(result.classification, "HIGH RISK / REVIEW REQUIRED")
        flags_str = " ".join(result.flags).lower()
        self.assertTrue("registration" in flags_str or "fee" in flags_str)

    # =========================================================================
    # SPECIFIC REQUIRED TESTS: 2. Unrealistic Salary
    # =========================================================================
    def test_unrealistic_salary_scam(self):
        """2. Unrealistic salary: Exorbitant compensation for simple copy/paste/typing substantially increases risk score."""
        result = scan_job_heuristics(
            job_title="Simple Data Entry / Typing Job",
            job_description="Earn easy money! Retyping simple PDF pages into Word documents. Guaranteed income and instant wealth.",
            payment_rate="$600 per day",
            expected_work="Typing 3 pages per day.",
            application_method="Apply now",
        )
        self.assertIn(result.risk_level, ["high", "very_high"])
        self.assertGreaterEqual(result.risk_score, 65.0)
        self.assertFalse(result.auto_publish_allowed)
        self.assertEqual(result.classification, "HIGH RISK / REVIEW REQUIRED")
        flags_str = " ".join(result.flags).lower()
        self.assertTrue("compensation" in flags_str or "typing" in flags_str or "guaranteed" in flags_str)

    # =========================================================================
    # SPECIFIC REQUIRED TESTS: 3. Pay-First Scam
    # =========================================================================
    def test_pay_first_scam(self):
        """3. Pay-first scam: Demands payment upfront before receiving work/tasks; substantially increases score."""
        result = scan_job_heuristics(
            job_title="Freelance Article Writer",
            job_description="High-paying writing opportunity. To prevent spam, all applicants must pay first to receive the job assignment.",
            payment_rate="$50 per article",
            expected_work="Write 2 articles per week.",
            application_method="Contact coordinator",
        )
        self.assertIn(result.risk_level, ["high", "very_high"])
        self.assertGreaterEqual(result.risk_score, 75.0)
        self.assertFalse(result.auto_publish_allowed)
        self.assertEqual(result.classification, "HIGH RISK / REVIEW REQUIRED")
        flags_str = " ".join(result.flags).lower()
        self.assertTrue("pay first" in flags_str or "advance fee" in flags_str)

    # =========================================================================
    # SPECIFIC REQUIRED TESTS: 4. Crypto Deposit
    # =========================================================================
    def test_crypto_deposit_scam(self):
        """4. Crypto deposit: Instructs worker to deposit cryptocurrency/USDT into wallet; substantially increases score."""
        result = scan_job_heuristics(
            job_title="Crypto Task Operator",
            job_description="Complete daily order reviews. You must deposit crypto into our wallet address to activate daily tasks.",
            payment_rate="300 USDT per day",
            expected_work="Click review buttons daily.",
            application_method="DM on Telegram",
        )
        self.assertIn(result.risk_level, ["high", "very_high"])
        self.assertGreaterEqual(result.risk_score, 70.0)
        self.assertFalse(result.auto_publish_allowed)
        self.assertEqual(result.classification, "HIGH RISK / REVIEW REQUIRED")
        flags_str = " ".join(result.flags).lower()
        self.assertTrue("crypto" in flags_str or "deposit" in flags_str or "wallet" in flags_str)

    # =========================================================================
    # SPECIFIC REQUIRED TESTS: 5. OTP/Password Request
    # =========================================================================
    def test_otp_password_request_scam(self):
        """5. OTP/password request: Requests authentication codes or credentials; substantially increases score."""
        result = scan_job_heuristics(
            job_title="Account Verification Assistant",
            job_description="Provide your Telegram OTP verification code and temporary account password to verify identity before hiring.",
            payment_rate="$40/hr",
            expected_work="Account setup and verification.",
            application_method="Email support@example.com",
        )
        self.assertIn(result.risk_level, ["high", "very_high"])
        self.assertGreaterEqual(result.risk_score, 75.0)
        self.assertFalse(result.auto_publish_allowed)
        self.assertEqual(result.classification, "HIGH RISK / REVIEW REQUIRED")
        flags_str = " ".join(result.flags).lower()
        self.assertTrue("otp" in flags_str or "password" in flags_str or "credential" in flags_str)

    # =========================================================================
    # SPECIFIC REQUIRED TESTS: 6. Multiple Combined Indicators
    # =========================================================================
    def test_multiple_combined_indicators(self):
        """6. Multiple combined indicators: Tests both multiple strong indicators and composite medium indicators."""
        # Case 6A: Multiple strong indicators present (e.g. registration fee + crypto deposit)
        multi_strong = scan_job_heuristics(
            job_title="VIP Crypto Analyst",
            job_description="Pay $50 registration fee and deposit crypto into our wallet address to unlock high-yield tasks.",
            payment_rate="$1000/day",
            expected_work="Trading review.",
            application_method="DM on Telegram",
        )
        self.assertEqual(multi_strong.risk_level, "very_high")
        self.assertGreaterEqual(multi_strong.risk_score, 85.0)
        self.assertGreaterEqual(multi_strong.strong_indicator_count, 2)
        self.assertFalse(multi_strong.auto_publish_allowed)
        self.assertTrue(any("MULTIPLE STRONG FRAUD INDICATORS" in f for f in multi_strong.flags))

        # Case 6B: Multiple medium-risk indicators combined (e.g. Telegram-only contact + urgent scarcity + masked shortener)
        multi_medium = scan_job_heuristics(
            job_title="Marketing Representative",
            job_description=(
                "Urgent hiring! Limited slots left, only 3 spots remaining, act now! "
                "No interview needed, direct hire without interview. Contact manager telegram only: "
                "http://bit.ly/fastapply"
            ),
            payment_rate="$35/hr",
            expected_work="Marketing outreach.",
            application_method="Contact on Telegram secret",
        )
        self.assertIn(multi_medium.risk_level, ["high", "very_high"])
        self.assertGreaterEqual(multi_medium.risk_score, 60.0)
        self.assertGreaterEqual(multi_medium.medium_indicator_count, 2)
        self.assertFalse(multi_medium.auto_publish_allowed)
        self.assertEqual(multi_medium.classification, "HIGH RISK / REVIEW REQUIRED")
        self.assertTrue(any("COMBINATION RISK" in f for f in multi_medium.flags))


if __name__ == "__main__":
    unittest.main()
