"""
Unit tests for FastAPI Endpoints and Moderation Pipeline.
"""

import unittest
from fastapi.testclient import TestClient
from api.server import app
from services.moderation import run_full_security_screening
from services.website_checker import check_website


class TestAPIAndModeration(unittest.IsolatedAsyncioTestCase):

    def test_fastapi_root_endpoint(self):
        client = TestClient(app)
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "online")
        self.assertEqual(data["service"], "Real Freelance Jobs Bot & Verification API")

    def test_fastapi_health_endpoint(self):
        client = TestClient(app)
        response = client.get("/health")
        self.assertIn(response.status_code, [200, 503])
        data = response.json()
        self.assertIn("status", data)
        self.assertIn("database", data)

    async def test_full_security_screening_scam_case(self):
        decision = await run_full_security_screening(
            company_name="Mega Quick Crypto Cash",
            company_website="http://bit.ly/fakejob",
            contact_email="hr@gmail.com",
            job_title="Typing Job - Earn $500 per day",
            job_description="Urgent hiring! 2 spots left. Pay $40 registration fee and send USDT to start.",
            payment_rate="$500/day",
            expected_work="Retyping documents",
            country_region="Worldwide",
            application_method="DM on Telegram",
        )
        self.assertIn(decision.risk_level, ["high", "very_high"])
        self.assertEqual(decision.action, "block_review")
        self.assertGreaterEqual(decision.final_score, 50.0)
        self.assertGreater(len(decision.all_flags), 0)

    async def test_full_security_screening_legit_case(self):
        decision = await run_full_security_screening(
            company_name="Python Software Foundation",
            company_website="https://python.org",
            contact_email="jobs@python.org",
            job_title="Software Engineer",
            job_description="Standard contract role for backend development with Python, Git, and automated testing.",
            payment_rate="$65/hr",
            expected_work="Design and implement software features.",
            country_region="Remote",
            application_method="Apply via jobs@python.org",
        )
        self.assertIn(decision.risk_level, ["low", "review"])
        self.assertLess(decision.final_score, 50.0)


if __name__ == "__main__":
    unittest.main()
