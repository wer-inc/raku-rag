"""Tier B — domain-table RLS parity for 010/003/006.

GAP-F14: the static SQL contract already asserts ENABLE/FORCE RLS, but this test exercises live
Postgres policies for industry framework, real-estate, and investment domain tables. It is skipped
unless the domain migrations have been applied to the Postgres target.
"""

from __future__ import annotations

import os
from uuid import uuid4
import unittest

DSN = os.environ.get("POSTGRES_URL", "postgresql://raku:raku@127.0.0.1:5432/raku_parity")


def _postgres_domain_tables_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema='public' "
                    "AND table_name IN ("
                    "'industry_profiles','real_estate_properties','investment_funds'"
                    ")"
                )
                return cur.fetchone()[0] == 3
    except Exception:
        return False


@unittest.skipUnless(
    _postgres_domain_tables_available(),
    "Domain Postgres tables not reachable (Tier B / domain migrations required)",
)
class TestDomainTableRls(unittest.TestCase):
    def setUp(self) -> None:
        import psycopg

        self.conn = psycopg.connect(DSN, autocommit=True)
        self.addCleanup(self.conn.close)
        self.suffix = uuid4().hex[:10]
        self.tenant_a = f"rls_domain_a_{self.suffix}"
        self.tenant_b = f"rls_domain_b_{self.suffix}"

    def test_industry_profiles_are_tenant_isolated_with_system_visibility(self) -> None:
        profile_a = f"profile_a_{self.suffix}"
        profile_b = f"profile_b_{self.suffix}"
        with self.conn.cursor() as cur:
            self._set_tenant(cur, self.tenant_a)
            cur.execute(
                "INSERT INTO industry_profiles "
                "(profile_id, tenant_id, industry_id, name, description) "
                "VALUES (%s, %s, 'real_estate_pm', 'A', '')",
                (profile_a, self.tenant_a),
            )
            self._set_tenant(cur, self.tenant_b)
            cur.execute(
                "INSERT INTO industry_profiles "
                "(profile_id, tenant_id, industry_id, name, description) "
                "VALUES (%s, %s, 'investment_management', 'B', '')",
                (profile_b, self.tenant_b),
            )

            self._set_tenant(cur, self.tenant_a)
            cur.execute(
                "SELECT count(*) FROM industry_profiles WHERE profile_id = %s", (profile_a,)
            )
            self.assertEqual(cur.fetchone()[0], 1)
            cur.execute(
                "SELECT count(*) FROM industry_profiles WHERE profile_id = %s", (profile_b,)
            )
            self.assertEqual(cur.fetchone()[0], 0)

    def test_real_estate_domain_tables_are_tenant_isolated(self) -> None:
        prop_a = f"prop_a_{self.suffix}"
        prop_b = f"prop_b_{self.suffix}"
        with self.conn.cursor() as cur:
            self._set_tenant(cur, self.tenant_a)
            cur.execute(
                "INSERT INTO real_estate_properties (property_id, tenant_id, property_name) "
                "VALUES (%s, %s, 'A')",
                (prop_a, self.tenant_a),
            )
            self._set_tenant(cur, self.tenant_b)
            cur.execute(
                "INSERT INTO real_estate_properties (property_id, tenant_id, property_name) "
                "VALUES (%s, %s, 'B')",
                (prop_b, self.tenant_b),
            )

            self._assert_visible_only_to_tenant_a(
                cur, "real_estate_properties", "property_id", prop_a, prop_b
            )

    def test_investment_domain_tables_are_tenant_isolated(self) -> None:
        fund_a = f"fund_a_{self.suffix}"
        fund_b = f"fund_b_{self.suffix}"
        with self.conn.cursor() as cur:
            self._set_tenant(cur, self.tenant_a)
            cur.execute(
                "INSERT INTO investment_funds (fund_id, tenant_id, fund_name) "
                "VALUES (%s, %s, 'A')",
                (fund_a, self.tenant_a),
            )
            self._set_tenant(cur, self.tenant_b)
            cur.execute(
                "INSERT INTO investment_funds (fund_id, tenant_id, fund_name) "
                "VALUES (%s, %s, 'B')",
                (fund_b, self.tenant_b),
            )

            self._assert_visible_only_to_tenant_a(
                cur, "investment_funds", "fund_id", fund_a, fund_b
            )

    def _set_tenant(self, cur, tenant_id: str) -> None:
        cur.execute("SET ROLE raku_app")
        cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (tenant_id,))

    def _assert_visible_only_to_tenant_a(
        self, cur, table: str, key_column: str, key_a: str, key_b: str
    ) -> None:
        self._set_tenant(cur, self.tenant_a)
        cur.execute(f"SELECT count(*) FROM {table} WHERE {key_column} = %s", (key_a,))
        self.assertEqual(cur.fetchone()[0], 1)
        cur.execute(f"SELECT count(*) FROM {table} WHERE {key_column} = %s", (key_b,))
        self.assertEqual(cur.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
