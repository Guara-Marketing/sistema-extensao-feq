#!/usr/bin/env python3
"""
Promoções de campanha — FEQ-0480 (valor promocional, 26/11/2026 a 03/01/2027) e
FEQ-0331 (agosto/2026, já encerrada; os dados seguem no catálogo).

O risco aqui é dinheiro dito errado a lead real. Os testes travam:
  1. a aritmética anunciada (o 15% à vista é sobre a TABELA, não sobre o promocional);
  2. o Revisor aceita o preço promocional e barra valor inventado ou de campanha morta;
  3. a promoção MORRE sozinha no fim da janela — não fica anunciada para sempre;
  4. o template de WhatsApp com preço antigo nunca volta a ser usado.
"""
import sys
import pathlib
import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from atena.ontologia.servico import Ontologia
from atena.revisor.ontologico import revisar_estrutural
from atena.growth.funil import valor_curso
from atena.growth.ponte import _investimento_itens
from atena.agentes.cerebro import _bloco_promo

# Campanhas morrem sozinhas no fim da janela (por design). Sem fixar "hoje", este
# arquivo vira teste de calendário: passa dentro da janela e quebra sozinho depois
# (aconteceu em 16/08 e 24/08/2026). HOJE_REF cai dentro da campanha do 0480;
# a do 0331 (agosto) é conferida com o próprio dia dela.
HOJE_REF = datetime.date(2026, 12, 1)
HOJE_0331 = datetime.date(2026, 8, 10)


class _OntFixaHoje(Ontologia):
    def __init__(self, hoje):
        super().__init__()
        self._hoje = hoje

    def promocao(self, codigo, hoje=None):
        return super().promocao(codigo, hoje or self._hoje)


ONT = _OntFixaHoje(HOJE_REF)
ONT_AGO = _OntFixaHoje(HOJE_0331)
ok = 0


def check(c, msg):
    global ok
    assert c, "FALHOU: " + msg
    ok += 1
    print("  ok:", msg)


# ------------------------------------------------------- 1) aritmética anunciada
TABELA = {"FEQ-0480": (19, 866.09, 16455.75), "FEQ-0331": (5, 1163.19, 5815.95)}

pr = ONT.promocao("FEQ-0480")
check(pr and len(pr["ofertas"]) == 2, "FEQ-0480 tem parcelado promocional + à vista")
a, b = pr["ofertas"]
check((a["n"], a["valor_parcela"], a["a_vista"]) == (19, "799.90", None),
      "oferta principal: 19x de R$ 799,90 (só parcelado)")
check((b["n"], b["a_vista"], b["desconto_pct"]) == (None, "13987.39", 15),
      "à vista: R$ 13.987,39 (15%)")
check(abs(float(b["a_vista"]) - TABELA["FEQ-0480"][2] * 0.85) < 0.01,
      "à vista = 15% off da TABELA (não do promocional)")
check(pr["ciclo_h"] == 48, "LP conta em ciclos de 48h")
check(pr["fim"] == ONT.curso("FEQ-0480")["inscricoes_fim"],
      "vale até o fim das inscrições (03/01/2027)")

o331 = ONT_AGO.promocao("FEQ-0331")["ofertas"][0]
n3, vp3, av3 = TABELA["FEQ-0331"]
check((o331["n"], o331["valor_parcela"]) == (6, "872.39"), "FEQ-0331 parcela em 6x de R$ 872,39")
check(abs(float(o331["a_vista"]) - av3 * 0.90) < 0.01, "FEQ-0331 à vista = 10% off da tabela")
check(abs(o331["n"] * float(o331["valor_parcela"]) - float(o331["a_vista"])) < 0.11,
      "6 × parcela fecha com o à vista (mesma trava do SHACL)")
check(ONT_AGO.promocao("FEQ-0331")["ciclo_h"] is None, "campanha sem ciclo conta os dias")

check(all(x["condicao"] for x in pr["ofertas"]), "toda oferta declara sua condição")

