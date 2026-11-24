# Semente — sessão de edição do Sistema Atena FEQ

> **Para quem vai usar:** abra o Claude Code numa pasta vazia (ou na pasta do projeto, se já
> clonou), cole este arquivo inteiro na primeira mensagem e diga o que quer mudar.
> **Para o Claude que está lendo:** este é o seu briefing. Siga a seção "Primeiros passos" antes
> de qualquer edição e respeite as "Regras que não se negociam".
>
> ⚠️ O repositório é **PÚBLICO**. Este arquivo não traz segredos e nada com segredo deve ser
> commitado. A chave do servidor e os tokens são entregues por fora, em canal seguro.

---

## 1. O que é o sistema

**Atena**: CRM operado por agentes de IA que capta alunos para os cursos de extensão da FEQ
Unicamp (e do Instituto de Economia, curso ECO-1100). Os leads chegam por Meta/Google Ads e pelas
landing pages; a Atena conversa pelo WhatsApp Business Cloud, qualifica o lead, faz a inscrição na
Extecamp e acompanha até a matrícula. A **Central de Operação** é a interface web que a equipe usa.

- Produção: **https://feq.vitoraugolis.com.br** (fallback: https://144.33.22.236.sslip.io)
- Stack: Python 3 + Flask (servido por waitress) + SQLite + ontologia JSON-LD/SHACL. Sem framework pesado.
- Contexto completo: **`CLAUDE.md`** na raiz do repo (lido automaticamente pelo Claude Code) e
  as **specs em `specs/`, que são a fonte da verdade**.

## 2. Onde as coisas estão

| O quê | Onde |
|---|---|
| Código | GitHub **`Guara-Marketing/sistema-extensao-feq`**, branch `main` |
| Clone HTTPS | `https://github.com/Guara-Marketing/sistema-extensao-feq.git` |
| Servidor | VM Oracle Cloud **`144.33.22.236`**, Ubuntu x86_64, 1 GB RAM, usuário SSH `ubuntu` |
| Chave SSH | arquivo `.pem` da empresa → salvar em **`~/.ssh/oracle-b.key`** com `chmod 600` |
| App no servidor | `/home/ubuntu/atena-feq` (venv em `.venv`), serviço systemd **`atena`** na porta 8095 |
| HTTPS | serviço **`caddy`**; config em `/etc/caddy/Caddyfile` + `/etc/caddy/*.caddy` |
| Segredos de produção | `/home/ubuntu/atena-feq/.env` (**só existe no servidor**) |
| Banco de produção | `/home/ubuntu/atena-feq/atena/data/atena.db` (SQLite em modo WAL) |
| Ontologia viva | `atena/ontologia/catalogo.jsonld` + `versoes/` **no servidor** (o Injetor grava nela) |
| Logs | `sudo journalctl -u atena -n 200 --no-pager` |
| Outros sistemas na VM | regras em `atena/ops/GUIA_novo_sistema_no_vps.md` |

## 3. Acessos que a pessoa precisa ter (checar antes de começar)

1. **GitHub**: conta convidada como colaboradora (permissão *Write*) em
   `Guara-Marketing/sistema-extensao-feq`. Sem isso dá para clonar (o repo é público), mas não dá
   para fazer push. Autenticar a máquina com `gh auth login`.
2. **Servidor**: a chave `.pem` em `~/.ssh/oracle-b.key` (`chmod 600 ~/.ssh/oracle-b.key`).
3. **Central**: um usuário criado por um supervisor em Configurações → Usuários (para conferir
   as mudanças em produção pelo navegador).
4. Máquina local: `git`, `python3` (3.11+), `rsync`, `ssh`, `zsh`, e o `gh` CLI. No macOS, o
   WeasyPrint (PDF do guia do curso) precisa de `brew install pango`.

## 4. Primeiros passos (Claude: faça nesta ordem e relate o resultado)

```bash
# 1. clonar (pule se já estiver dentro do repo)
git clone https://github.com/Guara-Marketing/sistema-extensao-feq.git
cd sistema-extensao-feq

# 2. ambiente local
python3 -m venv .venv && source .venv/bin/activate
pip install flask requests rdflib pyshacl waitress weasyprint

# 3. testes (todos devem passar antes de qualquer mudança)
for f in atena/tests/test_*.py; do python3 "$f" >/dev/null 2>&1 && echo "ok  $f" || echo "FALHOU $f"; done
python3 atena/ontologia/validar.py

# 4. acesso ao GitHub (push)
gh auth status && gh repo view Guara-Marketing/sistema-extensao-feq --json viewerPermission

# 5. acesso ao servidor (somente leitura)
ssh -i ~/.ssh/oracle-b.key ubuntu@144.33.22.236 'systemctl is-active atena caddy; free -h; df -h /'
curl -s -o /dev/null -w "%{http_code}\n" https://feq.vitoraugolis.com.br/
```

Depois disso, **leia `CLAUDE.md` e a spec da área que vai mexer** antes de propor qualquer código.

### Rodar a Central localmente

```bash
ATENA_DEV=1 python3 atena/api/app.py     # http://localhost:8095 · login operador/operador
```

