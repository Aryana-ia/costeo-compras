"""Guardado de perfiles de proveedores, lista de precios e historial.

Dos destinos:

* **Disco local** (carpeta ``data/``): siempre. Cuando la app corre en tu PC,
  esto basta y los datos persisten.
* **GitHub** (opcional): en Streamlit Community Cloud el disco se borra cada vez
  que la app se reinicia. Si en *Secrets* se configura::

      [github]
      token  = "github_pat_..."        # permiso Contents: Read and write
      repo   = "Aryana-ia/costeo-compras"
      branch = "datos"                 # rama separada: no reinicia la app

  cada guardado también se sube a esa rama, y al arrancar se lee de ahí.
  Se usa una rama distinta a ``main`` porque Streamlit Cloud redespliega la app
  con cada commit en la rama que publica.
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from .modelos import ErrorDeDatos, Proveedor

RAIZ = Path(__file__).resolve().parent.parent
DATA_DIR = RAIZ / "data"
API = "https://api.github.com"
TIMEOUT = 20

ARCH_PROVEEDORES = "proveedores.json"
ARCH_LISTA = "lista_precios.csv"
ARCH_HISTORIAL = "historial.csv"


@dataclass
class ConfigGitHub:
    token: str
    repo: str
    branch: str = "datos"
    carpeta: str = "data"

    @classmethod
    def desde_secrets(cls, secrets) -> "ConfigGitHub | None":
        try:
            g = secrets.get("github") if secrets else None
        except Exception:  # noqa: BLE001 - st.secrets lanza si no existe el archivo
            return None
        if not g or not g.get("token") or not g.get("repo"):
            return None
        return cls(token=g["token"], repo=g["repo"], branch=g.get("branch", "datos"), carpeta=g.get("carpeta", "data"))


class ErrorGitHub(RuntimeError):
    pass


class GitHub:
    def __init__(self, cfg: ConfigGitHub):
        self.cfg = cfg
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {cfg.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Accept": "application/vnd.github+json",
        })
        self._rama_ok = False

    def _url(self, nombre: str) -> str:
        return f"{API}/repos/{self.cfg.repo}/contents/{self.cfg.carpeta}/{nombre}"

    def _check(self, r: requests.Response, que: str) -> None:
        if r.status_code >= 400:
            detalle = r.json().get("message", r.text[:200]) if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
            raise ErrorGitHub(f"GitHub respondió {r.status_code} al {que}: {detalle}")

    def asegurar_rama(self) -> None:
        if self._rama_ok:
            return
        r = self.s.get(f"{API}/repos/{self.cfg.repo}/branches/{self.cfg.branch}", timeout=TIMEOUT)
        if r.status_code == 404:
            repo = self.s.get(f"{API}/repos/{self.cfg.repo}", timeout=TIMEOUT)
            self._check(repo, "leer el repositorio")
            base = repo.json()["default_branch"]
            ref = self.s.get(f"{API}/repos/{self.cfg.repo}/git/ref/heads/{base}", timeout=TIMEOUT)
            self._check(ref, "leer la rama principal")
            nueva = self.s.post(f"{API}/repos/{self.cfg.repo}/git/refs", timeout=TIMEOUT,
                                json={"ref": f"refs/heads/{self.cfg.branch}", "sha": ref.json()["object"]["sha"]})
            self._check(nueva, f"crear la rama {self.cfg.branch}")
        else:
            self._check(r, f"leer la rama {self.cfg.branch}")
        self._rama_ok = True

    def leer(self, nombre: str) -> bytes | None:
        self.asegurar_rama()
        r = self.s.get(self._url(nombre), params={"ref": self.cfg.branch}, timeout=TIMEOUT,
                       headers={"Accept": "application/vnd.github.raw"})
        if r.status_code == 404:
            return None
        self._check(r, f"leer {nombre}")
        return r.content

    def escribir(self, nombre: str, contenido: bytes, mensaje: str) -> None:
        self.asegurar_rama()
        meta = self.s.get(self._url(nombre), params={"ref": self.cfg.branch}, timeout=TIMEOUT)
        sha = meta.json().get("sha") if meta.status_code == 200 else None
        if meta.status_code not in (200, 404):
            self._check(meta, f"consultar {nombre}")
        cuerpo = {"message": mensaje, "content": base64.b64encode(contenido).decode(), "branch": self.cfg.branch}
        if sha:
            cuerpo["sha"] = sha
        r = self.s.put(self._url(nombre), json=cuerpo, timeout=60)
        self._check(r, f"guardar {nombre}")


class Almacen:
    """Lee y escribe los datos de la app en disco y, si está configurado, en GitHub."""

    def __init__(self, directorio: Path = DATA_DIR, github: ConfigGitHub | None = None):
        self.dir = Path(directorio)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.gh = GitHub(github) if github else None

    @property
    def sincroniza(self) -> bool:
        return self.gh is not None

    # -- bytes ---------------------------------------------------------------
    def _leer(self, nombre: str) -> tuple[bytes | None, str]:
        """Devuelve (contenido, origen). GitHub tiene prioridad sobre el disco."""
        if self.gh:
            try:
                datos = self.gh.leer(nombre)
                if datos is not None:
                    (self.dir / nombre).write_bytes(datos)  # copia local
                    return datos, "github"
            except (ErrorGitHub, requests.RequestException) as e:
                local = self.dir / nombre
                if local.exists():
                    return local.read_bytes(), f"disco (GitHub no respondió: {e})"
                raise ErrorDeDatos(f"No se pudo leer {nombre} de GitHub: {e}") from e
        local = self.dir / nombre
        return (local.read_bytes(), "disco") if local.exists() else (None, "")

    def _escribir(self, nombre: str, datos: bytes, mensaje: str) -> str:
        """Guarda en disco y en GitHub. Devuelve un texto de estado."""
        (self.dir / nombre).write_bytes(datos)
        if not self.gh:
            return "Guardado en este equipo."
        try:
            self.gh.escribir(nombre, datos, mensaje)
            return f"Guardado y sincronizado en GitHub (rama {self.gh.cfg.branch})."
        except (ErrorGitHub, requests.RequestException) as e:
            raise ErrorDeDatos(f"Se guardó en este equipo, pero no en GitHub: {e}") from e

    # -- proveedores ---------------------------------------------------------
    def cargar_proveedores(self) -> list[Proveedor]:
        datos, _ = self._leer(ARCH_PROVEEDORES)
        if datos is None:
            return []
        try:
            lista = json.loads(datos.decode("utf-8"))
            return [Proveedor.desde_dict(p) for p in lista]
        except (json.JSONDecodeError, ErrorDeDatos, TypeError) as e:
            raise ErrorDeDatos(f"El archivo {ARCH_PROVEEDORES} está dañado: {e}") from e

    def guardar_proveedores(self, proveedores: list[Proveedor]) -> str:
        texto = json.dumps([p.a_dict() for p in proveedores], ensure_ascii=False, indent=2)
        return self._escribir(ARCH_PROVEEDORES, texto.encode("utf-8"), "Actualiza perfiles de proveedores")

    # -- tablas --------------------------------------------------------------
    def cargar_tabla(self, nombre: str) -> tuple[pd.DataFrame | None, str]:
        datos, origen = self._leer(nombre)
        if datos is None:
            return None, ""
        try:
            return pd.read_csv(io.BytesIO(datos), dtype={"CODIGO": str, "FACTURA": str, "RIF": str, "CONTACTO": str}, keep_default_na=True), origen
        except Exception as e:  # noqa: BLE001
            raise ErrorDeDatos(f"El archivo {nombre} está dañado: {e}") from e

    def guardar_tabla(self, nombre: str, df: pd.DataFrame, mensaje: str) -> str:
        return self._escribir(nombre, df.to_csv(index=False).encode("utf-8"), mensaje)