# ------------------------------------------------------- 2) Revisor
APROVA = [("FEQ-0480", "No valor promocional sai por 19x de R$ 799,90."),
          ("FEQ-0480", "São R$ 15.198,10 no total, em 19x de R$ 799,90."),
          ("FEQ-0480", "À vista fica R$ 13.987,39."),
          ("FEQ-0480", "O valor de tabela é 19x de R$ 866,09.")]
BLOQUEIA = [("FEQ-0480", "Faço por 19x de R$ 650,00."),
            ("FEQ-0480", "Na promoção sai por 19x de R$ 799,00."),     # preço de agosto
            ("FEQ-0480", "Em grupo, a parcela cai para R$ 736,18."),   # oferta de agosto
            ("FEQ-0480", "À vista sai R$ 12.000,00."),
            ("FEQ-0480", "Com mais 10% de ex-aluno, a parcela vai a R$ 719,91."),
            ("FEQ-1000", "Tem promoção: 19x de R$ 799,90.")]
for cod, txt in APROVA:
    check(revisar_estrutural(cod, txt, ONT)["aprovado"], f"Revisor aprova: {txt}")
for cod, txt in BLOQUEIA:
    check(not revisar_estrutural(cod, txt, ONT)["aprovado"], f"Revisor bloqueia: {txt}")

# ------------------------------------------------------- 3) a promoção expira sozinha
fim = datetime.date.fromisoformat(pr["fim"])
check(ONT.promocao("FEQ-0480", fim) is not None, "no último dia ainda vale")
check(ONT.promocao("FEQ-0480", fim + datetime.timedelta(days=1)) is None,
      "no dia seguinte a promoção some da ontologia")
check(ONT.promocao("FEQ-0480", datetime.date(2026, 11, 25)) is None,
      "antes de começar também não existe")
check(ONT.promocao("FEQ-1000") is None, "curso sem campanha não ganha promoção")
check(ONT.promocao("FEQ-0331") is None, "campanha de agosto do 0331 já morreu")
check(ONT_AGO.promocao("FEQ-0331")["fim"] <= ONT.curso("FEQ-0331")["inscricoes_fim"],
      "FEQ-0331: promoção termina junto ou antes do fim das inscrições")

# ------------------------------------------------------- 4) o que o lead vê
html = _investimento_itens(ONT.curso("FEQ-0480"))
check("799,90" in html and "13.987,39" in html, "LP mostra as duas ofertas")
check("866,09" in html and 'class="risco' in html, "LP mostra a tabela riscada como referência")
check("03/01/2027" in html, "LP mostra o prazo REAL da promoção (não só o relógio)")
sem = _investimento_itens(ONT.curso("FEQ-0670"))
check("line-through" not in sem and "risco" not in sem, "curso sem promoção mantém a LP como era")

b0480 = _bloco_promo(ONT.curso("FEQ-0480"))
check("R$ 799,90" in b0480 and "R$ 13.987,39" in b0480, "prompt do cérebro traz os valores")
check("nunca recalcule" in b0480 and "não some a campanha com outros descontos" in b0480.lower(),
      "prompt proíbe recalcular e acumular desconto")
check("grupo" not in b0480.lower(), "prompt não sugere condição de grupo que não existe mais")
check(_bloco_promo(ONT.curso("FEQ-1000")) == "", "sem promoção, sem bloco no prompt")

# ------------------------------------------------------- 5) valor de conversão
check(abs(valor_curso(ONT.curso("FEQ-0480")) - 13987.39) < 0.01,
      "Purchase usa o valor promocional (não infla o ROAS com o preço de tabela)")
check(abs(valor_curso(ONT.curso("FEQ-0670")) - 1798.18) < 0.01,
      "curso sem promoção continua no valor de tabela")

# ------------------------------------------------------- 6) templates de campanha
from atena.transporte.whatsapp import (CORPOS_PROMO, TEMPLATES_ROL, validar_template,
                                       template_promocional, montar_params)
from atena.transporte import reenvio as R

for nome, corpo in CORPOS_PROMO.items():
    check(validar_template(nome, "MARKETING", corpo, ["Ana", "03/01/2027"]) is None,
          f"{nome}: corpo passa nas regras da Meta antes de submeter")
corpo = CORPOS_PROMO["feq_promo_0480_v2"]
check("799,90" in corpo and "13.987,39" in corpo and "866,09" in corpo,
      "template do 0480 traz os valores da ontologia")
