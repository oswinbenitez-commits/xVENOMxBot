

import discord
from discord.ext import commands, tasks
from discord import app_commands

from datetime import datetime, timezone, timedelta
import json
import os
import copy


from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
PANEL_GUILD_ID = int(os.environ.get("PANEL_GUILD_ID", "0"))

if not MONGO_URI:
    raise Exception("❌ MONGO_URI no está configurado en las variables de entorno")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client["discord_bot"]

# 🔥 Estado global de Mongo
MONGO_ACTIVO = False

# 🔥 Verificar conexión SIN tumbar el bot
try:
    client.server_info()
    print("✅ Conectado a MongoDB Atlas")
    MONGO_ACTIVO = True
except Exception as e:
    print("⚠️ Mongo no disponible, el bot seguirá sin base de datos:", e)


# 🔥 Función para verificar estado
def verificar_mongo():
    return MONGO_ACTIVO
def solo_admin():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.id == ADMIN_ID
    return app_commands.check(predicate)

# ==============================
# COLECCIONES
# ==============================
coleccion_plantillas = db["plantillas"]
coleccion_eventos = db["eventos"]
coleccion_servidores = db["servidores"]

if verificar_mongo():
    coleccion_plantillas.create_index(
        [("guild_id", 1), ("nombre", 1)],
        unique=True
    )
    coleccion_eventos.create_index(
        [("guild_id", 1), ("message_id", 1)],
        unique=True
    )


def guardar_plantilla_db(guild_id, nombre, data):
    if not verificar_mongo():
        print("⚠️ Mongo no disponible, no se guardó la plantilla")
        return

    try:
        coleccion_plantillas.update_one(
            {"guild_id": guild_id, "nombre": nombre},
            {"$set": {
                "guild_id": guild_id,
                "nombre": nombre,
                **data
            }},
            upsert=True
        )
    except Exception as e:
        print("❌ Error guardando plantilla:", e)
def obtener_plantillas_db(guild_id):
    if not verificar_mongo():
        return {}

    docs = coleccion_plantillas.find({"guild_id": guild_id})
    resultado = {}

    for doc in docs:
        doc.pop("_id", None)
        resultado[doc["nombre"]] = doc

    return resultado

def eliminar_plantilla_db(guild_id, nombre):
    if not verificar_mongo():
        print("⚠️ Mongo no disponible, no se eliminó la plantilla")
        return

    coleccion_plantillas.delete_one({
        "guild_id": guild_id,
        "nombre": nombre
    })

def guardar_evento_db(guild_id, message_id, data):
    if not verificar_mongo():
        print("⚠️ Mongo no disponible, no se guardó el evento")
        return

    try:
        coleccion_eventos.update_one(
            {"guild_id": guild_id, "message_id": message_id},
            {"$set": {
                "guild_id": guild_id,
                "message_id": message_id,
                **data
            }},
            upsert=True
        )
    except Exception as e:
        print("❌ Error guardando evento:", e)
def cargar_eventos_db():
    eventos = {}

    if not verificar_mongo():
        print("⚠️ Mongo no disponible, no se cargaron eventos")
        return eventos

    try:
        docs = coleccion_eventos.find()

        for doc in docs:
            if "message_id" not in doc:
                continue

            message_id = int(doc["message_id"])
            doc["guild_id"] = int(doc.get("guild_id", 0))
            eventos[message_id] = doc

    except Exception as e:
        print("❌ Error cargando eventos:", e)

    return eventos
def eliminar_evento_db(guild_id, message_id):
    if not verificar_mongo():
        print("⚠️ Mongo no disponible, no se eliminó el evento")
        return

    coleccion_eventos.delete_one({
        "guild_id": int(guild_id),
        "message_id": int(message_id),
    })
def servidor_autorizado(guild_id: int) -> bool:
    if not verificar_mongo():
        return False

    return coleccion_servidores.find_one({"guild_id": guild_id}) is not None
