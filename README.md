# Contadores

Repo de trabajo para el flujo de captación y seguimiento de `Contadores`.
El producto esta migrando a una plataforma de funnels por nicho: `contadores`
es el primer funnel operativo, y otros nichos se configuran desde tools de
agente, desde la UI o desde un archivo JSON persistente.

La arquitectura objetivo de plataforma completa vive en
`wiki/platform-architecture.md`.

## Estructura

- `src/`: código de producto.
- `wiki/`: documentación, skills y referencias de trabajo.
- `media/`: materiales audiovisuales, decks y archivos de soporte.
- `abogados/`: materiales, presentaciones y skills entrenadas del funnel de abogados.
- `data/`: estado local persistente. No se commitea.

## CRM portable por funnels

El CRM debe poder levantarse en un server nuevo aunque todavia no exista un
nicho real. Un primer arranque limpio no necesita `data/funnels.json`: el
backend carga `config/default-funnels.json`, muestra los funnels versionados y
los agentes o la UI pueden crear/editar funnels sobre el mismo override. El
sistema queda vivo; `/api/runtime` marca `ready=true` cuando algun funnel de
campaña habilitado tiene `sheet_url` y `sheet_gid`.

La fuente de verdad para nuevos usuarios tiene dos capas:

- `FUNNELS_SEED_CONFIG_PATH` o `config/default-funnels.json`, como seed
  versionado.
- `FUNNELS_CONFIG_PATH` o `data/funnels.json`, como override editable por server.

Esas capas las usan la UI, el bot y Codex. No hay un estado visual oculto: si
se crea un funnel desde una tool de agente se persiste en el override, y si un
operador edita desde la UI, los agentes leen el mismo contenido.

Ver el menu de funnels y errores no fatales del archivo:

```bash
curl http://127.0.0.1:8000/api/funnels
```

Ver readiness portable:

```bash
curl http://127.0.0.1:8000/api/runtime
```

Ver eventos recientes de plataforma:

```bash
curl http://127.0.0.1:8000/api/platform/events
```

`platform_events` es append-only y arranca registrando los WhatsApp outbound
encolados. Es la base para observar sheet import, mensajes, AI, scheduling,
conversion, ads, delivery y client updates sin depender de logs sueltos.

`/api/runtime` no expone URLs de sheets ni secretos. Expone `ready`, los
funnels de campaña habilitados, los funnels con sheet lista y los problemas de
setup. Un funnel incompleto no rompe el server; simplemente aparece como
pendiente de configurar.

### Configurar sin UI, agent-native

Los agentes autonomos no tienen que pedirle al operador que abra la UI para
configurar el platform. Deben usar el tool runner auditado:

```bash
uv run python -m backend.ai.codex_agent_runtime call \
  --run-id platform-config-001 \
  --tool read_platform_config \
  --arguments-json '{"include_schema":true}'
```

Crear o actualizar un funnel text-first:

```bash
uv run python -m backend.ai.codex_agent_runtime call \
  --run-id platform-config-001 \
  --tool configure_text_offer_funnel \
  --arguments-json '{"funnel_id":"dentistas","label":"Dentistas","enabled":false,"sheet_url":"https://docs.google.com/spreadsheets/d/.../export?format=csv&gid=0","sheet_gid":"0","opener_template_name":"dentistas_opener_v1","opener_text":"Hola {nombre}, vi que dejaste tus datos para recibir mas pacientes.","offer_text":"Son 599 USD mensuales. A cambio recibis consultas directo a tu WhatsApp.","alert_emails":["operador@example.com"],"reason":"Nuevo funnel creado por agente."}'
```

Configurar delivery de leads de un cliente:

```bash
uv run python -m backend.ai.codex_agent_runtime call \
  --run-id platform-config-001 \
  --tool upsert_client_lead_delivery_source \
  --arguments-json '{"source_id":"cliente-leads","label":"Cliente leads","enabled":true,"sheet_url":"https://docs.google.com/spreadsheets/d/.../export?format=csv&gid=0","sheet_gid":"0","recipient_name":"Cliente","recipient_phone":"+5491111111111","context_field_mapping":{"Servicio":"servicio"},"reason":"Delivery configurado por agente."}'
```

El ciclo operativo tambien se puede mover por tools auditadas, sin depender de
formularios:

- `create_platform_meeting` y `attach_meeting_transcript`: scheduling,
  transcript y handoff post-conversion.
- `upsert_client_profile`: conocimiento revisado del cliente.
- `stage_ad_campaign`, `stage_creative_asset`, `stage_meta_publish_plan` y
  `stage_meta_publish_attempt`: ads y publicacion Meta en modo
  staged/aprobable.
- `create_client_update`: actualizaciones de 24 horas para clientes.
- `ask_human_question` y `answer_human_question`: dudas a Facundo/operador con
  contexto, accion por defecto y memoria reutilizable.

Flujo Meta agent-native:

1. `stage_ad_campaign` guarda el objetivo comercial, presupuesto y angulos.
2. `stage_creative_asset` guarda prompts, archivos y referencias de imagen/video.
3. `stage_meta_publish_plan` arma el plan tipado `Campaign -> Ad Set ->
   Ad/Creative`, siempre en modo `PAUSED` y sin writes externos.
4. Si faltan `ad_account_id`, `page_id`, destino WhatsApp/form, presupuesto,
   targeting o creatividades, el resultado incluye `required_before_live_publish`
   y el agente debe usar `ask_human_question` en vez de inventar datos.
5. `stage_meta_publish_attempt` queda para payloads crudos, respuestas de Meta o
   ejecuciones futuras hechas por el publicador aprobado.

Ejemplo de plan Meta staged:

```bash
uv run python -m backend.ai.codex_agent_runtime call \
  --run-id meta-plan-001 \
  --tool stage_meta_publish_plan \
  --arguments-json '{"campaign_id":"campaign-123","client_id":"client-123","funnel_id":"abogados","ad_account_id":"act_123","campaign_name":"Abogados - WhatsApp","objective":"OUTCOME_LEADS","destination":{"destination_type":"whatsapp","page_id":"page_123","whatsapp_phone_number_id":"wa_phone_123"},"ad_sets":[{"name":"Despidos CABA","budget_daily_usd":15,"targeting":{"geo_locations":{"countries":["AR"]}},"ads":[{"name":"Te despidieron","creative":{"creative_asset_id":"asset-123","primary_text":"Si te despidieron, manda tu caso por WhatsApp.","headline":"Te despidieron?"}}]}],"idempotency_key":"meta-plan-client-123-v1"}'
```

Ejemplo de duda agent-native:

```bash
uv run python -m backend.ai.codex_agent_runtime call \
  --run-id platform-config-001 \
  --tool ask_human_question \
  --arguments-json '{"workflow":"meta_publish","target_type":"ad_campaign","target_id":"campaign-123","context_summary":"Meta pide confirmar categoria especial.","trying_to_do":"Publicar la campana del cliente.","question":"Uso categoria especial o dejo la campana staged?","options":["categoria especial","dejar staged"],"default_action":"Dejar staged si no hay respuesta en 4 minutos."}'
```

Validar antes de activar:

```bash
uv run python -m backend.ai.codex_agent_runtime call \
  --run-id platform-config-001 \
  --tool validate_platform_config \
  --arguments-json '{"include_disabled":true}'
```

Todas esas llamadas quedan auditadas en `agent_tool_calls`,
`data/agent-runs/<run-id>/tool_calls.jsonl` y `platform_events`. La UI queda
como cockpit opcional para revisar, no como prerequisito de configuracion.

### Crear un funnel visualmente

En la UI:

1. Entrar al CRM.
2. Usar `+ Funnel`.
3. Cargar id, nombre, sheet, oferta, mensajes, templates, texto de offer,
   reunion, alertas y IDs de anuncios.
4. Guardar.
5. Dejar `enabled=false` mientras falten templates, sheet u offer.
6. Activar `enabled=true` cuando el funnel pueda correr en produccion.

La UI muestra un checklist si el funnel no tiene los campos minimos para operar.
Eso es intencional: el objetivo es que un usuario nuevo vea que falta antes de
que el bot intente correr una campaña incompleta.

### Crear un funnel por archivo

Tambien se puede generar un archivo inicial de manera programatica:

