#!/usr/bin/env python3
"""
Atena · Growth — Bridge Page / LP inteligente (specs 16 §2 e 17).
GET /ponte?curso=X renderiza a LP (bridge-template.html + bridge-logic.js,
copy 100% ancorada na ontologia); POST /webhook/ponte cai em processar():
valida, ingere o lead (dedupe por telefone, opt-in LGPD fonte=ponte), registra
inicio_inscricao com o event_id DO NAVEGADOR (desduplicação Pixel×CAPI),
vincula a sessão de telemetria ao lead e devolve a URL do FORMULÁRIO oficial
(/curso/inscricao/). render/fragmento são reusados pelo deploy WordPress.
"""
import os
import re
import sys
import html
import json
import uuid
import base64
import hashlib
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from atena.growth import funil

_WEB = pathlib.Path(__file__).resolve().parents[1] / "web"
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_RAW_TOKENS = {"URL_CURSO", "CURSO", "TURMA", "CONTEUDO_HTML", "INVESTIMENTO_ITENS", "WA_LINK",
               "BARRA_PROMO", "HERO_PRECO", "HERO_SELOS", "HERO_REFORCO", "INVEST_DESTAQUE",
              "FOTO_PROFESSOR_HTML", "PROFESSOR_CREDENCIAL_HTML", "CURSOS_RELACIONADOS_HTML",
              "OUTROS_PROFESSORES_HTML", "SECAO_OBJETIVOS",
              "SECAO_DEPOIMENTOS", "PROFESSORES_BIO_HTML", "GARANTIA_HTML",
              "SALARIO_HTML", "PASSOS_HTML", "FAQ_EXTRA_HTML",
              "PRAZO_LINHA", "SECAO_INSCRICAO", "FAQ_COMO_INSCREVER",
              "PERIODO_OFERECIMENTO"}
WA_NUMERO_DEFAULT = "551931672313"   # WABA da Extensão FEQ (+55 19 3167-2313)
# Texto do requisito POR NÍVEL da ontologia (feq:nivelMinimo). Sem isto a LP dizia
# "ensino superior completo" para todo curso com requisito — falso nos cursos que
# pedem só ensino médio (FEQ-0299, FEQ-0670).
_REQUISITO_TEXTO = {
    # Sem exigência é ARGUMENTO DE VENDA, não ausência de informação — o texto
    # afirma a abertura em vez de deixar a linha vazia e parecer omissão.
    "nenhum": "Não há pré-requisito de escolaridade: o curso é aberto a todos.",
    "medio": "É necessário ensino médio completo.",
    "superiorIncompleto": "É necessário ensino superior em andamento (ou concluído).",
    "superiorCompleto": "É necessário ensino superior completo (graduação concluída em qualquer área).",
    "pos": "É necessária pós-graduação concluída.",
}
# Ativos reais já publicados pela própria FEQ (não fabricamos foto de ninguém):
# logo oficial + hero do site institucional (feq.unicamp.br — laboratório/planta
# de processos, temático; a home de cursos usava um stock genérico) + fotos
# oficiais dos professores, extraídas do diretório de docentes (spec 17).
LOGO_URL_DEFAULT = ("https://cursos-extensao.feq.unicamp.br/wp-content/uploads/"
                    "2021/04/logo-redmencionado-300x70.png")
HERO_BG_URL_DEFAULT = "https://www.feq.unicamp.br/wp-content/uploads/2024/10/Group-103.png"
GTM_ID_DEFAULT = "GTM-WPXLCWJ"   # já instalado no <head> do site (head code do usuário)
# Google Ads da campanha (24/11/2026): conversão "inscrição concluída", disparada pelo
# bridge-logic.js na etapa 2 (ID público, não segredo). O GTM da campanha
# (GTM-PV565RMB) vem do <head> do site inteiro (plugin GTM4WP), não daqui.
GADS_CONVERSAO_DEFAULT = "AW-18565429818/1LKxCNi31bYdELr015RF"
_UPLOADS = "https://cursos-extensao.feq.unicamp.br/wp-content/uploads"

# Logos das empresas onde os alunos formados trabalham — arquivos que a própria FEQ
# já publicava nas páginas antigas dos cursos (mesma regra das fotos de professor:
# só material oficial já publicado, nada fabricado).
EMPRESA_LOGO = {
    "3M": f"{_UPLOADS}/2024/02/3m.png",
    "Boehringer": f"{_UPLOADS}/2024/02/boehringer.png",
    "Braskem": f"{_UPLOADS}/2024/02/braskem-1.png",
    "Buckman": f"{_UPLOADS}/2024/02/buckman.png",
    "EMS": f"{_UPLOADS}/2024/02/ems.png",
    "Eaton": f"{_UPLOADS}/2024/02/eaton.png",
    "Petrobras": f"{_UPLOADS}/2024/02/petrobras.png",
    "Solvay": f"{_UPLOADS}/2024/02/solvay.png",
}

# Modelo do certificado, POR CURSO: o nome e o tipo do curso estão impressos dentro
# da imagem, então não existe arquivo genérico. Os nomes de arquivo NÃO identificam o
# curso (são todos "Modelo-Declaracao-Curso-de-Difusao..."), inclusive nos cursos de
# Formação de Especialistas — o mapa abaixo foi conferido lendo o texto de cada imagem.
# FEQ-0331, FEQ-0499 e FEQ-0580 ainda não têm modelo publicado: a seção sai sem a
# imagem neles (some, não inventa — mesma regra do resto do sistema).
# Foto do currículo (seção "Seu currículo no futuro"): imagem de engenharia que a
# PRÓPRIA FEQ já publica na biblioteca de mídia do site (mesma regra dos logos e das
# fotos de docente — nada de banco de imagem novo, nada gerado). Não representa
# nenhum aluno específico: é o retrato ilustrativo do currículo que o lead monta.
CV_FOTO_URL = (f"{_UPLOADS}/2026/01/"
               "pexels-thisisengineering-3861970-1-scaled-e1768404648529-300x293.jpg")

# Imagem de cada curso nos cards da home. São as MESMAS que a FEQ já usava na grade
# antiga da home (extraídas do backup do Elementor), então cada curso ficou com a
# imagem que a coordenação escolheu para ele. Duas exceções: FEQ-0299 e FEQ-0670
# apontavam para servidores de TERCEIROS (agencia.fapesp.br e ictq.com.br) — hotlink
# que quebra quando o outro site mexe no arquivo; troquei pelas equivalentes da
# própria biblioteca de mídia da FEQ (microscópio eletrônico e modelo molecular).
CURSO_IMAGEM = {
    "FEQ-0360": f"{_UPLOADS}/2024/07/offshore.webp",
    "FEQ-1000": f"{_UPLOADS}/2026/02/engenharia-quimica-ead.jpg",
    "FEQ-0480": f"{_UPLOADS}/2024/05/inteligencia-artificial-1.jpg",
    "FEQ-0499": f"{_UPLOADS}/2024/01/engenharia-de-processos-1.jpg",
    "FEQ-0580": (f"{_UPLOADS}/2025/08/engineer-working-on-chip-development-"
                 "2025-03-06-13-42-24-utc-scaled.jpg"),
    "FEQ-0331": f"{_UPLOADS}/2024/08/risk.png",
    "FEQ-0333": (f"{_UPLOADS}/2026/02/9e740d8e-54c4-469a-b8e5-e7fa8452b5ab_"
                 "Climeworks-direct-air-capture_plant-Orca.webp"),
    "FEQ-0670": (f"{_UPLOADS}/2025/03/scientist-holding-a-molecular-model-"
                 "2022-12-16-22-03-15-utc-678x381-1.jpg"),
    "FEQ-0299": f"{_UPLOADS}/2025/05/microscopio-eletronico-766x1024-1.jpeg",
    # foto real de plataforma offshore — diferente do offshore.webp do FEQ-0360
    # (aquele é um render 3D); tema de petróleo/reservatório bate com o curso.
    "FEQ-0295": f"{_UPLOADS}/2024/07/offshore.jpg",
    # diagrama de blocos de um controlador PID (biblioteca de mídia da FEQ)
    "FEQ-1150": f"{_UPLOADS}/2024/07/controller.jpeg",
}

CERTIFICADO_MODELO = {
    "FEQ-0480": f"{_UPLOADS}/2025/06/Modelo-Declaracao-Curso-de-Difusao-a-Distancia-1.pdf-2.png",
    "FEQ-0360": f"{_UPLOADS}/2025/06/Modelo-Declaracao-Curso-de-Difusao-a-Distancia-1.pdf-1-1.png",
    "FEQ-1000": f"{_UPLOADS}/2025/06/Modelo-Declaracao-Curso-de-Difusao-a-Distancia-1.pdf-2-1.png",
    "FEQ-0299": f"{_UPLOADS}/2026/07/Modelo-Declaracao-Curso-de-Difusao-a-Distancia-1.pdf.png",
    "FEQ-0333": f"{_UPLOADS}/2026/02/Modelo-Declaracao-Curso-de-Difusao-a-Distancia-1.pdf-2.png",
    "FEQ-0670": f"{_UPLOADS}/2026/07/Modelo-Declaracao-Curso-de-Difusao-a-Distancia-1.pdf-1.png",
}

