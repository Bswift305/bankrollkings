# Platform Doctrine — version pins

Append-only. One row per owner-approved version. A doctrine file whose SHA-256 does not match its row has been
edited without approval. Changing the doctrine means a new version, a new file and a new row, never an edit to an
existing row or file.

| Version | File | SHA-256 (committed bytes, LF) | Git blob | Recorded in commit | Approved |
|---|---|---|---|---|---|
| v1 (`PLATFORM-DOCTRINE-1`) | `docs/platform_doctrine_v1.md` | `40fe2dc69082fe792f4dfbd851c54d165a17b517c8a68a43f15ce3ee59527d56` | `517f25d50e22b1cf46d46f3d7937f85551bfeec8` | `2b22b83d22b788969d579c459a9ec292249f485d` | Owner, 2026-11-09 |
| v1.1 (`PLATFORM-DOCTRINE-1.1`) — current | `docs/platform_doctrine_v1_1.md` | `07f37a1ef132adfc28dd1bd5bb2cd2a9cc8cbb6b6492c3e91f62e0a86650b6de` | `5bcd73791363a5f5b5fa96415b63cdeaa6a6e68d` | `cb7913dcbe65fc38f62dea7cc33484c8f4819142` | Owner, 2026-11-09 (Q1/Q2/Q6/Q12 corrections; recommendation interpretation confirmed) |

Verify:

```bash
git show 2b22b83d22b788969d579c459a9ec292249f485d:docs/platform_doctrine_v1.md | sha256sum
git show cb7913dcbe65fc38f62dea7cc33484c8f4819142:docs/platform_doctrine_v1_1.md | sha256sum
```
