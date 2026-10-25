# Security Policy

## Zero-Secret Design

Ariadne is built under a strict **Zero-Secret Principle**:
- **No keys in source control**: No API keys, tokens, or plaintext credentials are stored in repository files, configuration templates, or SQLite ledger databases.
- **Keychain protection**: For cloud model providers, API keys are stored in the designer's personal macOS Keychain. Settings status checks query Keychain item presence without returning the value. Authorized live dispatch reads the key into process memory for the provider request; the key is not exposed in status responses or logs.
- **Local decision security**: The designer's decision passphrase is never stored in plaintext; it is hashed using `scrypt` ($N=16384, r=8, p=1$) and written to a private, POSIX `0600`-protected file (`~/.config/urban-design/decision-key`).

---

## Reporting a Security Vulnerability

If you discover a security vulnerability in Ariadne, please **do not open a public issue**.

Instead, please report vulnerabilities privately:
1. Use **GitHub Private Vulnerability Reporting** if it is enabled by navigating to the **Security** tab of the repository and clicking **"Report a vulnerability"**.
2. Otherwise, contact the maintainer through the private security contact listed here (`yuchenghsieh@alumni.tudelft.nl`). If no private contact is available, open a public issue only to request one; do not include vulnerability details.

Please provide:
- A clear description of the vulnerability.
- Steps or a minimal proof of concept to reproduce the issue.
- The affected component (e.g., FastAPI endpoint, MCP tool, decision key validator).

We will investigate and respond to vulnerability reports promptly.
