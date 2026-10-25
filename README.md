# EduCall

Sistema de llamadas, invitaciones y asistencia compuesto por **tres aplicaciones**:

| Aplicación | Carpeta | Función |
|---|---|---|
| **EduCall Server** | [educall-server](./educall-server/) | Sitio web Django, administración, API y base de datos central. |
| **EduCall Dial** | [educall-dial](./educall-dial/) | App Android para operadores: llamadas, resultados e invitaciones por WhatsApp. Requiere conexión HTTPS al servidor. |
| **EduCall Registro** | [educall-registro](./educall-registro/) | App Android para asistencia offline mediante QR o búsqueda, con importación y exportación de archivos. |

```mermaid
flowchart LR
  Admin[Administración web] --> Server[EduCall Server / PostgreSQL]
  Dial[EduCall Dial] -->|API autenticada por HTTPS| Server
  Server -->|Paquete firmado .attendance| Registro[EduCall Registro / Room]
  Registro -->|Archivo .attendance-results| Server
  Server --> Reportes[Reportes y revisión de conflictos]
```

## Inicio con Docker Compose

Esta configuración sirve para **desarrollo y pruebas locales**: usa PostgreSQL persistente y el servidor de desarrollo Django con `DEBUG=1`. No es un despliegue de producción ni ofrece HTTPS. Los comandos siguientes se ejecutan en PowerShell, desde la raíz del repositorio.

### 1. Requisitos

- Docker Desktop instalado y en ejecución, con contenedores Linux y Docker Compose v2.
- Git para descargar el repositorio.
- Puerto local `8080` disponible.

```powershell
git clone https://github.com/2025je/educall.git
Set-Location .\educall
docker version
docker compose version
```

Si ya tienes el repositorio, abre una terminal en su raíz; no vuelvas a clonarlo.

### 2. Configurar las variables

Copia el ejemplo sin sobrescribir un archivo de configuración existente:

```powershell
Copy-Item .\.env.example .\.env
```

Edita el archivo `.env` de la raíz y completa al menos:

```dotenv
DJANGO_SECRET_KEY=una-clave-larga-aleatoria-propia
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_TIME_ZONE=America/Mexico_City
EDUCALL_PORT=8080
POSTGRES_DB=educall
POSTGRES_USER=educall
POSTGRES_PASSWORD=una-contrasena-larga-aleatoria-propia
ATTENDANCE_SIGNING_PRIVATE_KEY=
ATTENDANCE_SIGNING_PUBLIC_KEY=
```

No uses los textos de ejemplo como secretos reales. No compartas ni subas `.env` al repositorio. Las claves de firma pueden quedar vacías para probar llamadas y administración; son necesarias para exportar paquetes de asistencia.

Compose carga `.env` e impone `POSTGRES_HOST=db`, `DJANGO_DEBUG=1` y el puerto interno `5432`. PostgreSQL no publica un puerto al equipo.

Si otro proyecto (por ejemplo, EduTrack) ya usa el puerto 8080, cambia `EDUCALL_PORT` a un puerto libre, como `8081`, y sustituye el puerto en las URL de esta guía. No es necesario detener los contenedores del otro proyecto.

### 3. Construir e iniciar

```powershell
docker compose up --build -d
docker compose ps
docker compose logs -f web
```

El servicio web espera a que PostgreSQL esté disponible y ejecuta las migraciones al iniciar. Espera a que ambos servicios aparezcan saludables. `Ctrl+C` deja de mostrar los registros, sin detener los contenedores.

### 4. Crear el administrador

```powershell
docker compose exec web python manage.py createsuperuser
```

Abre:

- Sitio de operadores: <http://localhost:8080/>.
- Inicio de sesión: <http://localhost:8080/accounts/login/>.
- Administración: <http://localhost:8080/admin/>.

### 5. Comandos habituales

