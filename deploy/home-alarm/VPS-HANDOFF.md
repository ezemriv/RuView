# RuView Home Alarm v2 — VPS Codex handoff

## Objective

Execute only Step 4, **Deploy and close the VPS network boundary**, from the
canonical tracker [`docs/status/home-alarm-v2.md`](../../docs/status/home-alarm-v2.md).
Do not provision or operate the ESP32; the Mac session owns the physical board
and will perform Step 5 after the VPS is ready.

## Required repository state

- Remote: `https://github.com/ezemriv/RuView.git`
- Branch: `main`
- The checked-out branch must contain clean-flash checkpoint `1edc7214` and
  this handoff. Do not silently substitute an upstream branch or another
  checkout.

## Read first

1. [`AGENTS.md`](../../AGENTS.md)
2. [`docs/status/home-alarm-v2.md`](../../docs/status/home-alarm-v2.md)
3. [`deploy/home-alarm/AGENTS.md`](AGENTS.md)
4. [`deploy/home-alarm/README.md`](README.md)
5. [`deploy/home-alarm/verification/level4-acceptance.md`](verification/level4-acceptance.md)

Those tracked files are authoritative. This handoff supplies routing only and
must not override them.

## Scope and sequence

1. Inspect the VPS read-only: OS, Docker/Compose availability, disk space,
   existing containers, occupied TCP/UDP ports, firewall tooling/rules, and
   intended deployment directory.
2. Report conflicts or prerequisites before mutation. Preserve all unrelated
   services and firewall rules.
3. Obtain explicit user authority for SSH/firewall/deployment writes in the
   VPS session if it has not already been granted there.
4. Create `deploy/home-alarm/.env` locally on the VPS with mode `0600`. Have
   the operator enter values through the VPS-controlled terminal or another
   secure channel. Never ask for or echo secrets in chat, logs, command
   arguments, Git, or this handoff.
5. Validate with `docker compose config --quiet`; never render resolved config.
6. Deploy the pinned Compose stack from the checked-out branch.
7. Use a time-bounded temporary UDP/5005 discovery opening only if required.
   Remove it, then restrict both the VPS firewall and `RUVIEW_UDP_ALLOW` to the
   same observed home `/32`. Do not record the real address in Git.
8. Record only redacted outcomes in
   `deploy/home-alarm/verification/level4-acceptance.md`, mark only Step 4 in
   `docs/status/home-alarm-v2.md`, and commit those two updates. If blocked,
   record the blocker and stop without marking the step complete.
9. Push the evidence commit only with explicit user authorization.

## Boundaries

- Do not start Step 5, provision NVS, access the Mac serial device, flash
  hardware, or claim live ESP32 sensing.
- Do not change the pinned sensing image digest.
- Do not publish TCP 3000 beyond loopback.
- Do not expose a broad or permanent UDP rule.
- Do not commit `.env`, tokens, chat IDs, real IP addresses, raw firewall
  dumps, private CSI, SSH keys, or other sensitive identifiers.
- Docker health alone is not API or hardware acceptance.

## Return to the Mac session

Report the deployment/evidence commit identifier, whether the same home `/32`
is active in both boundaries, whether the temporary rule was removed, and any
non-sensitive detail needed to fetch the commit. The Mac session will then
reconnect the ESP32, provision NVS with the VPS target through an interactive
hidden prompt, and execute Step 5.

## Suggested skills

- `superpowers:verification-before-completion`
- `superpowers:systematic-debugging` only if deployment behaves unexpectedly
- `codex-project-update` after a completed and committed Step 4
