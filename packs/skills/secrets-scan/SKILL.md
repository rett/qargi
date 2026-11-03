---
name: secrets-scan
description: Before you report, scan your commits with a secret scanner if one is installed, and quote its verdict line among the gates.
---
# Secret scan

- If a secret scanner is installed (for example gitleaks: `gitleaks git --log-opts BASE_SHA..HEAD`), run it over your commits before the report. Quote its verdict line in `gates[]`.
- None installed: gate `not run`, with the reason.
- A hit: remove the secret from the commits and report its kind, never its value.
- A pass is a hint. The lead scans again.
