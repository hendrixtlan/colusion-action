"""Genera los diagramas del README en par claro/oscuro.

    python3 docs/img/generar.py

Sigue la convencion visual de las laminas de fleet-agent: sans del sistema,
neutros de grafito sobre el lienzo de GitHub, **indigo** para lo que hace un
LLM, **neutro** para el codigo determinista y la infraestructura, **ambar**
para la intervencion humana. Conectores ortogonales, etiquetas de arista en
versalitas. Editar aqui y regenerar; no editar los .svg a mano.
"""
import math
import pathlib

AQUI = pathlib.Path(__file__).parent

LIGHT = dict(bg="#FFFFFF", card="#F6F8FA", borde="#D1D9E0", ink="#1F2328",
             muted="#59636E", acc="#4F46E5", accfill="#EEF2FF",
             amb="#B45309", ambfill="#FDF3DE", sufijo="light")
DARK = dict(bg="#0D1117", card="#161B22", borde="#3D444D", ink="#E6EDF3",
            muted="#9198A1", acc="#818CF8", accfill="#20263F",
            amb="#E3A008", ambfill="#2E2410", sufijo="dark")

SANS = "-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"


# ── primitivas ──────────────────────────────────────────────────────────────

def txt(p, x, y, t, size=13, w=400, color=None, anchor="middle", ls=0):
    c = color or p["ink"]
    extra = f' letter-spacing="{ls}"' if ls else ""
    return (f'<text x="{x}" y="{y}" font-family="{SANS}" font-size="{size}" '
            f'font-weight="{w}" fill="{c}" text-anchor="{anchor}"{extra}>{t}</text>')


def kicker(p, x, y, t):
    return txt(p, x, y, t, size=11, w=600, color=p["acc"], anchor="start", ls=2.5)


def etiqueta(p, x, y, t, color=None, anchor="middle"):
    """Etiqueta de arista: versalitas con tracking."""
    return txt(p, x, y, t.upper(), size=9.5, w=600, color=color or p["muted"],
               anchor=anchor, ls=1.1)


def estrella(p, cx, cy, r):
    """Chispa IA de cuatro puntas."""
    k = r * 0.27
    d = (f'M {cx} {cy-r} L {cx+k} {cy-k} L {cx+r} {cy} L {cx+k} {cy+k} '
         f'L {cx} {cy+r} L {cx-k} {cy+k} L {cx-r} {cy} L {cx-k} {cy-k} Z')
    return f'<path d="{d}" fill="{p["acc"]}"/>'


def card(p, x, y, w, h, titulo, sub=None, acento=False, ambar=False,
         chispa=False, rx=10):
    if ambar:
        fill, stroke = p["ambfill"], p["amb"]
    elif acento:
        fill, stroke = p["accfill"], p["acc"]
    else:
        fill, stroke = p["card"], p["borde"]
    s = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
         f'fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
    cy = y + h / 2
    if sub:
        s += txt(p, x + w / 2, cy - 3, titulo, size=13.5, w=600)
        s += txt(p, x + w / 2, cy + 15, sub, size=11, color=p["muted"])
    else:
        s += txt(p, x + w / 2, cy + 4, titulo, size=13.5, w=600)
    if chispa:
        bx, by = x + w - 4, y + 4
        s += (f'<circle cx="{bx}" cy="{by}" r="8.5" fill="{p["bg"]}" '
              f'stroke="{p["acc"]}" stroke-width="1.2"/>')
        s += estrella(p, bx, by, 4.5)
    return s


def flecha(p, puntos, color=None, w=1.5, dash=None):
    """Polilinea ortogonal o recta con chevron al final."""
    c = color or p["muted"]
    d = "M " + " L ".join(f"{x} {y}" for x, y in puntos)
    dd = f' stroke-dasharray="{dash}"' if dash else ""
    (x1, y1), (x2, y2) = puntos[-2], puntos[-1]
    a = math.atan2(y2 - y1, x2 - x1)
    s = (f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{w}"{dd} '
         f'stroke-linejoin="round"/>')
    for da in (2.7, -2.7):
        s += (f'<line x1="{x2}" y1="{y2}" x2="{x2 + 8*math.cos(a+da):.1f}" '
              f'y2="{y2 + 8*math.sin(a+da):.1f}" stroke="{c}" stroke-width="{w}" '
              f'stroke-linecap="round"/>')
    return s


