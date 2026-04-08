import discord
from discord.ext import commands, tasks
from discord import app_commands

from datetime import datetime, timezone, timedelta
import json
import os
import copy

ARCHIVO_PLANTILLAS = "plantillas.json"

def guardar_plantillas():
    with open(ARCHIVO_PLANTILLAS, "w", encoding="utf-8") as f:
        json.dump(plantillas_por_guild, f, indent=4, ensure_ascii=False)

# Cargar plantillas al iniciar
if os.path.exists(ARCHIVO_PLANTILLAS):
    with open(ARCHIVO_PLANTILLAS, "r", encoding="utf-8") as f:
        data = json.load(f)
        # Convertir todos los keys de guild a int
        plantillas_por_guild = {int(k): v for k, v in data.items()}
else:
    plantillas_por_guild = {}

# Función para guardar plantillas
ARCHIVO_EVENTOS = "eventos.json"

# Cargar eventos guardados
if os.path.exists(ARCHIVO_EVENTOS):
    with open(ARCHIVO_EVENTOS, "r", encoding="utf-8") as f:
        eventos_por_guild = json.load(f)
        # Convertir keys de guild a str si no lo son
        eventos_por_guild = {str(k): v for k, v in eventos_por_guild.items()}
else:
    eventos_por_guild = {}

# Función para guardar eventos
def guardar_eventos():
    with open(ARCHIVO_EVENTOS, "w", encoding="utf-8") as f:
        json.dump(eventos_por_guild, f, indent=4, ensure_ascii=False)

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =============================
# EVENTO: Cuando el bot se une a un servidor
# =============================
@bot.event
async def on_guild_join(guild: discord.Guild):
    """Cuando el bot se une a un servidor, crea la base de plantillas si no existe."""
    if guild.id not in plantillas_por_guild:
        plantillas_por_guild[guild.id] = {
            "Plantilla de ejemplo": {
                "fecha": "Pendiente",
                "hora": "Pendiente",
                "lugar": "Pendiente",
                "descripcion": "Descripción de ejemplo / Punto 2",
                "roles": {},  # Sin roles iniciales
                "rol": None,
                "imagen": None
            }
        }
    # Guardar en archivo
    guardar_plantillas()

eventos = {}  # Guardar eventos activos


# =============================
# FUNCIONES AUXILIARES
# =============================
def parsear_roles_string(roles_string):

    roles = {}

    lista_roles = [r.strip() for r in roles_string.split(",") if r.strip()]

    if len(lista_roles) > 20:
        raise ValueError("Solo se permiten máximo 20 roles.")

    for rol in lista_roles:

        partes = rol.split("-")

        # EMOJI-NOMBRE-CUPO
        if len(partes) == 3:
            emoji, nombre, cupo = partes

        # NOMBRE-CUPO
        elif len(partes) == 2:
            nombre, cupo = partes
            emoji = None

        else:
            raise ValueError(
                f"Formato incorrecto en '{rol}'. Debe ser EMOJI-NOMBRE-CUPO o NOMBRE-CUPO."
            )

        try:
            cupo = int(cupo)
        except:
            raise ValueError(
                f"Cupo inválido en '{rol}'. Debe ser un número entero."
            )

        roles[nombre.strip().lower()] = {
            "nombre": nombre.strip(),
            "emoji": emoji,
            "cupo": cupo,
            "usuarios": []
        }

    return roles

def obtener_datetime_evento(evento):

    # 🔹 Si es pendiente, no devolvemos fecha real
    if evento["fecha"] == "Pendiente" or evento["hora"] == "Pendiente":
        return None

    try:
        dt = datetime.strptime(
            f"{evento['fecha']} {evento['hora']}",
            "%d-%m-%Y %H:%M"
        )
        return dt.replace(tzinfo=timezone.utc)
    except:
        return None
    

def evento_finalizado(evento):
    inicio = obtener_datetime_evento(evento)
    # 🔹 Si no hay fecha válida, nunca está finalizado
    if inicio is None:
        return False

    fin = inicio + timedelta(hours=1, minutes=30)
    return datetime.now(timezone.utc) >= fin

async def marcar_eventos_finalizados():
    cambios = False
    for guild_id, eventos_guild in list(eventos_por_guild.items()):
        for mensaje_id, evento in list(eventos_guild.items()):
            if not evento.get("cerrado", False) and evento_finalizado(evento):
                evento["cerrado"] = True
                cambios = True
    if cambios:
        guardar_eventos()         

@tasks.loop(minutes=1)  # Revisa cada 1 minuto
async def revisar_eventos():
    await marcar_eventos_finalizados()

@bot.event
async def on_ready():
    print(f"Bot listo como {bot.user}")
    revisar_eventos.start()  # 🔹 Inicia el loop

def formatear_horas_multizona(hora_utc_str):
    dt_utc = datetime.strptime(hora_utc_str, "%H:%M")
    dt_utc = dt_utc.replace(tzinfo=timezone.utc)

    zonas = {
        "UTC": timezone.utc,
        "MX": timezone(timedelta(hours=-6)),
        "CO": timezone(timedelta(hours=-5)),
        "PE": timezone(timedelta(hours=-5)),
        "VE": timezone(timedelta(hours=-4)),
    }

    lines = []
    for label, tz in zonas.items():
        dt_local = dt_utc.astimezone(tz)
        if label == "UTC":
            hora_local = dt_local.strftime("%H:%M")  # 24 horas
            lines.append(f"⏰\u2003{hora_local} -- {label}")

        else:
            hora_local = dt_local.strftime("%I:%M %p").lower()
            if hora_local.startswith("0"):
                hora_local = hora_local[1:]  # Quitar cero inicial
            hora_local = hora_local.rjust(5)
            lines.append(f"⏰\u2003{hora_local} {label}")

    return "\n".join(lines)

