import os
import shutil
import subprocess
import sys
from pathlib import Path

import questionary
import requests
from questionary import Style

from .config import CONFIG_FILE, delete_token, get_token, save_token
from .github import GitHubClient, fetch_readme_public
from . import ui

console = ui.console

# style dinâmico que respeita tema claro/escuro (via ui.get_questionary_style)
def _get_style():
    return ui.get_questionary_style()

custom_style = _get_style()

def _pause():
    questionary.press_any_key_to_continue("↵ Pressione Enter para continuar...", style=_get_style()).ask()

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
            ui.warning("Você não está autenticado.", title="🔒 Login necessário")
            choice = _safe_ask(questionary.confirm, "Deseja fazer login agora?", default=True, style=_get_style())
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
    console.print(ui.info_panel("🔐 Login GitHub", "Crie seu token em: [link=https://github.com/settings/tokens]https://github.com/settings/tokens[/]\n[dim]Precisa de scopes: repo, read:org[/dim]", border_color=ui.THEME["primary"]))
    token = _safe_ask(questionary.password, "🔑 Cole seu GitHub Token:", style=_get_style())
    if not token:
        ui.warning("Cancelado.")
        _pause()
        return
    try:
        client = GitHubClient(token)
        with console.status("[bold #00D9FF]Validando token...[/]", spinner="dots12"):
            user = client.get_user()
        save_token(token)
        ui.success(f"Autenticado como [bold]{user['login']}[/]!", title="✓ Bem-vindo")
        console.print(f"[dim]Token salvo em {CONFIG_FILE}[/dim]")
        console.print(ui.auth_panel(user))
    except requests.HTTPError as e:
        ui.error(f"Erro ao validar token: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text[:400]}[/dim]")
    except Exception as e:
        ui.error(str(e))
    _pause()

def handle_auth_logout():
    token = get_token()
    if not token and not CONFIG_FILE.exists():
        ui.warning("Você já não está logado (sem token salvo).")
        _pause()
        return
    confirm = _safe_ask(questionary.confirm, f"Remover token salvo em {CONFIG_FILE}?", default=False, style=_get_style())
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
    token = get_token()
    if not token:
        ui.error("Não autenticado. Rode login.", title="Offline")
        _pause()
        return
    try:
        client = GitHubClient(token)
        with console.status("[bold #00D9FF]Buscando seu perfil...[/]", spinner="dots12"):
            user = client.get_user()
        console.print(ui.auth_panel(user))
        src = "env GITHUB_TOKEN" if os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") else str(CONFIG_FILE)
        console.print(f"[dim]Token origem: {src}[/dim]")
    except Exception as e:
        ui.error(str(e))
    _pause()

# ---------- HELPERS ----------
def _choose_visibility():
    vis = _safe_ask(questionary.select, "Visibilidade:",
        choices=["all", "public", "private"],
        style=_get_style())
    return vis or "all"

def _choose_limit(default=20):
    val = _safe_ask(questionary.text, f"Quantos? (padrão {default}):", style=_get_style())
    if not val or val.strip() == "":
        return default
    try:
        return int(val)
    except ValueError:
        ui.warning("Valor inválido, usando padrão.")
        return default

def _choose_state():
    state = _safe_ask(questionary.select, "Estado:",
        choices=["open", "closed", "all"],
        style=_get_style())
    return state or "open"

def _select_repo_interactively(repos):
    if not repos:
        return None
    choices = [f"{r['full_name']}  {'🔒' if r['private'] else '🌍'}  ⭐{r['stargazers_count']}  🍴{r.get('forks_count',0)}  {(r['description'] or '')[:35]}" for r in repos]
    choices.append(questionary.Separator("─────────────────"))
    choices.append("✏️  Digitar manualmente")
    choices.append("↩️  Cancelar")
    sel = _safe_ask(questionary.select, "Selecione um repositório:", choices=choices, style=_get_style(), instruction="(↑/↓ + Enter)")
    if sel is None or sel == "↩️  Cancelar":
        return None
    if sel == "✏️  Digitar manualmente":
        manual = _safe_ask(questionary.text, "Digite usuario/repo:", style=_get_style())
        return manual
    return sel.split()[0]

