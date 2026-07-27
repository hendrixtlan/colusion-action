"""Pruebas de las garantias "a prueba de balas" de la action.

Correr:  cd app && python3 -m pytest pruebas.py -q
No requiere GCP: el repositorio se sustituye por un doble de prueba.
"""
from __future__ import annotations

import importlib
import json
import os

import pytest
from fastapi.testclient import TestClient

os.environ["ACTION_HUB_TOKEN"] = "secreto123"
os.environ["URL_BASE"] = "https://demo.run.app"

import main  # noqa: E402  (despues de fijar el entorno)
import repositorio  # noqa: E402

AUTH = {"Authorization": 'Token token="secreto123"'}


class RepoDoble:
    def __init__(self, fallar_veces: int = 0, nombre_error: str = "Aborted"):
        self.persistidas, self.encoladas = [], []
        self.fallar_veces, self.nombre_error = fallar_veces, nombre_error
        self.verificaciones = 0

    def _tal_vez_fallar(self):
        if self.fallar_veces > 0:
            self.fallar_veces -= 1
            raise type(self.nombre_error, (Exception,), {})("boom")

    def persistir(self, cid, c, consulta_looker=None, usuario=""):
        self._tal_vez_fallar()
        self.persistidas.append((cid, c))

    def encolar_revision(self, cid, c):
        self.encoladas.append((cid, c))

    def verificar(self):
        self.verificaciones += 1


@pytest.fixture()
def cli():
    main._repo = RepoDoble()
    return TestClient(main.app, raise_server_exceptions=False)


def _payload(notas="n1", filas=None):
    filas = filas if filas is not None else [
        {"lic.proveedor_a": {"value": "ACME", "rendered": "Acme S.A."},
         "lic.proveedor_b": {"value": "BETA"},
         "lic.licitacion_id": {"value": "L-1"},
         "lic.score": {"value": "0.8"}}]
    return {"type": "query",
            "scheduled_plan": {"title": "t", "url": "u", "query": {}},
            "attachment": {"data": json.dumps({"fields": {}, "data": filas})},
            "form_params": {"modo": "auto", "notas": notas}}


# ── Autenticacion ──

def test_sin_token_401(cli):
    assert cli.post("/", headers={}).status_code == 401
    assert cli.post("/accion/execute", json=_payload(),
                    headers={"Authorization": 'Token token="malo"'}).status_code == 401


def test_con_token_200(cli):
    assert cli.post("/", headers=AUTH).status_code == 200


# ── Idempotencia (la garantia central) ──

def test_mismo_payload_misma_corrida(cli):
    r1 = cli.post("/accion/execute", json=_payload(), headers=AUTH).json()
    r2 = cli.post("/accion/execute", json=_payload(), headers=AUTH).json()
    c1 = r1["looker"]["message"].split(":")[0]
    c2 = r2["looker"]["message"].split(":")[0]
    assert c1 == c2 and c1.startswith("looker-")
    assert main._repo.persistidas[0][0] == main._repo.persistidas[1][0]


def test_payload_distinto_corrida_distinta(cli):
    c1 = cli.post("/accion/execute", json=_payload("n1"), headers=AUTH) \
        .json()["looker"]["message"].split(":")[0]
    c2 = cli.post("/accion/execute", json=_payload("n2"), headers=AUTH) \
        .json()["looker"]["message"].split(":")[0]
    assert c1 != c2


def test_celda_doble_clic_misma_corrida(cli):
    cuerpo = {"type": "cell", "data": {"value": "ACME"},
              "form_params": {"coludido_con": "BETA", "notas": "x"}}
    c1 = cli.post("/accion/celda", json=cuerpo, headers=AUTH) \
        .json()["looker"]["message"].split(":")[0]
    c2 = cli.post("/accion/celda", json=cuerpo, headers=AUTH) \
        .json()["looker"]["message"].split(":")[0]
    assert c1 == c2


# ── Politica de errores ──

def test_error_de_base_es_503_para_que_looker_reintente(cli):
    main._repo = RepoDoble(fallar_veces=1)
    r = cli.post("/accion/execute", json=_payload(), headers=AUTH)
    assert r.status_code == 503


def test_payload_invalido_es_200_success_false(cli):
    r = cli.post("/accion/execute", headers=AUTH,
                 json={"attachment": {"data": json.dumps([{"x.nada": 1}])}})
    assert r.status_code == 200 and r.json()["looker"]["success"] is False
    r = cli.post("/accion/execute", headers=AUTH,
                 content=b"esto no es json",
                 headers2=None) if False else cli.post(
        "/accion/execute", headers={**AUTH, "Content-Type": "application/json"},
        content=b"{roto")
    assert r.status_code == 200 and r.json()["looker"]["success"] is False


def test_payload_gigante_rechazado_con_mensaje(cli):
    r = cli.post("/accion/execute", json=_payload(),
                 headers={**AUTH, "Content-Length": str(main.MAX_BYTES + 1)})
    assert r.status_code == 200 and "excede" in r.json()["looker"]["message"]


# ── Limites y celdas raras ──

def test_truncado_avisa(cli, monkeypatch):
    monkeypatch.setattr(main, "MAX_FILAS", 2)
    filas = [{"l.proveedor_a": f"P{i}", "l.proveedor_b": f"Q{i}"} for i in range(5)]
    r = cli.post("/accion/execute", json=_payload(filas=filas), headers=AUTH).json()
    assert "2 de 5 filas" in r["looker"]["message"]


def test_scores_raros_y_celdas_dict():
    assert main._a_float("0.85", 0.5) == pytest.approx(0.85)
    assert main._a_float("85%", 0.5) == pytest.approx(0.85)
    assert main._a_float(None, 0.5) == 0.5
    assert main._a_float(True, 0.5) == 0.5
    assert main._valor_celda({"value": 3, "rendered": "3.0"}) == 3
    assert main._valor_celda({"rendered": "solo_texto"}) == "solo_texto"


def test_forma_bipartita_y_revision(cli):
    filas = [{"c.proveedor": "ACME", "c.licitacion_id": "L-9", "c.monto": 12.5}]
    p = _payload(filas=filas)
    p["form_params"]["modo"] = "revision"
    r = cli.post("/accion/execute", json=p, headers=AUTH).json()
    assert r["looker"]["success"] and main._repo.encoladas
    assert main._repo.encoladas[0][1].aristas[0].tipo.value == "PARTICIPO_EN"


# ── Resiliencia del repositorio ──

def test_reintentos_transitorios_convergen():
    intentos = {"n": 0}

    def falla_dos_veces():
        intentos["n"] += 1
        if intentos["n"] < 3:
            raise type("Aborted", (Exception,), {})("transitorio")
        return "ok"

    assert repositorio._con_reintentos(falla_dos_veces) == "ok"
    assert intentos["n"] == 3


def test_error_no_transitorio_propaga_de_inmediato():
    intentos = {"n": 0}

    def falla_definitivo():
        intentos["n"] += 1
        raise ValueError("permanente")

    with pytest.raises(ValueError):
        repositorio._con_reintentos(falla_definitivo)
    assert intentos["n"] == 1


def test_lotes():
    assert [len(l) for l in repositorio._lotes(list(range(1201)), 500)] \
        == [500, 500, 201]


# ── Operacion ──

def test_listo_ok_y_caido(cli):
    assert cli.get("/listo").json() == {"listo": True, "backend": "spanner"}

    class RepoCaido(RepoDoble):
        def verificar(self):
            raise ConnectionError("sin base")

    main._repo = RepoCaido()
    assert cli.get("/listo").status_code == 503