def curva(p, x1, y1, x2, y2, comba=0, color=None, w=1.5, dash=None):
    c = color or p["muted"]
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1
    cx, cy = mx - dy / L * comba, my + dx / L * comba
    dd = f' stroke-dasharray="{dash}"' if dash else ""
    a = math.atan2(y2 - cy, x2 - cx)
    s = (f'<path d="M {x1} {y1} Q {cx:.1f} {cy:.1f} {x2} {y2}" fill="none" '
         f'stroke="{c}" stroke-width="{w}"{dd}/>')
    for da in (2.7, -2.7):
        s += (f'<line x1="{x2}" y1="{y2}" x2="{x2 + 8*math.cos(a+da):.1f}" '
              f'y2="{y2 + 8*math.sin(a+da):.1f}" stroke="{c}" stroke-width="{w}" '
              f'stroke-linecap="round"/>')
    return s


def rombo(p, cx, cy, t, hw=54, hh=30):
    d = f'M {cx} {cy-hh} L {cx+hw} {cy} L {cx} {cy+hh} L {cx-hw} {cy} Z'
    return (f'<path d="{d}" fill="{p["card"]}" stroke="{p["borde"]}" '
            f'stroke-width="1.2"/>' + txt(p, cx, cy + 4, t, size=12, w=600))


def persona(p, cx, cy, r=34, acento=False):
    stroke = p["acc"] if acento else p["borde"]
    fill = p["accfill"] if acento else p["card"]
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.5"/>'
            f'<circle cx="{cx}" cy="{cy-8}" r="7" fill="none" stroke="{p["ink"]}" '
            f'stroke-width="1.8"/>'
            f'<path d="M {cx-14} {cy+16} A 14 14 0 0 1 {cx+14} {cy+16}" fill="none" '
            f'stroke="{p["ink"]}" stroke-width="1.8" stroke-linecap="round"/>')


def documento(p, cx, cy):
    return (f'<rect x="{cx-9}" y="{cy-12}" width="18" height="24" rx="3" '
            f'fill="none" stroke="{p["muted"]}" stroke-width="1.5"/>'
            + "".join(f'<line x1="{cx-4}" y1="{cy-5+i*6}" x2="{cx+4}" y2="{cy-5+i*6}" '
                      f'stroke="{p["muted"]}" stroke-width="1.2"/>' for i in range(3)))


def minigrafo(p, cx, cy, r=34):
    """Glifo de grafo: hexagono con cuerdas internas."""
    pts = [(cx + r * math.cos(a), cy + r * math.sin(a))
           for a in [i * 2 * math.pi / 6 - math.pi / 2 for i in range(6)]]
    pts += [(cx - 9, cy + 3), (cx + 11, cy - 4)]
    aristas = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0),
               (0, 6), (2, 7), (4, 6), (6, 7), (1, 7)]
    s = ""
    for i, j in aristas:
        (x1, y1), (x2, y2) = pts[i], pts[j]
        s += (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
              f'stroke="{p["borde"]}" stroke-width="1.2"/>')
    for k, (x, y) in enumerate(pts):
        col = p["acc"] if k in (0, 6, 7) else p["muted"]
        s += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="{col}"/>'
    return s


def svg(p, w, h, cuerpo):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="{p["bg"]}"/>{cuerpo}</svg>')


def encabezado(p, titulo, sub=None):
    s = kicker(p, 48, 52, "COLUSION-ACTION")
    s += txt(p, 48, 82, titulo, size=22, w=600, anchor="start")
    if sub:
        s += txt(p, 48, 104, sub, size=12.5, color=p["muted"], anchor="start")
    return s


# ── lamina I: arquitectura ─────────────────────────────────────────────────

