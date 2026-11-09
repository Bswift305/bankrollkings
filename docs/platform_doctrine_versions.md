# Platform Doctrine — version pins

Append-only. One row per owner-approved version. A doctrine file whose SHA-256 does not match its row has been
edited without approval. Changing the doctrine means a new version, a new file and a new row, never an edit to an
existing row or file.

| Version | File | SHA-256 (committed bytes, LF) | Git blob | Recorded in commit | Approved |
|---|---|---|---|---|---|
| v1 (`PLATFORM-DOCTRINE-1`) | `docs/platform_doctrine_v1.md` | `40fe2dc69082fe792f4dfbd851c54d165a17b517c8a68a43f15ce3ee59527d56` | `517f25d50e22b1cf46d46f3d7937f85551bfeec8` | `2b22b83d22b788969d579c459a9ec292249f485d` | Owner, 2026-11-09 |

Verify:

```bash
git show 2b22b83d22b788969d579c459a9ec292249f485d:docs/platform_doctrine_v1.md | sha256sum
```
