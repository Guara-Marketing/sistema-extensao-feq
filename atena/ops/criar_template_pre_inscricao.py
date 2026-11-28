#!/usr/bin/env python3
"""
Submete à Meta o template feq_pre_inscricao_aprovada (spec 17 §7c): sai sozinho quando o
lead conclui a qualificação da LP. Fica PENDING até a Meta aprovar; enquanto isso o
disparo não envia e deixa um alerta 'pre_inscricao' na caixa de Notificações.

  python3 -m atena.ops.criar_template_pre_inscricao     # sem token: dry-run (mostra o payload)
"""
import sys
import json
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import atena.api.app as A  # carrega o .env com o parser do app (`source .env` trunca valores)
from atena.transporte.whatsapp import (TPL_PRE_INSCRICAO, CORPO_PRE_INSCRICAO,
                                       EXEMPLOS_PRE_INSCRICAO)

if __name__ == "__main__":
    r = A.WA.criar_template(TPL_PRE_INSCRICAO, "UTILITY", CORPO_PRE_INSCRICAO,
                            exemplos=EXEMPLOS_PRE_INSCRICAO)
    print(json.dumps(r, ensure_ascii=False, indent=2))
