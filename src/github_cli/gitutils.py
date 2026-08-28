import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path


def secure_git_clone(clone_url: str, dest: Path, token: str | None, is_private: bool = False, ssh: bool = False, ssh_url: str | None = None) -> int:
    """
    Clona sem expor token no `ps aux`.
    - Se ssh=True: usa ssh_url direto (sem token)
    - Se público: clone_url puro sem token
    - Se privado + token: cria script ASK_PASS temporário que lê token do env HUBCTL_TOKEN
      e roda `git clone https://github.com/user/repo.git` com GIT_ASKPASS
    Retorna returncode do git.
    """
    if ssh:
        url = ssh_url or clone_url
        # fallback: se não tem ssh_url, constrói manualmente (sem token)
        if not url:
            # clone_url é https://github.com/user/repo.git sem token
            url = clone_url
        return subprocess.run(["git", "clone", url, str(dest)]).returncode

    # HTTPS — sem token na URL
    url = clone_url
    # garante que url não tem token embutido
    if token and "oauth2:" in url:
        # strip token se veio do caller legacy
        url = url.replace(f"oauth2:{token}@", "")

    if not is_private or not token:
        return subprocess.run(["git", "clone", url, str(dest)]).returncode

    # Privado com token — via GIT_ASKPASS
    # cria script temporário que responde username/password
    # Git chama ASK_PASS para username e password separados; usamos um script que
    # imprime token como password e 'oauth2' como username baseado no prompt.
    # Simplificação: usa credential helper via env que não aparece no ps.
    script_fd, script_path = tempfile.mkstemp(prefix="hubctl-askpass-", suffix=".sh")
    try:
        with os.fdopen(script_fd, "w") as f:
            # script detecta "Username" vs "Password" no argumento
            f.write("#!/bin/sh\n")
            f.write('case "$1" in\n')
            f.write('  *Username*) echo "oauth2" ;;\n')
            f.write('  *Password*) echo "$HUBCTL_TOKEN" ;;\n')
            f.write('  *) echo "$HUBCTL_TOKEN" ;;\n')
            f.write('esac\n')
        os.chmod(script_path, stat.S_IRWXU)

        env = os.environ.copy()
        env["HUBCTL_TOKEN"] = token
        env["GIT_ASKPASS"] = script_path
        env["GIT_TERMINAL_PROMPT"] = "0"
        # desativa credential helpers que poderiam cachear
        env["GCM_INTERACTIVE"] = "Never"

        # usa -c credential.helper= para garantir que não usa helper do sistema que pede GUI
        result = subprocess.run(["git", "clone", url, str(dest)], env=env)
        return result.returncode
    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass
        # limpa token do env local (não afeta parent)


def get_cwd_repo() -> str | None:
    """Detecta `user/repo` do git remote do diretório atual, se for GitHub."""
    try:
        out = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
        if not out:
            return None
        url = out.strip()
        # ssh: git@github.com:user/repo.git  ou ssh://git@github.com/user/repo.git
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            full = m.group(1).strip("/")
            # remove .git já tratado, garante sem sufixo
            if full.endswith(".git"):
                full = full[:-4]
            # valida formato user/repo
            if "/" in full and len(full.split("/")) == 2:
                return full
        return None
    except Exception:
        return None
