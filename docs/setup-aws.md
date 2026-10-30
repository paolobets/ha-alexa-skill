# Installazione della Lambda su AWS

La Lambda è il ponte tra la skill Alexa e Home Assistant (HA): riceve le
direttive di Alexa e le inoltra alla vista `/api/alexa_bridge/smart_home`
dell'integrazione. Si pubblica con AWS SAM nella regione **`eu-west-1`**
(Irlanda): l'italiano usa l'endpoint Alexa "Europe".

Nei comandi, `<HA_URL>` è l'indirizzo pubblico di HA (https, senza `/` finale)
e `<SKILL_ID>` è l'ID della skill (`amzn1.ask.skill.<...>`, vedi
[setup-skill.md](setup-skill.md)).

## 1. Strumenti su Windows

Servono l'AWS CLI e la SAM CLI. Con `winget` (PowerShell):

```powershell
winget install -e --id Amazon.AWSCLI
winget install -e --id Amazon.SAM-CLI
```

Chiudi e riapri il terminale, poi verifica:

```powershell
aws --version
sam --version
```

La funzione usa solo la libreria standard di Python, quindi `sam build` non
richiede Docker.

## 2. Utente IAM di deploy a privilegi minimi

Non usare l'utente root né un amministratore. Nella console AWS (IAM):

