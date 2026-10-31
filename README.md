# Alexa Bridge

Home Assistant custom integration that exposes the entities you choose to Alexa,
reusing Home Assistant's built-in Alexa engine, together with an AWS Lambda
bridge that connects a custom Alexa Smart Home skill to your instance.

Le guide sono in italiano.

## Come funziona

Una skill Alexa Smart Home (creata da te) invoca una Lambda su AWS; la Lambda
inoltra le direttive alla vista `/api/alexa_bridge/smart_home` di questa
integrazione, che le gestisce con il motore Alexa di Home Assistant, ma
condividendo **solo** le entità che scegli da interfaccia. Aggiunte e rimozioni
vengono comunicate ad Alexa automaticamente.

## Installazione (HACS)

1. HACS > menu a tre puntini > **Repository personalizzati**.
2. Aggiungi l'URL di questo repository, categoria **Integrazione**.
3. Cerca "Alexa Bridge", scarica e **riavvia** Home Assistant.

L'integrazione usa API interne di Home Assistant (`homeassistant.components.alexa`):
la CI la prova ogni settimana contro HA stabile e beta.

## Configurazione

1. [Lambda su AWS](docs/setup-aws.md): strumenti, utente IAM di deploy, `sam deploy`.
2. [Skill Alexa](docs/setup-skill.md): endpoint, Account Linking, permesso
   Send Alexa Events.
3. In HA: *Impostazioni > Dispositivi e servizi > Aggiungi integrazione > Alexa
   Bridge*, con Client ID e Client secret di Skill Messaging.
4. *Configura* nell'integrazione: scegli domini, aree ed entità da condividere
   (**prima** di collegare l'account in Alexa). Un'area condivide tutte le
   entità supportate che contiene (dell'entità o del suo dispositivo), tranne le
   escluse; spostare un dispositivo dentro o fuori l'area aggiorna Alexa da sé.
5. Collega la skill dall'app Alexa e cerca i dispositivi.
6. [Collaudo](docs/collaudo.md): checklist di verifica dal vivo.

Altre guide: [avviare un'automazione a voce](docs/script-gemelli.md).

Se nel `configuration.yaml` c'è il blocco `alexa:` dell'integrazione standard,
rimuovilo: HA lo segnala per evitare risposte doppie.

## Sviluppo

```bash
pip install -r requirements_test.txt
pytest                  # integrazione
pytest lambda/tests -v  # Lambda (solo pytest, libreria standard)
```

## Licenza

MIT, copyright Paolo Bets.
