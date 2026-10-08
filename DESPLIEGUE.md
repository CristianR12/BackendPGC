# Guía de despliegue

Backend en **Render** (gratis), frontend en **Netlify** (gratis), datos y cuentas en **Firebase** (ya existe).
Cada servicio se redespliega solo cuando se sube algo a `main` de su repositorio.

| Pieza | Repositorio | Dónde |
|---|---|---|
| Backend (Django) | `CristianR12/BackendPGC` | Render |
| Frontend (React) | `CristianR12/FrontendPGC` | Netlify |
| Base de datos y cuentas | proyecto `asistenciaconreconocimiento` | Firebase |

**Orden: Firestore → Render → Netlify → volver a Render (CORS) → Firebase Auth.**
Netlify necesita la dirección de Render, y Render necesita la de Netlify para el CORS; por eso Render se toca dos veces.

---

## 0. Antes de empezar

- [ ] `main` de los dos repos está actualizado en GitHub.
- [ ] Tienes a mano el JSON de credenciales de Firebase (`CredencialesFirebase/…adminsdk.json`). **Nunca se sube a GitHub.**
- [ ] Sabes los correos de los administradores reales.
- [ ] (Recomendado) Los textos legales ya no tienen datos "Pendiente" (`FrontendPGC/src/legal/contenido.ts`). Si los cambias, sube `VERSION_LEGAL` en ese archivo y `VERSION` en `api_app/legal.py` (los dos iguales).

## 1. Reglas de Firestore (bloquear el acceso desde el navegador)

El backend es lo único que debe leer y escribir. Las reglas del repo (`firestore.rules`) niegan todo desde el navegador; el backend usa el SDK de administrador y no se ve afectado.

**Opción A, consola:** Firebase Console → Firestore Database → pestaña **Reglas** → pega el contenido de `firestore.rules` → **Publicar**.

**Opción B, línea de comandos** (en la carpeta del backend):
```
npx firebase-tools login
npx firebase-tools deploy --only firestore:rules
```

> Si el módulo de reconocimiento facial usa el SDK **de cliente** (no el de administrador), con estas reglas dejaría de funcionar. Confírmalo con Sharon antes de publicarlas.

## 2. Render (backend)

1. render.com → **New +** → **Blueprint** → conecta GitHub → elige `BackendPGC` (lee `render.yaml`).
   *(Alternativa: **New Web Service** manual con Build `pip install -r requirements.txt` y Start `gunicorn api_project.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`.)*
2. Completa las variables que pide:

| Variable | Valor |
|---|---|
| `FIREBASE_CREDENTIALS_JSON` | El JSON de credenciales **completo en una línea** (ver abajo) |
| `ADMIN_EMAILS` | Correos de administradores, separados por coma |
| `CORS_ALLOWED_ORIGINS` | De momento, déjalo con cualquier valor (se corrige en el paso 4) |
| `REGISTRO_DOMINIOS` | `ucundinamarca.edu.co` (**sin** `gmail.com`) |
| `DJANGO_DEBUG` | `False` (ya viene) |
| `DJANGO_SECRET_KEY` | Lo genera Render (ya viene) |
| `PYTHON_VERSION` | `3.12.13` (ya viene) |

   Para sacar el JSON en una línea, en tu computador:
   ```
   python3 -c "import json; print(json.dumps(json.load(open('CredencialesFirebase/asistenciaconreconocimiento-firebase-adminsdk.json'))))"
   ```
   Copia la salida completa y pégala como valor de `FIREBASE_CREDENTIALS_JSON`.
3. **Create**. El primer despliegue tarda unos minutos.
4. Comprueba: abre `https://TU-SERVICIO.onrender.com/api/health/`. Debe responder `"status": "OK"` y `"firebase": "Conectado"`.
5. Anota la dirección `https://TU-SERVICIO.onrender.com`.

> El plan gratis duerme el servicio tras 15 minutos sin uso: la primera petición después tarda ~1 minuto en responder. Es normal.

