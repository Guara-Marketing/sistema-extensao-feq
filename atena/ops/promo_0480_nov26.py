#!/usr/bin/env python3
"""Valor promocional do FEQ-0480 (26/11/2026, pedido do Vitor): 19x de R$ 799,90 no
lugar de 19x de R$ 866,09, até o fim das inscrições, com contagem regressiva de 48h na LP.

Roda igual na semente local e no VPS, para as duas ontologias receberem a MESMA edição:
    python3 atena/ops/promo_0480_nov26.py              # mostra o diff, não grava
    python3 atena/ops/promo_0480_nov26.py --aplicar    # grava via Versionamento (rollback ok)
Depois de aplicar no VPS: `sudo systemctl restart atena` (o app relê a ontologia no boot).
"""
import sys
import json
import difflib
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from atena.ontologia.versionamento import Versionamento

CTX = {"contagemCicloHoras": {"@id": "feq:contagemCicloHoras", "@type": "xsd:integer"}}

PROMO = {
    "@type": "feq:Promocao",
    "rotulo": "Valor promocional",
    "janela": {"@type": "feq:JanelaTemporal", "inicio": "2026-11-26", "fim": "2027-01-03"},
    # contagem da LP: zera a cada 48h e recomeça; no último ciclo para no fim real
    "contagemCicloHoras": 48,
    "ofertas": [
        {"@type": "feq:Oferta", "rotulo": "Parcelado no boleto",
         "condicao": "pagamento em 19 parcelas no boleto, para inscrições feitas dentro do prazo",
         "numParcelas": 19, "valorParcela": "799.90"},
        # já existia (campo `descontos`: 15% à vista sobre a tabela). Entra como oferta
        # para o formulário não mostrar R$ 16.455,75 à vista ao lado de 19x de 799,90 —
        # o à vista pareceria MAIS caro que o parcelado.
        {"@type": "feq:Oferta", "rotulo": "À vista no boleto",
         "condicao": "pagamento à vista em boleto (os 15% à vista do curso, sobre o valor de tabela)",
         "percentualDesconto": 15, "aVista": "13987.39"},
    ],
    "comoAplicar": ("O formulário de inscrição da Extecamp mostra o valor CHEIO — o valor "
                    "promocional não aparece lá. Ele é aplicado depois, direto nos boletos das "
                    "mensalidades: conclua a inscrição normalmente e nos avise aqui pelo "
                    "WhatsApp, que o valor promocional entra no termo de compromisso."),
}


def patch(texto):
    d = json.loads(texto)
    d["@context"].update(CTX)
    curso = next(c for c in d["@graph"] if c.get("@id") == "feq:FEQ-0480")
    curso["promocao"] = PROMO
    return json.dumps(d, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    v = Versionamento()
    antes = v.catalogo.read_text(encoding="utf-8")
    depois = patch(antes)
    sys.stdout.writelines(difflib.unified_diff(
        json.dumps(json.loads(antes), ensure_ascii=False, indent=2).splitlines(True),
        depois.splitlines(True), "antes", "depois", n=1))
    if "--aplicar" in sys.argv:
        print(v.aplicar(depois, "vitor", "FEQ-0480: valor promocional 19x R$ 799,90 até o fim das inscrições"))