```bash
uv run python src/scripts/funnel_config_template.py dentistas \
  --label "Dentistas" \
  --sheet-url "https://docs.google.com/spreadsheets/d/..." \
  --sheet-gid "0" \
  --offer-text "Son 599 USD mensuales. A cambio recibis consultas directo a tu WhatsApp." \
  --calendly-base-url "https://calendly.com/tu-equipo/dentistas" \
  --alert-email "operador@example.com" \
  --whatsapp-referral-source-id "120000000000000000" \
  --output data/funnels.json
```

El helper genera un funnel deshabilitado salvo que se agregue `--enabled`. Esa
es la forma segura de portar el CRM: primero se carga el archivo, se valida en
la UI y recien despues se habilita el funnel.

### Seed y overrides

El CRM carga funnels en dos capas:

- `config/default-funnels.json`: seed versionado y neutral. Sirve para que un
  server nuevo arranque con el menu de funnels visible, pero no trae sheets,
  calendarios, emails personales ni IDs de anuncios de otro cliente.
- `data/funnels.json`: override local editable por UI/Codex. Vive en el volumen
  persistente y pisa los funnels del seed por `id`.

Si queres portar esto a otra persona, cambia primero el seed si queres una base
de producto versionada, o copia un `data/funnels.json` ya preparado si queres
mantener esa configuracion solo en ese server.

### Contrato de funnels JSON

Formato base:

```json
{
  "version": 1,
  "funnels": [
    {
      "id": "dentistas",
      "label": "Dentistas",
      "kind": "campaign",
      "enabled": false,
      "offer_version": "mission-2026-05-30",
      "offer_price_usd": 599,
      "offer_payment_model": "monthly",
      "offer_summary": "Marketing y anuncios para recibir interesados directo al WhatsApp; sitio incluido si hace falta.",
      "offer_includes_website": true,
      "default_campaign_count": 3,
      "default_daily_ad_budget_usd": null,
      "sheet_url": "https://docs.google.com/spreadsheets/d/...",
      "sheet_gid": "0",
      "sheet_source_filter": null,
      "sheet_poll_seconds": 30,
      "template_language": "es",
      "opener_text": "Hola {nombre}, completaste el formulario sobre como podemos ayudarte. Es correcto?",
      "opener_template_name": "dentistas_intro_nombre_pais_es_v1",
      "opener_followup_text": "Queria compartirte informacion sobre la propuesta que viste en el anuncio.",
      "opener_followup_template_name": "dentistas_opener_followup_24h_es_v1",
      "manual_ping_text": "Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion",
      "manual_ping_template_name": "dentistas_manual_ping_es_v1",
      "loom_intro_text": "",
      "loom_url": "",
      "video_check_text": "te interesa que lo veamos en una llamada corta?",
      "calendly_intro_text": "Para avanzar, decime dia, horario y email y coordinamos la llamada:",
      "calendly_base_url": "https://calendly.com/tu-equipo/dentistas",
      "alert_emails": ["operador@example.com"],
      "whatsapp_referral_source_ids": ["120000000000000000"],
      "initial_reply_quiet_seconds": 30,
      "post_loom_min_seconds": 600,
      "post_loom_quiet_seconds": 30,
      "strategies": [
        {
          "step": "loom",
          "id": "text_offer_599",
          "label": "Text offer 599",
          "weight": 100,
          "delivery": "text",
          "sequence_step": "text_offer",
          "message_text": "Son 599 USD mensuales. A cambio recibis oportunidades de clientes potenciales directo a tu WhatsApp. Eso lo logramos con una pagina profesional y campanas enfocadas. Si te interesa, lo vemos en una llamada corta y revisamos si tiene sentido para tu caso.",
          "media_type": null,
          "media_path": null,
          "media_caption": null
        }
      ]
    }
  ]
}
```

Campos que hay que pensar antes de activar un funnel:

- `id`: slug estable. No cambiarlo despues de crear leads, porque los leads se
  filtran por ese id.
- `label`: nombre que ve el operador en el menu.
- `kind`: `campaign` corre automatizacion; `inbox` solo junta conversaciones sin
  campaña.
- `enabled`: mantener en `false` hasta tener sheet, templates y offer listos.
- `offer_*`: fuente comercial del funnel. El offer activo del mission es `599`
  USD mensuales, sitio incluido si hace falta y campanas enfocadas para llevar
  interesados al WhatsApp del cliente.
- `sheet_url` y `sheet_gid`: fuente de leads. Son lo minimo para que el runtime
  marque listo algun funnel de campaña.
- `sheet_source_filter`: filtro opcional si una misma sheet trae varios origenes.
- `sheet_poll_seconds`: minimo 30. Usar mas alto si la sheet es lenta o muy
  grande.
- `template_language`: idioma de templates de WhatsApp, normalmente `es`.
- `opener_text` y `opener_template_name`: primer contacto. Si se inicia fuera de
  la ventana de 24h, el template debe existir y estar aprobado en Meta.
- `opener_followup_text` y `opener_followup_template_name`: follow-up si no
  responde.
- `manual_ping_text` y `manual_ping_template_name`: reapertura manual desde el
  CRM cuando el operador quiere retomar.
- `loom_intro_text`: texto opcional previo al offer. El offer nuevo no tiene
  Loom, por eso el seed lo deja vacio.
- `loom_url`: referencia opcional si tambien existe version Loom.
- `video_check_text`: pregunta corta de seguimiento cuando no responde al offer.
- `calendly_intro_text`: texto manual para pedir o confirmar datos de reunion.
- `calendly_base_url`: link legacy de agenda del funnel. No se fuerza desde Python;
  si cambia por nicho o por cliente, se cambia en el archivo.
- `alert_emails`: emails del administrador u operadores de este server para
  avisos humanos y fallas runtime. El seed portable lo deja en `[]`; antes de
  produccion hay que cargar correos del cliente/equipo real.
- `whatsapp_referral_source_ids`: IDs `referral.source_id` de anuncios
  Click-to-WhatsApp que deben caer en este funnel.
- `initial_reply_quiet_seconds`: espera antes de reaccionar a una primera
  respuesta.
- `post_loom_min_seconds`: espera minima despues de mandar el offer.
- `post_loom_quiet_seconds`: silencio necesario antes de clasificar post-offer.
- `strategies`: estrategias por paso. El default operativo del mission es
  `text_offer_599` con `delivery=text` y `sequence_step=text_offer`. Si un
  funnel futuro tiene video, puede configurar una estrategia `delivery=video`
  con `media_path` dentro de `data/`.

Consejos de portabilidad:

- No hardcodear nichos nuevos en Python si entran en este contrato.
- Guardar en git solo configuraciones que sean seguras para reutilizar como
  seed. `data/funnels.json` sigue siendo el estado editable de cada server.
- No versionar defaults personales como emails de admin, calendarios privados,
  sheets de otro cliente ni IDs reales de anuncios en el seed portable.
- Si el override tiene JSON invalido o un funnel mal formado, `/api/funnels`
  sigue respondiendo con el seed valido y devuelve `config_errors`.
- Para portar a otra persona, preparar su `.env`, `auth.toml`, `data/funnels.json`,
  credenciales de Google/WhatsApp y cualquier material de Workstation que esa
  persona vaya a usar.

## Switch central de Codex por lead

Cada lead tiene `codex_enabled`. Si esta apagado, ningun path con Codex puede
correr para ese lead: bot conversacional Codex, agent tools, wake-ups
agendados, Workstation solo-page, heartbeats, steer y foto profesional. La UI
muestra el switch en el header del chat y en Workstation. Al apagarlo se limpian
los wake-ups pendientes de ese lead y del cliente Workstation asociado, y se
interrumpe cualquier Codex vivo de Workstation.

Los leads nuevos nacen con Codex apagado salvo que se configure
`CONTADORES_LEAD_CODEX_ENABLED_DEFAULT=true`. Las automations externas de
follow-up reciben `codex_enabled` y la exclusion `codex_disabled`; sus endpoints
internos rechazan mutaciones o mensajes para leads con el switch apagado.

Template opener inicial:

- Contadores usa `contadores_intro_nombre_pais_es_v1`.
- Abogados usa `abogados_intro_nombre_pais_es_v1`.
- Ambos reciben parametros posicionales: nombre corto y pais inferido del
  WhatsApp del lead.
- Specs versionados: `src/scripts/whatsapp_template_specs/opener_nombre_pais_es_v1.json`.

## Fuente de leads

