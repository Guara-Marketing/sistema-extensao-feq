# 21 — Inscrição automática na Extecamp (robô)

**Status:** implementado em 06/11/2026 (`atena/coleta/inscricao.py`, 26 checks em
`atena/tests/test_inscricao_extecamp.py`). Dry-run conferido contra o formulário real
(FEQ-0480/009). **Primeira inscrição real feita** (06/11/2026, ver § Fluxo); ver § Ativação.

## Objetivo
A ficha que o lead entrega na etapa 2 da LP (spec 17) é lançada pelo robô no
formulário público de inscrição do curso — o mesmo que o lead preencheria — e o link
individual que a Extecamp devolve (`ok-inscricao_taxa.php?id1=…`) vai ao lead pelo
WhatsApp para ele validar a inscrição (termo + taxa). Substitui a transcrição manual.

## Fluxo na Extecamp (lido em 06/11/2026)
1. `GET /curso/inscricao/<SIGLA>/<TURMA>` → form que se auto-submete para
   `procura_aluno.php` (sigla, of, primeira=PRIMEIRA, cont=0).
2. `POST procura_aluno.php` → tela "Já fiz curso" (form1: `rg` → `procura_aluno.php?id=1`)
   e "Nunca fiz" (form2 → `inscricao.php?id1=…`).
3. **Ex-aluno**: busca por documento. Não achou = texto "Documento não localizado".
   Achou = pede a data de nascimento e abre a ficha pré-preenchida.
   Variantes testadas, nesta ordem (`variantes_documento`): como digitado, sem prefixo de
   UF, só dígitos, com hífen antes do dígito verificador, formato SP `12.345.678-9`,
   formato MG `12.345.678`, `MG…`/`MG-…`/`MG …` para emissor MG, CPF (CIN) com e sem máscara.
4. **Novo**: "Fazer primeiro cadastro" → ficha em branco.
5. `POST inscricao.php?id=1&…` com `cadastrar=cadastrar` → redireciona para
   `ok-inscricao*.php?id1=…` (sucesso). Sem esse link = falha.

Tela de data de nascimento do ex-aluno (vista em 06/11/2026): form `procura_aluno.php?id=2`
com selects `dia_t`/`mes_t`/`ano_t` (valores **sem zero à esquerda**: `5`, não `05`). Data
certa → página com `<script>location.href='inscricao.php?id1=…'</script>` (redirect em JS,
não HTTP), que o robô segue para chegar à ficha pré-preenchida. Tela desconhecida = pendência.

**CSRF (desde 25/11/2026, Vagner, FEQ-1150):** os forms da Extecamp passaram a levar um
`csrf_token` oculto. O "primeiro cadastro" (`inscricao.php?id1=` vazio) recusa GET (405) e
POST sem o token (403 "Requisição inválida"): vai com os campos do form2 (o token junto).
O ex-aluno abre a ficha pelo **GET do `location.href`** (200, ficha com o cadastro dele).
**Nunca** por um form "parecido" da página pós-data: o "Fazer primeiro cadastro" dela tem o
MESMO `id1` (só `id4` muda: F5 ex-aluno, F6 novo) e abre ficha EM BRANCO. Esse erro (de
25/11 manhã até a correção à noite) fez o robô inscrever o Vagner às 11:10 como cadastro
novo, com "Não informado" e nome encurtado — inscrição que depois sumiu. A ficha final **não traz** o token, mas o
POST dela o exige (403 sem ele, 1ª tentativa do Vagner): o token é um por sessão, então o
robô repete no envio final o da tela de busca.

**Primeira tentativa real (06/11/2026, FEQ-1150/001, Enzo):** primeiro cadastro, 47 campos,
e a Extecamp devolveu a ficha com "ATENÇÃO: Favor verificar os campos em destaque" — mas
**a inscrição foi feita** (conferido no ADM Cursos em 07/11). A resposta do POST não é
confiável; a palavra final é a **página de confirmação** `ok-inscricao_taxa.php?<ids>`, com
os ids do redirect em JS da tela de nascimento. Ela mostra "Pré inscrição foi concluída!"
quando a pessoa está inscrita na turma (`_ja_inscrito`, só leitura) — **mas só vale com a
data e o nº de inscrito preenchidos**: sem inscrição a Extecamp devolve o mesmo modelo
"concluída" com "realizada em: . Você é o ° inscrito" em branco (Handerson, 11/11/2026:
o robô tomou isso por inscrição e não enviou a ficha). O robô a consulta:
- **antes** de enviar, sempre que acha o cadastro (ex-aluno já inscrito → devolve o link, não envia);
- **depois** de um envio sem link, refazendo a busca (primeiro cadastro inscrito → link).
Falha que sobra guarda a página em `atena/data/extecamp_falhas/<card_id>.html` (PII; só no VPS).

