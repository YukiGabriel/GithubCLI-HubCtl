import os
import platform
import configparser
from pathlib import Path

def _get_config_dir(app: str = "hubctl") -> Path:
    """Retorna diretório de config multiplataforma (Windows/macOS/Linux)"""
    try:
        from platformdirs import user_config_dir
        return Path(user_config_dir(app))
    except ImportError:
        # fallback manual sem plataforma extra
        system = platform.system()
        if system == "Windows":
            base = os.getenv("APPDATA")
            if base:
                return Path(base) / app
            return Path.home() / "AppData" / "Roaming" / app
        elif system == "Darwin":
            # macOS: respeita XDG se existir, senão Library
            xdg = os.getenv("XDG_CONFIG_HOME")
            if xdg and Path(xdg).exists():
                return Path(xdg) / app
            return Path.home() / "Library" / "Application Support" / app
        else:
            # Linux / BSD
            xdg = os.getenv("XDG_CONFIG_HOME")
            if xdg:
                return Path(xdg) / app
            return Path.home() / ".config" / app

CONFIG_DIR = _get_config_dir("hubctl")
CONFIG_FILE = CONFIG_DIR / "config.ini"
# legacy path para migração (github-cli -> hubctl)
_LEGACY_DIR = _get_config_dir("github-cli")
_LEGACY_FILE = _LEGACY_DIR / "config.ini"
# fallback extra: ~/.config/github-cli direto (caso platformdirs não estava antes)
_FALLBACK_LEGACY = Path.home() / ".config" / "github-cli" / "config.ini"

def _read_config_with_fallback() -> tuple[configparser.ConfigParser, Path | None]:
    """Lê config de hubctl, com fallback pro legacy github-cli. Retorna (cfg, arquivo_usado)"""
    for p in (CONFIG_FILE, _LEGACY_FILE, _FALLBACK_LEGACY):
        if p.exists():
            cfg = configparser.ConfigParser()
            cfg.read(p)
            return cfg, p
    return configparser.ConfigParser(), None

def _migrate_legacy_if_needed():
    """Se existe legacy e não existe novo, migra automaticamente (suporta ambos legados)"""
    legacy_src = None
    if _LEGACY_FILE.exists() and not CONFIG_FILE.exists():
        legacy_src = _LEGACY_FILE
    elif _FALLBACK_LEGACY.exists() and not CONFIG_FILE.exists() and not _LEGACY_FILE.exists():
        legacy_src = _FALLBACK_LEGACY
    # também migra se _FALLBACK tem e _LEGACY não tem mas novo não tem
    elif _FALLBACK_LEGACY.exists() and _LEGACY_FILE.exists() and not CONFIG_FILE.exists():
        # prefere o mais recente? usa _LEGACY_FILE já tratado acima, mas se ambos existem, usa _LEGACY_FILE
        legacy_src = _LEGACY_FILE
    if legacy_src:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(legacy_src, CONFIG_FILE)
            try:
                os.chmod(CONFIG_FILE, 0o600)
            except Exception:
                pass
        except Exception:
            pass

def get_token(token: str | None = None) -> str | None:
    """Resolve token: param > env > config file (hubctl -> fallback github-cli)"""
    if token:
        return token
    env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if env_token:
        return env_token
    _migrate_legacy_if_needed()
    for p in (CONFIG_FILE, _LEGACY_FILE, _FALLBACK_LEGACY):
        if p.exists():
            cfg = configparser.ConfigParser()
            cfg.read(p)
            if "auth" in cfg and "token" in cfg["auth"]:
                return cfg["auth"]["token"]
    return None

def save_token(token: str):
    _migrate_legacy_if_needed()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        cfg.read(CONFIG_FILE)
    elif _LEGACY_FILE.exists():
        cfg.read(_LEGACY_FILE)
    elif _FALLBACK_LEGACY.exists():
        cfg.read(_FALLBACK_LEGACY)
    if "auth" not in cfg:
        cfg["auth"] = {}
    cfg["auth"]["token"] = token
    with open(CONFIG_FILE, "w") as f:
        cfg.write(f)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except Exception:
        pass