def formatear_fecha_bonita(fecha_str):
    try:
        dt = datetime.strptime(fecha_str, "%d-%m-%Y")

        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        dia_semana = dias[dt.weekday()]
        mes = meses[dt.month - 1]

        return f"{dia_semana} {dt.day} de {mes} del {dt.year}"

    except:
        return fecha_str

def estado_evento(timestamp):
    ahora = datetime.now(timezone.utc)
    inicio = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    fin = inicio + timedelta(hours=1, minutes=30)

    if ahora < inicio:
        diff = inicio - ahora
        total_seg = int(diff.total_seconds())

        dias = total_seg // 86400
        horas = (total_seg % 86400) // 3600
        minutos = (total_seg % 3600) // 60

        return f"⌛Inicia en {dias}d {horas}h {minutos}m"

    elif inicio <= ahora < fin:
        return "🟢 Evento en curso 🟢"

    else:
        return "🚫 Evento finalizado 🚫"
    
def construir_embed(evento):
    color = discord.Color.gold()
    titulo = f"{evento['nombre']}"

    embed = discord.Embed(title=titulo, color=color)



    # ============================= COLUMNAS =============================
    if evento["fecha"] == "Pendiente" or evento["hora"] == "Pendiente":
        timestamp = None
        estado = "⌛ Pendiente"
    else:
        dt = datetime.strptime(
            f"{evento['fecha']} {evento['hora']}",
            "%d-%m-%Y %H:%M"
        )
        dt = dt.replace(tzinfo=timezone.utc)
        timestamp = int(dt.timestamp())
        estado = estado_evento(timestamp)


    if timestamp is None:
        columna_1 = (
            f"🗓 Pendiente\n\n"
            f"{estado}\n\n"
            f"📍 {evento['lugar']}\n"
        )
    else:
        columna_1 = (
            f"🗓 <t:{timestamp}:D>\n\n"
            f"{estado}\n\n"
            f"📍 {evento['lugar']}\n"
        )

    if evento.get("rol"):
        columna_1 += f"\n<@&{evento['rol']}>"
    
    columna_2 = ""
    # Mostrar la hora en varias zonas, con alineación
    if evento["hora"] == "Pendiente":
        horas_lista = [
        "⏰   ♾️ -- UTC",
        "⏰   ♾️ MX",
        "⏰   ♾️ CO",
        "⏰   ♾️ PE",
        "⏰   ♾️ VE",
    ]
    else:
        horas_multi = formatear_horas_multizona(evento["hora"])
        horas_lista = horas_multi.split("\n")
        

    # Aseguramos que las horas estén alineadas, con espacio a la derecha
    max_long = max(len(linea) for linea in horas_lista)  # Encontramos el texto más largo
    for hora in horas_lista:
        columna_2 += f"{hora.rjust(max_long)}\n"  # Rellenamos con espacios a la izquierda para que se alineen

    # Añadir ambas columnas en el embed
    embed.add_field(name="\u200b", value=columna_1, inline=True)
    embed.add_field(name="\u200b", value=columna_2, inline=True)

    # ============================= DESCRIPCIÓN =============================
    descripcion_formateada = "\n".join(
        f"🔹 {line.strip()}" for line in evento["descripcion"].split("/") if line.strip()
    )

    embed.add_field(name="\u200b", value=descripcion_formateada, inline=False)
    
    embed.add_field(name="\u200b", value="\n", inline=False)

    # ============================= ROLES (2 COLUMNAS) =============================
    contador = 0
    max_roles_con_fila = 14

    total_campos_base = len(embed.fields)  # los campos que ya tenías antes de roles

    for rol in evento["roles"].values():
        usuarios = "\n".join(
            f"{rol['emoji'] + ' ' if rol['emoji'] else ''}<@{u}>"
            for u in rol["usuarios"]
        ) or "—"

        embed.add_field(
            name=f"{rol['emoji'] + ' ' if rol['emoji'] else ''}{rol['nombre']} ({len(rol['usuarios'])}/{rol['cupo']})",
            value=usuarios,
            inline=True
        )

        contador += 1

        # Romper fila solo si hay pocos roles **y no superamos 25 campos en total**
        if contador % 2 == 0 and len(evento["roles"]) <= max_roles_con_fila and (total_campos_base + contador + contador//2) <= 25:
            embed.add_field(name="\u200b", value="\u200b", inline=True)

# ============================= BANCA =============================
    if evento.get("banca"):
        menciones_banca = " ".join(f"<@{u}>" for u in evento["banca"])
        embed.add_field(
            name="Banca:",
            value=menciones_banca,
            inline=False
    )


    # ============================= IMAGEN =============================
    if evento.get("imagen"):
        embed.set_image(url=evento["imagen"])

    # ============================= FOOTER =============================
    if evento_finalizado(evento):
        embed.set_footer(text="Evento finalizado • Panel bloqueado")

    return embed



# =============================
# BOTONES
# =============================
class BotonRol(discord.ui.Button):
    def __init__(self, rol_id, rol):

        emoji = rol.get("emoji")

        if isinstance(emoji, str) and emoji.startswith("<") and emoji.endswith(">"):
            emoji = discord.PartialEmoji.from_str(emoji)

        if emoji:
            super().__init__(
                label=rol["nombre"],
                emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=f"rol_{rol_id}"
            )
        else:
            super().__init__(
                label=rol["nombre"],
                style=discord.ButtonStyle.secondary,
                custom_id=f"rol_{rol_id}"
            )

        self.rol_id = rol_id

    async def callback(self, interaction: discord.Interaction):
        evento = eventos.get(self.view.message_id)
        if not evento:
            await interaction.response.send_message("❌ Evento no encontrado.", ephemeral=True)
            return

        user_id = interaction.user.id

        if "banca" not in evento:
            evento["banca"] = []

        for r in evento["roles"].values():
            if user_id in r["usuarios"]:
                r["usuarios"].remove(user_id)

        if user_id in evento["banca"]:
            evento["banca"].remove(user_id)

        rol = evento["roles"][self.rol_id]

        if len(rol["usuarios"]) >= rol["cupo"]:

            if user_id not in evento["banca"]:
                evento["banca"].append(user_id)

            await interaction.response.send_message(
                "⚠️ Rol lleno. Has sido agregado a la banca.",
                ephemeral=True
            )

            await interaction.message.edit(
                embed=construir_embed(evento),
                view=self.view
            )
            return

        rol["usuarios"].append(user_id)

        if not interaction.response.is_done():
            await interaction.response.defer()

        await interaction.message.edit(
            embed=construir_embed(evento),
            view=self.view
        )

class BotonDesuscribir(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="❌Quitar",
            style=discord.ButtonStyle.danger,
            custom_id="evento_quitar"
        )

    async def callback(self, interaction: discord.Interaction):
        evento = eventos[self.view.message_id]
        user_id = interaction.user.id

        for r in evento["roles"].values():
            if user_id in r["usuarios"]:
                r["usuarios"].remove(user_id)

        if "banca" in evento and user_id in evento["banca"]:
            evento["banca"].remove(user_id)

        await interaction.response.defer()
        await interaction.message.edit(embed=construir_embed(evento), view=self.view)

class BotonConfig(discord.ui.Button):
    def __init__(self, message_id):
        super().__init__(
            emoji="⚙️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"evento_config_{message_id}"
        )
        self.message_id = message_id

    async def callback(self, interaction: discord.Interaction):
        evento = eventos.get(self.message_id)
        if not evento:
            await interaction.response.send_message("❌ Evento no encontrado.", ephemeral=True)
            return

        if interaction.user.id != evento["creador"]:
            await interaction.response.send_message("❌ Solo el creador puede usar este botón.", ephemeral=True)
            return

        embed = discord.Embed(
            title="⚙️ Configuración",
            description="Selecciona un campo para editar desde el menú desplegable.",
            color=discord.Color.blue()
        )

        view = discord.ui.View()
        view.add_item(ConfiguracionSelect(interaction.user.id, self.message_id))

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class EventoView(discord.ui.View):
    def __init__(self, message_id=None):
        super().__init__(timeout=None)
        self.message_id = message_id

        if message_id and message_id in eventos:
            evento = eventos[message_id]

            for rol_id, rol in evento["roles"].items():
                self.add_item(BotonRol(rol_id, rol))

            self.add_item(BotonDesuscribir())
            self.add_item(BotonConfig(message_id))  # ← nuevo botón ⚙️



#  -------------Eliminado de Evento------------------
class ConfirmarEliminarView(discord.ui.View):
    def __init__(self, message_id):
        super().__init__(timeout=30)
        self.message_id = message_id

    @discord.ui.button(label="Sí", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        evento = eventos.get(self.message_id)

        if not evento:
            await interaction.response.edit_message(content=None, view=None)
            return

        # Verificar que sea el creador
        if interaction.user.id != evento["creador"]:
            await interaction.response.send_message("❌ No tienes permiso.", ephemeral=True)
            return

        canal = interaction.channel
        try:
            mensaje = await canal.fetch_message(self.message_id)
            await mensaje.delete()
        except Exception:
            pass


        eventos.pop(self.message_id, None)

        # Cierra la ventana ephemeral sin dejar mensaje residual
        await interaction.response.edit_message(content=None, view=None)

        guild_id_str = str(interaction.guild.id)
        if guild_id_str in eventos_por_guild:
            eventos_por_guild[guild_id_str].pop(str(self.message_id), None)
            guardar_eventos()

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Solo cerrar la ventana
        await interaction.response.edit_message(content=None, view=None)

#========== comando usar plantilas Select==========
class SeleccionarPlantilla(discord.ui.Select):
    def __init__(self, user_id, guild_id):
        plantillas_actuales = plantillas_por_guild.get(guild_id, {})

        opciones = [
            discord.SelectOption(label=nombre, description=f"Plantilla: {nombre}")
            for nombre in plantillas_actuales.keys()
        ]

        super().__init__(
            placeholder="Selecciona una plantilla...",
            min_values=1,
            max_values=1,
            options=opciones
        )

        self.user_id = user_id
        self.guild_id = guild_id
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Solo tú puedes usar este menú.",
                ephemeral=True
            )
            return

        guild_id = interaction.guild.id if interaction.guild else 0
        plantillas_actuales = plantillas_por_guild.get(guild_id, {})

        nombre = self.values[0]
        plantilla = plantillas_actuales.get(nombre)
        if not plantilla:
            await interaction.response.send_message("❌ Plantilla no encontrada en este servidor.", ephemeral=True)
            return

        # 🔥 Corrección automática si roles es string
        if isinstance(plantilla.get("roles"), str):
            plantilla["roles"] = parsear_roles_string(plantilla["roles"])

        plantilla_preview = plantilla.copy()
        plantilla_preview["nombre"] = nombre

        embed = construir_embed(plantilla_preview)
        embed.title = "¿Usar plantilla?"          # Título fijo
        embed.description = f"**{nombre}**"      # Nombre de la plantilla abajo
        embed.color = discord.Color.green()      # Color positivo

        view = ConfirmarUsarPlantillaView(self.user_id, plantilla_preview)

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )




