# Despliegue de un servidor en vivo (opcional)

Sin servidor, la app y la web funcionan con los datos que publica el pipeline de GitHub Actions cada 30 minutos.
Un servidor propio añade:
- cuotas y estadísticas en directo por WebSocket;
- ingesta cada pocos segundos o minutos;
- cuentas de usuario sincronizadas entre dispositivos.

## Opción A — Render (un clic)

1. Abra <https://render.com/deploy?repo=https://github.com/cristhianlujan45-blip/Apuestas> e inicie sesión.
2. Render lee `render.yaml` y crea:
   - la API;
   - el worker;
   - PostgreSQL;
   - Redis.
3. Complete las claves que tenga: `ODDSPAPI_KEY`, `ODDS_API_NET_KEY`, `API_FOOTBALL_KEY`, `NTFY_TOPIC`.
4. Cuando termine, copie la URL de la API (por ejemplo `https://apuestas-api.onrender.com`).
5. En la app, vaya a **Configuración → Servidor en vivo** y pegue esa URL.

El worker entrena el modelo al arrancar. Por eso usa un plan con 2 GB de memoria. Revise los precios vigentes de
Render antes de confirmar.

## Opción B — VPS con Docker (más barato)

Cualquier VPS con 2 GB de RAM sirve (Hetzner, DigitalOcean, Contabo…, unos 5–6 USD/mes).

```bash
git clone https://github.com/cristhianlujan45-blip/Apuestas.git && cd Apuestas
cp .env.example .env    # complete JWT_SECRET y sus claves
echo 'CORS_ORIGINS=https://cristhianlujan45-blip.github.io,https://localhost,capacitor://localhost' >> .env
docker compose up -d --build
```

Para que el celular se conecte por HTTPS, ponga un dominio con Caddy o Nginx delante del puerto 8000. Luego use esa
URL en la app.
