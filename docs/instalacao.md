# Instalar o servidor do app de corrida (teste fechado)

## 0. Leia primeiro: o que isto é e o que não é

Este guia coloca o servidor num computador na internet, com endereço seguro (HTTPS), para um **teste fechado**: poucas pessoas que
você conhece, usando os dois apps no celular de verdade.

**Não é o lançamento.** Enquanto o plano 7 não existe (precisa de CNPJ e advogado), o Pix, o mapa e o código de login por WhatsApp
são **de mentira**. Por isso:

- **Nenhum dinheiro de verdade passa por aqui.** Corrida em dinheiro funciona; o Pix de mentira só "paga" por uma rota de
  desenvolvimento que fica fechada (veja o passo 11).
- **Não divulgue o endereço.** Qualquer pessoa que o conheça consegue criar conta.
- **O código de login você lê no registro do servidor** (`journalctl`, passo 6) e passa para a pessoa, no lugar do WhatsApp.
- **Foto de documento é dado pessoal (LGPD).** No teste, use só gente que concordou, ou documentos de mentira. O prazo certo de guarda
  das fotos e dos backups é pergunta para o advogado.

O servidor se recusa a ligar fora do modo de teste (`APP_MODE=dev`) até o plano 7 existir; isso é de propósito.

## O que você vai precisar

- Um servidor (uma "VPS"): Ubuntu 24.04, 2 GB de memória e 20 GB de disco bastam para um teste. Qualquer provedor serve; anote o
  **número IP** dele.
- Um domínio ou subdomínio para o servidor, por exemplo `corrida.seudominio.com.br`.
- Uns 60 minutos e um terminal no seu computador (os comandos abaixo são para colar lá).

Em todos os passos, `corrida.seudominio.com.br` e `IP` são os seus: troque.

## Passo 1. Apontar o domínio para o servidor

No painel de quem registra o seu domínio, crie um registro **A**: nome `corrida`, valor = o IP do servidor.
Conferir (pode levar alguns minutos):

    dig +short corrida.seudominio.com.br        # tem de mostrar o IP do servidor

## Passo 2. Preparar a máquina

Entre no servidor (`ssh root@IP`) e rode, uma parte de cada vez.

**Programas:**

    apt update && apt upgrade -y
    apt install -y postgresql redis-server python3-venv git ufw curl dnsutils

(O código de hoje não usa PostGIS: não precisa instalar.)

**Caddy** (é ele que cuida do HTTPS e do certificado, de graça e sozinho). Siga a instalação oficial para Ubuntu em
<https://caddyserver.com/docs/install#debian-ubuntu-raspbian>; no fim, `caddy version` tem de responder.

**Firewall** (só entra SSH, site e site seguro). Rode as três linhas nesta ordem; se trocar, você pode se trancar para fora:

    ufw allow OpenSSH
    ufw allow 80/tcp && ufw allow 443/tcp
    ufw --force enable

**Redis** (guarda posições e limites; já escuta só dentro da máquina). Ligue a gravação em disco para não perder as marcas se ele reiniciar:

    sed -i 's/^appendonly no/appendonly yes/' /etc/redis/redis.conf && systemctl restart redis-server
    redis-cli config get bind                  # tem de mostrar só 127.0.0.1 (e/ou ::1)

**Banco:** crie o usuário e o banco. Anote a senha que sair do `openssl`; você vai usar no passo 4.

    openssl rand -hex 16
    sudo -u postgres psql -c "CREATE USER corrida WITH PASSWORD 'COLE-AQUI-A-SENHA';" -c "CREATE DATABASE corrida OWNER corrida;"

**Usuário do serviço e pastas** (o servidor roda como um usuário comum, sem poderes):

    adduser --system --group --no-create-home corrida
    install -d -o corrida -g corrida -m 700 /var/lib/app-corrida /var/lib/app-corrida/uploads /var/backups/app-corrida
    install -d -m 755 /etc/app-corrida

## Passo 3. Baixar o código e instalar

O código fica em `/opt/app-corrida`, dono `root`: o serviço só lê, não consegue mexer no próprio código.
Como o repositório do GitHub é seu e privado, o servidor precisa de uma chave de **só leitura**:

    ssh-keygen -t ed25519 -f /root/.ssh/deploy_corrida -N ""
    cat /root/.ssh/deploy_corrida.pub

Copie a linha que apareceu e cole no GitHub: o repositório → **Settings → Deploy keys → Add deploy key** (deixe "Allow write access"
**desmarcado**). Depois:

    GIT_SSH_COMMAND="ssh -i /root/.ssh/deploy_corrida -o IdentitiesOnly=yes" git clone git@github.com:LevySA15/appdecorridas.git /opt/app-corrida
    git -C /opt/app-corrida config core.sshCommand "ssh -i /root/.ssh/deploy_corrida -o IdentitiesOnly=yes"
    cd /opt/app-corrida/server
    python3 -m venv .venv
    .venv/bin/pip install -q "sqlalchemy>=2.0" "psycopg[binary]>=3.2" "alembic>=1.13" "redis>=5.0" tzdata "fastapi>=0.115" "uvicorn[standard]>=0.30"