```powershell
# Ver estado y registros
docker compose ps
docker compose logs -f web db

# Validar y ejecutar las pruebas, incluidas las de concurrencia en PostgreSQL
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py test attendance

# Reconstruir después de modificar el código o las dependencias
docker compose up --build -d

# Detener sin borrar la base de datos
docker compose down
```

Los datos se conservan en el volumen `postgres_data`. **No ejecutes `docker compose down -v` si necesitas conservarlos:** elimina los volúmenes y la base de datos. Cambiar `POSTGRES_PASSWORD` después de inicializar el volumen no cambia automáticamente la contraseña del usuario existente.

El contenedor usa una copia del código: no hay recarga automática ni montaje del repositorio. Reconstruye la imagen para aplicar cambios.

## Configuración inicial de EduCall Server

1. Entra a `/admin/` con el superusuario.
2. Crea las reuniones y sus participantes.
3. Crea los usuarios y asígnales los grupos `ADMINISTRADOR`, `REGISTRAR` u `OPERADOR`, creados automáticamente por las migraciones.
4. Para cada operador, crea un perfil con iniciales únicas de **dos letras mayúsculas**, por ejemplo `JU`. Sin ese perfil no puede recibir llamadas de la cola.
5. Para llamadas salientes, el participante debe tener `contact_authorized=True` y `do_not_contact=False`. Crea las tareas `CallTask` pendientes: no se generan automáticamente para todos los participantes.
6. Crea plantillas activas de WhatsApp. Las variables permitidas son `{{nombre}}`, `{{fecha_reunion}}`, `{{hora_reunion}}`, `{{lugar_reunion}}` y `{{codigo_asistencia}}`.

Los códigos, intentos de llamada, asistencias e historiales generados se consultan desde el administrador. Cambia la reunión de origen mediante el formulario del participante; se conserva el historial y se invalidan los códigos anteriores.

### Reglas principales

- Las llamadas se asignan transaccionalmente, con vencimiento de diez minutos. Si no contestan, vuelven a estar disponibles después de quince minutos.
- «No volver a contactar» excluye inmediatamente al participante de futuras asignaciones y mensajes.
- Aceptar una invitación genera o reutiliza un código como `JU-03-001`. El número de reunión debe estar entre 1 y 99.
- Abrir WhatsApp no significa que se haya enviado el mensaje; el operador confirma el envío por separado.
- Los conflictos entre asistencias de varios dispositivos se conservan para revisión; no se eliminan silenciosamente.

## Firma de paquetes para EduCall Registro

Genera una pareja Ed25519 **una sola vez**. Con los servicios iniciados:

```powershell
docker compose exec web python -c "import base64; from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; from cryptography.hazmat.primitives import serialization; k=Ed25519PrivateKey.generate(); print('PRIVATE='+base64.b64encode(k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode()); print('PUBLIC='+base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode())"
```

El comando muestra material sensible: ejecútalo en una terminal privada y no publiques su salida.

1. Guarda `PRIVATE` en `ATTENDANCE_SIGNING_PRIVATE_KEY` del `.env` de la raíz.
2. Guarda `PUBLIC` en `ATTENDANCE_SIGNING_PUBLIC_KEY` del mismo archivo.
3. Configura esa misma clave **pública** en EduCall Registro antes de compilarlo.
4. Recrea el servicio para cargar las variables:

```powershell
docker compose up -d --force-recreate web
```

La clave privada nunca debe entrar en el APK ni en Git. Guarda una copia segura fuera del repositorio. Rotar la clave requiere distribuir un nuevo APK con la clave pública correspondiente antes de importar paquetes nuevos.

## Compilar las apps Android

Son dos proyectos independientes y generan APK distintos que pueden instalarse juntos. Puedes compilarlos con Docker o con Android Studio.

### Opción A: Docker (sin instalar Java, Gradle ni Android Studio)

Requiere Docker Desktop con contenedores Linux, conexión a internet y espacio para el SDK, las dependencias y las imágenes (varios GB). Es recomendable disponer de al menos 4 GB de memoria para Docker. La imagen incluye JDK 17, Gradle 8.11.1, SDK 35 y Build-Tools 35.0.0. Su construcción acepta las licencias del SDK de Android; revisa y acepta sus términos antes de usarla.

