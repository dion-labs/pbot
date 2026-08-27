# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's **Report a vulnerability** flow for the Dion Labs pbot repository. Do not open a public issue containing credentials, account data, device identifiers, screenshots, local paths, or reproduction data from `var/`.

Security fixes target the latest source revision. This experimental project does not currently maintain supported release branches.

## Trust boundaries

pbot is designed to run locally on a machine and Android device you control:

- The API binds to `127.0.0.1` by default and has no authentication layer. Do not expose API port `8765` or the dashboard to a LAN or the public internet.
- ADB authorization grants powerful control over the connected device. Revoke debugging authorization when it is no longer needed, and avoid running pbot on a phone containing sensitive unrelated data.
- Runtime SQLite data, screenshots, logs, device identifiers, and account-derived information live under ignored `var/` storage. Treat that directory as private and do not upload it in bug reports.
- `.env.local` may contain local paths and device configuration. It is ignored; never commit it.
- The no-spend and owned-only rules are application policy guards, not an Android sandbox. Supervise the first run after installation or a game update.
- Login and secure unlock remain manual. pbot should never request, store, or transmit account credentials.
- Optional future model or research providers may receive structured observations or screenshots only when explicitly configured. Review their data policy before enabling them.

pbot does not bypass game protections. Using automation can still violate a service's rules or terms and can risk the associated account.
