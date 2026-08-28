import os
import shutil
import subprocess
import sys
from pathlib import Path

import questionary
import requests
from questionary import Style

from .config import CONFIG_FILE, delete_token, get_recents, get_token, save_recent, save_token
from .github import GitHubClient, fetch_readme_public
from . import ui
from .gitutils import get_cwd_repo, secure_git_clone

from rich.panel import Panel
from rich.align import Align
from rich.text import Text
from rich import box

console = ui.console


def clear():
    os.system("clear" if os.name != "nt" else "cls")


def _get_style():
    return ui.get_questionary_style()


custom_style = _get_style()


def _pause():
    p = ui.get_palette()
    style = _get_style()
    questionary.press_any_key_to_continue("Pressione ENTER para continuar...", style=style).ask()


def _safe_ask(fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs).ask()
        return result
    except KeyboardInterrupt:
        return None


def _get_client_or_none(require: bool = True):
    token = get_token()
    if not token:
        if require:
            p = ui.get_palette()
            ui.warning("Você não está autenticado.", title="🔒 Login necessário")
            console.print(f"[{p['muted']}]  Dica: crie o token em https://github.com/settings/tokens  •  precisa de repo + read:org[/]")
            choice = _safe_ask(questionary.confirm, "Deseja fazer login agora?", default=True, style=_get_style(), qmark="◆")
            if choice:
                handle_auth_login()
                token = get_token()
            if not token:
                return None
        else:
            return None
    return GitHubClient(token) if token else None


# ---------- AUTH ----------
def handle_auth_login():
    clear()
    ui.show_header("Autenticação", "Login GitHub • token PAT")
    p = ui.get_palette()
    console.print(ui.info_panel("🔐 Login GitHub", f"Crie seu token em: [link=https://github.com/settings/tokens]https://github.com/settings/tokens[/]\n[dim]Scopes: repo, read:org  •  Token salvo em {CONFIG_FILE} (chmod 600)[/dim]", border_color=p["primary"]))
    console.print()
    token = _safe_ask(questionary.password, "🔑 Cole seu GitHub Token:", style=_get_style(), qmark="◆")
    if not token:
        ui.warning("Cancelado.")
        _pause()
        return
    try:
        client = GitHubClient(token)
        with console.status(f"[bold {p['primary']}]Validando token...[/]", spinner="dots12"):
            user = client.get_user()
        save_token(token)
        clear()
        ui.show_header("Autenticado", f"bem-vindo {user['login']}")
        ui.success(f"Autenticado como [bold]{user['login']}[/]!", title="✓ Bem-vindo")
        console.print(f"[{p['muted']}]  Token salvo em {CONFIG_FILE}[/]")
        console.print()
        console.print(ui.auth_panel(user))
    except requests.HTTPError as e:
        ui.error(f"Erro ao validar token: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text[:400]}[/dim]")
    except Exception as e:
        ui.error(str(e))
    console.print()
    _pause()


def handle_auth_logout():
    clear()
    ui.show_header("Logout", "Remover token salvo")
    p = ui.get_palette()
    token = get_token()
    if not token and not CONFIG_FILE.exists():
        ui.warning("Você já não está logado (sem token salvo).")
        if os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN"):
            console.print(f"[{p['warning']}]⚠ Mas existe GITHUB_TOKEN/GH_TOKEN no env — remova do shell.[/]")
        _pause()
        return
    console.print(ui.info_panel("🚪 Confirmar logout", f"Vamos remover o token de [{p['fg_bold']}]{CONFIG_FILE}[/]  [dim](preserva [ui] tema)[/dim]", border_color=p["warning"]))
    confirm = _safe_ask(questionary.confirm, f"Remover token salvo em {CONFIG_FILE}?", default=False, style=_get_style(), qmark="◆")
    if not confirm:
        console.print("[dim]Cancelado[/dim]")
        _pause()
        return
    if delete_token():
        ui.success(f"Token removido de {CONFIG_FILE}", title="✓ Logout")
    else:
        ui.warning("Nenhum token salvo encontrado.")
    _pause()


def handle_auth_status():
    clear()
    ui.show_header("Status", "Quem está logado agora")
    p = ui.get_palette()
    token = get_token()
    if not token:
        ui.error("Não autenticado. Rode login.", title="Offline")
        console.print(f"[{p['muted']}]  Dica: [bold]hubctl auth login[/] ou defina [bold]GITHUB_TOKEN[/] no env[/]")
        _pause()
        return
    try:
        client = GitHubClient(token)
        with console.status(f"[bold {p['primary']}]Buscando seu perfil...[/]", spinner="dots12"):
            user = client.get_user()
        console.print(ui.user_profile_panel(user, is_self=True))
        console.print()
        src = "env GITHUB_TOKEN" if os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") else str(CONFIG_FILE)
        console.print(f"  [{p['muted']}]Token:[/] [{p['fg_bold']}]{src}[/]  [dim]•[/]  [{p['muted']}]Tema:[/] {ui.get_effective_theme_name()}")
        # extra compacto: top repos em 1 linha
        try:
            with console.status(f"[dim]Buscando seus repos...[/]", spinner="dots12"):
                repos = client.list_repos(limit=3, sort="updated")
            if repos:
                console.print()
                console.print(ui.repo_table(f"Recentes • {len(repos)}", repos))
        except Exception:
            pass
    except Exception as e:
        ui.error(str(e))
    console.print()
    _pause()


# ---------- HELPERS ----------
def _choose_visibility():
    vis = _safe_ask(questionary.select, "Visibilidade:", choices=["all", "public", "private"], style=_get_style(), qmark="◆", pointer="▶")
    return vis or "all"


def _choose_limit(default=20):
    p = ui.get_palette()
    val = _safe_ask(questionary.text, f"Quantos? (padrão {default}):", style=_get_style(), qmark="◆")
    if not val or val.strip() == "":
        return default
    try:
        return int(val)
    except ValueError:
        ui.warning("Valor inválido, usando padrão.")
        return default


def _choose_state():
    state = _safe_ask(questionary.select, "Estado:", choices=["open", "closed", "all"], style=_get_style(), qmark="◆", pointer="▶")
    return state or "open"


def _select_repo_interactively(repos):
    if not repos:
        return None
    choices = [f"{r['full_name']}  {'🔒' if r['private'] else '🌍'}  ⭐{r['stargazers_count']}  🍴{r.get('forks_count',0)}  {(r['description'] or '')[:35]}" for r in repos]
    choices.append(questionary.Separator("─────────────────"))
    choices.append("✏️  Digitar manualmente")
    choices.append("↩️  Cancelar")
    sel = _safe_ask(questionary.select, "Selecione um repositório:", choices=choices, style=_get_style(), qmark="◆", pointer="▶", instruction="(↑/↓ + ENTER)")
    if sel is None or sel == "↩️  Cancelar":
        return None
    if sel == "✏️  Digitar manualmente":
        manual = _safe_ask(questionary.text, "Digite usuario/repo:", style=_get_style(), qmark="◆")
        return manual
    return sel.split()[0]