def _pick_repo_or_input(client):
    """Helper unificado: tenta listar e escolher, senão digitar"""
    if client:
        try:
            with console.status("[bold #00D9FF]Carregando seus repos...[/]", spinner="dots12"):
                repos = client.list_repos(limit=20, visibility="all")
            if repos:
                use_list = _safe_ask(questionary.confirm, "Escolher da sua lista de repos?", default=True, style=_get_style())
                if use_list:
                    return _select_repo_interactively(repos)
        except Exception:
            pass
    return _safe_ask(questionary.text, "Digite usuario/repo (ex: octocat/Hello-World):", style=_get_style())

def _has_admin_access(client, repo: dict) -> bool:
    """True se o usuário autenticado tem permissão admin (dono) no repo. Usa permissions se vier da API, senão compara owner vs /user"""
    if not client:
        return False
    perms = repo.get("permissions")
    if perms is not None:
        # GitHub retorna {"admin": true/false, ...} quando autenticado
        return bool(perms.get("admin"))
    # fallback: compara login do owner com usuário logado (evita mostrar Deletar em repo público de terceiros)
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
    visibility = _choose_visibility()
    if visibility is None: return
    limit = _choose_limit(20)
    try:
        with console.status(f"[bold #00D9FF]Buscando repos ({visibility})...[/]", spinner="dots12"):
            repos = client.list_repos(limit=limit, visibility=visibility)
    except Exception as e:
        ui.error(str(e))
        _pause()
        return
    if not repos:
        ui.warning("Nenhum repositório encontrado.", title="Vazio")
        _pause()
        return
    console.print(ui.repo_table(f"Seus Repositórios • {visibility} • {len(repos)}", repos))
    action = _safe_ask(questionary.select, "O que deseja fazer?",
        choices=["↩️  Voltar", "👁️  Ver detalhes", "📥 Clonar", "🍴 Fork", "⭐ Star/Unstar", "🐛 Issues", "🔀 PRs"],
        style=_get_style())
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
    # busca (autenticado se tiver token, senão anônimo)
    try:
        if client:
            with console.status(f"[bold #00D9FF]Buscando {full_name}...[/]", spinner="dots12"):
                r = client.get_repo(full_name)
                # checa se deu star
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
    star_str = "⭐ Starred" if r.get("_starred") else "☆ Não starred"
    console.print(f"[dim]{star_str}  •  [dim]Use setas abaixo[/dim]")

    # README.md bonito e organizado (em vez de só descrição curta)
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

    # Menu dinâmico: Editar/Deletar só aparece se você é dono/admin (evita deletar repo público de terceiros)
    can_admin = _has_admin_access(client, r)
    if not can_admin and client:
        # dica sutil quando não é dono
        console.print(f"[dim]ℹ {r.get('owner',{}).get('login','')} / permissões: leitura — Editar/Deletar ocultos (só dono vê)[/dim]")
    choices = ["↩️  Voltar", "📥 Clonar", "🍴 Fork", "⭐ Toggle Star"]
    if can_admin:
        choices.append("✏️  Editar")
    choices.extend(["🐛 Issues", "🔀 PRs"])
    if can_admin:
        choices.append("🗑️  Deletar")
    action = _safe_ask(questionary.select, f"Ações para {full_name}:", choices=choices, style=_get_style())
    if action == "📥 Clonar":
        handle_repo_clone(prefilled=full_name)
    elif action == "🍴 Fork":
        handle_repo_fork(prefilled=full_name)
    elif action == "⭐ Toggle Star":
        handle_repo_star_toggle(prefilled=full_name)
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
    name = _safe_ask(questionary.text, "📦 Nome do novo repositório:", style=_get_style())
    if not name:
        ui.warning("Nome não pode ser vazio.")
        _pause()
        return
    description = _safe_ask(questionary.text, "📝 Descrição (opcional):", style=_get_style()) or ""
    private = _safe_ask(questionary.confirm, "🔒 Privado?", default=False, style=_get_style())
    if private is None:
        _pause()
        return
    confirm = _safe_ask(questionary.confirm, f"Criar repo '{name}' {'🔒 privado' if private else '🌍 público'}?", default=True, style=_get_style())
    if not confirm:
        console.print("[dim]Cancelado[/dim]")
        _pause()
        return
    try:
        with console.status("[bold #B537F2]Criando repositório...[/]", spinner="dots12"):
            r = client.create_repo(name, private=private, description=description)
        ui.success(f"Repo criado: [bold]{r['full_name']}[/]\n🔗 {r['html_url']}", title="✓ Criado")
    except requests.HTTPError as e:
        ui.error(f"Erro ao criar: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text}[/dim]")
    except Exception as e:
        ui.error(str(e))
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
    ui.warning(f"Você vai deletar [bold]{full_name}[/] permanentemente!", title="⚠️  IRREVERSÍVEL")
    confirm1 = _safe_ask(questionary.confirm, f"Tem certeza que quer deletar {full_name}?", default=False, style=_get_style())
    if not confirm1:
        console.print("[dim]Cancelado[/dim]")
        _pause()
        return
    typed = _safe_ask(questionary.text, f"Digite '{full_name}' para confirmar:", style=_get_style())
    if typed != full_name:
        ui.error("Nomes não batem. Cancelado.")
        _pause()
        return
    try:
        with console.status(f"[bold #FF006E]Deletando {full_name}...[/]", spinner="dots12"):
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
    proto = _safe_ask(questionary.select, "Protocolo:",
        choices=["🌐 HTTPS (recomendado)", "🔑 SSH (precisa chave)"],
        style=_get_style())
    if proto is None:
        _pause()
        return
    use_ssh = "SSH" in proto
    dest_default = full_name.split("/")[-1]
    dest_input = _safe_ask(questionary.text, f"📁 Diretório destino (padrão: ./{dest_default}):", style=_get_style())
    dest = Path(dest_input.strip()) if dest_input and dest_input.strip() else Path(dest_default)
    if dest.exists():
        ui.error(f"Destino '{dest}' já existe")
        _pause()
        return
    try:
        if token:
            with console.status(f"[bold #00D9FF]Buscando {full_name}...[/]", spinner="dots12"):
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

    if use_ssh:
        url = ssh_url or f"git@github.com:{full_name}.git"
    else:
        url = clone_url or f"https://github.com/{full_name}.git"
        if is_private and token and url.startswith("https://"):
            url = url.replace("https://", f"https://oauth2:{token}@")

    safe_url = url.replace(token, "***") if token and token in url else url
    console.print(f"[bold #00D9FF]⬇ Clonando [bold]{full_name}[/] → [bold]{dest}[/][/]")
    console.print(f"[dim]{safe_url}[/]")
    result = subprocess.run(["git", "clone", url, str(dest)])
    if result.returncode == 0:
        ui.success(f"Clonado em [bold]{dest.resolve()}[/]", title="✓ Clone ok")
        console.print(f"[dim]cd {dest} && code .[/dim]")
    else:
        ui.error(f"git clone falhou (código {result.returncode})")
    _pause()