def require_token(token: str | None = None) -> str:
    t = get_token(token)
    if not t:
        raise ValueError(
            "Token não encontrado. Use 'hubctl auth login' ou defina GITHUB_TOKEN"
        )
    return t

def delete_token():
    # Remove token de todos os arquivos (hubctl, legacy platformdirs, fallback), preservando [ui]
    deleted = False
    for p, d in ((CONFIG_FILE, CONFIG_DIR), (_LEGACY_FILE, _LEGACY_DIR), (_FALLBACK_LEGACY, _FALLBACK_LEGACY.parent)):
        if p.exists():
            cfg = configparser.ConfigParser()
            cfg.read(p)
            if "auth" in cfg:
                del cfg["auth"]
                deleted = True
            has_data = any(cfg.sections())
            if has_data:
                with open(p, "w") as f:
                    cfg.write(f)
                try:
                    os.chmod(p, 0o600)
                except Exception:
                    pass
            else:
                p.unlink()
                try:
                    if not any(d.iterdir()):
                        d.rmdir()
                except Exception:
                    pass
    return deleted

def get_theme() -> str:
    """Retorna tema salvo: dark/light/auto (padrão auto)"""
    env_theme = os.getenv("GHC_THEME")
    if env_theme in ("dark", "light", "auto"):
        return env_theme
    env2 = os.getenv("HUBCTL_THEME")
    if env2 in ("dark", "light", "auto"):
        return env2
    _migrate_legacy_if_needed()
    for p in (CONFIG_FILE, _LEGACY_FILE, _FALLBACK_LEGACY):
        if p.exists():
            cfg = configparser.ConfigParser()
            cfg.read(p)
            if "ui" in cfg and "theme" in cfg["ui"]:
                t = cfg["ui"]["theme"].strip().lower()
                if t in ("dark", "light", "auto"):
                    return t
    return "auto"

def save_theme(theme: str):
    """Salva preferência de tema: dark/light/auto"""
    theme = theme.lower().strip()
    if theme not in ("dark", "light", "auto"):
        raise ValueError("Tema deve ser dark, light ou auto")
    _migrate_legacy_if_needed()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        cfg.read(CONFIG_FILE)
    elif _LEGACY_FILE.exists():
        cfg.read(_LEGACY_FILE)
    elif _FALLBACK_LEGACY.exists():
        cfg.read(_FALLBACK_LEGACY)
    if "ui" not in cfg:
        cfg["ui"] = {}
    cfg["ui"]["theme"] = theme
    with open(CONFIG_FILE, "w") as f:
        cfg.write(f)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except Exception:
        pass

# ---------- Recents (últimos repos acessados) ----------
def get_recents(limit: int = 10) -> list[str]:
    _migrate_legacy_if_needed()
    for p in (CONFIG_FILE, _LEGACY_FILE, _FALLBACK_LEGACY):
        if p.exists():
            cfg = configparser.ConfigParser()
            cfg.read(p)
            if "recent" in cfg and "repos" in cfg["recent"]:
                raw = cfg["recent"]["repos"]
                items = [s.strip() for s in raw.split(",") if s.strip()]
                return items[:limit]
    return []

def save_recent(full_name: str, limit: int = 10):
    full_name = full_name.strip()
    if not full_name or "/" not in full_name:
        return
    _migrate_legacy_if_needed()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        cfg.read(CONFIG_FILE)
    recents = get_recents(limit=50)
    # move to front, dedup
    recents = [r for r in recents if r.lower() != full_name.lower()]
    recents.insert(0, full_name)
    recents = recents[:limit]
    if "recent" not in cfg:
        cfg["recent"] = {}
    cfg["recent"]["repos"] = ", ".join(recents)
    with open(CONFIG_FILE, "w") as f:
        cfg.write(f)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except Exception:
        pass

def clear_recents():
    for p in (CONFIG_FILE, _LEGACY_FILE, _FALLBACK_LEGACY):
        if p.exists():
            cfg = configparser.ConfigParser()
            cfg.read(p)
            if "recent" in cfg:
                del cfg["recent"]
                with open(p, "w") as f:
                    cfg.write(f)
                try:
                    os.chmod(p, 0o600)
                except Exception:
                    pass
            break
