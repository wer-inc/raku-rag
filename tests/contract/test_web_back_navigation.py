"""0078 — source-level contract for universal, reliable "← 戻る" navigation.

apps/web has no TS unit runner, so this pins the back-navigation invariants at source level:
every non-root screen must expose a back control, the control must fall back to a parent route when
there is no in-app history (deep-link / hard refresh must not eject the user), and the state-based
phone detail sub-views must be dismissible. Same marker style as tests/contract/test_web_auth_recovery.py.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FULL_SAAS = ROOT / "apps/web/app/components/FullSaasScreen.tsx"
APP_SHELL = ROOT / "apps/web/app/components/AppShell.tsx"
NAV_HISTORY = ROOT / "apps/web/lib/nav-history.ts"


class WebBackNavigationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.full_saas = FULL_SAAS.read_text(encoding="utf-8")
        cls.app_shell = APP_SHELL.read_text(encoding="utf-8")
        cls.nav_history = NAV_HISTORY.read_text(encoding="utf-8")

    def test_nav_history_tracks_in_app_navigation(self) -> None:
        for marker in (
            "export function noteInAppNavigation",
            "export function canGoBackInApp",
            "inAppNavigations",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.nav_history)

    def test_app_shell_notes_navigation_after_first_mount(self) -> None:
        for marker in (
            "noteInAppNavigation",
            "navInitialized",
            "if (!AUTH_ROUTES.has(pathname)) noteInAppNavigation();",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.app_shell)

    def test_back_shown_on_every_non_root_screen(self) -> None:
        # Only the two home/landing screens are roots; everything else gets a back control.
        self.assertIn(
            'const ROOT_SCREEN_IDS = new Set(["answers", "home-dashboard"])', self.full_saas
        )
        self.assertIn("const showBack = !ROOT_SCREEN_IDS.has(screen.id);", self.full_saas)

    def test_back_falls_back_to_parent_route_without_history(self) -> None:
        # router.back() only when there is in-app history; otherwise push a real parent route so a
        # deep-link / refresh never dead-ends or ejects the user out of the app.
        for marker in (
            "if (canGoBackInApp()) router.back();",
            'else router.push(SCREEN_PARENT_HREF[screen.id] ?? "/home");',
            "const SCREEN_PARENT_HREF: Record<string, string>",
            '"document-detail": "/files"',
            '"review-detail": "/reviews"',
            '"source-detail": "/sources/list"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.full_saas)
        # The old unconditional router.back() gated to 3 ids must be gone.
        self.assertNotIn("BACK_AFFORDANCE_SCREEN_IDS", self.full_saas)

    def test_phone_detail_subviews_are_dismissible(self) -> None:
        for marker in (
            "onClick={() => setSelected(null)}",
            "onClick={() => setDetail(null)}",
            "detail-back-row",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.full_saas)

    def test_breadcrumb_trail_lets_user_jump_to_an_ancestor(self) -> None:
        # 0079: clickable ancestor trail (Home > parent list > current) so the user can jump to a
        # parent screen directly instead of reopening the sidebar menu.
        for marker in (
            "function breadcrumbAncestors",
            'className="topbar-breadcrumb"',
            'aria-label="パンくずリスト"',
            'aria-current="page"',
            "navLabelFor(parent)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.full_saas)


if __name__ == "__main__":
    unittest.main()
