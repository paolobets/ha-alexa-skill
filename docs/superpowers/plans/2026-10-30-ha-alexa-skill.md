# HA → Alexa (integrazione custom + Lambda) — Piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un'integrazione custom HA `alexa_bridge` (installabile da HACS) che espone ad Alexa solo le entità scelte da UI e tiene Alexa allineata, più una Lambda `eu-west-1` che fa da ponte per una skill Smart Home privata in it-IT.

**Architecture:** L'integrazione riusa il motore `homeassistant.components.alexa` (traduzione entità, handler, report di stato) tramite una sottoclasse di `AbstractConfig` con selezione, ID stabili e store propri, e registra una propria vista HTTP. La Lambda inoltra le direttive Alexa a quella vista con il token di Account Linking. La sincronizzazione (AddOrUpdate/Delete) confronta la selezione con l'ultimo insieme inviato, salvato su disco.

**Tech Stack:** Python 3.13+, Home Assistant custom integration (config/options flow, `Store`, registro entità, repairs), `pytest-homeassistant-custom-component`, AWS Lambda (Python, arm64) + AWS SAM, GitHub Actions (pytest, hassfest, HACS action).

**Spec:** `docs/superpowers/specs/2026-10-30-ha-alexa-skill-design.md`

## Global Constraints

- Dominio integrazione: `alexa_bridge`; vista HTTP: `/api/alexa_bridge/smart_home`; nome vista `api:alexa_bridge:smart_home`.
- Locale default `it-IT`; endpoint eventi default `https://api.eu.amazonalexa.com/v3/events`.
- Lambda in `eu-west-1`, architettura `arm64`, ultimo runtime Python supportato da Lambda.
- Account Linking: Client ID `https://layla.amazon.com/`, schema *Credentials in request body*, scope `smart_home`.
- Store propri: `alexa_bridge` (config/autorizzazione), `alexa_bridge_auth` (token LWA), `alexa_bridge_sync` (ultimo insieme sincronizzato). Mai `.storage/alexa*`.
- Domini mai selezionabili: `automation`, `alarm_control_panel`.
- `binary_sensor` condivisi per dominio solo con `device_class` in `door`, `garage_door`, `opening`, `window`, `motion`.
- Echo esclusi sempre: entità con piattaforma di registro `alexa_media`.
- Repo **pubblico**: nessun dato di casa (dominio, IP della LAN, entity_id reali, Skill ID, ARN, account id) in file versionati; negli esempi segnaposto `<HA_URL>`, `<SKILL_ID>`. Licenza MIT, copyright "Paolo Bets".
- Segreti mai in chat né nel repo; `samconfig.toml` e `.env*` in `.gitignore`.
- Test dell'integrazione: si eseguono in **WSL Ubuntu** (il banco di prova HA non gira su Windows nativo). In WSL c'è Python 3.14 senza pip/uv: installare `uv` per l'utente.
- Commit locali liberi; **creazione del repo GitHub, push, tag/release, installazione in HA di produzione, deploy AWS: solo con conferma esplicita di Paolo** (task 11–12).
- Ogni rilascio bumpa `version` in `manifest.json`.
- Codice e identificatori in inglese; testi UI in italiano (`translations/it.json`) e inglese (`strings.json`/`en.json`).

## Review Focus

1. **Instradamento con ID stabili**: `AlexaDirective.load_entity` ricava l'entity_id con `endpointId.replace("#", ".")` e ignora `generate_alexa_id`. Con ID basati sul registro, la vista deve tradurre l'`endpointId` in ingresso (ID stabile → forma legacy) e quello in uscita (legacy → stabile), altrimenti ogni comando risponde `NO_SUCH_ENDPOINT`. Test nel task 5.
2. **DeleteReport di un'entità già eliminata**: dopo la rimozione dal registro non si può più calcolare l'ID: va preso dall'ultimo insieme sincronizzato salvato. Test nel task 8.
3. **Avvio di HA**: entità con integrazione ancora non caricata (niente stato) non devono generare DeleteReport. Test nel task 8.
4. **binary_sensor senza stato**: la `device_class` si legge dal registro (`device_class` o `original_device_class`) prima che dallo stato, così la selezione non cambia durante l'avvio. Test nel task 2.
5. **Rimozione dell'integrazione senza token valido** (skill mai collegata): `async_remove_entry` non deve sollevare eccezioni né bloccare la rimozione. Test nel task 8.

---

## File Structure