PROFESSOR_FOTOS = {
    # Enviadas pelo usuário (26/08/2026), já hospedadas na biblioteca da própria FEQ.
    "André de Freitas Gonçalves":
        f"{_UPLOADS}/2026/08/andre-de-freitas-goncalves-feq-0670.jpeg",
    "Luiz Guilherme Lomônaco":
        f"{_UPLOADS}/2026/08/luiz-guilherme-lomonaco-feq-0670.png",
    "Flavio Vasconcelos da Silva":
        "https://www.feq.unicamp.br/wp-content/uploads/2025/09/D-Flavio-Vasconcelos-da-Silva-1.jpg",
    "Luis Fernando Mercier Franco":
        "https://www.feq.unicamp.br/wp-content/uploads/2025/09/Luis-Fernando-Mercier-Franco.png",
    "Osvaldir Pereira Taranto":
        "https://www.feq.unicamp.br/wp-content/uploads/2025/09/Osvaldir-Pereira-Taranto33333-300x300.png",
    # Fotos publicadas nas PÁGINAS OFICIAIS preexistentes dos cursos (mesma regra:
    # material já publicado pela FEQ; nunca fabricamos foto de pessoa real):
    "Vitor Machado Viana Cruz":
        "https://cursos-extensao.feq.unicamp.br/wp-content/uploads/2024/07/vitor_machado-e1721925782819.jpg",
    "Guilherme Jose de Castilho":
        "https://cursos-extensao.feq.unicamp.br/wp-content/uploads/2024/07/guilherme-300x300-1.png",
    "Edneu Jatkoski (Petrobras)":
        "https://cursos-extensao.feq.unicamp.br/wp-content/uploads/2024/07/edneu.png",
    "Claudio Vieira Neto":
        "https://cursos-extensao.feq.unicamp.br/wp-content/uploads/2025/04/1681221613629.jpg",
    "Gustavo Doubek":
        "https://cursos-extensao.feq.unicamp.br/wp-content/uploads/2026/02/Gustavo-Doubek.jpg",
    "Douglas Alves Goulart":
        "https://cursos-extensao.feq.unicamp.br/wp-content/uploads/2026/07/douglas-alves-goulart.jpg",
    # Docentes dos cursos incluídos em 21/07/2026 (fotos das páginas oficiais dos
    # cursos; Ronierik veio do diretório institucional feq.unicamp.br/funcionario/).
    "Leonardo Vasconcelos Fregolente":
        "https://cursos-extensao.feq.unicamp.br/wp-content/uploads/2024/01/leonardo.png",
    "Fabio Marcelo Brogna":
        "https://cursos-extensao.feq.unicamp.br/wp-content/uploads/2024/01/fabio-marcelo.jpeg",
    "Angela Hayashi":
        "https://cursos-extensao.feq.unicamp.br/wp-content/uploads/2024/02/image_2024-02-02_172849557-e1706905838346.png",
    "Savio Souza Venancio Vianna":
        "https://cursos-extensao.feq.unicamp.br/wp-content/uploads/2024/08/savio_vianna.jpg",
    "Eduardo Perez":
        "https://cursos-extensao.feq.unicamp.br/wp-content/uploads/2024/11/1c3aae43-bc40-46c1-aa8b-22778addf511.jpg",
    "Ronierik Pioli Vieira":
        "https://www.feq.unicamp.br/wp-content/uploads/2025/09/Ronierik-Pioli-Vieira.png",
}
# Docentes em DESTAQUE por curso (cards com foto), além do responsável — que já tem
# card próprio. FEQ-0480: escolha do usuário (20/07/2026); demais: os nomes que as
# LPs preexistentes destacavam. Douglas não tem foto/bio publicada -> card só com
# nome+link (avatar de iniciais; nunca inventamos foto).
PROFESSOR_DESTAQUE = {
    "FEQ-0480": ["Vitor Machado Viana Cruz", "Douglas Alves Goulart"],
    "FEQ-1000": ["Guilherme Jose de Castilho", "Edneu Jatkoski (Petrobras)",
                 "Flavio Vasconcelos da Silva"],
    "FEQ-0580": ["Claudio Vieira Neto"],
    "FEQ-0333": ["Gustavo Doubek"],
    "FEQ-0360": ["Fabio Marcelo Brogna", "Angela Hayashi"],
    "FEQ-0499": ["Eduardo Perez"],
    "FEQ-0670": ["André de Freitas Gonçalves", "Luiz Guilherme Lomônaco"],
}
# Credencial real (diretório de docentes feq.unicamp.br/funcionario/*): departamento
# oficial + CV Lattes (currículo acadêmico público-padrão no Brasil) — nada de bio
# inventada, só os dois fatos verificáveis que o próprio diretório expõe.
PROFESSOR_CREDENCIAL = {
    "Flavio Vasconcelos da Silva": {
        "departamento": "Departamento de Engenharia de Sistemas Químicos – DESQ",
        "lattes": "http://lattes.cnpq.br/1108208002886617",
    },
    "Luis Fernando Mercier Franco": {
        "departamento": "Departamento de Engenharia de Sistemas Químicos – DESQ",
        "lattes": "http://lattes.cnpq.br/1624206548318855",
    },
    "Osvaldir Pereira Taranto": {
        "departamento": "Departamento de Engenharia de Processos – DEPro",
        "lattes": "http://lattes.cnpq.br/3804707640110777",
    },
}
# Demais professores dos cursos (não-responsáveis): link real encontrado por busca
# (Lattes, LinkedIn ou Google Scholar) quando a identidade pôde ser confirmada com
# confiança; nomes sem entrada aqui aparecem SEM link (nunca adivinhamos Lattes —
# o ID é opaco — nem cravamos um perfil de nome homônimo sem contexto batendo).
PROFESSOR_LINK = {
    "Nikolas Ferreira de Souza": {"tipo": "Portal Docente Unicamp",
        "url": "https://portal.dados.unicamp.br/perfil?origem=&docente=330243&sigla_unidade=&nome_unidade=&nome_programa="},
    "Emerson Parazzi Lyra": {"tipo": "LinkedIn", "url": "https://www.linkedin.com/in/emersonparazzilyra/?locale=pt"},
    "Nathan Barros de Souza": {"tipo": "LinkedIn", "url": "https://www.linkedin.com/in/nathan-b-souza/"},
    "Flavio Vasconcelos da Silva": {"tipo": "Lattes", "url": "http://lattes.cnpq.br/1108208002886617"},
    "Claudio Vieira Neto": {"tipo": "LinkedIn", "url": "https://www.linkedin.com/in/claudio-vieira-neto"},
    "Douglas Alves Goulart": {"tipo": "LinkedIn", "url": "https://www.linkedin.com/in/douglas-alves-goulart/"},
    "Felipe Matheus Mota Sousa": {"tipo": "Google Scholar", "url": "https://scholar.google.com/citations?user=oshtt8oAAAAJ"},
    "Raphael Santana Almeida": {"tipo": "Google Scholar", "url": "https://scholar.google.com/citations?user=rg0xVnAAAAAJ"},
    "Victor Santana Ramos": {"tipo": "Lattes", "url": "http://lattes.cnpq.br/0419561926689242"},
    "Vitor Machado Viana Cruz": {"tipo": "Lattes", "url": "http://lattes.cnpq.br/0049996359988528"},
    "Vitor Augusto Oliveira da Silva": {"tipo": "LinkedIn", "url": "https://www.linkedin.com/in/vitor-aoliveira/"},
    "Dirceu Noriler": {"tipo": "Lattes",
        "url": "https://buscatextual.cnpq.br/buscatextual/visualizacv.do?id=K4762481H3&idiomaExibicao=2"},
    "Eduardo de Britto Perez": {"tipo": "Lattes", "url": "http://lattes.cnpq.br/8235156876575101"},
    "Guilherme Jose de Castilho": {"tipo": "LinkedIn",
        "url": "https://www.linkedin.com/in/guilherme-castilho-3820b81a3/"},
    "Edneu Jatkoski (Petrobras)": {"tipo": "LinkedIn",
        "url": "https://www.linkedin.com/in/edneu-jatkoski-34a3a630/"},
    "João Lameu da Silva Júnior": {"tipo": "Lattes", "url": "http://lattes.cnpq.br/7563505845567082"},
    "Leonardo Vasconcelos Fregolente": {"tipo": "Lattes", "url": "http://lattes.cnpq.br/0146291251418497"},
    "Mariana Conceicao da Costa": {"tipo": "Lattes", "url": "http://lattes.cnpq.br/6460520627911836"},
    "Raphael Soeiro Suppino": {"tipo": "Lattes", "url": "http://lattes.cnpq.br/1437214547688523"},
    # Lattes do Doubek: a página oficial do FEQ-0333 publica 6149769815435543
    # (diverge do 2409386156783785 achado no site do PRH/FEQ) — vale a fonte do curso.
    "Gustavo Doubek": {"tipo": "Lattes", "url": "http://lattes.cnpq.br/6149769815435543"},
    "Sallie Elizabeth Greenberg": {"tipo": "LinkedIn", "url": "https://www.linkedin.com/in/dr-sallie-greenberg-1955388/"},
}
# Bios TRANSCRITAS das páginas oficiais preexistentes da Extensão FEQ (cursos-extensao.
# feq.unicamp.br) — nunca redigidas por nós. Nome sem entrada aqui = sem bio no card.
PROFESSOR_BIO = {
    "Flavio Vasconcelos da Silva": {
        "cargo": "Professor Associado FEQ Unicamp",
        "bio": "Livre-Docente em Controle de Processos pela Unicamp e Professor Associado da "
               "Faculdade de Engenharia Química Unicamp. Atua em Controle de Processos, IA "
               "(Controle Fuzzy e Redes Neurais), Instrumentação Industrial e Refrigeração Industrial."},
    "Vitor Machado Viana Cruz": {
        "cargo": "Doutor em Engenharia Química",
        "bio": "Doutor e Pós-Doutorando pela FEQ Unicamp. Experiência em processos de recuperação "
               "química e especialista em desenvolvimento de softwares para simulação de plantas "
               "químicas com interfaces interativas."},
    "Guilherme Jose de Castilho": {
        "cargo": "Professor Associado FEQ Unicamp",
        "bio": "Pós-doutor em Engenharia Química pela Unicamp e UBC-Canadá, Coordenador da Escola "
               "de Extensão e Professor na FEQ. Especialista em Sistemas Particulados e "
               "Fluidodinâmica, com foco em fluidização, leito fluidizado circulante e "
               "processamento de sinais."},
    "Edneu Jatkoski (Petrobras)": {
        "cargo": "Coordenador de Inspeção — Petrobras (REPLAN)",
        "bio": "Coordenador de Inspeção na Refinaria de Paulínia, com 40 anos de experiência. "
               "Graduado em Engenharia Civil e MBA em Gestão Industrial. Instrutor em cursos de "
               "formação da Petrobras e representante da empresa no CEPETRO (Unicamp)."},
    "Claudio Vieira Neto": {
        "cargo": "Especialista em Data Science",
        "bio": "Engenheiro Químico e Black Belt com experiência em projetos de IA, NLP, otimização "
               "e simulação. Atuou em iniciativas com impacto financeiro e operacional relevante e "
               "liderou times ágeis em grandes empresas."},
    "Leonardo Vasconcelos Fregolente": {
        "cargo": "Professor Associado FEQ Unicamp",
        "bio": "Professor Associado da FEQ Unicamp. Atuou 11 anos como engenheiro de "
               "processamento na Petrobras, em áreas técnicas e de gestão operacional, e "
               "coordena pesquisas em parceria com a indústria."},
    "Fabio Marcelo Brogna": {
        "cargo": "Engenheiro de Processamento Sênior — Petrobras",
        "bio": "Especialista em confiabilidade, análise de causa básica, riscos e segurança de "
               "processos, com experiência em otimização de processos industriais."},
    "Angela Hayashi": {
        "cargo": "Engenheira e Doutora em Processos Ambientais",
        "bio": "23 anos de experiência em gestão de riscos operacionais e segurança de processos. "
               "Auditora Líder (ABNT NBR ISO)."},
    "Eduardo Perez": {
        "cargo": "Engenheiro Sênior de Tecnologia de Manufatura Avançada — 3M",
        "bio": "29 anos de experiência em processos e métodos de revestimento, com atuação em "
               "eficiência energética de processos de manufatura."},
    "Ronierik Pioli Vieira": {
        "cargo": "Professor Associado e Coordenador de Graduação FEQ Unicamp",
        "bio": "Graduação, mestrado e doutorado em Engenharia Química, com pesquisas em "
               "polimerização. Pós-doutorado em funcionalização de biopolímeros no Centro de "
               "Química Macromolecular da Ghent University (Bélgica)."},
    "André de Freitas Gonçalves": {
        "cargo": "Professor Pesquisador Colaborador",
        "bio": "Engenheiro Químico, Mestre pela UFMG e Doutor em Engenharia Química pela Unicamp. "
               "Pesquisador em termodinâmica de fluidos confinados e simulação molecular."},
    "Luiz Guilherme Lomônaco": {
        "cargo": "Professor Pesquisador Colaborador",
        "bio": "Engenheiro Químico, Doutor em Engenharia Química pela Unicamp, especialista em "
               "simulação de dinâmica molecular aplicada a sistemas biológicos."},
    "Savio Souza Venancio Vianna": {
        "cargo": "Professor Associado FEQ Unicamp",
        "bio": "Engenheiro Químico pela Escola de Química da UFRJ e Mestre pela COPPE/UFRJ, com "
               "PhD em Explosões pela Universidade de Cambridge. Pesquisa modelagem computacional "
               "de escoamentos reativos e não reativos."},
    "Douglas Alves Goulart": {
        "cargo": "Cientista de Dados",
        "bio": "Cientista de dados com experiência em mercado financeiro, marketing, logística e "
               "Indústria 4.0, focado em soluções orientadas a dados para decisões data-driven. "
               "Domina Machine Learning, Computer Vision, Reinforcement Learning e Cloud Computing "
               "(AWS e GCP), com Python (TensorFlow, PyTorch, scikit-learn, XGBoost, Pandas) "
               "aplicado a controle e automação de processos."},
    "Luis Fernando Mercier Franco": {
        "cargo": "Professor Associado FEQ Unicamp",
        "bio": "Engenheiro Químico, Mestre e Doutor em Ciências pela Poli-USP; Livre-Docente pela "
               "FEQ Unicamp. Atua em termodinâmica, mecânica estatística e simulação molecular."},
    "Gustavo Doubek": {
        "cargo": "Professor Associado FEQ Unicamp",
        "bio": "Doutor em Engenharia de Materiais e Nuclear pela USP, com período de pesquisa em "
               "Yale. Mais de 10 anos em pesquisa e ensino em células a combustível e baterias, "
               "com foco em energia limpa e desenvolvimento de produtos."},
}


# Congelado em 09/08/2026 — cópia ESTÁTICA de cursos_metas.turma NAQUELE momento,
# conferida ao vivo no banco de produção. NÃO importar de METAS: essa lista segue
# crescendo com cursos futuros, que devem nascer no slug perene desde a primeira
# turma, não herdar tratamento "legado". As URLs abaixo já circulam em campanha —
# não mudam nunca. Qualquer turma DIFERENTE da listada usa o slug perene.
# ponytail: comparação por valor de turma — assume que a Extecamp nunca reaproveita
# um número dentro do mesmo curso. Se acontecer, vira coluna cursos_metas.evergreen.
LEGADO_TURMA = {
    "FEQ-0480": "009", "FEQ-0580": "001", "FEQ-0333": "001", "FEQ-1000": "018",
    "FEQ-0360": "007", "FEQ-0331": "004", "FEQ-0299": "001", "FEQ-0670": "001",
    "FEQ-0499": "001",
}


def slug_lp(curso, turma):
    """URL da LP do curso. Uma regra só para todo mundo: deploy, cross-sell da LP e
    bloco de cursos da home. Duas implementações já produziram links divergentes."""
    turma = (turma or "").strip()
    legado = LEGADO_TURMA.get((curso or "").upper())
    if legado is not None and turma == legado.strip():
        return f"inscricao-{curso.lower()}-{turma}"      # URL já publicada: nunca muda
    return f"inscricao-{curso.lower()}"                   # oferecimento novo: URL perene


def url_inscricao(meta_row, c):
    """Destino do modal: SEMPRE o formulário /curso/inscricao/ (spec 17 §2).
    Preferência: url_extecamp da ontologia (governada); fallback cursos_metas.
    URLs antigas /curso/dados/ são normalizadas."""
    url = (c or {}).get("url_extecamp") or meta_row["url"]
    return url.replace("/curso/dados/", "/curso/inscricao/")


def _ddmm(iso):
    return "/".join(reversed((iso or "").split("-"))) if iso else ""


def _moeda(v):
    try:
        return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return ""


def _esc(v):
    return html.escape(str(v), quote=False)


def _secao_empresas(c):
    """Logos das empresas onde trabalham os alunos formados. Some sem `empresasJson`.
    Empresa sem logo cadastrado vira chip de texto — o nome é fato da ontologia, o
    logo é só o enfeite; não deixar o dado de fora por falta de imagem."""
    emp = (c or {}).get("empresas") or []
    if not emp:
        return ""
    itens = []
    for e in emp:
        # "Boehringer Ingelheim" e "Boehringer" são a mesma empresa no catálogo
        url = EMPRESA_LOGO.get(e) or next(
            (u for k, u in EMPRESA_LOGO.items() if e.lower().startswith(k.lower())), None)
        itens.append(f'<img src="{url}" alt="{_esc(e)}" loading="lazy" class="logo-empresa">'
                     if url else f'<span class="logo-empresa-txt">{_esc(e)}</span>')
    return (
        '<section id="empresas" data-secao="empresas" class="banda">'
        '<div class="faixa faixa-curta centro">'
        '<p class="kicker">Onde nossos alunos atuam</p>'
        '<h2 class="titulo-3 mt-2">Profissionais de empresas que você conhece</h2>'
        f'<div class="empresas-grid">{"".join(itens)}</div>'
        '</div></section>')


def _secao_curriculo(c):
    """"Seu Currículo no Futuro": o que o lead leva daqui — remuneração de referência,
    competências e o modelo do certificado. Cada bloco some sozinho sem o dado
    correspondente; se nenhum existir, a seção inteira some.
    Absorveu a antiga seção "O que você vai dominar", que listava as MESMAS
    habilidades em chips algumas seções abaixo (redesign monochrome, ago/2026)."""
    cod = (c or {}).get("codigo", "")
    salario = (c or {}).get("salario_ref")
    habs = (c or {}).get("habilidades") or []
    cert = CERTIFICADO_MODELO.get(cod)
    nome, carga = (c or {}).get("nome") or cod, (c or {}).get("carga_horas")
    # Sem NENHUM dos quatro não há currículo a mostrar (a folha teria só o nome do
    # curso, que a página inteira já repete).
    if not (salario or habs or cert or carga):
        return ""
    area = (c or {}).get("tipo") or "Extensão"
    blocos = [
        '<div class="cv-bloco"><p class="cv-rot">Formação complementar'
        '<span class="cv-tag">novo</span></p>'
        f'<p class="cv-item"><strong>{_esc(nome)}</strong>'
        f'<span>Extensão FEQ · Unicamp — {area}'
        + (f' · {carga}h' if carga else '') + '</span></p></div>']
    if habs:
        blocos.append(
            '<div class="cv-bloco"><p class="cv-rot">Competências'
            '<span class="cv-tag">novo</span></p><ul class="cv-habs">'
            + "".join(f'<li>{_esc(h)}</li>' for h in habs) + '</ul></div>')
    if salario:
        blocos.append(
            '<div class="cv-bloco"><p class="cv-rot">Referência de mercado</p>'
            f'<p class="cv-salario numero">{_esc(salario)}</p></div>')
    # Sem modelo publicado para o curso (a FEQ ainda não gerou o arquivo), a seção
    # DESCREVE o certificado em vez de mostrar a imagem de outro curso: emitir aqui um
    # "modelo" fabricado seria inventar um documento oficial da Unicamp.
    corpo_cert = (
        f'<img src="{cert}" alt="Modelo do certificado de {_esc(cod)}" loading="lazy">'
        '<p class="fraco mt-2">Modelo ilustrativo emitido pela Escola de '
        'Extensão da Unicamp ao concluir o curso.</p>' if cert else
        '<div class="cv-cert-txt">'
        '<p class="cv-cert-uni">Universidade Estadual de Campinas</p>'
        '<p class="cv-cert-linha">A Escola de Extensão declara que <strong>SEU NOME</strong> '
        # o tipo já vem como "Curso de Extensão"/"Formação de Especialistas": sem tirar
        # o "curso de" da frente sai "concluiu o curso de curso de extensão em"
        f'concluiu o curso de {_esc(re.sub(r"^curso de ", "", ((c or {}).get("tipo") or "extensão").lower()))} em</p>'
        f'<p class="cv-cert-curso">{_esc(nome)}</p>'
        + (f'<p class="cv-cert-linha">com carga horária total de <strong>{carga} horas</strong>.</p>'
           if carga else '') +
        '</div>'
        '<p class="fraco mt-2">Conteúdo da declaração emitida pela Escola de Extensão da '
        'Unicamp ao concluir o curso.</p>')
    cert_html = ('<aside class="cv-cert">'
                 f'<p class="kicker">{"A declaração" if _documento(c) != "Certificado" else "O certificado"} que você anexa</p>'
                 f'{corpo_cert}</aside>')
    # decorativa: o enquadramento (zoom/posição) mora no CSS, junto do resto do sistema
    foto = '<div class="cv-foto" aria-hidden="true"></div>'
    return (
        '<section id="curriculo" data-secao="curriculo" class="faixa regua-topo">'
        '<p class="kicker kicker-marca">Depois do curso</p>'
        '<h2 class="titulo mt-2">Seu currículo no futuro</h2>'
        '<p class="sub mt-2">O que muda no seu perfil profissional depois deste curso.</p>'
        '<div class="cv-grid"><article class="cv">'
        f'<header class="cv-topo">{foto}<div>'
        '<p class="cv-nome">Seu nome aqui</p>'
        f'<p class="cv-cargo">Profissional formado pela Extensão FEQ Unicamp</p>'
        '</div></header>'
        + "".join(blocos) +
        f'</article>{cert_html}</div>'
        '</section>')