`ATENA_DEV=1` **desliga o agendador** (não envia nada a lead, não publica LP, não chama Meta).
**Nunca rode localmente sem ele** e **nunca copie o `.env` de produção para a máquina local**:
em 09/07/2026 uma instância local com tokens reais reenviou template a ~28 leads.

## 5. Fluxo de trabalho (o mesmo usado até aqui)

1. Entender o pedido → ler a spec em `specs/` e o código envolvido → **se o comportamento muda,
   atualizar a spec antes de codar**.
2. Implementar o mínimo que resolve. Python stdlib + flask + requests; sem dependência nova sem motivo.
3. Deixar um teste reproduzível em `atena/tests/test_<area>.py` (scripts com `assert`, sem
   framework) e rodar a suíte da área.
4. Atualizar `CLAUDE.md` § 9/10 se a mudança é relevante para quem vem depois.
5. **Ao terminar cada entrega**: commit em `main` → `git push origin main` → deploy → conferir em produção.

```bash
zsh atena/ops/deploy_vps.sh 144.33.22.236 ubuntu
ssh -i ~/.ssh/oracle-b.key ubuntu@144.33.22.236 'systemctl is-active atena && sudo journalctl -u atena -n 30 --no-pager'
curl -s -o /dev/null -w "%{http_code}\n" https://feq.vitoraugolis.com.br/
```

O deploy faz rsync do código, **reinicia o serviço** (a Central cai por alguns segundos) e
**preserva** `.env`, `atena/data/` e a ontologia viva do servidor. Dependência Python nova **não**
é instalada pelo deploy: instale antes no `.venv` do servidor
(`ssh ... '~/atena-feq/.venv/bin/pip install <pacote>'`). Não há `requirements.txt`; as versões
de produção estão fixadas (pyshacl 0.31.0, weasyprint 69.0).

## 6. Regras que não se negociam

- **Mensagem a lead sempre passa pelo Revisor.** Nenhum caminho novo pode enviar WhatsApp,
  gastar verba de anúncio ou inscrever alguém sem a trava/aprovação existente (`specs/07`).
- **Ação irreversível nunca depende só do LLM** (opt-out, descarte, inscrição): precisa de trava
  determinística na borda.
- **Não sobrescrever** no servidor: `.env`, `atena/data/`, `atena/ontologia/catalogo.jsonld`,
  `atena/ontologia/versoes/`. Mudança de catálogo (preço, turma, link) vai pelo **Injetor** na
  Central (`/api/injetor/...`), não por edição de arquivo.
- **Segredos**: só via `os.environ`; nunca em commit, log, chat ou mensagem. O repo é público.
- **PII de lead** (nome, telefone, e-mail, CPF) não sai do servidor e não vai para commit.
- Dedupe de lead **sempre por telefone** (só dígitos). Fuso **America/Sao_Paulo**; script fora do
  pacote precisa `import atena` para herdar o fuso.
- Fase do funil: nunca compare por lista de strings; use `estado.alcancou(fase, "Inscrito")`.
- Confirmar com a pessoa antes de: reiniciar a VM, mexer no `.env` de produção, apagar dados,
  disparar campanha, publicar LP manualmente ou qualquer ação visível para leads.

## 7. Pegadinhas conhecidas

- **Banco em WAL**: consulte o arquivo vivo (`sqlite3 ~/atena-feq/atena/data/atena.db "..."`);
  copiar o `.db` sem o `-wal` mostra dados velhos.
- **`.env` de produção tem valor com espaço** (`WP_APP_PASSWORD`): `source .env` trunca. O app usa
  parser próprio; script avulso deve ler o arquivo do mesmo jeito.
- Para checar se um segredo está configurado, faça `grep` no **arquivo** `.env` (sem imprimir o
  valor), não em `/proc/<pid>/environ`.
- O tick horário republica sozinho a LP cuja renderização mudar: mudança em template de LP vai ao
  ar no WordPress em até 1h depois do deploy.
- `auto_aprovar` volta a OFF a cada restart do serviço (decisão de governança); religar na Central.
- A VM tem 1 GB de RAM; `atena/ops/recursos.py` avisa na Central quando disco/RAM/CPU apertam.
- O IP `3.218.159.36` era o servidor antigo (apagado): o deploy recusa esse IP.

## 8. Mapa rápido do código (`atena/`)

| Pasta | Papel |
|---|---|
| `api/app.py` | Flask: rotas da Central, webhooks Meta/WhatsApp, agendador `_operacoes` (tick 60s) |
| `web/` | SPA da Central (HTML/JS/CSS) |
| `core/` | estado SQLite, orquestrador (máquina de estados), auth, contatos |
| `agentes/` | cérebro LLM (com fallback determinístico) |
| `revisor/` | Revisor (fail-closed) de toda mensagem ao lead |
| `transporte/` | WhatsApp Business Cloud |
| `ontologia/` | catálogo de cursos JSON-LD + SHACL + serviço de consulta + Injetor |
| `growth/` | Growth Engine, LPs no WordPress, CAPI, funil, PDF do guia |
| `coleta/` | coleta e robô de inscrição na Extecamp |
| `ops/` | deploy, backup, scripts de manutenção, monitor de recursos |
| `tests/` | testes por área (`python3 atena/tests/test_<area>.py`) |
