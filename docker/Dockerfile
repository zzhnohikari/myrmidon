# sapper agent image for TSecBench hosted mode ( Throne Protocol qualifier ).
#
# Match rules (2026-10-17/18 online round):
#   - ONE submission attempt, 8h task limit, 50 challenges / 100 flags
#   - ranked by score, then elapsed time, then TOKEN USAGE
#   - no hints; model rate-limits are NOT grounds for a retry
#   - logs/trace are NOT viewable -> the image must fail loud, never hang
#
# Build:  docker build -f docker/Dockerfile -t sapper-agent:latest .
# Export: bash docker/build.sh          ->  dist/sapper-agent.tar.gz
FROM kalilinux/kali-rolling:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PATH="/home/agent/.local/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    SAPPER_MODEL=glm-5.3-flash[1m] \
    SAPPER_TOTAL_MINUTES=470 \
    SAPPER_MINUTES_PER_CHALLENGE=9 \
    SAPPER_MAX_STEPS=10 \
    SAPPER_RETRY_MODEL=3 \
    SAPPER_ROOT=/work/runs

# --- offensive tooling (kali repo, curated to stay < 3GB) -------------------
# Pin a reliable mirror: the default http.kali.org redirect can land on
# mirrors that fail to resolve in build sandboxes.
RUN echo 'deb http://mirrors.tuna.tsinghua.edu.cn/kali kali-rolling main contrib non-free non-free-firmware' \
        > /etc/apt/sources.list \
    && echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80-retries
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget git jq unzip zip file xxd less vim \
        procps psmisc lsof tcpdump iproute2 iputils-ping net-tools \
        python3 python3-pip \
        nodejs npm \
        netcat-traditional socat \
        dnsutils whois \
        openssl \
        nmap masscan \
        whatweb wafw00f nikto \
        gobuster ffuf dirb wfuzz \
        sqlmap \
        hydra \
        binwalk steghide exiftool \
        libgmp-dev libmpfr-dev libmpc-dev \
        redis-tools default-mysql-client postgresql-client \
        gdb checksec \
        smbclient smbmap \
        ldap-utils \
        enum4linux \
        responder impacket-scripts \
        proxychains4 \
        seclists \
        sudo \
    && rm -rf /var/lib/apt/lists/* \
    && du -sh /usr/share/seclists \
    && rm -rf /usr/share/seclists/IOCs \
              /usr/share/seclists/Misc /usr/share/seclists/Username_Lists \
              /usr/share/seclists/Discovery/DNS \
    && rm -rf /usr/share/doc /usr/share/man /usr/share/vim/vim*/doc \
    && du -sh /usr/share/seclists

# nuclei (Go release) — CVE-template runner referenced by the kb.
# The zip is downloaded on the host (proxy) and shipped via build context:
# the build sandbox cannot reach github.
COPY docker/nuclei.zip /tmp/nuclei.zip
RUN unzip -o /tmp/nuclei.zip -d /usr/local/bin nuclei \
    && chmod +x /usr/local/bin/nuclei && rm -f /tmp/nuclei.zip

# --- model CLI --------------------------------------------------------------
# --allow-scripts: kali's npm blocks postinstall by default, but claude-code
# ships a native binary that its postinstall (node install.cjs) must fetch.
RUN npm install -g --allow-scripts=@anthropic-ai/claude-code @anthropic-ai/claude-code \
    && claude --version \
    && npm cache clean --force

# --- python extras ----------------------------------------------------------
# pip goes TUNA + DIRECT for the same reason apt above does: the docker daemon
# injects a 7890 proxy into build containers and it stalls on big wheels.
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
# Kali rolling is on py3.14 now: ropper's `filebytes` dep uses ast.Str (removed
# in 3.14) and cannot build — ROPgadget covers the same need (the commander
# layer ships the same fallback). unicorn is not pinned to 2.0.1.post1 any
# more: it has no py3.14 wheel and would force a from-source build.
RUN env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    pip3 install --no-cache-dir --break-system-packages \
        requests pyjwt pycryptodome sympy ROPgadget \
    && (env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
        pip3 install --no-cache-dir --break-system-packages pwntools \
        || env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
        pip3 install --no-cache-dir --break-system-packages unicorn \
        || echo "WARN: pwntools/unicorn unavailable — continuing (stdlib+sympy covers most crypto)")
# heavy/compiled extras: failure here must not kill the build (kb mentions them
# as optional; stdlib+sympy covers most crypto)
RUN pip3 install --no-cache-dir --break-system-packages gmpy2 z3-solver \
        || echo "WARN: gmpy2/z3 unavailable — continuing without them"

# --- sapper -----------------------------------------------------------------
COPY lib/        /opt/sapper/lib/
COPY templates/  /opt/sapper/templates/
COPY kb/         /opt/sapper/kb/
COPY README.md LICENSE SKILL.md /opt/sapper/

# --- non-root agent user ----------------------------------------------------
# Claude Code refuses --dangerously-skip-permissions as root; run unprivileged
# with a writable HOME for the model CLI's state.
RUN useradd -m -s /bin/bash agent \
    && mkdir -p /home/agent/.local/bin /work/runs \
    && ln -sf /opt/sapper/lib/sapper.py /home/agent/.local/bin/sapper \
    && chmod +x /opt/sapper/lib/sapper.py \
    && chown -R agent:agent /work /opt/sapper /home/agent

COPY docker/entrypoint.sh /usr/local/bin/sapper-entrypoint
RUN chmod +x /usr/local/bin/sapper-entrypoint

USER root
# --- py3.14 compat fixes (kali rolling is on python 3.14 now) ---------------
# pwntools still pins unicorn!=2.1.3,!=2.1.4, so pip falls back to older sdists
# that have no py3.14 wheels and need cmake — install pwntools --no-deps against
# the unicorn 2.1.x already present and supply its runtime deps explicitly.
# binutils: --no-install-recommends above dropped it (gdb only Recommends it);
# pwn.asm needs `as`, and amd64 CTF targets need the x86-64 cross assembler.
RUN env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    pip3 install --no-cache-dir --break-system-packages \
        pwntools --no-deps pysocks paramiko mako plumbum pyelftools pyserial \
        rpyc sortedcontainers intervaltree psutil tqdm python-dateutil \
    || echo "WARN: pwntools unavailable — continuing (stdlib+sympy covers most crypto)"
RUN env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    apt-get update \
    && env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    apt-get install -y --no-install-recommends binutils binutils-x86-64-linux-gnu binutils-i686-linux-gnu cpp \
    && rm -rf /var/lib/apt/lists/*

# Docker Desktop (userns) refuses to exec binaries carrying file capabilities —
# kali ships nmap with cap_net_raw=eip — and stripping them needs CAP_SETFCAP,
# which the runtime doesn't grant either. Rewriting the inode via cp drops
# security.capability; nmap then falls back to connect scans.
RUN cp /usr/lib/nmap/nmap /usr/lib/nmap/nmap.nocaps \
    && rm /usr/lib/nmap/nmap \
    && mv /usr/lib/nmap/nmap.nocaps /usr/lib/nmap/nmap \
    && chmod 0755 /usr/lib/nmap/nmap \
    && nmap --version | head -1

USER agent
WORKDIR /work
ENTRYPOINT ["/usr/local/bin/sapper-entrypoint"]
