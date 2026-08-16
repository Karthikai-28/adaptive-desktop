# Legacy phase and version scripts

`scripts/` holds 88 scripts, 49 of them from earlier phase/version pushes. This
document says which are current, which exist only for rollback, and which are
obsolete, so nobody has to guess from a filename.

**Nothing here is deleted.** Obsolete scripts are kept because they document how
the system reached its current state and because some encode recovery steps that
are still the fastest way out of a bad session.

Classified by what each script actually targets, not by its name:

- scripts naming `adaptive-shell-v16@local` target the **retired duplicate**
  extension (canonical is `adaptive-shell@local`);
- scripts naming `apps/adaptive-files` or `adaptive-files-launch*` target the
  **retired standalone GTK4 app** (canonical is the forked Nautilus).

## CURRENT — the canonical workflow

```text
sync-shell.sh                        repo -> live extension
reload-adaptive-shell.sh             reload, with --restart-shell on X11
install-adaptive-session.sh          session wrapper, GDM entry, dconf profile
install-files-session-integration.sh D-Bus activation for the file manager
adaptive-files-dispatch.sh           picks fork vs stock Nautilus per session
install-project-context-service.sh   project registry service
project-context-autostart.sh         session-guarded autostart wrapper
install-keybindings.sh               shortcuts
build-nautilus-fork.sh               builds the fork
install-nautilus-fork-local.sh       installs it to the repo-local prefix
prepare-nautilus-fork.sh             fetches Ubuntu's Nautilus source
verify-*.sh / verify-*.py            verification suites
record-live-verification.py          physical-check ledger
*-cli.py                             project / focus / window / appearance / session
```

## LEGACY — kept for rollback only

Referenced by the recovery documentation. Do not run casually; they target the
retired extension UUID and will re-enable a second rail.

```text
rollback-v1.6.sh
rollback-v1.6.1.sh
rollback-complete-v1.5.sh
rollback-calendar-center-v1.6.2.sh
phase2.2-rollback.sh
phase2.1-uninstall-preview.sh
phase2-uninstall-visual-layer.sh
phase1-audit-identity.sh             still useful as a read-only fork audit
```

## OBSOLETE — historical record

These install, verify, or patch things that no longer exist: the retired v16
extension, the standalone Adaptive Files app, or per-user
`org.gnome.Nautilus.desktop` routing that the dispatcher replaced.

```text
install-v1.6.sh                      install-v1.6.1.sh
verify-v1.6.sh                       verify-v1.6.1.sh
diagnose-v1.6.sh                     diagnose-v1.6.1.sh
stage-shell-v1.6.1.sh                post-login-v1.6.1.sh
install-file-routing-v1.6.sh         test-files-route-v1.6.1.sh
install-calendar-center-v1.6.2.sh    verify-calendar-center-v1.6.2.sh
complete-install-v1.5.sh             verify-complete-v1.5.sh
hotfix-v06-double-click.py           hotfix-v06-storage-readable.py
phase1-isolate-identity.py           phase1-verify-identity.sh
phase1-rebuild-adaptive-files.sh     phase1-run-adaptive-files.sh
phase2*.sh (visual/preview phases, 2.1 through 2.5)
```

Two worth calling out:

- `phase1-isolate-identity.py` would rename the fork's application id to
  `com.karthi.AdaptiveFiles`. It was **never applied** — the build carries
  `APPLICATION_ID "org.gnome.Nautilus"`, which is exactly what lets the fork be
  the session's file manager instead of a second one competing with it. Running
  it now would undo that.
- `install-calendar-center-v1.6.2.sh` patched the retired extension. The
  calendar styling that ships today lives in `adaptive-shell@local/stylesheet.css`.

## Going forward

New work belongs in the canonical scripts above, not in another `v1.x`
installer chain. The repository is the source of truth; a versioned patch script
is only justified when a self-contained user-deliverable package is needed.
