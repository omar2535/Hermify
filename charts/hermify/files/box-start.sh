#!/usr/bin/env bash
# An SSH box: the "box" container in a tenant's hermes pod, from the Hermes image (Debian),
# so the `hermes` CLI works in SSH sessions.
# Runs as root, serves sshd on :22 with key auth only, logs in as $BOX_USER (the tenant
# name) with UID 10000, the same UID as the Hermes process, so ~/agent = /opt/data stays
# writable for both.
#
# Persistent (PVC box-home-<tenant>, mounted at /persist): home/, host-keys/ (SSH host key),
# apt-archives/ (downloaded .debs). Everything else is the stock image, rebuilt on every
# container start, so packages are reinstalled from ~/.box/apt-packages (from the .deb
# cache, so it's quick).
set -euo pipefail
U=${BOX_USER:?BOX_USER not set}
ID=10000
P=/persist
H=/home/$U
export DEBIAN_FRONTEND=noninteractive

mkdir -p "$P/home" "$P/host-keys" "$P/apt-archives/partial"

# Keep downloaded .debs on the PVC (the image deletes them after every install by default).
# Drop the cache when the distro changes (a new image on a new Debian release).
distro=$(. /etc/os-release && echo "$ID-$VERSION_CODENAME")
if [ "$(cat "$P/apt-archives/.distro" 2>/dev/null)" != "$distro" ]; then
  rm -f "$P/apt-archives/"*.deb "$P/apt-archives/partial/"*
  echo "$distro" > "$P/apt-archives/.distro"
fi
rm -f /etc/apt/apt.conf.d/docker-clean
cat > /etc/apt/apt.conf.d/01box-cache <<EOF
Dir::Cache::Archives "$P/apt-archives/";
Binary::apt::APT::Keep-Downloaded-Packages "true";
EOF

apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  openssh-server sudo tini ca-certificates curl git vim nano tmux less htop python3 >/dev/null

# Extra packages. A typo here must not take the box (and the way back in) down.
if [ -f "$P/home/.box/apt-packages" ]; then
  mapfile -t extra < <(grep -vE '^[[:space:]]*(#|$)' "$P/home/.box/apt-packages" || true)
  if [ "${#extra[@]}" -gt 0 ]; then
    # One bad name fails the whole batch, so fall back to one at a time.
    apt-get install -y -qq --no-install-recommends "${extra[@]}" >/dev/null 2>&1 \
      || for p in "${extra[@]}"; do
           apt-get install -y -qq --no-install-recommends "$p" >/dev/null 2>&1 \
             || echo "box: couldn't install '$p' from ~/.box/apt-packages" >&2
         done
  fi
fi

# User: no password (key login only; '*' is "no password", not "locked"), passwordless sudo.
# /home/$U points at the PVC; sshd resolves the link before its StrictModes checks.
# The image already has user and group "hermes" with UID/GID 10000: rename them to $U.
ln -sfn "$P/home" "$H"
g=$(getent group "$ID" | cut -d: -f1) || true
if [ -z "$g" ]; then groupadd -g "$ID" "$U"; elif [ "$g" != "$U" ]; then groupmod -n "$U" "$g"; fi
u=$(getent passwd "$ID" | cut -d: -f1) || true
if [ -z "$u" ]; then useradd -u "$ID" -g "$ID" -d "$H" -M -s /bin/bash "$U"
elif [ "$u" != "$U" ]; then usermod -l "$U" -d "$H" -s /bin/bash "$u"; fi
usermod -aG sudo -p '*' "$U"
echo "$U ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/box
chmod 440 /etc/sudoers.d/box

# Home: first boot copies /etc/skel. StrictModes wants it owned by the user, not group-writable.
if [ ! -e "$P/home/.bashrc" ]; then
  cp -rT /etc/skel "$P/home"
  mkdir -p "$P/home/.box"
  cat > "$P/home/.box/apt-packages" <<'EOF'
# Extra apt packages for this box, one per line. Installed on every box start,
# since only your home directory survives a restart. Example:
# build-essential
EOF
  chown -R "$ID:$ID" "$P/home"
fi
chown "$ID:$ID" "$P/home"
chmod 750 "$P/home"
ln -sfn /opt/data "$P/home/agent"
# sshd starts the shell in the link's target; show ~ as /home/$U instead of /persist/home.
echo "[ \"\$PWD\" = $P/home ] && cd \"\$HOME\"" > /etc/profile.d/box-home.sh

# The agent's environment for SSH sessions, so `hermes` sees what the agent sees: the image's
# HERMES_* and PATH, the Hindsight settings, the LLM key and the tenant's extra variables
# (BOX_EXPORT_ENV, from the chart). Login shells read the profile.d file; sshd's pam_env
# reads /etc/environment for `ssh box <command>`. Only $U can read either (the key is their
# own agent's).
PATH="/usr/local/bin:$PATH"   # the box's `hermes` guard (below) before /opt/hermes/bin
extra_re=""
for v in ${BOX_EXPORT_ENV:-}; do
  case "$v" in *[!A-Za-z0-9_]*|"") ;; *) extra_re="$extra_re|$v" ;; esac