```
custom_components/alexa_bridge/
  __init__.py        setup/unload/remove della config entry, avvio vista e sincronizzazione
  manifest.json      dominio, versione, dependencies ["http"], after_dependencies ["alexa"]
  const.py           costanti (dominio, chiavi opzioni, default, domini bloccati, classi binary_sensor)
  selection.py       regola "condivisa sì/no" e conteggio; nessun I/O
  ids.py             ID stabili ↔ entity_id
  config.py          BridgeConfig(AbstractConfig), store e Auth propri
  view.py            BridgeSmartHomeView con traduzione degli endpointId
  sync.py            SyncManager: ultimo insieme sincronizzato, Add/Delete, eventi registro
  config_flow.py     ConfigFlow (credenziali Skill Messaging) + OptionsFlow (selezione + conferma con conteggio)
  strings.json, translations/en.json, translations/it.json
hacs.json
tests/               conftest.py + un file per modulo
lambda/              lambda_function.py, template.yaml, tests/test_lambda_function.py
.github/workflows/   tests.yml, validate.yml
docs/                setup-aws.md, setup-skill.md, collaudo.md
README.md, LICENSE, .gitignore, pyproject.toml, requirements_test.txt
```

---

### Task 1: Scheletro del repo e banco di prova

**Files:**
- Create: `custom_components/alexa_bridge/__init__.py`, `manifest.json`, `const.py`, `hacs.json`, `pyproject.toml`, `requirements_test.txt`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_manifest.py`, `.gitignore`, `LICENSE`, `README.md`

**Interfaces:**
- Produces (`const.py`):
  - `DOMAIN = "alexa_bridge"`, `VIEW_URL = "/api/alexa_bridge/smart_home"`
  - `CONF_DOMAINS = "domains"`, `CONF_INCLUDE_ENTITIES = "include_entities"`, `CONF_EXCLUDE_ENTITIES = "exclude_entities"`
  - `CONF_LOCALE = "locale"`, `CONF_ENDPOINT = "endpoint"` (le credenziali usano `CONF_CLIENT_ID`/`CONF_CLIENT_SECRET` di `homeassistant.const`)
  - `DEFAULT_LOCALE = "it-IT"`, `DEFAULT_ENDPOINT = "https://api.eu.amazonalexa.com/v3/events"`
  - `BLOCKED_DOMAINS = frozenset({"automation", "alarm_control_panel"})`
  - `BINARY_SENSOR_CLASSES = frozenset({"door", "garage_door", "opening", "window", "motion"})`
  - `ECHO_PLATFORM = "alexa_media"`
  - `STORE_CONFIG = "alexa_bridge"`, `STORE_AUTH = "alexa_bridge_auth"`, `STORE_SYNC = "alexa_bridge_sync"`
  - `STABLE_ID_PREFIX = "ha-"`

- [ ] **Step 1:** In WSL: installa `uv`, crea `.venv` con Python 3.13+, installa `requirements_test.txt` (`pytest-homeassistant-custom-component` all'ultima versione stabile, che fissa anche `homeassistant`).
- [ ] **Step 2: Scrivi il test che fallisce** `tests/test_manifest.py::test_manifest_matches_domain`: carica `manifest.json`, asserisce `domain == DOMAIN`, `"http" in dependencies`, `config_flow is True`, presenza di `version`; e `hacs.json` ha `name` e `homeassistant` (versione minima).
- [ ] **Step 3:** `pytest tests/test_manifest.py -v` → FAIL (file mancanti).
- [ ] **Step 4:** Crea manifest (`iot_class: "cloud_push"`, `integration_type: "service"`, `version: "0.1.0"`, `after_dependencies: ["alexa"]`, `codeowners: ["@paolobets"]`), `hacs.json` (minimo HA = la versione `homeassistant` installata dallo step 1), `const.py`, `__init__.py` con `async_setup_entry`/`async_unload_entry` che restituiscono `True`; `conftest.py` con la fixture `auto_enable_custom_integrations`; `pyproject.toml` con `asyncio_mode = "auto"`; `.gitignore` (`.venv`, `samconfig.toml`, `.aws-sam/`, `.env*`, `__pycache__`); LICENSE MIT "Copyright (c) 2026 Paolo Bets"; README con un paragrafo e la sezione "Installazione (HACS)" da completare nel task 10.
- [ ] **Step 5:** `pytest -v` → PASS.
- [ ] **Step 6:** Commit `chore: scheletro integrazione alexa_bridge e banco di prova`.

---

### Task 2: Regola di selezione

**Files:**
- Create: `custom_components/alexa_bridge/selection.py`
- Test: `tests/test_selection.py`

**Interfaces:**
- Consumes: costanti del task 1.
- Produces:
  - `@dataclass(frozen=True) class Selection: domains: frozenset[str]; include: frozenset[str]; exclude: frozenset[str]` con `@classmethod from_options(cls, options: Mapping[str, Any]) -> Selection`
  - `def selectable_domains() -> list[str]`: chiavi ordinate di `homeassistant.components.alexa.entities.ENTITY_ADAPTERS` meno `BLOCKED_DOMAINS`
  - `def is_shared(hass: HomeAssistant, entity_id: str, selection: Selection) -> bool`
  - `def shared_entity_ids(hass: HomeAssistant, selection: Selection) -> set[str]`: su tutti gli stati presenti con dominio in `ENTITY_ADAPTERS`

Regola (in quest'ordine): bloccato se il dominio è in `BLOCKED_DOMAINS` o non è in `ENTITY_ADAPTERS` → `False`; piattaforma di registro `alexa_media` → `False`; in `exclude` → `False`; in `include` → `True`; dominio non in `domains` → `False`; voce di registro con `entity_category` o `hidden_by` → `False`; `binary_sensor` con classe (registro `device_class or original_device_class`, poi attributo `device_class` dello stato) non in `BINARY_SENSOR_CLASSES` → `False`; altrimenti `True`.

- [ ] **Step 1: Scrivi i test che falliscono** (stati con `hass.states.async_set`, voci con `er.async_get(hass).async_get_or_create`):
  - `test_domain_selected_shares_entity`: `light.sala` con `domains={"light"}` → `True`
  - `test_domain_not_selected`: `switch.x` con `domains={"light"}` → `False`
  - `test_include_overrides_domain`: `switch.x` in `include` → `True`
  - `test_exclude_wins_over_include_and_domain`: `light.sala` in `domains`, `include` ed `exclude` → `False`
  - `test_blocked_domains_never_shared`: `automation.a` e `alarm_control_panel.b` in `include` → `False`
  - `test_echo_never_shared`: `media_player.echo` con piattaforma `alexa_media`, in `include` → `False`
  - `test_hidden_and_diagnostic_excluded_unless_included`: `entity_category=EntityCategory.DIAGNOSTIC` → `False` per dominio, `True` se in `include`
  - `test_binary_sensor_classes`: `door`/`motion` → `True`; `battery`/`presence` → `False`
  - `test_binary_sensor_class_from_registry_without_state`: voce di registro `original_device_class="window"`, nessuno stato → `True`
  - `test_selectable_domains_excludes_blocked`: `"automation"` e `"alarm_control_panel"` assenti, `"light"` e `"script"` presenti
  - `test_shared_entity_ids_counts`: 3 luci (una nascosta) + 1 switch, `domains={"light"}` → 2 elementi
- [ ] **Step 2:** `pytest tests/test_selection.py -v` → FAIL (modulo mancante).
- [ ] **Step 3:** Implementa `selection.py` secondo la regola sopra.
- [ ] **Step 4:** `pytest tests/test_selection.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: regola di selezione delle entità condivise`.

---

### Task 3: ID stabili

**Files:**
- Create: `custom_components/alexa_bridge/ids.py`
- Test: `tests/test_ids.py`

**Interfaces:**
- Produces:
  - `def stable_alexa_id(hass: HomeAssistant, entity_id: str) -> str`: con voce di registro → `STABLE_ID_PREFIX + entry.id`; senza → forma legacy `entity_id.replace(".", "#").translate(TRANSLATION_TABLE)` (tabella da `homeassistant.components.alexa.entities`)
  - `def entity_id_from_alexa_id(hass: HomeAssistant, alexa_id: str) -> str | None`: prefisso `ha-` → voce di registro per `id` (con `er.async_get(hass).entities.get_entry(id)`; se l'API non c'è nella versione HA fissata, scansione di `entities.values()`) → `entry.entity_id`, `None` se non trovata; altrimenti `alexa_id.replace("#", ".")`
  - `def legacy_alexa_id(entity_id: str) -> str`

- [ ] **Step 1: Scrivi i test che falliscono:**
  - `test_registry_entity_gets_stable_id`: risultato == `"ha-" + entry.id`
  - `test_stable_id_survives_rename`: `async_update_entity(..., new_entity_id="light.nuovo")` → stesso ID; `entity_id_from_alexa_id` → `"light.nuovo"`
  - `test_entity_without_registry_uses_legacy`: `light.yaml_only` → `"light#yaml_only"` e ritorno
  - `test_unknown_stable_id_returns_none`
  - `test_stable_id_is_valid_alexa_endpoint_id`: corrisponde a `^[A-Za-z0-9_\-=#;:?@&]{1,256}$`
- [ ] **Step 2:** `pytest tests/test_ids.py -v` → FAIL.
- [ ] **Step 3:** Implementa `ids.py`.
- [ ] **Step 4:** `pytest tests/test_ids.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: ID Alexa stabili dal registro entità`.

---

### Task 4: Config Alexa del bridge con store propri

**Files:**
- Create: `custom_components/alexa_bridge/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `Selection`, `is_shared` (task 2); `stable_alexa_id` (task 3).
- Produces:
  - `class BridgeConfigStore(AlexaConfigStore)` con `_STORAGE_KEY = STORE_CONFIG`
  - `class BridgeAuth(Auth)`: dopo `super().__init__` sostituisce `self._store` con `Store(hass, STORAGE_VERSION, STORE_AUTH)`
  - `class BridgeConfig(AbstractConfig)`: `__init__(self, hass, entry: ConfigEntry)`; `async_initialize()` usa `BridgeConfigStore`; proprietà `supports_auth` (sempre `True`), `should_report_state` (`self.authorized`), `endpoint`, `locale` (da `entry.data`, default di `const`), `entity_config` (`{}`), `user_identifier()` (`entry.entry_id`); `selection` (property, `Selection.from_options(entry.options)`); `should_expose(entity_id)` → `is_shared`; `generate_alexa_id(entity_id)` → prima la mappa `self.known_ids: dict[str, str]` (riempita dal SyncManager, task 8), poi `stable_alexa_id`; `async_get_access_token`, `async_invalidate_access_token`, `async_accept_grant` delegati a `BridgeAuth`; `on_authorized: Callable[[], Awaitable[None]] | None = None`, chiamato da `set_authorized` (override che chiama `super()`) quando l'autorizzazione passa da `False` a `True`.

- [ ] **Step 1: Scrivi i test che falliscono:**
  - `test_uses_own_storage_keys`: dopo `async_initialize` e `set_authorized(True)` (proactive mode patchata), in `hass_storage` c'è `"alexa_bridge"` e non c'è `"alexa"`; `BridgeAuth(...)._store.key == "alexa_bridge_auth"`
  - `test_defaults_locale_and_endpoint`: entry senza locale/endpoint → `"it-IT"` e l'endpoint EU
  - `test_should_expose_follows_options`: options `domains=["light"]` → `light.x` sì, `switch.y` no
  - `test_generate_alexa_id_prefers_known_ids`: `known_ids={"light.gone": "ha-abc"}` → `"ha-abc"` per un'entità non più nel registro
  - `test_on_authorized_called_once_on_flip`: due `set_authorized(True)` consecutivi → callback chiamata una volta
- [ ] **Step 2:** `pytest tests/test_config.py -v` → FAIL.
- [ ] **Step 3:** Implementa `config.py`.
- [ ] **Step 4:** `pytest tests/test_config.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: BridgeConfig sul motore Alexa di HA con store propri`.

---

### Task 5: Vista HTTP con traduzione degli ID

**Files:**
- Create: `custom_components/alexa_bridge/view.py`
- Test: `tests/test_view.py`

**Interfaces:**
- Consumes: `BridgeConfig` (task 4); `entity_id_from_alexa_id`, `legacy_alexa_id` (task 3).
- Produces: `class BridgeSmartHomeView(HomeAssistantView)` con `url = VIEW_URL`, `name = "api:alexa_bridge:smart_home"`, `requires_auth = True`, `__init__(self, config: BridgeConfig)`, `async def post(self, request) -> web.Response | bytes`.

`post`: legge il JSON; se `directive.endpoint.endpointId` esiste, lo traduce con `entity_id_from_alexa_id` → `legacy_alexa_id(entity_id)` (ID sconosciuto: si lascia invariato, così il motore risponde `NO_SUCH_ENDPOINT`); chiama `homeassistant.components.alexa.smart_home.async_handle_message(hass, config, message, context=Context(user_id=user.id))`; nella risposta riporta `event.endpoint.endpointId` all'ID ricevuto in ingresso. Risposta `None` → `b""`.

- [ ] **Step 1: Scrivi i test che falliscono** (con `hass_client` e messaggi Alexa v3 in `tests/fixtures/` — Discover, TurnOn, ReportState):
  - `test_discovery_returns_only_selected`: 2 luci + 1 switch, `domains=["light"]` → 2 endpoint, `endpointId` che iniziano con `"ha-"`
  - `test_turn_on_with_stable_id_calls_service`: TurnOn su `"ha-<id>"` → chiamata `light.turn_on` registrata con `async_mock_service`; risposta `event.endpoint.endpointId == "ha-<id>"`
  - `test_unknown_endpoint_returns_no_such_endpoint`: `payload.type == "NO_SUCH_ENDPOINT"`
  - `test_not_shared_entity_rejected`: TurnOn su uno switch non selezionato → `NO_SUCH_ENDPOINT`
  - `test_requires_auth`: senza token → 401
- [ ] **Step 2:** `pytest tests/test_view.py -v` → FAIL.
- [ ] **Step 3:** Implementa `view.py`.
- [ ] **Step 4:** `pytest tests/test_view.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: vista smart home con endpointId stabili`.

---

### Task 6: Config flow e options flow con conteggio

**Files:**
- Create: `custom_components/alexa_bridge/config_flow.py`, `strings.json`, `translations/en.json`, `translations/it.json`
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `selectable_domains`, `Selection`, `shared_entity_ids` (task 2).
- Produces:
  - `ConfigFlow` (istanza unica: `async_set_unique_id(DOMAIN)`): step `user` con `client_id`, `client_secret` (selettore password), `locale` (default `it-IT`), `endpoint` (default EU). Crea la entry con `options` vuote (nessun dominio selezionato).
  - `OptionsFlow`: step `init` con `domains` (`SelectSelector` multiplo da `selectable_domains()`), `include_entities` ed `exclude_entities` (`EntitySelector` multiplo); poi step `confirm` che mostra `{count}` = `len(shared_entity_ids(...))` con la selezione proposta e salva solo alla conferma.
  - Testo italiano dello step `confirm` (description): `"Con questa selezione condividerai {count} entità con Alexa. Le entità che escono saranno rimosse da Alexa."`

- [ ] **Step 1: Scrivi i test che falliscono:**
  - `test_user_flow_creates_entry_with_defaults`: data con locale `it-IT` ed endpoint EU, `options == {}`
  - `test_single_instance`: secondo flow → abort `already_configured`
  - `test_options_flow_shows_count_then_saves`: 2 luci, `domains=["light"]` → step `confirm` con `description_placeholders["count"] == "2"`; dopo la conferma `entry.options[CONF_DOMAINS] == ["light"]`
  - `test_options_domains_exclude_blocked`: le opzioni del selettore non contengono `automation`
- [ ] **Step 2:** `pytest tests/test_config_flow.py -v` → FAIL.
- [ ] **Step 3:** Implementa i flow e le stringhe (en + it).
- [ ] **Step 4:** `pytest tests/test_config_flow.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: config flow e selezione da interfaccia con conteggio`.

---

### Task 7: Avvio dell'integrazione e convivenza

**Files:**
- Modify: `custom_components/alexa_bridge/__init__.py`
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `BridgeConfig` (task 4), `BridgeSmartHomeView` (task 5).
- Produces:
  - `entry.runtime_data: BridgeRuntime` (`@dataclass` con `config: BridgeConfig`, `sync: SyncManager | None`; il SyncManager arriva nel task 8)
  - La vista si registra **una volta per processo** (le viste HA non si deregistrano): flag in `hass.data[DOMAIN]`; la vista legge la config corrente da `hass.data[DOMAIN]["config"]`, che `async_setup_entry` imposta e `async_unload_entry` azzera; con config `None` → risposta `BRIDGE_UNREACHABLE` (`async_handle_message(..., enabled=False)`).
  - Se `config.should_report_state` → `async_enable_proactive_mode()`; l'unload chiama `async_disable_proactive_mode()` e `async_deinitialize()`.
  - Problema in Riparazioni `stock_alexa_configured` se `"alexa"` è in `hass.config.components` (testo it: `"È configurata anche l'integrazione Alexa di serie: rimuovi il blocco alexa: dal configuration.yaml per evitare risposte doppie."`).

- [ ] **Step 1: Scrivi i test che falliscono:**
  - `test_setup_registers_view_and_unload`: dopo il setup la POST risponde; dopo l'unload la stessa POST dà `BRIDGE_UNREACHABLE`; nuovo setup → risponde di nuovo (nessun errore di doppia registrazione)
  - `test_repair_issue_when_stock_alexa_loaded`: con `hass.config.components.add("alexa")` → il problema esiste in `ir.async_get(hass)`
- [ ] **Step 2:** `pytest tests/test_init.py -v` → FAIL.
- [ ] **Step 3:** Implementa il setup/unload.
- [ ] **Step 4:** `pytest -v` (intera suite) → PASS.
- [ ] **Step 5:** Commit `feat: avvio integrazione, vista unica e avviso di convivenza`.

---

### Task 8: Sincronizzazione con Alexa e ciclo di vita

**Files:**
- Create: `custom_components/alexa_bridge/sync.py`
- Modify: `custom_components/alexa_bridge/__init__.py` (avvio/stop del SyncManager, `async_remove_entry`)
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `BridgeConfig.known_ids`, `shared_entity_ids`, `is_shared`, `stable_alexa_id`; `async_send_add_or_update_message`, `async_send_delete_message` da `homeassistant.components.alexa.state_report`.
- Produces:
  - `class SyncManager`: `__init__(self, hass, config: BridgeConfig)`; `async_load()` carica `Store(STORE_SYNC)` = `{"synced": {entity_id: alexa_id}}` e riempie `config.known_ids`; `async_start()` registra, **a HA avviato** (`homeassistant.helpers.start.async_at_started`), una prima `async_reconcile()` e l'ascolto di `EVENT_ENTITY_REGISTRY_UPDATED`; `async_stop()`.
  - `async def async_reconcile(self) -> None`: desiderate = `shared_entity_ids`; **aggiunte** = desiderate meno sincronizzate → AddOrUpdate; **uscite** = sincronizzate per cui `is_shared(...)` è `False` **e** (c'è uno stato **oppure** una voce di registro) → Delete. Le sincronizzate senza stato né registro restano (avvio). Aggiorna e salva lo store solo per le parti inviate con successo.
  - Eventi di registro: `remove` di un'entità sincronizzata → Delete con l'ID salvato, poi rimozione dallo store; `update` con `old_entity_id` → sposta la chiave nello store (ID invariato) e invia AddOrUpdate.
  - Cambio opzioni (`entry.add_update_listener`) → `async_reconcile()` senza ricaricare l'integrazione.
  - Autorizzazione appena concessa (`config.on_authorized`, task 4, dopo il collegamento dall'app) → `async_reconcile()`.
  - Se `config.authorized` è `False` o l'invio dà 401/403: niente eccezioni, problema in Riparazioni `proactive_not_authorized` (it: `"Alexa non ha ancora autorizzato l'invio degli eventi: abilita 'Send Alexa Events' nella skill e ricollega l'account dall'app Alexa."`); il problema si cancella al primo invio riuscito.
  - `async_remove_entry(hass, entry)`: crea una `BridgeConfig` e un `SyncManager` temporanei, invia Delete per tutto lo store, poi cancella i tre store; errori di rete o di token → log e si prosegue.

- [ ] **Step 1: Scrivi i test che falliscono** (`aioclient_mock` sull'endpoint eventi EU; token LWA patchato su `BridgeAuth.async_get_access_token`):
  - `test_first_reconcile_adds_selected`: 2 luci selezionate → un AddOrUpdate con 2 endpoint; store con 2 voci
  - `test_deselect_sends_delete`: tolto `light` dalle opzioni → DeleteReport con gli ID `ha-` salvati
  - `test_startup_missing_state_not_deleted`: store con `light.lenta` (nessuno stato, nessun registro) → nessun DeleteReport, la voce resta
  - `test_registry_remove_sends_delete_with_saved_id`: rimozione dal registro di un'entità sincronizzata → DeleteReport con l'ID salvato
  - `test_rename_keeps_id`: rinomina entity_id → nessun DeleteReport, la voce dello store passa al nuovo entity_id con lo stesso ID
  - `test_unauthorized_creates_repair_issue`: `authorized=False` → nessuna richiesta HTTP, problema `proactive_not_authorized` presente
  - `test_remove_entry_deletes_all_and_clears_stores`: DeleteReport con tutti gli ID; `hass_storage` senza le tre chiavi
  - `test_remove_entry_without_token_does_not_raise`: token che solleva → la rimozione finisce, store cancellati
  - `test_authorization_triggers_reconcile`: `set_authorized(True)` partendo da `False` → AddOrUpdate inviato e problema `proactive_not_authorized` cancellato
- [ ] **Step 2:** `pytest tests/test_sync.py -v` → FAIL.
- [ ] **Step 3:** Implementa `sync.py` e il collegamento in `__init__.py`.
- [ ] **Step 4:** `pytest -v` (intera suite) → PASS.
- [ ] **Step 5:** Commit `feat: sincronizzazione Add/Delete con Alexa e ciclo di vita`.

---

### Task 9: CI e validazioni HACS/hassfest

**Files:**
- Create: `.github/workflows/tests.yml`, `.github/workflows/validate.yml`

- [ ] **Step 1:** `tests.yml`: su push, pull_request e `schedule` settimanale (`cron: "0 5 * * 1"`); matrice `ha: [stable, beta]`. `stable` installa `requirements_test.txt`; `beta` installa `pytest-homeassistant-custom-component` con `--pre` all'ultima versione. Esegue `pytest -v`.
- [ ] **Step 2:** `validate.yml`: `home-assistant/actions/hassfest@master` e `hacs/action@main` con `category: integration`.
- [ ] **Step 3:** Verifica in locale la sintassi con `actionlint` se disponibile, altrimenti alla prima esecuzione dopo il push (task 11).
- [ ] **Step 4:** Commit `ci: test contro HA stabile e beta, validazione hassfest e HACS`.

---

### Task 10: Lambda, template SAM e guide

**Files:**
- Create: `lambda/lambda_function.py`, `lambda/template.yaml`, `lambda/tests/test_lambda_function.py`, `docs/setup-aws.md`, `docs/setup-skill.md`, `docs/collaudo.md`
- Modify: `README.md`

**Interfaces:**
- Produces: `def lambda_handler(event: dict, context) -> dict` in `lambda/lambda_function.py`, solo libreria standard (`urllib`). Variabili d'ambiente: `BASE_URL` (obbligatoria, senza `/` finale), `HA_PATH` (default `/api/alexa_bridge/smart_home`), `NOT_VERIFY_SSL`, `DEBUG`, `LONG_LIVED_ACCESS_TOKEN` (usato solo se `DEBUG` è attivo e la direttiva non porta un token). Token preso, nell'ordine, da `directive.endpoint.scope.token`, `directive.payload.grantee.token`, `directive.payload.scope.token`. Errori HTTP 401/403 → evento `Alexa.ErrorResponse` con `INVALID_AUTHORIZATION_CREDENTIAL`; altri errori → `INTERNAL_ERROR`. Payload `payloadVersion` diverso da `"3"` → `ValueError`.

- [ ] **Step 1: Scrivi i test che falliscono** (`urllib.request.urlopen` patchato):
  - `test_forwards_to_bridge_path_with_bearer`: URL `BASE_URL + "/api/alexa_bridge/smart_home"`, header `Authorization: Bearer <token>`, body uguale all'evento; ritorna il JSON di HA
  - `test_token_from_grantee_for_accept_grant`
  - `test_401_maps_to_invalid_authorization_credential`
  - `test_long_lived_token_only_with_debug`: senza `DEBUG` il token di test non si usa
  - `test_base_url_trailing_slash_rejected`
- [ ] **Step 2:** `pytest lambda/tests -v` → FAIL.
- [ ] **Step 3:** Implementa `lambda_function.py`.
- [ ] **Step 4:** `pytest lambda/tests -v` → PASS.
- [ ] **Step 5:** `template.yaml` (SAM): funzione `arm64`, runtime Python più recente supportato da Lambda, `Timeout: 10`, parametri `BaseUrl` e `SkillId` (nessun default reale), env `BASE_URL: !Ref BaseUrl`, evento `AlexaSmartHome` con `SkillId: !Ref SkillId`; output ARN. Verifica: `sam validate --lint` (dopo l'installazione di SAM del task 12; fino ad allora si segna come da verificare).
- [ ] **Step 6:** Guide, con segnaposto e nessun dato reale:
  - `docs/setup-aws.md`: installazione di AWS CLI e SAM su Windows; utente IAM di deploy con permessi minimi (CloudFormation, Lambda, IAM PassRole/CreateRole limitati allo stack, S3 per gli artefatti SAM); `aws configure --profile ha-alexa`; `sam deploy --guided --region eu-west-1` (scrive `samconfig.toml`, ignorato da git).
  - `docs/setup-skill.md`: skill Smart Home, lingua Italiano, endpoint ARN EU; Account Linking con i valori dei Global Constraints e `<HA_URL>/auth/authorize` e `<HA_URL>/auth/token`; permesso Send Alexa Events e dove copiare client id/secret nel config flow; ordine: selezione in HA **prima** del collegamento; PIN vocale per le serrature.
  - `docs/collaudo.md`: i passi 0–7 della spec §10 come checklist.
  - `docs/script-gemelli.md`: modello YAML di uno script che avvia un'automazione (`automation.trigger` con `skip_condition: false`) e come condividerlo ("Alexa, attiva …"); spec §6.5.
  - README: installazione via HACS (repository personalizzato), configurazione, link alle guide.
- [ ] **Step 7:** Commit `feat: lambda ponte, template SAM e guide di installazione`.

---

### Task 11: Pubblicazione (con conferma di Paolo)

- [ ] **Step 1:** Controllo prima di pubblicare, su **tutta la storia** (non solo sui file attuali). Il dominio di casa non si scrive nel repo: si mette in una variabile al momento, in bash:
  ```bash
  read -r HOME_DOMAIN   # digitato a mano, es. il dominio di <HA_URL>
  : "${HOME_DOMAIN:?dominio mancante}"
  git log -p --all | grep -nF -e "$HOME_DOMAIN"
  git log -p --all | grep -nE "192\.168\.[0-9]+\.[0-9]+|amzn1\.ask\.skill\.[0-9a-f-]{8}|arn:aws:lambda:[a-z0-9-]+:[0-9]{12}"
  ```
  → nessun risultato da entrambi. Il modello non trova sé stesso (nel testo i punti sono `\.` e dopo `lambda:` c'è `[`) né i segnaposto `<HA_URL>`, `<HA_LAN_IP>`, `<SKILL_ID>`.
- [ ] **Step 2:** Pre-push (docs → test → debug → git): suite completa `pytest -v` e `pytest lambda/tests -v` in WSL → PASS.
- [ ] **Step 3:** **Chiedi conferma a Paolo**, poi `gh repo create paolobets/ha-alexa-skill --public --source . --push`.
- [ ] **Step 4:** Attendi la CI: `tests` (stable e beta) e `validate` verdi. Correggi e ripeti se rosse.
- [ ] **Step 5:** **Chiedi conferma**, poi tag `v0.1.0` e release GitHub (`gh release create v0.1.0 --generate-notes`).

---

### Task 12: Messa in opera e collaudo dal vivo (con Paolo)

Ogni passo che tocca HA di produzione, AWS o la console Amazon: prima conferma, segreti solo via file locale.

- [ ] **Step 1:** Collaudo §10 passo 0: controlli sul tunnel/proxy davanti a HA (WAF, protezione anti-bot, blocchi paese/ASN) e `trusted_proxies`/`ip_ban` in HA. Esito annotato in `docs/collaudo.md` (senza dati sensibili).
- [ ] **Step 2:** HACS → repository personalizzato → installa `alexa_bridge` v0.1.0 → riavvio HA (conferma).
- [ ] **Step 3:** Paolo crea la skill seguendo `docs/setup-skill.md` fino allo Skill ID; Claude esegue `docs/setup-aws.md` (installazione CLI) e Paolo inserisce le chiavi; `sam deploy --guided`; ARN nella skill.
- [ ] **Step 4:** Aggiungi l'integrazione in HA con client id/secret (Paolo). Selezione iniziale; il conteggio è quello atteso (passo 1 di §10).
- [ ] **Step 5:** Test Discovery della Lambda con token di test e `DEBUG` (passo 2): risponde esattamente con le entità selezionate. Revisione dell'elenco con Paolo e correzioni della selezione.
- [ ] **Step 6:** Collegamento dall'app Alexa (login HA), scoperta; cancellazione a mano degli orfani con nome uguale (passo 3).
- [ ] **Step 7:** Passi 4–6 di §10: prove a voce per dominio (temperatura, script, PIN serratura), report proattivi e routine da un contatto, rimozione e rinomina, riavvio di HA senza cancellazioni.
- [ ] **Step 8:** Passo 7: rimuovi `LONG_LIVED_ACCESS_TOKEN` e `DEBUG` dalla Lambda con `update-function-configuration` mantenendo `BASE_URL`/`HA_PATH` (`docs/setup-aws.md` passo 7.4; `sam deploy` non le toglie), verifica con `get-function-configuration --query Environment`, revoca il token in HA.
- [ ] **Step 9:** Aggiorna la memoria di progetto e `docs/collaudo.md` con l'esito; commit `docs: esito collaudo v0.1.0` (push con conferma).
