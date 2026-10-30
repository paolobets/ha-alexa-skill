# HA → Alexa: integrazione custom + skill Smart Home personale via AWS Lambda — Disegno

Data: 2026-10-30 · Autore: Paolo Bets (con Claude)

## 1. Intento

Comandare da Alexa i dispositivi di casa gestiti da Home Assistant con una **skill
Smart Home privata** (non pubblicata, solo per l'account di Paolo), al posto delle
vecchie skill di terze parti ormai disattivate. Niente Nabu Casa: il ponte è una
Lambda AWS di proprietà.

Lato HA, al posto della configurazione YAML dell'integrazione `alexa` di serie, una
**integrazione custom** con interfaccia in cui Paolo **sceglie domini ed entità da
condividere**, e che **toglie da Alexa** ciò che smette di condividere.

Il perché: oggi i dispositivi sono sparsi su skill diverse e Alexa è piena di
doppioni e orfani, senza cancellazione massiva. HA è già la fonte di verità di
casa, quindi Alexa deve vedere **HA e solo HA**, e la lista deve restare pulita nel
tempo senza interventi a mano nell'app Alexa.

## 2. Obiettivi

1. Alexa vede e comanda: luci, interruttori/prese, tapparelle/cover, clima,
   ventole, serrature, scene, script (e quanto altro Paolo seleziona tra i domini
   supportati).
2. Alexa legge i **sensori di temperatura** ("che temperatura c'è in sala?").
3. Le automazioni che Paolo vuole avviare a voce si avviano come **script**
   ("Alexa, attiva buonanotte").
4. Lo stato in app Alexa è sempre quello vero (report proattivi verso Alexa).
5. **Selezione da interfaccia HA**: domini e singole entità, modificabile in ogni
   momento senza YAML né riavvio.
6. **Rimozione automatica**: un'entità tolta dalla selezione (o eliminata da HA)
   sparisce anche dall'app Alexa; una aggiunta compare senza rifare la scoperta.
7. Tutto ricreabile da zero dal repo: Lambda pubblicata da script, integrazione
   installabile, guida passo-passo per i pezzi manuali.

## 3. Non obiettivi

- **Annunci vocali decisi da HA**: già coperti da *Alexa Media Player* (custom
  component già installato in HA, `notify.alexa_media_*`). La skill non se ne occupa.
- **Pulizia dei dispositivi orfani delle vecchie skill**: progetto separato,
  successivo (vedi §11). L'integrazione cancella solo i dispositivi propri.
- **Allarme** (`alarm_control_panel`): escluso per decisione di Paolo.
- **Umidità a voce**: rimandata (decisione di Paolo, "vediamo poi").
- Pubblicazione della skill sullo store / certificazione Amazon.
- Supporto multi-utente, multi-account Alexa o multi-regione.
- Riscrivere la traduzione dispositivi HA ↔ Alexa: si riusa quella di HA (§7).

## 4. Anti-obiettivi (fallimento anche se "funziona")

- Ricreare il disordine: centinaia di entità tecniche (batterie, diagnostica,
  aggiornamenti, helper) che finiscono nell'app Alexa.
- **Doppioni degli Echo**: i `media_player` creati da Alexa Media Player
  esposti di nuovo ad Alexa.
- Segreti (token HA, client secret) nel repo o in chat.
- Aprire serrature (o in futuro cancelli/garage) senza il PIN vocale Alexa.
- Un setup che funziona una volta e nessuno sa rifare.
- Un aggiornamento di HA che rompe l'integrazione **senza che ce ne accorgiamo**.

## 5. Vincoli e fatti verificati

Fonti (consultate 2026-10-30):
[HA – Alexa Smart Home](https://www.home-assistant.io/integrations/alexa.smart_home/),
[Amazon – Implement Smart Home Skill Code](https://developer.amazon.com/en-US/docs/alexa/smarthome/implement-your-skill.html),
codice `home-assistant/core` ramo `dev`, `homeassistant/components/alexa/`.

| Fatto | Conseguenza |
|---|---|
| Italiano (it-IT) → Lambda in **EU (Ireland) `eu-west-1`**, endpoint Alexa "Europe" | regione fissa |
| Il motore Alexa di HA supporta `locale: it-IT` | nomi e risposte in italiano |
| Lambda di riferimento HA: Python 3, `arm64` consigliato; env `BASE_URL` (senza `/` finale), `NOT_VERIFY_SSL`, `DEBUG`, `LONG_LIVED_ACCESS_TOKEN` (solo test) | |
| Account Linking: auth `<HA_URL>/auth/authorize`, token `<HA_URL>/auth/token`, Client ID **`https://layla.amazon.com/`** (EU, slash finale obbligatorio), secret qualsiasi, schema *Credentials in request body*, scope `smart_home` | login = pagina di accesso di HA; il token vale per qualunque vista HTTP autenticata di HA, quindi anche per quella dell'integrazione custom |
| L'integrazione `alexa` manuale **non ha selezione da UI**: solo `filter` YAML. Senza filtro espone tutto tranne entità **nascoste** o con `entity_category` (diagnostica/config) — `AlexaConfig.should_expose` in `smart_home.py` | motivo dell'integrazione custom |
| `AbstractConfig` (`alexa/config.py`) ha `should_expose()` sovrascrivibile; `state_report.py` ha `async_send_add_or_update_message` e **`async_send_delete_message`** (oggi usati solo da Nabu Casa) | selezione e rimozione automatica si costruiscono su questi |
| Sono **API interne** di HA, non pubbliche e senza garanzia di stabilità | rischio rotture agli aggiornamenti → §9 |
| `automation` è esposta come **interruttore abilita/disabilita**, non come avvio | dominio non selezionabile (§6.1) |
| `script`: avvio con "attiva"/"accendi", stop con "spegni"; `scene`: solo avvio | |
| `sensor`: **solo temperatura**; umidità non supportata | |
| `binary_sensor`: hanno capacità sensore solo `door/garage_door/opening/window` (contatto) e `motion` (movimento), usabili come **attivatori di routine** Alexa. `presence` usa `AlexaEventDetectionSensor` con `supported_locales = {"en-US"}`: **in it-IT non funziona**. Il motore però scopre *ogni* binary_sensor (sempre `EndpointHealth`), anche batteria/connettività | l'integrazione filtra i binary_sensor per `device_class` (§6.1) |
| `endpointId` = entity_id con `.`→`#` (`generate_alexa_id`): rinominare l'entity_id = dispositivo nuovo in Alexa | ID stabile da `unique_id` (§6.2) |
| Alexa riceve **un solo nome**: il primo alias di HA (`aliases[0]`), altrimenti il friendly name | |
| `AbstractConfig.async_initialize` usa lo store fisso `.storage/alexa`, `Auth` usa `.storage/alexa_auth` | l'integrazione usa store propri, per non condividere token con `alexa`/cloud |
| La Smart Home API **non** assegna i dispositivi a gruppi/stanze Alexa; un `DeleteReport` seguito da nuova aggiunta fa tornare il dispositivo **senza** gruppo e routine | §6.2, §12 |
| Sensori e binary_sensor **richiedono i report proattivi**; anche aggiunta/rimozione automatica li richiede | report proattivi obbligatori |
| Report proattivi: permesso *Send Alexa Events* nella skill; client id/secret da *Alexa Skill Messaging*; endpoint eventi EU `https://api.eu.amazonalexa.com/v3/events` | se il permesso si attiva dopo il linking → scollegare e ricollegare |
| `lock`: sblocco con PIN vocale a 4 cifre (app Alexa). `cover` con `device_class: garage` **o `gate`**: categoria `GARAGE_DOOR`, apertura con PIN (verificato in `entities.py`) | §6.4 |

Ambiente:

- HA su `<HA_LAN_IP>`, raggiungibile da internet in HTTPS su `<HA_URL>` tramite un
  tunnel; nessuna protezione davanti che blocchi Amazon/AWS.
- Account AWS e account sviluppatore Amazon (stessa email di Alexa): esistenti.
- Se in HA c'è Alexa Media Player, le sue entità Echo vanno escluse (§6.1).
- Sul PC di Paolo **non** ci sono AWS CLI né SAM CLI (verificato 2026-10-30).

## 6. Cosa si condivide

### 6.1 Selezione

Pagina **opzioni** dell'integrazione (Impostazioni → Dispositivi e servizi →
integrazione → Configura):

- **Domini**: scelta multipla tra quelli supportati dal motore Alexa di HA.
  Non proposti: `automation` (diventerebbe un interruttore che la disabilita) e
  `alarm_control_panel` (escluso, §3).
- **Entità incluse in più**: singole entità di domini non selezionati.
- **Entità escluse**: singole entità di domini selezionati.
- Regola: condivisa = (dominio selezionato **oppure** entità inclusa) **e non**
  esclusa **e** supportata dal motore. Restano sempre escluse le entità nascoste e
  quelle diagnostiche/config, salvo inclusione esplicita.
- `binary_sensor`: anche col dominio selezionato si condividono **solo** le classi
  `door`, `garage_door`, `opening`, `window`, `motion` (le altre, compresa
  `presence`, non funzionano in it-IT o sono rumore), salvo inclusione esplicita.
- **Esclusione fissa** degli Echo di Alexa Media Player (entità della piattaforma
  `alexa_media`), anche se il dominio `media_player` è selezionato.
- Al primo avvio nessun dominio è preselezionato: non si condivide nulla finché
  Paolo non sceglie (*scelta di Claude*, per non ricreare il disordine).
- La pagina mostra **quante entità** risultano condivise con la selezione corrente,
  così il disordine si vede prima di salvare (*scelta di Claude*).

### 6.2 Sincronizzazione con Alexa

Al salvataggio delle opzioni, e quando un'entità condivisa viene creata, rinominata
o eliminata in HA:

- entità che entrano → `AddOrUpdateReport`;
- entità che escono → `DeleteReport`.

Se i report proattivi non sono ancora autorizzati, l'integrazione lo segnala
(notifica persistente o problema in Riparazioni) invece di fallire in silenzio.

Regole di ciclo di vita (*scelte di Claude*, perché cancellare da Alexa fa perdere
gruppi e routine):

- **ID stabile**: l'`endpointId` si costruisce dal `unique_id` del registro entità
  (entity_id solo per le entità senza `unique_id`). Rinominare un entity_id è
  quindi un aggiornamento, non cancella+aggiungi. Deciso prima della prima
  scoperta, perché cambiarlo dopo duplica tutto.
- L'integrazione **salva l'ultimo insieme sincronizzato** e manda Add/Delete solo
  per differenza.
- Cancella da Alexa solo quando: la selezione cambia, oppure l'entità è
  **eliminata dal registro** di HA. Entità `unavailable` o non ancora caricate
  all'avvio **non** contano come rimosse; la riconciliazione parte solo a HA
  avviato del tutto.
- Ricaricare o disattivare l'integrazione non cancella nulla. **Rimuoverla** da HA
  manda `DeleteReport` per tutto, così non lascia orfani.

### 6.3 Nomi

Il nome pronunciato è quello che Alexa riceve: il **primo alias** dell'entità in
HA, altrimenti il friendly name. Per correggere un nome solo per la voce basta
aggiungere un alias in HA e metterlo primo. Nessuna gestione nomi nell'integrazione.

### 6.4 Sicurezza vocale

- `lock`: sblocco con PIN vocale Alexa a 4 cifre, impostato nell'app (passo nella
  guida).
- Regola per il futuro: un cancello o garage si condivide **solo** come `cover`
  con `device_class: garage` o `gate` (PIN all'apertura). Se in HA è `switch`/`button`/
  `script`, Alexa lo aprirebbe senza PIN: va avvolto in una cover template o non
  condiviso. Oggi non ce ne sono.

### 6.5 Automazioni avviabili a voce

Ogni automazione da avviare a voce ha uno **script** gemello (che chiama
`automation.trigger` o fa le stesse azioni). L'elenco lo dà Paolo durante il
lavoro; il builder prepara il modello.

## 7. Architettura

```
Echo ──▶ Alexa cloud (EU) ──▶ Lambda eu-west-1 ──HTTPS──▶ <HA_URL>/api/<dominio>/smart_home
                ▲                                                   │  (vista HTTP dell'integrazione custom)
                └──── report proattivi + Add/Delete (api.eu.amazonalexa.com) ◀───┘
```

- **Integrazione custom** (`custom_components/<dominio>/`):
  - *config flow*: client id/secret di Alexa Skill Messaging; locale `it-IT` e
    endpoint eventi EU come default;
  - *options flow*: la selezione di §6.1;
  - una sottoclasse della config Alexa di HA con `should_expose()` guidato dalla
    selezione, `generate_alexa_id()` stabile (§6.2) e **store propri** al posto di
    `.storage/alexa` e `.storage/alexa_auth`; una propria vista HTTP che passa le
    direttive al motore Alexa di HA;
  - la sincronizzazione di §6.2.
- **Convivenza**: l'integrazione `alexa:` di serie **non** va configurata insieme
  (stesso motore, rischio di doppie risposte/ID). La guida lo dice e l'integrazione
  lo segnala se la trova.
- **Lambda**: il codice di riferimento HA, versionato nel repo, con il percorso
  della vista custom al posto di `/api/alexa/smart_home`. Nessuna altra logica.

## 8. Come si costruisce (deciso)

- **Repo**: `C:\Work\Sviluppo\ha-alexa-skill`, git locale; remote GitHub
  **pubblico** su `paolobets` (decisione di Paolo), da creare con sua conferma.
  Essendo pubblico: nessun dato di casa nel repo (né dominio, né entity_id, né ID
  della skill/Lambda negli esempi: si usano segnaposto), e licenza **MIT** con
  copyright "Paolo Bets" (*scelta di Claude*, modificabile).
- **Installazione in HA**: via **HACS** come repository personalizzato (Paolo usa
  già HACS per Alexa Media Player), con release GitHub versionate.
- **Lambda**: Python, `eu-west-1`, pubblicata con **AWS SAM** (template nel repo).
  Trigger *Alexa Smart Home* limitato allo **Skill ID** della skill.
- **Credenziali AWS** (*scelta di Claude*): si installano AWS CLI e SAM CLI e si
  crea un utente IAM di deploy a privilegi minimi; le chiavi le inserisce Paolo con
  `aws configure` (mai in chat). Da lì deploy e test della Lambda li esegue Claude.
- **Skill**: creata a mano nella console sviluppatori Amazon seguendo
  `docs/setup-skill.md` (da scrivere): tipo Smart Home, lingua Italiano, endpoint =
  ARN Lambda EU, Account Linking (§5), permesso Send Alexa Events.
- **Segreti**: `LONG_LIVED_ACCESS_TOKEN` solo durante il collaudo, con `DEBUG`,
  poi rimosso e revocato in HA. Client secret di Skill Messaging inserito nel config
  flow di HA (salvato da HA, non nel repo). I segreti si passano con file locali,
  mai in chat.
- Installazione, aggiornamento e riavvio sull'HA di produzione: con conferma di
  Paolo.

## 9. Qualità e aggiornamenti di HA

- Test automatici con `pytest-homeassistant-custom-component`: selezione (regola di
  §6.1, esclusione Echo, nascoste/diagnostiche), risposta a `Discovery`, invio di
  Add/Delete al cambio di selezione, segnalazione quando i report proattivi non
  sono autorizzati.
- CI GitHub Actions contro HA **stabile** e contro la **beta/dev**, anche a
  calendario (settimanale), così una rottura dovuta a un aggiornamento di HA si
  vede prima di aggiornare casa.
- `manifest.json` con versione minima di HA dichiarata; versione dell'integrazione
  bumpata a ogni rilascio.

## 10. Collaudo dal vivo (in ordine)

0. Controlli d'accesso (*scelta di Claude*): nessuna regola del tunnel o del proxy
   davanti (WAF, protezione anti-bot, blocchi per paese/ASN) che sfidi o blocchi
   chiamate da AWS/Amazon verso `<HA_URL>`; in HA `trusted_proxies` corretto per il tunnel, così un
   `ip_ban` non banna l'IP del tunnel stesso.
1. Integrazione installata in HA, selezione iniziale fatta da Paolo; il contatore
   di §6.1 conferma il numero atteso.
2. Lambda contro HA con un evento di prova `Discovery` (token di test): risponde
   esattamente con le entità selezionate.
3. Collegamento account dall'app Alexa (login HA) e scoperta dispositivi.
   Confronto con i dispositivi orfani ancora in Alexa: quelli con **nome uguale** a
   un'entità condivisa si cancellano a mano prima delle prove a voce (*scelta di
   Claude*; la pulizia massiva resta §11).
4. Prove a voce: una per dominio condiviso, comprese temperatura, script e PIN.
5. Report proattivi: cambio stato da HA → app Alexa aggiornata; una routine Alexa
   attivata da un binary_sensor di contatto.
6. **Rimozione automatica**: togliere un'entità dalla selezione → sparisce
   dall'app Alexa; rimetterla → ricompare senza nuova scoperta (senza gruppo né
   routine, atteso). Rinominare un entity_id → stesso dispositivo in Alexa.
   Riavviare HA → nessun dispositivo cancellato.
