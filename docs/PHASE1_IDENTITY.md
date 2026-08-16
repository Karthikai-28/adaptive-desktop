# Phase 1 — Adaptive Files identity isolation

Production direction:

- preserve Nautilus 42.6 file-management behavior;
- preserve GIO/GVfs/Tracker/MIME/Trash semantics;
- preserve the Nautilus 3.0 extension ABI while we are on Nautilus 42;
- give the development fork its own GApplication identity;
- do not make it the system default yet.

## Application ID

Development application ID:

`com.karthi.AdaptiveFiles`

The patcher intentionally does not globally replace `org.gnome.Nautilus`.

That would be unsafe because identifiers in the source tree have different
roles: application identity, GSettings schemas, standard D-Bus interfaces,
desktop files, search providers and extension ABI.

## Standard FileManager1 interface

`org.freedesktop.FileManager1` is preserved in Phase 1.

The first goal is to prove that the fork has a separate GApplication identity
and still behaves like Nautilus. If side-by-side execution exposes an ownership
conflict around FileManager1, Phase 1.1 will isolate only the development
service ownership while keeping the standard interface for production.

## Acceptance gate

Phase 1 passes when:

1. the build completes;
2. the installed binary is the local Nautilus 42.6 fork;
3. the local build contains `com.karthi.AdaptiveFiles`;
4. double-click, tabs, search, Trash, mounts and network behavior still work;
5. stock `/usr/bin/nautilus` remains installed and recoverable.

Only after this gate do visual modifications begin.