done
vars=$(compgen -e | grep -E "^(PATH|HERMES_(HOME|PYTHON|RUNTIME_DIR|TUI_DIR|WEB_DIST|WRITE_SAFE_ROOT)|HINDSIGHT_(MODE|API_URL|BANK_ID)|PLAYWRIGHT_BROWSERS_PATH|PYTHONDONTWRITEBYTECODE|PYTHONUNBUFFERED|CC|CXX$extra_re)\$" || true)
: > /etc/profile.d/hermes-env.sh
: > /etc/environment
for v in $vars; do
  printf 'export %s=%q\n' "$v" "${!v}" >> /etc/profile.d/hermes-env.sh
  if [ -n "${!v}" ]; then printf '%s=%s\n' "$v" "${!v}" >> /etc/environment; fi
done
chown "root:$U" /etc/profile.d/hermes-env.sh && chmod 640 /etc/profile.d/hermes-env.sh
chmod 600 /etc/environment

cat > /usr/local/bin/restart-agent <<'EOF'
#!/bin/sh
# The hermes container's liveness probe sees this file, deletes it and fails once,
# so Kubernetes restarts only that container. This SSH session stays up.
touch /opt/data/.restart-agent && echo "Hermes restarts within about 10 seconds."
EOF
chmod 755 /usr/local/bin/restart-agent

# `hermes` guard, first on PATH. The gateway runs in the hermes container, whose processes
# the box can't see, so from here Hermes thinks none is running ("Gateway is not running")
# and suggests `hermes gateway run`: a second gateway would fight the first over the
# Telegram bot. So gateway lifecycle commands map to restart-agent or are refused, and
# `hermes update` is refused (it would only touch this container's throwaway copy).
cat > /usr/local/bin/hermes <<'EOF'
#!/bin/sh
real=/opt/hermes/bin/hermes
case "$1 ${2:-}" in
  "gateway run"*|"gateway start"*|"gateway install"*|"gateway uninstall"*|"gateway stop"*|"gateway ensure"*)
    echo "box: not here. Your agent's gateway already runs in the pod's other container." >&2
    echo "box: after changing settings, run: restart-agent" >&2
    exit 1 ;;
  "gateway restart"*)
    exec restart-agent ;;
  "gateway status"*)
    echo "box: your agent's gateway runs in the pod's other container, so 'hermes gateway status'"
    echo "box: can't see it from here. Last lines of ~/agent/logs/gateway.log:"
    tail -n 8 /opt/data/logs/gateway.log
    exit 0 ;;
  "update "*)
    echo "box: Hermes updates come with the image tag (agent.image.tag in Hermify), not 'hermes update'." >&2
    exit 1 ;;
esac
# Chat sessions (bare `hermes`, `hermes chat`, `hermes -z ...`) run in the agent's gateway,
# which gets this shell's folder as the session's cwd and refuses one that doesn't exist in
# its container ("invalid_params field=cwd"). Only /opt/data (~/agent) exists in both.
case "${1:-}" in
  ""|-*|chat)
    case "$(pwd -P)/" in
      /opt/data/*) ;;
      *) echo "box: starting in ~/agent (your agent and its tools run in the other container, where only ~/agent exists)" >&2
         cd /opt/data ;;
    esac ;;
esac
exec "$real" "$@"
EOF
chmod 755 /usr/local/bin/hermes

cat > /etc/motd <<EOF

  $U's box (Debian, in the hermes-$U pod, same Hermes install as your agent)

  hermes setup         configure your agent, as on any Hermes install (also: hermes model,
                       hermes gateway setup, hermes chat)
  restart-agent        restart your agent after a change (this session stays up)
  ~/agent              your agent's home: config.yaml, .env, SOUL.md, skills/, logs/
  ~/.box/apt-packages  packages to reinstall on every box start

  Your agent (and its Telegram gateway) runs in the pod's other container, so chats
  started here run there, starting in ~/agent (the only folder both share). Here,
  "hermes gateway restart" = restart-agent, "gateway status" shows its log, and
  "gateway run/start" and "hermes update" are blocked (updates come with the image).
  Only your home directory survives a restart; sudo apt install is temporary.
  Avoid sudo inside ~/agent: Hermes runs as you (UID 10000) and needs to own its files.

EOF

# Host key on the PVC, so the fingerprint survives restarts.
chown root:root "$P/host-keys"
chmod 700 "$P/host-keys"
[ -f "$P/host-keys/ssh_host_ed25519_key" ] \
  || ssh-keygen -q -t ed25519 -N '' -C "$U-box" -f "$P/host-keys/ssh_host_ed25519_key"
chmod 600 "$P/host-keys/ssh_host_ed25519_key"

# Keys from the chart (tenants[].box.authorizedKeys), plus any the user adds to ~/.ssh.
install -d -m 755 /etc/ssh/authorized_keys
install -m 644 /box-keys/authorized_keys "/etc/ssh/authorized_keys/$U"

# Debian's sshd_config includes sshd_config.d/*.conf first, and the first value wins.
cat > /etc/ssh/sshd_config.d/10-box.conf <<EOF
Port 22
HostKey $P/host-keys/ssh_host_ed25519_key
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
AuthorizedKeysFile /etc/ssh/authorized_keys/%u .ssh/authorized_keys
AllowUsers $U
X11Forwarding no
EOF

mkdir -p /run/sshd
/usr/sbin/sshd -t
echo "box: ready, sshd on :22 for $U"
exec tini -- /usr/sbin/sshd -D -e