def handle_repo_fork(prefilled: str | None = None):
    client = _get_client_or_none()
    if not client:
        _pause()
        return
    full_name = prefilled or _safe_ask(questionary.text, "Digite usuario/repo para fork:", style=_get_style())
    if not full_name:
        _pause()
        return
    try:
        with console.status(f"[bold #B537F2]Fazendo fork de {full_name}...[/]", spinner="dots12"):
            r = client.fork_repo(full_name)
        ui.success(f"Fork criado! [bold]{r['full_name']}[/]\n🔗 {r['html_url']}", title="🍴 Fork ok")
        clone = _safe_ask(questionary.confirm, "Deseja clonar o fork agora?", default=True, style=_get_style())
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
    full_name = prefilled or _safe_ask(questionary.text, "Digite usuario/repo:", style=_get_style())
    if not full_name:
        _pause()
        return
    try:
        with console.status(f"[dim]Verificando star de {full_name}...[/]", spinner="dots12"):
            starred = client.check_starred(full_name)
        if starred:
            console.print(f"[yellow]⭐ Você já deu star em {full_name}[/yellow]")
            if _safe_ask(questionary.confirm, "Remover star?", default=False, style=_get_style()):
                with console.status("[dim]Removendo star...[/]", spinner="dots12"):
                    client.unstar_repo(full_name)
                ui.success(f"Star removido de {full_name}")
            _pause()
        else:
            with console.status(f"[bold #FFD23F]Dando star em {full_name}...[/]", spinner="dots12"):
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
    # busca atual
    try:
        with console.status(f"[dim]Buscando {full_name}...[/]", spinner="dots12"):
            r = client.get_repo(full_name)
    except Exception as e:
        ui.error(str(e))
        _pause()
        return
    console.print(ui.detail_panel(r))
    field = _safe_ask(questionary.select, "O que editar?",
        choices=["📝 Descrição", "🏠 Homepage", "🔒 Visibilidade (privado/público)", "↩️  Cancelar"],
        style=_get_style())
    if not field or field == "↩️  Cancelar":
        _pause()
        return
    data = {}
    if "Descrição" in field:
        new_desc = _safe_ask(questionary.text, "Nova descrição:", default=r.get("description") or "", style=_get_style())
        if new_desc is not None:
            data["description"] = new_desc
    elif "Homepage" in field:
        new_home = _safe_ask(questionary.text, "Nova homepage:", default=r.get("homepage") or "", style=_get_style())
        if new_home is not None:
            data["homepage"] = new_home
    elif "Visibilidade" in field:
        is_private = r.get("private", False)
        console.print(f"[dim]Atual: {'🔒 privado' if is_private else '🌍 público'}[/dim]")
        new_private = _safe_ask(questionary.select, "Tornar:",
            choices=["🌍 Público", "🔒 Privado"],
            style=_get_style())
        if new_private:
            data["private"] = "Privado" in new_private

    if not data:
        _pause()
        return
    try:
        with console.status(f"[bold #00D9FF]Atualizando {full_name}...[/]", spinner="dots12"):
            updated = client.update_repo(full_name, **data)
        ui.success(f"Atualizado [bold]{updated['full_name']}[/]\n[dim]{updated.get('description') or ''}[/]", title="✓ Editado")
    except Exception as e:
        ui.error(str(e))
    _pause()