def _documento(c):
    """Difusão a distância emite DECLARAÇÃO de frequência, não certificado (ontologia,
    `certificacao`) — mesma regra de pdf_guia._certificado, para a LP não prometer um
    documento que a Extecamp não emite."""
    return ("Declaração de frequência"
            if ((c or {}).get("certificacao") or "").startswith("Declaração") else "Certificado")


def _plano_exibicao(c):
    """Plano de 1 parcela É pagamento à vista: sem isto a página dizia "em até 1
    parcelas" e "1x de R$ 499,16". O grafo mantém numParcelas=1 (SHACL e Revisor
    dependem dele); só a exibição deixa de tratá-lo como parcelamento."""
    p = (c or {}).get("plano") or {}
    if p.get("n") != 1:
        return c
    return {**c, "plano": {**p, "n": None}}


_REQUISITO_DECL = {
    # A frase que o lead DECLARA (1ª pessoa). Sem exigência ("nenhum") não há o que
    # declarar: o bloco some e a etapa 2 fica com três pontos em vez de quatro.
    "medio": "Tenho ensino médio completo.",
    "superiorIncompleto": "Estou cursando ou já concluí um curso superior.",
    "superiorCompleto": "Tenho ensino superior completo (graduação concluída em qualquer área).",
    "pos": "Tenho pós-graduação concluída.",
}


def _opcoes_pagamento(c):
    """Opções de pagamento da etapa 2: [(valor, titulo, detalhe)]. `valor` fica no
    formato que a Extecamp usa no próprio formulário (o consultor o reconhece na
    Central); título/detalhe são o que o lead lê. Sempre o parcelamento MÁXIMO e o à
    vista, vindos do plano da ontologia — a mesma fonte que o Revisor usa para validar
    preço, então o que o lead aceita aqui não pode divergir do que o agente afirma."""
    p = (c or {}).get("plano") or {}
    pr = (c or {}).get("promocao") or {}
    ofs = pr.get("ofertas", [])
    ops = []
    # Opção de tabela que a campanha cobre (mesmo nº de parcelas, ou à vista) sai: a
    # ficha mostrava 19x de R$ 866,09 ao lado de 19x de R$ 799,90, e R$ 16.455,75 à
    # vista acima do parcelado promocional — o à vista parecia o mais caro.
    if p.get("n") and p.get("valor_parcela") and not any(o.get("n") == p["n"] for o in ofs):
        ops.append((f"{int(p['n']):02d} PARCELA(S) DE {_moeda(p['valor_parcela'])} "
                    f"ATRAVÉS DE BOLETO BANCÁRIO",
                    f"{int(p['n'])}x de {_moeda(p['valor_parcela'])}", "no boleto"))
    if p.get("a_vista") and not any(o.get("a_vista") for o in ofs):
        ops.append((f"01 PARCELA(S) DE {_moeda(p['a_vista'])} À VISTA, "
                    f"ATRAVÉS DE BOLETO BANCÁRIO",
                    f"{_moeda(p['a_vista'])} à vista", "boleto único"))
    # Campanha vigente: as ofertas entram JÁ COM O PREÇO COM DESCONTO. Cada linha leva
    # o nome da campanha: sem isso, uma oferta cujo rótulo fala em grupo faz o lead
    # achar que o preço à vista também exige grupo.
    campanha = pr.get("rotulo") or "promoção"
    for o in ofs:
        pct = f" −{o['desconto_pct']}%" if o.get("desconto_pct") else ""
        cond = f": {o['rotulo']}" if o.get("rotulo") else ""
        if o.get("n") and o.get("valor_parcela"):
            ops.append((f"{int(o['n']):02d} PARCELA(S) DE {_moeda(o['valor_parcela'])} "
                        f"ATRAVÉS DE BOLETO BANCÁRIO — {campanha}{cond}{pct}",
                        f"{int(o['n'])}x de {_moeda(o['valor_parcela'])}",
                        f"no boleto · {campanha}{pct}"))
        if o.get("a_vista"):
            ops.append((f"01 PARCELA(S) DE {_moeda(o['a_vista'])} À VISTA, ATRAVÉS DE "
                        f"BOLETO BANCÁRIO — {campanha}{pct}",
                        f"{_moeda(o['a_vista'])} à vista", f"boleto único · {campanha}{pct}"))
    # dedupe pelo valor, preservando a ordem: duas ofertas podem repetir o mesmo à vista
    return list({v: (v, t, d) for v, t, d in reversed(ops)}.values())[::-1]


def _attr(v):
    return html.escape(str(v), quote=True)


def _declaracoes(c):
    """Os pontos da etapa 2, na ordem em que aparecem: [(chave, título, frase)].
    `forma_pagamento` é um grupo de opções (radio), os demais são um checkbox cada.
    Tudo derivado da ontologia: requisito, modalidade, calendário, datas do boleto."""
    c = c or {}
    out = []
    if c.get("requisito") in _REQUISITO_DECL:
        out.append(("decl_requisito", "Escolaridade", _REQUISITO_DECL[c["requisito"]]))
    out.append(("forma_pagamento", "Investimento",
                "Estou de acordo com o valor do curso e escolho como pagar:"))
    mod = (c.get("modalidade") or "").strip()
    mod = (mod[:1].lower() + mod[1:]) if mod else "do curso"
    hor = (c.get("horario") or "").strip()
    if c.get("continuo"):
        frase = f"Estou de acordo com a modalidade {mod}" + (f": {hor}." if hor else ".")
    else:
        frase = f"Estou de acordo com a modalidade {mod}"
        if c.get("aulas_inicio") and c.get("aulas_fim"):
            frase += (f" e com as datas da turma: aulas de {_ddmm(c['aulas_inicio'])} "
                      f"a {_ddmm(c['aulas_fim'])}")
        frase += (f", {hor}." if hor else ".")
    out.append(("decl_modalidade", "Modalidade e datas", frase))
    fim, bol = _ddmm(c.get("inscricoes_fim")), _ddmm(c.get("boleto_data"))
    # spec 17 §3e: a data do boleto NUNCA é derivada do prazo — sem `boleto_data`
    # declarada, a frase diz só "logo após o encerramento", sem inventar o dia.
    if c.get("continuo") or not fim:
        frase = "Estou ciente de que o boleto é emitido logo após a formalização da inscrição."
    elif bol:
        frase = (f"Estou ciente de que o primeiro boleto será emitido em {bol}, logo após "
                 f"o encerramento das inscrições em {fim}.")
    else:
        frase = (f"Estou ciente de que o primeiro boleto será emitido logo após o "
                 f"encerramento das inscrições em {fim}.")
    out.append(("decl_boleto", "Primeiro boleto", frase))
    return out


def _etapa2_html(c):
    """Etapa 2 = qualificação (desde 26/11/2026): o lead confirma, ponto a ponto, que
    atende ao requisito e aceita valor, modalidade/datas e data do boleto. Substituiu
    a ficha de dados (CPF, endereço...) — os dados da matrícula agora são colhidos
    pelo consultor, que formaliza a inscrição na Extecamp. O `value` de cada checkbox
    é a própria frase: a pré-inscrição guarda o texto exato que a pessoa declarou."""
    blocos = []
    for i, (k, titulo, frase) in enumerate(_declaracoes(c), 1):
        erro = f'<p id="erro-{k}" class="erro decl-erro hidden">' + (
            "Escolha a forma de pagamento para continuar." if k == "forma_pagamento"
            else "Marque esta confirmação para continuar.") + "</p>"
        if k == "forma_pagamento":
            opcoes = "".join(
                f'<label class="decl decl-opcao"><input type="radio" name="forma_pagamento" '
                f'value="{_attr(v)}" required aria-describedby="erro-{k}">'
                f'<span class="decl-txt"><strong>{_esc(t)}</strong>'
                f'<span class="decl-det">{_esc(d)}</span></span></label>'
                for v, t, d in _opcoes_pagamento(c))
            p = (c or {}).get("plano") or {}
            nota = (f'<p class="decl-det decl-nota">Mais a taxa de inscrição de '
                    f'{_moeda(p["taxa"])}' + (f' ({_esc(p["taxa_meios"])})' if p.get("taxa_meios")
                                             else "") + '.</p>') if _moeda(p.get("taxa")) else ""
            corpo = (f'<p class="decl-intro">{_esc(frase)}</p>'
                     f'<div class="decl-opcoes">{opcoes}</div>{nota}')
        else:
            corpo = (f'<label class="decl"><input type="checkbox" name="{k}" '
                     f'value="{_attr(frase)}" required aria-describedby="erro-{k}">'
                     f'<span class="decl-txt">{_esc(frase)}</span></label>')
        blocos.append(f'<fieldset data-decl="{k}">'
                      f'<legend class="e2-legenda"><span class="decl-n">{i}</span>{titulo}</legend>'
                      f'{corpo}{erro}</fieldset>')
    return "\n".join(blocos)


def _conteudo_html(texto):
    """'(1) A; (2) B; ...' -> <li> numerados. Sem programa na ontologia -> item neutro."""
    if not texto:
        return '<li class="prog-item">Programa completo na página oficial da Extecamp.</li>'
    itens = [i.strip(" ;.") for i in re.split(r"\(\d+\)", texto) if i.strip(" ;.")]
    return "\n    ".join(
        f'<li class="prog-item"><span class="prog-n">{i + 1:02d}</span>{_esc(t)}</li>'
        for i, t in enumerate(itens))


def _objetivo_curto(c):
    """Primeira frase do objetivo oficial. O texto inteiro (5 linhas de ementa
    acadêmica) afogava a dobra; a íntegra continua na seção Objetivos."""
    txt = (c or {}).get("objetivo") or ""
    if not txt:
        return _esc((c or {}).get("insight_venda") or
                    "Curso oficial da Extensão FEQ Unicamp.")
    corte = txt.find(":")
    frase = txt[:corte] if 0 < corte < 220 else txt.split(". ")[0]
    return _esc((frase.strip().rstrip(".:") + ".") if len(frase) < len(txt) else txt)


def _hero_reforco(c, aberto):
    """Linha de redução de risco logo abaixo do CTA — onde o visitante hesita."""
    if not aberto:
        return "Sem compromisso: avisamos assim que a próxima turma abrir."
    partes = ["Inscrição pelo sistema oficial da Unicamp (Extecamp)"]
    if c.get("garantia_7d"):
        partes.append("7 dias de garantia")
    if (c.get("vagas") or {}).get("max"):
        partes.append(f"vagas limitadas a {c['vagas']['max']}")
    return _esc(" · ".join(partes) + ".")


def _invest_destaque(c, aberto):
    """Cabeçalho do bloco de fechamento: quanto se economiza e até quando.
    Sem promoção some — curso sem campanha não ganha urgência artificial."""
    pr = (c or {}).get("promocao")
    if not pr or not aberto:
        return ""
    melhor, tab = _melhor_oferta(pr), _total_tabela(c)
    eco = ""
    if melhor and tab:
        alvo = float(melhor["a_vista"]) if melhor.get("a_vista") else melhor["n"] * float(melhor["valor_parcela"])
        if tab - alvo > 0:
            eco = (f'<p class="invest-eco">Você economiza até '
                   f'<strong>{_moeda(f"{tab - alvo:.2f}")}</strong></p>')
    return (f'<div class="invest-destaque"><p class="invest-destaque-tag">{_esc(pr["rotulo"])}</p>'
            f'{eco}{_prazo_span(pr, "p", "invest-destaque-prazo")}</div>')


def _prazo_span(pr, tag="span", cls=""):
    """Prazo da campanha, preenchido no cliente (bridge-logic.js). Com `ciclo_h` é um
    relógio que zera a cada N horas e recomeça; o último ciclo para no fim REAL. A
    âncora é a meia-noite BRT do início da campanha, então todo visitante vê o mesmo
    relógio e recarregar não o reinicia. Sem JS fica o prazo real."""
    attrs = (f'data-contagem data-inicio="{pr["inicio"]}" data-ciclo-h="{pr["ciclo_h"]}"'
             if pr.get("ciclo_h") and pr.get("inicio") else "data-prazo-dias")
    c = f' class="{cls}"' if cls else ""
    return f'<{tag}{c} {attrs} data-fim="{pr["fim"]}">termina em {_ddmm(pr["fim"])}</{tag}>'


def _melhor_oferta(pr):
    """Oferta de menor valor total — é a âncora de 'economia' que a página anuncia."""
    def total(o):
        if o.get("a_vista"):
            return float(o["a_vista"])
        if o.get("n") and o.get("valor_parcela"):
            return o["n"] * float(o["valor_parcela"])
        return float("inf")
    ofertas = [o for o in (pr or {}).get("ofertas", []) if total(o) < float("inf")]
    return min(ofertas, key=total) if ofertas else None