check("799,00" not in corpo and "736,18" not in corpo and "grupo" not in corpo,
      "nenhum valor/condição da campanha de agosto sobrou no corpo")
check("872,39" in CORPOS_PROMO["feq_promo_0331"] and "5.234,36" in CORPOS_PROMO["feq_promo_0331"],
      "template do 0331 traz os valores certos")
check("feq_promo_0480" not in CORPOS_PROMO and
      "feq_promo_0480" not in {t["nome"] for t in TEMPLATES_ROL},
      "template com preço de agosto não pode mais ser escolhido nem na Central")

check(template_promocional("FEQ-0480", ONT) == "feq_promo_0480_v2", "curso em campanha tem template")
check(template_promocional("FEQ-1000", ONT) is None, "curso sem campanha não tem")


class _OntSemPromo:
    def promocao(self, curso, hoje=None):
        return None

    def curso(self, c):
        return ONT.curso(c)


check(template_promocional("FEQ-0480", _OntSemPromo()) is None,
      "campanha encerrada trava o template (não anuncia preço morto)")


class _WA:
    def __init__(self, st):
        self._st = st

    def templates_status(self, forcar=False):
        return self._st


# o caso que motivou a v2: a antiga está APROVADA na Meta, a nova ainda não existe lá
check(template_promocional("FEQ-0480", ONT, _WA({"feq_promo_0480": "APPROVED"})) is None,
      "template antigo aprovado NÃO volta a ser usado com a campanha nova")
check(template_promocional("FEQ-0480", ONT, _WA({"feq_promo_0480_v2": "PENDING"})) is None,
      "template ainda em revisão na Meta não é usado (não queima tentativa)")
check(template_promocional("FEQ-0480", ONT, _WA({"feq_promo_0480_v2": "APPROVED"})) == "feq_promo_0480_v2",
      "aprovado na Meta, passa a ser usado")
check(template_promocional("FEQ-0480", ONT, _WA(None)) == "feq_promo_0480_v2",
      "sem conseguir consultar a Meta (dev/dry-run), não bloqueia")

check(montar_params("feq_promo_0480_v2", {"nome": "Ana", "curso": "FEQ-0480"}, ONT)
      == ["Ana", "03/01/2027"], "params do template de campanha: nome + prazo")

env = [{"texto": "[template feq_lead] x", "status": "falhou", "destino": "5519996027820",
        "erro_codigo": 131049, "ts": (datetime.datetime.now() - datetime.timedelta(hours=30)).isoformat()}]
p = R.plano({"card_id": "x", "telefone": "5519996027820", "curso": "FEQ-0480"}, env,
            promo_tpl="feq_promo_0480_v2")
check(p["template"] == "feq_promo_0480_v2", "retentativa por pacing usa o template da campanha")
p2 = R.plano({"card_id": "x", "telefone": "5519996027820", "curso": "FEQ-0480"}, env, promo_tpl=None)
check(p2["template"] != "feq_promo_0480_v2", "sem campanha vigente, volta aos templates genéricos")

# ------------------------------------------------------- 7) a LP como página de venda
from atena.growth import ponte as P
from atena.growth.db import Growth

c0480, c0670 = ONT.curso("FEQ-0480"), ONT.curso("FEQ-0670")

barra = P._barra_promo(c0480, True)
check("barra-promo" in barra and "R$ 799,90" in barra, "tarja fixa anuncia o valor promocional")
check('data-contagem data-inicio="2026-11-26" data-ciclo-h="48" data-fim="2027-01-03"' in barra,
      "tarja leva o relógio cíclico de 48h ancorado no início, limitado ao fim real")
check("data-prazo-dias" not in barra, "relógio cíclico substitui a contagem em dias")
check("termina em 03/01" in barra, "sem JS, sobra o prazo real")
check(P._barra_promo(c0670, True) == "", "curso sem campanha não ganha tarja")
check(P._barra_promo(c0480, False) == "", "sem inscrição aberta não há tarja (nada a vender)")
c0331_ago = ONT_AGO.curso("FEQ-0331")
check("data-prazo-dias" in P._barra_promo(c0331_ago, True),
      "campanha sem ciclo mantém a contagem em dias")