Contadores ya no tiene switch de runtime. No existe un modo alternativo ni lead
sintético. El bot importa siempre desde la sheet configurada para cada funnel.

Para compatibilidad, algunos scripts legacy siguen aceptando
`CONTADORES_SHEET_URL` y `CONTADORES_SHEET_GID`. Para usuarios nuevos, preferir
siempre `config/default-funnels.json` o `FUNNELS_CONFIG_PATH` / `data/funnels.json`
y poner ahi `sheet_url` y `sheet_gid` por cada nicho.

`docker-compose.yml` lee `.env` y `/api/runtime` muestra readiness sin exponer
secretos. El runtime queda `ready=false` hasta que exista al menos un funnel
`kind=campaign`, `enabled=true`, con `sheet_url` y `sheet_gid`.

## Client Lead Delivery

Delivery es la capa para avisarle a un cliente cuando su propia campana recibe
una consulta nueva. Guarda fuentes en `client_lead_sources` y filas importadas
en `client_lead_deliveries`; no contamina `contadores_leads`,
`contadores_messages`, Workstation ni alertas humanas.

La configuracion puede hacerse por UI/API o por archivo versionado:
`config/default-client-lead-sources.json` como seed y
`CLIENT_LEAD_SOURCES_CONFIG_PATH` / `data/client-lead-sources.json` como
override del server. El flujo actual usa `konecta_client_lead_alert_es_v2` y,
cuando hay `context_field_mapping`, `konecta_client_lead_alert_context_es_v1`.

La referencia operativa completa esta en la seccion `Client Lead Delivery` mas
abajo y en las skills `contadores-rollout` y `contadores-spreadsheet`.

## Desarrollo local

Instalar dependencias:

```bash
cd /Users/fgoiriz/private/repos/contadores
uv sync
```

Leer la sheet:

```bash
uv run python src/tools/read_google_sheet.py --as-records
```

Levantar el backend:

```bash
PYTHONPATH=src uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Desarrollar el frontend:

```bash
cd src/frontend
npm install
npm run dev
```

Compilar el frontend que sirve FastAPI:

```bash
cd src/frontend
npm run build
```

Verificar runtime:

```bash
curl http://127.0.0.1:8000/api/runtime
```

Verificar API de Contadores:

```bash
curl http://127.0.0.1:8000/api/contadores/config
```

## Cloudflare Registrar y DNS

La compra programatica de dominios se hace con la API REST de Cloudflare
Registrar, no con Wrangler. El camino preferido es un API token scoped con
permiso de Registrar write, `CLOUDFLARE_ACCOUNT_ID`, billing profile con metodo
de pago default y contacto registrante default aceptado en Cloudflare.

Variables locales:

```bash
CLOUDFLARE_ACCOUNT_ID=...
CLOUDFLARE_API_TOKEN=...
```

Fallback legacy si todavia no existe el token scoped:

```bash
CLOUDFLARE_API_EMAIL=...
CLOUDFLARE_API_KEY=...
```

Verificar que la autenticacion funciona:

```bash
uv run python -m backend.cloudflare_registrar verify-token
```

Buscar y chequear dominios:

```bash
uv run python -m backend.cloudflare_registrar search "estudio contable" --extensions com,net,dev
uv run python -m backend.cloudflare_registrar check ejemplo-contable.com ejemplo-contable.net
```

Registrar es billable y no reembolsable. El comando primero corre
`domain-check`; sin `--yes` queda en dry-run. Para comprar exige aprobacion
explicita y limite de precio. Por defecto compra con `auto_renew=false`; usar
`--auto-renew` solo cuando se quiera activar renovacion automatica:

```bash
uv run python -m backend.cloudflare_registrar register ejemplo-contable.com --max-first-year-usd 15
uv run python -m backend.cloudflare_registrar register ejemplo-contable.com --max-first-year-usd 15 --yes
uv run python -m backend.cloudflare_registrar poll-registration ejemplo-contable.com
```

Crear zona DNS y agregar registros:

```bash
uv run python -m backend.cloudflare_registrar create-zone ejemplo-contable.com
uv run python -m backend.cloudflare_registrar upsert-record --zone ejemplo-contable.com --type CNAME --name www --content contadores.fgoiriz.com --proxied
```

Ejecutar un tick interno de Workstation desde el worker o localmente:

```bash
curl -X POST -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  http://127.0.0.1:8000/api/workstation/automation/tick
```

Snapshot read-only para automations de follow-up:

```bash
curl -H "Host: crm.fgoiriz.com" \
  -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  "http://149.50.136.121/api/contadores/followup/snapshot?limit=20000&messages_per_lead=12"
```

Export CSV del mismo snapshot:

```bash
curl -H "Host: crm.fgoiriz.com" \
  -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  "http://149.50.136.121/api/contadores/followup/snapshot.csv?limit=20000&messages_per_lead=12"
