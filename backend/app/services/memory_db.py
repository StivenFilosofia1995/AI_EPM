"""
Modo demostración: almacenamiento en memoria, sin Supabase.

Se activa solo cuando SUPABASE_URL no está configurada. Reproduce la interfaz
del cliente de Supabase (select/eq/in_/order/limit, upsert con on_conflict,
update, delete, insert) y calcula las vistas al vuelo, de modo que TODO el
sistema funciona sin base de datos: árbol, autenticación, exportaciones y
panel de administración.

LIMITACIONES, que la aplicación advierte en los registros al arrancar:

  · Los datos viven en el proceso. En Railway, cada despliegue empieza vacío.
  · No hay CHECK, ni índices únicos, ni triggers: las garantías las da el
    backend, no el motor de base de datos.
  · No sirve para varias réplicas: cada una tendría sus propios datos.

Es para demostrar y para desarrollar. Para uso institucional real hay que
configurar Supabase y ejecutar sql/esquema_completo.sql.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Persistencia local opcional: hace que un reinicio en tu máquina no borre la
# demostración. En Railway el sistema de archivos es efímero y se pierde igual.
ARCHIVO = Path(__file__).resolve().parent.parent.parent / "datos_demo.json"

_LOCK = threading.RLock()


def _ahora() -> str:
    return datetime.now(UTC).isoformat()


class _Resultado:
    def __init__(self, data: list[dict]):
        self.data = data


class _Consulta:
    def __init__(self, db: MemoryDB, tabla: str, operacion: str,
                 datos: Any = None, on_conflict: str | None = None):
        self.db = db
        self.tabla = tabla
        self.operacion = operacion
        self.datos = datos
        self.on_conflict = on_conflict
        self.filtros: list[tuple[str, str, Any]] = []
        self._limite: int | None = None
        self._orden: tuple[str, bool] | None = None

    # ── Encadenamiento ──
    def select(self, *_a, **_k) -> _Consulta:
        return self

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

    # ── Filtrado ──
    def _coincide(self, fila: dict) -> bool:
        for op, campo, valor in self.filtros:
            actual = fila.get(campo)
            if op == "eq" and actual != valor:
                return False
            if op == "neq" and actual == valor:
                return False
            if op == "in" and actual not in valor:
                return False
            if op == "gte":
                if actual is None:
                    return False
                try:
                    if float(actual) < float(valor):
                        return False
                except (TypeError, ValueError):
                    if str(actual) < str(valor):
                        return False
            if op == "lte":
                if actual is None:
                    return False
                try:
                    if float(actual) > float(valor):
                        return False
                except (TypeError, ValueError):
                    if str(actual) > str(valor):
                        return False
        return True

    def execute(self) -> _Resultado:
        with _LOCK:
            return self._ejecutar()

    def _ejecutar(self) -> _Resultado:
        if self.tabla.startswith("v_"):
            if self.operacion != "select":
                raise RuntimeError(f"{self.tabla} es una vista: solo admite lectura.")
            filas = self.db.calcular_vista(self.tabla)
            return self._filtrar(filas)

        filas = self.db.tablas.setdefault(self.tabla, [])

        if self.operacion == "select":
            return self._filtrar(filas)

        if self.operacion == "insert":
            nuevas = self.datos if isinstance(self.datos, list) else [self.datos]
            creadas = []
            for n in nuevas:
                fila = {"id": str(uuid.uuid4()), "created_at": _ahora(), **n}
                fila.setdefault("updated_at", fila["created_at"])
                filas.append(fila)
                creadas.append(dict(fila))
            self.db.guardar()
            return _Resultado(creadas)

        if self.operacion == "upsert":
            claves = [c.strip() for c in (self.on_conflict or "id").split(",")]
            nuevas = self.datos if isinstance(self.datos, list) else [self.datos]
            salida = []
            for n in nuevas:
                existente = next(
                    (f for f in filas if all(f.get(k) == n.get(k) for k in claves)), None
                )
                if existente is not None:
                    existente.update(n)
                    existente["updated_at"] = _ahora()
                    salida.append(dict(existente))
                else:
                    fila = {"id": str(uuid.uuid4()), "created_at": _ahora(), **n}
                    fila.setdefault("updated_at", fila["created_at"])
                    filas.append(fila)
                    salida.append(dict(fila))
            self.db.guardar()
            return _Resultado(salida)

        if self.operacion == "update":
            afectadas = []
            for f in filas:
                if self._coincide(f):
                    # Emula el trigger de historial de epm_respuestas.
                    if self.tabla == "epm_respuestas":
                        self.db.archivar_si_cambia(f, self.datos)
                    f.update(self.datos)
                    f["updated_at"] = _ahora()
                    afectadas.append(dict(f))
            self.db.guardar()
            return _Resultado(afectadas)

        if self.operacion == "delete":
            borradas = [dict(f) for f in filas if self._coincide(f)]
            self.db.tablas[self.tabla] = [f for f in filas if not self._coincide(f)]
            self.db.guardar()
            return _Resultado(borradas)

        raise NotImplementedError(self.operacion)

    def _filtrar(self, filas: list[dict]) -> _Resultado:
        sel = [f for f in filas if self._coincide(f)]
        if self._orden:
            campo, desc = self._orden
            sel.sort(key=lambda f: (f.get(campo) is None, str(f.get(campo) or "")), reverse=desc)
        if self._limite is not None:
            sel = sel[: self._limite]
        return _Resultado([dict(f) for f in sel])


class _Tabla:
    def __init__(self, db: MemoryDB, nombre: str):
        self.db = db
        self.nombre = nombre

    def select(self, *_a, **_k) -> _Consulta:
        return _Consulta(self.db, self.nombre, "select")

    def insert(self, datos: Any) -> _Consulta:
        return _Consulta(self.db, self.nombre, "insert", datos)

    def upsert(self, datos: Any, on_conflict: str | None = None) -> _Consulta:
        return _Consulta(self.db, self.nombre, "upsert", datos, on_conflict)

    def update(self, datos: dict) -> _Consulta:
        return _Consulta(self.db, self.nombre, "update", datos)

    def delete(self) -> _Consulta:
        return _Consulta(self.db, self.nombre, "delete")


class MemoryDB:
    """Cliente compatible con la interfaz de Supabase, sin base de datos."""

    def __init__(self, archivo: Path | None = ARCHIVO):
        self.tablas: dict[str, list[dict]] = {}
        self.archivo = archivo
        self.cargar()

    # ── Persistencia local ──
    def cargar(self) -> None:
        if self.archivo and self.archivo.exists():
            try:
                self.tablas = json.loads(self.archivo.read_text(encoding="utf-8"))
                total = sum(len(v) for v in self.tablas.values())
                logger.info("Modo demostración: %d filas recuperadas de %s",
                            total, self.archivo.name)
            except Exception as exc:
                logger.warning("No se pudo leer %s: %s", self.archivo, exc)
                self.tablas = {}

    def guardar(self) -> None:
        if not self.archivo:
            return
        try:
            self.archivo.write_text(
                json.dumps(self.tablas, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("No se pudo escribir %s: %s", self.archivo, exc)

    def table(self, nombre: str) -> _Tabla:
        return _Tabla(self, nombre)

    def filas(self, nombre: str) -> list[dict]:
        return self.tablas.setdefault(nombre, [])

    # ── Emulación del trigger de historial ──
    def archivar_si_cambia(self, fila: dict, cambios: dict) -> None:
        if "valor" not in cambios and "valor_json" not in cambios:
            return
        if (cambios.get("valor", fila.get("valor")) == fila.get("valor")
                and cambios.get("valor_json", fila.get("valor_json")) == fila.get("valor_json")):
            return

        hist = self.filas("epm_respuestas_historial")
        version = max(
            [h["version_num"] for h in hist if h.get("respuesta_id") == fila.get("id")],
            default=0,
        ) + 1
        hist.append({
            "id": str(uuid.uuid4()),
            "respuesta_id": fila.get("id"),
            "version_num": version,
            "session_id": fila.get("session_id"),
            "user_id": fila.get("user_id"),
            "tree_version": fila.get("tree_version"),
            "node_id": fila.get("node_id"),
            "field_key": fila.get("field_key"),
            "valor": fila.get("valor"),
            "valor_json": fila.get("valor_json"),
            "es_valida": fila.get("es_valida"),
            "stale": fila.get("stale"),
            "intentos": fila.get("intentos"),
            "origen": fila.get("origen"),
            "answered_at": fila.get("answered_at"),
            "archivado_at": _ahora(),
        })

    # ── Vistas calculadas al vuelo ──
    def calcular_vista(self, nombre: str) -> list[dict]:
        from app.domain import fields as F

        if nombre == "v_actividades_export":
            salida = []
            for a in self.filas("epm_actividades"):
                fila = {"session_id": a.get("session_id"), "user_id": a.get("user_id")}
                for k in F.FIELD_KEYS:
                    v = a.get(k)
                    fila[k] = "" if v is None else str(v)
                if a.get("instrumento_evaluativo") == "Observación directa" and a.get(
                    "participantes_evaluados"
                ) is not None:
                    fila["participantes_evaluados"] += " (estimado)"
                fila["sheets_row"] = a.get("sheets_row")
                fila["created_at"] = a.get("created_at")
                fila["updated_at"] = a.get("updated_at")
                salida.append(fila)
            return salida

        if nombre == "v_actividades_completas":
            usuarios = {u["id"]: u for u in self.filas("epm_users")}
            vigentes: dict[str, dict[str, Any]] = {}
            for r in self.filas("epm_respuestas"):
                if not r.get("field_key") or r.get("stale") or not r.get("es_valida", True):
                    continue
                vigentes.setdefault(r["session_id"], {})[r["field_key"]] = r.get("valor")

            salida = []
            for s in self.filas("epm_sessions"):
                campos = vigentes.get(s["session_id"], {})
                u = usuarios.get(s.get("user_id"), {})
                fila = {
                    "session_id": s["session_id"],
                    "user_id": s.get("user_id"),
                    "facilitador": u.get("nombre"),
                    "facilitador_email": u.get("email"),
                    "facilitador_programa": u.get("programa"),
                    "estado": s.get("estado"),
                    "tree_version": s.get("tree_version"),
                    "current_node_id": s.get("current_node_id"),
                    "created_at": s.get("created_at"),
                    "completed_at": s.get("completed_at"),
                }
                for k in F.FIELD_KEYS:
                    fila[k] = campos.get(k)
                fila["campos_diligenciados"] = len(campos)
                fila["porcentaje_avance"] = round(len(campos) * 100 / 25, 1)
                salida.append(fila)
            return salida

        if nombre == "v_avance_por_usuario":
            sesiones = self.filas("epm_sessions")
            completas = {c["session_id"]: c for c in self.calcular_vista("v_actividades_completas")}
            salida = []
            for u in self.filas("epm_users"):
                mias = [s for s in sesiones if s.get("user_id") == u["id"]]
                campos = [completas.get(s["session_id"], {}).get("campos_diligenciados", 0)
                          for s in mias]
                salida.append({
                    "user_id": u["id"],
                    "nombre": u.get("nombre"),
                    "email": u.get("email"),
                    "programa": u.get("programa"),
                    "rol": u.get("rol"),
                    "sesiones_iniciadas": len(mias),
                    "sesiones_completadas": sum(1 for s in mias if s.get("estado") == "completada"),
                    "sesiones_planeadas": sum(1 for s in mias if s.get("estado") == "planeada"),
                    "sesiones_en_progreso": sum(1 for s in mias if s.get("estado") == "en_progreso"),
                    "sesiones_abandonadas": sum(1 for s in mias if s.get("estado") == "abandonada"),
                    "campos_promedio": round(sum(campos) / len(campos), 1) if campos else 0,
                    "ultima_sesion": max((s.get("created_at") or "" for s in mias), default=None),
                })
            return salida

        if nombre == "v_campos_problematicos":
            hist = self.filas("epm_respuestas_historial")
            grupos: dict[tuple, list[dict]] = {}
            for r in self.filas("epm_respuestas"):
                if not r.get("field_key"):
                    continue
                grupos.setdefault((r["field_key"], r["node_id"]), []).append(r)

            salida = []
            for (field_key, node_id), filas in grupos.items():
                intentos = [int(f.get("intentos") or 1) for f in filas]
                salida.append({
                    "field_key": field_key,
                    "node_id": node_id,
                    "veces_respondido": len(filas),
                    "intentos_totales": sum(intentos),
                    "intentos_promedio": round(sum(intentos) / len(intentos), 2),
                    "validaciones_fallidas": sum(1 for f in filas if f.get("es_valida") is False),
                    "marcadas_stale": sum(1 for f in filas if f.get("stale")),
                    "correcciones_posteriores": sum(1 for h in hist if h.get("node_id") == node_id),
                })
            salida.sort(key=lambda x: (-x["intentos_totales"], -x["validaciones_fallidas"]))
            return salida

        if nombre == "v_uso_sugerencias":
            grupos: dict[str, list[dict]] = {}
            for r in self.filas("epm_respuestas"):
                if not r.get("field_key") or r.get("stale"):
                    continue
                grupos.setdefault(r["field_key"], []).append(r)

            salida = []
            for field_key, filas in grupos.items():
                asistidas = sum(1 for f in filas if (f.get("origen") or "propio") != "propio")
                salida.append({
                    "field_key": field_key,
                    "respuestas": len(filas),
                    "aceptadas_tal_cual": sum(1 for f in filas if f.get("origen") == "sugerencia_ia"),
                    "aceptadas_y_editadas": sum(1 for f in filas if f.get("origen") == "sugerencia_editada"),
                    "escritas_a_mano": len(filas) - asistidas,
                    "porcentaje_asistido": round(asistidas * 100 / len(filas), 1) if filas else 0,
                })
            salida.sort(key=lambda x: -x["porcentaje_asistido"])
            return salida

        logger.warning("Vista no emulada en modo demostración: %s", nombre)
        return []
