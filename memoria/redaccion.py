"""Quita secretos antes de guardar texto en la base."""
import re

PATRONES = [
    ("clave_privada", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("anthropic", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("github", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("aws", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("bearer", re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{20,}")),
    ("url_con_clave", re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+(@)")),
    ("asignacion", re.compile(
        r"(?i)\b([A-Z0-9_]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|clave)[A-Z0-9_]*"
        r"\s*[=:]\s*[\"']?)([^\s\"']{8,})")),
]


def redactar(texto):
    """Devuelve (texto_redactado, cantidad_de_reemplazos)."""
    if not texto:
        return texto, 0
    total = 0
    for nombre, patron in PATRONES:
        marca = f"«REDACTADO:{nombre}»"
        if nombre in ("bearer",):
            texto, n = patron.subn(lambda m: m.group(1) + marca, texto)
        elif nombre == "url_con_clave":
            texto, n = patron.subn(lambda m: m.group(1) + marca + m.group(2), texto)
        elif nombre == "asignacion":
            texto, n = patron.subn(lambda m: m.group(1) + marca, texto)
        else:
            texto, n = patron.subn(marca, texto)
        total += n
    return texto, total