def _total_tabela(c):
    p = (c or {}).get("plano") or {}
    try:
        if p.get("a_vista"):
            return float(p["a_vista"])
        if p.get("n") and p.get("valor_parcela"):
            return int(p["n"]) * float(p["valor_parcela"])
    except (TypeError, ValueError):
        pass
    return None


def _barra_promo(c, aberto):
    """Tarja fixa no topo. A promoção estava na 11ª de 14 seções — o visitante
    precisava rolar ~6.000px para descobrir que existe desconto. Aqui ela é a
    primeira coisa que ele vê, com o prazo REAL (a contagem é client-side: a
    página é publicada estática e um 'faltam X dias' do servidor congelaria)."""
    pr = (c or {}).get("promocao")
    if not pr or not aberto:
        return ""
    o = _melhor_oferta(pr)
    if not o:
        return ""
    chamada = pr["ofertas"][0]
    preco = (f"{chamada['n']}x de {_moeda(chamada['valor_parcela'])}"
             if chamada.get("n") and chamada.get("valor_parcela")
             else _moeda(chamada.get("a_vista") or o.get("a_vista")))
    return (
        f'<div class="barra-promo" data-secao="barra-promo">'
        f'<div class="barra-promo-in">'
        f'<span class="barra-promo-tag">{_esc(pr["rotulo"])}</span>'
        f'<span class="barra-promo-txt"><strong>{preco}</strong>'
        f'<span class="barra-promo-sep">·</span>'
        f'{_prazo_span(pr)}</span>'
        f'<button data-cta class="barra-promo-btn">Garantir vaga</button>'
        f'</div></div>')


def _hero_preco(c, aberto):
    """Preço na primeira dobra. Página de venda sem preço acima da dobra obriga o
    visitante a caçar a informação que mais pesa na decisão."""
    pr = (c or {}).get("promocao")
    p = (c or {}).get("plano") or {}
    if not aberto:
        return ""
    if pr and pr["ofertas"]:
        o = pr["ofertas"][0]
        principal = (f'{o["n"]}x de <strong>{_moeda(o["valor_parcela"])}</strong>'
                     if o.get("n") and o.get("valor_parcela") else _moeda(o.get("a_vista")))
        de = (f'<span class="hero-preco-de">de {p["n"]}x de {_moeda(p["valor_parcela"])}</span>'
              if p.get("n") and p.get("valor_parcela") else "")
        melhor, economia = _melhor_oferta(pr), None
        tab = _total_tabela(c)
        if melhor and tab:
            alvo = float(melhor["a_vista"]) if melhor.get("a_vista") else melhor["n"] * float(melhor["valor_parcela"])
            economia = tab - alvo
        extra = (f'<p class="hero-preco-eco">Economia de até <strong>{_moeda(f"{economia:.2f}")}</strong> '
                 f'— {_esc(melhor["rotulo"].lower())}</p>' if economia and economia > 0 else "")
        return (f'<div class="hero-preco">{de}'
                f'<p class="hero-preco-num">{principal}</p>{extra}</div>')
    if p.get("n") and p.get("valor_parcela"):
        return (f'<div class="hero-preco"><p class="hero-preco-num">'
                f'{p["n"]}x de <strong>{_moeda(p["valor_parcela"])}</strong></p></div>')
    if p.get("a_vista"):
        return (f'<div class="hero-preco"><p class="hero-preco-num">'
                f'<strong>{_moeda(p["a_vista"])}</strong> à vista</p></div>')
    return ""


def _hero_selos(c):
    """Selos de confiança na dobra: o que o visitante checa antes de considerar
    o preço. Só entra o que existe na ontologia — nada de badge inventado.
    Sem ícone: emoji é a única cor que entraria fora da paleta da marca."""
    selos = []
    if c.get("carga_horas"):
        selos.append(f"{c['carga_horas']}h de curso")
    selos.append(f"{_documento(c)} Unicamp")
    if c.get("formato_aulas_resumo") or c.get("modalidade"):
        selos.append(c.get("formato_aulas_resumo") or c["modalidade"])
    vagas = (c.get("vagas") or {}).get("max")
    if vagas:
        selos.append(f"Turma de até {vagas} alunos")
    return "".join(f'<span class="selo">{_esc(txt)}</span>' for txt in selos)


def _promo_ofertas_html(pr):
    """Ofertas da promoção como itens de lista. Cada oferta traz a CONDIÇÃO junto:
    anunciar '19x de R$ 736,18' sem dizer que exige grupo de 3+ seria propaganda enganosa."""
    out = []
    for o in pr["ofertas"]:
        partes = []
        if o.get("n") and o.get("valor_parcela"):
            partes.append(f"{o['n']}x de {_moeda(o['valor_parcela'])}")
        if o.get("a_vista"):
            partes.append(f"{_moeda(o['a_vista'])} à vista")
        pct = f' <span class="destaque">−{o["desconto_pct"]}%</span>' if o.get("desconto_pct") else ""
        # UM só filho: o <li> da lista é flex, então dois filhos virariam duas COLUNAS e
        # o preço quebraria no meio. O <div> segura preço e condição em fluxo normal.
        out.append(f'<div><strong>{" ou ".join(partes)}</strong>{pct}<br>'
                   f'<span class="fraco">{_esc(o["rotulo"])} — {_esc(o["condicao"])}</span></div>')
    return out


def _investimento_itens(c):
    p = (c or {}).get("plano") or {}
    pr = (c or {}).get("promocao")
    itens = []
    if pr:
        # o valor de tabela vira referência riscada: é o que dá tamanho ao desconto
        if p.get("n") and p.get("valor_parcela"):
            itens.append(f'<span class="risco fraco">De {p["n"]}x de '
                         f'{_moeda(p["valor_parcela"])}</span>')
        itens += _promo_ofertas_html(pr)
        if pr.get("fim"):
            fim = "/".join(reversed(pr["fim"].split("-")))
            itens.append(f'<span class="destaque">Promoção válida até {fim}</span>')
        # `como_aplicar` (o aviso de que o formulário da Extecamp mostra o valor cheio)
        # NÃO entra mais: a ficha de inscrição agora é nossa e já lista os preços com
        # desconto. O texto segue na ontologia porque os agentes ainda o usam quando
        # mandam o link oficial da Extecamp (inscrição fora do prazo).
    else:
        if p.get("n") and p.get("valor_parcela"):
            itens.append(f"Em até <strong>{p['n']}x de {_moeda(p['valor_parcela'])}</strong>")
        if p.get("a_vista"):
            itens.append(f"À vista: <strong>{_moeda(p['a_vista'])}</strong>")
    if p.get("taxa"):
        itens.append(f"Taxa de inscrição: {_moeda(p['taxa'])}")
    if (c or {}).get("descontos"):
        itens.append(_esc(c["descontos"]))
    if not itens:
        itens = ["Valores e condições oficiais na página da Extecamp."]
    return "\n      ".join(f'<li>{i}</li>' for i in itens)


def _foto_professor_html(nome):
    """<img> com a foto oficial do professor (diretório de docentes da FEQ) se
    reconhecido; string vazia (layout sem foto) caso contrário — nunca inventa."""
    url = PROFESSOR_FOTOS.get((nome or "").strip())
    if not url:
        return ""
    return (f'<img src="{url}" alt="Foto de {_esc(nome)}" class="foto-professor" loading="lazy">')


def _professor_credencial_html(nome):
    """Departamento + link do Lattes (currículo acadêmico oficial) quando o
    professor está no diretório da FEQ; string vazia caso contrário."""
    cred = PROFESSOR_CREDENCIAL.get((nome or "").strip())
    if not cred:
        return ""
    return (f'<p class="fraco mt-2">{_esc(cred["departamento"])} · '
            f'<a href="{cred["lattes"]}" target="_blank" rel="noopener" '
            f'class="link">Currículo Lattes</a></p>')


def _outros_professores_html(nomes, codigo=None):
    """Lista dos demais professores do curso, abaixo do card do responsável.
    Cada nome ganha link (Lattes/LinkedIn/Google Scholar) SÓ se PROFESSOR_LINK tem
    uma entrada verificada; sem entrada -> nome puro, sem link (nunca inventamos).

    Quem já tem card de DESTAQUE (com foto, em PROFESSOR_DESTAQUE) sai desta lista —
    senão a mesma pessoa aparece duas vezes na página, uma com foto e outra como
    nome solto logo abaixo. Bug real no FEQ-0670 (André e Luiz Guilherme
    duplicados) que valia para qualquer curso com PROFESSOR_DESTAQUE."""
    destaque = set(PROFESSOR_DESTAQUE.get(codigo or "", []))
    nomes = [n for n in (nomes or []) if n not in destaque]
    if not nomes:
        return ""
    itens = []
    for nome in nomes:
        link = PROFESSOR_LINK.get(nome)
        if link:
            itens.append(f'<a href="{_esc(link["url"])}" target="_blank" rel="noopener" '
                          f'class="link">{_esc(nome)}</a>')
        else:
            itens.append(f'<span>{_esc(nome)}</span>')
    return (
        '<div class="prof-mais">\n'
        '      <p class="kicker">Mais professores do curso</p>\n'
        '      <div class="linha-itens mt-2">\n'
        '        ' + '\n        '.join(itens) + '\n'
        '      </div>\n'
        '    </div>'
    )


def _secao_objetivos_html(objetivos):
    """'Objetivos do curso' — texto literal das páginas oficiais. Era uma seção
    própria; virou item do FAQ (redesign monochrome): a promessa do curso já é a
    dobra, e repeti-la em cards no meio da página só empurrava o preço pra baixo.
    O data-secao continua no <details> — a telemetria de interesse não se perde."""
    if not objetivos:
        return ""
    itens = "\n      ".join(
        f'<li><strong>{_esc(o["t"])}</strong> — {_esc(o["d"])}</li>' for o in objetivos)
    return ('<details class="qa" data-secao="objetivos">\n'
            '    <summary>Quais são os objetivos do curso?</summary>\n'
            f'    <ul>\n      {itens}\n    </ul>\n  </details>')


def _programa_html(c):
    """Programa: accordion módulo→subtópicos quando temos o detalhe oficial;
    senão, a lista numerada simples de sempre (nunca inventa subtópico)."""
    det = c.get("programa_detalhe") or []
    if not det:
        return _conteudo_html(c.get("conteudo_programatico"))
    itens = []
    for i, m in enumerate(det):
        subs = "".join(f'<li>{_esc(s)}</li>' for s in m.get("s") or [])
        corpo = f'<ul class="prog-subs">{subs}</ul>' if subs else ""
        itens.append(
            '<details class="prog-mod">'
            f'<summary><span class="prog-n">{i + 1:02d}</span>'
            f'{_esc(m["t"])}</summary>{corpo}</details>')
    return "\n    ".join(itens)


def _secao_depoimentos_html(depoimentos):
    """Depoimentos REAIS transcritos das páginas oficiais preexistentes."""
    if not depoimentos:
        return ""
    def _avatar(d):
        """Foto real publicada nas páginas oficiais; sem foto, iniciais (nunca inventar rosto)."""
        if d.get("foto"):
            return (f'<img class="depo-foto" src="{_esc(d["foto"])}" alt="Foto de {_esc(d["nome"])}" '
                    f'loading="lazy" width="48" height="48">')
        return f'<span class="depo-avatar" aria-hidden="true">{_esc(_iniciais(d["nome"]))}</span>'

    cards = "\n    ".join(
        '<figure class="depoimento">'
        '<span class="depo-aspa" aria-hidden="true">“</span>'
        f'<p class="depo-texto">{_esc(d["texto"])}</p>'
        '<figcaption>'
        f'{_avatar(d)}'
        f'<span class="depo-quem"><strong>{_esc(d["nome"])}</strong>'
        f'<span class="muted-cap">{_esc(d.get("cargo") or "")}</span></span>'
        '</figcaption></figure>'
        for d in depoimentos)
    return ('<section id="depoimentos" data-secao="depoimentos" class="faixa regua-topo">\n'
            '  <p class="kicker kicker-marca">Quem fez, recomenda</p>\n'
            '  <h2 class="titulo mt-2">Depoimentos de ex-alunos</h2>\n'
            '  <p class="fraco mt-2">Publicados pelos próprios alunos da Extensão FEQ Unicamp.</p>\n'
            f'  <div class="grid-2 mt-4">\n    {cards}\n  </div>\n</section>')


def _iniciais(nome):
    partes = [p for p in (nome or "").split() if p and p[0].isupper()]
    return "".join(p[0] for p in partes[:2]) or "?"


def _professores_bio_html(c):
    """Cards de DESTAQUE do corpo docente (PROFESSOR_DESTAQUE por curso), com foto
    publicada em página oficial — o responsável já tem card próprio, com a bio via
    {{PROFESSOR_DESC}}. Sem foto publicada -> avatar de iniciais (nunca inventa);
    bio/cargo/link só quando existem nas fontes oficiais."""
    cards = []
    for nome in PROFESSOR_DESTAQUE.get(c.get("codigo") or "", []):
        if nome == c.get("professor"):
            continue   # responsável já tem o card grande acima
        b = PROFESSOR_BIO.get(nome) or {}
        foto = _foto_professor_html(nome) or f'<span class="avatar-iniciais">{_esc(_iniciais(nome))}</span>'
        cred = _professor_credencial_html(nome)
        link = PROFESSOR_LINK.get(nome)
        rotulo = ""
        if not cred and link:
            rotulo = (f'<p class="fraco mt-2"><a href="{_esc(link["url"])}" '
                      'target="_blank" rel="noopener" class="link">'
                      f'{_esc(link["tipo"])}</a></p>')
        bio = f'<p class="fraco mt-2">{_esc(b["bio"])}</p>' if b.get("bio") else ""
        cargo = (f'<p class="kicker">{_esc(b["cargo"])}</p>' if b.get("cargo")
                 else '<p class="kicker">Professor do curso</p>')
        cards.append(
            '<div class="card">'
            f'<div class="prof-topo">{foto}<div>'
            f'<p class="titulo-3">{_esc(nome)}</p>'
            f'{cargo}</div></div>{bio}{cred or rotulo}</div>')
    if not cards:
        return ""
    return '<div class="grid-2 mt-4">\n    ' + "\n    ".join(cards) + "\n  </div>"


def _garantia_html(c):
    if not c.get("garantia_7d"):
        return ""
    return ('<p class="garantia-selo">Garantia de 7 dias — reembolso de 100% da '
            'matrícula se você não gostar do curso na primeira semana.</p>')


def _salario_html(c):
    s = c.get("salario_ref")
    if not s:
        return ""
    return ('<p class="fraco mt-3">Perspectiva profissional: salário de '
            f'referência {_esc(s)}.</p>')