Desde la raíz del repositorio, construye la imagen una vez:

```powershell
docker compose -f compose.android.yaml build dial
```

Compila EduCall Dial:

```powershell
docker compose -f compose.android.yaml run --rm --no-deps dial
```

Para EduCall Registro, configura `ATTENDANCE_SIGNING_PUBLIC_KEY` en el archivo `.env` de la raíz con la **clave pública** del servidor (consulta la sección de firma de paquetes). También puedes establecerla solo en esta terminal:

```powershell
$env:ATTENDANCE_SIGNING_PUBLIC_KEY = "TU_CLAVE_PUBLICA_ED25519_EN_BASE64"
docker compose -f compose.android.yaml run --rm --no-deps registro
```

Se exige una clave Ed25519 Base64 válida de 32 bytes para compilar Registro mediante Docker. Nunca pases la clave privada. Una variable definida en PowerShell tiene prioridad sobre `.env`; elimina la variable si quieres volver a usar el valor del archivo:

```powershell
Remove-Item Env:\ATTENDANCE_SIGNING_PUBLIC_KEY
```

Los APK se guardan en:

```text
artifacts\android\educall-dial-debug.apk
artifacts\android\educall-registro-debug.apk
```

La configuración Android es independiente de [compose.yaml](./compose.yaml): no requiere las credenciales PostgreSQL ni iniciar el servidor. Solo monta el código de la app correspondiente en modo lectura; compila una copia temporal y no modifica las carpetas originales. Las dependencias Gradle y la clave de firma debug se conservan en volúmenes Docker para acelerar compilaciones posteriores y permitir actualizar los APK debug sin cambiar su firma.

Vuelve a ejecutar `build dial` si cambia el Dockerfile o el script del constructor; para cambios de código basta con repetir `run`. Si una compilación falla, el comando devuelve un error y no publica un APK nuevo; podría quedar un APK de una compilación anterior en la carpeta de salida.

Los contenedores de compilación terminan al generar cada APK. No necesitan acceso USB ni ejecutan un emulador. Copia el APK al teléfono e instálalo autorizando la instalación desde esa fuente; para pruebas por USB usa Android Platform-Tools (`adb install -r ruta-al-apk`) en el equipo.

### Opción B: Android Studio

### Requisitos comunes

- Android Studio compatible con Android Gradle Plugin **8.9.1**.
- **JDK 17** configurado como Gradle JDK.
- Android SDK Platform **35**, Android SDK Build-Tools **35.0.0** y Platform-Tools, instalados desde SDK Manager.
- **Gradle 8.11.1** instalado y disponible en `PATH` para generar el wrapper inicial. Actualmente el repositorio no incluye `gradlew.bat` ni el JAR del wrapper.
- Conexión a internet para descargar las dependencias.
- Teléfono o emulador con Android **9 / API 28 o superior**.

Comprueba las herramientas:

```powershell
java -version
gradle -v
```

Abre por separado [educall-dial](./educall-dial/) y [educall-registro](./educall-registro/) con **File → Open** de Android Studio. Configura JDK 17 en **Settings → Build, Execution, Deployment → Build Tools → Gradle**. Android Studio debe configurar la ruta del SDK en el archivo local de cada proyecto; no subas esa ruta a Git.

### EduCall Dial

Desde la raíz del repositorio:

```powershell
Set-Location .\educall-dial
gradle wrapper --gradle-version 8.11.1
.\gradlew.bat assembleDebug
```

El APK se genera en `educall-dial\app\build\outputs\apk\debug\app-debug.apk`, tomando como referencia la raíz del repositorio.

La app permite iniciar sesión con una cuenta del servidor, solicitar una llamada, abrir el marcador, registrar resultados, buscar contactos y preparar invitaciones de WhatsApp. No guarda la contraseña y el servidor sigue validando permisos y consentimiento de contacto.