```

Estos endpoints de snapshot no mandan mensajes ni mutan la base. Exponen todos
los chats recientes de `contadores` y `abogados`, ultimos mensajes, estado de
delivery, exclusiones fuertes y buckets sugeridos para que una automation pueda
analizar el CRM sin depender de SSH. Usar `include_all_funnels=true` si se quiere
incluir tambien inboxes/funnels fuera de Contadores y Abogados.

Acciones internas para automations de follow-up:

- `POST /api/contadores/followup/leads/{lead_id}/messages` con
  `{"text":"...", "dedupe_hours":24}` encola un mensaje manual si la ventana de
  WhatsApp esta abierta.
- `POST /api/contadores/followup/leads/{lead_id}/actions` con
  `{"action":"send-manual-ping"}` corre una accion existente del CRM.
- `PATCH /api/contadores/followup/leads/{lead_id}` cambia stage,
  clasificacion, tags o estado manual. No envia WhatsApp.

Runner horario de follow-up:

- El seguimiento horario activo corre como LaunchAgent local en la Mac, no como
  cron de Codex App. El cron de Codex App quedo pausado porque ese runtime puede
  no tener red hacia `149.50.136.121`, aunque esta maquina si la tenga.
- Cada hora se crea una ejecucion nueva de `codex exec`, lee
  `.codex/skills/contadores-crm-followup-automation/SKILL.md`, consulta la API
  de produccion y opera solo mediante endpoints internos aprobados o SSH al
  server real cuando hace falta debug.
- Requiere `INTERNAL_API_TOKEN` en `.env` local o en el entorno. El runner carga
  `.env`, pero nunca imprime el token.
- Instalar o actualizar el LaunchAgent:

```bash
scripts/install_contadores_crm_launchd.sh
```

- Ver estado:

```bash
launchctl print gui/$(id -u)/com.konecta.contadores.crm-followup
```

- Correrlo ahora:

```bash
launchctl kickstart -k gui/$(id -u)/com.konecta.contadores.crm-followup
```

- Logs y ultimo resumen:

```bash
ls -lt data/reports/contadores-crm-followup-*.log | head
cat data/reports/contadores-crm-followup-latest.md
```

- Vista visual local real de la Mac:

```bash
scripts/render_contadores_crm_runner_dashboard.py
open data/reports/contadores-crm-followup-dashboard.html
```

  El HTML se regenera en cada corrida del LaunchAgent y lee directamente
  `launchctl`, `data/reports/`, `data/locks/` y los logs locales de la Mac.
  La pantalla prioriza el delta contra la corrida anterior: nuevos replies,
  cambios de estado, cambios de delivery, proximos pasos que quedaron due y
  acciones humanas. Despues muestra el ultimo run, historial acumulado como
  Markdown renderizado, timeline y un panel para copiar un prompt o comando
  `codex exec` con el contexto del run.
- Vista visual remota: entrar al backoffice y abrir la seccion `Runner`. La UI lee
  `GET /api/contadores/followup/runner/status` y muestra primero el delta
  estructurado, despues el ultimo resumen, historial acumulado y timeline.
  Los logs/stdout quedan colapsados como detalles tecnicos. Esta ruta
  queda protegida por sesion o `X-Internal-Token`; no es publica.
- El LaunchAgent local tambien sincroniza su ultimo estado al server real con
  `POST /api/contadores/followup/runner/status`, usando `INTERNAL_API_TOKEN`.
  Asi el backoffice desplegado puede mostrar el ultimo resumen/log tail aunque
  la ejecucion haya corrido en la Mac.

Verificar API de funnels:

```bash
curl http://127.0.0.1:8000/api/funnels
```

Configurar pesos de estrategias:

- `CONTADORES_STRATEGY_WEIGHTS_JSON='{"loom":{"text_offer_599":100}}'`
- También se puede cambiar desde `Settings` en el backoffice.
- Los pesos son porcentajes de rollout por paso. Cambiarlos afecta nuevas asignaciones; las asignaciones ya guardadas no se reescriben.

Template manual de ping:

- Nombre default: `contadores_manual_ping_es_v1`.
- Texto default: `Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion`.
- Se envia solo desde la accion manual del backoffice; no participa del tick automatico ni del follow-up de 24 horas.
- Las acciones masivas del CRM no deben preseleccionar `Manual ping`; el operador tiene que elegir ese template explicitamente.
- `Manual ping` en bulk requiere confirmacion explicita en el payload/UI y queda auditado como batch.
- No se puede mandar ningun WhatsApp outbound a un lead `closed`; primero hay que reabrirlo.
- Marcar un lead como `booked` no envia WhatsApp. El alias legacy `send-manual-booked` queda soportado, pero solo marca `booked`.

Entrada Click-to-WhatsApp:

- Cada funnel puede declarar `whatsapp_referral_source_ids` en el seed o en
  `data/funnels.json`.
- Contadores no debe tener IDs cargados si no tiene campaña real. Hoy el source_id real queda en `abogados`.
- Cuando Meta envia un webhook con `referral.source_id` configurado, el backend crea o reutiliza un lead `whatsapp_ctwa`.
- Si el webhook trae el nombre de perfil de WhatsApp, se guarda como `full_name` para leads nuevos de WhatsApp y para leads existentes que todavia no tenian nombre.
- Ese lead queda como si ya hubiese respondido al opener: no se encola el template inicial y el tick automatico pasa al offer despues de `initial_reply_quiet_seconds`.
- Por defecto no se usa el texto prellenado del anuncio para rutear porque el usuario puede editarlo antes de enviarlo.
- Excepcion aprobada: el texto normalizado `Hola! Quiero mas informacion de su propuesta para abogados!` rutea directo a `abogados` cuando no hay reply/referral usable.
- Si no hay `referral.source_id`, ni frase aprobada, ni match de funnel, el mensaje se guarda como lead en el buzon `general`.
- El servicio `bot` guarda cada webhook inbound de WhatsApp en
  `BOT_WEBHOOK_INBOX_PATH` antes de llamar al backend. Si el backend esta caido,
  el evento queda en ese SQLite y se reintenta en el worker hasta que
  `/api/contadores/whatsapp/inbound` lo acepte.
- El backend trata `external_id`/`wamid` inbound como idempotente. Si Meta
  reintenta un webhook ya guardado, devuelve `processed` sin duplicar el mensaje.

Client Lead Delivery:

- Delivery es una superficie separada del CRM, Workstation y Runner para leads que
  se generan para clientes de Konecta.
- Cada fuente guarda URL/GID del Google Sheet, intervalo de polling, destinatario
  WhatsApp, mapping de columnas, campos de contexto y template Meta.
- Las fuentes tambien se pueden declarar por archivo. El seed versionado es
  `config/default-client-lead-sources.json`; el override editable del server es
  `CLIENT_LEAD_SOURCES_CONFIG_PATH` o `data/client-lead-sources.json`.
- El backend importa ese archivo a `client_lead_sources` al arrancar. Para
  aplicar un cambio sin reiniciar, llamar `POST /api/client-lead-sources/config/reload`
  con `X-Internal-Token`.
- El archivo acepta `recipient_name` / `recipient_phone` para un destinatario o
  `recipients` para varios. Si hay varios, el loader crea una fuente por
  destinatario usando el mismo sheet y labels como `Cliente · Ana`.
- Tambien acepta `sheet_tab_name` cuando la pestaña no es la primera. Para dos
  campañas del mismo cliente, usar `sheets` y el loader crea una fuente por
  sheet/campaña con el mismo destinatario. Cada item de `sheets` puede
  sobreescribir parte o todo el `column_mapping` y el `context_field_mapping` si
  esa pestaña usa nombres de columnas distintos; los campos omitidos heredan el
  mapping de la fuente padre.
- Las filas importadas se guardan en tablas dedicadas:
  `client_lead_sources` y `client_lead_deliveries`. No contaminan
  `contadores_leads`, alertas humanas ni Workstation.
- `context_field_mapping` permite elegir una vez por fuente que columnas del
  sheet se agregan al WhatsApp como `Nombre del campo = valor`. Si una fuente
  tiene contexto, usar `konecta_client_lead_alert_context_es_v1`; si no, seguir
  con `konecta_client_lead_alert_es_v2`. El template con contexto siempre lleva
  6 parametros; el sexto parametro va en una sola linea para cumplir las reglas
  de Meta. Si las columnas vienen vacias, el backend manda `-` como sexto
  parametro.
- Primer sync: importa todas las filas validas existentes y deja sus
  notificaciones `pending`. Los siguientes syncs son idempotentes por
  `(source_id, source_row_key)` y solo agregan filas nuevas.
- La UI de Delivery no muestra un boton de sync manual: al seleccionar un
  contacto, refresca la fuente automaticamente cada 10 segundos y deja la
  configuracion escondida detras del boton `Config`.
- Cuando varias fuentes comparten el mismo WhatsApp destinatario, la UI las
  agrupa como un solo contacto y muestra filtros internos por sheet/campaña
  (`All sheets`, `Deuda`, etc.). La lista de contactos mantiene orden estable y
  no depende del ultimo `updated_at` de sync.
- La vista de leads se renderiza por sheet/campaña y muestra las columnas reales
  importadas desde el Google Sheet en el mismo orden de headers. El scroll
  horizontal queda dentro de la tabla para no romper el chat ni el layout al
  hacer zoom.
- Los envios de notificacion quedan visibles en `Sent chat` con el texto exacto
  enviado/snapshotteado, `external_id` de Meta, estado, timestamps y errores.
- Esos envios son auditoria de Delivery: no contaminan `contadores_messages` ni
  el historial de conversacion del CRM.
- El link que recibe el cliente es un `https://wa.me/{telefono}` directo, sin
  parametro `text=`.
- El boton de chat CRM aparece solo cuando el telefono destinatario de Delivery
  matchea un lead del CRM.
- Filas con telefono de lead faltante o invalido quedan visibles como `blocked`
  con motivo; no se mandan por WhatsApp.
- Ejemplo de archivo:

```json
{
  "version": 1,
  "sources": [
    {
      "id": "mmb-ads",
      "label": "MMB Ads",
      "enabled": true,
      "sheet_url": "https://docs.google.com/spreadsheets/d/...",
      "sheet_gid": "0",
      "sheet_tab_name": "deuda",
      "sheet_poll_seconds": 10,
      "recipients": [
        {"id": "dueno", "name": "Duenio", "phone": "+5491122223333"}
      ],
      "column_mapping": {
        "source_id": "id",
        "created_time": "timestamp",
        "full_name": "name",
        "phone_number": "phone",
        "email": "email"
      },
      "context_field_mapping": {
        "Tipo de deuda": "¿qué_tipo_de_deuda_tiene_pendiente?",
        "Caso": "breve_descripción_de_su_caso"
      }
    }
  ]
}
```

Ejemplo con dos sheets para el mismo destinatario:

```json
{
  "id": "cliente-ads",
  "label": "Cliente Ads",
  "enabled": true,
  "sheet_poll_seconds": 10,
  "recipients": [
    {"id": "dueno", "name": "Duenio", "phone": "+5491122223333"}
  ],
  "sheets": [
    {"id": "deuda", "label": "Deuda", "sheet_url": "https://docs.google.com/spreadsheets/d/...", "sheet_tab_name": "deuda"},
    {
      "id": "simple",
      "label": "Simple Form Setup",
      "sheet_url": "https://docs.google.com/spreadsheets/d/...",
      "sheet_tab_name": "simple form setup 2026-05-25",
      "context_field_mapping": {"Empresa": "company_name"},
      "column_mapping": {"email": "work_email"}
    }
  ],
  "column_mapping": {
    "source_id": "id",
    "created_time": "timestamp",
    "full_name": "name",
    "phone_number": "phone",
    "email": "email"
  },
  "context_field_mapping": {
    "Ciudad": "city",
    "Campaña": "campaign_name"
  }
}
```