def _periodo_html(c, aberto=True):
    """PERÍODO DE OFERECIMENTO (início e fim das aulas) — dado oficial da Extecamp,
    guardado na ontologia (janelaOferecimento). Some se o curso não tiver as datas.
    Curso sem turma aberta: rotula como 'última turma' para não dar a entender que
    essas datas valem para quem entra na lista de espera agora.
    Era faixa própria; virou item do FAQ (redesign monochrome) — é informação de
    consulta, não argumento de venda."""
    ini, fim = _ddmm(c.get("aulas_inicio")), _ddmm(c.get("aulas_fim"))
    if not (ini and fim):
        return ""
    if c.get("continuo"):
        # não há "início das aulas": a Extecamp publica a disponibilidade do conteúdo
        return (
            '<details class="qa" data-secao="periodo">\n'
            '    <summary>Quando posso começar?</summary>\n'
            '    <p>Não há turma com data de início: o oferecimento é contínuo e o horário '
            f'é livre. O conteúdo fica disponível na plataforma de <strong>{ini}</strong> '
            f'a <strong>{fim}</strong>.</p>\n  </details>')
    rotulo = "Período do curso" if aberto else "Período da última turma"
    return (
        '<details class="qa" data-secao="periodo">\n'
        f'    <summary>Quando começam e terminam as aulas?</summary>\n'
        f'    <p>{rotulo}: as aulas acontecem de <strong>{ini}</strong> '
        f'a <strong>{fim}</strong>.</p>\n  </details>')


def _passos_html(c, antecipada=False, abre_em=""):
    """Como se inscrever — 5 passos publicados nas páginas oficiais (Extecamp).

    `antecipada`: captamos aqui ANTES de a Extecamp abrir. O passo 1 original manda o
    lead preencher no sistema da Extecamp — que ainda não aceita inscrição nesta turma.
    Repetir esse texto mandaria o lead bater numa porta fechada e culpar a página."""
    taxa = _moeda((c.get("plano") or {}).get("taxa")) or "o valor publicado na Extecamp"
    # data do boleto desta turma, quando a coordenação a declarou (spec 17 §3e)
    quando = f" O boleto desta turma é de {_ddmm(c.get('boleto_data'))}." if c.get("boleto_data") else ""
    if antecipada:
        passos = [
            "Faça a pré-inscrição aqui mesmo nesta página: deixe seu contato e confirme as "
            "condições da turma. Leva cerca de um minuto e garante o seu lugar.",
            "A Extensão FEQ registra a sua inscrição no sistema oficial da Unicamp (Extecamp) "
            + (f"assim que ele abrir para esta turma, em {abre_em}. " if abre_em
               else "assim que ele abrir para esta turma. ")
            + "Você não precisa fazer nada neste passo.",
            "Você recebe por e-mail as instruções de acesso ao portal do aluno e o termo de "
            "compromisso, e envia os documentos na aba “Documentos”.",
            f"Pague o boleto da taxa de inscrição ({taxa}).{quando}",
            "Com a turma confirmada, a secretaria entra em contato por e-mail para o pagamento "
            "e a efetivação da matrícula. Pronto — você é aluno da Extensão Unicamp!"]
        return "\n    ".join(
            f'<li class="passo"><span class="passo-n">{i + 1}</span><span>{p}</span></li>'
            for i, p in enumerate(passos))
    if c.get("continuo"):
        # Oferecimento contínuo: os passos 4-5 abaixo mandam "aguardar a abertura da
        # turma ao encerramento das inscrições" — aqui isso seria esperar até 2031.
        p = c.get("plano") or {}
        plat = f" ({_esc(c['plataforma'])})" if c.get("plataforma") else ""
        passos = [
            "Faça a pré-inscrição aqui nesta página. Um consultor da Extensão FEQ fala com "
            "você pelo WhatsApp e formaliza a inscrição no sistema oficial da Unicamp "
            "(Extecamp); você recebe por e-mail as instruções de acesso ao portal do aluno.",
            f"Pague o curso ({_moeda(p.get('a_vista'))} à vista) por boleto bancário ou cartão "
            f"de crédito. A taxa de inscrição ({taxa}) é somada a esse valor.",
            f"Estude no seu horário: o oferecimento é contínuo, sem turma a esperar, e o "
            f"conteúdo fica disponível na plataforma{plat} até {_ddmm(c.get('aulas_fim'))}."]
        return "\n    ".join(
            f'<li class="passo"><span class="passo-n">{i + 1}</span><span>{p}</span></li>'
            for i, p in enumerate(passos))
    passos = [
        "Faça a pré-inscrição aqui nesta página: deixe seu contato e confirme as condições "
        "da turma (requisito, valor, modalidade e datas).",
        "Um consultor da Extensão FEQ fala com você pelo WhatsApp e formaliza a inscrição no "
        "sistema oficial da Unicamp (Extecamp). Você recebe por e-mail as instruções de "
        "acesso ao portal do aluno e o termo de compromisso.",
        "Preencha o termo de compromisso e envie os documentos na aba “Documentos” do "
        "portal do aluno.",
        f"Pague o boleto da taxa de inscrição ({taxa}).{quando}",
        "Com a documentação validada e a turma confirmada (ao encerramento das inscrições), "
        "a secretaria entra em contato por e-mail para o pagamento e a efetivação da "
        "matrícula. Pronto — você é aluno da Extensão Unicamp!"]
    itens = "\n    ".join(
        f'<li class="passo"><span class="passo-n">{i + 1}</span><span>{p}</span></li>'
        for i, p in enumerate(passos))
    return itens


def _secao_inscricao_html(c, aberto, antecipada=False, abre_em=""):
    """'Como se inscrever' (5 passos oficiais da Extecamp) — só com turma aberta.
    Sem turma, prometer um passo a passo de inscrição seria falso; a captação
    acontece pelo modal de lista de espera.
    Deixou de ser seção própria: mora DENTRO do bloco de investimento, que é onde a
    pergunta 'e como eu faço?' nasce — a sequência de blocos da página não ganha um
    degrau a mais por causa disso."""
    if not aberto:
        return ""
    intro = ("Sua inscrição começa aqui mesmo: a Extensão FEQ conclui o registro no sistema "
             "oficial da Unicamp (Extecamp) " + (f"quando ele abrir, em {abre_em}." if abre_em
                                                 else "assim que ele abrir.")
             if antecipada else
             "O processo acontece no sistema oficial da Unicamp (Extecamp) — leva poucos minutos.")
    return (
        '<div id="inscricao" data-secao="inscricao" class="passos-bloco">\n'
        '  <p class="kicker">Como se inscrever</p>\n'
        f'  <p class="fraco mt-1">{intro}</p>\n'
        f'  <ol class="mt-2">\n    {_passos_html(c, antecipada, abre_em)}\n  </ol>\n</div>')


def _faq_extra_html(c):
    """FAQ extra ancorado: certificação/MEC (texto oficial), avaliação e plataforma."""
    itens = []
    aval = c.get("avaliacao")
    if aval:
        plat = c.get("plataforma")
        extra = (f' As aulas ficam disponíveis na plataforma {_esc(plat)}.' if plat else "")
        itens.append(("Como funcionam as avaliações e entregas?", _esc(aval) + extra))
    # "é um curso de " + tipo.lower() dava "é um curso de CURSO DE extensão" (o rótulo
    # já começa com "Curso de"). O substantivo da frase é outro do rótulo do card.
    _NOME_TIPO = {"Formação de Especialistas": "formação de especialistas",
                  "Curso de Extensão": "extensão", "Curso de Difusão": "difusão"}
    itens.append((
        "Esse curso é lato-sensu? É reconhecido pelo MEC?",
        "A certificação é reconhecida pelo MEC e aclamada pelo mercado, mas o curso não se "
        "enquadra como pós-graduação lato-sensu: é um curso de "
        + _esc(_NOME_TIPO.get(c.get("tipo"), "formação"))
        + " e a Unicamp certifica diretamente todos os formados no tema abordado. Na prática, "
        "a ementa é constantemente atualizada com as tendências do mercado e o corpo docente "
        "inclui profissionais com ampla experiência na indústria."))
    return "\n    ".join(
        f'<details class="qa"><summary>{p}</summary><p>{r}</p></details>'
        for p, r in itens)


def _cursos_relacionados_html(g, ont, curso_atual, limite=3, hoje=None):
    """Cards de cross-sell (spec 17) — nunca lista o próprio curso da página.
    Com o portfólio inteiro no ar (9 LPs), mostrar todos viraria um paredão: fica
    no `limite`, priorizando quem está com INSCRIÇÃO ABERTA (mandar o lead pra um
    curso fechado é pior que não sugerir nada). Só usa cursos_metas + ontologia."""
    outros = [m for m in g.cursos() if m["curso"] != curso_atual]

    def _aberto(cod):
        try:
            return bool(ont.captavel(cod, hoje).get("captavel"))
        except Exception:
            return True
    # sort ESTÁVEL só por aberto/fechado: dentro de cada grupo preserva a ordem do
    # cursos_metas, que começa pelas turmas-alvo da campanha (prioridade comercial).
    outros.sort(key=lambda m: not _aberto(m["curso"]))
    itens = []
    for m in outros[:limite]:
        try:
            c = ont.curso(m["curso"]) or {}
        except Exception:
            c = {}
        nome = c.get("nome") or m["curso"]
        tipo = c.get("tipo") or "Curso"
        # MESMA função de slug do deploy — link relativo funciona tanto publicado
        # (mesma origem no WP) quanto localmente via /ponte.
        slug = slug_lp(m["curso"], m["turma"])
        itens.append(
            '<a href="/%s/" class="rel-card">'
            '<p class="kicker">%s</p>'
            '<p class="titulo-3 mt-1">%s</p>'
            '<p class="rel-seta">Conhecer curso →</p></a>'
            % (slug, _esc(tipo), _esc(nome)))
    return "\n    ".join(itens)