**Conexión:** introduce una URL `https://` con certificado válido y accesible desde el dispositivo. El servidor local Docker de esta guía solo ofrece HTTP y, por tanto, **no basta para conectar EduCall Dial**. Necesitas publicar el servidor detrás de HTTPS; no desactives la validación de certificados. `localhost` en un teléfono es el teléfono, no tu computadora.

### EduCall Registro

En [gradle.properties](./educall-registro/gradle.properties) añade la clave pública obtenida del servidor, sin comillas:

```properties
attendancePublicKey=TU_CLAVE_PUBLICA_ED25519_EN_BASE64
```

No uses la clave privada. Sin una clave pública válida, la app no podrá verificar los paquetes.

Desde una nueva terminal en la raíz del repositorio:

```powershell
Set-Location .\educall-registro
gradle wrapper --gradle-version 8.11.1
.\gradlew.bat assembleDebug
```

El APK se genera en `educall-registro\app\build\outputs\apk\debug\app-debug.apk`, tomando como referencia la raíz del repositorio.

### Instalar, probar y distribuir

Conecta un dispositivo con depuración USB habilitada o inicia un emulador. Desde cada proyecto:

```powershell
.\gradlew.bat installDebug
```

También puedes usar **Run** en Android Studio. Autoriza la conexión USB en el teléfono.

Para distribuir fuera de pruebas, usa **Build → Generate Signed App Bundle or APK**, crea o selecciona tu almacén de claves y elige APK o AAB según el canal. Conserva ese almacén y su contraseña fuera del repositorio: los necesitas para publicar actualizaciones. No distribuyas el APK debug como versión de producción.

Se verificó la compilación Docker de ambas apps y la firma de sus APK debug. Registro se compiló para esta comprobación con una clave pública temporal: recompílalo con la clave de tu servidor antes de importar paquetes reales. Los APK generados quedan fuera de Git. Siguen pendientes las pruebas funcionales en un teléfono o emulador (cámara, QR, llamadas, WhatsApp y persistencia).

## Uso offline de EduCall Registro

1. En el servidor, exporta el paquete firmado de la reunión mediante `GET /api/v1/meetings/{meeting_id}/package/` con una sesión autorizada.
2. Transfiere el archivo `.attendance` por un canal controlado e impórtalo mediante el selector de documentos de Registro.
3. La app verifica firma Ed25519, hashes y estructura antes de guardar los datos en Room.
4. Selecciona y confirma explícitamente la reunión de trabajo. La selección persiste y no cambia por escanear, buscar o importar.
5. Registra por QR o búsqueda de nombre, teléfono o código. La cámara es opcional; se evitan duplicados locales por participante y reunión efectiva.
6. Exporta los resultados `.attendance-results`. Las asistencias permanecen en el dispositivo.
7. Importa el archivo en el servidor mediante `POST /api/v1/attendance/import/`, campo multipart `file`, con una cuenta autorizada.

### Formatos y límites

- `.attendance` es un ZIP con `manifest.json`, `manifest.sig`, `meeting.json`, `participants.json` y `verification.json`. El manifiesto firmado incluye hashes SHA-256.
- El QR contiene únicamente el código de asistencia, no el nombre ni el teléfono. Un QR copiado no demuestra identidad.
- Los paquetes contienen datos personales en texto plano: protege su transferencia y el acceso al dispositivo.
- Por defecto no se permite asistencia cruzada entre reuniones. Habilitarla amplía los datos exportados.
- Un dispositivo offline no conoce cambios posteriores a la exportación. El servidor vuelve a validar los registros y deja los casos correspondientes en revisión.
- Los resultados Android conservan UUID estables para importación idempotente, pero no tienen firma de dispositivo: no prueban criptográficamente quién registró cada asistencia.
- No hay sincronización automática de dispositivos, envío automático de WhatsApp, confirmación de entrega ni adjunto automático del QR. El operador confirma el envío; la imagen QR se adjunta manualmente cuando corresponda.