def requiere_acceso():
    async def predicate(interaction: discord.Interaction):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ Este comando solo funciona en servidores.",
                ephemeral=True
            )
            return False
        if interaction.user.id == ADMIN_ID:
            return True

        if servidor_autorizado(interaction.guild.id):
            return True

        await interaction.response.send_message(
            "🔒 Este servidor no tiene acceso.\n\n📩 Usa /solicitar_acceso",
            ephemeral=True
        )
        return False

    return app_commands.check(predicate)


intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)



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
    for evento in eventos.values():
        if not evento.get("cerrado", False) and evento_finalizado(evento):
            evento["cerrado"] = True
            

@tasks.loop(minutes=1)
async def revisar_eventos():
    await marcar_eventos_finalizados()



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
    if evento.get("ocultar_fecha_hora"):

        # 🔥 SOLO LUGAR + ROL
        columna_1 = f"📍 {evento['lugar']}\n"

        if evento.get("rol"):
            columna_1 += f"\n<@&{evento['rol']}>"

        embed.add_field(name="\u200b", value=columna_1.strip(), inline=False)

    else:
        # ================= NORMAL =================
        if evento["fecha"] == "Pendiente" or evento["hora"] == "Pendiente":
            timestamp = None
            estado = "⌛ Pendiente"
        else:
            try:
                dt = datetime.strptime(
                    f"{evento['fecha']} {evento['hora']}",
                    "%d-%m-%Y %H:%M"
                )
                dt = dt.replace(tzinfo=timezone.utc)
                timestamp = int(dt.timestamp())
                estado = estado_evento(timestamp)
            except ValueError:
                timestamp = None
                estado = "❌ Fecha inválida"

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

        # HORAS
        if evento["hora"] == "Pendiente":
            horas_lista = [
                "⏰   ♾️ -- UTC",
                "⏰   ♾️ MX",
                "⏰   ♾️ CO",
                "⏰   ♾️ PE",
                "⏰   ♾️ VE",
            ]
        else:
            horas_lista = formatear_horas_multizona(evento["hora"]).split("\n")

        columna_2 = "\n".join(horas_lista)

        embed.add_field(name="\u200b", value=columna_1, inline=True)
        embed.add_field(name="\u200b", value=columna_2, inline=True)


    # ============================= DESCRIPCIÓN (SIEMPRE FUERA) =============================
    descripcion = evento.get("descripcion") or ""

    descripcion_formateada = "\n".join(
        f"🔹 {line.strip()}" for line in descripcion.split("/") if line.strip()
    )

    embed.add_field(name="\u200b", value=descripcion_formateada, inline=False)

    embed.add_field(name="\u200b", value="\n", inline=False)
    # ============================= ROLES (2 COLUMNAS) =============================
    contador = 0
    max_roles_con_fila = 14

    total_campos_base = len(embed.fields)  # los campos que ya tenías antes de roles

    for rol in evento.get("roles", {}).values():
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

        if contador % 2 == 0 and len(evento.get("roles", {})) <= max_roles_con_fila and (total_campos_base + contador + contador//2) <= 25:
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
    if evento.get("cerrado", False) or evento_finalizado(evento):
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
        
        if not self.view or not self.view.message_id:
            return
        evento = eventos.get(self.view.message_id)
        if not evento:
            await interaction.response.send_message("❌ Evento no encontrado.", ephemeral=True)
            return

        user_id = interaction.user.id

        if "banca" not in evento:
            evento["banca"] = []

        for r in evento.get("roles", {}).values():
            if user_id in r["usuarios"]:
                r["usuarios"].remove(user_id)

        if user_id in evento["banca"]:
            evento["banca"].remove(user_id)

        rol = evento.get("roles", {}).get(self.rol_id)
        if not rol:
            await interaction.response.send_message("❌ Rol no válido.", ephemeral=True)
            return

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
            guardar_evento_db(int(interaction.guild.id), int(self.view.message_id), evento)
            return

        if user_id not in rol["usuarios"]:
            rol["usuarios"].append(user_id)

        try:
            await interaction.response.defer()
        except:
            pass

        await interaction.message.edit(
            embed=construir_embed(evento),
            view=self.view
        )
        
        guardar_evento_db(int(interaction.guild.id), int(self.view.message_id), evento)

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

        for r in evento.get("roles", {}).values():
            if user_id in r["usuarios"]:
                r["usuarios"].remove(user_id)

        if "banca" in evento and user_id in evento["banca"]:
            evento["banca"].remove(user_id)

        await interaction.response.defer()
        await interaction.message.edit(embed=construir_embed(evento), view=self.view)
        guardar_evento_db(int(interaction.guild.id), int(self.view.message_id), evento)
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

            for rol_id, rol in evento.get("roles", {}).items():
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
            await interaction.response.edit_message(content=" ", view=None)
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
        await interaction.response.edit_message(content=" ", view=None)

        
        
        eliminar_evento_db(interaction.guild.id, self.message_id)

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Solo cerrar la ventana
        await interaction.response.edit_message(content=None, view=None)

#========== comando usar plantilas Select==========
class SeleccionarPlantilla(discord.ui.Select):
    def __init__(self, user_id, guild_id):
        plantillas_actuales = obtener_plantillas_db(guild_id)

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
        plantillas_actuales = obtener_plantillas_db(guild_id)

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
        evento_real["ocultar_fecha_hora"] = False


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

        guardar_evento_db(interaction.guild.id, mensaje_enviado.id, evento_real)

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
        plantillas_actuales = obtener_plantillas_db(guild_id)

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
        plantillas_actuales = obtener_plantillas_db(guild_id)

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
        eliminar_plantilla_db(guild_id, self.nombre)

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

        guild_id = interaction.guild.id if interaction.guild else 0  # Aquí reemplazamos por guild real más abajo
        # 🔹 Obtenemos guild real del interaction
        if hasattr(interaction, "guild") and interaction.guild:
            guild_id = interaction.guild.id if interaction.guild else 0
        else:
            guild_id = 0  # fallback

        # Crear espacio si no existe
        plantillas_actuales = obtener_plantillas_db(guild_id)

        if len(plantillas_actuales) >= 40:
            await interaction.response.send_message(
                "❌ Solo puedes guardar un máximo de 40 plantillas por servidor.",
                ephemeral=True
            )
            return

        # Guardar plantilla
        guardar_plantilla_db(
            guild_id,
            self.titulo,
            {
                "guild_id": guild_id,
                "nombre": self.titulo,
                "fecha": "Pendiente",
                "hora": "Pendiente",
                "lugar": "Pendiente",
                "descripcion": self.descripcion,
                "roles": self.roles,
                "rol": self.rol.id if self.rol else None,
                "imagen": self.imagen
            }
        )
        

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
            discord.SelectOption(label="Ocultar fecha y hora", description="Oculta fecha, hora y relojes de países"),
        ]
        super().__init__(placeholder="Selecciona un campo para editar...", min_values=1, max_values=1, options=opciones)
        self.user_id = user_id
        self.mensaje_id = mensaje_id

    async def callback(self, interaction: discord.Interaction):

        campo = self.values[0]

        evento = eventos.get(self.mensaje_id)

        if not evento:
            await interaction.response.send_message(
                "❌ Evento no encontrado.",
                ephemeral=True
            )
            return

        # 🔥 OCULTAR FECHA Y HORA
        if campo == "Ocultar fecha y hora":

            if evento.get("ocultar_fecha_hora"):
                await interaction.response.send_message(
                    "⚠️ Este evento ya tiene la fecha y hora ocultas.",
                    ephemeral=True
                )
                return

            await interaction.response.send_message(
                "🚨 ESTO ES PERMANENTE 🚨\n\n"
                "Se ocultará:\n"
                "• Fecha\n"
                "• Hora\n"
                "• Relojes de países\n\n"
                "❌ Esta acción no se puede deshacer\n\n"
                "¿Confirmas?",
                view=ConfirmarOcultarFechaHora(self.user_id, self.mensaje_id),
                ephemeral=True
            )
            return

        # 🔥 AQUÍ SIGUEN LAS DEMÁS OPCIONES DEL MENÚ

        if campo == "Fecha":
            await interaction.response.send_modal(EditarCampoModal(self.user_id, self.mensaje_id, "Fecha"))
            return

        if campo == "Hora":
            await interaction.response.send_modal(EditarCampoModal(self.user_id, self.mensaje_id, "Hora"))
            return

        if campo == "Lugar":
            await interaction.response.send_modal(EditarCampoModal(self.user_id, self.mensaje_id, "Lugar"))
            return

        if campo == "Descripción":
            await interaction.response.send_modal(EditarCampoModal(self.user_id, self.mensaje_id, "Descripción"))
            return

        if campo == "Título":
            await interaction.response.send_modal(EditarCampoModal(self.user_id, self.mensaje_id, "Título"))
            return
        # 🔥 fallback por si no coincide nada
        await interaction.response.send_message(
            "❌ Opción no reconocida.",
            ephemeral=True
        )