## 3. Netlify (frontend)

1. netlify.com → **Add new site** → **Import an existing project** → GitHub → `FrontendPGC`.
2. Netlify lee `netlify.toml` (build `npm run build`, carpeta `dist`). No cambies nada.
3. **Site configuration → Environment variables** → agrega:

| Variable | Valor |
|---|---|
| `VITE_API_URL` | `https://TU-SERVICIO.onrender.com/api` (con `/api` al final, sin barra extra) |

4. **Deploy site** (o *Trigger deploy* si ya había uno sin la variable).
5. Anota la dirección `https://TU-SITIO.netlify.app`.

## 4. Volver a Render: CORS

Render → tu servicio → **Environment** → `CORS_ALLOWED_ORIGINS` = `https://TU-SITIO.netlify.app`
(sin barra al final; varios dominios separados por coma) → **Save**. Se redespliega solo.

## 5. Firebase Authentication

Firebase Console → **Authentication** → **Settings** → **Authorized domains** → **Add domain** → `TU-SITIO.netlify.app`.
Y en **Sign-in method** deben estar habilitados **Google** y **Correo/contraseña**.

## 6. Primer ingreso

1. Abre `https://TU-SITIO.netlify.app` y entra con una cuenta de `ADMIN_EMAILS` (correo verificado). Verás "Acceso al sistema" → **Ir a administración**.
2. Pestaña **Docentes autorizados**: agrega correo, cédula y nombre de cada docente (o aprueba solicitudes).
3. El docente entra, acepta los términos y sube su horario desde "Mi horario". Después inscribe estudiantes en cada curso.
4. Los estudiantes entran con su correo institucional, eligen "Soy estudiante" y escriben su cédula.

## Verificación rápida

- [ ] `https://…onrender.com/api/health/` → `OK` y `Conectado`.
- [ ] El sitio carga y muestra el login.
- [ ] Iniciar sesión funciona (si no: dominio sin autorizar en Firebase, o `VITE_API_URL` mal).
- [ ] La consola del navegador no muestra errores de CORS.
- [ ] Un docente ve su Inicio; un estudiante vinculado ve el suyo.
- [ ] `/terminos` y `/privacidad` abren sin sesión.

## Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| Error de **CORS** en el navegador | `CORS_ALLOWED_ORIGINS` no tiene exactamente la dirección de Netlify (sin `/` final, con `https://`) |
| "No se pudo conectar con el servidor" | Render dormido (espera ~1 min) o `VITE_API_URL` incorrecta / sin `/api` |
| `auth/unauthorized-domain` al iniciar sesión | Falta autorizar el dominio de Netlify en Firebase Authentication |
| Render no arranca: "Falta DJANGO_SECRET_KEY" / "credenciales" | Falta esa variable de entorno o el JSON está incompleto |
| 401 en todas las llamadas | El token de Firebase no llega: revisa el dominio autorizado y que el proyecto de Firebase sea el mismo |
| Correo de verificación no llega a cuentas institucionales | El filtro de correo de la Universidad lo bloquea; usar "Continuar con Google" o pedir a TI que permita el remitente de Firebase |
| Datos de otra persona / "no tienes permiso" | Es la validación del backend funcionando; revisa que la cuenta esté vinculada |

## Volver atrás (rollback)

- **Render:** servicio → **Events/Deploys** → un despliegue anterior → **Rollback**.
- **Netlify:** **Deploys** → un despliegue anterior → **Publish deploy**.

## Seguridad: recordatorios

- `gmail.com` **no** va en `REGISTRO_DOMINIOS` de producción (cualquiera podría reclamar una cédula).
- `ADMIN_EMAILS` en producción: solo administradores reales.
- Si el JSON de credenciales llegó a compartirse o subirse por error: Firebase Console → Configuración del proyecto → Cuentas de servicio → generar una clave nueva y revocar la anterior.
- No subas `.env`, el JSON de credenciales ni logs: `.gitignore` ya los excluye.