#========== comando usar plantilas View==========
class SeleccionarPlantillaView(discord.ui.View):
    def __init__(self, user_id, guild_id):
        super().__init__(timeout=60)
        self.user_id = user_id
        # Crear el Select y agregarlo a la View
        self.add_item(SeleccionarPlantilla(user_id, guild_id))

#========== comando usar plantilas Botones==========



class ConfirmarUsarPlantillaView(discord.ui.View):
    def __init__(self, user_id, plantilla):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.plantilla = plantilla

    @discord.ui.button(label="Usar", style=discord.ButtonStyle.success)  # antes era "Confirmar"
    async def usar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Solo tú puedes usar esta plantilla.", ephemeral=True)
            return

        evento_real = copy.deepcopy(self.plantilla)
        evento_real["creador"] = self.user_id
        evento_real["canal"] = interaction.channel.id
        evento_real["cerrado"] = False
        evento_real["banca"] = []  # 🔥 NUEVO
        evento_real["recordatorio_enviado"] = False
        evento_real["dm_enviado"] = False


        for rol in evento_real.get("roles", {}).values():
            if "usuarios" not in rol:
                rol["usuarios"] = []

        if evento_real.get("rol"):

            mensaje_enviado = await interaction.channel.send(
                content=f"<@&{evento_real['rol']}>",
                embed=construir_embed(evento_real),
                allowed_mentions=discord.AllowedMentions(roles=True)
            )

            # borrar el ping visual pero mantener notificación
            await mensaje_enviado.edit(content=None)

        else:

            mensaje_enviado = await interaction.channel.send(
                embed=construir_embed(evento_real)
            )

        eventos[mensaje_enviado.id] = evento_real

        guild_id_str = str(interaction.guild.id)

        # Crear apartado del guild si no existe
        if guild_id_str not in eventos_por_guild:
            eventos_por_guild[guild_id_str] = {}

        # Guardar evento en JSON
        eventos_por_guild[guild_id_str][str(mensaje_enviado.id)] = evento_real
        guardar_eventos()

        await mensaje_enviado.edit(view=EventoView(mensaje_enviado.id))

        await interaction.response.edit_message(
            content=f"✅ Plantilla **{self.plantilla['nombre']}** publicada correctamente.",
            embed=None,
            view=None
        )

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger)  # antes era "Eliminar"
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Solo tú puedes cerrar esto.", ephemeral=True)
            return

        await interaction.response.edit_message(
            content="❌ Uso de plantilla cancelado.",
            embed=None,
            view=None
        )



