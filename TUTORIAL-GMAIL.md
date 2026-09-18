# Ligar a leitura automática do código (OTP) pelo Gmail

Quando o Santander pede o código de 6 dígitos, o bot pode **ler o e-mail
sozinho** em vez de você digitar. Para isso ele precisa de uma autorização do
Google — feita uma vez, por máquina.

Leva ~10 minutos. É de graça.

> O bot só **lê** e-mails do remetente `santander@santander.com.br` chegados
> nos últimos minutos, e marca esse e-mail como lido. Ele não manda e-mail,
> não apaga nada e não olha o resto da sua caixa.

---

## 1. Criar o projeto no Google Cloud

1. Entre em **https://console.cloud.google.com/** com a conta de e-mail **que
   recebe os códigos do Santander**.
2. No topo, no seletor de projeto, clique em **Novo projeto**.
3. Nome: `Arqueiro OTP` (ou o que preferir) → **Criar**.
4. Espere criar e **selecione esse projeto** no seletor do topo.

## 2. Ativar a API do Gmail

1. Menu ☰ → **APIs e serviços** → **Biblioteca**.
2. Busque por **Gmail API** → abra → **Ativar**.

## 3. Configurar a tela de consentimento

1. Menu ☰ → **APIs e serviços** → **Tela de permissão OAuth**.
2. Tipo de usuário: **Externo** → **Criar**.
3. Preencha só o obrigatório:
   - Nome do app: `Arqueiro`
   - E-mail de suporte: o seu
   - E-mail do desenvolvedor: o seu
4. **Salvar e continuar**.
5. Em *Escopos*, não precisa adicionar nada → **Salvar e continuar**.
6. Em **Usuários de teste**, clique em **+ Add users** e adicione **o seu
   próprio e-mail**. Sem isso o Google recusa o login com
   *"app não verificado"*.
7. **Salvar e continuar** → **Voltar ao painel**.

> Deixe o app em **Teste**. Não precisa publicar nem passar por verificação:
> usuários de teste funcionam normalmente.

## 4. Criar a credencial (o arquivo que o bot usa)

1. Menu ☰ → **APIs e serviços** → **Credenciais**.
2. **+ Criar credenciais** → **ID do cliente OAuth**.
3. Tipo de aplicativo: **App para computador** (Desktop app).
4. Nome: `Arqueiro` → **Criar**.
5. Na janela que aparece, clique em **Fazer o download do JSON**.

## 5. Colocar o arquivo no lugar

1. Renomeie o arquivo baixado para **`credentials.json`**.
2. Coloque-o **na pasta do bot** (a mesma pasta do `bot.py`).
3. Abra o Arqueiro → aba **Configurações** → **Autorizar Gmail**.
4. O navegador abre pedindo permissão:
   - escolha a conta que recebe os códigos;
   - se aparecer *"O Google não verificou este app"*, clique em
     **Avançado → Acessar Arqueiro (não seguro)** — é o seu próprio app;
   - marque a permissão e confirme.
5. Pronto: o bot cria o `token_gmail.json` e, a partir daí, entra sozinho.

---

## Conferindo se funcionou

Na aba **Configurações** do Arqueiro, o estado do Gmail deve ficar:

```
credentials.json: encontrado
token_gmail.json: autorizado
```

Quando o portal pedir o código, o log mostra:

```
🔍 Buscando o código no Gmail...
✓ Código encontrado no Gmail.
```

Se nada aparecer em ~85 segundos, o bot volta para o modo manual e você digita
o código nos seis quadradinhos da barra lateral. **O automático nunca impede o
manual.**

---

## Problemas comuns

| O que aparece | O que é | O que fazer |
|---|---|---|
| `Arquivo 'credentials.json' nao encontrado` | O arquivo não está na pasta do `bot.py`, ou o bot foi aberto de outra pasta | Copie o `credentials.json` para a pasta do bot e reabra |
| `access_denied` no navegador | Seu e-mail não está em **Usuários de teste** | Passo 3.6 |
| "App não verificado" e não deixa passar | Faltou clicar em *Avançado* | Passo 5.4 |
| Autorizou, mas não acha o código | O e-mail chegou de outro remetente, ou antes da tela do código aparecer | O bot procura e-mails de `santander@santander.com.br` dos últimos 5 minutos — lidos ou não. Se o assunto não trouxer o código, ele lê o corpo |
| `invalid_grant` depois de semanas | O token de app em modo *Teste* expira em 7 dias sem uso | Apague `token_gmail.json` e clique em **Autorizar Gmail** de novo |

## Segurança

- `credentials.json` e `token_gmail.json` **não vão para o Git** (já estão no
  `.gitignore`) e não entram no instalador. São arquivos daquela máquina.
- Quem tiver esses dois arquivos consegue ler os e-mails autorizados: trate-os
  como senha.
- Para revogar: **https://myaccount.google.com/permissions** → *Arqueiro* →
  **Remover acesso**.
