"""
Unit tests for /myid, Monetization Architecture, and SUSPICIOUS User Workflow.
"""

import unittest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from database.models import Base, User, Job, EmployerProfile
from database.crud import (
    get_or_create_user,
    confirm_user_rules,
    set_user_status,
    flag_user_suspicious,
    create_job_submission,
    set_job_tier,
    upsert_employer_profile,
    get_employer_profile,
)
from utils.formatters import (
    format_my_id_card,
    format_monetization_card,
    format_job_card,
    format_user_verification_status,
    COMMUNITY_SAFETY_DISCLAIMER,
)


class TestMonetizationAndMyId(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()

    def test_format_my_id_card(self):
        """Verifies /myid format includes monospace code block and correct admin indicator."""
        card_member = format_my_id_card(
            user_id=12345678,
            first_name="Jane",
            last_name="Doe",
            username="janedoe",
            status="VERIFIED",
            risk_score=5.0,
            is_admin=False,
            chat_id=12345678,
            chat_type="private"
        )
        self.assertIn("<code>12345678</code>", card_member)
        self.assertIn("Standard Member", card_member)
        self.assertIn("Verified", card_member)

        card_admin = format_my_id_card(
            user_id=99999999,
            first_name="Admin",
            last_name="User",
            username="adminuser",
            status="VERIFIED",
            risk_score=0.0,
            is_admin=True,
            chat_id=99999999,
            chat_type="private"
        )
        self.assertIn("Authorized Administrator", card_admin)

    def test_format_monetization_card_anti_fraud_rules(self):
        """Verifies monetization card confirms basic services are 100% free with no fake unlock fees."""
        card = format_monetization_card()
        self.assertIn("100% free forever", card)
        self.assertIn("NEVER charge", card)
        self.assertIn("Featured Job Placement", card)
        self.assertIn("Sponsored Employer Listing", card)
        self.assertIn(COMMUNITY_SAFETY_DISCLAIMER, card)

    def test_format_job_card_badges(self):
        """Verifies featured and sponsored job cards display distinct badges."""
        card_std = format_job_card(
            job_id=1,
            company_name="Acme",
            job_title="Dev",
            payment_rate="$50/hr",
            country_region="Remote",
            expected_work="Code",
            job_description="Description",
            application_method="Email",
            is_featured=False,
            is_sponsored=False
        )
        self.assertIn("VERIFIED JOB OPPORTUNITY #1", card_std)

        card_feat = format_job_card(
            job_id=2,
            company_name="Acme",
            job_title="Dev",
            payment_rate="$50/hr",
            country_region="Remote",
            expected_work="Code",
            job_description="Description",
            application_method="Email",
            is_featured=True,
            is_sponsored=False
        )
        self.assertIn("[FEATURED OPPORTUNITY]", card_feat)

        card_spon = format_job_card(
            job_id=3,
            company_name="Acme",
            job_title="Dev",
            payment_rate="$50/hr",
            country_region="Remote",
            expected_work="Code",
            job_description="Description",
            application_method="Email",
            is_featured=False,
            is_sponsored=True
        )
        self.assertIn("[SPONSORED LISTING]", card_spon)

    def test_suspicious_status_card(self):
        """Verifies status card displays observation notice for SUSPICIOUS accounts."""
        text = format_user_verification_status(
            user_id=777,
            status="SUSPICIOUS",
            risk_score=65.0,
            submission_count=2,
            flag_notes="Elevated scam risk on prior post"
        )
        self.assertIn("Suspicious Account", text)
        self.assertIn("held for administrative review", text)

    async def test_suspicious_user_workflow(self):
        """Tests flagging a user as SUSPICIOUS and restoring to VERIFIED."""
        async with self.session_factory() as session:
            user = await get_or_create_user(session, user_id=456, first_name="Eve")
            await confirm_user_rules(session, user_id=456)
            await session.commit()
            self.assertEqual(user.status, "VERIFIED")

            # Flag suspicious
            flagged = await flag_user_suspicious(
                session=session,
                user_id=456,
                reason="Detected upfront fee pattern in job draft",
                risk_score=65.0,
                actor_id=1001
            )
            await session.commit()
            self.assertEqual(flagged.status, "SUSPICIOUS")
            self.assertEqual(flagged.risk_score, 65.0)

            # Unflag / restore
            restored = await set_user_status(
                session=session,
                user_id=456,
                status="VERIFIED",
                flag_notes="Admin cleared flags",
                actor_id=1001
            )
            await session.commit()
            self.assertEqual(restored.status, "VERIFIED")

    async def test_job_tier_and_employer_profile(self):
        """Tests updating job tier and managing employer profile."""
        async with self.session_factory() as session:
            await get_or_create_user(session, user_id=888, first_name="Dan")
            job = await create_job_submission(
                session=session,
                user_id=888,
                company_name="Corp Inc",
                company_website="https://corp.com",
                contact_email="hiring@corp.com",
                job_title="Lead Architect",
                job_description="Architect scalable services in Python.",
                payment_rate="$120/hr",
                expected_work="Technical leadership",
                country_region="Remote",
                application_method="Apply on portal",
                original_source="Direct",
                risk_score=5.0,
                risk_level="low",
                detected_flags=[],
                ai_analysis={"recommendation": "approve"},
            )
            await session.commit()

            # Set featured
            updated_job = await set_job_tier(
                session=session,
                job_id=job.id,
                is_featured=True,
                is_sponsored=False,
                listing_tier="featured",
                actor_id=1001
            )
            await session.commit()
            self.assertTrue(updated_job.is_featured)
            self.assertEqual(updated_job.listing_tier, "featured")

            # Create Employer Profile
            emp = await upsert_employer_profile(
                session=session,
                user_id=888,
                company_name="Corp Inc",
                official_domain="corp.com",
                tier="verified_employer",
                is_verified_business=True
            )
            await session.commit()
            self.assertTrue(emp.is_verified_business)
            self.assertEqual(emp.tier, "verified_employer")

            fetched = await get_employer_profile(session, user_id=888)
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.company_name, "Corp Inc")


if __name__ == "__main__":
    unittest.main()
