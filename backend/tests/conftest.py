"""
Cliente de Supabase simulado, en memoria.

Reproduce el subconjunto del encadenamiento de postgrest-py que usa el motor:
select/eq/in_/order/limit, upsert con on_conflict simple o compuesto, update,
delete e insert. No pretende ser un Postgres: pretende que las pruebas del
motor no necesiten red ni credenciales.

Lo que NO simula, y por tanto no está cubierto por estas pruebas: los CHECK,
los índices únicos y los triggers de la base de datos real. Eso solo se
verifica ejecutando las migraciones contra Postgres.
"""

from __future__ import annotations

import itertools
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class _Consulta:
    def __init__(self, tabla: _Tabla, operacion: str, datos: Any = None,
                 on_conflict: str | None = None):
        self.tabla = tabla
        self.operacion = operacion
        self.datos = datos
        self.on_conflict = on_conflict
        self.filtros: list[tuple[str, str, Any]] = []
        self._limite: int | None = None
        self._orden: tuple[str, bool] | None = None

    # ── Filtros ──
    def eq(self, campo: str, valor: Any) -> _Consulta:
        self.filtros.append(("eq", campo, valor))
        return self

    def neq(self, campo: str, valor: Any) -> _Consulta:
        self.filtros.append(("neq", campo, valor))
        return self

    def in_(self, campo: str, valores: list) -> _Consulta:
        self.filtros.append(("in", campo, list(valores)))
        return self

    def gte(self, campo: str, valor: Any) -> _Consulta:
        self.filtros.append(("gte", campo, valor))
        return self

    def lte(self, campo: str, valor: Any) -> _Consulta:
        self.filtros.append(("lte", campo, valor))
        return self

    def order(self, campo: str, desc: bool = False) -> _Consulta:
        self._orden = (campo, desc)
        return self

    def limit(self, n: int) -> _Consulta:
        self._limite = n
        return self

    # ── Ejecución ──
    def _coincide(self, fila: dict) -> bool:
        for op, campo, valor in self.filtros:
            actual = fila.get(campo)
            if op == "eq" and actual != valor:
                return False
            if op == "neq" and actual == valor:
                return False
            if op == "in" and actual not in valor:
                return False
            if op == "gte" and (actual is None or str(actual) < str(valor)):
                return False
            if op == "lte" and (actual is None or str(actual) > str(valor)):
                return False
        return True

    def execute(self) -> _Resultado:
        filas = self.tabla.filas

        if self.operacion == "select":
            sel = [f for f in filas if self._coincide(f)]
            if self._orden:
                campo, desc = self._orden
                sel.sort(key=lambda f: (f.get(campo) is None, f.get(campo) or ""), reverse=desc)
            if self._limite is not None:
                sel = sel[: self._limite]
            return _Resultado([dict(f) for f in sel])

        if self.operacion == "insert":
            nuevas = self.datos if isinstance(self.datos, list) else [self.datos]
            creadas = []
            for n in nuevas:
                fila = {"id": str(uuid.uuid4()), **n}
                fila.setdefault("created_at", f"2026-09-10T00:00:{next(self.tabla.reloj):02d}+00:00")
                filas.append(fila)
                creadas.append(dict(fila))
            return _Resultado(creadas)

        if self.operacion == "upsert":
            claves = [c.strip() for c in (self.on_conflict or "id").split(",")]
            nuevas = self.datos if isinstance(self.datos, list) else [self.datos]
            resultado = []
            for n in nuevas:
                existente = next(
                    (f for f in filas if all(f.get(k) == n.get(k) for k in claves)), None
                )
                if existente is not None:
                    existente.update(n)
                    resultado.append(dict(existente))
                else:
                    fila = {"id": str(uuid.uuid4()), **n}
                    fila.setdefault("created_at", f"2026-09-10T00:00:{next(self.tabla.reloj):02d}+00:00")
                    filas.append(fila)
                    resultado.append(dict(fila))
            return _Resultado(resultado)

        if self.operacion == "update":
            afectadas = []
            for f in filas:
                if self._coincide(f):
                    f.update(self.datos)
                    afectadas.append(dict(f))
            return _Resultado(afectadas)

        if self.operacion == "delete":
            borradas = [dict(f) for f in filas if self._coincide(f)]
            self.tabla.filas = [f for f in filas if not self._coincide(f)]
            return _Resultado(borradas)

        raise NotImplementedError(self.operacion)


class _Resultado:
    def __init__(self, data: list[dict]):
        self.data = data


class _Tabla:
    def __init__(self):
        self.filas: list[dict] = []
        self.reloj = itertools.count(1)

    def select(self, *_args, **_kwargs) -> _Consulta:
        return _Consulta(self, "select")

    def insert(self, datos: Any) -> _Consulta:
        return _Consulta(self, "insert", datos)

    def upsert(self, datos: Any, on_conflict: str | None = None) -> _Consulta:
        return _Consulta(self, "upsert", datos, on_conflict)

    def update(self, datos: dict) -> _Consulta:
        return _Consulta(self, "update", datos)

    def delete(self) -> _Consulta:
        return _Consulta(self, "delete")


class ClienteFalso:
    def __init__(self):
        self.tablas: dict[str, _Tabla] = {}

    def table(self, nombre: str) -> _Tabla:
        return self.tablas.setdefault(nombre, _Tabla())

    # Acceso directo para las afirmaciones de las pruebas.
    def filas(self, nombre: str) -> list[dict]:
        return self.table(nombre).filas


@pytest.fixture
def cliente(monkeypatch) -> ClienteFalso:
    """Sustituye el cliente real en todos los módulos que lo usan."""
    falso = ClienteFalso()

    from app.services import db as db_mod

    monkeypatch.setattr(db_mod, "get_client", lambda: falso)
    monkeypatch.setattr("app.services.tree_repository.get_client", lambda: falso)
    # ideas_service hace "from app.services.db import get_client", asi que el
    # nombre queda ligado en SU modulo: parchear solo db no lo alcanza.
    monkeypatch.setattr("app.services.ideas_service.get_client", lambda: falso)
    monkeypatch.setattr("app.services.auth_service.get_client", lambda: falso)
    return falso


@pytest.fixture
def arbol():
    from app.domain.tree_loader import load_tree

    return load_tree()


@pytest.fixture
def sesion(cliente):
    """Sesión ya creada, lista para responder nodos."""
    sid = "s-prueba-0001"
    uid = "u-prueba-0001"
    cliente.table("epm_sessions").filas.append({
        "id": str(uuid.uuid4()),
        "session_id": sid,
        "user_id": uid,
        "user_name": "Facilitadora de prueba",
        "tree_version": "1.0.0",
        "current_node_id": "q00_etapa",
        "estado": "en_progreso",
    })
    return {"session_id": sid, "user_id": uid}