def _pick_repo_or_input(client):
    # 1. cwd repo (git remote) tem prioridade — como sweeo mostra cwd
    cwd_repo = get_cwd_repo()
    if cwd_repo:
        if _safe_ask(questionary.confirm, f"Usar repo do diretório atual ({cwd_repo})?", default=True, style=_get_style(), qmark="◆"):
            try:
                save_recent(cwd_repo)
            except Exception:
                pass
            return cwd_repo
    # 2. recentes (últimos 5)
    recents = get_recents(limit=5)
    if recents:
        choices = [f"{r}  📌 recente" for r in recents]
        choices.append(questionary.Separator("─────────────────"))
        choices.append("📋  Buscar na sua lista de repos")
        choices.append("✏️  Digitar manualmente")
        choices.append("↩️  Cancelar")
        sel = _safe_ask(questionary.select, "Recentes ou digitar:", choices=choices, style=_get_style(), qmark="◆", pointer="▶")
        if sel and "recente" in sel:
            repo = sel.split()[0]
            try:
                save_recent(repo)
            except Exception:
                pass
            return repo
        if sel == "📋  Buscar na sua lista de repos":
            if client:
                try:
                    p = ui.get_palette()
                    with console.status(f"[bold {p['primary']}]Carregando seus repos...[/]", spinner="dots12"):
                        repos = client.list_repos(limit=20, visibility="all")
                    if repos:
                        return _select_repo_interactively(repos)
                except Exception:
                    pass
            return _safe_ask(questionary.text, "Digite usuario/repo (ex: octocat/Hello-World):", style=_get_style(), qmark="◆")
        if sel == "✏️  Digitar manualmente":
            manual = _safe_ask(questionary.text, "Digite usuario/repo:", style=_get_style(), qmark="◆")
            if manual:
                try:
                    save_recent(manual)
                except Exception:
                    pass
            return manual
        if sel is None or sel == "↩️  Cancelar":
            return None
    # 3. lista completa como fallback
    if client:
        try:
            p = ui.get_palette()
            with console.status(f"[bold {p['primary']}]Carregando seus repos...[/]", spinner="dots12"):
                repos = client.list_repos(limit=20, visibility="all")
            if repos:
                use_list = _safe_ask(questionary.confirm, "Escolher da sua lista de repos?", default=True, style=_get_style(), qmark="◆")
                if use_list:
                    chosen = _select_repo_interactively(repos)
                    if chosen:
                        try:
                            save_recent(chosen)
                        except Exception:
                            pass
                    return chosen
        except Exception:
            pass
    manual = _safe_ask(questionary.text, "Digite usuario/repo (ex: octocat/Hello-World):", style=_get_style(), qmark="◆")
    if manual:
        try:
            save_recent(manual)
        except Exception:
            pass
    return manual


def _has_admin_access(client, repo: dict) -> bool:
    if not client:
        return False
    perms = repo.get("permissions")
    if perms is not None:
        return bool(perms.get("admin"))
    try:
        owner_login = repo.get("owner", {}).get("login")
        if not owner_login:
            owner_login = repo.get("full_name", "").split("/")[0]
        user = client.get_user()
        return user.get("login", "").lower() == owner_login.lower()
    except Exception:
        return False


# ---------- REPO ----------
def handle_repo_list():
    client = _get_client_or_none()
    if not client:
        _pause()
        return
    clear()
    ui.show_header("Repositórios", "Listar com filtro de visibilidade")
    p = ui.get_palette()
    visibility = _choose_visibility()
    if visibility is None:
        return
    limit = _choose_limit(20)
    try:
        with console.status(f"[bold {p['primary']}]Buscando repos ({visibility})...[/]", spinner="dots12"):
            repos = client.list_repos(limit=limit, visibility=visibility)
    except Exception as e:
        ui.error(str(e))
        _pause()
        return
    if not repos:
        ui.warning("Nenhum repositório encontrado.", title="Vazio")
        _pause()
        return
    clear()
    ui.show_header("Seus Repositórios", f"{visibility} • {len(repos)} encontrados")
    console.print(ui.repo_table(f"Seus Repositórios • {visibility} • {len(repos)}", repos))
    console.print()
    console.print(f"[{p['muted']}]  Dica: selecione uma ação rápida abaixo para navegar sem digitar usuario/repo[/]")
    console.print()
    action = _safe_ask(questionary.select, "O que deseja fazer?",
        choices=["↩️  Voltar", "👁️  Ver detalhes", "📥 Clonar", "🍴 Fork", "⭐ Star/Unstar", "🐛 Issues", "🔀 PRs"],
        style=_get_style(), qmark="◆", pointer="▶", instruction="↑↓ navega • ENTER seleciona")
    if action == "👁️  Ver detalhes":
        full_name = _select_repo_interactively(repos)
        if full_name: handle_repo_view(prefilled=full_name)
        else: _pause()
    elif action == "📥 Clonar":
        full_name = _select_repo_interactively(repos)
        if full_name: handle_repo_clone(prefilled=full_name)
        else: _pause()
    elif action == "🍴 Fork":
        full_name = _select_repo_interactively(repos)
        if full_name: handle_repo_fork(prefilled=full_name)
        else: _pause()
    elif action == "⭐ Star/Unstar":
        full_name = _select_repo_interactively(repos)
        if full_name: handle_repo_star_toggle(prefilled=full_name)
        else: _pause()
    elif action == "🐛 Issues":
        full_name = _select_repo_interactively(repos)
        if full_name: handle_issue_list(prefilled=full_name)
        else: _pause()
    elif action == "🔀 PRs":
        full_name = _select_repo_interactively(repos)
        if full_name: handle_pr_list(prefilled=full_name)
        else: _pause()
    else:
        _pause()


