#!/usr/bin/env python3
"""
Revisão de segurança (11/2026): as três falhas mais graves da Central.

1. Webhook da Meta/WhatsApp sem META_APP_SECRET aceitava qualquer mensagem.
2. A etapa 2 da LP trocava a ficha (inclusive o CPF) de um lead sabendo só o
   telefone, e o robô inscrevia com esses dados.
3. Qualquer operador ligava o envio sem aprovação humana.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.pop("ATENA_USERS", None)
os.environ["WHATSAPP_TOKEN"] = ""
os.environ["WHATSAPP_WABA_ID"] = ""
os.environ["ATENA_DEV"] = "1"

import atena.core.estado as _E
_E.DEFAULT_DB = tempfile.mktemp(suffix=".db")
import atena.api.app as A
from atena.core import guardrails as G

FICHA = {"cpf": "123.456.789-00", "nascimento": "1990-01-01",
         "escolaridade": "Superior Completo", "forma_pagamento": "19 PARCELA(S)"}


def _cliente(papel):
    c = A.app.test_client()
    with c.session_transaction() as s:
        s["usuario"], s["papel"] = "tester", papel
    return c


# -- 1. webhook sem segredo --------------------------------------------------------

def test_assinatura_sem_segredo_recusa_por_padrao(monkeypatch):
    monkeypatch.delenv("ATENA_WEBHOOK_SEM_ASSINATURA", raising=False)
    assert not G.verificar_assinatura(None, b"{}", None)
    assert not G.verificar_assinatura("", b"{}", "sha256=qualquer")


def test_assinatura_sem_segredo_so_passa_com_flag_de_dev(monkeypatch):
    monkeypatch.setenv("ATENA_WEBHOOK_SEM_ASSINATURA", "1")
    assert G.verificar_assinatura(None, b"{}", None)


def test_webhook_whatsapp_sem_segredo_responde_403(monkeypatch):
    monkeypatch.delenv("META_APP_SECRET", raising=False)
    monkeypatch.delenv("ATENA_WEBHOOK_SEM_ASSINATURA", raising=False)
    r = A.app.test_client().post("/webhook/whatsapp", json={"entry": []})
    assert r.status_code == 403
    r = A.app.test_client().post("/webhook/meta", json={"entry": []})
    assert r.status_code == 403


# -- 2. ficha da etapa 2 vinculada à etapa 1 ------------------------------------------

def _etapa1(c, tel, ev):
    r = c.post("/webhook/ponte", json={"nome": "Lead Real", "whatsapp": tel,
                                       "curso": "FEQ-0480", "event_id": ev})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_etapa1_devolve_token_e_etapa2_com_token_segue_normal(monkeypatch):
    monkeypatch.setenv("INSCRICAO_AUTO", "1")
    robo = []
    monkeypatch.setattr(A, "_inscrever_extecamp", lambda cid, valer: robo.append(cid))
    c = A.app.test_client()
    d = _etapa1(c, "19997771001", "ev-seg-1")
    assert d.get("ficha_token")
    r = c.post("/webhook/inscricao", json={"whatsapp": "19997771001", "curso_id": "FEQ-0480",
                                           "event_id": "ev-seg-1", "ficha_token": d["ficha_token"],
                                           **FICHA})
    assert r.status_code == 200, r.get_json()
    import time
    time.sleep(0.2)
    assert robo == [d["card_id"]]
    assert not (A.GRW.get_inscricao(d["card_id"]).get("robo_obs") or "").startswith("CONFERIR")


def test_etapa2_sem_token_vai_para_conferencia_e_nao_para_o_robo(monkeypatch):
    monkeypatch.setenv("INSCRICAO_AUTO", "1")
    robo = []
    monkeypatch.setattr(A, "_inscrever_extecamp", lambda cid, valer: robo.append(cid))
    c = A.app.test_client()
    d = _etapa1(c, "19997771002", "ev-seg-2")
    # outra pessoa, que só sabe o telefone, manda uma ficha com outro CPF
    r = c.post("/webhook/inscricao", json={"whatsapp": "19997771002", "curso_id": "FEQ-0480",
                                           "event_id": "ev-seg-x", **{**FICHA, "cpf": "999.999.999-99"}})
    assert r.status_code == 200   # a ficha não se perde (LP antiga também cai aqui)
    import time
    time.sleep(0.2)
    assert robo == []
    assert A.GRW.get_inscricao(d["card_id"])["robo_obs"].startswith("CONFERIR")
    alertas = [a["texto"] for a in A.EST.alertas() if a.get("card_id") == d["card_id"]] \
        if hasattr(A.EST, "alertas") else None
    if alertas is not None:
        assert any("sem vínculo" in t for t in alertas)


def test_token_de_outro_lead_nao_vale(monkeypatch):
    c = A.app.test_client()
    d1 = _etapa1(c, "19997771003", "ev-seg-3")
    d2 = _etapa1(c, "19997771004", "ev-seg-4")
    assert A._ficha_token_ok(d1["ficha_token"], d1["card_id"], "FEQ-0480")
    assert not A._ficha_token_ok(d1["ficha_token"], d2["card_id"], "FEQ-0480")
    assert not A._ficha_token_ok(d1["ficha_token"], d1["card_id"], "FEQ-0499")
    assert not A._ficha_token_ok("lixo", d1["card_id"], "FEQ-0480")
    vencido = A._ficha_token(d1["card_id"], "FEQ-0480", exp=1)
    assert not A._ficha_token_ok(vencido, d1["card_id"], "FEQ-0480")


# -- 3. envio sem aprovação só por supervisor -------------------------------------------

def test_operador_nao_liga_envio_sem_aprovacao():
    antes = A.CFG["auto_aprovar"]
    r = _cliente("operador").post("/api/config", json={"auto_aprovar": not antes})
    assert r.status_code == 403
    assert A.CFG["auto_aprovar"] == antes


def test_supervisor_liga_e_desliga_envio_sem_aprovacao():
    c = _cliente("supervisor")
    assert c.post("/api/config", json={"auto_aprovar": True}).status_code == 200
    assert A.CFG["auto_aprovar"] is True
    assert c.post("/api/config", json={"auto_aprovar": False}).status_code == 200
    assert A.CFG["auto_aprovar"] is False