7. Rimozione del token di test e di `DEBUG`.

Fatto = tutti i punti verificati dal vivo.

## 11. Dopo (fuori da questo disegno)

**Pulizia dispositivi orfani delle vecchie skill**: strumento da lanciare una
volta che elenca i dispositivi Smart Home dell'account Alexa, seleziona quelli non
appartenenti alla nostra skill e li cancella in blocco tramite l'interfaccia web
**non ufficiale** di Alexa. Possibile appoggio: il login già usato da Alexa Media
Player. Va fatto dopo la scoperta della nostra skill, così si distinguono i buoni
dagli orfani. Potrebbe diventare un servizio della stessa integrazione. Si progetta
a parte.

**Stanze Alexa = aree di HA** (decisione di Paolo, 2026-10-30): i gruppi/stanze
esistenti in Alexa si cancellano e si ricreano uguali alle aree di HA, con dentro i
dispositivi condivisi di quell'area (e, *idea di Claude*, l'Echo che sta in
quell'area, così "accendi la luce" vale per la stanza). Usa la stessa interfaccia
non ufficiale della pulizia, quindi sta nella stessa seconda fase, dopo la prima
scoperta (*scelta di Claude*). In questa prima fase le stanze non si toccano.

## 12. Aperto

Nulla. (Repo pubblico perché HACS non usa repository privati: "Private GitHub
repositories can not be used with HACS at all", FAQ HACS.)

## 13. Lasciato al builder

- Nome del dominio dell'integrazione e percorso della vista HTTP.
- Struttura interna del repo, template SAM, versione Python esatta.
- Forma della pagina opzioni (selettori HA), formato del contatore.
- Formato dell'evento di prova e script di test della Lambda.
- Testo della guida `docs/setup-skill.md`.