class ConfirmarOcultarFechaHora(discord.ui.View):
    def __init__(self, user_id, message_id):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.message_id = message_id

    @discord.ui.button(label="Sí, ocultar", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):

        evento = eventos.get(self.message_id)
        if not evento:
            await interaction.response.send_message("❌ Evento no encontrado.", ephemeral=True)
            return

        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Solo el creador puede confirmar.", ephemeral=True)
            return

        # 🔥 ACTIVAR OCULTAR
        evento["ocultar_fecha_hora"] = True

        # 🔥 SI TENÍA FECHA/HORA → PASAR A PENDIENTE
        if evento.get("fecha") != "Pendiente" or evento.get("hora") != "Pendiente":

            evento["fecha"] = "Pendiente"
            evento["hora"] = "Pendiente"

            # 🔥 RESETEAR FLAGS DE TIEMPO
            evento.pop("ultimo_minuto", None)
            evento["recordatorio_enviado"] = False
            evento["dm_enviado"] = False

            # 🔥 OPCIONAL PERO RECOMENDADO: resetear contador de 24h
            evento["created_at"] = datetime.now(timezone.utc)

        canal = interaction.channel
        mensaje = await canal.fetch_message(self.message_id)

        await mensaje.edit(embed=construir_embed(evento))

        guardar_evento_db(interaction.guild.id, self.message_id, evento)

        await interaction.response.edit_message(
            content="🚫 Fecha y hora ocultadas.",
            view=None
        )
    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="❌ Cancelado.",
            view=None
        )
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
            "Fecha": "En UTC ejem: 03-03-2026",
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
            try:
                datetime.strptime(nuevo_valor, "%d-%m-%Y")
                evento["fecha"] = nuevo_valor

                evento.pop("ultimo_minuto", None)
                evento["recordatorio_enviado"] = False
                evento["dm_enviado"] = False

            except ValueError:
                await interaction.response.send_message(
                    "❌ Formato de fecha inválido. Usa DD-MM-YYYY.",
                    ephemeral=True
                )
                return
                
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
        guardar_evento_db(interaction.guild.id, self.mensaje_id, evento)
        await interaction.response.send_message(f"✅ {self.campo} actualizado correctamente.", ephemeral=True)