## Ejecutar Django sin Docker

Requiere Python 3.11 o superior; se validó inicialmente con Python 3.12. Desde la raíz:

```powershell
Set-Location .\educall-server
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Abre <http://127.0.0.1:8000/>. Por defecto usa SQLite y `DEBUG=1`, solo para desarrollo. Django no carga automáticamente los archivos `.env` al ejecutarse directamente: establece las variables en PowerShell o en el entorno del proceso. El ejemplo para ese modo está en [educall-server/.env.example](./educall-server/.env.example).

## Producción y HTTPS

El Compose incluido **no es apto para producción**. Antes de publicar:

- Usa un servidor WSGI/ASGI de producción y sirve los archivos estáticos recopilados con `collectstatic`.
- Configura TLS con certificado válido y un dominio accesible desde Android.
- Establece `DJANGO_DEBUG=0`, una `DJANGO_SECRET_KEY` propia y `DJANGO_ALLOWED_HOSTS` con los dominios reales.
- Mantén PostgreSQL: fuera de DEBUG se rechaza SQLite por no ofrecer los bloqueos de fila necesarios para la cola.
- Conserva las cookies seguras y la redirección HTTPS; revisa la configuración del proxy sin confiar en cabeceras de clientes no fiables.
- Protege y respalda PostgreSQL, la clave privada Ed25519 y los secretos de despliegue.

El puerto del Compose está ligado a `127.0.0.1`: no expone la aplicación a toda la red. No publiques este servidor de desarrollo en internet como sustituto de un despliegue HTTPS.

## API y pruebas

La API vive bajo `/api/v1/` y requiere sesión Django y los permisos de cada operación. Los POST requieren CSRF. EduCall Dial usa las mismas reglas que el sitio web.

| Método y ruta relativa | Función |
|---|---|
| `POST /calls/next/` | Solicitar la siguiente llamada. |
| `POST /calls/{task_id}/result/` | Registrar resultado y notas. |
| `POST /calls/inbound/` | Registrar contacto entrante. |
| `GET /participants/search/?q=...` | Buscar participantes. |
| `GET /whatsapp/templates/` | Consultar plantillas activas. |
| `POST /whatsapp/prepare/` | Preparar un mensaje autorizado. |
| `POST /whatsapp/campaigns/prepare/` | Preparar entre 1 y 100 mensajes con plantillas por destinatario. |
| `POST /whatsapp/{log_id}/status/` | Actualizar el estado manual de un mensaje. |
| `POST /mobile/logout/` | Cerrar la sesión móvil. |
| `GET /meetings/` | Listar reuniones activas. |
| `GET /meetings/{meeting_id}/package/` | Descargar un paquete firmado. |
| `GET /codes/{code_id}/qr/` | Descargar el QR PNG de un código vigente. |
| `POST /attendance/import/` | Importar resultados offline. |
| `GET /attendance/report/{meeting_id}/` | Consultar totales de la reunión. |
| `POST /attendance/conflicts/{id}/resolve/` | Resolver un conflicto conservando los registros. |
| `GET /attendance/stream/` | Recibir eventos SSE publicados después del commit. |

Sin Docker, ejecuta desde la carpeta del servidor:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test attendance
```

Las pruebas cubren asignación, permisos, llamadas, consentimiento, códigos, paquetes firmados, estados de WhatsApp e importación con conflictos. Con SQLite se omiten las pruebas que necesitan bloqueo de filas; usa PostgreSQL mediante Compose para ejecutarlas. Los eventos en tiempo real usan SSE y una tabla persistente, no Django Channels/WebSockets.

Validación realizada: construcción y arranque de Compose con servicios saludables, inicio de sesión HTTP 200, migraciones sin cambios pendientes y **22 pruebas aprobadas en PostgreSQL, sin omisiones**. También se generaron ambos APK con Docker y se verificaron sus firmas. Esto no sustituye las pruebas Android en dispositivo pendientes.