## Passo 4. Configurar

Copie o modelo (`server/deploy/app.env.example`) e troque o que começa com `TROQUE`:

    install -m 640 -o root -g corrida /opt/app-corrida/server/deploy/app.env.example /etc/app-corrida/app.env
    nano /etc/app-corrida/app.env

- `DATABASE_URL`: troque `TROQUE-A-SENHA-DO-BANCO` pela senha do passo 2.
- `WEBHOOK_SECRET`: rode `openssl rand -hex 32` e cole o resultado.
- **Não mude** `APP_MODE=dev` nem `DEV_ROUTES=off`. O segundo é o que esconde as rotas que entregam o código de login e a documentação.

Conferir que não sobrou nada para trocar (não pode aparecer linha nenhuma):

    grep TROQUE /etc/app-corrida/app.env | grep -v '^#'

Esse arquivo tem a senha do banco: nunca o envie para o GitHub nem para ninguém.

## Passo 5. Ligar o servidor e o Caddy

    cp /opt/app-corrida/server/deploy/app-corrida.service /opt/app-corrida/server/deploy/app-corrida-backup.service /opt/app-corrida/server/deploy/app-corrida-backup.timer /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable --now app-corrida
    journalctl -u app-corrida -n 30 --no-pager        # tem de acabar em "Application startup complete."
    curl http://127.0.0.1:8000/health                 # {"status":"ok"}

Ao subir, o serviço já aplica sozinho as mudanças do banco (`alembic upgrade head`).

Agora o Caddy, dizendo qual é o domínio (`server/deploy/Caddyfile` usa a variável `APP_DOMAIN`):

    mkdir -p /etc/systemd/system/caddy.service.d
    printf '[Service]\nEnvironment=APP_DOMAIN=corrida.seudominio.com.br\n' > /etc/systemd/system/caddy.service.d/dominio.conf
    cp /opt/app-corrida/server/deploy/Caddyfile /etc/caddy/Caddyfile
    systemctl daemon-reload && systemctl restart caddy
    journalctl -u caddy -n 30 --no-pager              # procure "certificate obtained successfully"

Se o certificado não sair, quase sempre é o passo 1 (domínio ainda não aponta para o IP) ou o firewall (portas 80 e 443).

## Passo 6. Conferir

    curl https://corrida.seudominio.com.br/health                                    # {"status":"ok"}
    curl -s -o /dev/null -w '%{http_code}\n' https://corrida.seudominio.com.br/docs  # 404 (fechado de propósito)
    curl -s -o /dev/null -w '%{http_code}\n' https://corrida.seudominio.com.br/v1/dev/audit   # 404

**Criar o administrador (você):**

    (set -a; . /etc/app-corrida/app.env; set +a; cd /opt/app-corrida/server && .venv/bin/python -m app.cli create-admin --phone "75 99999-0000" --name "Levy")

**Entrar no painel:** abra `https://corrida.seudominio.com.br/painel/`, digite o telefone e peça o código. Em outra janela do
terminal, deixe o registro aberto:

    journalctl -u app-corrida -f

O código aparece numa linha assim: `app.otp: código de login de +5575999990000: 116815`. É assim também que você passa o código
para cada pessoa do teste. (Um número de administrador não pode ser usado como passageiro nem motoqueiro.)

## Passo 7. Gerar os apps apontando para o servidor

No **seu computador**, em cada app (o endereço precisa ser `https://`; o app de release se recusa a abrir com `http://`):

    cd mobile/apps/passenger && flutter build apk --release --dart-define=API_URL=https://corrida.seudominio.com.br
    cd ../rider && flutter build apk --release --dart-define=API_URL=https://corrida.seudominio.com.br

O arquivo fica em `build/app/outputs/flutter-apk/app-release.apk` de cada app. Mande para os celulares do teste (o Android pede para
permitir "instalar apps de fontes desconhecidas"). Mais detalhes em `mobile/README.md`.

## Passo 8. Backup diário e o ensaio de restauração

O backup do banco e das fotos roda todo dia às 03:30 (`server/deploy/backup.sh`). Ligue e teste uma vez agora:

    systemctl enable --now app-corrida-backup.timer
    systemctl start app-corrida-backup
    ls -l /var/backups/app-corrida                    # um db-AAAAMMDD-HHMMSS.dump (e um uploads-... se já houver fotos)

Ficam 14 dias do banco e 7 das fotos (você muda em `/etc/app-corrida/app.env`). Backup com cara de bom que nunca foi restaurado não
vale nada, então faça agora o **ensaio**: restaurar num banco de teste, sem mexer no de verdade.

    sudo -u postgres createdb -O corrida corrida_ensaio
    sudo -u corrida bash -c 'set -a; . /etc/app-corrida/app.env; set +a; DATABASE_URL="${DATABASE_URL%/*}/corrida_ensaio" /opt/app-corrida/server/deploy/restore.sh db "$(ls -t /var/backups/app-corrida/db-*.dump | head -1)"'
    sudo -u postgres psql corrida_ensaio -c "select count(*) from users"       # compare com o mesmo comando no banco "corrida"
    sudo -u postgres dropdb corrida_ensaio