class SolicitudAccesoView(discord.ui.View):
    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    @discord.ui.button(label="✅ Aprobar", style=discord.ButtonStyle.success)
    async def aprobar(self, interaction, button):

        if interaction.user.id != ADMIN_ID:
            return await interaction.response.send_message("❌ No autorizado", ephemeral=True)

        guild = self.guild

        # 👥 admins completos (nombre + id)
        admins = [
            {
                "name": str(m),
                "id": m.id
            }
            for m in guild.members
            if m.guild_permissions.administrator
        ][:10]

        # 🙋 usuario que solicitó acceso
        # (lo tomamos del interaction message embed si quieres tracking real)
        solicitante = interaction.user

        coleccion_servidores.update_one(
            {"guild_id": guild.id},
            {"$set": {
                # 🏷 servidor
                "guild_id": guild.id,
                "name": guild.name,
                "icon": str(guild.icon.url) if guild.icon else None,

                # 👑 owner
                "owner": {
                    "name": str(guild.owner),
                    "id": guild.owner.id if guild.owner else None
                },

                # 👥 admins
                "admins": admins,

                # 🙋 solicitante
                "solicitante": {
                    "name": str(solicitante),
                    "id": solicitante.id
                },

                # ⏱ metadata
                "approved_at": datetime.now(timezone.utc)
            }},
            upsert=True
        )

        try:
            await guild.owner.send("✅ Servidor aprobado.")
        except:
            pass

        await interaction.response.send_message("✅ Guardado en MongoDB correctamente", ephemeral=True)

    @discord.ui.button(label="❌ Rechazar", style=discord.ButtonStyle.danger)
    async def rechazar(self, interaction, button):

        if interaction.user.id != ADMIN_ID:
            return await interaction.response.send_message("❌ No autorizado", ephemeral=True)

        try:
            await self.guild.owner.send("❌ Rechazado.")
        except:
            pass

        await interaction.response.send_message("❌ Hecho", ephemeral=True)
