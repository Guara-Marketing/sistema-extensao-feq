#!/usr/bin/env python3
"""
Pré-inscrição aprovada (spec 17 §7c): quem conclui a qualificação da LP vai para a fase
Pré-Inscrito e recebe SOZINHO o template com o link do formulário completo.

O risco aqui é mandar texto falso ou ilegível: link que não existe, prazo errado,
mensagem num bloco só. Os testes protegem a forma do template, o fail-closed por curso
e o disparo (só com template aprovado, nunca para opt-out).
"""
import os
import sys
import json
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.pop("ATENA_USERS", None)
os.environ["WHATSAPP_TOKEN"] = ""        # dry-run: nenhum envio real
os.environ["WHATSAPP_WABA_ID"] = ""
os.environ["ATENA_DEV"] = "1"

import atena.core.estado as _E
_E.DEFAULT_DB = tempfile.mktemp(suffix=".db")
import atena.api.app as A
from atena.core.estado import ESTEIRA, alcancou, em_captacao
from atena.core import faro
from atena.growth import ponte
from atena.transporte.whatsapp import (TPL_PRE_INSCRICAO, CORPO_PRE_INSCRICAO,
                                       EXEMPLOS_PRE_INSCRICAO, LIMITE_TEXTO_TEMPLATE,
                                       preencher_template, validar_template)

ONT = A.ONTO.ont


def _cliente():
    c = A.app.test_client()
    c.post("/api/login", json={"usuario": "operador", "senha": "operador"})
    return c


def test_fase_entre_prospect_e_inscrito():
    assert ESTEIRA.index("Prospect") < ESTEIRA.index("Pré-Inscrito") < ESTEIRA.index("Inscrito")
    assert alcancou("Pré-Inscrito", "Prospect") and not alcancou("Pré-Inscrito", "Inscrito")
    # ainda em captação (curador/ontologista continuam olhando), Inscrito já não
    assert em_captacao("Pré-Inscrito") and not em_captacao("Inscrito")
    # o FARO não tem o degrau: espelha como Prospect
    assert faro.STAGES["Pré-Inscrito"] == faro.STAGES["Prospect"]


def test_template_legivel_e_aceito_pela_meta():
    assert validar_template(TPL_PRE_INSCRICAO, "UTILITY", CORPO_PRE_INSCRICAO,
                            EXEMPLOS_PRE_INSCRICAO) is None
    # a queixa era "texto corrido": o corpo fixo tem parágrafos, e nenhuma variável quebra linha
    assert CORPO_PRE_INSCRICAO.count("\n\n") >= 5
    assert all("\n" not in e and "    " not in e for e in EXEMPLOS_PRE_INSCRICAO)
    assert CORPO_PRE_INSCRICAO.rstrip().endswith(
        "_Mensagem enviada pela equipe da Secretaria de Extensão da FEQ Unicamp - extfeq@unicamp.br_")
    assert len(preencher_template(CORPO_PRE_INSCRICAO, EXEMPLOS_PRE_INSCRICAO)) <= LIMITE_TEXTO_TEMPLATE


def test_cabe_em_todo_curso_com_link():
    """Para cada curso FEQ com link da Extecamp, a mensagem preenchida passa no limite
    da Meta e não sobra nenhum {{n}} sem valor."""
    lead = {"nome": "maria aparecida da silva"}
    checados = 0
    for cod in ONT.cursos():
        c = ONT.curso(cod)
        params, motivo = ponte.params_pre_inscricao(c, lead, {}, ONT.captavel(cod))
        if params is None:
            continue
        checados += 1
        txt = preencher_template(CORPO_PRE_INSCRICAO, params)
        assert len(txt) <= LIMITE_TEXTO_TEMPLATE, (cod, len(txt))
        assert "{{" not in txt and params[0] == "Maria", cod
        assert all("\n" not in str(p) for p in params), cod
        assert c["url_inscricao"] in txt, cod
    assert checados >= 3, checados


def test_opcao_escolhida_entra_no_texto():
    c = ONT.curso("FEQ-0480")
    ops = ponte._opcoes_pagamento(ponte._plano_exibicao(c))
    vista = next(o for o in ops if "vista" in o[1])
    params, _ = ponte.params_pre_inscricao(c, {"nome": "Ana"}, {"forma_pagamento": vista[0]},
                                           ONT.captavel("FEQ-0480"))
    assert params and vista[1] in params[8] and " ou " not in params[8]


