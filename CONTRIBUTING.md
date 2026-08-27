# Contributing

pbot is a Dionlabs personal workbench shared as an experimental reference project. Contributions that make its behavior safer, more inspectable, or easier to adapt are welcome; broad compatibility and maintainer-led porting support are not promised.

Before proposing support for a new device, resolution, platform, OCR provider, account shape, or game version, open an issue describing the setup and attach only sanitized evidence. Never post account details, credentials, ADB serials, private screenshots, local paths, or files from `var/`.

For code changes:

1. Preserve the owned-only, no-rental, no-spend defaults and fail-closed read-back checks.
2. Add a focused regression test for classifier, routing, selector, recovery, or persistence changes.
3. Prefer sanitized replay fixtures over account-specific coordinates or names when practical.
4. Run `npm run lint` and `npm test` before submitting a pull request.
5. Explain the observed state, expected state, and evidence behind any visual automation change.

By contributing, you agree that your contribution is licensed under the repository's MIT License.