**Atenção:** a cópia fica na mesma máquina. Se o disco do servidor morrer, o backup morre junto. Traga uma cópia para o seu
computador de vez em quando (guarde em lugar seguro, são dados pessoais):

    rsync -a root@IP:/var/backups/app-corrida/ ~/backups-corrida/

**Para restaurar de verdade** (servidor novo ou banco estragado), com o serviço parado e o banco vazio:

    systemctl stop app-corrida
    sudo -u postgres dropdb corrida && sudo -u postgres createdb -O corrida corrida
    sudo -u corrida bash -c 'set -a; . /etc/app-corrida/app.env; set +a; /opt/app-corrida/server/deploy/restore.sh db /var/backups/app-corrida/db-AAAAMMDD-HHMMSS.dump'
    sudo -u corrida bash -c 'set -a; . /etc/app-corrida/app.env; set +a; /opt/app-corrida/server/deploy/restore.sh uploads /var/backups/app-corrida/uploads-AAAAMMDD-HHMMSS.tar.gz'
    systemctl start app-corrida

O `restore.sh` **recusa** restaurar por cima de um banco ou de uma pasta que já tem dados; só com `--substituir` ele apaga o que estiver lá.
Se você restaurar um backup antigo, fotos que já tinham sido apagadas pela limpeza da LGPD voltam, e a limpeza diária do servidor as apaga de novo.

## Passo 9. Atualizar o servidor

    systemctl start app-corrida-backup                                # sempre um backup antes
    git -C /opt/app-corrida pull
    systemctl restart app-corrida                                      # aplica as mudanças do banco sozinho
    journalctl -u app-corrida -n 20 --no-pager                         # "Application startup complete."

Se o `pull` trouxer um programa novo na lista do passo 3 (vai estar dito na mudança), rode também o `pip install` de lá.

## Passo 10. Se algo der errado

| O que você vê | O que olhar |
|---|---|
| O site não abre ou o navegador reclama do certificado | `journalctl -u caddy -n 50 --no-pager`; o domínio aponta para o IP (`dig`)? `ufw status` mostra 80 e 443? |
| Erro 502 | o servidor caiu: `systemctl status app-corrida` e `journalctl -u app-corrida -n 50 --no-pager` |
| O servidor não sobe depois de atualizar | quase sempre a mudança do banco: o motivo está no registro. Volte o código com `git -C /opt/app-corrida checkout COMMIT-ANTERIOR` e `systemctl restart app-corrida`; se o banco já mudou, restaure o backup do passo 9 |
| Não chega o código de login | ele **não** vai por mensagem: está no `journalctl -u app-corrida -f` |
| O backup falhou | `systemctl status app-corrida-backup` e `journalctl -u app-corrida-backup -n 30 --no-pager`; confira `df -h` (disco cheio) |

## Passo 11. (Opcional) Testar o Pix de mentira

O Pix de mentira só fica "pago" por uma rota de desenvolvimento, que está desligada (`DEV_ROUTES=off`) e fechada no Caddy. Para usar
na sua máquina, sem abrir para a internet: no servidor, troque para `DEV_ROUTES=on` em `/etc/app-corrida/app.env` e rode
`systemctl restart app-corrida`; no seu computador, abra um túnel e chame a rota por ele:

    ssh -L 8001:127.0.0.1:8000 root@IP
    curl -X POST http://localhost:8001/v1/dev/pix/ID-DA-COBRANCA/pay

Quando terminar, volte para `DEV_ROUTES=off` e reinicie.

## Onde fica cada coisa

| O que | Onde |
|---|---|
| Código do servidor | `/opt/app-corrida/server` |
| Configuração (com senhas) | `/etc/app-corrida/app.env` |
| Fotos dos documentos | `/var/lib/app-corrida/uploads` |
| Backups | `/var/backups/app-corrida` |
| Registro do servidor / do Caddy / do backup | `journalctl -u app-corrida` / `-u caddy` / `-u app-corrida-backup` |
| Modelos de tudo isto | `server/deploy/` |

## Antes de abrir para o público

**Não abra enquanto isto não estiver pronto:**

1. Plano 7: Pix, mapa e código por WhatsApp de verdade (precisa de CNPJ e do advogado), com `APP_MODE` trocado para o modo real.
2. Advogado: prazos de guarda e aviso de privacidade e termos de uso. Hoje o servidor apaga a foto de um cadastro recusado depois de 30 dias e a foto enviada e nunca usada depois de 24 horas; os backups ficam 14 dias (banco) e 7 dias (fotos). São valores meus, para o advogado conferir.
3. Cópia dos backups para fora da máquina feita automaticamente.
4. Alguém olhando o `/health` de fora (um serviço de monitoramento) e avisando quando cair.
5. Contato de suporte nas telas de bloqueio dos apps.
