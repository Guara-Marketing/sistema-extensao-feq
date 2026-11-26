#!/usr/bin/env python3
"""
Captação antecipada: a janela da Extecamp ainda não abriu, mas a coordenação
autorizou captar no NOSSO site (FEQ-0295, autorizado em 24/08/2026).

Antes existia só "futura", que mandava o lead para a lista de espera — jogando fora
um inscrito que já era possível hoje. É o espelho exato do 'fora_do_prazo' e ganhou,
pelo mesmo motivo, um estado próprio.

O que estes testes protegem:
  1. a janela da EXTECAMP continua verdadeira no grafo (é dela que sai o prazo citado);
  2. o agente NUNCA manda o link da Extecamp antes de ela abrir — link que não aceita
     a inscrição faz o lead concluir que a vaga acabou e sumir;
  3. a LP não manda o lead preencher lá;
  4. a ficha BÁSICA pede só o que a Extecamp vai receber.

Toda checagem fixa `hoje`: o estado depende do calendário e, sem fixar, o arquivo
passaria hoje e falharia sozinho em 01/09 sem nenhum bug — erro já cometido duas
vezes neste projeto (test_promocao.py e test_growth.py).
"""
import re
import sys
import pathlib
import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from atena.ontologia.servico import Ontologia
from atena.core.estado import Estado
from atena.core.orquestrador import brain_deterministico
from atena.growth.db import Growth
from atena.growth import ponte

ONT = Ontologia()
GRW = Growth(":memory:")
ANTES = datetime.date(2026, 8, 24)      # antes de a Extecamp abrir (01/09/2026)
DEPOIS = datetime.date(2026, 9, 15)     # já dentro da janela oficial
ok = 0


def check(c, msg):
    global ok
    assert c, "FALHOU: " + msg
    ok += 1
    print("  ok:", msg)


# ------------------------------------------------------------- 1) estado na ontologia
cap = ONT.captavel("FEQ-0295", ANTES)
check(cap["status"] == "antecipada", f"antes de 01/09 o FEQ-0295 é 'antecipada' (veio {cap['status']})")
check(cap["captavel"] is True, "captável: a LP abre e o agente engaja")
check(cap["antecipada"] is True, "flag própria p/ quem for mandar link da Extecamp")
check(cap["recuperavel"] is False, "não confunde com prazo vencido")

# a janela da Extecamp NÃO foi falsificada para abrir a página
c = ONT.curso("FEQ-0295")
check(cap["inicio"] == "2026-09-01", "início da Extecamp segue verdadeiro no grafo")
check(c["inscricoes_fim"] == "2027-02-01", "prazo citado ao lead continua o oficial")

# depois que a Extecamp abre, vira 'aberta' sozinho — sem ninguém mexer no catálogo
check(ONT.captavel("FEQ-0295", DEPOIS)["status"] == "aberta",
      "a partir de 01/09 o estado vira 'aberta' sem intervenção")

# curso SEM a flag continua exatamente como era
check(ONT.captavel("FEQ-0670", ANTES)["status"] == "aberta"
      and ONT.captavel("FEQ-0670", ANTES).get("antecipada") is False,
      "curso sem a flag não é afetado")


# ------------------------------------------------------------- 2) o agente não manda link morto
def _lead(curso="FEQ-0295"):
    est = Estado(":memory:")
    est.upsert_lead("c1", nome="X", telefone="+5519999990001", curso=curso, fase="Lead",
                    estado_conversa="qualificacao", escolaridade="Superior Completo")
    return est


d = brain_deterministico(ONT, _lead().get_lead("c1"), "me manda o link de inscrição", hoje=ANTES)
msg = d.mensagem_ao_lead or ""
check("ins.extecamp" not in msg, "agente NÃO envia a URL da Extecamp antes de ela abrir")
check("01/09/2026" in msg, "agente diz ao lead QUANDO a Extecamp abre (não deixa no vácuo)")
check("registro" in msg.lower() or "registro" in (d.motivo or "").lower(),
      "agente assume o passo: oferece registrar a inscrição")

# depois de 01/09 o link volta a ser enviado normalmente
d2 = brain_deterministico(ONT, _lead().get_lead("c1"), "me manda o link de inscrição", hoje=DEPOIS)
check("ins.extecamp" in (d2.mensagem_ao_lead or ""),
      "com a Extecamp aberta, o link volta a ser enviado")

# curso normal segue mandando o link (nada quebrou no caminho de sempre)
d3 = brain_deterministico(ONT, _lead("FEQ-0670").get_lead("c1"), "quero o link", hoje=ANTES)
check("ins.extecamp" in (d3.mensagem_ao_lead or ""), "curso comum continua recebendo o link")


# ------------------------------------------------------------- 3) a LP não mente
lp = ponte.render(GRW, ONT, "FEQ-0295", hoje=ANTES)
check("Preencha o formulário de inscrição no sistema oficial" not in lp,
      "LP não manda o lead preencher na Extecamp (que ainda não aceita esta turma)")
check("aqui mesmo nesta página" in lp, "LP diz que a inscrição começa nela")
check("01/09/2026" in lp, "LP informa quando a Extecamp abre")
check("Entrar na lista de espera" not in lp, "não é mais lista de espera: é inscrição de verdade")

lp_dep = ponte.render(GRW, ONT, "FEQ-0670", hoje=ANTES)
check("formaliza a inscrição no sistema oficial" in lp_dep,
      "curso comum: o consultor formaliza a inscrição na Extecamp (pré-inscrição na LP)")


# ------------------------------------------- 4) etapa 2 = pré-inscrição qualificada
# Desde 26/11/2026 a etapa 2 não pede dado de matrícula (CPF, endereço...): o lead
# confirma requisito, valor, modalidade/datas e boleto, e o consultor formaliza.
DADOS = ("cpf", "nascimento", "doc_numero", "cep", "rua", "sexo", "comprovante_em")
for html_lp, nome in ((lp, "0295"), (lp_dep, "0670")):
    sobrou = [x for x in DADOS if f'name="{x}"' in html_lp]
    check(not sobrou, f"{nome}: etapa 2 não pede dado de matrícula (sobrou: {sobrou})")
    check(html_lp.count("<fieldset data-decl=") == 4, f"{nome}: quatro pontos a confirmar")
    check("de 4 pontos confirmados" in html_lp, f"{nome}: contador bate com os pontos")
    for k in ("decl_requisito", "forma_pagamento", "decl_modalidade", "decl_boleto"):
        check(re.search(rf'name="{k}"[^>]*\srequired', html_lp), f"{nome}: {k} é obrigatório")
check("Tenho ensino médio completo." in lp, "requisito declarado vem da ontologia (0295: médio)")
check("Estou ciente de que o primeiro boleto será emitido em 03/02/2027, logo após o "
      "encerramento das inscrições em 01/02/2027." in lp,
      "0295: data do boleto declarada e fim das inscrições na frase do boleto")
check("logo após o encerramento das inscrições em 01/01/2027." in lp_dep
      and "emitido em" not in lp_dep.split("decl_boleto")[1][:400],
      "0670 sem data de boleto declarada: a frase não inventa o dia (spec 17 §3e)")
check("{{E2_" not in lp and "{{E2_" not in lp_dep, "nenhum token da etapa 2 vazou para o HTML")
check("Concluir pré-inscrição" in lp and "Fale com um consultor no WhatsApp" in lp,
      "botão nomeia a ação e há saída humana para quem não se encaixa")

print(f"\n{ok} checks OK — captação antecipada")
