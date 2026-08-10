# Website Agent

Simulador local de WhatsApp para vender, construir y publicar sitios con Deep Agents.

Cada usuario tiene:

- un thread de Agent Server;
- un filesystem virtual aislado por namespace y disponible entre runs;
- interrupción nativa que acepta mensajes nuevos mientras el agente trabaja y continúa desde su último checkpoint;
- soporte para texto, imágenes, video, audio y documentos.

FastAPI guarda usuarios y mensajes en SQLite. El runtime open source de este workspace guarda threads, checkpoints, runs y archivos en PostgreSQL. Un mensaje consecutivo interrumpe el run activo, conserva su progreso y continúa en otro run con el mensaje nuevo.

## Ejecutar

```bash
cp .env.example .env
```

Completá `OPENAI_API_KEY`. `AGENT_RUNTIME_API_KEY` es opcional; si lo configurás, Compose lo comparte entre FastAPI y el runtime.

```bash
docker compose up --build
```

Abrí <http://127.0.0.1:8000>. Compose levanta FastAPI, Agent Runtime y PostgreSQL. La base del producto queda en `data/`; los threads, checkpoints, runs, crons y archivos del agente quedan en el volumen de PostgreSQL. La API compatible con LangGraph queda disponible en <http://127.0.0.1:2024/docs> y MCP en `http://127.0.0.1:2024/mcp`.

## WhatsApp

El mismo FastAPI expone `GET` y `POST /webhook/wa` mediante PyWA. Los mensajes de WhatsApp crean o reutilizan un usuario por número, guardan sus adjuntos en el Store virtual y entran en la misma cola durable que el chat web. La respuesta final del agente vuelve al mismo número. Los IDs externos evitan repetir un run o una respuesta cuando Meta reintenta un webhook.

Configurá en Meta:

- callback URL: `https://chatterface.fgoiriz.com/webhook/wa`;
- verify token: el valor local de `WA_VERIFY_TOKEN`;
- campo suscripto: `messages`.

`WA_APP_SECRET` valida la firma de cada POST. `WA_PHONE_ID` identifica el número emisor; `WA_WABA_ID` identifica la cuenta de WhatsApp Business; `WA_BUSINESS_ID` es el Business Portfolio y se conserva sólo como referencia administrativa. El runtime no modifica automáticamente la configuración de Meta.

El endpoint necesita HTTPS público para recibir tráfico real. En local podés comprobar el estado en `GET /health`: devuelve `whatsapp=configured` cuando las credenciales requeridas llegaron al container.

En producción, Compose conecta FastAPI a la red `contadores_default`; el Traefik existente publica únicamente el callback de WhatsApp.

## Probar

```bash
docker compose run --rm --no-deps app uv run --no-sync pytest
```
