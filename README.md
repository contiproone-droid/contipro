# CRM de Perfis — AdsPower / Facebook / WhatsApp Business Manager

CRM interno para gerenciar o ciclo de vida de perfis usados no **AdsPower** para
criação de contas **Facebook Business Manager**, desde a criação do perfil até
o Business Manager ativo, passando por login, verificação/criação de página e
vínculo do WhatsApp.

## Stack

- **Backend:** Django 6
- **Banco de dados:** PostgreSQL hospedado no [Neon](https://neon.tech) (via `DATABASE_URL`)
- **Deploy:** [Render](https://render.com) (Web Service)
- **Arquivos estáticos:** WhiteNoise
- **Campos sensíveis:** criptografados com `django-encrypted-model-fields` (Fernet)

> **Nota sobre criptografia:** o pedido original citava `django-cryptography`
> ou `django-fernet-fields`. Ambas as bibliotecas estão sem manutenção e
> quebram em versões atuais do Django (usam `django.utils.baseconv`, removido
> há tempos). Optei por `django-encrypted-model-fields`, que é mantida, usa a
> mesma ideia (Fernet + `FIELD_ENCRYPTION_KEY`) e é literalmente a mesma
> variável de ambiente pedida.

## Fluxo de fases

1. Perfil criado no AdsPower
2. Login/acesso ao perfil no Facebook
3. Verificação de página do Facebook
4. Criação da página (se necessário)
5. Vínculo da conta do WhatsApp
6. Geração do Business Manager
7. Concluído / Ativo

Cada avanço de fase é feito pelo botão **"Avançar fase"** na página de detalhe
do perfil, e é automaticamente registrado em `PhaseHistory` (usuário, data/hora
e observação opcional) para fins de auditoria. O campo de fase **não** é
editável diretamente no formulário, exatamente para preservar esse histórico.

## Modelos

- **Profile** — dados do perfil, credenciais criptografadas, fase e status.
- **PhaseHistory** — auditoria de mudanças de fase.
- **PageInfo** — página do Facebook vinculada ao perfil (1 perfil → N páginas).
- **WhatsAppLink** — número(s) de WhatsApp vinculado(s) ao perfil.
- **BusinessManager** — Business Manager gerado (1 para 1 com o perfil).

---

## Rodando localmente

Pré-requisitos: Python 3.11+.

```bash
# 1. Criar e ativar o ambiente virtual
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Copiar o arquivo de variáveis de ambiente
cp .env.example .env
```

Edite o `.env` e gere pelo menos a `SECRET_KEY` e a `FIELD_ENCRYPTION_KEY`
(veja abaixo como gerar cada uma). Sem `DATABASE_URL` definida, o projeto usa
**SQLite** automaticamente — ótimo para desenvolvimento local.

```bash
# 4. Rodar migrações
python manage.py migrate

# 5. Criar um usuário para acessar o sistema
python manage.py createsuperuser

# 6. Subir o servidor
python manage.py runserver
```

Acesse `http://127.0.0.1:8000/` para o dashboard (pede login) e
`http://127.0.0.1:8000/admin/` para o Django Admin.

### Gerando a `SECRET_KEY`

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Gerando a `FIELD_ENCRYPTION_KEY`

Esta é a chave que criptografa a senha e os dados de autenticação adicional
de cada perfil. **Guarde-a em local seguro** (ex: gerenciador de senhas) — se
ela for perdida ou trocada, os dados já salvos no banco não poderão mais ser
descriptografados.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

ou, usando o comando do próprio pacote (com o app já instalado):

```bash
python manage.py generate_encryption_key
```

Cole o valor gerado em `FIELD_ENCRYPTION_KEY` no `.env`.

---

## Configurando o banco no Neon

1. Crie uma conta em [neon.tech](https://neon.tech) e um novo projeto/banco.
2. No painel do Neon, copie a **connection string** (formato
   `postgresql://usuario:senha@host/nomedobanco?sslmode=require`). O Neon já
   inclui `sslmode=require`, então não é necessário configurar SSL manualmente.
3. Cole essa string na variável `DATABASE_URL` (no `.env` local ou nas
   variáveis de ambiente do Render em produção).
4. Rode as migrações apontando para o Neon (ambiente com `DATABASE_URL`
   definida):
   ```bash
   python manage.py migrate
   ```

O projeto usa `dj-database-url` para interpretar essa string automaticamente
— não é preciso configurar host/porta/usuário manualmente em `settings.py`.

---

## Deploy no Render

### 1. Subir o código no GitHub

```bash
git init
git add .
git commit -m "CRM de perfis inicial"
git branch -M main
git remote add origin <url-do-seu-repositorio>
git push -u origin main
```

### 2. Conectar o repositório do GitHub ao Render

1. Acesse [dashboard.render.com](https://dashboard.render.com) → **New +** → **Web Service**.
2. Conecte sua conta do GitHub e selecione este repositório.
3. Se o Render detectar o `render.yaml`, ele já preenche a maior parte da
   configuração automaticamente (Blueprint). Caso prefira configurar na mão:
   - **Runtime:** Python 3
   - **Build Command:** `./build.sh`
   - **Start Command:** `gunicorn config.wsgi:application`

### 3. Configurar as variáveis de ambiente no Render

Na aba **Environment** do serviço, defina:

| Variável | Valor |
|---|---|
| `SECRET_KEY` | gerada (ou deixe o Render gerar automaticamente) |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `.onrender.com` (ou o domínio customizado que usar) |
| `CSRF_TRUSTED_ORIGINS` | `https://*.onrender.com` |
| `DATABASE_URL` | connection string do Neon |
| `FIELD_ENCRYPTION_KEY` | a chave Fernet gerada (guarde uma cópia fora do Render também) |

Se usar o `render.yaml` incluso, `SECRET_KEY` é gerada automaticamente e
`DEBUG`/`ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` já vêm preenchidos — só é
preciso completar `DATABASE_URL` e `FIELD_ENCRYPTION_KEY` manualmente (foram
deixadas como `sync: false` de propósito, por serem segredos).

### 4. Deploy

Clique em **Create Web Service** (ou **Apply** no Blueprint). O Render vai
rodar `build.sh` (instala dependências, coleta estáticos via WhiteNoise e
aplica as migrações) e depois iniciar o Gunicorn.

Depois do primeiro deploy, crie um superusuário para acessar o admin/sistema
via o shell do Render (aba **Shell** do serviço):

```bash
python manage.py createsuperuser
```

---

## ⚠️ Aviso de segurança

- **Nunca** commite o arquivo `.env` — ele contém `SECRET_KEY`, a connection
  string do banco e a `FIELD_ENCRYPTION_KEY`. O `.gitignore` já bloqueia isso,
  mas cuidado ao forçar `git add`.
- Guarde a `FIELD_ENCRYPTION_KEY` em um cofre de senhas/segredos separado do
  código. Perder essa chave torna os dados criptografados (senhas, códigos de
  backup) irrecuperáveis.
- Em produção, mantenha `DEBUG=False` — com `DEBUG=True` o Django expõe
  variáveis de ambiente e stack traces detalhados em caso de erro.
- As senhas dos perfis nunca são exibidas em texto puro nas telas do CRM; o
  formulário de edição sempre pede a senha em branco por padrão ("deixe em
  branco para manter a senha atual").

---

## Estrutura do projeto

```
config/          # settings, urls, wsgi/asgi do projeto Django
profiles/        # app principal: models, views, forms, admin, urls
templates/        # templates HTML (base + telas do app profiles)
build.sh          # script de build usado pelo Render
render.yaml        # definição do Web Service para o Render (Blueprint)
requirements.txt    # dependências Python
.env.example       # variáveis de ambiente necessárias (copie para .env)
```