- Endpoints principales:
  `GET/POST /api/client-lead-sources`,
  `POST /api/client-lead-sources/config/reload`,
  `PUT/DELETE /api/client-lead-sources/{id}`,
  `POST /api/client-lead-sources/{id}/sync`,
  `GET /api/client-lead-sources/{id}/leads`,
  `GET /api/client-leads/{id}/copy-all`,
  `POST /api/client-leads/{id}/retry`.
- El bot consume `/api/client-lead-deliveries/pending`, manda el template
  `konecta_client_lead_alert_es_v2` por Meta y registra `sent`, `delivered` o
  `failed` por id externo del provider.
- Para sheets privados, configurar `CONTADORES_GOOGLE_SERVICE_ACCOUNT_FILE` o
  reutilizar `GOOGLE_SERVICE_ACCOUNT_FILE`.

Buzon General:

- `general` es un inbox, no una campaña: no tiene pipeline de fases ni sheet sync.
- Los chats que entran por WhatsApp sin formulario pueden mostrar el nombre de perfil de WhatsApp si Meta lo envia en el webhook.
- Permite chatear, mandar el mensaje inicial o el ping general.
- Desde la UI se puede mover un chat a una campaña existente y elegir la fase inicial.

Tags:

- Los leads tienen tags libres de operador y filtro por tag.
- Los importados desde formulario reciben el tag `form`.
- Los creados desde un funnel Click-to-WhatsApp reciben el tag `whatsapp_funnel`.
- Los creados desde WhatsApp sin funnel matcheado reciben el tag `whatsapp`.
- La UI muestra tags en el detalle como solo lectura; para cambiarlos hay que seleccionar leads y usar la accion batch `Set tags`.
- El filtro por tag se combina con las fases, busqueda y estrategia.

Bot conversacional post-offer y post-meeting:

- Luego del offer y de la ventana de silencio, el backend llama a
  `ContadoresConversationBotProgram` con historial completo, funnel, stage,
  ultimos mensajes y timezone inferida por telefono cuando sea claro.
- La ventana de silencio funciona como backoff real: el backend bloquea el
  procesamiento conversacional por lead, relee el batch actual antes de correr
  la AI y vuelve a validarlo antes de encolar. Si entra otro inbound mientras la
  AI genera, descarta esa respuesta vieja y espera la proxima ventana quieta.
- El runtime principal es Codex SDK con `CONVERSATION_BOT_CODEX_MODEL`
  (`gpt-5.5` por defecto) y `CONVERSATION_BOT_CODEX_EFFORT=medium`, usando las
  skills `contadores-bot-sequence` y `contadores-lead-reply-playbook` como
  contexto estructurado.
  Puede inspeccionar archivos del repo y usar herramientas read-only para
  resolver dudas de source of truth; no debe modificar archivos ni estado
  externo durante una decision runtime.
- Si `CODEX_AGENT_TOOLS_ENABLED=true` y
  `CODEX_AGENT_TOOLS_CONVERSATION_ENABLED=true`, antes del contrato JSON legacy
  corre el runtime autonomo con tools internas auditadas. En ese modo Codex no
  actua como clasificador: puede llamar tools para mandar uno o mas mensajes,
  agendar un follow-up/heartbeat, mover leads entre funnels, taggear, escribir
  memoria durable, iniciar Workstation, actualizar estado o pasar a humano.
  Si ese runtime falla antes de ejecutar side effects, se conserva el fallback
  legacy.
- Codex SDK (`run_codex_with_context`) solo corre si `CODEX_BACKEND_ENABLED=true`
  (opt-in explicito; por defecto no gasta tokens Codex). Con Codex activo, el
  orden es ChatGPT Codex solo si `CODEX_PREFER_CHATGPT_LOGIN=true`, sino Codex
  con `OPENAI_API_KEY`, y despues DSPy/Grok. Si falla ChatGPT Codex, el lead no se pausa
  por eso: se crea una alerta runtime por email con link/comando para
  reautenticar y se responde con el siguiente fallback disponible. El fallback usa
  `OPENROUTER_GROK_4_3_MODEL=openrouter/x-ai/grok-4.3` cuando hay
  `OPENROUTER_API_KEY`; si no, usa `gpt-5.4-mini`. Si todos fallan, ahi si
  pasa a `needs_human`.
- El bot devuelve una accion estructurada:
  `send_reply`, `offer_solo_page_promo`, `send_page_example_video`,
  `start_workstation_solo_page`, `ask_scheduling_details`, `handoff_human`,
  `handoff_scheduling`, `close_lead` o `no_action`.
- Preguntas conocidas de precio, pais/cobertura, garantia, proceso, dominio,
  pagina existente, dudas sobre el offer o confirmaciones simples se responden con
  `sequence_step=ai_reply` y, si vienen del post-offer, mueven el lead a
  `needs_human`/Manual con `automation_paused_reason=ai_reply_conversation`.
  Como la AI ya contesto, el `manual_reply_status` queda `answered`.
