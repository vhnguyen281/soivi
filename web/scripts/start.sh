#!/bin/sh
# Wait for the API, build (prerendering every page from it), then serve the
# standalone server. Later changes arrive through POST /api/revalidate.
set -e
echo "waiting for the API at $SOIVI_API_URL"
i=0
until node -e "fetch(process.env.SOIVI_API_URL + '/methodology').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"; do
  i=$((i + 1))
  [ "$i" -ge 60 ] && { echo "API not reachable"; exit 1; }
  sleep 2
done
npm run build
cp -r .next/static .next/standalone/.next/static
cp -r public assets content .next/standalone/ 2>/dev/null || true
cd .next/standalone
exec node server.js