def test_fail_closed():
    lead = {"nome": "Ana"}
    # sem curso, outro instituto, contínuo, antecipado, sem link da Extecamp
    assert ponte.params_pre_inscricao(None, lead)[0] is None
    for cod in ("ECO-1100", "FEQ-1150"):
        try:
            c = ONT.curso(cod)
        except Exception:
            continue
        assert ponte.params_pre_inscricao(c, lead, {}, ONT.captavel(cod))[0] is None, cod
    c = dict(ONT.curso("FEQ-0480"))
    assert ponte.params_pre_inscricao(c, lead, {}, {"antecipada": True})[0] is None
    c["url_inscricao"] = "https://extensao.feq.unicamp.br/inscricao-feq-0480/"
    assert ponte.params_pre_inscricao(c, lead, {}, {})[0] is None
    # sem nome: variável vazia não sai (a Meta recusa parâmetro vazio)
    assert ponte.params_pre_inscricao(ONT.curso("FEQ-0480"), {}, {}, {})[0] is None


def _etapa2(c, tel, ev):
    r = c.post("/webhook/ponte", json={"nome": "Lia Pré", "whatsapp": tel,
                                       "curso": "FEQ-0480", "event_id": ev})
    cid = r.get_json()["card_id"]
    feito = threading.Event()
    orig = A._avisar_pre_inscricao
    resultado = {}

    def espiao(card_id):
        try:
            resultado["r"] = orig(card_id)
        finally:
            feito.set()
    A._avisar_pre_inscricao = espiao
    try:
        r2 = c.post("/webhook/inscricao", json={
            "whatsapp": tel, "curso_id": "FEQ-0480", "event_id": ev,
            "forma_pagamento": "19 PARCELA(S)", "decl_modalidade": "Estou de acordo."})
        assert r2.status_code == 200, r2.get_json()
        assert feito.wait(10), "o disparo não rodou"
    finally:
        A._avisar_pre_inscricao = orig
    return cid, resultado["r"]


def test_webhook_move_e_envia():
    c = _cliente()
    cid, r = _etapa2(c, "19997771001", "ev-pre-1")
    assert A.EST.get_lead(cid)["fase"] == "Pré-Inscrito"
    assert r.get("ok"), r
    msgs = [m for m in A.EST.historico(cid) if m.get("autor") == "template"]
    assert msgs and "Recebemos sua pré-inscrição" in msgs[-1]["texto"]
    assert "Lia" in msgs[-1]["texto"] and "{{" not in msgs[-1]["texto"]


def test_sem_aprovacao_nao_envia_e_alerta():
    c = _cliente()
    orig = A.WA.templates_status
    A.WA.templates_status = lambda forcar=False: {TPL_PRE_INSCRICAO: "PENDING"}
    try:
        cid, r = _etapa2(c, "19997771002", "ev-pre-2")
    finally:
        A.WA.templates_status = orig
    assert not r.get("ok") and "não aprovado" in r["motivo"]
    assert not [m for m in A.EST.historico(cid) if m.get("autor") == "template"]
    alertas = A.EST.conn.execute("SELECT tipo, texto FROM alertas WHERE card_id=?", (cid,)).fetchall()
    assert any(t == "pre_inscricao" for t, _ in alertas), alertas
    assert "pre_inscricao" not in A.ALERTAS_FORA_DA_CAIXA


def test_optout_nao_recebe():
    A.EST.upsert_lead("optx", nome="Opt Out", telefone="+5519997771003",
                      curso="FEQ-0480", fase="Pré-Inscrito")
    A.EST.conn.execute("UPDATE leads SET optout=1 WHERE card_id='optx'")
    r = A._avisar_pre_inscricao("optx")
    assert not r.get("ok") and "não receber" in r["motivo"]


if __name__ == "__main__":
    casos = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    falhas = 0
    for fn in casos:
        try:
            fn(); print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            falhas += 1; print(f"FAIL  {fn.__name__}  {e}")
        except Exception as e:
            falhas += 1; print(f"ERRO  {fn.__name__}  {type(e).__name__}: {e}")
    print(f"\n{len(casos) - falhas}/{len(casos)} passaram.")
    sys.exit(1 if falhas else 0)