- Si el lead recibio el offer, no esta decidido a avanzar con la oferta principal,
  pero muestra interes tibio ("lo analizo", "te aviso", "les estare
  comunicando", "lo consulto"), el bot puede usar `offer_solo_page_promo`. Esa
  accion encola `sequence_step=offer_solo_page_promo`, mantiene la automatizacion
  activa y ofrece solo la pagina web. El precio se elige de forma deterministica
  con peso fuerte hacia `99` y `49` USD.
- Cada batch inbound se reclama en SQLite antes de llamar al bot, con
  `conversation_processing_started_at` y
  `conversation_processing_latest_inbound_id`. Esto evita que dos ticks/procesos
  encolen dos `ai_reply` distintos para la misma pregunta. Un claim se considera
  abandonado despues de `CONVERSATION_PROCESSING_STALE_SECONDS`.
- Si el bot no sabe responder una pregunta factual/comercial, no manda una
  respuesta insegura ni corta el flujo permanentemente: crea un runtime alert
  `unanswered_lead_question` por AgentMail. El operador responde ese mismo
  thread con el texto exacto para WhatsApp; el backend lo manda, restaura el
  stage anterior, y guarda la respuesta en
  `.codex/skills/contadores-lead-reply-playbook/references/operator-learned-answers.md`
  y `wiki/skills/contadores-lead-reply-playbook/references/operator-learned-answers.md`
  para futuras preguntas parecidas.
- Si el operador ya respondio por CRM antes de contestar el email de aprendizaje,
  esa respuesta de email solo se guarda como conocimiento y resuelve el ticket:
  no se encola otro WhatsApp duplicado. Los emails de alerta incluyen la
  conversacion reciente en orden cronologico, no solamente el ultimo inbound.
- Si el lead rechaza el servicio o dice que no quiere avanzar, el bot envia
  exactamente `1) Muy caros los 599 dolares`, `2) No me sirve la pagina web +
  publicidades`, `3) No es mi momento para invertir`, `4) Otro motivo`, con
  `sequence_step=ai_rejection_survey`, y cierra el lead para no responder mas.
- El origen/identidad de Konecta no se infiere del pais del lead. El prompt y
  un guardrail post-modelo usan el source of truth del repo `konecta-labs`:
  Konecta Labs, trade name de Octopy LLC, equipo founder-led de IA aplicada,
  fundado por Facundo Goiriz y Alan Kravchuk. Ese mismo bloque tambien fija la
  operacion completa del funnel: ICP por Contadores/Abogados, objetivo,
  mecanismo, entrega remota, precio, garantia, limites de promesa, paises,
  scheduling y cosas que no se pueden inventar. Para `De donde son?` la
  respuesta canonica es `Escribo desde Argentina. Somos Konecta Labs y
  trabajamos remoto para toda Latinoamerica.` Nunca debe contestar `Somos de
  Ecuador` ni copiar el pais del lead como origen nuestro.
- El copy del bot debe sonar a WhatsApp real de Facu/operador: natural, corto,
  no robotizado, sin signos de apertura como `¿` o `¡`, y sin frases
  corporativas de asistente AI.
- El bot no debe repetir la pregunta del lead como encabezado ni arrancar con
  frases tipo `Para estar claros:`. Si el lead pregunta que cuenta como
  consulta/prospecto, responde que es una oportunidad real que llega a WhatsApp,
  no un cliente cerrado, y no pide email/dia/horario en ese mismo mensaje.
- Si falta email, dia, horario o zona horaria para una llamada, el bot pide solo
  el dato faltante. La llamada default es de 15 minutos.
- Cuando ya tiene email, dia y horario, confirma por WhatsApp con
  `sequence_step=scheduling_handoff_confirmation`, pausa el lead en
  `needs_human`, guarda `automation_paused_reason=booking_details_collected` y
  deja email/dia/horario/timezone en `last_classification_reason` para la alerta
  por email.
- Los audios inbound se transcriben antes de llegar al bot con
  `OPENAI_AUDIO_TRANSCRIPTION_MODEL=gpt-4o-transcribe` por defecto. Si WhatsApp
  entrega `.ogg`, Docker incluye `ffmpeg` para convertirlo a un formato aceptado
  por OpenAI. Si sale bien, el audio queda como mensaje reproducible y el
  transcript se guarda como el siguiente inbound con
  `sequence_step=audio_transcript`. Si descarga/transcripcion falla, se conserva
  el audio reproducible y recien ahi pasa como media sin transcript.
- El bot no inventa audio/media sin transcript. Imagen, video, documento,
  sticker o audio fallido sin texto pasan a humano.
- Cerrados, booked, archivados, excluidos, Venezuela y Workstation siguen
  bloqueados por los guards existentes.

Acciones manuales de Meeting:

- `Meeting with intro` encola el texto previo y despues el link legacy de agenda.
- `Meeting link only` encola solo el link legacy de agenda.
- El link legacy sale de `calendly_base_url` del funnel activo.
- Ambas acciones registran `calendly_sent_at` y mantienen el lead en Manual.
- La automatizacion nueva no manda links automaticamente. Para avanzar, el
  bot pide email, dia y horario para que Facu coordine la llamada manualmente.
- Hoy el codigo no crea eventos de Google Calendar ni links de agenda desde texto
  libre; cuando junta los datos, marca `booking_details_collected`, pausa en
  `needs_human` y dispara la alerta por email.

Promo solo pagina:

- Si un lead post-offer no esta 100% decidido por la oferta completa de pagina +
  campanas pero muestra interes tibio, el bot puede ofrecer automaticamente la
  promo de solo pagina con `sequence_step=offer_solo_page_promo`.
- Esa promo ofrecida por el bot usa precios ponderados hacia valores altos:
  `99` y `49` USD. El precio queda escrito en el outbound para que Workstation
  lo fije luego en `offer_price_usd`.
- Si un lead responde positivamente a la promo de pagina barata, el bot manda
  automaticamente un video de ejemplo reutilizable segun funnel:
  `data/contadores/videos/cliente-pagina.mp4` para contadores o
  `data/contadores/videos/pagina-abogado.mp4` para abogados.
- Si el lead vuelve a responder con interes despues del ejemplo, se crea un
  `WorkstationClient` idempotente con `work_type=solo_pagina`,
  `status=pending_payment`, `automation_status=intake` y el precio fijo de la
  promo en `offer_price_usd`.
- Para leads que quedaron en Manual por manejo humano, la UI muestra una accion
  `Solo page`. Esa accion crea el mismo Workstation `solo_pagina`: si el chat
  viejo ya trae datos utiles del estudio/servicios, Workstation genera el
  boceto directamente; si solo trae interes generico, primero manda el intake.
- El CRM queda pausado con
  `automation_paused_reason=workstation_solo_page_started`; desde ese punto
  responde el tick de Workstation, no el bot comercial.
- Los pasos nuevos de secuencia son
  `offer_solo_page_promo`, `auto_accountant_page_example_video`,
  `auto_lawyer_page_example_video`, `workstation_intake`, `workstation_preview_video`,
  `workstation_revision_video`, `workstation_ping_1`,
  `workstation_ping_2` y `workstation_handoff`.

Vista Manual del backoffice:

- `Manual` muestra todos los leads manuales.
- `Needs answer` aparece como un bloque del pipeline entre `Manual` y `Closed`.
- Al marcarlos como respondidos, salen de `Needs answer` y siguen quedando en `Manual`.
- `Manual outbound` permite enviar texto, media o archivos. Uno o mas adjuntos se
  pueden seleccionar, arrastrar sobre el composer, o pegar desde el
  portapapeles; enviar algo desde ahi pausa la automatizacion del lead.

Media en WhatsApp:

- La media que envian los leads se descarga y se muestra en el backoffice
  cuando el proveedor la entrega.
- Los audios inbound se guardan con `media_type/media_path` para poder
  reproducirlos y, si la transcripcion sale bien, el transcript queda como un
  mensaje inbound subsiguiente con `sequence_step=audio_transcript`, para que el
  operador lea el chat sin escuchar el audio y el bot siga como texto normal.
- Si el lead ya tiene cliente en Workstation, toda imagen inbound del usuario se
  copia tambien a `data/workstation/clients/.../media/`. Si la imagen llego
  antes de crear el cliente, se copia al workspace en el momento de convertir el
  lead.
- La media o archivos que envia el operador desde `Manual outbound` se guardan
  en `data/contadores/outbound_media/{lead_id}/`, se muestran en el chat y el
  bot los despacha por WhatsApp como imagen, video, audio o documento.
- Si un lead envia solo media sin texto, se guarda un placeholder textual como `[image]` o `[video]`.
- Los videos salientes de estrategia usan el `media_path` configurado, por ejemplo `data/contadores/videos/loom_60_seconds_captions.mp4`.
- El frontend sirve esos videos desde una URL estable basada en `media_path`, asi el mismo archivo se reutiliza para todos los leads que recibieron ese video.

## Workstation de clientes convertidos

La UI tiene dos superficies: `CRM` para captar y conversar con leads, y
`Workstation` para trabajar con clientes que ya pagaron.

Desde el detalle de un lead se puede usar `Convert` para crear un cliente de
Workstation. La conversion es idempotente: si el lead ya fue convertido, la UI
muestra `Open Workstation` y conserva el link al chat original del CRM.

Al convertir:

- se crea un registro en `workstation_clients`;
- se marca el lead como `booked` si todavia no lo estaba;
- se pausa la automatizacion del lead;
- se registra el evento `workstation_client_created`;
- la media subida en Workstation se puede renombrar desde la UI sin cambiar el
  archivo fisico guardado en `data/workstation/clients/.../media/`.
- si la conversion viene de la promo solo pagina, el precio sorteado queda
  fijo en el cliente de Workstation para saber cuanto cobrar.
- la accion `Solo page` desde Manual usa `work_type=solo_pagina`,
  `status=pending_payment` y `automation_status=intake`, y pausa el lead con
  `automation_paused_reason=manual_workstation_solo_page_conversion`.
- el summary del CRM expone `workstation_client_id`.

Cada cliente de Workstation tiene notas editables, media subida manualmente con
titulo, copia de notas, copia de todo el contexto, foto profesional generada
desde fotos fuente, y export ZIP. La media se puede subir con el selector de
archivo, arrastrando un archivo sobre el panel `Media`, o pegando una imagen o
archivo desde el portapapeles mientras ese panel esta activo.

La foto profesional se dispara desde el boton `Actions` del cliente. La accion
`Hacer foto profesional` abre un modal para seleccionar imagenes de `media/`,
arranca un job async en el backend y la UI hace polling hasta mostrar el
resultado o el error.
Para clientes `solo_pagina`, `Actions` tambien permite arrancar Codex con un
prompt manual del operador, enviar instrucciones adicionales al run activo con
`Steer Codex` y detenerlo con `Stop Codex`. El steer usa el turn activo de Codex
sin reiniciar el trabajo. El stop interrumpe el turn activo, marca el cliente
como `needs_human` sin crear alerta de fallo y deja el evento visible en
`progress.md`.

## WhatsApp delivery failures

El bot registra cada error de envio en el backend. Un mensaje saliente fallido
se reintenta hasta `CONTADORES_DELIVERY_MAX_ATTEMPTS` veces, esperando
`CONTADORES_DELIVERY_RETRY_DELAY_SECONDS` entre intentos. Cuando se agotan los
intentos, el mensaje queda en `failed`, el lead se marca con una alerta roja en
el CRM, y el detalle del chat muestra el error expandible junto al mensaje. Los
errores de Meta se normalizan antes de mostrarse: por ejemplo, el codigo
`130472` se muestra como destinatario bloqueado por un experimento de Meta,
`131026` como posible numero no registrado en WhatsApp o destinatario que no
puede recibir mensajes de empresa, y `131047` como ventana de 24 horas cerrada.
El operador puede tocar el mensaje fallido o el boton `Seen` para
guardar `delivery_error_acknowledged_at`; desde ese momento el error sigue
visible en el chat, pero deja de contar para la alerta roja del lead.

Los mensajes no-template solo se pueden encolar si el ultimo inbound del lead
esta dentro de la ventana de 24 horas de WhatsApp. Si la ventana esta cerrada,
el backend rechaza custom/media/Meeting/Loom no-template antes de llegar a
Meta, y la UI bloquea el composer custom indicando que hay que usar un template
aprobado como `Manual ping`.

Para reencolar mensajes historicos que ya quedaron en `failed`:

```bash
uv run python src/scripts/requeue_failed_contadores_messages.py --dry-run
uv run python src/scripts/requeue_failed_contadores_messages.py
```

## Promo web profesional mayo 2026

Template Meta:

- Nombre: `konecta_promo_web_profesional_es_v1`
- Categoria: `MARKETING`
- Parametros posicionales: nombre corto, profesion, pais, precio.
- Spec versionado: `src/scripts/whatsapp_template_specs/konecta_promo_web_profesional_es_v1.json`.

Script one-off:

```bash
uv run python src/scripts/contadores_promo_web_20260505.py
uv run python src/scripts/contadores_promo_web_20260505.py --execute
```

El modo default es dry-run: genera `data/reports/promo-web-profesional-2026-05-05-preview.csv`
y `data/contadores/promo-web-profesional-2026-05-05-aliases.csv`.
El script excluye convertidos, Workstation, booked, closed, archived, opt-outs
de marketing y, salvo que se pase `--include-provider-failures`, leads cuyo
ultimo outbound ya fallo en Meta. Los precios `19/29/49/99` se eligen de forma
deterministica por lead y pais, con mayor peso a precios bajos en Venezuela,
Bolivia y mercados similares. Al ejecutar, encola el template con sus variables
en `contadores_messages`. Las respuestas posteriores entran por la ruta de
oferta activa (`promo_`/`offer_`), pero esta promo tiene un atajo
deterministico: primer interes manda el video de ejemplo y el segundo interes
crea Workstation de `solo_pagina` para intake y boceto.

La promo de solo pagina ofrecida por el bot conversacional, no por el batch,
usa `sequence_step=offer_solo_page_promo` y pondera el precio hacia `99` y
`49` USD para leads tibios que no avanzan con la oferta completa.

La carpeta canonica por cliente queda en:

```text
data/workstation/clients/{client_id_corto}-{nombre-slug}/
```

Dentro de esa carpeta se refrescan estos archivos:

- `profile.json`: datos del cliente, lead, precio de oferta y media.
- `notes.txt`: notas de reunion.
- `conversation.txt`: transcript del chat CRM.
- `media/`: archivos subidos desde Workstation y copias de artefactos
  generados que conviene ver rapido desde la UI. Las imagenes que el cliente
  mande por WhatsApp tambien se copian aca automaticamente.
- `professional-photo/vNNN/`: versiones generadas por Codex para la foto
  profesional del cliente.
- `landing-page/vNNN/`: bocetos estaticos generados por Codex para la promo
  solo pagina, con `index.html`, `styles.css`, `script.js`, `assets/`,
  `preview-message.txt`, `outbound-messages.json` opcional, `preview.mp4` y
  `metadata.json`.
- `progress.md`: log de progreso operativo que Codex y el backend van
  agregando durante drafts, revisiones, render y cola del preview.

Cada `landing-page/vNNN/` tiene contrato rigido: `index.html`, `styles.css` y
`script.js` viven en la raiz de la version; todos los assets propios de la
pagina viven bajo `assets/`; el HTML referencia `./styles.css`, `./script.js` y
`./assets/...`. No se permiten referencias a `/data`, `../`, rutas absolutas de
filesystem ni archivos de las plantillas fuente. `preview.mp4` y
`metadata.json` los escribe el backend, no el builder.

La foto profesional se crea desde imagenes seleccionadas en `media/` y se guarda
siempre con versionado determinista:

```text
professional-photo/v001/professional-photo.jpg
professional-photo/v001/metadata.json
```

Las modificaciones desde la UI crean `v002`, `v003`, etc. Nunca se sobrescriben
las fotos fuente ni las versiones anteriores.
Durante el intake hay que incentivar al cliente a mandar una foto sin demorar:
no hace falta que sea profesional. Sirve una foto de perfil, una foto de redes
sociales o cualquier foto casual donde se vea la cara, porque Konecta la mejora
con inteligencia artificial antes de usarla.

La automatizacion de `landing-page` nunca debe usar fotos crudas de personas
desde `media/` como retratos publicos. Si el cliente mando fotos de una o varias
personas, primero se generan las fotos profesionales faltantes y la siguiente
web incluye todas las fotos profesionales correspondientes.
Si el cliente no mando ninguna foto y no existe `professional-photo/`, la pagina
no debe mostrar retratos ni fotos default de personas. Tampoco se reutilizan
fotos de otros clientes ni fotos personales de la plantilla base; se usa una
imagen generica del rubro, como un estudio juridico, biblioteca legal, papeles
contables, calculadora u oficina.

Cada version de `landing-page` tambien debe traer `preview-message.txt`: Codex
elige ahi el texto exacto que acompana al MP4 por WhatsApp. El backend solo usa
un texto generico como fallback cuando ese archivo falta o esta vacio.
Si Codex necesita mandar mas de un item al cliente, tambien puede escribir
`outbound-messages.json` con una lista ordenada de mensajes y adjuntos
(`image`, `video`, `audio` o `document`). Cuando hay foto profesional, se manda
como imagen separada una sola vez en todo el chat del cliente y se pregunta si
le gusta; en el mismo ciclo de entrega tambien se manda el video de la pagina
cuando termina de renderizar. El orden preferido para esa primera entrega es
foto profesional primero y video del boceto despues. Si el archivo no existe o
no tiene mensajes validos, Workstation arma el plan default: foto profesional
disponible primero solo si todavia no fue enviada y MP4 con
`preview-message.txt` despues.

El backend usa el Codex SDK async para Workstation y el bot conversacional. Cada
lead conserva su thread en
`contadores_leads.codex_conversation_thread_id` y cada cliente Workstation
conserva otro thread separado en
`workstation_clients.codex_workstation_thread_id`; los runs auditados guardan
`codex_thread_id` y `codex_turn_id` en `agent_runs`. En Docker, la imagen
instala `@openai/codex` y usa `CODEX_HOME=/app/data/codex-home` por defecto para
que la autenticacion de Codex pueda persistir en el volumen `data/`. Si
`CODEX_PREFER_CHATGPT_LOGIN=true`, el backend remueve `OPENAI_API_KEY` antes de
lanzar Codex para priorizar el login ChatGPT/Codex. Si se configura en `false`,
el proceso Codex conserva `OPENAI_API_KEY`.

Cada cliente `solo_pagina` con una version generada tiene una URL publica de
prueba estable, no autenticada e indescifrable:

```text
{WORKSTATION_PUBLIC_PAGE_BASE_URL}/p/{token}/
```

La URL vive en `workstation_public_pages`, una fila por cliente. El token no
cambia entre versiones; cuando el backend crea `v002`, `v003`, etc. actualiza la
fila para que la misma URL sirva siempre la ultima version. El detalle de
Workstation muestra botones para abrir y copiar esa URL, y `profile.json`
incluye `public_page` para que el agente Codex tambien la conozca.

La URL de prueba se genera apenas existe `index.html` en una version y el
backend termina de renderizar el preview. El primer envio al cliente puede ser
video-first; cuando el cliente empieza a mandar contenido o cambios concretos,
Workstation ya no debe mandar solo otro video: revisa/genera la pagina, encola
el video y tambien manda el link publico para que vea la pagina online. Tambien
manda el link cuando el cliente pide ver/probar la pagina online o cuando ya
aprobo el video y falta revisar la version publicada de prueba. Si despues pide
cambios, se genera otra version y se reenvia el mismo link, que ya apunta a la
version nueva. La aprobacion final llega recien cuando el cliente confirma la
pagina publica de prueba; luego se handoffea para dominio, pago y publicacion
final.

Workstation tambien agenda un heartbeat Codex automatico cada 12 horas para
clientes `solo_pagina` activos. El heartbeat lee el contexto del cliente y puede
mandar el link publico, responder, revisar la pagina, handoffear o elegir
`no_action` sin mandar nada. Esto cubre casos donde una respuesta llego despues
de un handoff humano o entre cambios de logica.

La automatizacion Workstation solo pagina usa Codex GPT-5.5 con la skill
`.codex/skills/workstation-solo-page/SKILL.md`. Todo agente autonomo tambien
carga `.codex/skills/contadores-agent-harness/SKILL.md`, que le explica el loop
de herramientas, memoria y heartbeats. Si
`CODEX_AGENT_TOOLS_ENABLED=true` y
`CODEX_AGENT_TOOLS_WORKSTATION_ENABLED=true`, primero corre el agente autonomo
con toolbelt interna: puede responder texto, agendar follow-up/heartbeat, leer o
escribir memoria en `data/agent-memory/`, crear/revisar la pagina, encolar
entregables, mandar la URL publica de prueba, marcar aprobacion, pasar a humano
o consultar disponibilidad y precios publicos estimados de dominios sin
credenciales. Las tools quedan auditadas en
`agent_runs`, `agent_tool_calls`, `scheduled_agent_tasks` y
`data/agent-runs/`. Si el agente con tools falla antes de completar side
effects, Workstation vuelve al decisionador JSON legacy.
Antes de generar bocetos, revisiones, respuestas o aprobaciones, espera 20
minutos de silencio desde el ultimo inbound para que el cliente pueda mandar
fotos, audios y datos en tandas.
Cuando un cliente responde durante intake o despues de un preview, Workstation
ya no fuerza una revision con video ante cualquier mensaje. Primero corre una
decision autonoma:
puede responder por texto, pedir mas datos, crear/revisar la pagina, aprobar y
handoffear, pasar a humano o no hacer nada. Si el cliente pregunta como mandar
contenido, la respuesta correcta es pedirle que lo envie por WhatsApp y no
generar otro boceto.
Si el pedido es factual pero vago, por ejemplo "hacer la trayectoria mas
amplia" o "poner algo mas completo", Workstation no debe inventar contenido ni
regenerar por reflejo: pide cinco datos concretos, espera la respuesta y recien
ahi crea la revision.
Si ambos runtimes de Codex fallan o no generan los archivos esperados, se marca
`automation_status=failed` y se crea una alerta por email con el error real de
ChatGPT Codex, el fallback API-key y el comando/link de reauth. Ese fallo tambien
debe quedar visible en el detalle del cliente de Workstation: el endpoint
devuelve `runtime_alerts` y la UI muestra la alerta con el estado de email
pendiente, enviado o resuelto. No debe existir un `failed` silencioso ni un
timeout generico que tape el error real.
El panel tambien muestra estado observado en vivo: task backend activo, turn
Codex activo, hora de inicio y `not_running` cuando la base dice `drafting` o
`revision_requested` pero el proceso real ya no existe.
Las acciones manuales de Workstation deben bloquearse solo por ese estado vivo:
si no hay task ni turn activo, el operador puede reiniciar Codex aunque haya
quedado un `drafting` o `revision_requested` persistido.
Los errores posteriores a un preview ya generado y enviado, como problemas al
evaluar pings o estados secundarios, no deben marcar el cliente como failed ni
mandar email: se registran en `progress.md` y el cliente sigue esperando review.

El detalle de Workstation tambien devuelve `automation_state`, que explica si el
cliente esta idle, esperando backoff, trabajando con Codex, listo para revision o
fallado. La UI hace polling del cliente abierto cada pocos segundos sin pisar las
notas que el operador este editando y muestra el contenido de `progress.md` como
progreso casi en tiempo real. Si un draft o revision queda en estado working por
mas de 2 horas, el detalle lo marca como stale y el proximo tick lo convierte
en fallo visible con alerta/email. El endpoint de tick usa un lock de proceso:
si otro tick llega mientras una generacion larga de Codex sigue activa, responde
`status=busy` y no reevalua estados stale hasta que termine el tick en curso.

El preview principal se renderiza como MP4. El backend renderiza el HTML estatico
con Playwright en desktop `1440x900`, graba un scroll y normaliza el archivo con
`ffmpeg` a H.264. El scroll usa una animacion lineal y continua para evitar
saltos en paginas largas. Cuando Codex
escribe `outbound-messages.json`, Workstation respeta esa lista y puede encolar
varios WhatsApp seguidos, incluyendo el MP4 y otros entregables generados.
Cada carpeta de cliente tambien se inicializa como un proyecto Git local. En
cada version, el backend commitea el HTML, CSS, JS, assets y mensajes de salida.
Las revisiones parten copiando la version anterior al nuevo `vNNN`, asi Codex
edita sobre el mismo diseno y solo cambia lo pedido salvo que el cliente pida un
redisenio.

Cuando la ventana de WhatsApp esta cerrada, Workstation solo usa templates Meta
aprobados. Los nombres son configurables por `.env`:

- `WORKSTATION_PING_TEMPLATE_1_NAME=konecta_workstation_ping_1_es_v1`
- `WORKSTATION_PING_TEMPLATE_2_NAME=konecta_workstation_ping_2_es_v1`
- `WORKSTATION_HANDOFF_TEMPLATE_NAME=konecta_workstation_handoff_es_v1`
- `WORKSTATION_PUBLIC_PAGE_BASE_URL=https://crm.fgoiriz.com`
- `CONTADORES_REVIEW_BASE_URL=https://crm.fgoiriz.com`
- `WORKSTATION_CODEX_HEARTBEAT_ENABLED=true`
- `WORKSTATION_CODEX_HEARTBEAT_INTERVAL_HOURS=12`

La cadencia es 24h, 48h y 72h desde el ultimo preview. Si faltan templates o
falla WhatsApp/Codex, se alerta por email y no se manda texto custom fuera de la
ventana de 24 horas.
Si el cliente responde despues del `workstation_handoff`, y ese handoff no fue
por aprobacion explicita, Workstation vuelve a tratarlo como review del preview:
primero muestra backoff de 20 minutos y luego el tick arranca una revision de
Codex automaticamente. Los handoffs por aprobacion quedan en humano.

El ZIP se descarga desde:

```bash
curl -L http://127.0.0.1:8000/api/workstation/clients/{client_id}/zip -o client.zip
```

Codex debe usar esa carpeta como fuente de verdad para trabajos manuales futuros
como landing pages, imagenes o materiales de entrega. No se llama a GPT Image por
API desde esta V1.

## Docker Compose

```bash
docker compose up --build
```

Compose lee `.env`. Para cambiar la fuente de leads, editás la sheet configurada
y reiniciás el servicio.

Servicios:

- `backend`: FastAPI con login, API de Contadores y frontend.
- `bot`: webhooks de WhatsApp/Meeting y worker de automatización.
- `traefik`: entrada HTTP para mantener el despliegue detrás de Traefik.

El backend corre con un solo worker de Uvicorn mientras use SQLite. La base
local queda en `data/database.sqlite`, montada como volumen persistente, y el
engine activa WAL + busy timeout para reducir locks entre el backend y el bot.
No subir `--workers` sin migrar a Postgres o definir otra estrategia de
concurrencia.

El bot tambien usa el volumen persistente `data/` para
`bot-webhook-inbox.sqlite`. Ese inbox es el buffer antifallos de inbound
WhatsApp entre Meta y el backend; no borrarlo durante deploys o limpiezas.

## Rollout recomendado

`ALWAYS_DEPLOY`: un cambio de producto no esta terminado por compilar local,
pasar tests o estar pusheado. Esta terminado cuando `main` fue deployado en el
server real y se verifico ahi.

Este repo se trabaja server-first: `localhost` sirve para desarrollar, verificar, mover git, pushear y deployar. Un cambio de producto se considera terminado cuando está en el server real, salvo que explícitamente se pida local-only.

1. Trabajar y mergear directo a `main`.
2. Pushear `main`.
3. Deployar el servidor desde `main`.
4. Verificar `/api/runtime`, `/api/funnels`, la ingesta de sheet y el flujo de WhatsApp en el server.
5. Si el cambio toca Client Lead Delivery, verificar fuentes, sync, pendientes,
   delivery callbacks y aprobacion del template en el server real.

Deploy remoto:

```bash
./deploy_to_server.sh
```

El script usa SSH en `149.50.136.121:5389`.

Logs remotos:

```bash
./server_logs.sh
```