def handle_repo_search():
    token = get_token()
    # Fluxo melhorado: pergunta usuário/org opcional + termos
    user_filter = _safe_ask(questionary.text, "👤 Filtrar por usuário/org? (ex: octocat, deixe vazio para busca global):", style=_get_style())
    # None = Ctrl+C
    if user_filter is None:
        _pause()
        return
    user_filter = user_filter.strip()
    query = _safe_ask(questionary.text, "🔍 Termos da busca (ex: 'cli language:python', vazio lista tudo do usuário se filtrou):", style=_get_style())
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
        console.print(f"[dim]🔎 Busca: '{effective_query}' (filtro usuário: {user_filter})[/dim]")
    limit = _choose_limit(10)
    try:
        if token:
            client = GitHubClient(token)
            with console.status(f"[bold #00D9FF]Buscando '{effective_query}'...[/]", spinner="dots12"):
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
    console.print(ui.repo_table(f"Busca: '{effective_query}' • {total} resultados (mostrando {len(items)})", items))
    # Fluxo direto: mostra info + opção clonar (via view)
    action = _safe_ask(questionary.select, "O que fazer? (Ver detalhes já mostra info + opção Clonar)",
        choices=["↩️  Voltar", "👁️  Ver detalhes (+ clonar/fork/star)", "📥 Clonar direto", "🍴 Fork", "⭐ Star"],
        style=_get_style())
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
    state = _choose_state()
    limit = _choose_limit(20)
    # usa client se tiver, senão anônimo
    try:
        if client:
            with console.status(f"[bold #00D9FF]Buscando issues de {full_name}...[/]", spinner="dots12"):
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
    # permite ver detalhes
    choices = [f"#{i['number']} • {i['title'][:45]}  [{i['state']}]" for i in issues[:10]]
    choices += ["↩️  Voltar", "➕ Criar nova issue"]
    sel = _safe_ask(questionary.select, "Ver detalhes ou criar?", choices=choices, style=_get_style())
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
        num_str = _safe_ask(questionary.text, "Número da issue:", style=_get_style())
        if not num_str: _pause(); return
        try: number = int(num_str)
        except: ui.error("Número inválido"); _pause(); return
    try:
        if client:
            with console.status(f"[bold #00D9FF]Buscando issue #{number}...[/]", spinner="dots12"):
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
    color = ui.THEME["success"] if state == "open" else ui.THEME["error"]
    labels = "  ".join(f"[bold #B537F2]#{l['name']}[/]" for l in issue.get("labels", [])) or "[dim]sem labels[/dim]"
    console.print(ui.info_panel(
        f"#{issue['number']} • {issue['title']}",
        f"[bold {color}]● {state.upper()}[/]  por [bold]{issue['user']['login']}[/]  em {issue['created_at'][:10]}  •  💬 {issue['comments']}\n"
        f"[dim]{labels}[/]\n\n"
        f"{issue.get('body') or '[dim]Sem descrição[/dim]'}\n\n"
        f"[dim]🔗 {issue['html_url']}[/]",
        border_color=color
    ))
    action = _safe_ask(questionary.select, "Ação:", choices=["↩️  Voltar", "🔒 Fechar issue"], style=_get_style())
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
    title = _safe_ask(questionary.text, "🐛 Título da issue:", style=_get_style())
    if not title:
        ui.warning("Título não pode ser vazio")
        _pause()
        return
    body = _safe_ask(questionary.text, "📝 Descrição (opcional):", style=_get_style()) or ""
    labels_str = _safe_ask(questionary.text, "🏷️  Labels separados por vírgula (opcional):", style=_get_style()) or ""
    labels = [s.strip() for s in labels_str.split(",") if s.strip()] or None
    try:
        with console.status("[bold #B537F2]Criando issue...[/]", spinner="dots12"):
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
        num_str = _safe_ask(questionary.text, "Número da issue para fechar:", style=_get_style())
        if not num_str: _pause(); return
        try: number = int(num_str)
        except: ui.error("Número inválido"); _pause(); return
    if not _safe_ask(questionary.confirm, f"Fechar issue #{number} em {full_name}?", default=False, style=_get_style()):
        console.print("[dim]Cancelado[/dim]")
        _pause()
        return
    try:
        with console.status(f"[bold #FF006E]Fechando #{number}...[/]", spinner="dots12"):
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
    state = _choose_state()
    limit = _choose_limit(20)
    try:
        if client:
            with console.status(f"[bold #B537F2]Buscando PRs de {full_name}...[/]", spinner="dots12"):
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
    choices = [f"#{pr['number']} • {pr['title'][:40]}  [{pr['state']}]" for pr in prs[:10]]
    choices += ["↩️  Voltar", "➕ Criar novo PR"]
    sel = _safe_ask(questionary.select, "Ver detalhes ou criar?", choices=choices, style=_get_style())
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
        num_str = _safe_ask(questionary.text, "Número do PR:", style=_get_style())
        if not num_str: _pause(); return
        try: number = int(num_str)
        except: ui.error("Número inválido"); _pause(); return
    try:
        if client:
            with console.status(f"[bold #B537F2]Buscando PR #{number}...[/]", spinner="dots12"):
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
        color = ui.THEME["secondary"]
        state_str = "MERGED"
    elif state == "open":
        color = ui.THEME["success"]
        state_str = "OPEN"
    else:
        color = ui.THEME["error"]
        state_str = state.upper()
    console.print(ui.info_panel(
        f"#{pr['number']} • {pr['title']}",
        f"[bold {color}]● {state_str}[/]  por [bold]{pr['user']['login']}[/]  em {pr['created_at'][:10]}\n"
        f"[bold #00D9FF]{pr['head']['ref']}[/] → [bold]{pr['base']['ref']}[/]  •  💬 {pr.get('comments',0)}  •  ✅ {pr.get('additions',0)}++ / ❌ {pr.get('deletions',0)}--  •  📄 {pr.get('changed_files',0)} arquivos\n\n"
        f"{pr.get('body') or '[dim]Sem descrição[/dim]'}\n\n"
        f"[dim]🔗 {pr['html_url']}[/]",
        border_color=color
    ))
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
    title = _safe_ask(questionary.text, "🔀 Título do PR:", style=_get_style())
    if not title:
        ui.warning("Título não pode ser vazio")
        _pause()
        return
    head = _safe_ask(questionary.text, "🌿 Branch head (ex: feature/minha):", style=_get_style())
    if not head:
        ui.warning("Head é obrigatório")
        _pause()
        return
    base = _safe_ask(questionary.text, "🎯 Branch base (padrão: main):", default="main", style=_get_style()) or "main"
    body = _safe_ask(questionary.text, "📝 Descrição (opcional):", style=_get_style()) or ""
    draft = _safe_ask(questionary.confirm, "Criar como draft?", default=False, style=_get_style())
    try:
        with console.status("[bold #B537F2]Criando PR...[/]", spinner="dots12"):
            pr = client.create_pr(full_name, title=title, head=head, base=base, body=body, draft=bool(draft))
        ui.success(f"PR criado: [bold]#{pr['number']} {pr['title']}[/]\n🔗 {pr['html_url']}  {'(draft)' if pr.get('draft') else ''}", title="🔀 PR criado")
    except requests.HTTPError as e:
        ui.error(f"Erro ao criar PR: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text}[/dim]")
    except Exception as e:
        ui.error(str(e))
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
    ui.print_banner(clear=True)

    while True:
        choice = _safe_ask(questionary.select, "O que você quer fazer?",
            choices=[
                "🔐  Autenticação",
                "📦  Repositórios",
                "🔍  Buscar Repos",
                "🐛  Issues",
                "🔀  Pull Requests",
                questionary.Separator("─────────────────────────────"),
                "❌  Sair",
            ],
            style=_get_style(),
            instruction="(↑/↓ + Enter)",
        )

        if choice is None or choice == "❌  Sair":
            console.print("[dim]Até logo! 👋[/dim]")
            sys.exit(0)

        elif choice == "🔐  Autenticação":
            sub = _safe_ask(questionary.select, "Autenticação:",
                choices=["🔑  Login", "👤  Status", "🚪  Logout", "↩️  Voltar"],
                style=_get_style())
            if sub == "🔑  Login":
                handle_auth_login()
            elif sub == "👤  Status":
                handle_auth_status()
            elif sub == "🚪  Logout":
                handle_auth_logout()

        elif choice == "📦  Repositórios":
            sub = _safe_ask(questionary.select, "Repositórios:",
                choices=[
                    "📋  Listar meus repositórios",
                    "👁️  Ver detalhes de um repo",
                    "📥  Clonar repositório",
                    "🍴  Fork de repo",
                    "⭐  Star / Unstar",
                    "✏️  Editar repo",
                    "➕  Criar repositório",
                    "🗑️  Deletar repositório",
                    "↩️  Voltar",
                ],
                style=_get_style())
            if sub == "📋  Listar meus repositórios":
                handle_repo_list()
            elif sub == "👁️  Ver detalhes de um repo":
                handle_repo_view()
            elif sub == "📥  Clonar repositório":
                handle_repo_clone()
            elif sub == "🍴  Fork de repo":
                handle_repo_fork()
            elif sub == "⭐  Star / Unstar":
                handle_repo_star_toggle()
            elif sub == "✏️  Editar repo":
                handle_repo_edit()
            elif sub == "➕  Criar repositório":
                handle_repo_create()
            elif sub == "🗑️  Deletar repositório":
                handle_repo_delete()

        elif choice == "🔍  Buscar Repos":
            handle_repo_search()

        elif choice == "🐛  Issues":
            sub = _safe_ask(questionary.select, "Issues:",
                choices=[
                    "📋  Listar issues",
                    "👁️  Ver issue",
                    "➕  Criar issue",
                    "🔒  Fechar issue",
                    "↩️  Voltar"
                ],
                style=_get_style())
            if sub == "📋  Listar issues":
                handle_issue_list()
            elif sub == "👁️  Ver issue":
                handle_issue_view()
            elif sub == "➕  Criar issue":
                handle_issue_create()
            elif sub == "🔒  Fechar issue":
                handle_issue_close()

        elif choice == "🔀  Pull Requests":
            sub = _safe_ask(questionary.select, "Pull Requests:",
                choices=[
                    "📋  Listar PRs",
                    "👁️  Ver PR",
                    "➕  Criar PR",
                    "↩️  Voltar"
                ],
                style=_get_style())
            if sub == "📋  Listar PRs":
                handle_pr_list()
            elif sub == "👁️  Ver PR":
                handle_pr_view()
            elif sub == "➕  Criar PR":
                handle_pr_create()