def handle_repo_view(prefilled: str | None = None):
    client = _get_client_or_none(require=False)
    full_name = prefilled or _pick_repo_or_input(client if client else None)
    if not full_name or full_name == "↩️  Cancelar":
        console.print("[dim]Cancelado[/dim]")
        _pause()
        return
    try:
        save_recent(full_name)
    except Exception:
        pass
    p = ui.get_palette()
    clear()
    ui.show_header("Detalhes do Repo", full_name)
    console.print(f"[{p['muted']}]  Buscando informações + README...[/]\n")
    try:
        if client:
            with console.status(f"[bold {p['primary']}]Buscando {full_name}...[/]", spinner="dots12"):
                r = client.get_repo(full_name)
                try:
                    starred = client.check_starred(full_name)
                    r["_starred"] = starred
                except: r["_starred"] = False
        else:
            with console.status(f"[dim]Buscando {full_name}...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}", headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                r = resp.json()
                r["_starred"] = False
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            ui.error(f"Repo '{full_name}' não encontrado", title="404")
        else:
            ui.error(str(e))
        _pause()
        return
    except Exception as e:
        ui.error(str(e))
        _pause()
        return

    console.print(ui.detail_panel(r))
    console.print()
    star_str = f"[{p['warning']}]⭐ Starred[/]" if r.get("_starred") else f"[{p['muted']}]☆ Não starred[/]"
    console.print(f"  {star_str}  [dim]•  {r.get('language') or '—'}  •  updated {r.get('updated_at','')[:10]}[/]")
    console.print()

    readme_text = None
    try:
        if client:
            with console.status(f"[dim]Buscando README.md...[/]", spinner="dots12"):
                readme_text = client.get_readme(full_name)
        else:
            with console.status(f"[dim]Buscando README.md...[/]", spinner="dots12"):
                readme_text = fetch_readme_public(full_name)
    except Exception:
        readme_text = None
    console.print(ui.readme_panel(full_name, readme_text))
    console.print()

    can_admin = _has_admin_access(client, r)
    if not can_admin and client:
        console.print(f"[{p['muted2']}]  ℹ {r.get('owner',{}).get('login','')} / permissão leitura — Editar/Deletar ocultos (só dono vê)[/]")
        console.print()
    owner_login = r.get("owner", {}).get("login") or r.get("full_name", "").split("/")[0] if r.get("full_name") else ""
    choices = ["↩️  Voltar", "📥 Clonar", "🍴 Fork", "⭐ Toggle Star"]
    if owner_login:
        choices.append(f"👤 Ver perfil de {owner_login}")
    if can_admin:
        choices.append("✏️  Editar")
    choices.extend(["🐛 Issues", "🔀 PRs"])
    if can_admin:
        choices.append("🗑️  Deletar")
    action = _safe_ask(questionary.select, f"Ações para {full_name}:", choices=choices, style=_get_style(), qmark="◆", pointer="▶", instruction="↑↓ + ENTER")
    if action == "📥 Clonar":
        handle_repo_clone(prefilled=full_name)
    elif action == "🍴 Fork":
        handle_repo_fork(prefilled=full_name)
    elif action == "⭐ Toggle Star":
        handle_repo_star_toggle(prefilled=full_name)
    elif action and "Ver perfil de" in action:
        handle_user_view(prefilled=owner_login)
    elif action == "✏️  Editar":
        handle_repo_edit(prefilled=full_name)
    elif action == "🐛 Issues":
        handle_issue_list(prefilled=full_name)
    elif action == "🔀 PRs":
        handle_pr_list(prefilled=full_name)
    elif action == "🗑️  Deletar":
        handle_repo_delete(prefilled=full_name)
    else:
        _pause()


def handle_repo_create():
    client = _get_client_or_none()
    if not client:
        _pause()
        return
    clear()
    ui.show_header("Criar Repositório", "Novo repo na sua conta")
    p = ui.get_palette()
    name = _safe_ask(questionary.text, "📦 Nome do novo repositório:", style=_get_style(), qmark="◆")
    if not name:
        ui.warning("Nome não pode ser vazio.")
        _pause()
        return
    description = _safe_ask(questionary.text, "📝 Descrição (opcional):", style=_get_style(), qmark="◆") or ""
    private = _safe_ask(questionary.confirm, "🔒 Privado?", default=False, style=_get_style(), qmark="◆")
    if private is None:
        _pause()
        return
    console.print()
    console.print(ui.info_panel("Confirmar criação", f"[bold {p['fg_bold']}]{name}[/]  {'🔒 privado' if private else '🌍 público'}\n[dim]{description or 'sem descrição'}[/]", border_color=p["primary"]))
    confirm = _safe_ask(questionary.confirm, f"Criar repo '{name}' {'🔒 privado' if private else '🌍 público'}?", default=True, style=_get_style(), qmark="◆")
    if not confirm:
        console.print("[dim]Cancelado[/dim]")
        _pause()
        return
    try:
        with console.status(f"[bold {p['secondary']}]Criando repositório...[/]", spinner="dots12"):
            r = client.create_repo(name, private=private, description=description)
        ui.success(f"Repo criado: [bold]{r['full_name']}[/]\n🔗 {r['html_url']}", title="✓ Criado")
        console.print(f"[dim]  Clone: hubctl repo clone {r['full_name']}[/]")
    except requests.HTTPError as e:
        ui.error(f"Erro ao criar: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text}[/dim]")
    except Exception as e:
        ui.error(str(e))
    console.print()
    _pause()


def handle_repo_delete(prefilled: str | None = None):
    client = _get_client_or_none()
    if not client:
        _pause()
        return
    full_name = prefilled or _pick_repo_or_input(client)
    if not full_name or full_name == "↩️  Cancelar":
        console.print("[dim]Cancelado[/dim]")
        _pause()
        return
    clear()
    ui.show_header("Deletar Repositório", f"{full_name} • IRREVERSÍVEL")
    p = ui.get_palette()
    console.print(ui.info_panel("⚠️  Zona de perigo", f"Você vai deletar [bold {p['error']}]{full_name}[/] permanentemente!\n[dim]Todos os commits, issues e PRs serão perdidos.[/dim]", border_color=p["error"]))
    console.print()
    ui.warning(f"Você vai deletar [bold]{full_name}[/] permanentemente!", title="⚠️  IRREVERSÍVEL")
    confirm1 = _safe_ask(questionary.confirm, f"Tem certeza que quer deletar {full_name}?", default=False, style=_get_style(), qmark="◆")
    if not confirm1:
        console.print("[dim]Cancelado[/dim]")
        _pause()
        return
    typed = _safe_ask(questionary.text, f"Digite '{full_name}' para confirmar:", style=_get_style(), qmark="◆")
    if typed != full_name:
        ui.error("Nomes não batem. Cancelado.")
        _pause()
        return
    try:
        with console.status(f"[bold {p['error']}]Deletando {full_name}...[/]", spinner="dots12"):
            client.delete_repo(full_name)
        ui.success(f"Repo {full_name} deletado", title="🗑️  Removido")
    except requests.HTTPError as e:
        ui.error(str(e))
        if e.response is not None:
            console.print(f"[dim]{e.response.text}[/dim]")
    except Exception as e:
        ui.error(str(e))
    _pause()


def handle_repo_clone(prefilled: str | None = None):
    token = get_token()
    client = GitHubClient(token) if token else None
    full_name = prefilled or _pick_repo_or_input(client)
    if not full_name or full_name == "↩️  Cancelar":
        console.print("[dim]Cancelado[/dim]")
        _pause()
        return
    if shutil.which("git") is None:
        ui.error("git não encontrado. Instale o git.")
        _pause()
        return
    clear()
    ui.show_header("Clonar Repositório", full_name)
    p = ui.get_palette()
    proto = _safe_ask(questionary.select, "Protocolo:", choices=["🌐 HTTPS (recomendado)", "🔑 SSH (precisa chave)"], style=_get_style(), qmark="◆", pointer="▶")
    if proto is None:
        _pause()
        return
    use_ssh = "SSH" in proto
    dest_default = full_name.split("/")[-1]
    dest_input = _safe_ask(questionary.text, f"📁 Diretório destino (padrão: ./{dest_default}):", style=_get_style(), qmark="◆")
    dest = Path(dest_input.strip()) if dest_input and dest_input.strip() else Path(dest_default)
    if dest.exists():
        ui.error(f"Destino '{dest}' já existe")
        _pause()
        return
    try:
        if token:
            with console.status(f"[bold {p['primary']}]Buscando {full_name}...[/]", spinner="dots12"):
                r = GitHubClient(token).get_repo(full_name)
        else:
            with console.status(f"[dim]Buscando {full_name}...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}", headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                r = resp.json()
        clone_url = r.get("clone_url")
        ssh_url = r.get("ssh_url")
        is_private = r.get("private", False)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            ui.error(f"Repo '{full_name}' não encontrado", title="404")
        elif e.response is not None and e.response.status_code == 401:
            ui.error("Não autorizado. Repo privado? Faça login.")
        else:
            ui.error(str(e))
        _pause()
        return
    except Exception as e:
        ui.error(str(e))
        _pause()
        return

    base_url = clone_url or f"https://github.com/{full_name}.git"
    safe_display = ssh_url if use_ssh else base_url
    console.print()
    console.print(ui.info_panel("⬇ Clonando", f"[bold {p['primary']}]{full_name}[/] → [bold]{dest}[/]  {'(SSH)' if use_ssh else '(HTTPS)'}\n[dim]{safe_display}[/]", border_color=p["primary"]))
    console.print()
    rc = secure_git_clone(base_url, dest, token, is_private=is_private, ssh=use_ssh, ssh_url=ssh_url)
    if rc == 0:
        console.print()
        ui.success(f"Clonado em [bold]{dest.resolve()}[/]", title="✓ Clone ok")
        console.print(f"[{p['muted']}]  cd {dest} && code .[/]")
    else:
        ui.error(f"git clone falhou (código {rc})")
    _pause()


def handle_repo_fork(prefilled: str | None = None):
    client = _get_client_or_none()
    if not client:
        _pause()
        return
    full_name = prefilled or _safe_ask(questionary.text, "Digite usuario/repo para fork:", style=_get_style(), qmark="◆")
    if not full_name:
        _pause()
        return
    clear()
    ui.show_header("Fork", full_name)
    p = ui.get_palette()
    try:
        with console.status(f"[bold {p['secondary']}]Fazendo fork de {full_name}...[/]", spinner="dots12"):
            r = client.fork_repo(full_name)
        ui.success(f"Fork criado! [bold]{r['full_name']}[/]\n🔗 {r['html_url']}", title="🍴 Fork ok")
        console.print(f"[dim]  Clone depois: hubctl repo clone {r['full_name']}[/dim]")
        console.print()
        clone = _safe_ask(questionary.confirm, "Deseja clonar o fork agora?", default=True, style=_get_style(), qmark="◆")
        if clone:
            handle_repo_clone(prefilled=r['full_name'])
        else:
            _pause()
    except requests.HTTPError as e:
        ui.error(f"Erro ao fazer fork: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text[:600]}[/dim]")
            if e.response.status_code == 409:
                console.print("[yellow]Já existe fork seu?[/yellow]")
        _pause()
    except Exception as e:
        ui.error(str(e))
        _pause()


def handle_repo_star_toggle(prefilled: str | None = None):
    client = _get_client_or_none()
    if not client:
        _pause()
        return
    full_name = prefilled or _safe_ask(questionary.text, "Digite usuario/repo:", style=_get_style(), qmark="◆")
    if not full_name:
        _pause()
        return
    clear()
    ui.show_header("Star", full_name)
    p = ui.get_palette()
    try:
        with console.status(f"[dim]Verificando star de {full_name}...[/]", spinner="dots12"):
            starred = client.check_starred(full_name)
        if starred:
            console.print(f"[{p['warning']}]⭐ Você já deu star em {full_name}[/]")
            console.print()
            if _safe_ask(questionary.confirm, "Remover star?", default=False, style=_get_style(), qmark="◆"):
                with console.status("[dim]Removendo star...[/]", spinner="dots12"):
                    client.unstar_repo(full_name)
                ui.success(f"Star removido de {full_name}")
            _pause()
        else:
            with console.status(f"[bold {p['warning']}]Dando star em {full_name}...[/]", spinner="dots12"):
                client.star_repo(full_name)
            ui.success(f"⭐ Star em {full_name}!", title="Favoritado")
            _pause()
    except Exception as e:
        ui.error(str(e))
        _pause()


def handle_repo_edit(prefilled: str | None = None):
    client = _get_client_or_none()
    if not client:
        _pause()
        return
    full_name = prefilled or _pick_repo_or_input(client)
    if not full_name:
        _pause()
        return
    clear()
    ui.show_header("Editar Repo", full_name)
    p = ui.get_palette()
    try:
        with console.status(f"[dim]Buscando {full_name}...[/]", spinner="dots12"):
            r = client.get_repo(full_name)
    except Exception as e:
        ui.error(str(e))
        _pause()
        return
    console.print(ui.detail_panel(r))
    console.print()
    field = _safe_ask(questionary.select, "O que editar?",
        choices=["📝 Descrição", "🏠 Homepage", "🔒 Visibilidade (privado/público)", "↩️  Cancelar"],
        style=_get_style(), qmark="◆", pointer="▶")
    if not field or field == "↩️  Cancelar":
        _pause()
        return
    data = {}
    if "Descrição" in field:
        new_desc = _safe_ask(questionary.text, "Nova descrição:", default=r.get("description") or "", style=_get_style(), qmark="◆")
        if new_desc is not None:
            data["description"] = new_desc
    elif "Homepage" in field:
        new_home = _safe_ask(questionary.text, "Nova homepage:", default=r.get("homepage") or "", style=_get_style(), qmark="◆")
        if new_home is not None:
            data["homepage"] = new_home
    elif "Visibilidade" in field:
        is_private = r.get("private", False)
        console.print(f"[dim]Atual: {'🔒 privado' if is_private else '🌍 público'}[/dim]")
        new_private = _safe_ask(questionary.select, "Tornar:", choices=["🌍 Público", "🔒 Privado"], style=_get_style(), qmark="◆", pointer="▶")
        if new_private:
            data["private"] = "Privado" in new_private

    if not data:
        _pause()
        return
    try:
        with console.status(f"[bold {p['primary']}]Atualizando {full_name}...[/]", spinner="dots12"):
            updated = client.update_repo(full_name, **data)
        ui.success(f"Atualizado [bold]{updated['full_name']}[/]\n[dim]{updated.get('description') or ''}[/]", title="✓ Editado")
    except Exception as e:
        ui.error(str(e))
    _pause()


def handle_repo_search():
    token = get_token()
    clear()
    ui.show_header("Buscar Repos", "Filtro por user + termos • stars sort")
    p = ui.get_palette()
    console.print(f"[{p['muted']}]  Exemplos: [bold]cli[/]  •  [bold]language:python stars:>5000[/]  •  [bold]user:octocat[/][/]")
    console.print()
    user_filter = _safe_ask(questionary.text, "👤 Filtrar por usuário/org? (ex: octocat, deixe vazio para busca global):", style=_get_style(), qmark="◆")
    if user_filter is None:
        _pause()
        return
    user_filter = user_filter.strip()
    query = _safe_ask(questionary.text, "🔍 Termos da busca (ex: 'cli language:python', vazio lista tudo do usuário se filtrou):", style=_get_style(), qmark="◆")
    if query is None:
        _pause()
        return
    query = query.strip() if query else ""
    effective_query = query
    if user_filter:
        effective_query = f"user:{user_filter} {query}".strip()
    if not effective_query:
        ui.warning("Informe um termo de busca ou um usuário para filtrar. Ex: user:octocat ou 'cli' + user:octocat")
        _pause()
        return
    if user_filter:
        console.print(f"\n[{p['muted']}]  🔎 Busca: '[{p['fg_bold']}]{effective_query}[/]' (filtro usuário: {user_filter})[/]")
    limit = _choose_limit(10)
    try:
        if token:
            client = GitHubClient(token)
            with console.status(f"[bold {p['primary']}]Buscando '{effective_query}'...[/]", spinner="dots12"):
                result = client.search_repos(effective_query, limit=limit)
        else:
            with console.status(f"[dim]Buscando '{effective_query}'...[/]", spinner="dots12"):
                resp = requests.get("https://api.github.com/search/repositories", params={"q": effective_query, "per_page": limit}, headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                result = resp.json()
    except Exception as e:
        ui.error(str(e))
        _pause()
        return
    items = result.get("items", [])
    total = result.get("total_count", len(items))
    if not items:
        ui.warning(f"Nenhum resultado para '{effective_query}'")
        _pause()
        return
    clear()
    ui.show_header("Resultado da Busca", f"'{effective_query}' • {total} encontrados")
    console.print(ui.repo_table(f"Busca: '{effective_query}' • {total} resultados (mostrando {len(items)})", items))
    console.print()
    action = _safe_ask(questionary.select, "O que fazer? (Ver detalhes já mostra info + opção Clonar)",
        choices=["↩️  Voltar", "👁️  Ver detalhes (+ clonar/fork/star)", "📥 Clonar direto", "🍴 Fork", "⭐ Star"],
        style=_get_style(), qmark="◆", pointer="▶")
    if action == "👁️  Ver detalhes (+ clonar/fork/star)":
        sel = _select_repo_interactively(items)
        if sel: handle_repo_view(prefilled=sel)
        else: _pause()
    elif action == "📥 Clonar direto":
        sel = _select_repo_interactively(items)
        if sel: handle_repo_clone(prefilled=sel)
        else: _pause()
    elif action == "🍴 Fork":
        sel = _select_repo_interactively(items)
        if sel: handle_repo_fork(prefilled=sel)
        else: _pause()
    elif action == "⭐ Star":
        sel = _select_repo_interactively(items)
        if sel: handle_repo_star_toggle(prefilled=sel)
        else: _pause()
    else:
        _pause()


# ---------- ISSUE / PR ----------
def handle_issue_list(prefilled: str | None = None):
    client = _get_client_or_none(require=False)
    full_name = prefilled or _pick_repo_or_input(client if client else None)
    if not full_name or full_name == "↩️  Cancelar":
        _pause()
        return
    clear()
    ui.show_header("Issues", full_name)
    p = ui.get_palette()
    state = _choose_state()
    limit = _choose_limit(20)
    try:
        if client:
            with console.status(f"[bold {p['primary']}]Buscando issues de {full_name}...[/]", spinner="dots12"):
                issues = client.list_issues(full_name, state=state, limit=limit)
        else:
            with console.status(f"[dim]Buscando issues de {full_name}...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}/issues", params={"state": state, "per_page": limit}, headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                issues = resp.json()
        issues = [i for i in issues if "pull_request" not in i]
    except Exception as e:
        ui.error(str(e))
        _pause()
        return
    if not issues:
        ui.warning("Nenhuma issue encontrada", title="Vazio")
        _pause()
        return
    console.print(ui.issue_table(f"Issues • {full_name} • {state}", issues))
    console.print()
    choices = [f"#{i['number']} • {i['title'][:45]}  [{i['state']}]" for i in issues[:10]]
    choices += ["↩️  Voltar", "➕ Criar nova issue"]
    sel = _safe_ask(questionary.select, "Ver detalhes ou criar?", choices=choices, style=_get_style(), qmark="◆", pointer="▶")
    if sel == "➕ Criar nova issue":
        handle_issue_create(prefilled=full_name)
    elif sel and sel != "↩️  Voltar":
        num = int(sel.split()[0][1:])
        handle_issue_view(prefilled=full_name, number=num)
    else:
        _pause()


def handle_issue_view(prefilled: str | None = None, number: int | None = None):
    client = _get_client_or_none(require=False)
    full_name = prefilled or _pick_repo_or_input(client if client else None)
    if not full_name:
        _pause()
        return
    if number is None:
        num_str = _safe_ask(questionary.text, "Número da issue:", style=_get_style(), qmark="◆")
        if not num_str: _pause(); return
        try: number = int(num_str)
        except: ui.error("Número inválido"); _pause(); return
    clear()
    ui.show_header(f"Issue #{number}", full_name)
    p = ui.get_palette()
    try:
        if client:
            with console.status(f"[bold {p['primary']}]Buscando issue #{number}...[/]", spinner="dots12"):
                issue = client.get_issue(full_name, number)
        else:
            with console.status(f"[dim]Buscando issue #{number}...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}/issues/{number}", headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                issue = resp.json()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            ui.error(f"Issue #{number} não encontrada em {full_name}")
        else:
            ui.error(str(e))
        _pause()
        return
    except Exception as e:
        ui.error(str(e))
        _pause()
        return
    state = issue["state"]
    color = p["success"] if state == "open" else p["error"]
    labels = "  ".join(f"[{p['secondary']}]#{l['name']}[/]" for l in issue.get("labels", [])) or "[dim]sem labels[/dim]"
    console.print(ui.info_panel(
        f"#{issue['number']} • {issue['title']}",
        f"[bold {color}]● {state.upper()}[/]  por [bold]{issue['user']['login']}[/]  em {issue['created_at'][:10]}  •  💬 {issue['comments']}\n"
        f"[dim]{labels}[/]\n\n"
        f"{issue.get('body') or '[dim]Sem descrição[/dim]'}\n\n"
        f"[dim]🔗 {issue['html_url']}[/]",
        border_color=color
    ))
    console.print()
    action = _safe_ask(questionary.select, "Ação:", choices=["↩️  Voltar", "🔒 Fechar issue"], style=_get_style(), qmark="◆", pointer="▶")
    if action == "🔒 Fechar issue" and state == "open":
        handle_issue_close(prefilled=full_name, number=number)
    else:
        _pause()


def handle_issue_create(prefilled: str | None = None):
    client = _get_client_or_none()
    if not client:
        _pause()
        return
    full_name = prefilled or _pick_repo_or_input(client)
    if not full_name:
        _pause()
        return
    clear()
    ui.show_header("Criar Issue", full_name)
    title = _safe_ask(questionary.text, "🐛 Título da issue:", style=_get_style(), qmark="◆")
    if not title:
        ui.warning("Título não pode ser vazio")
        _pause()
        return
    body = _safe_ask(questionary.text, "📝 Descrição (opcional):", style=_get_style(), qmark="◆") or ""
    labels_str = _safe_ask(questionary.text, "🏷️  Labels separados por vírgula (opcional):", style=_get_style(), qmark="◆") or ""
    labels = [s.strip() for s in labels_str.split(",") if s.strip()] or None
    p = ui.get_palette()
    try:
        with console.status(f"[bold {p['secondary']}]Criando issue...[/]", spinner="dots12"):
            issue = client.create_issue(full_name, title=title, body=body, labels=labels)
        ui.success(f"Issue criada: [bold]#{issue['number']} {issue['title']}[/]\n🔗 {issue['html_url']}", title="🐛 Criada")
    except requests.HTTPError as e:
        ui.error(f"Erro ao criar issue: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text}[/dim]")
    except Exception as e:
        ui.error(str(e))
    _pause()


def handle_issue_close(prefilled: str | None = None, number: int | None = None):
    client = _get_client_or_none()
    if not client:
        _pause()
        return
    full_name = prefilled or _pick_repo_or_input(client)
    if not full_name:
        _pause()
        return
    if number is None:
        num_str = _safe_ask(questionary.text, "Número da issue para fechar:", style=_get_style(), qmark="◆")
        if not num_str: _pause(); return
        try: number = int(num_str)
        except: ui.error("Número inválido"); _pause(); return
    clear()
    ui.show_header(f"Fechar Issue #{number}", full_name)
    if not _safe_ask(questionary.confirm, f"Fechar issue #{number} em {full_name}?", default=False, style=_get_style(), qmark="◆"):
        console.print("[dim]Cancelado[/dim]")
        _pause()
        return
    p = ui.get_palette()
    try:
        with console.status(f"[bold {p['error']}]Fechando #{number}...[/]", spinner="dots12"):
            issue = client.close_issue(full_name, number)
        ui.success(f"Issue #{issue['number']} fechada", title="✓ Fechada")
    except Exception as e:
        ui.error(str(e))
    _pause()


def handle_pr_list(prefilled: str | None = None):
    client = _get_client_or_none(require=False)
    full_name = prefilled or _pick_repo_or_input(client if client else None)
    if not full_name or full_name == "↩️  Cancelar":
        _pause()
        return
    clear()
    ui.show_header("Pull Requests", full_name)
    p = ui.get_palette()
    state = _choose_state()
    limit = _choose_limit(20)
    try:
        if client:
            with console.status(f"[bold {p['secondary']}]Buscando PRs de {full_name}...[/]", spinner="dots12"):
                prs = client.list_prs(full_name, state=state, limit=limit)
        else:
            with console.status(f"[dim]Buscando PRs de {full_name}...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}/pulls", params={"state": state, "per_page": limit}, headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                prs = resp.json()
    except Exception as e:
        ui.error(str(e))
        _pause()
        return
    if not prs:
        ui.warning("Nenhum PR encontrado", title="Vazio")
        _pause()
        return
    console.print(ui.pr_table(f"Pull Requests • {full_name} • {state}", prs))
    console.print()
    choices = [f"#{pr['number']} • {pr['title'][:40]}  [{pr['state']}]" for pr in prs[:10]]
    choices += ["↩️  Voltar", "➕ Criar novo PR"]
    sel = _safe_ask(questionary.select, "Ver detalhes ou criar?", choices=choices, style=_get_style(), qmark="◆", pointer="▶")
    if sel == "➕ Criar novo PR":
        handle_pr_create(prefilled=full_name)
    elif sel and sel != "↩️  Voltar":
        num = int(sel.split()[0][1:])
        handle_pr_view(prefilled=full_name, number=num)
    else:
        _pause()


def handle_pr_view(prefilled: str | None = None, number: int | None = None):
    client = _get_client_or_none(require=False)
    full_name = prefilled or _pick_repo_or_input(client if client else None)
    if not full_name:
        _pause()
        return
    if number is None:
        num_str = _safe_ask(questionary.text, "Número do PR:", style=_get_style(), qmark="◆")
        if not num_str: _pause(); return
        try: number = int(num_str)
        except: ui.error("Número inválido"); _pause(); return
    clear()
    ui.show_header(f"PR #{number}", full_name)
    p = ui.get_palette()
    try:
        if client:
            with console.status(f"[bold {p['secondary']}]Buscando PR #{number}...[/]", spinner="dots12"):
                pr = client.get_pr(full_name, number)
        else:
            with console.status(f"[dim]Buscando PR #{number}...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}/pulls/{number}", headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                pr = resp.json()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            ui.error(f"PR #{number} não encontrado em {full_name}")
        else:
            ui.error(str(e))
        _pause()
        return
    except Exception as e:
        ui.error(str(e))
        _pause()
        return
    state = pr["state"]
    merged = pr.get("merged", False)
    if merged:
        color = p["secondary"]
        state_str = "MERGED"
    elif state == "open":
        color = p["success"]
        state_str = "OPEN"
    else:
        color = p["error"]
        state_str = state.upper()
    console.print(ui.info_panel(
        f"#{pr['number']} • {pr['title']}",
        f"[bold {color}]● {state_str}[/]  por [bold]{pr['user']['login']}[/]  em {pr['created_at'][:10]}\n"
        f"[{p['primary']}]{pr['head']['ref']}[/] → [bold]{pr['base']['ref']}[/]  •  💬 {pr.get('comments',0)}  •  ✅ {pr.get('additions',0)}++ / ❌ {pr.get('deletions',0)}--  •  📄 {pr.get('changed_files',0)} arquivos\n\n"
        f"{pr.get('body') or '[dim]Sem descrição[/dim]'}\n\n"
        f"[dim]🔗 {pr['html_url']}[/]",
        border_color=color
    ))
    console.print()
    _pause()


def handle_pr_create(prefilled: str | None = None):
    client = _get_client_or_none()
    if not client:
        _pause()
        return
    full_name = prefilled or _pick_repo_or_input(client)
    if not full_name:
        _pause()
        return
    clear()
    ui.show_header("Criar PR", full_name)
    title = _safe_ask(questionary.text, "🔀 Título do PR:", style=_get_style(), qmark="◆")
    if not title:
        ui.warning("Título não pode ser vazio")
        _pause()
        return
    head = _safe_ask(questionary.text, "🌿 Branch head (ex: feature/minha):", style=_get_style(), qmark="◆")
    if not head:
        ui.warning("Head é obrigatório")
        _pause()
        return
    base = _safe_ask(questionary.text, "🎯 Branch base (padrão: main):", default="main", style=_get_style(), qmark="◆") or "main"
    body = _safe_ask(questionary.text, "📝 Descrição (opcional):", style=_get_style(), qmark="◆") or ""
    draft = _safe_ask(questionary.confirm, "Criar como draft?", default=False, style=_get_style(), qmark="◆")
    p = ui.get_palette()
    try:
        with console.status(f"[bold {p['secondary']}]Criando PR...[/]", spinner="dots12"):
            pr = client.create_pr(full_name, title=title, head=head, base=base, body=body, draft=bool(draft))
        ui.success(f"PR criado: [bold]#{pr['number']} {pr['title']}[/]\n🔗 {pr['html_url']}  {'(draft)' if pr.get('draft') else ''}", title="🔀 PR criado")
    except requests.HTTPError as e:
        ui.error(f"Erro ao criar PR: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text}[/dim]")
    except Exception as e:
        ui.error(str(e))
    _pause()


def handle_user_view(prefilled: str | None = None):
    username = prefilled or _safe_ask(questionary.text, "👤 Username GitHub (ex: torvalds, octocat):", style=_get_style(), qmark="◆")
    if not username:
        _pause()
        return
    username = username.strip()
    p = ui.get_palette()
    clear()
    ui.show_header("Perfil GitHub", username)
    console.print(f"[{p['muted']}]  Buscando perfil + top repos...[/]\n")
    # tenta autenticado para rate maior
    token = get_token()
    user = None
    user_repos = []
    orgs = []
    is_self = False
    try:
        if token:
            client = GitHubClient(token)
            with console.status(f"[bold {p['primary']}]Buscando perfil {username}...[/]", spinner="dots12"):
                user = client.get_user_by_username(username)
                try:
                    me = client.get_user()
                    is_self = me.get("login", "").lower() == username.lower()
                except Exception:
                    pass
                user_repos = client.list_user_repos(username, limit=6, sort="updated")
                try:
                    orgs = client.list_user_orgs(username)
                except Exception:
                    orgs = []
        else:
            from .github import fetch_user_public, fetch_user_repos_public
            with console.status(f"[dim]Buscando perfil {username}...[/]", spinner="dots12"):
                user = fetch_user_public(username)
                if user:
                    user_repos = fetch_user_repos_public(username, limit=6, sort="updated")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            ui.error(f"Usuário '{username}' não encontrado", title="404")
        else:
            ui.error(str(e))
        _pause()
        return
    except Exception as e:
        ui.error(str(e))
        _pause()
        return

    if not user:
        ui.error(f"Usuário '{username}' não encontrado", title="404")
        _pause()
        return

    # Perfil premium — clean sem redundância
    console.print(ui.user_profile_panel(user, is_self=is_self))
    console.print()
    if orgs:
        org_str = "  ".join(f"[{p['secondary']}]@{o['login']}[/]" for o in orgs[:5])
        console.print(f"  [{p['muted']}]🏢[/] {org_str}")
        console.print()
    if user_repos:
        console.print(ui.repo_table(f"Top repos de {username} • {len(user_repos)}", user_repos))
        console.print()
    else:
        console.print(f"  [{p['muted']}]📦 {username} sem repos públicos[/]")
        console.print()

    # Ações
    choices = ["↩️  Voltar", f"📦 Ver todos repos de {username}", f"🔍 Buscar repos de {username}", "👤 Ver outro perfil"]
    # se for org, não faz sentido stir?
    sel = _safe_ask(questionary.select, f"O que fazer com {username}?", choices=choices, style=_get_style(), qmark="◆", pointer="▶")
    if sel and "Ver todos repos" in sel:
        # lista completa
        clear()
        ui.show_header(f"Repos de {username}", "ordenado por updated")
        token2 = get_token()
        try:
            if token2:
                c2 = GitHubClient(token2)
                with console.status(f"[bold {p['primary']}]Buscando repos de {username}...[/]", spinner="dots12"):
                    all_repos = c2.list_user_repos(username, limit=20, sort="updated")
            else:
                from .github import fetch_user_repos_public
                with console.status(f"[dim]Buscando repos de {username}...[/]", spinner="dots12"):
                    all_repos = fetch_user_repos_public(username, limit=20, sort="updated")
            if all_repos:
                console.print(ui.repo_table(f"Repos de {username} • {len(all_repos)}", all_repos))
                # permitir ver detalhe
                chosen = _select_repo_interactively(all_repos)
                if chosen:
                    handle_repo_view(prefilled=chosen)
                    return
            else:
                ui.warning("Nenhum repo encontrado.")
        except Exception as e:
            ui.error(str(e))
        _pause()
    elif sel and "Buscar repos" in sel:
        handle_repo_search()
    elif sel and "Ver outro perfil" in sel:
        handle_user_view()
    else:
        _pause()


# ---------- MENU PRINCIPAL ----------
def run_interactive():
    if not sys.stdin.isatty():
        ui.warning("Modo interativo precisa de um terminal (TTY).", title="Aviso")
        console.print("[dim]Rode sem pipe/redirecionamento ou use os comandos: hubctl --help[/dim]")
        sys.exit(1)

    ui.reload_theme()
    global custom_style
    custom_style = _get_style()

    try:
        while True:
            p = ui.get_palette()
            style = _get_style()
            clear()
            try:
                from . import __version__ as _ver
            except Exception:
                _ver = "0.2.1"
            ui.print_banner(version=_ver)
            console.print()
            console.print(ui.make_status_bar())
            # cwd repo detectado (como sweeo mostra cwd)
            try:
                cwd_repo = get_cwd_repo()
                if cwd_repo:
                    console.print(f"  [{p['success']}]📁 repo atual:[/] [{p['fg_bold']}]{cwd_repo}[/]  [{p['muted']}]•[/] [{p['muted2']}]hubctl repo view já abre ele[/]")
            except Exception:
                pass
            # hint de tema como sweeo
            if ui._get_preferred_theme() == "auto" and ui._is_light_background():
                console.print(f"  [{p['muted2']}]Tema claro detectado automaticamente • ajuste em hubctl config theme se precisar[/]")
            console.print()

            choice = _safe_ask(questionary.select, "O que deseja fazer hoje?",
                choices=[
                    questionary.Choice(" 1. 🔐  Autenticação  —  login / status / logout", value="auth"),
                    questionary.Choice(" 2. 📦  Repositórios  —  listar, ver, clonar, fork, star", value="repos"),
                    questionary.Choice(" 3. 🔍  Buscar Repos  —  busca global por user/linguagem", value="search"),
                    questionary.Choice(" 4. 🐛  Issues  —  listar, ver, criar, fechar", value="issues"),
                    questionary.Choice(" 5. 🔀  Pull Requests  —  listar, ver, criar", value="prs"),
                    questionary.Choice(" 6. 👤  Usuários  —  ver perfil, repos do dono", value="users"),
                    questionary.Choice(" 7. ⚙️  Config  —  tema claro/escuro", value="config"),
                    questionary.Choice(" 8. ❌  Sair", value="exit"),
                ],
                style=style,
                qmark="◆",
                pointer="▶",
                instruction=" ↑↓ navega  •  ENTER seleciona",
            )

            if choice is None or choice == "exit":
                clear()
                console.print(Panel(
                    Align.center(Text("Até a próxima! 👋\n", style=f"bold {p['primary']}") + Text("Obrigado por usar o HubCtl", style=p["muted"])),
                    box=box.ROUNDED, border_style=p["border"], padding=(1, 2)
                ))
                sys.exit(0)

            elif choice == "auth":
                sub = _safe_ask(questionary.select, "Autenticação:",
                    choices=[
                        questionary.Choice("🔑  Login", value="login"),
                        questionary.Choice("👤  Status", value="status"),
                        questionary.Choice("🚪  Logout", value="logout"),
                        questionary.Choice("↩  Voltar", value="back"),
                    ],
                    style=style, qmark="◆", pointer="▶", instruction="↑↓ + ENTER")
                if sub == "login":
                    handle_auth_login()
                elif sub == "status":
                    handle_auth_status()
                elif sub == "logout":
                    handle_auth_logout()

            elif choice == "repos":
                sub = _safe_ask(questionary.select, "Repositórios:",
                    choices=[
                        questionary.Choice("📋  Listar meus repositórios", value="list"),
                        questionary.Choice("👁️  Ver detalhes de um repo", value="view"),
                        questionary.Choice("📥  Clonar repositório", value="clone"),
                        questionary.Choice("🍴  Fork de repo", value="fork"),
                        questionary.Choice("⭐  Star / Unstar", value="star"),
                        questionary.Choice("✏️  Editar repo", value="edit"),
                        questionary.Choice("➕  Criar repositório", value="create"),
                        questionary.Choice("🗑️  Deletar repositório", value="delete"),
                        questionary.Choice("↩  Voltar", value="back"),
                    ],
                    style=style, qmark="◆", pointer="▶")
                if sub == "list":
                    handle_repo_list()
                elif sub == "view":
                    handle_repo_view()
                elif sub == "clone":
                    handle_repo_clone()
                elif sub == "fork":
                    handle_repo_fork()
                elif sub == "star":
                    handle_repo_star_toggle()
                elif sub == "edit":
                    handle_repo_edit()
                elif sub == "create":
                    handle_repo_create()
                elif sub == "delete":
                    handle_repo_delete()

            elif choice == "search":
                handle_repo_search()

            elif choice == "issues":
                sub = _safe_ask(questionary.select, "Issues:",
                    choices=[
                        questionary.Choice("📋  Listar issues", value="list"),
                        questionary.Choice("👁️  Ver issue", value="view"),
                        questionary.Choice("➕  Criar issue", value="create"),
                        questionary.Choice("🔒  Fechar issue", value="close"),
                        questionary.Choice("↩  Voltar", value="back"),
                    ],
                    style=style, qmark="◆", pointer="▶")
                if sub == "list":
                    handle_issue_list()
                elif sub == "view":
                    handle_issue_view()
                elif sub == "create":
                    handle_issue_create()
                elif sub == "close":
                    handle_issue_close()

            elif choice == "prs":
                sub = _safe_ask(questionary.select, "Pull Requests:",
                    choices=[
                        questionary.Choice("📋  Listar PRs", value="list"),
                        questionary.Choice("👁️  Ver PR", value="view"),
                        questionary.Choice("➕  Criar PR", value="create"),
                        questionary.Choice("↩  Voltar", value="back"),
                    ],
                    style=style, qmark="◆", pointer="▶")
                if sub == "list":
                    handle_pr_list()
                elif sub == "view":
                    handle_pr_view()
                elif sub == "create":
                    handle_pr_create()

            elif choice == "users":
                sub = _safe_ask(questionary.select, "Usuários:",
                    choices=[
                        questionary.Choice("👤  Ver perfil por username", value="view"),
                        questionary.Choice("📦  Listar repos de um usuário", value="repos"),
                        questionary.Choice("⭐  Meu perfil (auth status)", value="me"),
                        questionary.Choice("↩  Voltar", value="back"),
                    ],
                    style=style, qmark="◆", pointer="▶")
                if sub == "view":
                    handle_user_view()
                elif sub == "repos":
                    # pede username e lista
                    uname = _safe_ask(questionary.text, "Username:", style=_get_style(), qmark="◆")
                    if uname:
                        clear()
                        # reutiliza handler de repos do user com lógica direta
                        token2 = get_token()
                        p2 = ui.get_palette()
                        try:
                            if token2:
                                c2 = GitHubClient(token2)
                                with console.status(f"[bold {p2['primary']}]Buscando repos de {uname}...[/]", spinner="dots12"):
                                    repos = c2.list_user_repos(uname.strip(), limit=20)
                            else:
                                from .github import fetch_user_repos_public
                                with console.status(f"[dim]Buscando repos de {uname}...[/]", spinner="dots12"):
                                    repos = fetch_user_repos_public(uname.strip(), limit=20)
                            if repos:
                                clear()
                                ui.show_header(f"Repos de {uname.strip()}", f"{len(repos)} repos")
                                console.print(ui.repo_table(f"Repos de {uname.strip()} • {len(repos)}", repos))
                                chosen = _select_repo_interactively(repos)
                                if chosen:
                                    handle_repo_view(prefilled=chosen)
                                else:
                                    _pause()
                            else:
                                ui.warning("Nenhum repo encontrado.")
                                _pause()
                        except Exception as e:
                            ui.error(str(e))
                            _pause()
                elif sub == "me":
                    handle_auth_status()

            elif choice == "config":
                clear()
                ui.show_header("Configurações", "Tema e preferências")
                console.print()
                cur = ui._get_preferred_theme()
                eff = ui.get_effective_theme_name()
                console.print(Panel(
                    f"  Tema preferido: [{p['primary']}]{cur}[/]  → efetivo: [{p['fg_bold']}]{eff}[/]\n"
                    f"  [{p['muted']}]COLORFGBG={os.getenv('COLORFGBG','-')}  •  GHC_THEME={os.getenv('GHC_THEME','-')}  •  HUBCTL_THEME={os.getenv('HUBCTL_THEME','-')}[/]\n"
                    f"  [{p['muted']}]Config: [{p['fg_bold']}]{CONFIG_FILE}[/]",
                    box=box.ROUNDED, border_style=p["border"], padding=(1,2), title=f"[{p['primary']}]◆ Aparência[/]"
                ))
                console.print()
                tchoice = _safe_ask(questionary.select, "O que mudar?",
                    choices=[
                        questionary.Choice("🌓  Tema  —  auto/dark/light", value="theme"),
                        questionary.Choice("📄  Ver config completa", value="show"),
                        questionary.Choice("↩  Voltar", value="back"),
                    ],
                    style=style, qmark="◆", pointer="▶")
                if tchoice == "theme":
                    new_theme = _safe_ask(questionary.select, "Escolha o tema:",
                        choices=[
                            questionary.Choice("🌓  Automático  —  detecta via COLORFGBG", value="auto"),
                            questionary.Choice("🌙  Escuro  —  neon em fundo preto", value="dark"),
                            questionary.Choice("☀️  Claro  —  contraste em fundo branco", value="light"),
                            questionary.Choice("↩  Cancelar", value="cancel"),
                        ],
                        style=style, qmark="◆", pointer="▶", instruction="↑↓ + ENTER")
                    if new_theme and new_theme != "cancel":
                        from .config import save_theme
                        save_theme(new_theme)
                        ui.reload_theme()
                        ui.success(f"Tema alterado para {new_theme}! Reiniciando UI...")
                        import time as _t
                        _t.sleep(0.9)
                elif tchoice == "show":
                    import configparser
                    clear()
                    ui.show_header("Config", str(CONFIG_FILE))
                    if not CONFIG_FILE.exists():
                        ui.warning("Nenhum config salvo ainda.", title="Vazio")
                    else:
                        cfg = configparser.ConfigParser()
                        cfg.read(CONFIG_FILE)
                        for sec in cfg.sections():
                            console.print(f"[bold {p['primary']}][{sec}][/]")
                            for k, v in cfg[sec].items():
                                if k == "token":
                                    v = v[:6] + "***" + v[-4:] if len(v) > 10 else "***"
                                console.print(f"  {k} = {v}")
                        console.print(f"\n[{p['muted']}]  Tema efetivo: {eff} ({'claro' if eff=='light' else 'escuro'})[/]")
                    console.print()
                    _pause()
    except KeyboardInterrupt:
        p = ui.get_palette()
        console.print(f"\n[{p['muted']}]Saindo... até logo! 👋[/]")
        sys.exit(0)