1. Crea un utente, ad esempio `ha-alexa-deploy`, **senza** accesso alla console.
2. Crea una policy con i permessi sotto e assegnala all'utente.
3. Crea una chiave di accesso (caso d'uso "Command Line Interface").

Permessi necessari, in sintesi:

| Area | Perché |
|---|---|
| CloudFormation | SAM crea e aggiorna lo stack |
| Lambda | creare/aggiornare la funzione e il permesso per Alexa |
| IAM (ruolo dello stack) | SAM crea il ruolo di esecuzione della funzione: `CreateRole`, `AttachRolePolicy`, `PutRolePolicy`, `PassRole`, `DeleteRole` ecc., **limitati ai ruoli dello stack** |
| S3 | SAM carica il pacchetto in un bucket di artefatti |

Esempio di policy. Descrive l'idea, **non è garantita esatta**: se il deploy
fallisce con `AccessDenied`, aggiungi solo l'azione mancante. Sostituisci
`<ACCOUNT_ID>` con l'id del tuo account AWS e `<STACK_NAME>` con il nome dello
stack (lo stesso che darai a `sam deploy`).

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "StackCloudFormation",
      "Effect": "Allow",
      "Action": [
        "cloudformation:CreateStack", "cloudformation:UpdateStack",
        "cloudformation:DeleteStack", "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents", "cloudformation:GetTemplateSummary",
        "cloudformation:CreateChangeSet", "cloudformation:DescribeChangeSet",
        "cloudformation:ExecuteChangeSet", "cloudformation:DeleteChangeSet",
        "cloudformation:ListStackResources"
      ],
      "Resource": [
        "arn:aws:cloudformation:eu-west-1:<ACCOUNT_ID>:stack/<STACK_NAME>/*",
        "arn:aws:cloudformation:eu-west-1:<ACCOUNT_ID>:stack/aws-sam-cli-managed-default/*",
        "arn:aws:cloudformation:eu-west-1:aws:transform/Serverless-2016-10-31"
      ]
    },
    {
      "Sid": "StackLambda",
      "Effect": "Allow",
      "Action": [
        "lambda:CreateFunction", "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration", "lambda:DeleteFunction",
        "lambda:GetFunction", "lambda:GetFunctionConfiguration",
        "lambda:AddPermission", "lambda:RemovePermission",
        "lambda:TagResource", "lambda:ListTags"
      ],
      "Resource": "arn:aws:lambda:eu-west-1:<ACCOUNT_ID>:function:<STACK_NAME>-*"
    },
    {
      "Sid": "StackRoles",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:PassRole",
        "iam:AttachRolePolicy", "iam:DetachRolePolicy",
        "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy",
        "iam:TagRole"
      ],
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/<STACK_NAME>-*"
    },
    {
      "Sid": "SamArtifactsBucket",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket", "s3:PutBucketVersioning", "s3:PutBucketPolicy",
        "s3:PutEncryptionConfiguration", "s3:PutBucketPublicAccessBlock",
        "s3:GetBucketLocation", "s3:ListBucket",
        "s3:GetObject", "s3:PutObject"
      ],
      "Resource": [
        "arn:aws:s3:::aws-sam-cli-managed-default-*",
        "arn:aws:s3:::aws-sam-cli-managed-default-*/*"
      ]
    }
  ]
}
```

Note:

- **Il bucket S3 lo crea SAM** la prima volta, con `sam deploy --guided`: si
  chiama `aws-sam-cli-managed-default-...` ed è il motivo del blocco
  `SamArtifactsBucket`. In alternativa crealo tu e indicalo con `--s3-bucket`,
  restringendo la policy a quel bucket.
- I nomi delle risorse create da CloudFormation iniziano con il nome dello stack,
  per questo i `Resource` usano `<STACK_NAME>-*`.
- Non dare mai `AdministratorAccess` a questo utente.
- Le chiavi di accesso sono segreti: non incollarle in chat, nel repo o in
  issue. Si inseriscono solo con `aws configure` (passo successivo).

## 3. Profilo AWS CLI

```powershell
aws configure --profile ha-alexa
```

Inserisci chiave di accesso, chiave segreta, regione `eu-west-1`, formato `json`.
Verifica:

```powershell
aws sts get-caller-identity --profile ha-alexa
```

## 4. Build e deploy

Dalla radice del repository:

```powershell
cd lambda
sam validate --lint --region eu-west-1
sam build
sam deploy --guided --region eu-west-1 --profile ha-alexa
```

Risposte alla procedura guidata:

- **Stack Name**: ad esempio `ha-alexa-bridge` (lo stesso di `<STACK_NAME>` nella policy)
- **AWS Region**: `eu-west-1`
- **Parameter BaseUrl**: `<HA_URL>`
- **Parameter SkillId**: `<SKILL_ID>`
- **Allow SAM CLI IAM role creation**: `Y`
- **Save arguments to samconfig.toml**: `Y`

`samconfig.toml` contiene i tuoi valori reali ed è **ignorato da git**: non
rimuoverlo da `.gitignore`.

Se non hai ancora lo Skill ID, crea prima la skill senza endpoint
([setup-skill.md](setup-skill.md), passo 1) e copia l'ID.

## 5. Copia l'ARN

A fine deploy, nelle `Outputs`, trovi `FunctionArn`
(`arn:aws:lambda:eu-west-1:<ACCOUNT_ID>:function:<...>`): è l'**ARN** da
incollare come endpoint della skill. Per rivederlo:

```powershell
aws cloudformation describe-stacks --stack-name <STACK_NAME> --region eu-west-1 --profile ha-alexa --query "Stacks[0].Outputs"
```

Il template concede ad Alexa il permesso di invocare la funzione come trigger
**Alexa Smart Home** (principal `alexa-connectedhome.amazon.com`), limitato al
tuo Skill ID: non serve configurare il trigger a mano nella console Lambda.

## 6. Aggiornamenti e rimozione

- Aggiornare il codice: `sam build` e `sam deploy` (usa `samconfig.toml`).
- Rimuovere tutto: `sam delete --stack-name <STACK_NAME> --region eu-west-1 --profile ha-alexa`.

## 7. Variabili di prova (solo collaudo)

`DEBUG` e `LONG_LIVED_ACCESS_TOKEN` **non** sono nel template: si aggiungono a
mano per la prova del collaudo e a mano si tolgono. `sam deploy` non le
rimuove (CloudFormation non tocca ciò che non ha impostato lui), quindi non
contare su un nuovo deploy per la pulizia.

Attenzione: `aws lambda update-function-configuration --environment`
**sostituisce l'intero insieme** di variabili. Ogni comando sotto riscrive
quindi anche `BASE_URL` e `HA_PATH`: se le dimentichi, la Lambda smette di
funzionare.

`<FUNCTION_NAME>` è il nome della funzione, cioè l'ultima parte di
`FunctionArn` (passo 5); va bene anche l'ARN intero. I file si creano in
`%TEMP%`, **fuori dal repository**, perché uno contiene il token.

### 7.1 Situazione di partenza

```powershell
aws lambda get-function-configuration --function-name <FUNCTION_NAME> --profile ha-alexa --region eu-west-1 --query Environment
```

Devono comparire solo `BASE_URL` (uguale a `<HA_URL>`) e `HA_PATH`.

### 7.2 Aggiungere le variabili di prova

1. In HA crea un token di prova: profilo utente > Sicurezza > *Token di accesso
   a lunga durata*, nome ad esempio `alexa-collaudo`. Copialo.
2. Crea il file con Blocco note, così il token non resta nella cronologia
   della shell:

   ```powershell
   notepad "$env:TEMP\ha-alexa-env-test.json"
   ```

   Contenuto (sostituisci i segnaposto, salva e chiudi):

   ```json
   {
     "Variables": {
       "BASE_URL": "<HA_URL>",
       "HA_PATH": "/api/alexa_bridge/smart_home",
       "DEBUG": "true",
       "LONG_LIVED_ACCESS_TOKEN": "<TOKEN>"
     }
   }
   ```

3. Applica, attendi la fine dell'aggiornamento e cancella il file:

   ```powershell
   aws lambda update-function-configuration --function-name <FUNCTION_NAME> --profile ha-alexa --region eu-west-1 --environment "file://$env:TEMP\ha-alexa-env-test.json" --query "Environment.Variables | keys(@)"
   aws lambda wait function-updated --function-name <FUNCTION_NAME> --profile ha-alexa --region eu-west-1
   Remove-Item "$env:TEMP\ha-alexa-env-test.json"
   ```

   La prima riga stampa solo i **nomi** delle variabili (non il token): devono
   essere `BASE_URL`, `HA_PATH`, `DEBUG`, `LONG_LIVED_ACCESS_TOKEN`.

### 7.3 Evento di prova Discover

L'evento **non** contiene un token: così la Lambda usa quello di prova.

```powershell
notepad "$env:TEMP\ha-alexa-discover.json"
```

Contenuto:

```json
{
  "directive": {
    "header": {
      "namespace": "Alexa.Discovery",
      "name": "Discover",
      "payloadVersion": "3",
      "messageId": "00000000-0000-0000-0000-000000000001"
    },
    "payload": {}
  }
}
```

Invoca la funzione e leggi la risposta:

```powershell
aws lambda invoke --function-name <FUNCTION_NAME> --profile ha-alexa --region eu-west-1 --payload "fileb://$env:TEMP\ha-alexa-discover.json" "$env:TEMP\ha-alexa-discover-out.json"
Get-Content "$env:TEMP\ha-alexa-discover-out.json"
```

La risposta è un `Discover.Response` con un elemento in `endpoints` per ogni
entità condivisa. Un `ErrorResponse` indica il problema nel campo `type`
(ad esempio `INVALID_AUTHORIZATION_CREDENTIAL`: token errato o variabili non
applicate). I log sono in CloudWatch, gruppo `/aws/lambda/<FUNCTION_NAME>`.

### 7.4 Togliere le variabili di prova

Subito dopo la prova. Il file contiene solo le due variabili del template:

```powershell
notepad "$env:TEMP\ha-alexa-env-base.json"
```

```json
{
  "Variables": {
    "BASE_URL": "<HA_URL>",
    "HA_PATH": "/api/alexa_bridge/smart_home"
  }
}
```

```powershell
aws lambda update-function-configuration --function-name <FUNCTION_NAME> --profile ha-alexa --region eu-west-1 --environment "file://$env:TEMP\ha-alexa-env-base.json" --query Environment
aws lambda wait function-updated --function-name <FUNCTION_NAME> --profile ha-alexa --region eu-west-1
aws lambda get-function-configuration --function-name <FUNCTION_NAME> --profile ha-alexa --region eu-west-1 --query Environment
Remove-Item "$env:TEMP\ha-alexa-env-base.json", "$env:TEMP\ha-alexa-discover.json", "$env:TEMP\ha-alexa-discover-out.json"
```

L'ultima `get-function-configuration` deve mostrare **solo** `BASE_URL` e
`HA_PATH`. Poi **revoca il token** in HA: profilo utente > Sicurezza > token
`alexa-collaudo` > Elimina.

## Variabili d'ambiente della funzione

| Variabile | Uso |
|---|---|
| `BASE_URL` | URL di HA, senza `/` finale (impostata dal parametro `BaseUrl`) |
| `HA_PATH` | percorso della vista, default `/api/alexa_bridge/smart_home` |
| `NOT_VERIFY_SSL` | `true` salta la verifica TLS: solo per prove |
| `DEBUG` | `true` abilita i log di debug e il token di prova; solo durante il collaudo (passo 7) |
| `LONG_LIVED_ACCESS_TOKEN` | token di prova, usato **solo** con `DEBUG` attivo e solo se la direttiva non porta un token. Va aggiunto solo durante il collaudo e rimosso (e revocato in HA) subito dopo: passo 7 |