hp = P._hero_preco(c0480, True)
check("R$ 799,90" in hp and "866,09" in hp, "preço e ancoragem ficam na primeira dobra")
check("2.468,36" in hp, "economia calculada sobre a melhor oferta (à vista)")
check(P._hero_preco(c0480, False) == "", "curso fechado não exibe preço no topo")

selos = P._hero_selos(c0480)
check("368h" in selos and "Certificado Unicamp" in selos and "60 alunos" in selos,
      "selos de confiança saem da ontologia (nada inventado)")

check("Onde nossos alunos atuam" in P._secao_empresas(c0480)
      and 'class="logo-empresa"' in P._secao_empresas(c0480),
      "prova social fica logo abaixo da dobra, com os logos oficiais")
check(P._secao_empresas(None) == "", "sem empresas, a faixa some")

idst = P._invest_destaque(c0480, True)
check("economiza" in idst and "2.468,36" in idst and "data-contagem" in idst,
      "bloco de fechamento repete a economia e o relógio")
check(P._invest_destaque(c0670, True) == "",
      "curso sem campanha não recebe urgência artificial")

lp = P.render(Growth(":memory:"), ONT, "FEQ-0480")
for frag in ("barra-promo", "hero-preco", "hero-selos", "empresas-grid", "invest-destaque",
             "Tirar dúvidas no WhatsApp", "data-contagem"):
    check(frag in lp, f"LP renderizada contém {frag}")
check("{{" not in lp, "nenhum placeholder ficou sem substituição")
lp0670 = P.render(Growth(":memory:"), ONT, "FEQ-0670")
check('<div class="barra-promo"' not in lp0670
      and '<div class="invest-destaque"' not in lp0670,
      "LP de curso sem campanha não recebe a marcação da campanha")

# ------------------------------------------------------- 8) o preço que o agente ANUNCIA
from atena.agentes.cerebro import _bloco_descontos

d_promo = _bloco_descontos({"curso": ONT.curso("FEQ-0480")})
d_sem = _bloco_descontos({"curso": ONT.curso("FEQ-0670")})
check("CHEIO" not in d_promo, "curso EM CAMPANHA nunca recebe a ordem de dizer o valor cheio")
check("CHEIO" in d_sem, "curso sem campanha mantém a regra do valor cheio (correta lá)")
check("promocional" in d_promo, "curso em campanha é instruído a anunciar o preço promocional")
check("prevalece sobre qualquer outra instrução" in b0480,
      "a regra de preço da campanha se declara vencedora de conflitos no prompt")
check("NUNCA abra a resposta pelo valor de tabela" in b0480, "proíbe abrir pelo preço cheio")
check(pr.get("como_aplicar") and "boletos" in pr["como_aplicar"],
      "ontologia registra COMO o desconto chega ao aluno")
check("formulário" in b0480 and "boletos" in b0480,
      "agente sabe explicar por que o formulário da Extecamp mostra o valor cheio")

# ------------------------------------------------------- 9) a ficha de inscrição (nossa)
ops = P._opcoes_pagamento(c0480)
check("19 PARCELA(S) DE R$ 799,90" in ops and "01 PARCELA(S) DE R$ 13.987,39 À VISTA" in ops,
      "ficha oferece o parcelado promocional e o à vista com desconto")
check("866,09" not in ops and "16.455,75" not in ops,
      "opções de tabela cobertas pela campanha saem (à vista não parece mais caro)")
check(ops.count("Valor promocional") == 2, "cada opção da campanha leva o nome dela")
ops670 = P._opcoes_pagamento(c0670)
check("PARCELA(S)" in ops670 and "À VISTA" in ops670, "curso sem campanha mantém as opções de tabela")

from atena.coleta.inscricao import _parcelas
check(_parcelas("19 PARCELA(S) DE R$ 799,90 ATRAVÉS DE BOLETO BANCÁRIO — Valor promocional") == 19,
      "robô casa a opção promocional com a de 19 parcelas da Extecamp")

print(f"\n{ok}/{ok} passaram.")