def render_tokens(meta_row, c, aberto=True, recuperavel=False,
                  antecipada=False, abre_em=""):
    """Tokens da LP a partir do cursos_metas + ontologia (c = ont.curso(...) ou {}).
    Regra anti-alucinação: todo fato vem da ontologia; sem âncora -> texto neutro
    apontando para a página oficial da Extecamp.
    aberto=False: a página vira LISTA DE ESPERA — mesmos fatos do curso, mas os
    CTAs/modal captam contato ("avise-me quando reabrir") em vez de prometer uma
    inscrição que não existe hoje."""
    c = _plano_exibicao(c or {})
    horario = c.get("horario") or ""
    plano = c.get("plano") or {}
    n, vp, taxa = plano.get("n"), plano.get("valor_parcela"), plano.get("taxa")
    promo = c.get("promocao")
    if promo and promo["ofertas"]:
        # o destaque do topo passa a ser o preço da campanha: é o que o lead compara
        o = promo["ofertas"][0]
        # resumo curto: só o essencial. O detalhe completo (todas as ofertas, condições,
        # tabela riscada) fica na seção Investimento — repetir tudo aqui virava parágrafo.
        melhor = _melhor_oferta(promo)
        plano_det = f"{promo['rotulo']}, até {_ddmm(promo.get('fim'))}."
        if melhor is not None and melhor is not o:
            alt = " ou ".join(
                ([f'{melhor["n"]}x de {_moeda(melhor["valor_parcela"])}']
                 if melhor.get("n") and melhor.get("valor_parcela") else [])
                + ([f'{_moeda(melhor["a_vista"])} à vista'] if melhor.get("a_vista") else []))
            plano_det += f" {melhor['rotulo']}: {alt}."
        if n and vp:
            plano_det += f" Valor de tabela: {n}x de {_moeda(vp)}."
    elif n:
        plano_det = f"Pagamento em até {n} parcelas" + (f" de {_moeda(vp)}" if vp else "")
        if taxa:
            plano_det += f" + taxa de inscrição de {_moeda(taxa)}"
        plano_det += "."
    elif plano.get("a_vista"):
        plano_det = f"Pagamento à vista de {_moeda(plano['a_vista'])}"
        if taxa:
            plano_det += f" + taxa de inscrição de {_moeda(taxa)}"
        plano_det += "."
    else:
        plano_det = "Condições de pagamento na página oficial da Extecamp."
    if c.get("descontos") and not promo:      # com campanha, isto já está no Investimento
        plano_det += " " + c["descontos"]
    formato_resumo = c.get("formato_aulas_resumo") or (
        "Sábados" if "sábado" in horario.lower() else (horario.split()[0].capitalize() if horario else "Flexível"))
    formato_detalhe = c.get("formato_aulas_detalhe") or (
        f"{horario} — pensado para quem trabalha." if horario else "Consulte a Extecamp.")
    # O nível vem da ontologia — NUNCA assumir "superior completo": há cursos que
    # pedem só ensino médio (FEQ-0299, FEQ-0670) e afirmar o contrário barraria
    # lead elegível e seria informação falsa na página.
    requisito = _REQUISITO_TEXTO.get(c.get("requisito") or "",
                                     "Consulte os requisitos na página oficial da Extecamp.")
    if c.get("publico_alvo"):
        requisito += " Público-alvo: " + c["publico_alvo"]
    wa = re.sub(r"\D", "", os.environ.get("GROWTH_WA_NUMERO", WA_NUMERO_DEFAULT))
    oi = f"Olá! Vim da página do curso {meta_row['curso']} e quero saber mais."
    return {
        "CURSO": meta_row["curso"],
        "TURMA": meta_row["turma"],
        "URL_CURSO": url_inscricao(meta_row, c),
        "WA_LINK": f"https://wa.me/{wa}?text={oi.replace(' ', '%20')}",
        "NOME_CURSO": c.get("nome") or meta_row["curso"],
        "TIPO_CURSO": c.get("tipo") or "Curso",
        "MODALIDADE": c.get("modalidade") or "Detalhes na Extecamp",
        "OBJETIVO": c.get("objetivo") or c.get("insight_venda")
                    or "Curso oficial da Extensão FEQ Unicamp — programa completo na página da Extecamp.",
        "PRAZO": _ddmm(c.get("inscricoes_fim")) or "a data publicada na Extecamp",
        "CARGA": str(c.get("carga_horas") or "?"),
        "HORARIO": horario or "consulte a Extecamp",
        "FORMATO_AULAS_RESUMO": formato_resumo,
        "FORMATO_AULAS_DETALHE": formato_detalhe,
        "PLANO_DETALHE": plano_det,
        "PROFESSOR": c.get("professor") or "Corpo docente FEQ/Unicamp",
        "PROFESSOR_DESC": (PROFESSOR_BIO.get((c.get("professor") or "").strip()) or {}).get("bio")
                          or "Docente da Faculdade de Engenharia Química da Unicamp, responsável "
                             "pelo curso junto à Extecamp (Escola de Extensão da Unicamp).",
        "REQUISITO": requisito,
        "CONTEUDO_HTML": _programa_html(c),
        "INVESTIMENTO_ITENS": _investimento_itens(c),
        "FOTO_PROFESSOR_HTML": _foto_professor_html(c.get("professor")),
        "PROFESSOR_CREDENCIAL_HTML": _professor_credencial_html(c.get("professor")),
        "OUTROS_PROFESSORES_HTML": _outros_professores_html(c.get("professores_adicionais"), c.get("codigo")),
        # Conteúdo rico das páginas oficiais preexistentes (seções somem se sem dado):
        "SECAO_OBJETIVOS": _secao_objetivos_html(c.get("objetivos")),
        "SECAO_DEPOIMENTOS": _secao_depoimentos_html(c.get("depoimentos")),
        "BARRA_PROMO": _barra_promo(c, aberto),
        "HERO_PRECO": _hero_preco(c, aberto),
        "HERO_SELOS": _hero_selos(c),
        "OBJETIVO_CURTO": _objetivo_curto(c),
        "HERO_REFORCO": _hero_reforco(c, aberto),
        "DOCUMENTO": _documento(c),
        "DOCUMENTO_GENERO": "Emitida" if _documento(c) != "Certificado" else "Emitido",
        "DOCUMENTO_NO": "na declaração" if _documento(c) != "Certificado" else "no certificado",
        "PROFESSORES_BIO_HTML": _professores_bio_html(c),
        "GARANTIA_HTML": _garantia_html(c),
        "SALARIO_HTML": _salario_html(c),
        "PASSOS_HTML": _passos_html(c, antecipada, abre_em),
        "PERIODO_OFERECIMENTO": _periodo_html(c, aberto),
        "FAQ_EXTRA_HTML": _faq_extra_html(c),
        # --- inscrição aberta × lista de espera (spec 17 §2b) ---------------------
        # recuperavel = prazo vencido MAS a turma ainda não começou: a mecânica de captura
        # é a mesma da lista de espera (precisamos do contato), só a copy muda — prometer
        # "aviso quando reabrir" aqui jogaria fora uma vaga que ainda existe HOJE.
        "CTA_LABEL": ("Inscreva-se →" if aberto else
                      ("Quero uma vaga remanescente →" if recuperavel else "Quero ser avisado →")),
        "PRAZO_LINHA": (
            f"Inscrições abertas até <strong>{_ddmm(c.get('inscricoes_fim')) or 'a data publicada na Extecamp'}</strong> · turma {meta_row['turma']}"
            if aberto else
            ("Prazo de inscrição <strong>encerrado</strong> — mas a turma "
             "ainda não começou e há <strong>vagas remanescentes</strong>. "
             "Deixe seu contato que a coordenação gera um link de inscrição fora do prazo."
             if recuperavel else
             "Inscrições <strong>encerradas no momento</strong> — entre na "
             "lista de espera e avisamos assim que a próxima turma abrir.")),
        "MODAL_TITULO": ("Para iniciar sua inscrição no sistema da Unicamp, informe seu contato rápido:"
                         if aberto else
                         ("Ainda dá para entrar: informe seu contato que a coordenação gera um "
                          "link de inscrição fora do prazo para você (o link vale 24 horas):"
                          if recuperavel else
                          "Entre na lista de espera deste curso. Assim que a próxima turma abrir, "
                          "a gente te avisa pelo WhatsApp:")),
        # o botão da etapa 1 abre a ETAPA 2 — prometer "para a Extecamp" aqui virou
        # falso quando o formulário passou a ter duas etapas (spec 17 §7)
        "MODAL_BOTAO": ("Continuar →" if aberto else
                        ("Quero meu link fora do prazo" if recuperavel else "Entrar na lista de espera")),
        # O passo a passo da Extecamp só faz sentido com turma aberta (vai dentro do
        # bloco de Investimento; o CTA final é o do próprio bloco, não uma seção extra).
        "SECAO_INSCRICAO": _secao_inscricao_html(c, aberto, antecipada, abre_em),
        "INVEST_DESTAQUE": _invest_destaque(c, aberto),
        "INVEST_TARJA": (f"Inscrições abertas até {_ddmm(c.get('inscricoes_fim'))}" if aberto
                         else ("Prazo encerrado · vagas remanescentes" if recuperavel
                               else "Valores da última turma · sem inscrições abertas")),
        "INVEST_RODAPE": (
            "Pagamento e emissão de boletos direto no sistema oficial da Unicamp (Extecamp)."
            if aberto else
            ("Valores desta turma. O prazo oficial encerrou, mas ainda dá para entrar pelo link "
             "de inscrição fora do prazo — deixe seu contato que a coordenação gera o seu."
             if recuperavel else
             "Valores praticados na última turma, para você se planejar — podem ser reajustados "
             "quando a próxima abrir. Entre na lista de espera para receber as condições oficiais.")),
        "FAQ_COMO_INSCREVER": (
            '<details class="qa">'
            '<summary>Como funciona a inscrição?</summary>'
            '<p>Ao clicar em Inscreva-se, você deixa seu contato e confirma as condições da '
            'turma (requisito, valor, modalidade e datas): é a sua pré-inscrição, e a vaga fica '
            'registrada conosco. O sistema oficial da Unicamp (Extecamp) abre para a turma '
            f'{meta_row["curso"]}/{meta_row["turma"]} em {abre_em}'
            ' — um consultor da Extensão FEQ fala com você pelo WhatsApp, formaliza a inscrição '
            'lá e orienta o termo de compromisso, os documentos e o boleto da taxa de '
            'inscrição.</p></details>'
            if (aberto and antecipada) else
            '<details class="qa">'
            '<summary>Como funciona a inscrição?</summary>'
            '<p>Ao clicar em Inscreva-se, você deixa seu contato e confirma as condições da '
            'turma (requisito, valor, modalidade e datas): é a sua pré-inscrição. Em seguida, '
            'um consultor da Extensão FEQ fala com você pelo WhatsApp e formaliza a inscrição da '
            f'turma {meta_row["curso"]}/{meta_row["turma"]} no sistema oficial da Unicamp '
            '(Extecamp) — com taxa de inscrição, envio de documentos e boletos gerados por '
            'lá.</p></details>'
            if aberto else
            ('<details class="qa">'
             '<summary>O prazo acabou. Ainda dá para entrar?</summary>'
             '<p>Sim. A turma ainda não começou e costumam '
             'sobrar vagas remanescentes: deixe seu contato no botão desta página que a '
             'coordenação gera um link de inscrição fora do prazo no seu e-mail. O link é '
             'individual e vale 24 horas.</p></details>'
             if recuperavel else
             '<details class="qa">'
             '<summary>Como entro na lista de espera?</summary>'
             '<p>Basta deixar nome e WhatsApp no botão desta '
             'página. Assim que a próxima turma for confirmada na Extecamp, avisamos você com as '
             'datas e o link oficial de inscrição — sem compromisso e sem custo.</p></details>')),
        "FAQ_PRAZO": (
            f"As inscrições desta turma vão até {_ddmm(c.get('inscricoes_fim')) or 'a data publicada na Extecamp'}."
            if aberto else
            (f"O prazo oficial encerrou em {_ddmm(c.get('inscricoes_fim'))}, mas as aulas ainda "
             "não começaram: há vagas remanescentes e a coordenação consegue gerar um link de "
             "inscrição fora do prazo. Deixe seu contato nesta página."
             if recuperavel else
             "Não há turma com inscrições abertas neste momento. Deixe seu contato na lista de "
             "espera que avisamos assim que a próxima for confirmada.")),
    }


def _bridge_bootstrap(tokens, webhook_url, pixel_id, aberto=True):
    """window.BRIDGE + bridge-logic.js, em UM bloco base64 (spec 17 / bug WP
    convert_chars): o WordPress normaliza "&" bruto -> "&#038;" em todo o
    post_content, mesmo dentro de <script>, quebrando o "&&" do JS. Base64
    usa só [A-Za-z0-9+/=] — imune a essa e a qualquer outra normalização de
    texto (aspas retas->curvas, travessões, reticências).
    aberto=False (sem turma na Extecamp): destino vazio — o JS confirma a
    entrada na lista de espera em vez de redirecionar (spec 17 §2b)."""
    config_js = "window.BRIDGE=" + json.dumps({
        "curso": tokens["CURSO"],
        # `destino` (URL do formulário da Extecamp) saiu: a etapa 2 não repassa mais o
        # lead para lá. O link oficial segue existindo para o time transcrever e para o
        # agente mandar em inscrição fora do prazo — mas isso não é assunto do navegador.
        "aberto": bool(aberto),
        "webhook": webhook_url,
        # etapa 2 mora ao lado da etapa 1 no mesmo host (o webhook_url já traz o
        # host público do hub — derivar daqui evita uma segunda variável de ambiente)
        "webhook_inscricao": webhook_url.replace("/webhook/ponte", "/webhook/inscricao"),
        "pixel": pixel_id,
        "gads_conversao": os.environ.get("GOOGLE_ADS_CONVERSAO") or GADS_CONVERSAO_DEFAULT}) + ";"
    completo = config_js + (_WEB / "bridge-logic.js").read_text()
    return base64.b64encode(completo.encode()).decode()


def render(g, ont, curso, webhook_url="/webhook/ponte", hoje=None):
    """HTML final da LP (template + JS + tokens). Curso desconhecido -> None.
    Curso SEM turma aberta na Extecamp -> LP em modo lista de espera (spec 17 §2b):
    mesma página, mas o CTA capta o contato em vez de mandar pra inscrição."""
    alvo = next((m for m in g.cursos() if m["curso"] == curso), None)
    if not alvo:
        return None
    try:
        c = _plano_exibicao(ont.curso(curso))
    except Exception:
        c = None
    recuperavel = antecipada = False
    abre_em = ""
    try:
        cap = ont.captavel(curso, hoje)
        aberto = bool(cap.get("captavel"))
        recuperavel = bool(cap.get("recuperavel"))
        # captação antecipada: a página abre, mas a Extecamp só recebe a inscrição a
        # partir de `inicio` — a data entra no texto para o lead saber o que esperar.
        antecipada = bool(cap.get("antecipada"))
        abre_em = _ddmm(cap.get("inicio")) if antecipada else ""
    except Exception:
        aberto = True    # sem ontologia (ex.: FakeOnt nos testes): comporta como aberto
    tokens = render_tokens(alvo, c, aberto=aberto, recuperavel=recuperavel,
                           antecipada=antecipada, abre_em=abre_em)
    pagina = (_WEB / "bridge-template.html").read_text()
    for k, v in tokens.items():
        pagina = pagina.replace("{{%s}}" % k, str(v) if k in _RAW_TOKENS else _esc(v))
    pixel_id = os.environ.get("META_PIXEL_ID", "")
    hero_bg = os.environ.get("GROWTH_HERO_BG_URL") or HERO_BG_URL_DEFAULT
    logo = os.environ.get("GROWTH_LOGO_URL") or LOGO_URL_DEFAULT
    css = ((_WEB / "bridge.css").read_text()
           .replace("{{HERO_BG_URL}}", hero_bg)
           .replace("{{CV_FOTO_URL}}", os.environ.get("GROWTH_CV_FOTO_URL") or CV_FOTO_URL))
    return (pagina
            .replace("{{CURSOS_RELACIONADOS_HTML}}", _cursos_relacionados_html(g, ont, curso))
            .replace("{{WEBHOOK_URL}}", webhook_url)
            .replace("{{SECAO_EMPRESAS}}", _secao_empresas(c))
            .replace("{{SECAO_CURRICULO}}", _secao_curriculo(c))
            .replace("{{E2_DECLARACOES}}", _etapa2_html(c))
            .replace("{{E2_TOTAL}}", str(len(_declaracoes(c))))
            .replace("{{REQUISITO_AVISO}}",
                     _esc(_REQUISITO_TEXTO.get((c or {}).get("requisito"), "")))
            .replace("{{LOGO_URL}}", logo)
            .replace("{{BRIDGE_CSS}}", css)
            .replace("{{BRIDGE_B64}}", _bridge_bootstrap(tokens, webhook_url, pixel_id, aberto)))


def pagina_obrigado_html():
    """/lp-thank-you-page/ — FIM da jornada da LP (spec 17 §7).

    O lead concluiu a pré-inscrição (etapa 2: confirmou requisito, valor, modalidade
    e boleto). Quem formaliza a matrícula na Extecamp é o consultor, e esta página
    diz exatamente isso — que um consultor de Extensão entra em contato.
    O path continua começando com 'thank-you-page' porque é o que o gatilho de
    conversão do Google Ads/GTM (GTM-WPXLCWJ, já no <head> do site) observa.
    Mesmos seletores de bridge.css pra tirar cabeçalho/faixa de título do tema."""
    gtm_id = os.environ.get("GROWTH_GTM_ID") or GTM_ID_DEFAULT
    logo = os.environ.get("GROWTH_LOGO_URL") or LOGO_URL_DEFAULT
    return (
        '<style>\n'
        '.page-header, .pre-content { display: none !important; }\n'
        '#site-header, #header-container, .mob-menu-header-holder,\n'
        '.mobmenu-panel { display: none !important; }\n'
        '#main.clearfix, #container.row-inner, #content,\n'
        'article.page.type-page, .entry-content.clearfix {\n'
        '  max-width: none !important; width: 100% !important; margin: 0 !important;\n'
        '  padding: 0 !important; border: none !important; box-shadow: none !important;\n'
        '  background: transparent !important;\n'
        '}\n'
        # mesma paleta/disciplina do redesign monochrome das LPs (raio 0, tinta FEQ)
        '.lp-obrigado {\n'
        '  min-height: 100vh; display: flex; align-items: center; justify-content: center;\n'
        '  flex-direction: column; text-align: center; background: #FFFFFF; color: #094567;\n'
        '  padding: 3rem 1.5rem; font-family: Montserrat, "Helvetica Neue", Arial, sans-serif;\n'
        '}\n'
        '.lp-obrigado img { height: 36px; margin-bottom: 2.5rem; }\n'
        # selo de conclusão no lugar do spinner: não há mais nada carregando —
        # girar um spinner aqui prometeria um redirecionamento que não vem.
        '.lp-obrigado .selo {\n'
        '  width: 56px; height: 56px; margin-bottom: 1.75rem; display: flex;\n'
        '  align-items: center; justify-content: center; background: #19ABB5;\n'
        '  color: #094567; font-size: 1.8rem; font-weight: 800;\n'
        '}\n'
        '.lp-obrigado p:first-of-type { font-size: 1.6rem; font-weight: 800; color: #065BAA;\n'
        '  letter-spacing: -0.03em; margin-bottom: .75rem; }\n'
        '.lp-obrigado p:last-of-type { color: rgba(9,69,103,.68); max-width: 30rem;\n'
        '  line-height: 1.6; }\n'
        '</style>\n'
        f'<div class="lp-obrigado">\n'
        f'  <img src="{logo}" alt="FEQ Unicamp">\n'
        '  <div class="selo">✓</div>\n'
        '  <p>Pré-inscrição concluída!</p>\n'
        '  <p>Em breve um de nossos consultores de Extensão entra em contato pelo '
        'WhatsApp para formalizar a sua matrícula e dar as devidas orientações. '
        'Não precisa fazer mais nada agora.</p>\n'
        '</div>\n'
        f'<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={gtm_id}" '
        'height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>'
    )   # sem JS próprio: o redirecionamento para a Extecamp deixou de existir, e o
        # pageview que o GTM observa é o do próprio carregamento da página


