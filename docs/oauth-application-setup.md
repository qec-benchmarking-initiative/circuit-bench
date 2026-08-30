# GitHub and ORCID application setup

Status: defer this setup until the mocked account tests pass and a developer is
ready to run the first real provider smoke test. Normal development and the
automated test suite do not require OAuth credentials.

DecoderBench uses provider-only login through `django-allauth`. Provider
credentials are supplied through environment variables. Do not also create
`SocialApp` rows in Django admin: configuring the same provider in both places
is ambiguous, and the credentials do not belong in the development database.

## Local GitHub application

Create a dedicated development **OAuth app** at
<https://github.com/settings/applications/new>. Use:

- Application name: `DecoderBench local` (or another clearly local name)
- Homepage URL: `http://127.0.0.1:8000/`
- Authorization callback URL:
  `http://127.0.0.1:8000/accounts/github/login/callback/`
- Device flow: disabled
- Callback wildcard matching: disabled

Put the generated values in the untracked `.env` file:

```dotenv
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
```

Start the local server with `uv run --env-file .env python manage.py
runserver`; Django deliberately does not parse dotenv files itself.

GitHub OAuth apps have one configured callback URL, so create a separate
production app later rather than repeatedly changing the local app or enabling
wildcards.

## Local ORCID sandbox application

Create or use an ORCID sandbox account at <https://sandbox.orcid.org/signin>.
Verify its email, open **Developer Tools**, accept the Public API terms, and
register an application with:

- Name: `DecoderBench local`
- Application URL: `http://127.0.0.1:8000/`
- Redirect URI:
  `http://127.0.0.1:8000/accounts/orcid/login/callback/`

Put the generated values in `.env`:

```dotenv
ORCID_CLIENT_ID=...
ORCID_CLIENT_SECRET=...
ORCID_BASE_DOMAIN=sandbox.orcid.org
```

## Production later

After a public HTTPS domain exists:

1. Create a separate GitHub OAuth app whose homepage and exact callback use
   that domain.
2. Register ORCID production Public API credentials at
   <https://orcid.org/developer-tools>. ORCID production redirect URIs must use
   HTTPS and exactly match the deployed hostname.
3. Store both secrets in the hosting provider's secret environment, set
   `ORCID_BASE_DOMAIN=orcid.org`, and do not copy them into Git, database seed
   data, screenshots, or support messages.
4. Run the manual smoke matrix: new GitHub account, new ORCID account, link the
   second identity, sign in with each identity, reject an attempted collision,
   unlink one identity, and refuse unlinking the last identity.

Primary documentation:

- [django-allauth provider callback convention](https://docs.allauth.org/en/latest/socialaccount/providers/index.html)
- [django-allauth GitHub provider](https://docs.allauth.org/en/dev/socialaccount/providers/github.html)
- [GitHub OAuth app registration](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app)
- [django-allauth ORCID provider](https://docs.allauth.org/en/dev/socialaccount/providers/orcid.html)
- [ORCID Public API client registration](https://info.orcid.org/documentation/integration-guide/registering-a-public-api-client/)
