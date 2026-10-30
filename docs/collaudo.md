# Collaudo dal vivo

Checklist da eseguire **in ordine** dopo l'installazione. Il lavoro è finito
solo quando tutti i punti sono verificati dal vivo.

- [ ] **0. Controlli d'accesso**
  - [ ] Nessuna regola del proxy/CDN davanti a HA (WAF, Bot Fight Mode, blocchi
        per paese o ASN) sfida o blocca chiamate provenienti da AWS/Amazon verso
        `<HA_URL>`.
  - [ ] In HA `trusted_proxies` è corretto per il tunnel o il reverse proxy,
        così un eventuale `ip_ban` non banna l'IP del proxy stesso.
- [ ] **1. Integrazione installata** in HA (vedi README), config flow completato
      e **selezione iniziale** fatta. Il contatore mostrato in conferma coincide
      con il numero atteso.
- [ ] **2. Lambda contro HA** con un evento di prova `Discover` e un token di
      prova: aggiungi `DEBUG` e `LONG_LIVED_ACCESS_TOKEN` **mantenendo**
      `BASE_URL` e `HA_PATH` ([setup-aws.md](setup-aws.md), passi 7.1-7.2),
      poi invoca la funzione (passo 7.3): la risposta contiene esattamente le
      entità selezionate.
- [ ] **3. Collegamento account** dall'app Alexa (login HA, con la verifica a due
      fattori se attiva) e scoperta dei dispositivi.
  - [ ] Confronto con i dispositivi orfani ancora in Alexa: quelli con **nome
        uguale** a un'entità condivisa si cancellano a mano prima delle prove a
        voce.
- [ ] **4. Prove a voce**: una per ogni dominio condiviso, comprese temperatura,
      script e PIN vocale (serrature).
- [ ] **5. Report proattivi**
  - [ ] Cambio di stato da HA: l'app Alexa si aggiorna.
  - [ ] Una routine Alexa si attiva da un binary_sensor di contatto.
- [ ] **6. Rimozione automatica**
  - [ ] Togli un'entità dalla selezione: sparisce dall'app Alexa.
  - [ ] Rimettila: ricompare senza nuova scoperta (senza gruppo né routine:
        atteso).
  - [ ] Rinomina un `entity_id`: resta lo stesso dispositivo in Alexa.
  - [ ] Riavvia HA: nessun dispositivo viene cancellato.
- [ ] **7. Pulizia**: rimuovi `LONG_LIVED_ACCESS_TOKEN` e `DEBUG` dalla funzione
      con `aws lambda update-function-configuration`, mantenendo `BASE_URL` e
      `HA_PATH` ([setup-aws.md](setup-aws.md), passo 7.4). **Non** basta
      `sam deploy`: le variabili aggiunte a mano restano.
  - [ ] `aws lambda get-function-configuration --function-name <FUNCTION_NAME> --profile ha-alexa --region eu-west-1 --query Environment`
        mostra solo `BASE_URL` e `HA_PATH`.
  - [ ] **Revoca il token** di prova in HA (profilo utente > Sicurezza).