## ## ## ## ## ## #
#  Comando /crear_plantilla
# ## ## ## ## ## #
@bot.tree.command(name="crear_plantilla", description="Crea una plantilla de evento sin modal")
@requiere_acceso()
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
        "rol": rol.id if rol else None,
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
@requiere_acceso()
@app_commands.describe(
    nombre="Nombre del evento",
    fecha="Formato DD-MM-YYYY en UTC (ej: 12-03-2026)",
    hora="Formato HH:MM en UTC (ej: 21:30)",
    lugar="Sitio de reunion",
    descripcion="Separa los puntos con /",
    roles="EMOJI-NOMBRE-CUPO,separados por coma ejem:🛡️-Tanke-1,⛑️-Healer-2",
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

    # Validar hora y fecha antes de procesar roles para ahorrar recursos
    try:
        datetime.strptime(hora, "%H:%M")
    except ValueError:
        await interaction.response.send_message(
            "❌ Formato de hora inválido. Debe ser HH:MM en UTC.", ephemeral=True
        )
        return
    try:
        datetime.strptime(fecha, "%d-%m-%Y")
    except ValueError:
        await interaction.response.send_message(
            "❌ Formato de fecha inválido. Usa DD-MM-YYYY.",
            ephemeral=True
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
        "guild_id": interaction.guild.id,
        "nombre": nombre,
        "fecha": fecha,
        "hora": hora,
        "lugar": lugar,
        "descripcion": descripcion,
        "roles": roles_parseados,
        "rol": rol.id if rol else None,
        "canal": interaction.channel_id,
        "creador": interaction.user.id,
        "cerrado": False,
        "imagen": imagen,
        "banca": [],
        "recordatorio_enviado": False,
        "dm_enviado": False,
        "terminado": False,
        "created_at": datetime.now(timezone.utc),  # 🔥 PEGA AQUÍ
        "ocultar_fecha_hora": False,
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

    guardar_evento_db(int(interaction.guild.id), int(mensaje.id), evento_data)

    await mensaje.edit(view=EventoView(mensaje.id))
    


@bot.tree.command(name="solicitar_acceso")
async def solicitar_acceso(interaction: discord.Interaction):

    if not interaction.guild:
        return await interaction.response.send_message(
            "❌ Solo en servidores.",
            ephemeral=True
        )

    guild = interaction.guild

    admins = [
        m.name for m in guild.members
        if m.guild_permissions.administrator
    ]

    embed = discord.Embed(
        title=f"🏷 {guild.name}",
        description="Solicitud de acceso al bot",
        color=discord.Color.gold()
    )

    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

    embed.add_field(name="👑 Dueño", value=str(guild.owner), inline=False)
    embed.add_field(name="🆔 ID", value=str(guild.id), inline=False)
    embed.add_field(name="👥 Admins", value="\n".join(admins[:10]) or "Ninguno", inline=False)
    embed.add_field(name="🙋 Solicitante", value=str(interaction.user), inline=False)

    view = SolicitudAccesoView(guild)

    owner = await bot.fetch_user(ADMIN_ID)
    await owner.send(embed=embed, view=view)

    await interaction.response.send_message(
        "📩 Solicitud enviada.",
        ephemeral=True
    )

# =============================
# COMANDO ELIMINAR PLANTILLA
# =============================
@bot.tree.command(name="eliminar_plantilla", description="Eliminar una plantilla guardada")
@requiere_acceso()
async def eliminar_plantilla(interaction: discord.Interaction):
    guild_id = interaction.guild.id if interaction.guild else 0
    plantillas_actuales = obtener_plantillas_db(guild_id)

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

@bot.tree.command(name="agregar_servidor", description="Agregar un servidor manualmente a la whitelist")
async def agregar_servidor(interaction: discord.Interaction, guild_id: str):
    
    # 🔒 Solo tú (admin del bot)
    if interaction.user.id != ADMIN_ID:
        await interaction.response.send_message("❌ No autorizado.", ephemeral=True)
        return
    # DM OK
    if interaction.guild is None:
        print("Ejecutado en DM")

    try:
        guild_id = int(guild_id)
    except:
        await interaction.response.send_message("❌ ID inválido.", ephemeral=True)
        return

    guild = bot.get_guild(guild_id)

    # 🔥 si el bot no está en ese servidor
    if not guild:
        await interaction.response.send_message("❌ No estoy en ese servidor.", ephemeral=True)
        return

    coleccion_servidores.update_one(
        {"guild_id": guild.id},
        {"$set": {
            "guild_id": guild.id,
            "name": guild.name,
            "owner": guild.owner.id if guild.owner else None,
            "icon": str(guild.icon.url) if guild.icon else None,
            "admins": [m.id for m in guild.members if m.guild_permissions.administrator],
            "approved_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )

    await interaction.response.send_message(
        f"✅ Servidor **{guild.name}** agregado y autorizado.",
        ephemeral=True
    )

@bot.tree.command(name="remover_servidor", description="Eliminar un servidor de la whitelist del bot")
async def remover_servidor(interaction: discord.Interaction, guild_id: str):

    # 🔒 Solo tú (admin del bot)
    if interaction.user.id != ADMIN_ID:
        await interaction.response.send_message("❌ No autorizado.", ephemeral=True)
        return
    # DM OK
    if interaction.guild is None:
        print("Ejecutado en DM")

    try:
        guild_id = int(guild_id)
    except:
        await interaction.response.send_message("❌ ID inválido.", ephemeral=True)
        return

    result = coleccion_servidores.delete_one({"guild_id": guild_id})

    if result.deleted_count == 0:
        await interaction.response.send_message("⚠️ Ese servidor no estaba registrado.", ephemeral=True)
        return

    await interaction.response.send_message(
        f"🗑 Servidor `{guild_id}` eliminado correctamente.",
        ephemeral=True
    )

@bot.tree.command(name="ver_servidores", description="Muestra todos los servidores aprobados")
async def ver_servidores(interaction: discord.Interaction):

    # 🔐 Solo tú
    if interaction.user.id != ADMIN_ID:
        return await interaction.response.send_message(
            "❌ No autorizado.",
            ephemeral=True
        )
    # DM OK
    if interaction.guild is None:
        print("Ejecutado en DM")


    docs = list(coleccion_servidores.find())

    if not docs:
        return await interaction.response.send_message("❌ No hay servidores registrados.")

    # 📦 dividir en bloques de 10
    chunks = [docs[i:i + 10] for i in range(0, len(docs), 10)]
    total = len(chunks)

    await interaction.response.defer()

    for idx, chunk in enumerate(chunks, start=1):

        embeds = []

        for s in chunk:

            guild_name = s.get("name", "Sin nombre")
            guild_id = s.get("guild_id", "N/A")
            icon = s.get("icon")

            owner = s.get("owner", {})
            owner_name = owner.get("name", "Desconocido")
            owner_id = owner.get("id", "N/A")

            solicitante = s.get("solicitante", {})
            solicitante_name = solicitante.get("name", "Desconocido")
            solicitante_id = solicitante.get("id", "N/A")

            admins = s.get("admins", [])

            embed = discord.Embed(
                title=f"🏷 {guild_name}",
                color=discord.Color.green()
            )

            # 🆔 ID del servidor
            embed.add_field(
                name="🆔 ID",
                value=str(guild_id),
                inline=False
            )

            # 👑 Owner completo
            embed.add_field(
                name="👑 Dueño",
                value=f"{owner_name}\n`{owner_id}`",
                inline=True
            )

            # 🙋 Solicitante completo
            embed.add_field(
                name="🙋 Solicitante",
                value=f"{solicitante_name}\n`{solicitante_id}`",
                inline=True
            )

            # 👥 Admins (mencionables)
            admins_txt = "\n".join(
                f"{a.get('name','?')} (`{a.get('id','?')}`)"
                for a in admins[:10]
            ) or "Ninguno"

            embed.add_field(
                name="👥 Admins",
                value=admins_txt,
                inline=False
            )

            # 🖼 icono
            if icon:
                embed.set_thumbnail(url=icon)

            embeds.append(embed)

        await interaction.followup.send(
            content=f"📄 Servidores aprobados ({idx}/{total})",
            embeds=embeds
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
    for rol in evento.get("roles", {}).values():
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
    for rol in evento.get("roles", {}).values():
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

        try:
            mensaje = canal.get_partial_message(message_id)
        except:
            continue


        dt_evento = obtener_datetime_evento(evento)
        
        # 🔥 SI NO HAY FECHA VÁLIDA, SALTAR
        if dt_evento is None:
            continue
        # 🔥 EVENTOS INCOMPLETOS (Pendiente: fecha o hora)
# 🔥 EVENTOS INCOMPLETOS (Pendiente: fecha o hora)
        if evento.get("fecha") == "Pendiente" or evento.get("hora") == "Pendiente":

            creado = evento.get("created_at")

            if isinstance(creado, str):
                creado = datetime.fromisoformat(creado)

            if creado and (ahora - creado).total_seconds() >= 86400:  # 24 horas

                evento["cerrado"] = True

                try:
                    await mensaje.edit(embed=construir_embed(evento), view=None)
                except:
                    pass

                eliminar_evento_db(evento["guild_id"], message_id)
                eventos.pop(message_id, None)

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
            evento["cerrado"] = True

            try:
                await mensaje.edit(view=None)
            except:
                pass

            # 🔥 BORRAR DE MONGODB
            eliminar_evento_db(evento["guild_id"], message_id)

            # 🔥 BORRAR DE MEMORIA
            eventos.pop(message_id, None)

            continue

# =============================
# COMANDO /HELP VISUAL FORMATEADO
# =============================
@bot.tree.command(name="help", description="Muestra las instrucciones de uso del bot de forma visual y clara")
@requiere_acceso()
async def help_command(interaction: discord.Interaction):

    embed = discord.Embed(
        title="📚 Manual del Bot de Eventos",
        description="Bienvenido 👋 aquí tienes cómo usar correctamente el bot.\n\n",
        color=discord.Color.teal()
    )

    # -------------------- CREAR EVENTO --------------------
    embed.add_field(
        name="📝 Crear evento",
        value=(
            "Usa `/crear_evento`\n\n"
            "• nombre\n"
            "• fecha → DD-MM-YYYY\n"
            "• hora → HH:MM (UTC)\n"
            "• lugar\n"
            "• descripcion (usa `/` para separar)\n"
            "• roles\n"
            "• rol (opcional)\n"
            "• imagen (opcional)"
        ),
        inline=False
    )

    # -------------------- ROLES --------------------
    embed.add_field(
        name="🎯 Formato de roles",
        value=(
            "• Máximo 20 roles\n"
            "• Separados por coma `,`\n"
            "• Formato: `EMOJI-NOMBRE-CUPO`\n\n"
            "Ejemplo:\n"
            "`🛡️-Tanque-1, 💉-Healer-2, ⚔️-DPS-5`\n"
            "También sin emoji:\n"
            "`Tanque-1, Healer-2`"
        ),
        inline=False
    )

    # -------------------- BOTONES --------------------
    embed.add_field(
        name="🔘 Botones",
        value=(
            "• Únete presionando un rol\n"
            "• Si está lleno → vas a banca\n"
            "• ❌ Quitar → salir del evento\n"
            "• ⚙️ Solo el creador puede editar"
        ),
        inline=False
    )

    # -------------------- CONFIG --------------------
    embed.add_field(
        name="⚙️ Edición",
        value=(
            "Puedes editar:\n"
            "• Título\n"
            "• Fecha\n"
            "• Hora\n"
            "• Lugar\n"
            "• Descripción"
        ),
        inline=False
    )

    # -------------------- SISTEMA AUTO --------------------
    embed.add_field(
        name="🧠 Automatización",
        value=(
            "• Cuenta regresiva automática\n"
            "• Aviso 20 min antes\n"
            "• DM 10 min antes\n"
            "• Banca automática\n"
            "• Cierre automático"
        ),
        inline=False
    )

    # -------------------- PLANTILLAS --------------------
    embed.add_field(
        name="📋 Plantillas",
        value=(
            "`/crear_plantilla`\n"
            "`/usar_plantillas`\n"
            "`/eliminar_plantilla`\n\n"
            "Máximo 40 por servidor"
        ),
        inline=False
    )

    # -------------------- CONSEJOS --------------------
    embed.add_field(
        name="💡 Consejos",
        value=(
            "• Usa UTC siempre\n"
            "• Usa `/` para separar texto\n"
            "• Usa emojis claros\n"
            "• Revisa cupos antes de entrar"
        ),
        inline=False
    )

    embed.set_footer(text="👀 Solo tú puedes ver este mensaje")

    await interaction.response.send_message(embed=embed, ephemeral=True)
# =============================
# COMANDO /usar_plantillas
# =============================
@bot.tree.command(name="usar_plantillas", description="Selecciona una plantilla de evento para usarla")
@requiere_acceso()
async def usar_plantillas(interaction: discord.Interaction):
    # Obtenemos el guild ID
    guild_id = interaction.guild.id if interaction.guild else 0

    

    # Verificar si hay plantillas para este servidor
    plantillas_actuales = obtener_plantillas_db(guild_id)
    if not plantillas_actuales:
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
    eventos.update(cargar_eventos_db())
    
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
    if not revisar_eventos.is_running():
        revisar_eventos.start()    

@bot.event
async def on_guild_join(guild):

    canal = discord.utils.get(guild.text_channels)

    if canal:
        await canal.send(
            "👋 Bienvenido a xVENOMx Bot\n\n"
            "🔒 Usa /solicitar_acceso para activar el bot."
        )

    try:
        await guild.owner.send(
            "🔒 Tu servidor requiere aprobación para usar el bot."
        )
    except:
        pass

@bot.event
async def on_error(event, *args, **kwargs):
    print(f"❌ Error en evento {event}:", args, kwargs)


@bot.event
async def on_message_delete(message):

    if message.id in eventos:
        eventos.pop(message.id, None)

        

        if message.guild:
            eliminar_evento_db(message.guild.id, message.id)

        print(f"[DELETE] Intentando eliminar evento {message.id}")



TOKEN = os.environ.get("TOKEN")

if not TOKEN:
    raise Exception("❌ Falta la variable de entorno TOKEN")

import atexit

def cerrar_mongo():
    client.close()
    print("🔌 Conexión a Mongo cerrada")

atexit.register(cerrar_mongo)

bot.run(TOKEN)