HOME_MARCA = "<!-- FEQ-CARDS-CURSOS"   # marcador do bloco que o deploy substitui


def home_marca_versao(html):
    """Carimbo de VERSÃO do bloco (hash do conteúdo). Sem ele, o deploy só conseguia
    perguntar "existe um bloco nosso na home?" — e respondia "publicado" mesmo quando
    o que estava no ar era a versão anterior, servida do cache do Elementor."""
    return hashlib.sha1(html.encode()).hexdigest()[:8]


def _card_home(m, c, cap):
    """Um card do bloco de cursos da home. Três estados, todos ancorados:
    aberto (prazo real), fora do prazo (a turma não começou — pedido de vaga
    remanescente) e sem turma (lista de espera). Nada de preço/prazo inventado."""
    c = _plano_exibicao(c)
    nome = (c or {}).get("nome") or m["curso"]
    tipo = (c or {}).get("tipo") or "Curso"
    aberto, recuperavel = bool(cap.get("captavel")), bool(cap.get("recuperavel"))
    linha = " · ".join(x for x in (
        f"{c['carga_horas']}h" if (c or {}).get("carga_horas") else "",
        (c or {}).get("formato_aulas_resumo") or (c or {}).get("modalidade") or "") if x)
    if aberto:
        selo, selo_cls = "Inscrições abertas", "aberto"
        prazo = _ddmm((c or {}).get("inscricoes_fim"))
        rodape = f"Inscrições até {prazo}" if prazo else "Prazo na página do curso"
        cta = "Ver curso e inscrever-se"
    elif recuperavel:
        selo, selo_cls = "Fora do prazo", "prazo"
        rodape = "Prazo encerrado, mas a turma ainda não começou — peça uma vaga remanescente"
        cta = "Pedir inscrição fora do prazo"
    else:
        selo, selo_cls = "Sem turma aberta", "espera"
        rodape = "Entre na lista de espera e avisamos quando a próxima turma abrir"
        cta = "Entrar na lista de espera"
    # preço só com turma aberta: valor de turma encerrada não é oferta
    preco = ""
    if aberto:
        pr, p = (c or {}).get("promocao"), (c or {}).get("plano") or {}
        o = (pr or {}).get("ofertas", [{}])[0] if pr else {}
        if o.get("n") and o.get("valor_parcela"):
            preco = f'<p class="feq-preco">{o["n"]}x de <strong>{_moeda(o["valor_parcela"])}</strong></p>'
        elif p.get("n") and p.get("valor_parcela"):
            preco = f'<p class="feq-preco">{p["n"]}x de <strong>{_moeda(p["valor_parcela"])}</strong></p>'
        elif p.get("a_vista"):
            preco = f'<p class="feq-preco"><strong>{_moeda(p["a_vista"])}</strong> à vista</p>'
    img = CURSO_IMAGEM.get(m["curso"])
    capa = (f'<span class="feq-capa"><img src="{img}" alt="" aria-hidden="true" '
            f'loading="lazy"></span>') if img else ""
    return (
        f'<a class="feq-card" href="/{slug_lp(m["curso"], m["turma"])}/">'
        f'{capa}'
        f'<span class="feq-selo feq-selo-{selo_cls}">{selo}</span>'
        f'<span class="feq-tipo">{_esc(tipo)}</span>'
        f'<span class="feq-nome">{_esc(nome)}</span>'
        + (f'<span class="feq-meta">{_esc(linha)}</span>' if linha else "")
        + preco +
        f'<span class="feq-rodape">{_esc(rodape)}</span>'
        f'<span class="feq-cta">{cta} →</span></a>')


def home_cursos_html(g, ont, hoje=None):
    """Bloco de cursos da HOME, gerado da ontologia (spec 17 §3d).

    Substitui a grade fixa de 4 imagens que apontava para as páginas antigas: aqui
    todo curso do catálogo vira card, com o estado REAL de captação, e o link é a LP
    (mesma função de slug do deploy). CSS embutido e escopado em .feq-cards — o resto
    da home (hero, diferenciais, menu, rodapé) não é tocado."""
    abertos, prazo, espera = [], [], []
    for m in g.cursos():
        try:
            c = ont.curso(m["curso"]) or {}
        except Exception:
            c = {}
        try:
            cap = ont.captavel(m["curso"], hoje) or {}
        except Exception:
            cap = {"captavel": True}
        card = _card_home(m, c, cap)
        (abertos if cap.get("captavel") else
         prazo if cap.get("recuperavel") else espera).append(card)
    cards = abertos + prazo + espera
    if not cards:
        return ""
    corpo = _home_corpo(cards)
    return f"{HOME_MARCA} v={home_marca_versao(corpo)} -->{corpo}"


_HEAD_SEL = re.compile(r"lp-head|lp-site-nav|lp-busca|menu-tgl|menu-btn|btn-mini")
_REGRA_CSS = re.compile(r"([^{}]+)\{((?:[^{}]|\{[^{}]*\})*)\}")


def _css_cabecalho():
    """Regras do cabeçalho tiradas do PRÓPRIO bridge.css (incluindo as do @media
    mobile) — a home não tem cópia do CSS para envelhecer diferente das LPs."""
    css = re.sub(r"/\*.*?\*/", "", (_WEB / "bridge.css").read_text(), flags=re.S)
    out = []
    for sel, corpo in _REGRA_CSS.findall(css):
        sel = sel.strip()
        if sel == ":root":                       # a paleta: na home vale só no cabeçalho
            out.append(".feq-head{%s}" % corpo.strip())
        elif sel.startswith("@media"):
            dentro = "".join("%s{%s}" % (a.strip(), b.strip())
                             for a, b in _REGRA_CSS.findall(corpo) if _HEAD_SEL.search(a))
            if dentro:
                out.append("%s{%s}" % (sel, dentro))
        elif _HEAD_SEL.search(sel):
            out.append("%s{%s}" % (sel, corpo.strip()))
    return re.sub(r"\s+", " ", "".join(out))


def home_cabecalho_html():
    """Cabeçalho da HOME = o das LPs (mesmo HTML do bridge-template, mesmo CSS do
    bridge.css). Viaja dentro do bloco de cursos porque é o único pedaço da home que
    publicamos; por isso é `fixed` (o `sticky` da LP só gruda quando o cabeçalho é
    filho direto da página) e o cabeçalho do tema (#masthead + menu mobile) é ocultado.
    Única diferença: o botão, que na LP abre o formulário, aqui leva à grade #cursos."""
    tpl = (_WEB / "bridge-template.html").read_text()
    head = re.search(r'<header class="lp-head">.*?</header>', tpl, re.S).group(0)
    head = re.sub(r"<!--.*?-->", "", head, flags=re.S)
    head = re.sub(r'<button data-cta class="btn-mini">.*?</button>',
                  '<a href="https://cursos-extensao.feq.unicamp.br/#cursos" class="btn-mini">'
                  'Ver cursos</a>', head)
    head = head.replace("{{LOGO_URL}}", os.environ.get("GROWTH_LOGO_URL") or LOGO_URL_DEFAULT)
    return ('<div class="feq-head"><style>'
            # #masthead = cabeçalho das páginas Elementor (home); #site-header = o das
            # páginas comuns do tema (contatos). Os dois, para servir a qualquer página.
            '#masthead,#site-header,#header-container,.mob-menu-header-holder,.mobmenu-panel,'
            '.mobmenu-overlay,.page-header,.pre-content{display:none!important}'
            'body{padding-top:73px!important}'   # altura medida do .lp-head (desktop 73 · mobile 57)
            '@media(max-width:700px){body{padding-top:57px!important}}'
            '.feq-head{position:fixed;top:0;left:0;right:0;z-index:9999;'
            'font-family:Montserrat,"Helvetica Neue",Arial,sans-serif;line-height:1.6}'
            '.admin-bar .feq-head{top:32px}'
            '.feq-head *{box-sizing:border-box}'
            '.feq-head a{text-decoration:none}'
            '.feq-head img{max-width:100%}'
            '.feq-head form{margin:0}'
            '.feq-head button{font:inherit;color:inherit;background:none;border:0;cursor:pointer}'
            + _css_cabecalho() + '</style>' + re.sub(r"\s*\n\s*", " ", head) + '</div>')


CONTATO_SLUG = "contatos"


def pagina_contato_html():
    """/contatos/ — destino do item "Contato" do cabeçalho (06/10/2026). Só canais
    confirmados, de contatos.CONTATOS_OFICIAIS (fonte única); nada de endereço ou
    horário que ninguém confirmou."""
    from atena.core.contatos import CONTATOS_OFICIAIS, INSTAGRAM
    sec = CONTATOS_OFICIAIS["secretaria"]
    wa = sec["telefone"].lstrip("+")
    itens = [("E-mail", sec["email"], "mailto:" + sec["email"])]
    if sec.get("whatsapp"):
        itens.append(("WhatsApp", "+55 " + sec["telefone_exibicao"], "https://wa.me/" + wa))
    itens.append(("Instagram", INSTAGRAM, "https://www.instagram.com/" + INSTAGRAM.lstrip("@") + "/"))
    cards = "".join(f'<a class="ct-item" href="{_esc(h)}"><span>{_esc(r)}</span>'
                    f'<strong>{_esc(v)}</strong></a>' for r, v, h in itens)
    return (home_cabecalho_html() +
            '<style>'
            '#main.clearfix,#container.row-inner,#content,article.page.type-page,'
            '.entry-content.clearfix{max-width:none!important;width:100%!important;'
            'margin:0!important;padding:0!important;border:none!important;'
            'box-shadow:none!important;background:transparent!important}'
            '.feq-contato{font-family:Montserrat,"Helvetica Neue",Arial,sans-serif;color:#094567;'
            'max-width:62rem;margin:0 auto;padding:4.5rem 1.75rem 5.5rem;line-height:1.6}'
            '.feq-contato .ct-olho{font-size:.7rem;font-weight:800;text-transform:uppercase;'
            'letter-spacing:.14em;color:#065BAA;margin:0 0 .6rem}'
            '.feq-contato h1{font-size:2.4rem;font-weight:800;letter-spacing:-.03em;line-height:1.15;'
            'color:#065BAA!important;margin:0 0 1rem}'
            '.feq-contato p{margin:0;max-width:38rem}'
            '.feq-contato .ct-grade{display:grid;gap:1px;background:rgba(6,91,170,.18);'
            'border:1px solid rgba(6,91,170,.18);border-top:4px solid #065BAA;margin-top:2.5rem;'
            'grid-template-columns:1fr}'
            '@media(min-width:700px){.feq-contato .ct-grade{grid-template-columns:repeat(3,1fr)}}'
            '.feq-contato .ct-item{display:flex;flex-direction:column;gap:.4rem;background:#fff;'
            'padding:1.6rem 1.4rem;text-decoration:none;color:#094567;'
            'transition:background-color 90ms linear,color 90ms linear}'
            '.feq-contato .ct-item:hover{background:#094567;color:#fff}'
            '.feq-contato .ct-item span{font-size:.66rem;font-weight:800;text-transform:uppercase;'
            'letter-spacing:.14em;color:#065BAA}'
            '.feq-contato .ct-item:hover span{color:#19ABB5}'
            '.feq-contato .ct-item strong{font-size:1.05rem;font-weight:800;letter-spacing:-.02em;'
            'overflow-wrap:anywhere}'
            '</style>'
            '<div class="feq-contato">'
            '<p class="ct-olho">Extensão FEQ Unicamp</p>'
            '<h1>Fale com a Secretaria de Extensão</h1>'
            '<p>Dúvidas sobre cursos, inscrição, pagamento ou documentos? Fale com a '
            'Secretaria de Extensão da Faculdade de Engenharia Química da Unicamp por um '
            'destes canais.</p>'
            f'<div class="ct-grade">{cards}</div>'
            '</div>')


def _home_corpo(cards):
    return (home_cabecalho_html() + '<div class="feq-cards"><style>'
            '.feq-cards{font-family:Montserrat,"Helvetica Neue",Arial,sans-serif;'
            'display:grid;gap:1px;background:rgba(6,91,170,.18);border:1px solid rgba(6,91,170,.18);'
            'grid-template-columns:1fr}'
            '@media(min-width:700px){.feq-cards{grid-template-columns:1fr 1fr}}'
            '@media(min-width:1000px){.feq-cards{grid-template-columns:1fr 1fr 1fr}}'
            '.feq-cards .feq-card{display:flex;flex-direction:column;gap:.35rem;background:#fff;'
            'padding:0 1.4rem 1.6rem;text-decoration:none;color:#094567;'
            'transition:background-color 90ms linear,color 90ms linear}'
            '.feq-cards .feq-card:hover{background:#094567;color:#fff}'
            # capa sangra até as bordas do card (margin negativa compensa o padding)
            # quem define a altura é a IMAGEM (aspect-ratio nela): com o aspect-ratio no
            # container e height:100% no <img>, a altura percentual não resolve e a capa
            # renderiza vazia — só o fundo cinza aparecia.
            '.feq-cards .feq-capa{display:block;margin:0 -1.4rem 1.3rem;overflow:hidden;'
            'background:#F5F7F9}'
            '.feq-cards .feq-capa img{width:100%;aspect-ratio:16/9;object-fit:cover;'
            'display:block;transition:opacity 90ms linear}'
            '.feq-cards .feq-card:hover .feq-capa img{opacity:.82}'
            '.feq-cards .feq-selo{align-self:flex-start;font-size:.62rem;font-weight:800;'
            'text-transform:uppercase;letter-spacing:.12em;padding:.22rem .5rem;margin-bottom:.5rem}'
            '.feq-cards .feq-selo-aberto{background:#19ABB5;color:#094567}'
            '.feq-cards .feq-selo-prazo{background:#FBBF24;color:#094567}'
            '.feq-cards .feq-selo-espera{background:#A2DADB;color:#094567}'
            '.feq-cards .feq-tipo{font-size:.66rem;font-weight:800;text-transform:uppercase;'
            'letter-spacing:.14em;color:#065BAA}'
            '.feq-cards .feq-card:hover .feq-tipo{color:#19ABB5}'
            '.feq-cards .feq-nome{font-size:1.08rem;font-weight:800;letter-spacing:-.02em;'
            'line-height:1.25;color:#065BAA}'
            '.feq-cards .feq-card:hover .feq-nome{color:#fff}'
            '.feq-cards .feq-meta{font-size:.8rem;opacity:.7}'
            '.feq-cards .feq-preco{margin:.35rem 0 0;font-size:.95rem}'
            '.feq-cards .feq-preco strong{font-size:1.15rem;font-weight:800;letter-spacing:-.02em}'
            '.feq-cards .feq-card:hover .feq-preco strong{color:#FBBF24}'
            '.feq-cards .feq-rodape{margin-top:auto;padding-top:.9rem;font-size:.76rem;opacity:.72}'
            '.feq-cards .feq-cta{margin-top:.9rem;font-size:.72rem;font-weight:800;'
            'text-transform:uppercase;letter-spacing:.08em;color:#065BAA}'
            '.feq-cards .feq-card:hover .feq-cta{color:#19ABB5}'
            '</style>' + "".join(cards) + '</div>')


