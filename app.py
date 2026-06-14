from flask import Flask, render_template, request, url_for, session, redirect, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Mail, Message
import os

app = Flask(__name__)
app.secret_key = 'mi_llave_secreta_super_segura'
ts = URLSafeTimedSerializer("CLAVE_SECRETA_PARA_EL_TOKEN")

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'ruben650160@gmail.com'
app.config['MAIL_PASSWORD'] = 'gwwuxyrjezjiwodr'
app.config['MAIL_DEFAULT_SENDER'] = 'ruben650160@gmail.com'

mail = Mail(app)

# =========================================================================
# CONFIGURACIÓN DE LA BASE DE DATOS
# =========================================================================
db_path = os.path.join(os.path.dirname(__file__), 'alquileres.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

app.config['UPLOAD_FOLDER'] = os.path.join('static', 'img')

# --- CONTROL DE ROLES (Agregado del código de tu amigo) ---
NIVELES_ACCESO = {'cliente': 1, 'empleado': 5, 'admin': 10}

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

# Tabla intermedia para la lista de espera
lista_espera = db.Table('lista_espera',
    db.Column('usuario_id', db.Integer, db.ForeignKey('usuarios.id'), primary_key=True),
    db.Column('producto_id', db.Integer, db.ForeignKey('productos_alquiler.id'), primary_key=True)
)

# =========================================================================
# MODELOS DE CLASES (POO - Versión Avanzada Tuya)
# =========================================================================

class Usuario(db.Model):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    rol = db.Column(db.String(20), default='cliente') 
    bloqueado = db.Column(db.Boolean, default=False)
    activo = db.Column(db.Boolean, default=False)

    alquileres = db.relationship('ProductoAlquiler', backref='usuario', lazy=True)
    reservas_solicitadas = db.relationship('ProductoAlquiler', secondary=lista_espera, backref=db.backref('en_espera', lazy=True))

    def guardar(self):
        db.session.add(self)
        db.session.commit()

    def es_staff(self):
        return self.rol in ('empleado', 'admin')

    def es_admin(self):
        return self.rol == 'admin'

    @classmethod
    def buscar_por_id(cls, usuario_id):
        return cls.query.get(usuario_id)

    @classmethod
    def autenticar(cls, email_f, pass_f):
        return cls.query.filter_by(email=email_f, password=pass_f).first()


class ProductoAlquiler(db.Model):
    __tablename__ = 'productos_alquiler'
    
    id = db.Column(db.Integer, primary_key=True)                
    titulo = db.Column(db.String(100), nullable=False)            
    genero = db.Column(db.String(50), nullable=True)              
    alquilado = db.Column(db.Boolean, default=False)              
    precio_alquiler = db.Column(db.Float, nullable=False)         
    stock = db.Column(db.Integer, default=1)
    imagen = db.Column(db.String(100), default='default.jpg')
    contador_alquileres = db.Column(db.Integer, default=0) 
    tipo_producto = db.Column(db.String(50)) 

    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    fecha_alquiler = db.Column(db.DateTime, nullable=True)
    fecha_vencimiento = db.Column(db.DateTime, nullable=True)
    estado = db.Column(db.String(30), default='disponible')

    # Propiedad dinámica agregada para compatibilidad con los HTML de tu amigo que buscan .precio
    @property
    def precio(self):
        return self.precio_alquiler

    __mapper_args__ = {
        'polymorphic_on': tipo_producto,
        'polymorphic_identity': 'producto_generico'
    }

    def obtener_especifico(self):
        return "No aplica"

    def esta_vencido(self):
        if self.fecha_vencimiento and datetime.now() > self.fecha_vencimiento:
            return True
        return False

    def alquilar_a(self, usuario):
        if usuario.bloqueado:
            return "usuario_bloqueado"

        if self.stock > 0:
            self.stock -= 1
            self.contador_alquileres += 1 
            self.usuario_id = usuario.id 
            self.fecha_alquiler = datetime.now()
            self.fecha_vencimiento = datetime.now() + timedelta(days=7)
            
            if self.stock == 0:
                self.alquilado = True                                                                             
            db.session.commit()
            return "alquilado"
        
        elif usuario not in self.en_espera:
            self.en_espera.append(usuario)
            db.session.commit()
            return "reservado"
        
        return "ya_esperando"

    def devolver_producto(self):
        if len(self.en_espera) > 0:
            proximo_usuario = self.en_espera.pop(0)
            self.usuario_id = proximo_usuario.id
            self.fecha_alquiler = datetime.now()
            self.fecha_vencimiento = datetime.now() + timedelta(days=7)
            self.contador_alquileres += 1
            db.session.commit()
            return proximo_usuario
        else:
            self.stock += 1
            self.alquilado = False                                                                                                                                    
            self.usuario_id = None 
            self.fecha_alquiler = None
            self.fecha_vencimiento = None
            db.session.commit()
            return None

    def solicitar_alquiler(self, usuario):
        if usuario.bloqueado:
            return "usuario_bloqueado"
        if self.stock > 0:
            self.stock -= 1
            self.usuario_id = usuario.id
            self.estado = 'pendiente'
            if self.stock == 0:
                self.alquilado = True
            db.session.commit()
            return "pendiente"
        elif usuario not in self.en_espera:
            self.en_espera.append(usuario)
            db.session.commit()
            return "reservado"
        return "ya_esperando"

    def confirmar_alquiler(self):
        if self.estado != 'pendiente':
            return False
        self.estado = 'activo'
        self.fecha_alquiler = datetime.now()
        self.fecha_vencimiento = datetime.now() + timedelta(days=7)
        self.contador_alquileres += 1
        db.session.commit()
        return True

    def rechazar_alquiler(self):
        if self.estado != 'pendiente':
            return False
        self.stock += 1
        self.alquilado = False
        self.usuario_id = None
        self.estado = 'disponible'
        db.session.commit()
        return True

    def solicitar_devolucion(self, usuario):
        if self.usuario_id != usuario.id or self.estado != 'activo':
            return False
        self.estado = 'dev_pendiente'
        db.session.commit()
        return True

    def confirmar_devolucion(self):
        if self.estado != 'dev_pendiente':
            return None
        if len(self.en_espera) > 0:
            proximo_usuario = self.en_espera.pop(0)
            self.usuario_id = proximo_usuario.id
            self.estado = 'pendiente'   
            db.session.commit()
            return proximo_usuario
        self.stock += 1
        self.alquilado = False
        self.usuario_id = None
        self.fecha_alquiler = None
        self.fecha_vencimiento = None
        self.estado = 'disponible'
        db.session.commit()
        return None


class Pelicula(ProductoAlquiler):
    formato = db.Column(db.String(50), nullable=True)             
    __mapper_args__ = {'polymorphic_identity': 'pelicula'}

    def obtener_especifico(self):
        return f"Formato: {self.formato}" if self.formato else "Sin formato"


class Juego(ProductoAlquiler):
    plataforma = db.Column(db.String(50), nullable=True)          
    __mapper_args__ = {'polymorphic_identity': 'juego'}

    def obtener_especifico(self):
        return f"Plataforma: {self.plataforma}" if self.plataforma else "Sin plataforma"

# =========================================================================
# CONTROLADOR GESTOR DE INVENTARIO
# =========================================================================
class GestorInventario:
    @staticmethod
    def agregar_producto(producto):
        db.session.add(producto)
        db.session.commit()

    @staticmethod
    def eliminar_producto(id_prod):
        prod = ProductoAlquiler.query.get(id_prod)
        if prod:
            prod.en_espera.clear()
            db.session.delete(prod)
            db.session.commit()
            return True
        return False

    @staticmethod
    def buscar_producto_por_id(id_prod):
        return ProductoAlquiler.query.get(id_prod)

    @staticmethod
    def listar_para_catalogo(clase_modelo, limite=None):
        query = clase_modelo.query.order_by(clase_modelo.contador_alquileres.desc(), clase_modelo.id.desc())
        if limite:
            query = query.limit(limite)
        return query.all()
    
    @staticmethod
    def procesar_alquiler(id_prod, usuario):
        producto = ProductoAlquiler.query.get(id_prod)
        if not producto:
            return "no_encontrado"
        return producto.alquilar_a(usuario)

    @staticmethod
    def calcular_ingresos_estimados():
        todos_los_productos = ProductoAlquiler.query.all()
        return sum(p.precio_alquiler * p.contador_alquileres for p in todos_los_productos)

    @staticmethod
    def solicitudes_pendientes():
        return ProductoAlquiler.query.filter_by(estado='pendiente').all()

    @staticmethod
    def devoluciones_pendientes():
        return ProductoAlquiler.query.filter_by(estado='dev_pendiente').all()


# =========================================================================
# RUTAS PÚBLICAS Y DE CLIENTES
# =========================================================================

@app.route('/')
def inicio():
    peliculas = GestorInventario.listar_para_catalogo(Pelicula, limite=4)
    juegos = GestorInventario.listar_para_catalogo(Juego, limite=4)

# 1. Traemos el top 1 de cada uno para comparar
    top_pelicula = peliculas[0] if peliculas else None
    top_juego = juegos[0] if juegos else None
    destacado = None
    if top_pelicula and top_juego:
        if top_pelicula.contador_alquileres >= top_juego.contador_alquileres:
            destacado = top_pelicula
        else:
            destacado = top_juego
    elif top_pelicula:
        destacado = top_pelicula
    elif top_juego:
        destacado = top_juego

    # 3. Pasamos la variable 'destacado' al template
    return render_template('inicio.html', 
                           peliculas=peliculas, 
                           juegos=juegos, 
                           destacado=destacado)

@app.route('/peliculas')
def ver_peliculas():
    peliculas = GestorInventario.listar_para_catalogo(Pelicula)
    return render_template('peliculas.html', peliculas=peliculas)

@app.route('/juegos')
def ver_juegos():
    juegos = GestorInventario.listar_para_catalogo(Juego)
    return render_template('juegos.html', juegos=juegos)

@app.route('/alquilar/<int:prod_id>')
def alquilar_item(prod_id):
    if 'usuario_id' not in session:
        flash("Debes iniciar sesión para alquilar o reservar.", "danger")
        return redirect(url_for('login'))

    usuario_actual = Usuario.buscar_por_id(session['usuario_id'])
    producto = GestorInventario.buscar_producto_por_id(prod_id)

    if not producto:
        flash("Producto no encontrado.", "danger")
        return redirect(request.referrer or url_for('inicio'))

    resultado = producto.solicitar_alquiler(usuario_actual)

    if resultado == "usuario_bloqueado":
        flash("Tu cuenta se encuentra SUSPENDIDA. Comunícate con soporte.", "danger")
    elif resultado == "pendiente":
        flash("¡Solicitud enviada! El local la confirmará a la brevedad.", "info")
    elif resultado == "reservado":
        flash("Sin stock. ¡Te añadimos a la lista de espera!", "info")
    elif resultado == "ya_esperando":
        flash("Ya estás anotado en la lista de espera.", "warning")
        
    return redirect(request.referrer or url_for('inicio'))

@app.route('/devolver/<int:prod_id>')
def devolver_item(prod_id):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    usuario_actual = Usuario.buscar_por_id(session['usuario_id'])
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto and producto.solicitar_devolucion(usuario_actual):
        flash(f"Devolución de '{producto.titulo}' registrada. El local la confirmará cuando reciba el producto.", "info")
    else:
        flash("No se pudo registrar la devolución.", "danger")
    return redirect(url_for('mis_alquileres'))

@app.route('/cancelar-reserva/<int:prod_id>')
def cancelar_reserva(prod_id):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    usuario_actual = Usuario.buscar_por_id(session['usuario_id'])
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto and usuario_actual in producto.en_espera:
        producto.en_espera.remove(usuario_actual)
        db.session.commit()
        flash(f"Cancelaste tu reserva para '{producto.titulo}' correctamente.", "success")
    return redirect(request.referrer or url_for('inicio'))

@app.route('/mis-alquileres')
def mis_alquileres():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    usuario_actual = Usuario.buscar_por_id(session['usuario_id'])
    return render_template('mis_alquileres.html', alquileres=usuario_actual.alquileres, reservas=usuario_actual.reservas_solicitadas)


# =========================================================================
# RUTAS EXCLUSIVAS DE ADMINISTRACIÓN (TÚ SUPER DASHBOARD CON DECORADOR)
# =========================================================================

@app.route('/admin/dashboard', methods=['GET', 'POST'])
@requiere_nivel( 5) # Protegido con el decorador de tu amigo
def dashboard():
    usuario_actual = Usuario.buscar_por_id(session.get('usuario_id'))
    
    if request.method == 'POST':
        tipo_f = request.form.get('tipo') 
        titulo = request.form.get('titulo')
        precio = float(request.form.get('precio'))
        stock = int(request.form.get('stock', 1))
        genero = request.form.get('genero')
        especifico_f = request.form.get('especifico') 
        
        # Compatibilidad: Soporta carga por archivo o por campo de texto simple de tu amigo
        file_imagen = request.files.get('imagen')
        if file_imagen and file_imagen.filename != '':
            nombre_imagen = secure_filename(file_imagen.filename)
            file_imagen.save(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], nombre_imagen))
        else:
            nombre_imagen = request.form.get('imagen') or "default.jpg"

        if tipo_f == 'pelicula':
            nuevo = Pelicula(titulo=titulo, precio_alquiler=precio, stock=stock, genero=genero, imagen=nombre_imagen, formato=especifico_f)
        else:
            nuevo = Juego(titulo=titulo, precio_alquiler=precio, stock=stock, genero=genero, imagen=nombre_imagen, plataforma=especifico_f)

        GestorInventario.agregar_producto(nuevo)
        flash(f"¡{tipo_f.capitalize()} cargada correctamente!", "success")
        return redirect(url_for('dashboard'))

    usuarios_registrados = Usuario.query.filter(Usuario.rol == 'cliente').all()
    todos_los_productos = ProductoAlquiler.query.all()
    alquileres_activos = ProductoAlquiler.query.filter(ProductoAlquiler.estado == 'activo').all()

    return render_template(
        'dashboard.html', 
        u_total=Usuario.query.count(), 
        p_total=Pelicula.query.count(), 
        j_total=Juego.query.count(), 
        ingresos=GestorInventario.calcular_ingresos_estimados(),
        usuarios=usuarios_registrados,
        productos=todos_los_productos,
        alquileres=alquileres_activos,
        solicitudes=GestorInventario.solicitudes_pendientes(),
        devoluciones=GestorInventario.devoluciones_pendientes(),
        es_admin=usuario_actual.es_admin()
    )

