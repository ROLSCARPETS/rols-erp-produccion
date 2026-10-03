"""La copia del login común está al día (03-10-2026).

shared/scripts/rols_sso.py es una COPIA de rols-one/shared/kit/rols_sso.py (el
original), que se reparte con rols-one/shared/kit/repartir.py. Si alguien la
cambia aquí, o cambia el original y no la reparte, esta prueba lo dice. Solo
donde está rols-one al lado (en el PC de desarrollo); en el servidor, se salta.

    python tests/test_rols_sso_al_dia.py      (o con pytest)
"""
from __future__ import annotations

import sys
from pathlib import Path

COPIA = Path(__file__).resolve().parent.parent / "shared" / "scripts" / "rols_sso.py"
ORIGINAL = Path(__file__).resolve().parents[2] / "Rols - One" / "shared" / "kit" / "rols_sso.py"


def _texto(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_la_copia_del_login_comun_es_la_de_rols_one():
    if not ORIGINAL.exists():
        return   # sin rols-one al lado (en el servidor): no hay con qué comparar
    assert _texto(COPIA) == _texto(ORIGINAL), (
        "shared/scripts/rols_sso.py no es igual que rols-one/shared/kit/rols_sso.py: "
        "corre `python shared/kit/repartir.py` en rols-one (y no la edites aquí)")


if __name__ == "__main__":
    try:
        test_la_copia_del_login_comun_es_la_de_rols_one()
    except AssertionError as e:
        print("FALLA:", e)
        sys.exit(1)
    print("OK: la copia del login común está al día" if ORIGINAL.exists()
          else "Sin rols-one al lado: no se comprueba")
