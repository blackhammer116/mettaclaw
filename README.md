# SNET TELEGRAM BOT

A Telegram bot with media support. It reads images, PDFs and voice notes that
users attach, and can generate images and send them back.

Everything ships as an Omega plugin: a `CommChannel` for the Telegram
channel plus two skills for the media capabilities. No core internals are
patched — `plugins.yaml` and `skills.metta` are mounted over their core copies
so the plugin and its skills are registered.

## Capabilities

| Capability | How the agent sees it |
| --- | --- |
| Inbound photo | Message shows `[image]`; the agent calls `describe-image` on demand |
| Inbound PDF | Extracted text is inlined into the message |
| Inbound voice / audio | Whisper transcript is inlined into the message |
| Outbound image | The agent calls `generate-image`, which generates and sends the photo |
| Admin commands | `/kill`, `/pause [chat_id]`, `/togglesearch`, `/purge` (admin IDs only) |
| Safety | Ethics classification on inbound and outbound text, per-user spam throttling |

## Installation

1. `git clone git@github.com:singnet/Omega_CustomBots.git`
2. `cd Omega_CustomBots`
3. `git checkout SNET_Telegram`
4. Open `Omega_Telegram_SNET` in an editor and replace every `'...'`:
   - `TG_BOT_TOKEN` — from @BotFather
   - `TG_CHAT_ID` — the chat the bot operates in
   - `ANTHROPIC_API_KEY` — reading images
   - `OPENROUTER_API_KEY` — chat, image generation, voice transcription
   - `OPENAI_API_KEY` — the Moderation API used by the safety checks
5. Edit `telegram/telegram_profile.yaml` and fill in **both** of these — they
   ship empty and the bot is not safe to run in a real chat until they are set:
   - `admin_controls.admin_ids` — Telegram user IDs allowed to run admin commands
   - `telegram.allowed_chats` — chat IDs the bot may operate in
6. In BotFather, turn **Group Privacy off** for the bot, otherwise it cannot see
   group messages that are not direct replies to it.
7. `./Omega_Telegram_SNET`

The first run builds core from source and takes a while. Later runs reuse the
image.

## Stop and restart

```sh
docker stop omega && docker start omega
```

Run only one instance per bot token. A second one makes Telegram reject both
with `TelegramConflictError`.

## Build notes

**Core is built from source, not pulled from a published tag.** This bot needs
core's plugin system (`config/plugins.yaml`, `src/channels.py`), which is not in
a release yet — `v0.1.17` has neither. `Omega_Telegram_SNET` clones core at
the pinned commit and builds it, then layers the plugin's Python dependencies
on top via the `Dockerfile`, from `telegram/requirements.txt`. Core installs
only its own `requirements.txt`, so without that layer the plugin loader fails
on import.

Omega core version: pinned commit `7f0d33f` of
`singnet/Omega`. Change `CORE_COMMIT` in
`Omega_Telegram_SNET` to move it.

**The launcher bypasses core's `entrypoint.sh`** with `--entrypoint sh`. That
entrypoint scrubs the environment down to an allowlist which excludes
`TG_BOT_TOKEN` and every API key, because core expects channels to read their
secrets from the nginx proxy it starts. This channel reads the environment
instead, so the entrypoint is skipped.

Two things follow, and one of them is worth understanding before deploying:

- **The keys stay in the agent process's environment.** A stock run keeps them
  in the proxy, where the agent cannot read them. Here anything that can read
  the process environment — including the agent's own `shell` skill — can read
  `TG_BOT_TOKEN` and all three API keys. Routing the channel through the proxy,
  the way core's `channels/telegram.py` does, would remove the need for the
  bypass entirely.
- `GATEWAY_URL` is unset, so providers call their APIs directly rather than
  through the proxy.

Skipping the entrypoint also skips the `su nobody` it ends with, which would
leave the agent running as **root**. The launcher runs the same `su nobody`
itself, so the process ends up as uid 65534 exactly as it would on a stock run;
`memoryDirectory` and the writable paths in `profile/policy.yaml` are all owned
by that user. Secrets handling is therefore the only way this run differs from a
stock one — not privileges.

## Files

| Path | Mounted over | Role |
| --- | --- | --- |
| `telegram/` | `plugins/telegram` | The plugin: channel, media handling, vision, config |
| `plugins.yaml` | `config/plugins.yaml` | Core's plugin list plus this plugin's entry |
| `skills.metta` | `src/skills.metta` | Core's skills plus `describe-image` and `generate-image` |
| `Dockerfile` | — | Adds the plugin's Python dependencies to the core image |
| `Omega_Telegram_SNET` | — | Builds and runs the bot |

`skills.metta` carries the two media skills because a MeTTa plugin's
`loadOmegaPlugin` cannot currently register skills that reach `getSkills`.
Once that is fixed upstream they can move into the plugin and this file no
longer needs mounting.

## Configuration

Behaviour lives in `telegram/telegram_profile.yaml`: reply gating, admin IDs,
spam thresholds, ethics categories, and `reply_constraints` (which includes
`allow_image_generation`). `telegram/policy.md` holds the `/start`, `/about` and
`/privacy` text.

Optional environment variables:

