# Security policy

GymTS is currently a synchronous, locally executed experiment framework. Plugins run in the Python process and must be trusted. Component-level resource authorization is an API boundary, **not an operating-system sandbox for untrusted code**. Deployment owners must supply separate users, containers, or external workers and appropriate network/filesystem isolation for unknown model code, plugins, or services.

## Reporting security issues

Do not disclose exploit steps, real keys, private data, or production endpoints in public Issues, PRs, logs, or attachments.

1. Check the repository [Security page](https://github.com/Jurmean/GymTS/security). If “Report a vulnerability” is available, use GitHub’s private vulnerability reporting.
2. If that entry point is unavailable, open a [minimal public Issue](https://github.com/Jurmean/GymTS/issues/new) stating only that a private security reporting channel is needed. Do not describe the vulnerability, affected assets, or exploit. Send full materials only after a maintainer provides a verifiable private channel.

The repository has not declared a dedicated security email, a confirmed private reporting entry point, response deadlines, or a bounty program. Do not assume an unconfirmed personal account is a security contact. Security issues are handled separately from ordinary questions; see [support](SUPPORT.md).

A private report should include GymTS/adapter and Python versions, the affected public interface, a minimal reproduction, actual impact, required permissions, known mitigations, and whether you can help validate a fix. Use synthetic data and placeholder credentials; send only necessary material.

## Known trust boundaries

- **Local storage is not an access-control service.** Anyone able to read the directory may obtain prompts, raw responses, reference answers, model trajectories, and service metadata. Protect directories with OS permissions; inspect the entire CAS and record snapshot before sharing, not just the final report.
- **There is currently no general automatic redaction backend.** The core rejects non-null `redaction_policy_ref`. Adapters avoid credential values, but external responses and user content may still contain sensitive data. Interface authorization does not imply automatic de-identification.
- **Planning validation does not establish runtime safety.** Schemas and compatibility checks do not authenticate remote services, review external code, or establish model/data licensing. Loaders, dependency installation, remote model code, dynamic plugins, and servers each require their own trust assessment.
- **External actions may be irreversible.** Limit accounts, actions, and budgets before connecting production testbeds. A timeout does not mean no action occurred; adapters must preserve unknown/possible side effects rather than conceal uncertainty through automatic retries.
- **Artifact hashes establish content consistency, not authorship or trustworthiness.** Preserve original sources, fixed revisions, and necessary verification records.

Supply secrets through environment variables or external credential references, not configurations, command examples, notebooks, logs, or Git. Revoke or rotate exposed credentials with the provider first; deleting repository files cannot revoke leaked values.

## Fixes and version scope

The current version is 0.5.0. No supported-version matrix or security backport commitment has been published. Report precise versions and source revisions so maintainers can assess impact. Fixes should include a minimal regression, compatibility notes, and necessary public advisories, without exposing actionable exploit details before users have mitigations.

`scripts/check_release.py` checks distribution contents, dangerous archive paths, and a set of known secret patterns. It does not audit Git history, detect every secret, verify external services, or constitute a full security audit.