def fragmento(html_completo):
    """Miolo da LP p/ publicar no WordPress (entre os marcadores LP-FEQ), sem
    doctype/head — o tema do WP embrulha; o bloco wp:html preserva o JS (spec 17 §4)."""
    m = re.search(r"<!-- LP-FEQ-INICIO.*?-->(.*)<!-- LP-FEQ-FIM -->", html_completo, re.S)
    return m.group(1).strip() if m else html_completo


def processar(dados, est, g, ads, ing, ont=None):
    """Webhook da ponte (público — valida tudo). dados = JSON do navegador
    ({nome, whatsapp|telefone, curso_id|curso, event_id, sessao_id, fbp, fbc, url})
    + ip/ua injetados pela rota. Retorna {ok, card_id, event_id, redirect}."""
    tel = re.sub(r"\D", "", dados.get("telefone") or dados.get("whatsapp") or "")
    curso = (dados.get("curso") or dados.get("curso_id") or "").strip().upper()
    alvo = next((m for m in g.cursos() if m["curso"] == curso), None)
    if not 10 <= len(tel) <= 13:
        return {"ok": False, "motivo": "telefone inválido"}
    if not alvo:
        return {"ok": False, "motivo": f"curso desconhecido: {curso or '?'}"}
    eid = dados.get("event_id") or ""
    if not _EVENT_ID_RE.match(eid):
        eid = str(uuid.uuid4())          # id do navegador ausente/sujo: gera (sem dedup, mas rastreia)
    nome = (dados.get("nome") or "").strip()[:120]
    # UTMs: a LP manda o dict pronto; `url` fica como fallback (extrair_utm cobre os dois)
    utm = dados.get("utm") if isinstance(dados.get("utm"), dict) else {}
    r = ing.ingest({"nome": nome, "telefone": tel, "curso": curso,
                    "email": (dados.get("email") or "").strip(),
                    "url": dados.get("url"), **utm,
                    "consentimento": "true", "fonte": "ponte"})
    if not r.get("ok"):
        return {"ok": False, "motivo": r.get("motivo", "ingestão falhou")}
    # Lead que já existia (quase sempre veio antes pelo WhatsApp) entra com o nome do
    # PERFIL ("mari 🎀"). A ingestão não sobrescreve nada de lead existente, então o
    # nome que a pessoa digitou na LP se perdia — e é ele que vai para a Extecamp.
    if est and nome and r.get("acao") == "atualizado" and \
            (est.get_lead(r["card_id"]) or {}).get("nome") != nome:
        est.set_lead(r["card_id"], nome=nome)
        est.log_acao("ponte", f"nome atualizado pelo formulário da LP: {nome}", r["card_id"])
    contexto ={k: dados.get(k) for k in ("fbp", "fbc", "ip", "ua", "url") if dados.get(k)}
    # Curso SEM turma aberta: o lead entrou na LISTA DE ESPERA, não num checkout.
    # Registrar checkout aqui seria errado em cadeia — jogaria o lead na aba
    # Verificação pedindo pro operador conferir na Extecamp uma inscrição que não
    # existe, e o poria na régua de recuperação de inscrição abandonada.
    try:
        aberto = bool(ont.captavel(curso).get("captavel")) if ont else True
    except Exception:
        aberto = True
    if aberto:
        # ETAPA 1 concluída. Evento SEM CAPI e sem Pixel: quem só deixou o telefone
        # ainda não é conversão (spec 17 §7) — o InitiateCheckout sai na etapa 2.
        # Gravado direto com add_evento, fora de EVENTO_CAPI, do mesmo jeito que
        # verificacao_negativa e recuperacao_enviada: mantém intocado o caminho de
        # atribuição, que é onde errar custa dinheiro.
        g.add_evento(r["card_id"], curso, "etapa1")
        if est:
            est.log_acao("ponte", f"etapa 1 concluída ({curso}) — aguardando ficha completa",
                         r["card_id"])
    else:
        funil.registrar(g, ads, est, r["card_id"], "lista_espera",
                        curso=curso, event_id=eid, contexto=contexto)
    if dados.get("sessao_id"):           # liga a telemetria da sessão ao lead (spec 17 §5)
        g.vincular_sessao(str(dados["sessao_id"])[:64], r["card_id"])
    # `aberto` diz à LP o que fazer: abrir a etapa 2 ou levar ao "voltamos em breve".
    # Sem `redirect`: o lead não vai mais à Extecamp por aqui — quem transcreve lá é o
    # agente comercial, com a ficha que a etapa 2 coletar.
    return {"ok": True, "card_id": r["card_id"], "event_id": eid, "aberto": aberto}


# Campos da ETAPA 2 — espelham o formulário oficial da Extecamp (PDFs de inscrição),
# menos nome/e-mail/telefone, que já vieram na etapa 1 e não se repetem.
# Lista branca: o que não está aqui é descartado, para o formulário público não virar
# porta de gravação de campo arbitrário no banco.
CAMPOS_ETAPA2 = (
    # dados pessoais
    "email_alt", "ddd_residencial", "telefone_residencial", "sexo", "genero",
    "doc_tipo", "doc_numero", "doc_emissor", "cpf", "nascimento", "estado_civil",
    "pais_nascimento", "estado_nascimento", "cidade_nascimento",
    "necessidades", "deficiencia", "ajuda",
    # endereço
    "cep", "rua", "numero", "complemento", "bairro", "estado", "cidade", "pais",
    # acadêmico
    "escolaridade", "instituicao", "instituicao_cidade", "curso_concluido", "ano_conclusao",
    # profissional
    "situacao", "empresa", "empresa_estado", "cargo", "departamento",
    "experiencia_anos", "superior",
    # financeiro
    "forma_pagamento", "comprovante_em",
    # qualificação (etapa 2 desde 26/11/2026): a frase exata que o lead confirmou
    "decl_requisito", "decl_modalidade", "decl_boleto",
)
# "Para finalizar" (como ficou sabendo / preferência de contato) saiu do formulário:
# a origem já vem dos UTMs e do fbclid, e o canal de contato é o WhatsApp que ele
# acabou de informar — eram dois campos a mais numa ficha que já é longa.
# Só a forma de pagamento: é o que a etapa 2 nova (qualificação) e a antiga (ficha,
# ainda em cache de navegador logo após a troca) têm em comum. As confirmações são
# exigidas no navegador; aqui guardamos o que veio, com a frase de cada uma.
OBRIGATORIOS_ETAPA2 = ("forma_pagamento",)


def processar_etapa2(dados, est, g, ads, ing, ont=None):
    """Etapa 2 da LP: a pré-inscrição qualificada. É AQUI que a conversão conta (spec 17 §7).

    Só neste ponto sai `inicio_inscricao` -> CAPI InitiateCheckout, com o event_id do
    NAVEGADOR, para desduplicar contra o Pixel que dispara no mesmo submit.

    O lead é reencontrado pelo TELEFONE (a mesma chave que a etapa 1 usou): nada de
    card_id trafegando pelo navegador, que seria um id de registro nosso exposto num
    formulário público e adulterável."""
    tel = re.sub(r"\D", "", dados.get("telefone") or dados.get("whatsapp") or "")
    curso = (dados.get("curso") or dados.get("curso_id") or "").strip().upper()
    alvo = next((m for m in g.cursos() if m["curso"] == curso), None)
    if not 10 <= len(tel) <= 13:
        return {"ok": False, "motivo": "telefone inválido"}
    if not alvo:
        return {"ok": False, "motivo": f"curso desconhecido: {curso or '?'}"}
    faltando = [c for c in OBRIGATORIOS_ETAPA2 if not (dados.get(c) or "").strip()]
    if faltando:
        return {"ok": False, "motivo": f"campos obrigatórios: {', '.join(faltando)}"}
    eid = dados.get("event_id") or ""
    if not _EVENT_ID_RE.match(eid):
        eid = str(uuid.uuid4())
    card_id = est.lead_por_telefone(tel) if est else None
    if not card_id:
        # Chegou na etapa 2 sem passar pela 1 (link direto, sessão perdida): cria o
        # lead em vez de recusar — perder uma ficha completa por isso seria absurdo.
        r = ing.ingest({"nome": (dados.get("nome") or "").strip()[:120], "telefone": tel,
                        "curso": curso, "email": (dados.get("email") or "").strip(),
                        "consentimento": "true", "fonte": "ponte-etapa2"})
        if not r.get("ok"):
            return {"ok": False, "motivo": r.get("motivo", "ingestão falhou")}
        card_id = r["card_id"]
    ficha = {c: (dados.get(c) or "").strip()[:500] for c in CAMPOS_ETAPA2 if dados.get(c)}
    g.add_inscricao(card_id, curso, alvo.get("turma") or "",
                    json.dumps(ficha, ensure_ascii=False))
    contexto = {k: dados.get(k) for k in ("fbp", "fbc", "ip", "ua", "url") if dados.get(k)}
    funil.registrar(g, ads, est, card_id, "inicio_inscricao",
                    curso=curso, event_id=eid, contexto=contexto)
    if est:
        # Pré-inscrição qualificada = PRÉ-INSCRITO no kanban (28/11/2026): confirmou
        # requisito, valor, modalidade/datas e boleto, mas ainda NÃO está na Extecamp.
        # O app manda em seguida o template com o link do formulário completo
        # (`_avisar_pre_inscricao`). Nunca regride quem já está adiante (a coleta pode
        # ter visto a pessoa inscrita antes).
        from atena.core.estado import alcancou
        if not alcancou((est.get_lead(card_id) or {}).get("fase"), "Pré-Inscrito"):
            est.upsert_lead(card_id, fase="Pré-Inscrito")
        est.log_acao("ponte", f"pré-inscrição qualificada recebida ({curso}) — fase "
                              f"Pré-Inscrito", card_id)
    return {"ok": True, "card_id": card_id, "event_id": eid}


def params_pre_inscricao(c, lead, ficha=None, captavel=None):
    """Variáveis do template `feq_pre_inscricao_aprovada` (whatsapp.CORPO_PRE_INSCRICAO),
    tudo da ontologia — a mesma fonte da LP e do Revisor. Devolve (params, None) ou
    (None, motivo): fail-closed, o consultor recebe o motivo e fala com o lead.

    Não envia quando o template afirmaria algo falso para este curso:
      • sem link da Extecamp (turma nova com `urlInscricaoLead`: o link aponta para a LP);
      • captação antecipada (a Extecamp ainda não abriu esta turma);
      • oferecimento contínuo (sem prazo, turma ou termo: os passos não se aplicam);
      • curso de outro instituto (a assinatura é da Secretaria de Extensão da FEQ)."""
    from atena.transporte.whatsapp import (CORPO_PRE_INSCRICAO, LIMITE_TEXTO_TEMPLATE,
                                           preencher_template)
    if not c:
        return None, "curso fora do catálogo"
    cod = c.get("codigo") or ""
    if not cod.upper().startswith("FEQ-"):
        return None, f"{cod} não é da FEQ (o template assina pela Secretaria da FEQ)"
    if c.get("continuo"):
        return None, f"{cod} é oferecimento contínuo: os passos do template não se aplicam"
    if (captavel or {}).get("antecipada"):
        return None, f"a Extecamp ainda não abriu a inscrição de {cod}"
    link = c.get("url_inscricao") or ""
    if "extecamp.unicamp.br/curso/inscricao/" not in link:
        return None, f"{cod} ainda não tem link de inscrição na Extecamp"
    c = _plano_exibicao(c)
    p = c.get("plano") or {}
    fim, bol = _ddmm(c.get("inscricoes_fim")), _ddmm(c.get("boleto_data"))
    # mesma regra da LP (spec 17 §3e): o dia do boleto nunca é derivado do prazo
    boleto = (f"O primeiro boleto do curso sai em {bol}, logo após o fim das inscrições."
              if bol else "O primeiro boleto do curso sai logo após o fim das inscrições.")
    aulas = ""
    if c.get("aulas_inicio") and c.get("aulas_fim"):
        aulas = f"de {_ddmm(c['aulas_inicio'])} a {_ddmm(c['aulas_fim'])}"
        if c.get("horario"):
            aulas += f", {c['horario']}"
    mod = (c.get("modalidade") or "").strip()
    mod = mod[:1].lower() + mod[1:]
    # a opção que o lead ESCOLHEU na qualificação; sem ela (ficha antiga), as opções
    escolhida = ((ficha or {}).get("forma_pagamento") or "").strip()
    ops = _opcoes_pagamento(c)
    alvo = [o for o in ops if o[0] == escolhida]
    if alvo:
        invest = f"{alvo[0][1]} {alvo[0][2].split(' · ')[0]}"
    else:
        invest = " ou ".join(t for _, t, _ in ops)     # só os títulos: cabe no limite
    # opção de campanha = a que leva o nome dela no detalhe ("no boleto · Valor promocional")
    promo = (" · " in alvo[0][2]) if alvo else bool((c.get("promocao") or {}).get("ofertas"))
    if promo:
        # o formulário da Extecamp mostra o valor CHEIO (promocao.como_aplicar): sem o
        # aviso, o lead vê outro preço no passo 1 e acha que a pré-inscrição mentiu
        invest += " (promocional: o formulário mostra o valor cheio e o desconto vem nos boletos)"
    primeiro = ((lead or {}).get("nome") or "").split()
    params = [
        primeiro[0].capitalize() if primeiro else "",
        f"{c.get('nome') or cod} ({cod})",
        link, fim, _moeda(p.get("taxa")), boleto, aulas, mod, invest,
    ]
    vazios = [i + 1 for i, v in enumerate(params) if not str(v).strip()]
    if vazios:
        return None, f"variável vazia no template ({', '.join(map(str, vazios))})"
    n = len(preencher_template(CORPO_PRE_INSCRICAO, params))
    if n > LIMITE_TEXTO_TEMPLATE:
        return None, f"mensagem preenchida com {n} caracteres (limite da Meta: {LIMITE_TEXTO_TEMPLATE})"
    return params, None