## Mapeamento ficha → Extecamp (`valores_desejados`)
| Extecamp | Fonte | Regra |
|---|---|---|
| pf_nome, pf_email | etapa 1 (lead) | |
| DDD_CEL, celular | telefone do lead | `19` + `99999-0001` |
| pf_sexo | sexo | F/M (a Extecamp não aceita outro valor) |
| genero | genero | opções idênticas às da Extecamp (campo novo na LP) |
| do_ap_reg, pf_rg, pf_emissor | doc_tipo, doc_numero, doc_emissor | CIN: nº = CPF formatado |
| CPF1–4, DIA/MES/ANO | cpf, nascimento | |
| pf_estcivil, pf_naturae, pf_naturac | estado_civil, estado_nascimento, cidade_nascimento | |
| pf_nacion, pais_endereco | — | Brasil |
| pf_deficiencia/pf_def_qual | deficiencia | default NÃO |
| pf_cep … pf_cid | endereço | CEP completa rua/bairro/cidade (ViaCEP, como o navegador faz); cidade casada sem acento/caixa com `seleciona_cidade.php?id_estado=UF` |
| escolaridade | — | **Superior** |
| situacao_aluno | — | **Empregado** |
| textos acadêmicos/profissionais | — | **"Não informado"** |
| números (ano_conclusao, tempo_experiencia) | — | **"00"** |
| cidade_instituicao, pj_est/pj_cid | — | cidade/UF de moradia |
| forma_de_pagamento | forma_pagamento | casada pelo **nº de parcelas** (a LP mostra preço de campanha; a Extecamp, o de tabela) |
| misto, comprovante | — | NÃO; em nome do aluno |
| pf_fontinf, pf_tipo_contato | — | Redes sociais (RS), Celular |

Ex-aluno: o que a Extecamp trouxe preenchido **fica** (é o cadastro oficial); o robô só
completa o vazio, exceto as escolhas do curso (pagamento, misto, como soube, contato).

## Guardrails
- **Fail-closed**: qualquer obrigatório sem dado, opção não reconhecida, cidade fora da
  lista, tela desconhecida → `pendencias` (só nomes de campo, sem PII) e nada é enviado.
