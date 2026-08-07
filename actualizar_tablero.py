#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comando "actualizar tablero" — Centro de Mando RDW.

Recibe el bloque JSON que genera el botón "Copiar actualización" del tablero
(o cualquier JSON con las claves fecha/marcas/semana/gente/objetivos/esperando)
y reescribe SOLO el objeto `const RDW = {...}` dentro de index.html.
El resto del archivo no se toca nunca.

Uso:
    python3 actualizar_tablero.py datos.json        # desde archivo
    pbpaste | python3 actualizar_tablero.py         # desde el portapapeles/stdin
    python3 actualizar_tablero.py --no-push ...     # sin commit ni push (solo reescribe)

Qué hace:
  1. Lee el JSON (ignora cualquier texto antes de la primera "{", porque el
     botón del tablero antepone una frase al bloque).
  2. Conserva las claves que el JSON no trae (p. ej. `estaciones`).
  3. Reescribe el bloque `const RDW = {...};` en index.html.
  4. Copia index.html a la bóveda (07 SISTEMA/tablero/) — la bóveda es la
     fuente de verdad; el tablero es su cara pública.
  5. Commit + push en rdw-tablero. GitHub Pages republica en ~1 minuto.
     (El commit de la bóveda lo hace el protocolo de cierre, no este script.)
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
INDEX = REPO / "index.html"
BOVEDA_COPIA = Path.home() / "RDW" / "boveda" / "07 SISTEMA" / "tablero" / "index.html"
URL = "https://samuelmunozia99-web.github.io/rdw-tablero/"


def leer_payload(texto: str) -> dict:
    """Extrae el objeto JSON aunque venga con texto antes (frase del botón)."""
    inicio = texto.find("{")
    if inicio == -1:
        sys.exit("ERROR: no encontré ningún JSON en la entrada.")
    return json.loads(texto[inicio:])


def bloque_actual(html: str) -> str:
    m = re.search(r"const RDW = \{.*?\n\};", html, flags=re.S)
    if not m:
        sys.exit("ERROR: no encontré el bloque `const RDW = {...};` en index.html.")
    return m.group(0)


def a_js(obj: dict) -> str:
    return "const RDW = " + json.dumps(obj, ensure_ascii=False, indent=2) + ";"


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--no-push"]
    push = "--no-push" not in sys.argv

    texto = Path(args[0]).read_text(encoding="utf-8") if args else sys.stdin.read()
    payload = leer_payload(texto)

    html = INDEX.read_text(encoding="utf-8")
    viejo = bloque_actual(html)

    # El JSON del botón no trae `estaciones`: se rescata del bloque vigente
    # para no perderla al reescribir.
    if "estaciones" not in payload:
        m = re.search(r'"?estaciones"?:\s*(\[[^\]]*\])', viejo)
        if not m:
            sys.exit("ERROR: el JSON no trae `estaciones` y no pude rescatarla del bloque actual.")
        payload = {"fecha": payload.get("fecha"),
                   "estaciones": json.loads(m.group(1)),
                   **payload}

    obligatorias = {"fecha", "marcas", "semana", "gente", "objetivos", "esperando"}
    faltan = obligatorias - payload.keys()
    if faltan:
        sys.exit(f"ERROR: al JSON le faltan claves: {', '.join(sorted(faltan))}.")

    INDEX.write_text(html.replace(viejo, a_js(payload)), encoding="utf-8")
    print(f"✓ index.html reescrito (solo el bloque RDW) — fecha: {payload['fecha']}")

    BOVEDA_COPIA.parent.mkdir(parents=True, exist_ok=True)
    BOVEDA_COPIA.write_text(INDEX.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"✓ copia en la bóveda: {BOVEDA_COPIA}")

    if push:
        subprocess.run(["git", "-C", str(REPO), "add", "index.html"], check=True)
        r = subprocess.run(["git", "-C", str(REPO), "diff", "--cached", "--quiet"])
        if r.returncode == 0:
            print("· sin cambios que publicar")
            return
        subprocess.run(["git", "-C", str(REPO), "commit", "-m",
                        f"Tablero: actualización {payload['fecha']}"], check=True)
        subprocess.run(["git", "-C", str(REPO), "push"], check=True)
        print(f"✓ push hecho — verificando el build de Pages…")
        verificar_build(payload["fecha"])


def verificar_build(fecha: str) -> None:
    """Regla (2026-08-08): un push que no publica es como no haber escrito nada.

    Espera a que el build de Pages termine y confirma que la página sirve la
    fecha nueva. Sale con error si el build falla; avisa si va lento (los 3
    fallos del 8-ago tardaron 10-30 min en runners de GitHub caídos)."""
    import json, time, urllib.request
    sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()[:7]
    api = "https://api.github.com/repos/samuelmunozia99-web/rdw-tablero/actions/runs?per_page=3"
    for i in range(60):  # hasta ~5 min
        time.sleep(5)
        try:
            runs = json.load(urllib.request.urlopen(api))["workflow_runs"]
        except Exception:
            continue
        run = next((r for r in runs if r["head_sha"].startswith(sha)), None)
        if not run:
            continue
        if run["status"] == "completed":
            if run["conclusion"] == "success":
                print(f"✓ build de Pages EN VERDE ({sha})")
                break
            sys.exit(f"❌ BUILD DE PAGES FALLÓ ({run['conclusion']}) — el tablero NO se "
                     f"publicó. Revisar: https://github.com/samuelmunozia99-web/rdw-tablero/actions\n"
                     f"   (Si el error es de runners de GitHub, reintentar con 'Re-run jobs'.)")
    else:
        sys.exit(f"⚠️ El build lleva 5+ min sin terminar (patrón de los fallos del 8-ago). "
                 f"Verificar a mano: https://github.com/samuelmunozia99-web/rdw-tablero/actions")
    # el CDN cachea 10 min la URL limpia; el cache-buster ve el origen directo
    for _ in range(12):
        try:
            html = urllib.request.urlopen(f"{URL}?cb={int(time.time())}").read().decode("utf-8")
            if fecha in html:
                print(f"✓ verificado: la página pública ya sirve «{fecha}» — {URL}")
                print("  (la URL sin parámetros puede tardar hasta 10 min más por el caché del CDN)")
                return
        except Exception:
            pass
        time.sleep(10)
    sys.exit("⚠️ El build pasó pero la página aún no sirve la fecha nueva — verificar a mano.")


if __name__ == "__main__":
    main()
