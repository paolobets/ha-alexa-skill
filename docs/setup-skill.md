# Creazione della skill Alexa

La skill è di tipo **Smart Home** e si crea a mano nella
[console sviluppatori Alexa](https://developer.amazon.com/alexa/console/ask)
con lo stesso account Amazon usato per l'app Alexa. Prerequisito: Lambda
distribuita ([setup-aws.md](setup-aws.md)).

Segnaposto usati qui: `<HA_URL>` (indirizzo pubblico di HA, https),
`<SKILL_ID>`, `<ARN>` (ARN della Lambda).

## 1. Crea la skill

1. *Create Skill*, nome a piacere (ad esempio "Casa").
2. Lingua primaria: **Italiano**.
3. Tipo di esperienza: **Smart Home**.
4. Crea e annota lo **Skill ID** (`amzn1.ask.skill.<...>`): serve per il deploy
   della Lambda (parametro `SkillId`).

## 2. Endpoint

Nella sezione *Smart Home service endpoint*:

- **Default endpoint**: `<ARN>` (ARN della Lambda in `eu-west-1`).
- Lascia vuoti gli altri endpoint regionali: per l'italiano vale quello **Europe**.

Salva.

## 3. Account Linking

Nella sezione *Account Linking* inserisci:

| Campo | Valore |
|---|---|
| Authorization URI | `<HA_URL>/auth/authorize` |
| Access Token URI | `<HA_URL>/auth/token` |
| Client ID | `https://layla.amazon.com/` (con lo slash finale: è quello del servizio EU) |
| Client Secret | un valore qualsiasi (HA non lo verifica) |
| Authentication Scheme | *Credentials in request body* |
| Scope | `smart_home` |

Il login è la normale pagina di accesso di HA (con la verifica a due fattori,
se attiva).

## 4. Permesso per gli eventi

Nella sezione *Permissions* attiva **Send Alexa Events**. Servono i report
proattivi (sensori, binary_sensor, aggiunta e rimozione automatica dei
dispositivi). Appena attivato compaiono **Client ID** e **Client Secret** di
*Alexa Skill Messaging*: copiali.

> Se attivi questo permesso **dopo** aver già collegato l'account, scollega e
> ricollega la skill dall'app Alexa, altrimenti Alexa non concede
> l'autorizzazione agli eventi.

## 5. Dati nel config flow di HA

In HA: *Impostazioni > Dispositivi e servizi > Aggiungi integrazione > Alexa
Bridge*. Incolla *Client ID* e *Client secret* di Skill Messaging; gli altri
campi hanno già i valori giusti (lingua `it-IT`, endpoint eventi
`https://api.eu.amazonalexa.com/v3/events`). I segreti restano salvati da HA:
non vanno scritti nel repo né condivisi.

## 6. Ordine corretto

1. **Prima** scegli in HA cosa condividere (*Alexa Bridge > Configura*): domini
   interi, aree intere (tutte le entità supportate dell'area, tranne le escluse)
   o singole entità; togli domini o dispositivi interi con «Domini da
   escludere» e «Dispositivi da escludere». Conferma il numero di entità.
2. **Poi** collega la skill dall'app Alexa (abilita la skill in sviluppo, accedi
   con HA) e avvia la scoperta dei dispositivi.

Così Alexa vede subito solo le entità scelte.

## 7. PIN vocale per serrature e cancelli

Le serrature (`lock`) si sbloccano a voce solo con un **PIN vocale a 4 cifre**:
impostalo nell'app Alexa (impostazioni della serratura, *PIN vocale*). Lo stesso
vale per cancelli e garage, **ma solo** se in HA sono `cover` con
`device_class: garage` o `gate`. Un cancello esposto come `switch`, `button` o
`script` verrebbe aperto da Alexa senza PIN: avvolgilo in una cover template o
non condividerlo.

## Automazioni a voce

Le automazioni non si condividono direttamente (Alexa le tratta come interruttori
abilita/disabilita): vedi [script-gemelli.md](script-gemelli.md).
