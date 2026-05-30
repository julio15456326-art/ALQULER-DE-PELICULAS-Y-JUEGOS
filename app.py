from flask import Flask, render_template, request, url_for, session, redirect, flash
from flask_sqlalchemy import SQLAlchemy
import os
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__)
app.secret_key = 'mi_llave_secreta_super_segura'

# 1. CONFIGURACIÓN AUTOMÁTICA DE LA NUEVA BASE DE DATOS
db_path = os.path.join(os.path.dirname(__file__), 'alquileres.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- CONTROL DE ROLES ---
NIVELES_ACCESO = {'cliente': 1, 'gestor': 5, 'admin': 10}

def requiere_nivel(nivel_minimo):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            rol_usuario = session.get('usuario_rol', 'cliente')
            nivel_usuario = NIVELES_ACCESO.get(rol_usuario, 1)
            if nivel_usuario < nivel_minimo:
                flash("No tenés permisos suficientes para entrar acá.", "danger")
                return redirect(url_for('inicio'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# =========================================================================
# 2. MODELOS DE BASE DE DATOS (SÚPER REDUCIDOS)
# =========================================================================

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    rol = db.Column(db.String(20), default='cliente')

class Pelicula(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(100), nullable=False)
    precio = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=1)
    imagen = db.Column(db.String(100), default='default.jpg')

class Juego(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(100), nullable=False)
    precio = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=1)
    imagen = db.Column(db.String(100), default='default.jpg')

# Creación automática del archivo .db y sus tablas
with app.app_context():
    db.create_all()

# =========================================================================
# 3. RUTAS DE LA PÁGINA
# =========================================================================

@app.route('/')
def inicio():
    # Traemos todo para mostrarlo en la pantalla principal
    lista_peliculas = Pelicula.query.all()
    lista_juegos = Juego.query.all()
    return render_template('inicio.html', peliculas=lista_peliculas, juegos=lista_juegos)

# --- LOGIN / REGISTRO / LOGOUT ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email_f = request.form.get('email')
        pass_f = request.form.get('password')
        user = Usuario.query.filter_by(email=email_f, password=pass_f).first()
        if user:
            session['usuario_id'] = user.id
            session['usuario_nombre'] = user.nombre
            session['usuario_rol'] = user.rol
            flash(f"¡Hola de nuevo, {user.nombre}!", "success") 
            return redirect(url_for('inicio'))
        flash("Email o contraseña incorrectos", "danger")
    return render_template('login.html')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if Usuario.query.filter_by(email=email).first():
            flash("Ese email ya está registrado.", "warning")
            return redirect(url_for('registro'))
            
        nuevo = Usuario(nombre=nombre, email=email, password=password)
        db.session.add(nuevo)
        db.session.commit()
        flash("¡Usuario creado con éxito! Ya podés iniciar sesión.", "success")
        return redirect(url_for('login'))
    return render_template('registro.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('inicio'))

# =========================================================================
# 4. PANEL DE CONTROL (SOLO ADMIN) - PARA CARGAR STOCK
# =========================================================================

app.config['UPLOAD_FOLDER'] = os.path.join('static', 'img')

@app.route('/admin/dashboard', methods=['GET', 'POST']) # Habilitamos GET y POST
@requiere_nivel(10) # Nivel admin
def dashboard():
    # SI EL ADMIN ENVIÓ EL FORMULARIO DE CARGA (POST)
    if request.method == 'POST':
        tipo = request.form.get('tipo') # Recibe 'pelicula' o 'juego'
        titulo = request.form.get('titulo')
        precio = float(request.form.get('precio'))
        stock = int(request.form.get('stock', 1))
        
        # Procesamos la imagen de texto que viene del campo input text
        nombre_imagen = request.form.get('imagen')
        if not nombre_imagen or nombre_imagen.strip() == '':
            nombre_imagen = "default.jpg"

        # Guardamos en la tabla correspondiente según el select del HTML
        if tipo == 'pelicula':
            nuevo = Pelicula(titulo=titulo, precio=precio, stock=stock, imagen=nombre_imagen)
        else:
            nuevo = Juego(titulo=titulo, precio=precio, stock=stock, imagen=nombre_imagen)
            
        db.session.add(nuevo)
        db.session.commit()
        flash(f"¡{tipo.capitalize()} '{titulo}' agregada al stock con éxito!", "success")
        return redirect(url_for('dashboard')) # Recarga el panel limpio mostrando los nuevos totales

    # SI EL ADMIN SOLO ENTRÓ A MIRAR LA PÁGINA (GET)
    total_pelis = Pelicula.query.count()
    total_juegos = Juego.query.count()
    total_users = Usuario.query.count()
    return render_template('dashboard.html', u_total=total_users, p_total=total_pelis, j_total=total_juegos)


# Dejamos esta ruta de auxilio por si la necesitas, apuntando a tu dashboard
@app.route('/admin/nuevo_item', methods=['GET', 'POST'])
@requiere_nivel(10)
def nuevo_item():
    return redirect(url_for('dashboard'))

# =========================================================================
# CREACIÓN AUTOMÁTICA DE TABLAS Y ADMIN INICIAL AL ARRANCAR
# =========================================================================
with app.app_context():
    db.create_all()  # Crea el archivo alquileres.db y las tablas automáticamente

    # Forzamos la creación del administrador apenas arranca el servidor
    existe_admin = Usuario.query.filter_by(email="admin@alquiler.com").first()
    if not existe_admin:
        admin = Usuario(
            nombre="Admin", 
            email="admin@alquiler.com", 
            password="123", 
            rol="admin"  # Rango máximo para que no entre como cliente común
        )
        db.session.add(admin)
        db.session.commit()
        print("¡Base de datos lista y Administrador Inicial generado con éxito!")

if __name__ == '__main__':
    app.run(debug=True)