# =============================
# SELECT ELIMINAR PLANTILLA
# =============================
class SeleccionarPlantillaEliminar(discord.ui.Select):
    def __init__(self, user_id, guild_id):
        plantillas_actuales = plantillas_por_guild.get(guild_id, {})

        opciones = [
            discord.SelectOption(label=nombre, description=f"Plantilla: {nombre}")
            for nombre in plantillas_actuales.keys()
        ]

        super().__init__(
            placeholder="Selecciona una plantilla para eliminar...",
            min_values=1,
            max_values=1,
            options=opciones
        )

        self.user_id = user_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Solo tú puedes usar este menú.",
                ephemeral=True
            )
            return

        guild_id = self.guild_id
        plantillas_actuales = plantillas_por_guild.get(guild_id, {})

        nombre = self.values[0]
        plantilla = plantillas_actuales.get(nombre)

        if not plantilla:
            await interaction.response.send_message(
                "❌ Plantilla no encontrada en este servidor.",
                ephemeral=True
            )
            return

        # 🔥 CORRECCIÓN AUTOMÁTICA SI ROLES ES STRING
        roles = plantilla.get("roles")
        if isinstance(roles, str) and roles.strip():
            plantilla["roles"] = parsear_roles_string(roles)
        elif not isinstance(roles, dict):
            plantilla["roles"] = {}

        plantilla_preview = plantilla.copy()
        plantilla_preview["nombre"] = nombre

        embed = construir_embed(plantilla_preview)
        embed.title = f"⚠️ Eliminar plantilla: {nombre}"
        embed.color = discord.Color.orange()

        view = ConfirmarEliminarPlantillaView(self.user_id, nombre)

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )

#========== comando eliminar plantilla view ==========
class SeleccionarPlantillaEliminarView(discord.ui.View):
    def __init__(self, user_id, guild_id):
        super().__init__(timeout=60)
        self.add_item(SeleccionarPlantillaEliminar(user_id, guild_id))


