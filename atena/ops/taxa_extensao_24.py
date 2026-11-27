#!/usr/bin/env python3
"""Taxa de inscrição de R$ 24,00 para todo curso FEQ de extensão e difusão
(27/11/2026, pedido do Vitor). Formação de especialistas continua em R$ 69,00.

Roda igual na semente local e no VPS, para as duas ontologias receberem a MESMA edição:
    python3 atena/ops/taxa_extensao_24.py              # mostra o diff, não grava
    python3 atena/ops/taxa_extensao_24.py --aplicar    # grava via Versionamento (rollback ok)
Depois de aplicar no VPS: `sudo systemctl restart atena` (o app relê a ontologia no boot).
"""
import sys
import json
import difflib
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from atena.ontologia.versionamento import Versionamento

TAXA = "24.00"
TIPOS = {"feq:Extensao", "feq:Difusao"}


def patch(texto):
    d = json.loads(texto)
    for c in d["@graph"]:
        # ponytail: só FEQ — ECO-1100 é do Instituto de Economia, a taxa dele não é regra da FEQ
        if c.get("@type") in TIPOS and c.get("@id", "").startswith("feq:FEQ-") and c.get("planoPagamento"):
            c["planoPagamento"]["taxaInscricao"] = TAXA
    return json.dumps(d, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    v = Versionamento()
    antes = v.catalogo.read_text(encoding="utf-8")
    depois = patch(antes)
    sys.stdout.writelines(difflib.unified_diff(
        json.dumps(json.loads(antes), ensure_ascii=False, indent=2).splitlines(True),
        depois.splitlines(True), "antes", "depois", n=1))
    if "--aplicar" in sys.argv:
        print(v.aplicar(depois, "vitor", "taxa de inscrição R$ 24,00 em extensão e difusão FEQ"))