- CPF com dígito verificador errado (ou todo repetido) não é enviado: vira pendência.
- Celular de 8 dígitos (id do WhatsApp sem o 9) ganha o 9: a Extecamp o recusa ("campos em destaque", Suélen 16/11/2026). A pendência de envio sem link lista os campos `has-danger` (fora telefone residencial e `pj_*`, que ela sempre marca).
- Ex-aluno com nascimento recusado **não** cai para primeiro cadastro (duplicaria o aluno).
- **Turma que exige foto** (FEQ-0360/007, 17/11/2026: carteira estudantil): o "primeiro
  cadastro" e o redirect do ex-aluno vão para `upload_foto.php` em vez da ficha. O robô não
  envia foto. Mesmo assim ele busca o documento e confere `ok-inscricao_taxa` com os ids
  do redirect: quem já está inscrito sai com o link, e os demais viram pendência ("turma
  exige foto") e seguem à mão.
- Envio sem o link de volta e sem confirmação → `robo_obs` começa com `ENVIADO`. Rodar de
  novo só **confere** (nunca reenvia): se a página de confirmação mostra a inscrição, conclui
  com o link; senão o humano confere no ADM Cursos e marca Transcrita.
- **Link conferido antes de ir ao lead** (`conferir_link`, só leitura): a página precisa
  mostrar a inscrição com data e nº, o primeiro nome do lead e o botão do boleto da taxa
  (`gera_boleto`). Se não mostrar, a inscrição vale, mas o link **não** é enviado e vira
  alerta na Central com o motivo. O caso típico é "Termo já aceito": o lead já gerou o
  boleto e a página fica sem ação, então parece genérica (Enzo, 16/11/2026).
- Lock por card: duas execuções simultâneas do mesmo lead são recusadas.
- **reCAPTCHA no envio** (desde 25/11/2026 à tarde, Google reCAPTCHA v2 na ficha): o robô
  **nunca** contorna captcha. Com `g-recaptcha`/`data-sitekey` na ficha, ele para ANTES do
  POST final com a pendência "use o preenchimento assistido" — não marca `ENVIADO`. A
  simulação continua valendo (ficha pronta, `captcha: true`).
- Cidade digitada com a UF no fim ("Capão bonito SP", "… - SP", "…/SP", "… (SP)") casa com
  a lista da Extecamp (Everton, 25/11/2026).
- Ficha básica (spec 17, só CPF/nascimento/pagamento) não tem os obrigatórios → sempre
  pendência; esses cursos seguem na transcrição manual.
- Desde 08/11/2026 a ficha **completa** da LP exige no navegador (`required`) tudo que o
  robô precisa: documento (tipo, número, UF emissora), sexo, gênero, estado civil, UF e
  cidade de nascimento, CEP, rua, número, bairro, cidade e UF. Só o complemento é opcional.
  O servidor (`OBRIGATORIOS_ETAPA2`) continua aceitando só CPF/nascimento/pagamento, de
  propósito: uma LP antiga em cache que mande ficha incompleta não pode perder o lead
  (o JS segue para o obrigado mesmo com erro). Ficha incompleta assim cai em pendência no
  robô, e o lead recebe o link oficial de inscrição.

## Integração
- `POST /api/inscricoes/<card_id>/extecamp` `{"valer": false|true}`. Central, aba
  Inscrições: **simular** (só leitura) e **Inscrever na Extecamp** (com confirmação).
- Sucesso = mesmo efeito de "Transcrita" (status, fase Inscrito, CAPI offline), com o
  link guardado em `inscricoes.link_extecamp` e enviado no template
  `feq_continuidade_inscricao` (nome, curso, link). Template não aprovado/opt-out: não
  envia, o link fica na ficha para envio manual.
- Falha → `inscricoes.robo_obs` + alerta `inscricao` na caixa de Notificações.
- **Automático**: `INSCRICAO_AUTO=1` no `.env` faz o robô rodar em thread assim que a
  etapa 2 chega (`/webhook/inscricao`). Sem a flag, só pelo botão.

## Preenchimento assistido (desde 25/11/2026)
Com o reCAPTCHA, quem envia a ficha é uma pessoa; o robô faz a leitura e o operador só cola.
1. Central → Inscrições → **Preencher assistido**: `GET /api/inscricoes/<card_id>/preenchimento`
   roda a simulação e devolve o caminho (ex-aluno/primeiro cadastro), o documento que a busca
   achou, a data de nascimento, a URL do curso e `dados` = só os campos que o robô mudaria
   na ficha (sem `csrf_token`, que é da sessão do robô).
2. O operador instala uma vez o favorito **Atena · preencher ficha**: ele injeta
   `/inscricao/preenchedor.js` (rota pública, **sem dado nenhum**). Os dados do lead vão pela
   área de transferência ("Copiar dados") e são colados num `prompt` na página da Extecamp.
3. O script preenche (UF antes, espera a lista de cidades carregar por AJAX), contorna em
   verde, lista o que não conseguiu e rola até o captcha. **Nunca envia.** Ficha já com nome
   de outra pessoa (ex-aluno) pede confirmação antes de preencher. Na ficha real: campo
   achado por `name` (a página repete `id` — `pf_email`, `celular`) e um par UF→cidade por
   vez (o AJAX de cidades usa uma global `xmlHttp`; duas UFs juntas = cidade no spinner).
   O captcha vale ~2 min: marcar e enviar em seguida.
4. A pessoa marca o captcha e envia. **Já enviei: conferir** = `POST …/extecamp
   {"conferir": true}`: marca `robo_obs` como `ENVIADO pelo preenchimento assistido` e roda o
   modo conferência (acha a inscrição pela busca, marca Transcrita, CAPI, manda o link).

Primeiro uso real (25/11/2026, Najara e Everton, FEQ-0670, primeiro cadastro): ambas
inscritas. Depois do envio a Extecamp redireciona para `sistemas.extecamp.unicamp.br/
termo_clicksign_desen/update.php`, que quebra com "email é obrigatório" (chega e-mail vazio
à Clicksign) — defeito da Extecamp; a inscrição fica gravada, mas o termo provavelmente não
foi gerado. Avisar a secretaria.

## Ativação
1. Primeira inscrição real pelo botão, com um lead verdadeiro, conferindo no ADM Cursos.
2. Um ex-aluno real para validar a tela de nascimento.
3. Então `INSCRICAO_AUTO=1` no VPS. **Ligado em 16/11/2026**, depois do lote da fila
   (4 fichas: 3 inscritas e conferidas na página com data e nº; 1 "campos em destaque"
   sem confirmação, segue para conferência humana no ADM Cursos).