# =============================
# CONFIRMAR ELIMINACIÓN PLANTILLA
# =============================
class ConfirmarEliminarPlantillaView(discord.ui.View):
    def __init__(self, user_id, nombre_plantilla):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.nombre = nombre_plantilla

    @discord.ui.button(label="Sí", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Solo tú puedes confirmar.", ephemeral=True)
            return

        # Eliminar del diccionario
        guild_id = interaction.guild.id if interaction.guild else 0
        if guild_id in plantillas_por_guild and self.nombre in plantillas_por_guild[guild_id]:
            plantillas_por_guild[guild_id].pop(self.nombre)
            guardar_plantillas()

        await interaction.response.edit_message(
            content=f"✅ Plantilla '{self.nombre}' eliminada.",
            embed=None,
            view=None
        )
        
    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Solo tú puedes cerrar esto.", ephemeral=True)
            return

        # ⚠️ poner un texto mínimo, nunca None
        await interaction.response.edit_message(
            content="❌ Eliminación cancelada.",
            embed=None,
            view=None
        )



# =============================
# BOTONES PARA CONFIRMAR GUARDADO 
# =============================
class ConfirmarGuardarPlantillaView(discord.ui.View):
    def __init__(self, user_id, titulo, descripcion, roles, rol, imagen):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.titulo = titulo
        self.descripcion = descripcion
        self.roles = roles
        self.rol = rol
        self.imagen = imagen

    @discord.ui.button(label="Sí", style=discord.ButtonStyle.primary)
    async def guardar(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Solo el creador puede guardar esta plantilla.",
                ephemeral=True
            )
            return

        guild_id = interaction.guild.id  # Aquí reemplazamos por guild real más abajo
        # 🔹 Obtenemos guild real del interaction
        if hasattr(interaction, "guild") and interaction.guild:
            guild_id = interaction.guild.id
        else:
            guild_id = 0  # fallback

        # Crear espacio si no existe
        if guild_id not in plantillas_por_guild:
            plantillas_por_guild[guild_id] = {}

        # 🔥 Límite de 40 plantillas por servidor
        if len(plantillas_por_guild[guild_id]) >= 40:
            await interaction.response.send_message(
                "❌ Solo puedes guardar un máximo de 40 plantillas por servidor.",
                ephemeral=True
            )
            return

        # Guardar plantilla
        plantillas_por_guild[guild_id][self.titulo] = {
            "fecha": "Pendiente",
            "hora": "Pendiente",
            "lugar": "Pendiente",
            "descripcion": self.descripcion,
            "roles": self.roles,
            "rol": self.rol.id if self.rol else None,
            "imagen": self.imagen
        }
        guardar_plantillas()

        await interaction.response.edit_message(
            content="✅ Plantilla guardada correctamente.",
            embed=None,
            view=None
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Solo tú puedes cerrar esto.",
                ephemeral=True
            )
            return

        # ⚠️ Usar contenido mínimo para evitar error 50006
        await interaction.response.edit_message(
            content="❌ Operación cancelada.",
            embed=None,
            view=None
        )

# --- SELECT PARA CONFIGURACION ---
class ConfiguracionSelect(discord.ui.Select):
    def __init__(self, user_id, mensaje_id):
        opciones = [
            discord.SelectOption(label="Título", description="Editar el nombre del evento"),
            discord.SelectOption(label="Fecha", description="Editar la fecha del evento"),
            discord.SelectOption(label="Hora", description="Editar la hora del evento"),
            discord.SelectOption(label="Lugar", description="Editar el lugar del evento"),
            discord.SelectOption(label="Descripción", description="Editar la descripción del evento"),
        ]
        super().__init__(placeholder="Selecciona un campo para editar...", min_values=1, max_values=1, options=opciones)
        self.user_id = user_id
        self.mensaje_id = mensaje_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Solo el creador puede editar.", ephemeral=True)
            return

        campo = self.values[0]
        await interaction.response.send_modal(EditarCampoModal(self.user_id, self.mensaje_id, campo))

# --- MODAL PARA EDITAR CAMPOS ---
class EditarCampoModal(discord.ui.Modal):
    def __init__(self, user_id, mensaje_id, campo):
        super().__init__(title=f"Editar {campo}")
        self.user_id = user_id
        self.mensaje_id = mensaje_id
        self.campo = campo

        # Diccionario con placeholders específicos
        placeholders = {
            "Título": "Nombre de la actividad",
            "Fecha": "Ejem: 03-03-2026",
            "Hora": "Hora UTC ejem: 02:00 ",
            "Lugar": "Sitio de reunion",
            "Descripción": (
                "Anotaciones o cosas que requieras"
                ". Separa los puntos con / Ejem:  Punto 1 / Punto 2"
            )
        }

        self.add_item(discord.ui.TextInput(
            label=f"Nuevo {campo}",
            placeholder=placeholders.get(campo, f"Ingresa el nuevo {campo.lower()}..."),
            style=discord.TextStyle.short if campo != "Descripción" else discord.TextStyle.paragraph
        ))

    async def on_submit(self, interaction: discord.Interaction):
        evento = eventos.get(self.mensaje_id)
        if not evento:
            await interaction.response.send_message("❌ Evento no encontrado.", ephemeral=True)
            return

        nuevo_valor = self.children[0].value
        if self.campo == "Título":
            evento["nombre"] = nuevo_valor
        elif self.campo == "Fecha":
            evento["fecha"] = nuevo_valor
            evento.pop("ultimo_minuto", None)
            evento["recordatorio_enviado"] = False
            evento["dm_enviado"] = False
        
        elif self.campo == "Hora":
            try:
                datetime.strptime(nuevo_valor, "%H:%M")
                evento["hora"] = nuevo_valor
        
                evento.pop("ultimo_minuto", None)
                evento["recordatorio_enviado"] = False
                evento["dm_enviado"] = False
        
            except ValueError:
                await interaction.response.send_message(
                    "❌ Formato de hora inválido. Debe ser HH:MM en UTC.",
                    ephemeral=True
                )
                return
            try:
                datetime.strptime(nuevo_valor, "%H:%M")
                evento["hora"] = nuevo_valor
            except ValueError:
                await interaction.response.send_message(
                    "❌ Formato de hora inválido. Debe ser HH:MM en UTC.", ephemeral=True
                )
                return
        elif self.campo == "Lugar":
            evento["lugar"] = nuevo_valor
        elif self.campo == "Descripción":
            evento["descripcion"] = nuevo_valor

        try:
            canal = interaction.channel
            mensaje = await canal.fetch_message(self.mensaje_id)
            await mensaje.edit(embed=construir_embed(evento))
        except Exception as e:
            print("Error actualizando evento:", e)
        guardar_eventos()
        await interaction.response.send_message(f"✅ {self.campo} actualizado correctamente.", ephemeral=True)
## ## ## ## ## ## #
#  Comando /crear_plantilla
# ## ## ## ## ## #
@bot.tree.command(name="crear_plantilla", description="Crea una plantilla de evento sin modal")

async def crear_plantilla(
    interaction: discord.Interaction,
    titulo: str,
    descripcion: str,
    roles: str,
    rol: discord.Role = None,
    imagen: str = None
):
    # Parsear roles
    roles_parseados = {}
    lista_roles = [r.strip() for r in roles.split(",") if r.strip()]

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Solo administradores pueden usar este comando.", ephemeral=True)
        return
    
    if len(lista_roles) > 20:
        await interaction.response.send_message("❌ Solo se permiten un máximo de 20 roles.", ephemeral=True)
        return


    # Procesar roles usando la función auxiliar
    try:
        roles_parseados = parsear_roles_string(roles)
    except ValueError as e:
        await interaction.response.send_message(f"⚠️ Error al procesar los roles: {e}", ephemeral=True)
        return

    # Crear un "evento temporal" solo para previsualización
    evento_temporal = {
        "nombre": titulo,
        "fecha": "Pendiente",
        "hora": "Pendiente",
        "lugar": "Pendiente",
        "descripcion": descripcion,
        "roles": roles_parseados,
        "rol": rol,
        "imagen": imagen,
        "creador": interaction.user.id
    }

    embed_previo = construir_embed(evento_temporal)
    embed_previo.title = f"📝 Previsualización de la plantilla: {titulo}"

    view = ConfirmarGuardarPlantillaView(
        user_id=interaction.user.id,
        titulo=titulo,
        descripcion=descripcion,
        roles=roles_parseados,
        rol=rol,
        imagen=imagen
    )

    await interaction.response.send_message(
        embed=embed_previo,
        view=view,
        ephemeral=True
    )




# =============================
# COMANDO /crear_evento
# =============================
@bot.tree.command(name="crear_evento", description="Crear un evento")

@app_commands.describe(
    nombre="Nombre del evento",
    fecha="Formato DD-MM-YYYY en UTC (ej: 12-03-2026)",
    hora="Formato HH:MM en UTC (ej: 21:30)",
    lugar="Sitio de reunion",
    descripcion="Separa los puntos con /",
    roles="EMOJI-NOMBRE(CUPO),separados por coma ejem:🛡️-Tanke(1),⛑️-Healer(2)",
    rol="Rol a mencionar (opcional)",
    imagen="URL de imagen (opcional)"
)
async def crear_evento(
    interaction: discord.Interaction,
    nombre: str,
    fecha: str,
    hora: str,
    lugar: str,
    descripcion: str,
    roles: str,
    rol: discord.Role = None,
    imagen: str = None
):
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Solo administradores pueden usar este comando.", ephemeral=True)
        return

    roles_parseados = {}
    lista_roles = [r.strip() for r in roles.split(",") if r.strip()]

    if len(lista_roles) > 20:
        await interaction.response.send_message("❌ Solo se permiten un máximo de 20 roles.", ephemeral=True)
        return

    # Validar hora
    try:
        datetime.strptime(hora, "%H:%M")
    except ValueError:
        await interaction.response.send_message(
            "❌ Formato de hora inválido. Debe ser HH:MM en UTC.", ephemeral=True
        )
        return

  
    # Procesar roles usando la función auxiliar
    try:
        roles_parseados = parsear_roles_string(roles)
    except ValueError as e:
        await interaction.response.send_message(f"⚠️ Error al procesar los roles: {e}", ephemeral=True)
        return

    # Crear datos del evento
    evento_data = {
        "nombre": nombre,
        "fecha": fecha,
        "hora": hora,
        "lugar": lugar,
        "descripcion": descripcion,
        "roles": roles_parseados,
        "rol": rol.id if rol else None,  # Guardas solo el ID
        "canal": interaction.channel_id,
        "creador": interaction.user.id,
        "cerrado": False,
        "imagen": imagen,
        "banca": [],  
        "recordatorio_enviado": False,   # 🔥 NUEVO
        "dm_enviado": False,              # 🔥 NUEVO
        "terminado": False  # Nuevo campo para marcar cuando el evento finalizó
}

    embed = construir_embed(evento_data)

    # Si hay rol, mandar ping real pero ocultarlo después
    if rol:

        await interaction.response.send_message(
            content=f"<@&{rol.id}>",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(roles=True)
        )

        mensaje = await interaction.original_response()

        # borrar el ping visual
        await mensaje.edit(content=None)

    else:

        await interaction.response.send_message(embed=embed)
        mensaje = await interaction.original_response()

    # Guardar evento y asignar botones
    eventos[mensaje.id] = evento_data

    guild_id_str = str(interaction.guild.id)

    # Crear apartado del guild si no existe
    if guild_id_str not in eventos_por_guild:
        eventos_por_guild[guild_id_str] = {}

    # Guardar el evento usando el ID del mensaje como key
    eventos_por_guild[guild_id_str][str(mensaje.id)] = evento_data
    guardar_eventos()

    await mensaje.edit(view=EventoView(mensaje.id))

# =============================
# COMANDO ELIMINAR PLANTILLA
# =============================
@bot.tree.command(name="eliminar_plantilla", description="Eliminar una plantilla guardada")

async def eliminar_plantilla(interaction: discord.Interaction):
    guild_id = interaction.guild.id if interaction.guild else 0
    plantillas_actuales = plantillas_por_guild.get(guild_id, {})

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Solo administradores pueden usar este comando.", ephemeral=True)
        return
    
    if not plantillas_actuales:
        await interaction.response.send_message(
            "❌ No hay plantillas guardadas en este servidor.",
            ephemeral=True
        )
        return

    # Abrir el menú de selección
    view = SeleccionarPlantillaEliminarView(interaction.user.id, guild_id)

    await interaction.response.send_message(
        "Selecciona la plantilla que deseas eliminar:",
        view=view,
        ephemeral=True
    )


# =============================
# FUNCION PARA ENVIAR RECORDATORIO 20 MIN ANTES
# =============================
async def enviar_recordatorio(evento, message_id):
    """Envía un recordatorio 20 minutos antes del evento."""

    canal = bot.get_channel(evento["canal"])
    if not canal:
        return

    # =============================
    # USUARIOS CONFIRMADOS (ROLES)
   
    usuarios_roles = set()
    for rol in evento["roles"].values():
        usuarios_roles.update(rol["usuarios"])

    # =============================
    # USUARIOS EN BANCA
 
    usuarios_banca = set(evento.get("banca", []))

    # Si no hay nadie en roles, no enviamos nada
    if not usuarios_roles:
        return

    # =============================
    # CONSTRUIR MENSAJE
  
    menciones_roles = " ".join(f"<@{u}>" for u in usuarios_roles)

    contenido = (
        f"🚨 Esta por iniciar el evento **{evento['nombre']}** en 20 minutos! 🚨\n"
        f"Preparen sus builds:\n"
        f"{menciones_roles}"
    )

    # 🔥 Si hay banca, agregamos sección extra
    if usuarios_banca:
        menciones_banca = " ".join(f"<@{u}>" for u in usuarios_banca)

        contenido += (
            f"\n\n🪑 Los de Banca atentos por si se libera un cupo.\n"
            f"{menciones_banca}"
        )

    await canal.send(contenido)

    # Marcar como enviado
    evento["recordatorio_enviado"] = True

# =============================
# FUNCION PARA ENVIAR DM 10 MIN ANTES
# =============================
async def enviar_dm_recordatorio(evento):
    """Envía mensaje privado 10 minutos antes del evento."""

    usuarios = set()

    # Usuarios de roles
    for rol in evento["roles"].values():
        usuarios.update(rol["usuarios"])

    # Usuarios en banca
    usuarios.update(evento.get("banca", []))

    if not usuarios:
        return

    mensaje = (
    f"🚨 ¡RECORDATORIO RÁPIDO! 🚨\n\n"
    f"🎯 Evento: \"{evento['nombre']}\"\n\n"
    f"📍 Lugar: \"{evento['lugar']}\"\n\n"
    f"⏰ Inicia en: ~10 minutos\n\n"
    f"⚡ Conéctate a la llamada, ajusta tu build y preparate para darlo todo ⚡"
)

    for user_id in usuarios:
        try:
            usuario = await bot.fetch_user(user_id)
            await usuario.send(mensaje)
        except:
            pass

    evento["dm_enviado"] = True

# =============================
# LOOP UNIFICADO PARA ACTUALIZAR, RECORDAR Y CERRAR EVENTOS
# =============================
@tasks.loop(seconds=30)
async def gestionar_eventos():
    ahora = datetime.now(timezone.utc)

    for message_id, evento in list(eventos.items()):
        canal = bot.get_channel(evento["canal"])
        if not canal:
            continue

        mensaje = canal.get_partial_message(message_id)

        # si no tiene fecha u hora
        if evento["fecha"] == "Pendiente" or evento["hora"] == "Pendiente":
            continue

        dt_evento = obtener_datetime_evento(evento)
        if dt_evento is None:
            continue

        minutos_para_evento = (dt_evento - ahora).total_seconds() / 60
        minutos_restantes = int((dt_evento - ahora).total_seconds() // 60)

        # actualizar contador
        if evento.get("ultimo_minuto") != minutos_restantes:
            evento["ultimo_minuto"] = minutos_restantes
            try:
                await mensaje.edit(embed=construir_embed(evento))
            except Exception:
                pass

        # RECORDATORIO 20 MIN
        if 19 <= minutos_para_evento <= 20 and not evento.get("recordatorio_enviado", False):
            await enviar_recordatorio(evento, message_id)

        # DM 10 MIN
        if 9 <= minutos_para_evento <= 10 and not evento.get("dm_enviado", False):
            await enviar_dm_recordatorio(evento)

        # cerrar evento
        if minutos_para_evento < -90:
            try:
                await mensaje.edit(view=None)
            except Exception:
                pass

# =============================
# COMANDO /HELP VISUAL FORMATEADO
# =============================
@bot.tree.command(name="help", description="Muestra las instrucciones de uso del bot de forma visual y clara")

async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📚 Manual del Bot de Eventos",
        description="¡Bienvenido! Aquí tienes todas las instrucciones para usar el bot de forma correcta y divertida.\n\n",
        color=discord.Color.teal()
    )

    # -------------------- CREAR EVENTO --------------------
    embed.add_field(
        name="📝 Crear evento",
        value=(
            "Usa `/evento` con los siguientes parámetros:\n\n"
            "• **nombre:** Nombre del evento\n"
            "• **fecha:** Formato `DD-MM-YYYY` (ej. 12-02-2026)\n"
            "• **hora:** Formato `HH:MM` UTC (ej. 21:30)\n"
            "• **lugar:** Lugar del evento\n"
            "• **descripción:** Usa `/` para separar puntos y aparte\n"
            "• **imagen:** (Opcional) URL de la imagen del evento\n\n"
        ),
        inline=False
    )

    # -------------------- USO DE ROLES --------------------
    embed.add_field(
        name="🎯 Uso de los roles",
        value=(
            "• Cada rol se separa con **coma `,`**\n"
            "• Solo puedes tener un Maximo de 20 roles diferentes**\n"
            "• Dentro de cada rol, el **emoji** y el **nombre** se separan con **`-`**\n"
            "• El **cupo máximo** se indica dentro del paréntesis `()`\n"
            "• **roles:** Lista separada por `,` con formato `EMOJI-NOMBRE(CUPO)`\n\n"
            "📌 **Ejemplo de roles:**\n"
            "`🛡️-Guerrero(10), 🧙-Mago(5)`\n\n"
        ),
        inline=False
    )

    # -------------------- BOTONES --------------------
    embed.add_field(
        name="🔘 Botones del evento",
        value=(
            "• Pulsa un botón de rol para unirte a ese rol\n"
            "• Pulsa ❌Quitar para eliminar tu inscripción de todos los roles\n"
            "• ⚙️ Solo el creador puede usar este botón para borrar el evento\n"
            "• Al borrar el evento, todos los botones desaparecen automáticamente\n"
            "• Los roles muestran el cupo y los usuarios inscritos en tiempo real\n"
        ),
        inline=False
    )

    # -------------------- CONSEJOS --------------------
    embed.add_field(
        name="💡 Consejos útiles",
        value=(
            "• Revisa la fecha y hora en UTC antes de crear el evento\n"
            "• Usa emojis claros para los roles para que todos los usuarios identifiquen fácilmente\n"
            "• Mantén la descripción clara usando `/` para puntos y aparte\n"
            "• Recuerda revisar el cupo de cada rol antes de unirte"
        ),
        inline=False
    )

    embed.set_footer(text="👀 Solo tú puedes ver este mensaje | ¡Diviértete creando eventos!")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# =============================
# COMANDO /usar_plantillas
# =============================
@bot.tree.command(name="usar_plantillas", description="Selecciona una plantilla de evento para usarla")

async def usar_plantillas(interaction: discord.Interaction):
    # Obtenemos el guild ID
    guild_id = interaction.guild.id if interaction.guild else 0

    

    # Verificar si hay plantillas para este servidor
    if guild_id not in plantillas_por_guild or not plantillas_por_guild[guild_id]:
        await interaction.response.send_message(
            "❌ No hay plantillas guardadas para este servidor.",
            ephemeral=True
        )
        return

    # Crear la vista de selección pasando solo las plantillas de este servidor
    view = SeleccionarPlantillaView(interaction.user.id, interaction.guild.id)
    await interaction.response.send_message(
        "📋 Selecciona una plantilla para previsualizar:",
        view=view,
        ephemeral=True
    )


# =============================
# READY
# =============================
@bot.event
async def on_ready():
    print(f"✅ Bot listo: {bot.user}")

    # 🔹 Reconstruir eventos en memoria desde el JSON
    eventos.clear()
    for guild_id, eventos_guild in eventos_por_guild.items():
        for msg_id, evento in eventos_guild.items():
            eventos[int(msg_id)] = evento

    # 🔹 Registrar botones persistentes para que funcionen después de reiniciar el bot
    for msg_id in eventos:
        bot.add_view(EventoView(int(msg_id)))

    # 🔹 Sincronización global de comandos
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} comandos sincronizados globalmente")
    except Exception as e:
        print("❌ Error al sincronizar:", e)

    # 🔹 Iniciar loops si no están corriendo
    if not gestionar_eventos.is_running():
        gestionar_eventos.start()

    if not limpiar_eventos_json.is_running():
        limpiar_eventos_json.start()

@tasks.loop(minutes=5)
async def limpiar_eventos_json():
    ahora = datetime.now(timezone.utc)
    cambios = False

    for guild_id, guild_eventos in list(eventos_por_guild.items()):
        for msg_id, evento in list(guild_eventos.items()):
            # 🔹 Marcar como terminado si ya pasó el tiempo
            if not evento.get("terminado") and evento_finalizado(evento):
                evento["terminado"] = True

            # 🔹 Solo borrar si terminó hace más de 2 horas
            if evento.get("terminado"):
                dt_evento = obtener_datetime_evento(evento)
                if dt_evento and ahora >= dt_evento + timedelta(hours=3):  
                    # 1.5 h de duración + 2 h → 3.5 h
                    guild_eventos.pop(msg_id, None)
                    cambios = True

    if cambios:
        guardar_eventos()

@bot.event
async def on_message_delete(message):

    if message.id in eventos:
        eventos.pop(message.id, None)

        guild_id_str = str(message.guild.id)

        if guild_id_str in eventos_por_guild:
            eventos_por_guild[guild_id_str].pop(str(message.id), None)
            guardar_eventos()

        print(f"Evento eliminado automáticamente: {message.id}")



bot.run(os.environ["TOKEN"])