def arquitectura(p):
    s = encabezado(p, "Arquitectura del sistema",
                   "Un agente en Looker, una action en Cloud Run, un grafo.")

    # analista
    s += persona(p, 74, 322)
    s += txt(p, 74, 380, "analista", size=12.5, w=600)

    # contenedor Google Cloud
    s += (f'<rect x="150" y="140" width="790" height="392" rx="14" fill="none" '
          f'stroke="{p["borde"]}" stroke-width="1.2"/>')
    s += etiqueta(p, 170, 163, "Google Cloud", anchor="start")

    # Looker
    s += (f'<rect x="176" y="180" width="246" height="300" rx="12" '
          f'fill="{p["card"]}" stroke="{p["borde"]}" stroke-width="1.2"/>')
    s += etiqueta(p, 299, 205, "Looker")
    s += card(p, 192, 218, 214, 60, "data agent",
              "Conversational Analytics", acento=True, chispa=True, rx=8)
    s += card(p, 192, 292, 214, 58, "Send · Schedule · celda",
              "el disparo de la action", rx=8)
    s += card(p, 192, 364, 214, 60, "Explores del grafo",
              "GRAPH_TABLE · chord · fuerzas", rx=8)
    s += txt(p, 299, 452, "una sola semántica: LookML", size=11, color=p["muted"])

    # action
    s += etiqueta(p, 566, 244, "Cloud Run")
    s += card(p, 476, 256, 180, 78, "Action", "/accion/execute")
    s += txt(p, 566, 350, "filas → nodos y aristas", size=11, color=p["muted"])

    # revision humana
    s += card(p, 476, 386, 180, 62, "revisión humana",
              "RevisionPendiente", ambar=True)

    # grafo
    s += (f'<rect x="700" y="196" width="216" height="252" rx="12" fill="none" '
          f'stroke="{p["borde"]}" stroke-width="1.2"/>')
    s += etiqueta(p, 808, 221, "El grafo")
    s += card(p, 716, 236, 184, 64, "Spanner Graph", "GrafoColusion · GQL", rx=8)
    s += card(p, 716, 316, 184, 64, "AlloyDB", "esquema espejo", rx=8)
    s += txt(p, 808, 418, "GRAFO_BACKEND", size=11, color=p["muted"])

    # conectores
    s += flecha(p, [(110, 322), (172, 322)])
    s += etiqueta(p, 141, 312, "conversa")
    s += flecha(p, [(406, 321), (472, 321)])
    s += etiqueta(p, 439, 311, "filas")
    # chat propio: el segundo camino de detonacion
    s += curva(p, 408, 244, 474, 274, comba=-14, color=p["acc"],
               dash="4 5", w=1.2)
    s += etiqueta(p, 444, 228, "chat propio", color=p["acc"])
    # escrituras
    s += flecha(p, [(656, 288), (682, 288), (682, 268), (712, 268)])
    s += flecha(p, [(656, 306), (682, 306), (682, 348), (712, 348)])
    s += etiqueta(p, 684, 232, "escribe")
    s += flecha(p, [(566, 334), (566, 382)])
    s += etiqueta(p, 578, 362, "modo revisión", color=p["amb"], anchor="start")
    # el ciclo se cierra
    s += flecha(p, [(808, 448), (808, 506), (299, 506), (299, 484)])
    s += etiqueta(p, 554, 498, "el grafo regresa a Looker")

    return svg(p, 980, 560, s)


# ── lamina II: el camino de la conclusion ──────────────────────────────────

def camino(p):
    s = encabezado(p, "El camino de la conclusión",
                   "El LLM propone, el código dispone, el humano firma.")

    s += f'<circle cx="72" cy="222" r="7" fill="{p["muted"]}"/>'
    s += flecha(p, [(82, 222), (108, 222)])
    s += card(p, 112, 190, 196, 64, "data agent", "arma la consulta",
              acento=True, chispa=True)
    s += flecha(p, [(308, 222), (348, 222)])
    s += etiqueta(p, 328, 212, "filas")
    s += card(p, 352, 190, 180, 64, "normalizar", "código determinista")
    s += flecha(p, [(532, 222), (566, 222)])
    s += card(p, 570, 190, 212, 64, "ConclusionColusion", "nodos · aristas · score")

    # decision
    s += flecha(p, [(676, 254), (676, 292)])
    s += rombo(p, 676, 322, "modo")
    s += flecha(p, [(730, 322), (760, 322), (760, 300), (790, 300)])
    s += etiqueta(p, 757, 288, "auto")
    s += card(p, 794, 268, 148, 64, "GrafoColusion", "insert_or_update")
    s += flecha(p, [(676, 352), (676, 416), (790, 416)])
    s += etiqueta(p, 716, 406, "revisión", color=p["amb"])
    s += card(p, 794, 384, 148, 64, "RevisionPendiente", "PENDIENTE", ambar=True)

    # nota de idempotencia
    s += (f'<rect x="48" y="300" width="380" height="76" rx="10" fill="{p["card"]}" '
          f'stroke="{p["borde"]}" stroke-width="1.2" stroke-dasharray="5 4"/>')
    s += txt(p, 68, 328, "corrida_id = sha256(plan + adjunto + form)",
             size=12.5, w=600, anchor="start")
    s += txt(p, 68, 350, "El reintento de Looker converge: reescribe la misma",
             size=11, color=p["muted"], anchor="start")
    s += txt(p, 68, 366, "corrida en vez de duplicar la conclusión.",
             size=11, color=p["muted"], anchor="start")

    s += txt(p, 48, 460,
             "Ningún LLM tiene credenciales de la base: propone la consulta, "
             "nunca la escritura.",
             size=12, color=p["muted"], anchor="start")
    return svg(p, 980, 500, s)


