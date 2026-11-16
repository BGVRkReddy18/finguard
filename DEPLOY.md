# Deploying FinGuard (free)

Two options:

| | Hugging Face Spaces (live demo) | Oracle Cloud VM |
|---|---|---|
| Cost / card | Free, **email signup only** | Free, card needed for verification |
| Runs | All services in one container | Separate containers (`docker-compose.prod.yml`) |
| Data | Simulated, resets on restart | Persistent volumes |
| Setup | Automatic from GitHub Actions | ~40 min, see below |

## Option A — Hugging Face Spaces (what the live demo uses)

1. Create an account at huggingface.co and a **Write** token (Settings → Access Tokens).
2. In the GitHub repo:
   ```bash
   gh secret set HF_TOKEN                      # paste the hf_... token
   gh secret set LLM_API_KEY < <(grep '^LLM_API_KEY=' .env | cut -d= -f2-)   # Groq key, passed to the Space as a secret
   gh variable set HF_SPACE --body "<hf-username>/finguard"
   gh workflow run "Deploy to Hugging Face"   # or just push to main
   ```
3. The workflow creates the Space and uploads the repo; Hugging Face builds `deploy/hf/Dockerfile`
   (~5–10 min the first time). The app is at `https://<hf-username>-finguard.hf.space`.
4. **Keep it awake:** free Spaces sleep after 48 h without visitors. Add a free monitor at
   **uptimerobot.com** (email signup): *New monitor → HTTP(s) → URL `https://<hf-username>-finguard.hf.space/api/health/`
   → interval 5 min*. You also get a public status page to link.

Optional Space secrets: `ADMIN_PASSWORD` (Django admin; random if unset), `SIM_TPS` (default 5 —
keep it equal to the training rate).

## Option B — Oracle Cloud Always Free VM

Target: one **Ampere A1 ARM VM (4 OCPU, 24 GB RAM)** from Oracle's Always Free tier, HTTPS via
**Caddy + Let's Encrypt**, and a free hostname from **sslip.io** (`<your-ip>.sslip.io`), so no domain
purchase is needed. Total cost: ₹0.

```
Internet ──443──▶ Caddy ──┬─ /            → Next.js console
                          ├─ /api, /admin → Django (gunicorn)
                          ├─ /ai/{ask,investigate,ws/live,health} → AI service
                          ├─ /ml/{model/info,health}             → ML service
                          └─ /grafana     → Grafana (password)
        (Postgres, Redis, Kafka, /metrics, /ml/score: internal only)
```

## 1. Create the VM (~15 min, one time)

1. Sign up at **cloud.oracle.com** → *Start for free*. Oracle asks for a card **for identity
   verification only**; Always Free resources are never charged. Pick a home region close to you
   (e.g. *India South (Hyderabad)* or *India West (Mumbai)*) — it can't be changed later.
2. *Compute → Instances → Create instance*
   - **Image:** Canonical Ubuntu 24.04 (aarch64)
   - **Shape:** *Ampere* → `VM.Standard.A1.Flex`, **4 OCPU, 24 GB** (shows "Always Free-eligible")
     - If you get **"Out of capacity"**, retry later or try 2 OCPU / 12 GB — FinGuard fits in that too.
   - **SSH keys:** *Upload public key* → your `~/.ssh/id_ed25519.pub`
     (no key yet? `ssh-keygen -t ed25519` on your Mac)
   - Boot volume: default 50 GB is fine (Always Free covers up to 200 GB total)
3. Note the **public IP** shown on the instance page.
4. Open the ports in Oracle's network firewall:
   *Instance → Subnet → Security Lists → Default → Add Ingress Rules*:
   | Source CIDR | Protocol | Port |
   |---|---|---|
   | `0.0.0.0/0` | TCP | 80 |
   | `0.0.0.0/0` | TCP | 443 |
   | `0.0.0.0/0` | UDP | 443 (optional, HTTP/3) |

## 2. Prepare the server (~5 min)

```bash
ssh ubuntu@<IP>
git clone https://github.com/<you>/finguard.git ~/finguard && cd ~/finguard
./deploy/setup-server.sh      # Docker + opens 80/443 in the VM's own iptables firewall
exit                          # log out/in so the docker group applies
```

> Oracle's Ubuntu images block all ports except SSH **inside the VM too** (iptables), in addition
> to the Security List. `setup-server.sh` fixes the VM side; step 1.4 fixes the network side.
> Missing either one is the #1 reason "the site doesn't load".

## 3. Configure and start (~15 min, mostly image builds)

```bash
ssh ubuntu@<IP> && cd ~/finguard
./deploy/gen-env.sh <IP>.sslip.io     # random secrets → .env.prod (prints admin + Grafana passwords — save them)
nano .env.prod                        # paste LLM_API_KEY=gsk_... (your free Groq key)
./deploy/deploy.sh                    # build + start everything
./deploy/bootstrap-ml.sh              # warm the feature store (~1 min)
```

Open **https://&lt;IP&gt;.sslip.io** — Caddy fetches the certificate on the first request (a few seconds).

| URL | Login |
|---|---|
| `https://<IP>.sslip.io` | `analyst` / `finguard123`, `manager` / `finguard123` (public demo) |
| `https://<IP>.sslip.io/admin/` | `admin` / *password printed by gen-env.sh* |
| `https://<IP>.sslip.io/grafana/` | `admin` / *Grafana password printed by gen-env.sh* |

## 4. Continuous deployment (optional, ~5 min)

After this, every push to `main` that passes CI deploys automatically.

```bash
# On your Mac: a dedicated key used only by GitHub Actions
ssh-keygen -t ed25519 -f ~/.ssh/finguard_deploy -N "" -C "github-actions-deploy"
ssh-copy-id -i ~/.ssh/finguard_deploy.pub ubuntu@<IP>

# Pin the server's host key (compare the fingerprint with: ssh ubuntu@<IP> 'ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub')
ssh-keyscan -t ed25519 <IP> > /tmp/finguard_known_hosts && ssh-keygen -lf /tmp/finguard_known_hosts

gh secret set DEPLOY_HOST --body "<IP>"
gh secret set DEPLOY_USER --body "ubuntu"
gh secret set DEPLOY_DOMAIN --body "<IP>.sslip.io"
gh secret set DEPLOY_SSH_KEY < ~/.ssh/finguard_deploy
gh secret set DEPLOY_KNOWN_HOSTS < /tmp/finguard_known_hosts
gh variable set DEPLOY_ENABLED --body "true"
```

## Operations

| Task | Command (on the server, in `~/finguard`) |
|---|---|
| Status | `docker compose -f docker-compose.prod.yml --env-file .env.prod ps` |
| Logs | `docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f ai-service` |
| Update manually | `./deploy/deploy.sh` |
| Back up the database | `docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres pg_dump -U finguard finguard \| gzip > backup-$(date +%F).sql.gz` |
| Pause the demo (save LLM quota) | `docker compose -f docker-compose.prod.yml --env-file .env.prod stop simulator` |

## Security model of the public demo

- Only ports 80/443 are reachable; databases, Kafka, internal APIs and `/metrics` are not routed.
- `/ml/score` is internal, so visitors can't inject transactions into the feature store.
- Demo accounts are analyst/manager only; the admin account has a random password.
- LLM endpoints are rate-limited per user (`USER_ASK_PER_HOUR`, `USER_INVESTIGATE_PER_HOUR`) and
  auto-investigation has a daily token budget, so visitors can't exhaust the free Groq quota.
- Secrets live only in `.env.prod` (mode 600, git-ignored); Django refuses to start with a weak key.