| Variable | Purpose |
| --- | --- |
| `VISION_PROVIDER` | `Anthropic` (default) or `OpenRouter` |
| `VISION_MODEL` | Overrides the vision provider's default model |
| `IMAGE_PROVIDER` | `OpenRouter` (default, FLUX) or `OpenAI` |
| `IMAGE_MODEL` | Overrides the image provider's default model |

Vision defaults to Anthropic: an OpenRouter account whose data policy excludes
vision providers gets a 404 on every vision model, while text chat and image
generation keep working on the same key.

## Tests

```sh
pip install pytest -r telegram/requirements.txt
pytest telegram/tests -q
```

Network and Telegram calls are stubbed, so no credentials are needed. The live
suite in `telegram/tests/test_e2e.py` skips itself unless `TG_E2E=1` is set; it
talks to a real bot, so give it an idle token rather than the one a running bot
is polling with.

To run the suite against the real core inside a built image:

```sh
./run-plugin --test
```

## Continuous delivery

Five workflows in `.github/workflows/`, all living on this branch only:

| Trigger | Workflow | What happens |
| --- | --- | --- |
| pull request | `ci.yml` | test, build, smoke test; publishes nothing |
| push to `SNET_Telegram` | `deploy-staging.yml` | the same, then push the image and deploy to staging |
| push a `prod-*` tag | `deploy-production.yml` | the same against production, with `--restart=always` |

All three call `common.yml`, where the image is assembled, and the two deploys
call `deploy.yml`, where the server work lives. Staging and production differ
only in which Infisical environment the secrets come from and whether the
container restarts on its own, so they share one deploy definition.

### How the image is built

`common.yml` runs the same script you would run locally:

```sh
./run-plugin --prepare-only --core-remote <remote> --core-ref <commit>
```

Core is cloned at a commit, copied, and the copy is what receives the plugin at
`plugins/telegram`. Core itself is never edited, so nothing on this branch has
to land upstream for the image to exist.

Core defaults to the `telegram` branch of `iCog-Labs-Dev/mettaclaw`, which
already carries everything the plugin needs, so nothing is patched. Against a
core that does not — `singnet/Omega` today — the script adds the manifest entry,
the plugin requirements install, the `/telegram-file/` proxy route, and removes
the channel file that claims the same id. Point it at a different core with the
`CORE_REMOTE` or `CORE_REF` repository variable; no workflow edit.

A branch is resolved to a commit when the run starts, so a push to core
mid-build cannot change what is built, and every run summary records the core
commit its image came from.

Images go to `ghcr.io/singnet/omega-telegram-snet`, tagged `staging-<sha>` or
`production-<sha>` after the plugin's own commit.

### What has to pass before an image is published

The plugin's test suite, on the runner. Then the built image is asked to load
the plugin the way core will: read the manifest through core's own loader, and
import every module. The suite cannot catch a missing dependency on its own,
because it stubs core out and runs against whatever the runner has installed —
only the image can, and a missing dependency is this plugin's most likely way
to break a deployment.

### One-time setup

Nothing in Infisical changes: the same machine identities, the same project, the
same `staging` and `prod` environments, and the same key names (`ASI_API_KEY`,
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `BOT_TOKEN`,
`CHAT_ID`) this bot already reads.

What this repository needs is the login to that vault and SSH access to the two
servers, as nine repository secrets:

| Secret | |
| --- | --- |
| `INFISICAL_PROJECT_SLUG` | the project holding the keys, shared |
| `INFISICAL_CLIENT_ID_STAGING` | the staging machine identity |
| `INFISICAL_CLIENT_SECRET_STAGING` | |
| `INFISICAL_CLIENT_ID_PRODUCTION` | the production machine identity |
| `INFISICAL_CLIENT_SECRET_PRODUCTION` | |
| `SSH_HOST_STAGING` | staging server |
| `SSH_HOST_PRODUCTION` | production server |
| `SSH_USER` | shared by both |
| `SSH_PRIVATE_KEY` | shared by both |

Staging and production log in to Infisical as different identities, so their
credentials cannot share a name. Each deploy workflow passes its own pair into
`deploy.yml`, which reads them under one name — so the deploy logic stays
single-copy while the credentials stay separate.

`./push-cicd-secrets` sets all nine from a filled `.env.cicd`, validating first
and printing no value. Setting secrets needs admin on the repository. GitHub
environments are deliberately not used: the protection rules that would justify
them also need admin, and without them an environment adds nothing here. To add
approval gates later, put `environment: staging` back on the job in
`deploy.yml`.

Everything else has a default: `LLM_PROVIDER` (`OpenRouter`), `LLM_MODEL`
(core's own default when unset), `CORE_REMOTE` and `CORE_REF`. Set any of them
as a repository variable to override.

### It replaces the pipeline on core's telegram branch

The deploy is the same in every respect that touches the server: the same host,
the same `/omega/.env`, the same `/Backup/docker/PeTTa` memory mount, and the
same container name `omega`, which it removes and recreates. That is deliberate.
The Infisical `BOT_TOKEN` names one bot, and Telegram hands each update to one
poller, so two containers on that token would each see half the messages.

Disable `deploy-staging.yml` and `deploy-production.yml` on core's `telegram`
branch before the first push here, or whichever pipeline runs last wins.

---

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) file for details.