@app.route('/admin/nuevo_item', methods=['GET', 'POST'])
@requiere_nivel(10)
def nuevo_item():
    return redirect(url_for('dashboard'))

@app.route('/admin/usuario/bloquear/<int:user_id>')
@requiere_nivel(10)
def administrar_bloqueo(user_id):
    user = Usuario.buscar_por_id(user_id)
    if user:
        user.bloqueado = not user.bloqueado 
        db.session.commit()
        estado = "SANCIONADO" if user.bloqueado else "ACTIVADO"
        flash(f"Usuario {user.nombre} ha sido {estado}.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/usuario/eliminar/<int:user_id>')
@requiere_nivel(10)
def administrar_eliminar_usuario(user_id):
    user = Usuario.buscar_por_id(user_id)
    if user:
        for p in user.alquileres:
            p.devolver_producto()
        db.session.delete(user)
        db.session.commit()
        flash("Usuario eliminado del sistema correctamente.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/usuario/editar/<int:user_id>', methods=['GET', 'POST'])
@requiere_nivel(10)
def administrar_editar_usuario(user_id):
    user = Usuario.buscar_por_id(user_id)
    if not user:
        flash("Usuario no encontrado.", "danger")
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        nuevo_email = request.form.get('email')
        existente = Usuario.query.filter_by(email=nuevo_email).first()
        if existente and existente.id != user_id:
            flash("Ese correo ya está en uso por otro usuario.", "danger")
            return redirect(url_for('administrar_editar_usuario', user_id=user_id))
        user.nombre = request.form.get('nombre')
        user.email  = nuevo_email
        nueva_pass  = request.form.get('password')
        if nueva_pass:
            user.password = nueva_pass
        db.session.commit()
        flash(f"Usuario '{user.nombre}' updated correctamente.", "success")
        return redirect(url_for('dashboard'))
    return render_template('editar_usuario.html', usuario=user)

@app.route('/admin/usuario/crear', methods=['GET', 'POST'])
@requiere_nivel(10)
def administrar_crear_usuario():
    if request.method == 'POST':
        nombre   = request.form.get('nombre')
        email    = request.form.get('email')
        password = request.form.get('password')
        rol      = request.form.get('rol', 'empleado')
        if Usuario.query.filter_by(email=email).first():
            flash("El correo ya está registrado.", "danger")
            return redirect(url_for('administrar_crear_usuario'))
        Usuario(nombre=nombre, email=email, password=password, rol=rol, activo=True).guardar()
        flash(f"Usuario '{nombre}' ({rol}) creado correctamente.", "success")
        return redirect(url_for('dashboard'))
    return render_template('crear_usuario_admin.html')

@app.route('/admin/producto/eliminar/<int:prod_id>')
@requiere_nivel(5) # Habilitado para empleados o admins
def administrar_eliminar_producto(prod_id):
    if GestorInventario.eliminar_producto(prod_id):
        flash("Producto eliminado del inventario.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/producto/editar-stock/<int:prod_id>', methods=['POST'])
@requiere_nivel(5)
def administrar_editar_stock(prod_id):
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto:
        nuevo_stock = int(request.form.get('nuevo_stock', 0))
        producto.stock = nuevo_stock
        while producto.stock > 0 and len(producto.en_espera) > 0:
            proximo = producto.en_espera.pop(0)
            producto.usuario_id = proximo.id
            producto.estado = 'pendiente'   
            producto.stock -= 1
            if producto.stock == 0:
                producto.alquilado = True
        db.session.commit()
        flash(f"Stock de '{producto.titulo}' actualizado con éxito.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/producto/editar/<int:prod_id>', methods=['GET', 'POST'])
@requiere_nivel(5)
def administrar_editar_producto(prod_id):
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if not producto:
        flash("Producto no encontrado.", "danger")
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        producto.titulo          = request.form.get('titulo')
        producto.genero          = request.form.get('genero')
        producto.precio_alquiler = float(request.form.get('precio'))
        producto.stock           = int(request.form.get('stock', 0))
        especifico = request.form.get('especifico')
        if producto.tipo_producto == 'pelicula':
            producto.formato    = especifico
        else:
            producto.plataforma = especifico
        file_imagen = request.files.get('imagen')
        if file_imagen and file_imagen.filename != '':
            nombre_imagen = secure_filename(file_imagen.filename)
            file_imagen.save(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], nombre_imagen))
            producto.imagen = nombre_imagen
        db.session.commit()
        flash(f"Producto '{producto.titulo}' actualizado correctamente.", "success")
        return redirect(url_for('dashboard'))
    return render_template('editar_producto.html', producto=producto)

@app.route('/admin/alquiler/confirmar/<int:prod_id>')
@requiere_nivel(5)
def confirmar_alquiler(prod_id):
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto and producto.confirmar_alquiler():
        flash(f"Alquiler de '{producto.titulo}' confirmado para {producto.usuario.nombre}.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/alquiler/rechazar/<int:prod_id>')
@requiere_nivel(5)
def rechazar_alquiler(prod_id):
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto and producto.rechazar_alquiler():
        flash(f"Solicitud de '{producto.titulo}' rechazada. Stock repuesto.", "info")
    return redirect(url_for('dashboard'))

@app.route('/admin/devolucion/confirmar/<int:prod_id>')
@requiere_nivel(5)
def confirmar_devolucion(prod_id):
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto:
        proximo = producto.confirmar_devolucion()
        if proximo:
            flash(f"Devolución confirmada. '{producto.titulo}' asignado a {proximo.nombre} (lista de espera).", "info")
        else:
            flash(f"Devolución de '{producto.titulo}' confirmada. Producto de vuelta en stock.", "success")
    return redirect(url_for('dashboard'))


# =========================================================================
# RUTAS DE AUTENTICACIÓN Y SESIÓN (FUSIONADAS)
# =========================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = Usuario.autenticar(request.form.get('email'), request.form.get('password'))
        if user:
            if not user.activo:
                flash("Tu cuenta aún no está verificada. Revisá tu correo.", "warning")
                return redirect(url_for('login'))
            session['usuario_id'] = user.id
            session['usuario_nombre'] = user.nombre
            session['usuario_rol'] = user.rol
            flash(f"¡Hola de nuevo, {user.nombre}!", "success")
            
            if user.es_staff():
                return redirect(url_for('dashboard'))
            return redirect(url_for('inicio'))
        flash("Credenciales incorrectas o inexistentes", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('inicio'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre, email, password = request.form.get('nombre'), request.form.get('email'), request.form.get('password')
        if Usuario.query.filter_by(email=email).first():
            flash("El correo ya está registrado.", "danger")
            return redirect(url_for('registro'))
        
        nuevo = Usuario(nombre=nombre, email=email, password=password, rol='cliente', activo=False)
        nuevo.guardar()

        try:
            token = ts.dumps(email, salt='activar-cuenta')
            link = url_for('confirmar_email', token=token, _external=True)
            msg = Message(subject="Verificá tu cuenta", recipients=[email])
            msg.body = f"Para activar tu cuenta, hacé click acá: {link}"
            mail.send(msg)
        except Exception as e:
            print(f"--- ERROR AL ENVIAR MAIL: {e} ---")

        flash(f"¡Cuenta creada! Te enviamos un mail a {email} para verificarla.", "success")
        return redirect(url_for('login'))
    return render_template('registro.html')

@app.route('/confirmar/<token>')
def confirmar_email(token):
    try:
        email = ts.loads(token, salt='activar-cuenta', max_age=86400)
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario:
            usuario.activo = True
            db.session.commit()
            return "<h1>¡Cuenta verificada!</h1><p>Ya podés cerrar esta pestaña e iniciar sesión.</p>"
        return "Usuario no encontrado."
    except:
        return "<h1>El enlace es inválido o ya venció.</h1>"
    
# =========================================================================
# CREACIÓN DE CONTEXTO E INICIALIZACIÓN DE PRUEBAS
# =========================================================================
with app.app_context():
    db.create_all()  
    
    if not Usuario.query.filter_by(email="admin@alquiler.com").first():
        Usuario(nombre="Admin", email="admin@alquiler.com", password="123", rol="admin", activo=True).guardar()

if __name__ == '__main__':
    app.run(debug=True)