<div align="center">

```
   ____ _ _   _           _       ____ _     ___
  / ___(_) |_| |__  _   _| |__   / ___| |   |_ _|
 | |  _| | __| '_ \| | | | '_ \ | |   | |    | |
 | |_| | | |_| | | | |_| | |_) || |___| |___ | |
  \____|_|\__|_| |_|\__,_|_.__/  \____|_____|___|
```

# HubCtl

**Controle total do GitHub pelo terminal — interativo, lindo e rápido.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Typer](https://img.shields.io/badge/typer-0.27-black?style=flat-square)](https://typer.tiangolo.com)
[![Rich](https://img.shields.io/badge/rich-15.0-00D9FF?style=flat-square)](https://rich.readthedocs.io)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat-square)](#-compatibilidade)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg?style=flat-square)](https://github.com/psf/black)

[Instalação](#-instalação) • [Quickstart](#-quickstart) • [Comandos](#-comandos) • [Modo Interativo](#-modo-interativo) • [Compatibilidade](#-compatibilidade) • [Tema](#-tema-dinâmico)

</div>

---

HubCtl é uma CLI em Python que traz o GitHub pro seu terminal sem dor. Esqueça decorar flags: tudo funciona com **setas ↑/↓**, menus bonitos e tabelas neon. E quando quiser scriptar, os comandos clássicos continuam lá.

> **Por que HubCtl e não `gh` oficial?** `gh` é ótimo, mas é imperativo. HubCtl é **TUI-first**: navegue nos seus repos, escolha com setas, clone/fork/star sem digitar `usuario/repo`. Perfeito pra quem vive no terminal e quer velocidade + beleza.

### ✨ Destaques

| Recurso | O que faz |
|---------|-----------|
| **🎮 TUI 100%** | `hubctl` sem args abre menu navegável com `questionary` + `rich` |
| **📦 Repos** | list / view / create / delete / clone / fork / star / unstar / edit / search |
| **🐛 Issues** | list / view / create / close (com labels) |
| **🔀 PRs** | list / view / create (draft, head/base) |
| **🎨 Tema dinâmico** | auto detecta fundo claro/escuro (`COLORFGBG`), `hubctl config theme light/dark/auto` |
| **🖥️ Cross-OS** | Windows / macOS / Linux via `platformdirs` — mesmo `pip install hubctl` |
| **🔑 Auth simples** | PAT via prompt, `GITHUB_TOKEN` env ou `config.ini` (`chmod 600` no Unix, ignorado no Win) |
| **📋 Anônimo ok** | `view/search/clone` público funciona sem token |

---

## 🖥️ Compatibilidade

**HubCtl roda em qualquer sistema operacional:** Windows, macOS e Linux. 100% Python, sem binários nativos.

| OS | Terminal testado | Instalação | Config |
|----|------------------|------------|--------|
| **Windows** 11/10 | PowerShell 7, Windows Terminal, CMD | `pip` / `pipx` / `uv` | `%APPDATA%\hubctl\config.ini` via `platformdirs` |
| **macOS** 13+ | Terminal.app, iTerm2, Warp | `pip` / `brew` (python) | `~/Library/Application Support/hubctl/config.ini` ou `~/.config/hubctl/` (XDG) |
| **Linux** | bash, zsh, fish | `pip` / `uv` | `~/.config/hubctl/config.ini` (`$XDG_CONFIG_HOME`) |

* **`platformdirs>=3.0` + fallback manual** garante pasta certa em cada OS (`src/github_cli/config.py:7` → `_get_config_dir()`).
* **`os.chmod 600` com `try/except`** — funciona no Linux/macOS e ignora graciosamente no Windows.
* **`questionary` + `rich`** usam `prompt_toolkit` com suporte `win32` → setas ↑/↓ funcionam no PowerShell/CMD.
* **Migração automática:** se você veio do `github-cli` (`~/.config/github-cli/config.ini`), HubCtl copia pra nova pasta na primeira execução.

---

## 📦 Instalação

### Via pip (qualquer OS)

```bash
# Windows / macOS / Linux — mesmo comando
pip install hubctl
# ou isolado (recomendado)
pipx install hubctl
# ou ultra-rápido
uv pip install hubctl

# verifique
hubctl --help
hubctl config show   # mostra onde salvou o config no seu OS
```

### Do código fonte (qualquer OS)

```bash
git clone https://github.com/yukigabriel/hubctl.git
cd hubctl
pip install -e .

# Ative o venv (escolha seu shell/OS)
# Linux/macOS bash/zsh
source .venv/bin/activate
# Linux/macOS fish
source .venv/bin/activate.fish
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Windows CMD
.venv\Scripts\activate.bat
```

> **Alias:** `ghc` continua funcionando por compatibilidade, mas o recomendado é `hubctl`.

**Requisitos:** Python 3.9+ (3.9, 3.10, 3.11, 3.12 testados), `git` no PATH para `hubctl repo clone`.

<details>
<summary>🐍 Windows: detalhes Python</summary>

* Instale Python de https://python.org (marque “Add to PATH”) ou `winget install Python.Python.3.12`
* No PowerShell pode precisar `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` pra ativar venv
* Se `hubctl` não for encontrado, feche e reabra o terminal ou adicione `%USERPROFILE%\AppData\Roaming\Python\Scripts` ao PATH
</details>

<details>
<summary>🍎 macOS: detalhes</summary>

* `brew install python@3.12 git` e depois `pip install hubctl`
* Config fica em `~/Library/Application Support/hubctl/config.ini` (ou `~/.config/hubctl/` se `XDG_CONFIG_HOME` estiver setado)
</details>

<details>
<summary>🐧 Linux: detalhes</summary>

* `sudo apt install python3-pip git` (Debian/Ubuntu) ou `sudo pacman -S python-pip git` (Arch)
* `pip install --user hubctl` se não usar pipx/uv
</details>

---

## 🚀 Quickstart

```bash
# 1. Autentique (crie o token em https://github.com/settings/tokens)
hubctl auth login
# ou
export GITHUB_TOKEN="ghp_xxx"
hubctl auth status

# 2. Entre no modo interativo (sem decorar nada)
hubctl
# ou
hubctl interactive

# 3. Ou use comandos diretos
hubctl repo list --limit 5
hubctl repo view octocat/Hello-World
hubctl repo search "language:python stars:>50000" --limit 3
```

---

## 🎮 Modo Interativo

É o coração do HubCtl. Rode `hubctl` puro:

```
🔐  Autenticação        → Login / Status / Logout
📦  Repositórios        → Listar, Ver, Clonar, Fork, Star, Editar, Criar, Deletar
🔍  Buscar Repos        → Busca global (ex: language:python stars:>1000)
🐛  Issues              → Listar, Ver, Criar, Fechar
🔀  Pull Requests       → Listar, Ver, Criar
❌  Sair
```

* Navegue com **↑/↓ + Enter**
* Escolha repos da sua lista sem digitar `usuario/repo`
* Ao listar repos, atalho direto pra **Ver / Clonar / Fork / Issues / PRs**
* Ao ver um repo, submenu: **Clonar / Fork / Toggle Star / Editar / Issues / PRs / Deletar**

```
   ____ _ _   _           _       ____ _     ___
  / ___(_) |_| |__  _   _| |__   / ___| |   |_ _|
 | |  _| | __| '_ \| | | | '_ \ | |   | |    | |
 ...  Tema: dark (auto) — detectado via COLORFGBG
```

---

## 📖 Comandos

### Autenticação

```bash
hubctl auth login                 # prompt seguro (password)
hubctl auth login --token ghp_xxx
hubctl auth status                # mostra user, repos, seguidores
hubctl auth logout --yes
```

### Repositórios

```bash
hubctl repo list --limit 10 --visibility private  # all/public/private
hubctl repo view octocat/Hello-World              # painel HEAVY com stats
hubctl repo create meu-repo --private --description "Meu projeto"
hubctl repo delete usuario/repo --yes             # confirmação dupla sem --yes
hubctl repo clone usuario/repo --dir ./pasta --ssh
hubctl repo fork usuario/repo                     # fork pra sua conta + dica clone
hubctl repo star usuario/repo
hubctl repo unstar usuario/repo
hubctl repo edit usuario/repo --description "nova desc" --homepage https://site.com
hubctl repo edit usuario/repo --private           # ou --public
hubctl repo search "language:python stars:>5000 cli" --limit 5
```

### Issues

```bash
hubctl issue list usuario/repo --state open --limit 10  # open/closed/all
hubctl issue view usuario/repo 123
hubctl issue create usuario/repo --title "Bug" --body "descrição" --label bug --labels "help wanted, good first issue"
hubctl issue close usuario/repo 123
```

### Pull Requests

```bash
hubctl pr list usuario/repo --state open
hubctl pr view usuario/repo 123                   # mostra branch, +/-, arquivos
hubctl pr create usuario/repo --title "feat" --head feature/xyz --base main --body "desc" --draft
```

### Config / Tema

```bash
hubctl config theme              # mostra atual + preview (auto)
hubctl config theme light        # força claro (pra terminal branco)
hubctl config theme dark         # força escuro
hubctl config theme auto         # auto-detecta
hubctl config show               # vê ~/.config/github-cli/config.ini

# override só da sessão
GHC_THEME=light hubctl repo list
GHC_THEME=dark hubctl repo view octocat/Hello-World
```

Todas as views públicas (`view`, `search`, `issue/pr list/view`, `clone` público) funcionam **sem token**.

---

## 🎨 Tema Dinâmico

Seu terminal é branco e as letras somem? HubCtl detecta sozinho.

* **Auto (padrão):** lê `COLORFGBG` (`0;15` = fundo branco → light, `15;0` = fundo preto → dark). Fallback: `dark`.
* **Manual:** `hubctl config theme light` salva em `config.ini` `[ui] theme = light` (caminho varia por OS, veja `hubctl config show`).
* **Env:** `GHC_THEME` ou `HUBCTL_THEME` (`light|dark|auto`) tem prioridade máxima (útil no Windows: `set HUBCTL_THEME=light`).

| Tema | Cores | Pra onde |
|------|-------|----------|
| **dark** | `primary #00D9FF` / `secondary #B537F2` / `success #00F5A0` | fundo preto |
| **light** | `primary #0070C9` / `secondary #6A1B9A` / `success #0A7A3A` | fundo branco |

Fix: `[white]` removido — usa `bold` que herda cor do terminal, visível nos dois fundos. `questionary` também troca (`fg:#0070C9` no claro).

```bash
# seu terminal branco tá ilegível?
hubctl config theme light   # resolve pra sempre
# ou só agora
GHC_THEME=light hubctl
```

---

## ⚙️ Configuração

HubCtl salva tudo num único `config.ini` multiplataforma:

| OS | Caminho |
|----|---------|
| **Linux** | `~/.config/hubctl/config.ini` (`$XDG_CONFIG_HOME/hubctl/` se setado) |
| **macOS** | `~/Library/Application Support/hubctl/config.ini` ou `~/.config/hubctl/` |
| **Windows** | `%APPDATA%\hubctl\config.ini` (ex: `C:\Users\Você\AppData\Roaming\hubctl\config.ini`) |

Compatibilidade: na primeira execução HubCtl migra automaticamente de `~/.config/github-cli/config.ini` (legado) pra nova pasta.

```ini
# exemplo (~/.config/hubctl/config.ini no Linux)
[auth]
token = ghp_xxx

[ui]
theme = auto  # dark | light | auto
```

* `chmod 600` no Linux/macOS, ignorado no Windows (sem erro)
* Prioridade token: `--token` > `GITHUB_TOKEN`/`GH_TOKEN` env > `config.ini`
* `hubctl auth logout` preserva `[ui]` (só remove `token`)
* `hubctl config show` mostra o caminho real no seu OS + token mascarado `ghp_***`

---

## 🛠️ Desenvolvimento

```bash
git clone https://github.com/seu-usuario/hubctl.git
cd hubctl
uv pip install -e ".[dev]"  # ou pip install -e .
hubctl --help
hubctl repo view octocat/Hello-World
```

Estrutura:

```
src/github_cli/
  ui.py           # tema dinâmico claro/escuro, banner, tabelas, painéis
  github.py       # GitHubClient (repos, issues, prs, fork/star/edit/search)
  config.py       # token + theme (get_theme/save_theme)
  main.py         # typer CLI + config theme
  interactive.py  # TUI completo com setas + style adaptativo
```

Stack: `typer[all]` + `rich` + `requests` + `questionary` + `platformdirs` (config multiplataforma)

---

## 🗺️ Roadmap

- [x] Clone com `git` + token inject pra privado
- [x] Fork / Star / Edit / Search
- [x] Issues/PRs create/view/close
- [x] Tema claro/escuro dinâmico
- [ ] `repo sync` (fork sync)
- [ ] `issue comment` + `pr merge`
- [ ] `hubctl completion` (fish/zsh/bash)

PRs e issues são bem-vindos!

---

## 🤝 Contribuindo

1. Fork o repo
2. Crie um branch `feat/minha-feature`
3. `hubctl repo create` ou use o fork local
4. Abra um PR com `hubctl pr create`

---

## 📄 Licença

MIT — veja [LICENSE](LICENSE).

---

<div align="center">

**Feito com 💜 + `rich` + `questionary` — HubCtl, seu GitHub no terminal.**

`hubctl` • `hubctl interactive` • `GHC_THEME=light hubctl`

</div>
# GithubCLI-HubCtl