# ── lamina III: el patron en el grafo ──────────────────────────────────────

def patron(p):
    s = encabezado(p, "El patrón en el grafo",
                   "Lo que la action convierte en aristas.")

    A, B = (250, 240), (250, 424)
    L, C = (540, 332), (818, 332)

    # aristas
    s += flecha(p, [(284, 262), (500, 316)], w=1.5)
    s += etiqueta(p, 378, 250, "participó_en · postura")
    s += txt(p, 378, 268, "gana en t₁", size=11, color=p["muted"])
    s += flecha(p, [(284, 402), (500, 348)], w=1.5)
    s += etiqueta(p, 378, 404, "participó_en · postura")
    s += txt(p, 378, 422, "gana en t₂", size=11, color=p["muted"])
    # la conclusion: indigo
    s += flecha(p, [(250, 278), (250, 386)], color=p["acc"], w=1.8)
    s += etiqueta(p, 226, 326, "coludido_con", color=p["acc"], anchor="end")
    s += txt(p, 226, 344, "score · señales", size=11, color=p["muted"],
             anchor="end")
    # proveniencia
    s += curva(p, 284, 224, 752, 314, comba=-80, dash="4 5", w=1.2)
    s += curva(p, 284, 440, 752, 350, comba=80, dash="4 5", w=1.2)
    s += etiqueta(p, 818, 276, "detectado_en · corrida")

    # nodos
    s += persona(p, *A)
    s += txt(p, A[0], A[1] - 52, "proveedor a", size=12.5, w=600)
    s += persona(p, *B)
    s += txt(p, B[0], B[1] + 58, "proveedor b", size=12.5, w=600)
    s += (f'<rect x="{L[0]-40}" y="{L[1]-40}" width="80" height="80" rx="14" '
          f'fill="{p["card"]}" stroke="{p["borde"]}" stroke-width="1.5" '
          f'transform="rotate(45 {L[0]} {L[1]})"/>')
    s += documento(p, *L)
    s += txt(p, L[0], L[1] - 74, "licitación", size=12.5, w=600)
    s += (f'<rect x="{C[0]-62}" y="{C[1]-30}" width="124" height="60" rx="10" '
          f'fill="{p["card"]}" stroke="{p["borde"]}" stroke-width="1.2"/>')
    s += documento(p, C[0] - 36, C[1])
    s += txt(p, C[0] + 12, C[1] - 2, "corrida", size=13, w=600)
    s += txt(p, C[0] + 12, C[1] + 15, "proveniencia", size=10.5, color=p["muted"])

    s += txt(p, 48, 500,
             "Dos proveedores, las mismas licitaciones y el ganador que alterna: "
             "el patrón que GQL encuentra y la action persiste.",
             size=12, color=p["muted"], anchor="start")
    return svg(p, 980, 540, s)


if __name__ == "__main__":
    laminas = {"arquitectura": arquitectura, "camino": camino, "patron": patron}
    for nombre_l, fn in laminas.items():
        for p in (LIGHT, DARK):
            destino = AQUI / f"{nombre_l}-{p['sufijo']}.svg"
            destino.write_text(fn(p), encoding="utf-8")
            print("→", destino)
