"use client";

// Tracks whether the user has navigated within the SPA since the last full page load. A "← 戻る"
// control uses this to decide between router.back() and a parent-route fallback: firing
// router.back() blindly on a deep-link or hard refresh would eject the user out of the app (or do
// nothing), which is exactly the "can't go back, have to re-open from the menu" complaint. The
// counter lives in module scope, so it naturally resets to 0 on every full page load — precisely
// when there is no in-app history to pop.
let inAppNavigations = 0;

/** Call once per in-app route change (AppShell), skipping the initial mount. */
export function noteInAppNavigation(): void {
  inAppNavigations += 1;
}

/** True when router.back() has a real in-app screen to return to. */
export function canGoBackInApp(): boolean {
  return inAppNavigations > 0;
}
