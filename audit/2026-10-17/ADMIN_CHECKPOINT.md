# Administrator provisioning and GitHub checkpoint

Subsequent real Edge login and local-service verification are recorded in [LIVE_BROWSER_CHECK.md](LIVE_BROWSER_CHECK.md), including successful CAPTCHA/SMS sign-in by the user.

The requested existing local phone account was promoted from CUSTOMER to ADMIN using the private bootstrap function. Its original identity was preserved; no phone-number-based automatic role grant or OTP bypass was added. A SQLite backup was saved locally before the role update. Databases, that backup and environment credentials remain excluded from Git.

The private `bootstrap_admin.py` command now supports `--phone` as well as the existing email argument. Indian ten-digit and international phone formats resolve to existing accounts; ambiguous or missing identities are rejected. Relative SQLite paths are resolved against the backend directory, so running the private command from the repository root targets the same database as the API.

Verification: **73 tests passed**, including four administrator/bootstrap/path regressions and the existing browser tests. The sole warning comes from the Starlette test-client dependency. The latest isolated results are in `regression-results.xml`.

The initial complete repair checkpoint was committed and pushed to `origin/master` as `f132abf`. Further verified changes are committed and pushed at meaningful milestones while work is active; no background automation or unattended commit job was installed.

Firebase's public configuration endpoint accepted the frontend API key and listed the expected Firebase hosting domains plus localhost and 127.0.0.1. This rules out an invalid key or absent local domain entry in that response; it does not establish why SMS/reCAPTCHA failed in the screenshot. Administrator authorization and Firebase OTP verification remain separate.

A read-only administrator configuration check also confirmed that Phone sign-in is enabled and SMS region policy allows India. No Firebase settings were changed and no SMS was sent by these checks. The screenshot's internal error has not been resolved by this provisioning change.
