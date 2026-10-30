# Avviare un'automazione a voce: lo script gemello

Alexa non può *avviare* un'automazione (la vede come interruttore
abilita/disabilita), e per questo il dominio `automation` non è selezionabile.
Il modo giusto è uno **script gemello**: uno script che avvia l'automazione, da
condividere con Alexa.

## Modello

```yaml
script:
  avvia_nome:
    alias: "Nome pronunciabile"
    icon: mdi:play
    sequence:
      - action: automation.trigger
        target:
          entity_id: automation.tua_automazione
        data:
          skip_condition: false
```

- `skip_condition: false` fa rispettare le condizioni dell'automazione: lo script
  la avvia come se l'evento fosse accaduto, ma solo se le condizioni sono vere.
  Metti `true` solo se vuoi forzare l'esecuzione ignorandole.
- In alternativa, lo script può contenere direttamente le stesse azioni
  dell'automazione.
- L'`alias` è il nome che Alexa pronuncerà: scegline uno breve e chiaro
  (Alexa riceve un solo nome: il primo alias dell'entità in HA, altrimenti il
  nome).

## Condivisione

1. In HA: *Alexa Bridge > Configura* e seleziona lo script (dominio `script`, o
   tra le entità aggiuntive).
2. Alexa rileva il nuovo dispositivo da sola (aggiunta automatica); se non
   comparisse, chiedi "Alexa, trova i miei dispositivi".
3. A voce: **"Alexa, attiva Nome pronunciabile"** (o "accendi ..."). "Spegni ..."
   ferma lo script.

Uno script per ogni automazione: tieni l'elenco degli script gemelli accanto alle
tue automazioni, per non esporre ad Alexa più del necessario.
