# Review of the user's existing installers/updaters

Read-only reference checkouts: MeetleJuice/friendly-bassoon (Aigentics) and
MeetleJuice/repos (Idea Foundry). Neither reference repository was modified.

Useful existing patterns:
- Foundry bootstrap.py and desktop_launcher.py keep a stable private launcher,
  independently observe startup, preserve original fallback, and retain bounded
  metadata diagnostics. forge/updates.py verifies a complete immutable ZIP and
  retains the previous version while preserving user data.
- Aigentics packaging/installer.iss uses a per-user installation, custom Desktop
  icon and explicit restart for in-app upgrades. aigentics/updates.py verifies
  downloaded installers. Its Windows gate tests real installed shortcuts,
  previous-version data preservation and public updater downloads.
- Aigentics maintenance/UPGRADE_0200_PLAN.md records two measured Windows runs
  timing out at12minutes while advancing from528to1045+checks, with no recorded
  assertion failure. The developer test allowance became18minutes inside a30minute
  job. A last-started test was explicitly not classified as the cause.
- The same repo's ENGINEERING_LOG.md and workflow retain stdout, native exit,
  test-count/slow-phase breadcrumbs and a bounded tail. Frequent progress belongs
  in ordinary logs so annotations cannot hide actual failures.

AASS keeps its stdlib GUI and the user's ZIP/double-click flow rather than adding
an unrelated framework or a new executable installer. Its permanent per-user
root, custom icon, full-release validation, settings preservation and rollback
already implement the same installation goals. Its backup engine is loaded
before importing an interrupted new source tree. Dependency wheels are reused
when their lock/interpreter identity is unchanged.

Applied reference lesson: preserve CI stdout and a parameter-free last-started
breadcrumb, expose bounded failure tails in a separate always-run step, and use
an explicit Windows test window of18minutes within30minutes. The independent
per-test monitor remains bounded. No application/model runtime budget, assertion,
Windows installer/icon/browser check or release scan gate is relaxed. AASS timing
and actual failures must be recorded independently rather than inferred from the
other application's timing. User API keys/models/GPU remain untested by CI.
