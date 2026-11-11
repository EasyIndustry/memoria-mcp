"""Proyectos, directorios y archivos (solo metadatos + hash)."""
import datetime
import fnmatch
import hashlib
import os
import subprocess
from pathlib import Path

IGNORAR = [".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache",
           "dist", "build", "*.egg-info", ".DS_Store", "*.pyc"]


def alta(db, nombre, ruta=None, descripcion=None, repo_url=None):
    """Crea o actualiza un proyecto. Devuelve su id."""
    ruta = str(Path(ruta).expanduser().resolve()) if ruta else None
    with db.transaccion():
        fila = db.uno("SELECT id FROM proyectos WHERE nombre=%s", (nombre,))
        if fila:
            db.ejecutar("UPDATE proyectos SET ruta_raiz=COALESCE(%s, ruta_raiz), descripcion=COALESCE(%s, descripcion), "
                        "repo_url=COALESCE(%s, repo_url) WHERE id=%s", (ruta, descripcion, repo_url, fila["id"]))
            db.auditar("proyectos", fila["id"], "actualizar", ruta=ruta)
            return fila["id"]
        pid = db.ejecutar("INSERT INTO proyectos (nombre, ruta_raiz, descripcion, repo_url) VALUES (%s,%s,%s,%s)",
                          (nombre, ruta, descripcion, repo_url))
        db.auditar("proyectos", pid, "crear", ruta=ruta)
        return pid


def listar(db):
    return db.todos("SELECT id, nombre, ruta_raiz, descripcion, archivado, actualizado FROM proyectos ORDER BY nombre")


def por_ruta(db, ruta):
    """Proyecto cuya ruta_raiz contiene `ruta` (el más específico)."""
    if not ruta:
        return None
    ruta = str(Path(ruta).resolve())
    candidatos = [p for p in db.todos("SELECT id, nombre, ruta_raiz FROM proyectos WHERE ruta_raiz IS NOT NULL")
                  if ruta == p["ruta_raiz"] or ruta.startswith(p["ruta_raiz"].rstrip("/") + "/")]
    return max(candidatos, key=lambda p: len(p["ruta_raiz"]), default=None)


def _archivos(raiz, ignorar):
    """Archivos del proyecto: `git ls-files` si es repo (respeta .gitignore), si no un recorrido."""
    try:
        r = subprocess.run(["git", "-C", str(raiz), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, check=True)
        rutas = [p for p in r.stdout.decode().split("\0") if p]
    except (subprocess.CalledProcessError, FileNotFoundError):
        rutas = []
        for dirpath, dirnames, filenames in os.walk(raiz):
            dirnames[:] = [d for d in dirnames if not any(fnmatch.fnmatch(d, p) for p in ignorar)]
            for f in filenames:
                rutas.append(os.path.relpath(os.path.join(dirpath, f), raiz))
    return sorted(p for p in rutas
                  if not any(fnmatch.fnmatch(parte, pat) for parte in Path(p).parts for pat in ignorar))


def _sha256_archivo(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def escanear(db, nombre, ignorar=IGNORAR):
    """Sincroniza directorios y archivos del proyecto con el disco. Devuelve un resumen."""
    p = db.uno("SELECT id, ruta_raiz FROM proyectos WHERE nombre=%s", (nombre,))
    if p is None or not p["ruta_raiz"]:
        raise LookupError(f"el proyecto {nombre!r} no existe o no tiene ruta_raiz")
    raiz = Path(p["ruta_raiz"])
    resumen = {"nuevos": 0, "modificados": 0, "sin_cambios": 0, "desaparecidos": 0}
    with db.transaccion():
        dirs = {f["ruta_relativa"]: f["id"] for f in
                db.todos("SELECT id, ruta_relativa FROM directorios WHERE proyecto_id=%s", (p["id"],))}

        def dir_id(rel):
            if rel in dirs:
                return dirs[rel]
            padre = None if rel == "" else dir_id(str(Path(rel).parent) if Path(rel).parent != Path(".") else "")
            dirs[rel] = db.ejecutar("INSERT INTO directorios (proyecto_id, padre_id, ruta_relativa) VALUES (%s,%s,%s)",
                                    (p["id"], padre, rel))
            return dirs[rel]

        previos = {f["ruta_relativa"]: f for f in
                   db.todos("SELECT id, ruta_relativa, sha256, presente FROM archivos WHERE proyecto_id=%s", (p["id"],))}
        vistos = set()
        for rel in _archivos(raiz, ignorar):
            ruta = raiz / rel
            if not ruta.is_file():
                continue
            vistos.add(rel)
            st = ruta.stat()
            sha = _sha256_archivo(ruta)
            carpeta = str(Path(rel).parent) if Path(rel).parent != Path(".") else ""
            datos = (dir_id(carpeta), ruta.name, ruta.suffix.lstrip(".").lower() or None, st.st_size, sha,
                     datetime.datetime.fromtimestamp(st.st_mtime))
            previo = previos.get(rel)
            if previo is None:
                db.ejecutar("INSERT INTO archivos (proyecto_id, ruta_relativa, directorio_id, nombre, extension, "
                            "tamano_bytes, sha256, modificado_fs) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (p["id"], rel, *datos))
                resumen["nuevos"] += 1
            else:
                cambio = previo["sha256"] != sha or not previo["presente"]
                db.ejecutar("UPDATE archivos SET directorio_id=%s, nombre=%s, extension=%s, tamano_bytes=%s, "
                            "sha256=%s, modificado_fs=%s, presente=TRUE, escaneado=CURRENT_TIMESTAMP(3) WHERE id=%s",
                            (*datos, previo["id"]))
                resumen["modificados" if cambio else "sin_cambios"] += 1
        for rel, previo in previos.items():
            if rel not in vistos and previo["presente"]:
                db.ejecutar("UPDATE archivos SET presente=FALSE, escaneado=CURRENT_TIMESTAMP(3) WHERE id=%s",
                            (previo["id"],))
                resumen["desaparecidos"] += 1
        db.auditar("proyectos", p["id"], "escanear", **resumen)
    return resumen
